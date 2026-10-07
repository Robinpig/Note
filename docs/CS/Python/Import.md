## Introduction

`import` 不是编译期链接指令，而是**运行时的一段 Python 逻辑**：查缓存表、依次问几个 finder 要 spec、让 loader 把字节码灌进新模块对象、最后把名字绑到当前作用域。因为全链路都在运行时且完全由**字符串名字 + 路径**驱动，导入失败几乎总能归到四类根因：`sys.path` 里没有那个位置、包结构不满足 finder 的假设、循环导入撞上"部分初始化"的模块、本地文件把标准库的名字吃掉了。本篇讲的是这套机制与排查判断，打包、发布与虚拟环境不在范围内，见 [Packaging](/docs/CS/Python/Packaging.md)。

## The Import Protocol

```
import a.b.c → __import__('a.b.c', globals, locals, [], 0)   # import 语句语义上就是这次调用
  → 查 sys.modules['a.b.c']                                  # 命中即返回，跳过后面所有步骤
  → 未命中：先逐级导入父包 a、a.b；父包的 __path__ 决定子包搜索范围
  → 遍历 sys.meta_path，第一个返回非 None 的 finder 胜出并给出 ModuleSpec（PEP 451）
  → importlib.util.module_from_spec(spec) 建空模块对象
  → **先写进 sys.modules**，再 spec.loader.exec_module(module) 执行
      （执行抛异常则把条目摘掉，实测失败的模块不会留下半截缓存）
  → 只把顶层名字 a 绑进当前作用域
```

`sys.meta_path` 的默认内容（本机实跑；3.12 里这三项是**类本身**，不是实例）：

```python
>>> for f in sys.meta_path: print(f)
<class '_frozen_importlib.BuiltinImporter'>        # sys.builtin_module_names 里的 C 内置模块
<class '_frozen_importlib.FrozenImporter'>         # 编译进解释器二进制的 frozen 模块
<class '_frozen_importlib_external.PathFinder'>    # 基于 sys.path 的文件 / zip 搜索
```

顺序即优先级，**自定义 finder 必须插到最前面才抢得到活**。`PathFinder` 产出的 spec（`# Python 3.12.5 实测`，路径省略前缀）：

```python
>>> s = importlib.util.find_spec('json')
>>> s.name, s.origin, s.submodule_search_locations
('json', '.../python3.12/json/__init__.py', ['.../python3.12/json'])
>>> s.loader                    # json.decoder 用同类 loader，但 submodule_search_locations 是 None
<_frozen_importlib_external.SourceFileLoader object at 0x100f58ef0>
>>> importlib.util.find_spec('sys')     # 内置模块：origin 是 'built-in'，loader 是 BuiltinImporter
ModuleSpec(name='sys', loader=<class '_frozen_importlib.BuiltinImporter'>, origin='built-in')
```

四个入口别混用：

| 入口 | 返回 | 名字绑定 | 要点 |
| :--- | :--- | :--- | :--- |
| `import a.b.c` | — | 只绑顶层 `a` | `b.c` 靠属性链；实测 `import email.mime.text` 后 `dir()` 里只有 `email` |
| `from x import y` | — | 绑 `y` | 先**完整执行整个 x**（含链上所有 `__init__.py`）再取 `y`，比 `import x` 多干活 |
| `importlib.import_module('a.b.c')` | **`a.b.c` 本身** | 不绑 | 运行时按字符串导入，首选 |
| `builtins.__import__(...)` | 顶层包；实测给了 `fromlist=['quote']` 才返回 `email.utils` | 不绑 | 与语句同语义但参数晦涩，仅用于复刻语句行为 |

## sys.path Construction

- **第 0 项随启动方式变**：`python -c` 模式实测 `sys.path` 共 5 项，第 0 项是字面量 `''`（与 `python312.zip`、`.../python3.12`、`.../python3.12/lib-dynload`、`site-packages` 一起构成搜索链）。跑脚本时第 0 项是**脚本所在目录**的绝对路径，`python -m` 时是**当前工作目录**；3.11 起 `-P` / `PYTHONSAFEPATH=1` 直接去掉它。这条差异正是"在 A 目录能跑、从 B 目录调用就 `ModuleNotFoundError`"的根因。
- `PYTHONPATH` 插在**第 0 项之后、stdlib 之前**：能盖住第三方，也会被项目里的同名文件盖住 stdlib。`PYTHONHOME` 改的则是 `sys.prefix` / `sys.exec_prefix`，即 stdlib 与 site-packages 的**根**，设错会让解释器连 `encodings` 都找不到而启动失败。`site-packages` 由 `site` 追加、`-S` 可跳过；其中 `.pth` 每行是一个附加路径，**以 `import ` 开头的行在每次解释器启动时都会被执行**（`site` 文档明写）——`pip install -e` 靠它，它因此也是隐蔽的启动期代码执行面。

