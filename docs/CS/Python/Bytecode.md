## Introduction

CPython 把源码编译到**字节码（bytecode）为止**，产物是 `code object`，由 `Python/ceval.c` 里的求值循环逐条解释执行；它**不编译成机器码**。这与 [Go 编译](/docs/CS/Go/compile.md)（AOT 直出原生可执行文件）和 C（编译器直出机器码）是两条路线，对照见 [编译原理](/docs/CS/Compiler/Compiler.md)。

但"Python 是纯解释执行"这句话在 3.11 之后已经不准确：3.11 引入**特化自适应解释器**（PEP 659），3.13 引入**实验性 JIT** 与 Tier 2 微指令，3.14 引入 **tail-call 解释器**并让官方 macOS/Windows 二进制带上实验性 JIT。准确说法是：**以字节码解释为主干、按运行热度自适应特化、可选地把热路径编译到机器码**。

## Compilation Pipeline

CPython 的执行前置流程大致是：

```
token 化 → PEG 解析器 → AST → 符号表（symtable）→ 生成字节码 → code object → 求值
```

- 自 3.9 起用 **PEG 解析器**（`pegen`）取代旧的 LL(1) + `pgen` 语法，报错定位更好。
- 解析直接产出 **AST**（抽象语法树），`ast` 模块可以拿到它。
- `symtable` pass 决定每个名字是局部、全局、自由变量还是 cell，这一步的结果直接决定了后面用哪种 `LOAD_*` 指令。
- 编译器 pass 把 AST 降级为字节码并折叠常量，最终得到一个 `code object`。

关键区别：Python **止步于字节码**，不会 AOT 产出机器码；解释器在运行时消费字节码。

## Code Objects and the Stack Machine

`compile(source, filename, mode)` 直接返回一个 `code object`，`mode` 取 `'exec'` / `'single'` / `'eval'`。`ast.dump()` 看到的是**结构**（表达式树），而 `dis` 看到的是把结构拉平后的**执行序列**——两者是同一份源码的两种视图，前者接近解析结果，后者接近编译产物。

CPython 的字节码是**基于栈的虚拟机**（stack machine），操作数压入值栈、指令从栈顶取。下面是一个极小函数的**真实**反汇编（`# Python 3.12.5 实测`）：

```
def f(a, b):
    return a + b

  2           0 RESUME                   0
  3           2 LOAD_FAST                0 (a)      # 把局部 a 压栈
              4 LOAD_FAST                1 (b)      # 把局部 b 压栈
              6 BINARY_OP                0 (+)      # 弹出两个、相加、结果压栈
             10 RETURN_VALUE                        # 弹出栈顶作为返回值
```

生成器表达式会额外编译成一个**子 code object**，主函数里只是把它 `MAKE_FUNCTION` 出来再迭代：

```
def g(xs):
    return sum(x*x for x in xs)

# 主体：
              2 LOAD_GLOBAL              1 (NULL + sum)   # 取全局 sum
             12 LOAD_CONST               1 (<code object <genexpr> ...>)
             14 MAKE_FUNCTION            0                 # 造出内层生成器函数
             16 LOAD_FAST                0 (xs)
             18 GET_ITER
             20 CALL                     0
             28 CALL                     1
             36 RETURN_VALUE
```

`code object` 上几个最常用的元信息（`# Python 3.12.5 实测`，函数体 `def f(a,b): "doc"; c=a+b; return c`）：

| 字段 | 值 | 含义 |
| :--- | :--- | :--- |
| `co_consts` | `('doc',)` | 常量池；嵌套的 code object / 元组字面量也在这里 |
| `co_varnames` | `('a', 'b', 'c')` | 局部变量名（含参数），`LOAD_FAST` 按下标寻址 |
| `co_names` | `()` | 全局 / 属性名表，`LOAD_GLOBAL`、`LOAD_ATTR` 用它 |
| `co_stacksize` | `2` | 该帧值栈的最大深度 |

⚠️ **指令名、条数、顺序随版本剧烈变化**——`RESUME`、`CALL` vs `CALL_FUNCTION`、`FOR_ITER` 的跳转编码、生成器是否单独 code object，在不同小版本里都不一样。**不要背指令表**，跨版本脚本不要假设任何具体 opcode 名；需要时永远当场 `dis` 一次。观测用 `dis.get_instructions()`（每条给 `opname`/`argval`/`argrepr`/`offset`/`starts_line`/`positions`）或 `dis.Bytecode(codeobj)`；要看指令后预留的内联缓存槽，用 `dis.dis(obj, show_caches=True)`。

## Pyc Cache Files

