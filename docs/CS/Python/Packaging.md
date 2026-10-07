## Introduction

Python 的打包体系常被抱怨"工具太多、概念太碎"，根因不在工具质量，而在模型本身：Python 没有一份能同时回答"我要什么 / 这次确切装什么 / 装进哪个解释器"的文件，也没有把版本选择算法钉进语言工具链（Go 用 MVS 做了这件事）。于是**环境、声明、解析**这三件事分别落在 `venv`、`pyproject.toml`、`uv.lock` 上，而每一层都还有历史替身在流通。绝大多数"到底该用 pip 还是 Poetry"式的困惑，都是把这三层混为一谈的结果。

本篇讲这套模型的机制与判断逻辑，横向对照对象是 Go 的 [Module](/docs/CS/Go/Module.md)。单个工具的完整命令面不在此展开，`uv` 的细节见 [uv](/docs/CS/Python/uv.md)。

## Environment, Declaration, Resolution

| 三件事 | 要回答的问题 | Python 的载体 | Go 的对应物 |
| :--- | :--- | :--- | :--- |
| 环境 | 装到哪个解释器、与谁隔离 | `venv` / `virtualenv` / conda env / uv 自动建的 `.venv` | 没有：`go build` 产物静态自包含，依赖在编译期就折进去了 |
| 依赖声明 | 允许哪些版本范围 | `pyproject.toml` 的 `[project].dependencies`、`requirements.txt` | `go.mod` 的 `require` |
| 解析与锁 | 这次确切装哪些版本、内容是什么 | `uv.lock` / `poetry.lock` / 编译出的 pinned requirements / `pylock.toml` | `go.sum`（只锁字节，不锁选择） |

Go 之所以能省掉锁，是因为 MVS 是**确定性算法**：同一份 `go.mod` 在任何机器、任何时间都解出同一组版本（它取"能满足全部约束的最小版本"，而不是最新版），所以声明文件本身就可复现，只差一层哈希校验。Python 的解析默认目标是"满足约束的最新版"，同一份 `pyproject.toml` 周一和周五会解出两套版本——**锁因此必须是一个独立文件**，而它一独立，就必然与声明文件产生"新鲜度"问题。三件事分离不是设计失误，而是"最新版优先"这条默认策略的必然后果。

另外两处常被混淆：`pip` 自己声明它不是 workflow 工具，只往"已经存在的那个解释器"里装包，环境从哪来它不管；`pip freeze` 给出的是**整个环境的快照**，而不是"本项目依赖解析出的最小集合"。

## The pyproject.toml Foundation

`pyproject.toml` 不是一份规范，而是四份规范叠在同一个文件上：

| PEP | 引入的表 / 键 | 解决的问题 |
| :--- | :--- | :--- |
| PEP 518 | `[build-system]`（`requires` 是唯一必填键）、`[tool.*]` | 声明"构建本项目要先装什么"，前端才能先建隔离环境再跑构建；`[tool.$NAME]` 只有该名字的所有者可用 |
| PEP 517 | `build-backend`、`backend-path` | 前后端之间的钩子协议：必选 `build_wheel` / `build_sdist`，可选 `get_requires_for_build_wheel` / `prepare_metadata_for_build_wheel`；并建议前端**默认**为每次构建建隔离环境 |
| PEP 621 | `[project]` | 元数据从"执行 `setup.py` 才知道"变成静态可读 |
| PEP 735 | `[dependency-groups]` | 存只在开发时才需要的包组，且**不进入任何发行版元数据** |

PEP 621 的价值常被低估。在此之前，安装器要拿到一个包的依赖，唯一办法是**先装好构建依赖、再执行那个尚未装好的项目的任意代码**——"要跑文件才知道装什么、要装了才能跑文件"这个循环正是 PEP 518 动机一节写明的代价。元数据静态化之后，索引与解析器只读一个 TOML 就能拿到依赖图，这也是后来解析器能做快能做准的前提。

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "note-demo"
version = "0.1.0"
description = "打包模型示例"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1,<9",
    "tomli>=2.0; python_version<'3.11'",   # 3.11 起标准库已有 tomllib
]