## Packages, Modules, Namespace Packages

`__init__.py` 有两层职责：把目录**标记**为常规包，并在包被导入时**执行**一次。子模块不会自动可见——`from pkg import sub` 能成是因为它触发对 `sub` 的按需导入，而非 `__init__.py` 预先导入了它。PEP 420 的隐式命名空间包（3.3+）取消了"必须有 `__init__.py`"，三类对象的差异全落在 spec 字段上（`# Python 3.12.5 实测`）：

| 类型 | `spec.origin` | `spec.loader` | `submodule_search_locations` | `__file__` |
| :--- | :--- | :--- | :--- | :--- |
| 普通模块 | `.py` 路径 | `SourceFileLoader` | **None** | `.py` 路径 |
| 常规包 | `__init__.py` 路径 | `SourceFileLoader` | **单元素 list** | `__init__.py` 路径 |
| 命名空间包 | **None** | **None** | **`_NamespacePath`** | 值为 None（`has_location` 为 False） |

最后一列是关键判断：**`submodule_search_locations` 是否为 None 决定它能不能当父包**——非 None 会被赋给 `__path__`，`import x.y` 才有搜索范围；为 None 就是叶子模块，会报 `'x' is not a package`。命名空间包的奇特组合正是 `loader` 为 None（没有可执行代码）却仍能当父包用。而 `PathFinder` 要扫完整条 `sys.path` 才下结论，由此得到两条容易踩空的实测规则：

- **常规包优先于命名空间候选，哪怕后者更靠前**：`p1/nr`（无 `__init__.py`）+ `p2/nr`（有）→ 选中 `p2/nr/__init__.py`，且 `__path__` **只剩这一项**，`p1/nr/m1.py` 变成 `ModuleNotFoundError`。这是"文件明明在，却导不到"的典型现场。
- **纯命名空间包跨目录合并**：`p1/nspkg` 与 `p2/nspkg` 都无 `__init__.py` 时，`nspkg.__path__` 同时含两个目录、两边子模块都可导入。`google.protobuf.*`、`zope.*` 分散在多个发行包里就是这个机制；但给任意一个目录补上 `__init__.py`，合并立刻失效。

## Circular Imports

最小复现（`# Python 3.12.5 实测`）：`a.py` 是 `from b import val_b` + `val_a = "A"`，`b.py` 是 `from a import val_a` + `val_b = "B"`。

```
$ python3 -c "import a"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/private/tmp/circ2/a.py", line 1, in <module>
    from b import val_b
  File "/private/tmp/circ2/b.py", line 1, in <module>
    from a import val_a
ImportError: cannot import name 'val_a' from partially initialized module 'a' (most likely due to a circular import) (/private/tmp/circ2/a.py)
```

根因只有一条：**模块在开始执行前就被放进 `sys.modules`**，于是第二个 `import` 拿到的是一张**已注册但还没跑完**的表；`from` 要在表上查具体 key，而赋值还没执行到。这与"找不到模块"无关——`a` 明明在 `sys.modules` 里，坏的是它的**属性绑定进度**。同一场景改成属性访问，报错变成 `AttributeError: partially initialized module 'a' has no attribute 'get'`，本质相同。解法按代价从低到高：

1. **`from x import y` 改成 `import x`，用时写 `x.y`**：取值时机从模块执行期推迟到调用期，多数环当场消失——实测上面那对模块改成 `import b` / `import a` 后双向都能正常加载。
2. **import 挪进函数体**：适合只被某条分支用到的重依赖，代价是把启动期错误变成运行期错误。
3. **重构出共同依赖**：环几乎总是说明某层依赖方向画反了，把共用类型 / 常量抽到第三个模块比任何技巧都稳。
4. **纯类型注解造成的环**：`if TYPE_CHECKING:` 里导入 + 注解惰性求值，另见 Typing 笔记。3.14 起 PEP 649 让注解默认不再急切求值，3.13 及之前仍需 `from __future__ import annotations`。