模块首次导入时，CPython 会把编译好的字节码写进 `__pycache__`，文件名带**缓存 tag**：`x.py` → `__pycache__/x.cpython-312.pyc`（`# Python 3.12.5 实测`）。tag 里的 `312` 是主.次版本，不同版本互不复用；优化级别还会追加后缀，`-O` 得 `cpython-312.opt-1.pyc`，`-OO` 得 `cpython-312.opt-2.pyc`。

校验方式（PEP 552）有三种：

- **timestamp**（默认）：`.pyc` 头里存源码的 mtime + size，导入时比对源码，不一致就重编译。
- **checked-hash**：头里存源码内容的哈希，导入时重算校验。
- **unchecked-hash**：只认哈希、不再查源码时间，用于源码被有意改动的场景（如冻结 / 部署）。

命令行开关是 `python -m compileall --invalidation-mode {checked-hash,timestamp,unchecked-hash}`（`# Python 3.12.5 实测`），设了 `SOURCE_DATE_EPOCH` 时默认变成 `checked-hash` 以获得可复现产物。

常见行为：`sys.dont_write_bytecode`（或环境变量 `PYTHONDONTWRITEBYTECODE` / `python -B`）为真时不写 `.pyc`；目录只读时写入会**静默失败**，退化为每次重新编译；`python -OO` 会**剥掉 docstring 与 assert**。注意区分：自 3.13 起编译器**自动剥掉 docstring 每行的公共前导空白**（只为省体积），这与 `-OO` 把整个 docstring 删掉是两回事。源码级发布（只给 `.pyc` 不给 `.py`）技术上可行，但不提供真正的保护。

## Specializing Adaptive Interpreter

动态语言的每次运算都要重新判定类型：同一条 `BINARY_OP` 这一秒是两个 `int` 相加，下一秒可能是字符串拼接。传统做法每次都走一遍通用的类型分派，这正是解释器最大的常数开销。

PEP 659（3.11 起）的思路是**指令特化 + 内联缓存（inline cache）**：解释器观察到某条指令在某个位置上反复作用于同一种类型后，**原地**把它改写为更专门、更快的家族成员（quickening），并在指令后预留的 `CACHE` 槽里记住已验证的类型。`show_caches=True` 能看到 `BINARY_OP` 后面紧跟一个 `CACHE` 单元，`LOAD_GLOBAL` / `LOAD_ATTR` 后面预留更宽的缓存槽（多个 `CACHE`），用来记住已经验证过的类型与查找结果。

收益量级：PEP 659 正文自己的说法是"个别操作特化收益约 10%–60%、实验估计可达 ~50%，即便整体只有 25% 也值得"——即**两位数百分比量级**，主要来自属性查找、全局变量、调用三块。CPython 没有稳定的公开 API 读取特化命中计数（个别版本有 `sys._` 前缀的内部函数，随版本变动），要看效果请以 `dis` 与 profiling 为准。

## Tier 2 Micro-ops and the Experimental JIT

3.13 在特化解释器之上再加一层 **Tier 2**：把特化后的一级（Tier 1）字节码进一步拆成更细的**微指令（micro-ops / uops）**，解释循环先跑 uops；一条被判定为"热"的 uop 桶，可选地由**实验性 copy-and-patch JIT** 编译成机器码。⚠️ 别把"JIT 关着"和"仍在跑 uop 循环"混为一谈：`--enable-experimental-jit` 的默认值 `no` 是**整条 Tier 2 与 JIT 管线都不编译进去**，此时解释器跑的就是 Tier 1 特化字节码；只有 `interpreter` / `yes-off` 这类构建才保留 uops 解释循环（`yes-off` 的 JIT 可用 `PYTHON_JIT=0` 关掉）。官方 macOS / Windows 的 3.14 二进制属于后者。

- 源码构建开关 `--enable-experimental-jit`，取值 `no` / `yes` / `yes-off` / `interpreter`；Windows 用 `PCbuild/build.bat --experimental-jit[-interpreter]`。
- 运行时用环境变量 `PYTHON_JIT=0/1` 开关。
- 3.14 的官方 macOS/Windows 二进制**开始内置实验性 JIT**，但官方文档仍**不推荐生产使用**（`--enable-experimental-jit=yes-off` 语义：编进去、默认关、靠 `PYTHON_JIT=1` 手动开）。

它只在 amd64 / aarch64 上、只对热区起作用，绝大多数代码仍走解释。所以更别把 Python 说成"完全没有 JIT"，也别把它理解成 Java 那种成熟 JIT。

## Tail Call Interpreter in 3.14