[project.optional-dependencies]
# extras 面向"用我包的人"，会写进发行版元数据，会被当作依赖装
cli = ["rich>=13"]

[project.scripts]
note-demo = "note_demo.__main__:main"

[dependency-groups]
# 开发组只给贡献者，不会出现在下游项目的依赖里
dev = ["pytest>=8", "ruff"]

[tool.setuptools.packages.find]
where = ["src"]     # src-layout 的包发现，见 Project Layout
```

## Migration From setup.py and requirements.txt

| 旧机制 | 现在的定位 | 迁移判断 |
| :--- | :--- | :--- |
| `setup.py` | 仍是合法入口，也是那些不认识 pyproject 的老工具的兼容面 | 只有**动态元数据**（从 git tag 推版本、生成 C 扩展、按平台改 `ext_modules`）才值得留；纯声明一律搬进 `[project]` |
| `setup.cfg` | 与 `[project]` 等价的另一种写法，属过渡形态 | 新项目不要再用；旧项目下次动元数据时顺手搬走，不必单独开一次迁移 |
| `requirements.txt` | 表达"某个环境要装什么"，**不是**包的依赖声明 | 发布库的依赖必须写进 `pyproject.toml`；写在 requirements 里的东西下游安装者拿不到 |

`install_requires` 与 requirements 文件的区别官方专门写了一节，因为它是最常见的误用：前者是"我对下游的承诺"（版本范围，解析器会读），后者是"我这次要装的清单"（通常全 pin，只对自己有意义）。依赖只写进 requirements 的库，别人 `pip install` 你时什么都装不到。

## Wheels and SDists

sdist 是"源码 + PKG-INFO"的 tar.gz，安装它意味着**在目标机器上再跑一次构建**：要编译器、要 `[build-system].requires` 那套隔离环境、要能连索引。wheel 是解压即装的 ZIP。二者的差别不在体积而在"构建发生在哪里"——只要允许 sdist，可复现性就从"锁文件"转移到了"构建机的状态"，同时多出一段安装期执行任意代码的窗口。

wheel 文件名的语法是 `{name}-{version}-{python}-{abi}-{platform}.whl`，三个 tag 用 `-` 连接，每个 tag 允许 `.` 分隔的复合值（压缩 tag 集）。以下文件名摘自 PyPI 上的实际发行物：

| 文件名 | 读法 |
| :--- | :--- |
| `requests-2.9.2-py2.py3-none-any.whl` | 同一份源码兼容 2/3，无扩展模块，任何平台 |
| `cryptography-50.0.2-cp39-abi3-manylinux_2_34_x86_64.whl` | CPython 扩展，用稳定 ABI，3.9 起任一版本可装，glibc ≥ 2.34 |
| `orjson-3.9.9-cp39-cp39-musllinux_1_1_x86_64.whl` | 绑定 3.9 专属 ABI，musl 1.1，换 Python 小版本就要换包 |
| `rpds_py-0.22.0-cp313-cp313t-manylinux_2_17_aarch64.manylinux2014_aarch64.whl` | free-threaded 构建；末尾是同一平台的两个别名（新名 + 旧名） |

| 段 | 含义 | 常见取值 |
| :--- | :--- | :--- |
| python tag | 需要哪个实现与版本 | `py` 通用（不依赖实现特性）/ `cp` CPython / `pp` PyPy / `jy` Jython / `ip` IronPython，后接版本号 |
| abi tag | 需要哪个 Python ABI | `none` 纯 Python / `cp312` 绑定该小版本 / `abi3` 走 PEP 384 稳定 ABI / 带 `t` 后缀者为 free-threaded 构建 |
| platform tag | 需要哪个平台 | `any` / `win_amd64` / `macosx_11_0_arm64` / `manylinux_2_17_x86_64`（x、y 是 glibc 主次版本，含义"glibc x.y 及以上可用"）/ `musllinux_1_2_x86_64` |

manylinux 各版本**向前兼容**（旧标的包能装在新系统上，反之不行）；`manylinux1` / `manylinux2010` / `manylinux2014` 是历史别名，2014 对应 glibc 2.17，所以常见到新旧两个名字点在一起写。从纯 Python 到 Rust 扩展共四条链，决定你要发多少份 wheel：

| 链 | 工具 | tag 结果与代价 |
| :--- | :--- | :--- |
| 纯 Python | setuptools / hatchling / flit 系后端 | `py3-none-any`，一份通吃所有实现与平台 |
| C 扩展 | setuptools + 平台编译器 | `cpXY-cpXY-<platform>`，小版本 × 平台的笛卡尔积；只有代码只用 `Py_LIMITED_API`（PEP 384）才能标 `abi3`，让一份 `cp39-abi3` 服务 3.9 之后的所有版本 |
| Cython | 先转 C，再接上一条 | 静态编译换运行期性能的取舍见 [Performance](/docs/CS/Python/Performance.md)；绑了 NumPy C-API 的扩展（见 [NumPy](/docs/CS/Python/NumPy.md)）其 ABI 还随 NumPy 大版本变，`abi3` 救不了这一段 |
| Rust | `maturin` + PyO3，或 `setuptools-rust` | 产物仍是 CPython 扩展；`maturin` 自己就是 PEP 517 后端，直接读 `pyproject.toml`，不需要 `setup.py` |

这个笛卡尔积通常交给 cibuildwheel 批量产出（在各架构的原生 runner 或 QEMU 里跑），那一层与依赖解析无关，属发布工程。free-threaded 构建再把这个矩阵翻一倍：PEP 703 规定 `--disable-gil` 构建的 **ABI tag 含字母 `t`**（官方可执行文件也叫 `python3.13t`），装错套直接 `import` 失败；3.14 起 Windows 上编译 free-threaded 扩展时 `Py_GIL_DISABLED` 必须由构建后端显式给出。机制见 [GIL](/docs/CS/Python/GIL.md)。

## Version Numbers and Specifiers

PEP 440 的公共版本形态：`[N!]N(.N)*[{a|b|rc}N][.postN][.devN]`，另允许 `+local` 只用于本地构建。

- **epoch `!`**：当上游换了版本方案、光比数字会"降级"时的强制抬升手段（`2.0` 之后发 `1!1.0`）。
- 排序规则（PEP 440）：`1.0.dev1 < 1.0a1 < 1.0b2 < 1.0rc1 < 1.0 < 1.0.post1 < 1!0.1`。
- SemVer 的 `-` 预发布写法与 `+build` 写法**不被允许**出现在公共版本字段里，Git 哈希也不行——PEP 440 明确点名这两条。所以"照抄 npm 版本号"在 Python 上会直接发布失败。

| 写法 | 等价展开 | 实测边界 |
| :--- | :--- | :--- |
| `~=2.2` | `>=2.2, ==2.*` | 2.9 允许、3.0 拒绝 |
| `~=1.4.5` | `>=1.4.5, ==1.4.*` | 1.4.9 允许、1.5.0 拒绝（最后一位固定，倒数第二位可变） |
| `==1.2.*` | 前缀匹配 | 1.2.7 允许、1.3 拒绝 |
| `>=1.0,!=1.5` | 差集 | 1.5 被剔除 |

⚠️ 预发布的排除发生在**安装器的候选筛选**，而不是 specifier 集合的成员判断。`pip` 默认只找 stable，要 `--pre` 才纳入 pre/dev release；但 `Version('1.1rc1') in SpecifierSet('>=1.0')` 实测返回 `True`（`packaging` 对显式传入的 Version 对象放行预发布）。把这两件事混为一谈，会误判"我这么写会不会哪天装到 rc"。

environment marker（`python_version<"3.11"`、`sys_platform=="win32"`、`extra=="cli"`）由安装器**在解析时按当前解释器求值**，所以同一份元数据在不同环境里依赖集不同——Python 锁文件的跨平台可移植性天然比 `go.mod` 差，`pip lock` 的文档就直接写明"生成的锁文件只在当前 Python 版本与平台下保证有效"。

`MAJOR.MINOR.PATCH` 在 Python 只是习惯，不是契约：语言层面没有"不兼容大版本必须换导入路径"的机制（Go 用 `/v2` 后缀把它变成编译期错误），所以破坏性升级全靠 specifier 上界表达。生态的普遍建议是**库不要给自己的依赖加 `<2` 这类上界**（除非已确认某个不兼容点），上界留给应用层锁文件——两个库各自写死不一致的上界，回溯解析当场就无解，而用户无法通过升级任何一个来脱身。

PyPI 上出问题时的补救手段是 **yank**（发行物上的 `data-yanked` 属性，带一个原因字符串），不是删除：安装器在能选到非 yanked 版本时必须忽略 yanked 版本，只有用户显式指名才可能装上；yank 可以撤回。结论是把已发布的版本号当不可回收资源——宁可发 `.post1` 修一次，也别指望把 `1.2.3` 收回来重发。

## Resolution and Lock Files

dependency hell 的成本在 Python 里是具体的：解析器要为每个候选拿到元数据，而历史上的手段是**下载候选发行物并执行它的构建脚本**（pip 文档明说解析过程需要下载所用到的包的发行文件），回溯就是在这棵"下载—试—退回"的树上搜索，最坏情况指数级。pip 的解析器自 20.3 起支持回溯，底层求解库是 `resolvelib`；提速的前提不在算法，而在 PEP 621（声明侧元数据可静态读）与 PEP 658（发行物侧核心元数据可单独取）。

回溯式解析不承诺唯一解：候选遍历顺序、索引此刻能看到哪些版本、marker 何时求值都会影响结果。所以"把解写下来"不是保守，而是自洽——锁文件是 Python 模型里的一等公民。

| 方案 | 声明 | 锁 | 环境 | 定位 |
| :--- | :--- | :--- | :--- | :--- |
| pip + `requirements.txt` | requirements 文件（或读 pyproject） | 无（`pip freeze` 是环境快照，不是解） | 不管 | 只是安装器，故意不做项目管理 |
| pip-tools | `requirements.in` | `pip-compile` 出全量 pinned 清单，可带哈希 | 自己配 `venv` | 改动最小的编译式锁，兼容既有 pip 工作流 |
| Poetry | `pyproject.toml` + `[tool.poetry]` | `poetry.lock` | `poetry env` | 一体化项目管理器，自有方言较多 |
| uv | `pyproject.toml`（PEP 621） | `uv.lock` | 自动建 `.venv`，还能装解释器 | 见下 |

PDM 与 Hatch 也在这套标准生态里：PDM 走"严格遵循标准 + 自己的锁"，Hatch 的重心在多环境矩阵与发布流水线。

`uv` 的定位是把 pip + venv + pip-tools + pyenv + Poetry 的职责合成一个二进制：resolver、installer、项目管理器、Python 版本管理器。工作流上值得记住的不是命令名而是**新鲜度规则**：`uv add` / `uv remove` 改声明并同步重解，`uv lock` 只重解，`uv sync` 把 `uv.lock` 装进 `.venv` 并默认删掉锁里没有的东西；`pyproject.toml` 收紧到把已锁版本排除在外才算过期，**上游发了新版不算过期**，锁必须显式更新；已有锁时 uv 优先沿用已锁版本。CI 里用 `--locked`（过期即报错、不改文件），`--frozen` 则是完全跳过检查照锁装。`uv pip` 是给"只想换掉 pip、不想换工作流"的迁移期用的兼容表层。细节见 [uv](/docs/CS/Python/uv.md)。

标准侧最近有了新变化：PEP 751 已定稿，给出跨工具的锁格式 `pylock.toml`，pip 26.x 也带了实验性的 `pip lock` 默认输出该文件。旧资料里"Python 没有标准锁文件"这句大体仍成立，但它正在失效。

## Virtual Environments

| 工具 | 管什么 | 与 PyPI 的关系 | 适用 |
| :--- | :--- | :--- | :--- |
| `venv`（标准库，3.3 起） | 一个隔离的解释器目录与它的 `site-packages` | 只是给 pip 提供一个可写目标 | 够用且零依赖，脚本与容器里首选 |
| `virtualenv` | 同上，是 `venv` 的超集（标准库当年只并入了它的一个子集） | 同上 | 需要更快创建、或给任意解释器建环境 |
| `conda` | **Python 包之外的东西**：原生依赖（C 库、CUDA、MKL）、Python 解释器本身、非 Python 工具 | 自有 channel 索引；纯 Python wheel 可由 `conda-pypi` channel 纳入同一次求解 | 科学计算、需要非 Python 二进制 |
| uv 建的 `.venv` | 就是标准 venv 目录，另能下载并 pin 解释器版本 | 直接吃 PyPI | 新项目默认 |

conda 与 pip 混用的经典事故有明确根因：两者写的是**同一个 `site-packages`**，但 conda 的账本里看不到 pip 装的东西，于是下一次 `conda install` / `conda update` 会按自己的元数据决策，把 pip 装的版本降级或覆盖，留下"装了 A 之后 B 就坏"且无从回滚的状态。官方给的规避顺序是：能走 `conda-pypi` channel 就走（这样它参与同一次求解）；否则先 `conda install pip`，用**环境内**的那个 pip；把所有 conda 操作做完再引入 pip；一旦混用，就别再指望靠 conda 修同一批依赖。见 [conda](/docs/CS/Python/conda.md)。

PEP 668 常被误解成"发行版在为难用户"：发行版在 stdlib 目录放一个 INI 文件 `EXTERNALLY-MANAGED`（`[externally-managed]` 段）标记**整个解释器安装**归外部包管理器，pip 见到就拒绝往里装，逃生舱 `--break-system-packages` 被规范自己要求"应当带有使用风险的含义"。它针对的是真实故障：`apt` / `dnf` 与 pip 争同一棵目录树，两边都没有对方的账本，一次 `sudo pip install` 要么覆盖发行版维护的文件，要么被下一次发行版升级静默清掉。这个标记没有替任何人解决环境管理，只是把"先建环境再装包"变成硬约束。

## Project Layout

flat 与 `src/` layout 的差别不是审美，而是一个假成功：运行脚本时解释器把**脚本所在目录**插到 `sys.path` 最前（`python -c` / `-m` 时插的是当前工作目录，实测 `sys.path[0]` 是空字符串），于是 flat 布局下 `import demo_pkg` 命中的是源码树本身，而不是安装进 `site-packages` 的那份。3.12.5 实测：

```text
# flat：源码目录被直接 import 成功，什么都没装
$ python run.py
imported: /private/tmp/lay-demo/flat/demo_pkg/__init__.py