⚠️ **易误判点**：只导入子模块时环常常不报错，于是开发者以为"环是 `from` 的锅"。真实条件是"两个模块在**各自执行期间**去读**对方尚未绑定的名字**"——若跨模块引用都发生在函数调用期，或被引用一侧恰好在 `import` 之前完成了赋值，环只是转了一圈而不出错。判断依据是 `python3 -v` 打出的实际导入顺序，不是读代码的感觉。

## Shadowing and Search Order

第 0 项搜索路径意味着**项目根的同名文件必然吃掉标准库**。放一个只定义了 `dumps()` 的 `json.py` 在项目根：

```
$ python3 -c "import json; print(json.__file__); import json.scanner"
/private/tmp/shadow/json.py
ModuleNotFoundError: No module named 'json.scanner'; 'json' is not a package
```

被依赖的名字一旦缺失，报错现场会**远离**真正起因，因为标准库会反过来 import 你的假模块。实测：项目根放一行 `randrange = 1` 的 `random.py`，`python3 -c "import secrets"` 报 `ImportError: cannot import name 'SystemRandom' from 'random' (/private/tmp/shadow2/random.py)`；脚本自身就叫 `random.py` 且 `import random` 时，3.12 给的是彻底误导人的 `AttributeError: partially initialized module 'random' has no attribute 'SystemRandom' (most likely due to a circular import)`——把遮蔽说成了循环导入。**3.13 起**这类报错改进为附带 `(consider renaming '/home/me/random.py' ...)`，一句话说中根因。排查动作固定两条：`python3 -c "import xxx; print(xxx.__file__)"` 看它到底从哪来；检查项目根有没有与 stdlib / 第三方同名的 `.py`（含上次调试留下的临时文件）。工具要分清：`-X importtime` 是**测每个模块导入耗时**的，与遮蔽无关，别当诊断手段混用，看导入链路要用 `-v`。编译缓存同样不参与名字解析，但会制造"改了代码没生效"的错觉——`__pycache__/*.pyc` 头部存了源文件 mtime 与 size（实测都在那 16 字节里），校验不过就自动重编，PEP 552 另有 hash-based 变体，细节见 [Bytecode](/docs/CS/Python/Bytecode.md)。

## Non-filesystem Sources and Bundled Data

`sys.path_hooks` 注册了 `zipimporter` 与 `FileFinder.path_hook`，所以 `sys.path` 上的 `.zip` / `.pyz` 条目可直接当目录用。实测把包压进 zip 后，`mypkg.__spec__.loader` 是 `<zipimporter object "/tmp/ziptest/app.zip/">`，而 `mypkg.__file__` 变成 `'/tmp/ziptest/app.zip/mypkg/__init__.py'`——一个 `open()` 必然抛 `NotADirectoryError` 的**逻辑路径**。这就是"**zip 安全**"问题的全部来源：`open(__file__)` 与 `os.path.join(os.path.dirname(__file__), 'data.json')` 在 zipapp、PyInstaller 产物、只读 wheel 里都会崩，读随包数据必须走 `importlib.resources`（3.9+ 用 `files()`）——实测同一 zip 里 `files('mypkg').joinpath('data.txt').read_text()` 正常返回内容。frozen imports 是另一条非文件路径：`importlib._bootstrap`、`zipimport` 自身都编译进解释器二进制，实测其 `spec.origin == 'frozen'`、loader 是 `FrozenImporter`；3.11 起 `-X frozen_modules=on|off` 控制是否启用（源码树运行默认 off，安装版默认 on）。

## Entry Points and Plugins

`importlib.metadata` 把"发行包声明的可加载入口"变成运行时可查的表，这是插件生态的地基：`pip install` 生成的 console script、pytest 插件发现、SQLAlchemy dialect 都走它。3.12 实跑：

```python
>>> import importlib.metadata as md
>>> type(md.entry_points()).__name__, type(md.entry_points(group='console_scripts')).__name__
('EntryPoints', 'EntryPoints')
>>> list(md.entry_points(group='console_scripts'))[:2]        # group= 是 3.10 才加的关键字
[EntryPoint(name='wheel', value='wheel.cli:main', group='console_scripts'),
 EntryPoint(name='pip', value='pip._internal.cli.main:main', group='console_scripts')]
>>> md.entry_points()['pip']             # 3.12 的 [] 按 **name** 查，可用
EntryPoint(name='pip', value='pip._internal.cli.main:main', group='console_scripts')
>>> md.entry_points()['console_scripts'] # 按 group 查的老写法（3.9 返回 dict）已不成立
KeyError: 'console_scripts'
```