3.14 引入一种**新的类型解释器实现**：不再用单个巨大的 C `switch` 分发 opcode，而是让每个 opcode 的实现是一个小 C 函数，函数之间用 **tail call** 互相跳转，省掉外层 switch 的开销。

- 目前仅支持 **Clang 19+**、且限定 **x86-64 / AArch64**。
- 需 `--with-tail-call-interp` **显式开启**，官方强烈建议配合 **PGO** 一起构建。
- 初步基准：pyperformance 几何平均约 **3–5%**（基线是"3.14 + Clang 19 但不开该解释器"）。

⚠️ **这不是 Python 函数层面的尾调用优化（TCO）**。CPython 至今不实现 Python 函数的尾调用优化；这里的 "tail call" 指的是**解释器内部 C 函数之间**的分派方式，与 `def f(n): return f(n-1)` 会不会爆栈无关。

## Observability and Debugging

- `sys.settrace` / `sys.setprofile` 是最通用的钩子，但代价极高：`settrace` 让**每一行**都回调 Python 函数，运行时可能慢到数量级。
- PEP 669 的 `sys.monitoring`（3.12 起）是低开销替代：按事件粒度注册回调，未启用某类事件时近乎零成本。观测/覆盖率工具优先走它。
- `faulthandler` 在段错误、`SIGSEGV` 等致命信号或超时时 dump 各线程的 Python traceback，用于定位原生崩溃。
- `python -X importtime` / `PYTHONPROFILEIMPORTTIME` 读的是 **import 阶段**的耗时；启动整体分析属于性能专题，交给同目录的 Performance 笔记。

## Practical Judgments

真正有效的，几乎都是**减少运行时查找**或**少写一层 Python 循环**：

| 做法 | 为什么有效 |
| :--- | :--- |
| 把全局量绑成局部变量 | `LOAD_GLOBAL` 要走命名空间查找（含缓存），`LOAD_FAST` 直接按数组下标取值 |
| `__slots__` | 属性从 `__dict__` 哈希查找变为固定偏移访问，配合 `LOAD_ATTR` 特化 |
| 用内建 / C 扩展代替手写循环 | 循环在 C 里跑，绕开逐条字节码解释 |
| 列表 / 字典推导式 | 一次性构建，通常快于等价的 `for` + `append` |

同一个"比较 `x < N`"的循环，把 `N` 写成全局还是先绑成局部，编译结果直接不同（`# Python 3.12.5 实测`，截取自循环体）：

```
def use_global(xs):        #   def use_local(xs):
    s = 0                      n = N
    for x in xs:           #   s = 0
        s += x < N         #   for x in xs:
    return s               #       s += x < n
# ... LOAD_GLOBAL 0 (N)   #  ... LOAD_FAST 1 (n)   ← 少一次全局查找
```

至于"迷信"：`del x` 不会让代码变快（CPython 用引用计数，变量离开作用域本就立即释放，提前 `del` 只是省一点峰值内存）；用 `x<<1` 代替 `x*2`、用 `//` 技巧代替除法，在现代 CPython 里往往不比特化后的 `BINARY_OP` 更快，反而牺牲可读性。**先测量再优化**，别靠字节码传说下手。

## Decompilation and Tooling

`.pyc` 是 `marshal` 序列化的 `code object`（外加头部），`marshal.loads(marshal.dumps(code))` 可在本机 round-trip 验证结构。逆向层面存在反编译工具这一**类别**（把字节码还原成 AST 再还原成源码），但字节码随版本变化，任何反编译器都强绑定某个版本区间，不保证语义完全还原——不要在生产里依赖它。正经用途是理解编译器降级行为时 `dis` + `ast.dump` 对照着看。

## Links

- [Python](/docs/CS/Python/Python.md)
- [C](/docs/CS/C/C.md)
- [Memory](/docs/CS/Python/Memory.md)
- [GIL](/docs/CS/Python/GIL.md)
- [Performance](/docs/CS/Python/Performance.md)
- [Import](/docs/CS/Python/Import.md)

## References

- [dis — Disassembler for Python bytecode](https://docs.python.org/3/library/dis.html)
- [code — Object representing executable Python code](https://docs.python.org/3/library/code.html)
- [PEP 659 — Specializing Adaptive Interpreter](https://peps.python.org/pep-0659/)
- [PEP 669 — Low impact monitoring for CPython](https://peps.python.org/pep-0669/)
- [PEP 552 — Deterministic .pyc files](https://peps.python.org/pep-0552/)
- [What's New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [CPython Configure Options](https://docs.python.org/3/using/configure.html)
- [A Quick Intro to the Execution Model](https://docs.python.org/3/reference/executionmodel.html)
- [CPython Internals — Compiler](https://devguide.python.org/internals/compiler/)