# src layout：未安装时 import 失败，强制你先走一遍安装
$ python run.py
ModuleNotFoundError: No module named 'demo_pkg'
```

后果是 flat 布局的测试全绿可能什么都没验证：包数据文件没被打进 wheel、entry point 从没注册、`importlib.metadata.version()` 报错，这些只有在"真的装了"的路径上才暴露。官方对两种布局差异的第一条描述正是"src layout 需要安装才能运行代码，flat layout 不需要"。机制原理见 [Import](/docs/CS/Python/Import.md) 的 sys.path 构造一节。

- `tests/` 与 `src/` 同级，不要放进包内：放进去会被打进 wheel，还会让测试运行器收集到安装副本。
- 插件机制的取舍：PEP 420 的隐式命名空间包（**没有** `__init__.py` 的目录）允许多个发行版共同往同一顶层包名下挂子模块，是"目录级插件"的标准做法；代价是这个顶层名字没有唯一定义点，撞名即静默合并，且打包发现与类型检查工具对它的处理历来比常规包粗糙。要给用户提供扩展点，entry point 注册通常是更稳的选择。

## Building and Publishing

```shell
python -m build                                  # PEP 517 前端：dist/*.tar.gz + dist/*.whl
twine check dist/*                               # 元数据与 README 渲染
twine upload --repository testpypi dist/*        # 先在 TestPyPI 上验一遍
twine upload dist/*
```

`build` 是**前端**：它按 `[build-system].requires` 建隔离环境，再调用 `build-backend` 的钩子。这层前后端分离的全部意义就是"换构建后端不需要改工作流"，反过来也成立——你的 CI 不该假定项目用的是 setuptools。

凭据与溯源分两件事。PyPI 的 Trusted Publishing 用 CI 平台的 OIDC 身份令牌换一枚短期上传凭据，仓库与密钥库里就不再需要长期 API token（凭据泄露是发包事故的头号来源）。与之配套的索引侧数字 attestation（PEP 740）记录"哪个源被构建成了哪个发行物"。前者管"谁传的"，后者管"从哪来的"，合起来才让版本溯源成为可能。

索引与镜像：解析范围由 `--index-url`（默认 `https://pypi.org/simple`）与 `--extra-index-url` 控制，而 PEP 503 的 simple API 就是索引协议本身——自建私有仓库只需实现这套 HTTP 接口。慢网络换镜像（本库 [Python](/docs/CS/Python/Python.md) 里已有的用法）：

```shell
pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

私有 index 与公共 index 并列时要当心：两者对解析器是**并列候选集**而不是"私有的优先"，公开 PyPI 上有人抢注同名包就可能顶掉你的内部包，所以内部包名必须带组织前缀。

供应链的最低配置是锁文件带哈希 + 安装时开 hash-checking。`--require-hashes` 是**全有或全无**的：清单里任何一行出现 `--hash` 就全局生效，届时所有条目（含全部传递依赖）都必须写明版本与哈希、必须用 `==` 钉死，漏一个直接报错。再配 `--only-binary :all:` 禁掉 sdist，才真正消掉"安装期执行构建代码"这一段。官方把这套模式定位成"省力版私有索引"——它提供完整性，不提供可用性（索引挂了照样装不上）。

## Contrast With Go Modules

| 维度 | Python | Go |
| :--- | :--- | :--- |
| 版本选择 | 回溯式解析，倾向满足约束的最新版；解不唯一 ⇒ 必须写下来 | MVS：取能满足全部声明的**最小**版本，纯由 `go.mod` 决定 |
| 声明文件 | `pyproject.toml` 的 `[project].dependencies` | `go.mod` 的 `require` |
| 锁 | `uv.lock` / `poetry.lock` / `pylock.toml`（版本 + 哈希，格式刚定稿） | 没有版本锁；`go.sum` 只有哈希，不参与选择 |
| 完整性校验 | 可选（`--require-hashes`），默认不校验 | 默认强制，缺 `go.sum` 记录直接失败 |
| 可重现 | 需锁 + 平台与 marker 一致，跨平台锁更难 | 同一 `go.mod` 到处同一解，产物静态自包含 |
| 把依赖带进仓库 | wheelhouse / 私有 index / `--only-binary` | `go mod vendor` 一条命令 |
| 环境 | 必须先造一个环境 | 无环境概念 |
| 私有源鉴权 | 私有 index + 凭据，另有包名抢注风险 | `GOPROXY` / `GOSUMDB` / `GOPRIVATE`，走 VCS 凭据与代理 |
| 不兼容大版本 | 靠 specifier 上界 + 人守约定 | `module path/v2` 强制换导入路径，编译期即冲突 |

一句话：Go 把确定性做进了算法，所以只需要哈希；Python 把确定性外包给锁文件与工具，于是哈希、锁、环境三件事都得自己管。

## Which Tool for Which Job

| 场景 | 环境隔离 | 依赖管理 |
| :--- | :--- | :--- |
| 一次性脚本 | 不必建环境，或用临时环境 | 有第三方依赖就用 PEP 723 内联元数据，别为脚本单开 requirements |
| 要发到 PyPI 的库 | 本地一个 `uv venv` 或 `venv` | 只声明不锁；extras 表达可选功能，锁绝不进 `[project].dependencies` |
| CLI 工具（用户用 tool runner 装） | 由安装工具建隔离环境 | `[project.scripts]` 给入口；依赖不写上界，把锁留给下游 |
| Web 服务 / 生产部署 | 容器内一个 venv，由锁驱动 | 锁 + 哈希 + `--only-binary :all:`，CI 用 `--locked` / `--frozen`；部署与镜像细节见 [Ecosystem](/docs/CS/Python/Ecosystem.md) |
| 数据与科学计算（CUDA 等原生依赖） | conda env（不要与 pip 混用同一环境） | conda 先求解，pip 只补漏；`conda-pypi` 优先 |
| 多包 monorepo 本地联调 | 单环境 + workspace | uv workspace 承担 Go `go.work` 的角色 |

## Links

- [Python](/docs/CS/Python/Python.md)
- [README](/docs/CS/Python/README.md)
- [Rust](/docs/CS/Rust/Rust.md)
- [C](/docs/CS/C/C.md)

## References

- [PEP 517 – A build-system independent format for source trees](https://peps.python.org/pep-0517/)
- [PEP 518 – Specifying Minimum Build System Requirements for Python Projects](https://peps.python.org/pep-0518/)
- [PEP 621 – Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
- [PEP 735 – Dependency Groups in pyproject.toml](https://peps.python.org/pep-0735/)
- [PEP 658 – Serve Distribution Metadata in the Simple Repository API](https://peps.python.org/pep-0658/)
- [PEP 503 – Simple Repository API](https://peps.python.org/pep-0503/)
- [PEP 723 – Inline script metadata](https://peps.python.org/pep-0723/)
- [PEP 751 – A file format to record Python dependencies for installation reproducibility](https://peps.python.org/pep-0751/)
- [pyproject.toml specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
- [Is setup.py deprecated?](https://packaging.python.org/en/latest/discussions/setup-py-deprecated/)
- [install_requires vs requirements files](https://packaging.python.org/en/latest/discussions/install-requires-vs-requirements/)
- [PEP 425 – Compatibility Tags for Built Distributions](https://peps.python.org/pep-0425/)
- [Platform compatibility tags](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)
- [Binary distribution format (wheel)](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
- [PEP 600 – Future manylinux Platform Tags for Portable Linux Built Distributions](https://peps.python.org/pep-0600/)
- [PEP 384 – Defining a Stable ABI](https://peps.python.org/pep-0384/)
- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [PEP 440 – Version Identification and Dependency Specification](https://peps.python.org/pep-0440/)
- [PEP 508 – Dependency specification for Python Software Packages](https://peps.python.org/pep-0508/)
- [File yanking](https://packaging.python.org/en/latest/specifications/file-yanking/)
- [Simple repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/)
- [pip dependency resolution](https://pip.pypa.io/en/stable/topics/dependency-resolution/)
- [pip repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/)
- [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)
- [pip lock](https://pip.pypa.io/en/stable/cli/pip_lock/)
- [Pip is not a workflow management tool](https://pip.pypa.io/en/stable/topics/workflow/)
- [resolvelib](https://github.com/sarugaku/resolvelib)
- [pip-tools](https://github.com/jazzband/pip-tools)
- [Poetry dependency specification](https://python-poetry.org/docs/dependency-specification/)
- [Hatch](https://hatch.pypa.io/latest/)
- [PDM](https://github.com/pdm-project/pdm)
- [uv projects](https://docs.astral.sh/uv/concepts/projects/)
- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [venv – Creation of virtual environments](https://docs.python.org/3/library/venv.html)
- [virtualenv](https://virtualenv.pypa.io/en/latest/)
- [conda: installing non-conda packages](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-pkgs.html)
- [PEP 420 – Implicit Namespace Packages](https://peps.python.org/pep-0420/)
- [PEP 668 – Marking Python base environments as externally managed](https://peps.python.org/pep-0668/)
- [src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [build](https://build.pypa.io/en/stable/)
- [twine](https://twine.readthedocs.io/en/stable/)
- [Using TestPyPI](https://packaging.python.org/en/latest/guides/using-testpypi/)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- [PEP 740 – Index support for digital attestations](https://peps.python.org/pep-0740/)
- [maturin](https://maturin.rs/)
- [PyO3](https://pyo3.rs/)
- [setuptools-rust](https://github.com/PyO3/setuptools-rust)
- [cibuildwheel](https://cibuildwheel.pypa.io/en/stable/)
- [Cython](https://github.com/cython/cython)