API 断层要记牢：**3.9 的 `entry_points()` 返回按 group 键控的 dict**；3.10 引入 `select()` 与 `group=`；**3.12 起一律返回 `EntryPoints` 集合**。跨版本统一写 `entry_points().select(group=...)`（3.10+）或依赖 `importlib_metadata` 回填包。`EntryPoint.load()` 才真正把 `'wheel.cli:main'` 解析成对象——"发现"很廉价，"加载"走的就是前面那套 finder 协议。发行包元数据与 console script 的生成归 [Packaging](/docs/CS/Python/Packaging.md)。

## Custom Finders

骨架（基类与方法签名本机验证可用，逻辑已简化）：

```python
import sys
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec

class DemoFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("demo_"):
            return None                              # 交还给下一个 finder，不要抛异常
        return ModuleSpec(fullname, DemoLoader(fullname))
class DemoLoader(Loader):
    def create_module(self, spec): return None       # None => 用默认方式建模块对象
    def exec_module(self, module):                   # 真正干活处：把代码灌进 module.__dict__
        exec(compile(SOURCE[module.__name__], "<demo>", "exec"), module.__dict__)
sys.meta_path.insert(0, DemoFinder())                # 位置决定优先级
sys.path_importer_cache.clear()   # 路径/文件变动后必须失效缓存
```

值得写的场景很少，且共享一个特征：**代码不来自文件系统上的常规位置**——配置驱动的动态模块、测试期替身、插件热重载、REPL 里按需编译。只想改搜索顺序或改版本，就用 `sys.path` 操作、虚拟环境或 monkeypatch，别接管整套协议。⚠️ 代价必须提前告知：自定义 finder 是**纯运行时行为**，mypy / pyright 与 IDE 跳转只看文件和 `py.typed`，看不见你的 `meta_path`，结果是代码能跑但**无法补全、无法跳转、类型检查报 `Cannot resolve import`**，PyInstaller / Nuitka 的依赖图也扫不出来。除非别无选择，不要把导入做成隐式魔法。

## Contrast With Go Module

| 维度 | Python import | Go module |
| :--- | :--- | :--- |
| 解析依据 | 运行时在 `sys.path` 上线性搜索一个**名字** | 编译期把 import path 映射到**模块路径 + 版本** |
| 版本选择 | 语言层无版本概念，同名只有一份，由安装顺序决定 | MVS 在所有 `require` 约束下取满足全部要求的最小版本集 |
| 可复现构建 | 靠 lock 文件与 lock tool（uv、Poetry），**解释器本身不管**，且 `requirements.txt` 与 import 语句无强制一致 | `go.sum` 哈希校验 + `require` 声明内置于工具链，缺声明直接报错 |
| vendoring | 手工把目录塞进 `sys.path`，或 `pip install --target` | `go mod vendor` + `-mod=vendor`，一等公民 |
| 环依赖 | 允许，退化为 `partially initialized module` | **禁止**，`import cycle not allowed` |

Go 把"依赖是谁"交给构建期声明与 lock，Python 把"名字解析到哪"交给运行时路径；Python 侧任何版本或来源问题都不该指望 import 机制解决——那是 [Packaging](/docs/CS/Python/Packaging.md) 的边界。

## Links

- [Python](/docs/CS/Python/Python.md)
- [Data_Model](/docs/CS/Python/Data_Model.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [Module](/docs/CS/Go/Module.md)
- [term](/docs/CS/term.md)

## References

- [5. The import system](https://docs.python.org/3/reference/import.html)
- [How `sys.path` is initialized](https://docs.python.org/3/library/sys_path_init.html)
- [importlib — The importlib package](https://docs.python.org/3/library/importlib.html)
- [importlib.metadata — Accessing package metadata](https://docs.python.org/3/library/importlib.metadata.html)
- [importlib.resources — Package resource access](https://docs.python.org/3/library/importlib.resources.html)
- [zipimport — Import modules from Zip archives](https://docs.python.org/3/library/zipimport.html)
- [PEP 420 — Implicit Namespace Packages](https://peps.python.org/pep-0420/)
- [PEP 451 — A ModuleSpec Type for the Import System](https://peps.python.org/pep-0451/)
- [PEP 552 — Deterministic `pyc` files](https://peps.python.org/pep-0552/)
- [Python command line and environment variables](https://docs.python.org/3/using/cmdline.html)
