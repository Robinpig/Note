## Introduction

这一页不罗列 API，只回答三件事：**慢在哪里、值不值得动手、动手有没有用**。三条规矩贯穿全文：

1. **先定义指标**。"这段代码快不快"不是问题，"p99 延迟 ≤ 20 ms"、"单核吞吐 ≥ 3k req/s"、"容器 RSS 峰值 ≤ 512 MiB"、"CLI 冷启动 ≤ 80 ms"才是。指标决定工具，也决定改动的方向：降尾延迟常常要动 GC 与并发模型，提吞吐常常只需要批量化。
2. **先测量后优化**。同一份代码里，算法与数据结构的问题通常是几个数量级，字节码层面的技巧通常是百分之几（本文所有微基准都给了实测倍率）。用后者的确定感替代前者的测量，是 Python 性能工作里最常见的浪费。
3. **动手前先排除"根本不是算力问题"**。CPU 密集的多线程不加速是 GIL 的指纹（机制与实测见 [GIL](/docs/CS/Python/GIL.md)）；事件循环里一处同步调用会把整个循环钉住（见 [Asyncio](/docs/CS/Python/Asyncio.md)）。这两类问题的解法是换并发模型，改代码风格无效。

边界：GIL 原理、asyncio 事件循环内部、ndarray 内存布局、对象与回收细节分别由 GIL.md、Asyncio.md、[NumPy](/docs/CS/Python/NumPy.md)、[Memory](/docs/CS/Python/Memory.md) 承载，本页只引用结论。文中所有 `实测` 数字来自本机 CPython 3.12.5 / macOS arm64 / 8 核（`# Python 3.12.5 实测`，取 5 次以上最小值），换机器必须重跑。

## Choose the Metric First

| 指标 | 为什么单独列 | 观测手段 |
| :--- | :--- | :--- |
| 延迟分位数 p50 / p99 / max | 平均值同时隐藏"多数很快"和"偶发极慢"两件事 | 逐请求打点自己算分位；`timeit` 只给单次统计量 |
| 吞吐 req/s 或 items/s | 加并发后 p50 变差、吞吐变高是常见结果，只看一个会误判 | 压测工具 + 固定时间窗计数 |
| CPU 时间（user / sys 分列） | 墙钟时间不等于算力消耗，`sys` 高说明在付系统调用税 | `resource.getrusage`、`time.process_time` |
| RSS 与峰值 RSS | 释放对象不等于还给内核（arena 粒度，见 Memory.md） | `ps -o rss` 采样、`memray`、`tracemalloc` |
| 启动与导入时间 | CLI / serverless 场景下这是主要成本，与稳态性能无关 | `-X importtime`、子进程墙钟 |
| 单位成本 | 前三项都能靠加机器换，成本不能 | 上述指标除以核数或实例数 |

同一段分配密集的负载（`[{'k': i, 't': (i, i)} for i in range(20000)]` 跑 2000 次），只报平均数会得出完全错误的结论：

| 统计量 | cyclic GC 开启 | GC 关闭 |
| :--- | ---: | ---: |
| mean | 0.226 ms | 0.167 ms |
| p50 | 0.215 ms | 0.165 ms |
| p99 | 0.71 – 0.82 ms | 0.18 – 0.20 ms |
| max | 0.97 – 1.20 ms | 0.23 – 0.83 ms |

关掉自动回收让中位数降约 23 %、p99 降约 4 倍——因为这段负载**没有循环引用**，GC 只是白扫。这个结论不可外推：长驻进程关掉 GC 等于选慢性 OOM，阈值怎么调见 Memory.md。

## Wall User and System Time

第一刀不切函数，切时间去哪。`resource.getrusage(RUSAGE_SELF)` 的 `ru_utime` / `ru_stime` 给出进程的 CPU 时间，和墙钟对照即可分类（实测，min of 5）：

| 负载 | wall | user | sys | 判读 |
| :--- | ---: | ---: | ---: | :--- |
| 纯 Python 循环 2e6 次 | 102.2 ms | 102.0 ms | 0.2 ms | 算力问题，去剖析 |
| `alloc` 2e5 个 dict | 46.2 ms | 41.7 ms | 4.4 ms | 算力 + 分配，注意 GC |
| `time.sleep(0.001)` x 100 | 150.4 ms | 0.1 ms | 0.3 ms | 99.7 % 在等，优化 CPU 无效 |
| `os.write` 1 字节 x 50000 | 77.5 ms | 9.4 ms | 65.8 ms | 系统调用税，先合并 |

Linux 上再下一层用 `perf stat`（IPC、cache miss、上下文切换），macOS 没有 `perf`（本机 `which perf` 无输出，故未实测），对应工具是 `powermetrics` / Instruments。CPython 的 `-X perf_jit`（3.12 起）与环境变量 `PYTHON_PERF_JIT_SUPPORT`（3.13 起）让 perf 在没有 frame pointer 的构建上也能还原 Python 栈。

## Timing Small Code With timeit

手工 `time.time()` 计一个小函数会同时踩四个坑，坑的规模都比被测对象大：

```python
import time
def f(x): return x * 2 + 1

t0 = time.time(); f(1); print(time.time() - t0)         # 1.19e-06
t0 = time.perf_counter(); f(1); print(time.perf_counter() - t0)   # 3.7e-07
# 而 f(1) 本身约 50 ns —— 读到的是计时器自己的开销
```

- **时钟选错**。`time.get_clock_info` 本机实测：`time.time` 是 `CLOCK_REALTIME`、`monotonic=False`、`adjustable=True`、resolution 1 µs；`time.perf_counter` 是 `mach_absolute_time()`、单调不可调、resolution 41.7 ns。前者会被 NTP 校时拉动，后者才是测量工具。
- **GC 干扰**。`timeit.Timer.timeit()` 源码里显式 `gc.disable()` 再恢复；手工计时的每一轮都可能被一次回收打断。实测同一段语句 9 轮：手工 + GC 开 min 3.23 ms / 离散 31 %，手工 + GC 关 2.01 ms / 21 %，`timeit.repeat` 2.16 ms / 9 %。
- **单次读数没有意义**。同一语句 `repeat=7` 的读数是 `[1.18, 1.22, 1.23, 1.22, 1.16, 1.19, 1.21] ms`，取 `min()` 而不是平均值：噪声只会让它变慢，最小值才是"这段代码本身"。
- **`number` 与 `repeat` 是两件事**。`number` 决定单次测量够不够长（盖过时钟分辨率），`repeat` 决定能取几次最小值。不确定就让 `Timer.autorange()` 自己挑：本机对 `x*2+1` 给出 `(20000000, 0.237)`。命令行 `python -m timeit -s "setup" "stmt"` 已经做好这套流程。
- **它测不到解释器启动**。`timeit` 在同一进程里循环，不含解释器初始化与 import；冷启动是另一个指标，用下一节的 `-X importtime` 与进程级计时。

## Startup Time and importtime

`python -X importtime -c "import asyncio"` 输出 `self [us] | cumulative | 模块名`，缩进表示嵌套。官方文档给的典型用法就是这个 `-c` 形式，**不要包一层脚本**：脚本本身会先进 `sys.path` 处理与 `site`，还可能已经把目标模块间接导入过，读数就被污染了。同理不要多线程跑，文档明说输出可能错乱。本机（6 次取 min）：

| 命令 | 数值 |
| :--- | :--- |
| `python3 -c pass` | 16.4 ms 墙钟 |
| `python3 -S -c pass` | 12.7 ms（`site` 与路径处理约占 3.7 ms） |
| `import asyncio` | cumulative 23.9 ms，同一命令跨批次波动到 44 ms |
| `import sqlite3` | cumulative 2.0 ms |
| `python3 -c "import asyncio"` | 总墙钟 46.1 ms |

读 `self` 与 `cumulative` 的差才找得到病灶：另一次运行（该次 asyncio 总耗时 43.7 ms）里 `asyncio.base_events` 的 self 只有 838 µs，cumulative 却 40252 µs——时间花在它拉进来的依赖上，优化它自己没用。`-X importtime=2` 会把已加载模块标成 `cached`，用来确认重复导入。启动侧的解释器红利：一部分标准库以**冻结模块**（frozen modules）内嵌在二进制里，import 时跳过文件查找与反序列化，`-X frozen_modules=off` / `PYTHON_FROZEN_MODULES` 可关掉对照；3.13 官方还专门压缩了 `typing`、`enum`、`functools`、`importlib.metadata` 等模块的导入时间。第三方包想复现这类收益属于打包与部署话题，`zipapp` / PyInstaller 的取舍见 [Packaging](/docs/CS/Python/Packaging.md)。

内存观测只补两条：`ru_maxrss` 是**峰值**不是当前值，拿它验证"释放后回落"必然徒劳（见 Memory.md）；而且它**跨平台单位不同**——本机 `ru_maxrss` 读数 14123008，按字节换算 13.5 MiB，与 `ps -o rss` 的 13856 KiB 一致，而 Linux 手册页的单位是 KiB。照抄代码到另一平台前先做这一步核对。

## Deterministic Profiling

`cProfile` 在每次函数调用与返回时打点（call/return 事件），因此**开销按调用次数摊，不按行数摊**。实测同一负载开剖析前后的倍率：

| 负载 | 无剖析 | cProfile | 倍率 |
| :--- | ---: | ---: | ---: |
| `fib(24)`（150049 次调用） | 4.3 ms | 17.4 ms | 4.1x |
| `loop(2e5)` 单个函数、零内部调用 | 9.9 ms | 10.2 ms | 1.0x |
| `sleep(0.001)` x 100 | 30.3 ms | 30.5 ms | 1.0x |
| `alloc(50000)` 个 dict | 10.4 ms | 9.2 ms | 0.9x |

两个直接推论：一是"代码风格拆成很多小函数"在剖析器下被系统性放大，占比要向真实负载复核；二是 cProfile **看不见循环内部**——一个 10 ms 的单函数在报表里只是一行 `tottime`，行级热点得靠采样剖析器。`profile` 模块不是被废弃，而是纯 Python 实现、官方明说开销显著，只在需要扩展剖析接口（它还提供 calibration 扣除打点开销）时才用。

`pstats` 里 `tottime` 是该函数自身时间（不含被调），`cumtime` 含被调，`ncalls` 是调用次数——**排序键决定你看到什么问题**：按 `tottime` 排找 CPU 热点，按 `cumtime` 排找调用链入口。还有一个默认值造成的失真：cProfile 用墙钟，阻塞时间照记。同一份"3e5 次整数运算 + 200 x 1 ms sleep"的函数（实测）：

| timer | 榜首 | 该函数 tottime |
| :--- | :--- | ---: |
| 默认（墙钟） | `time.sleep` 0.300 s | 0.020 s |
| `Profile(timer=time.process_time)` | `work` 0.022 s | `sleep` 只剩 0.001 s |

也就是说，"I/O 型函数在剖析报表里排第一"不是它变慢了，而是计时口径把它算进来了；换成 CPU 时间口径，热点立刻回到真正吃算力的地方。`sys.setprofile` 的代价形状与剖析器同源（按事件数），代价细节与低开销替代 `sys.monitoring` 见 [Bytecode](/docs/CS/Python/Bytecode.md)。

## Sampling and Memory Tracking

`py-spy` 是**外部采样剖析器**：Rust 实现，读目标进程的内存快照，不需要改代码、不需要重启进程，因此是唯一能在生产实例上直接跑的那类工具。子命令 `record`（火焰图 / speedscope）、`top`（实时按函数排名）、`dump`；选项里最有用的是只采样持 GIL 的线程（对照 GIL.md 的判读）、`--subprocesses`、以及 `--native`（需要扩展带符号，Cython 还要生成出的 C 文件）。它看到的是解释器停在安全点上的栈，聚在 native 帧或"等锁"上的样本要配合系统级工具——这条限制 Ecosystem.md 的观测性一节已经写过。

横向对照：Go 的剖析能力**内建在运行时里**（`runtime/pprof` 定时采样、`net/http/pprof` 把剖析端点直接挂到服务上，见 [pprof](/docs/CS/Go/pprof.md)），Java 侧靠 JFR 与 async-profiler，调优清单是按"堆积 / 超时 / 重试 / 分配"逐项展开的（见 [sche](/docs/CS/Java/JDK/sche.md)）；CPython 两者都没有内建，所以采样剖析由 py-spy 这种**进程外**工具补齐——代价是只能看到安全点上的栈，好处是与被测进程完全解耦。

内存侧分工：**`tracemalloc` 在标准库内**、按 Python 层分配记录栈，适合 CI 里做断言与行号级增量对比；它看不见 C 扩展里的 `malloc`，而且栈深直接决定代价——实测同一段 5e4 dict 分配（基线 9.9 ms）在 `start(1)` / `start(10)` / `start(25)` 下分别是 53.4 ms / 135.1 ms / 133.0 ms，即 **5x – 14x**。用法与典型泄漏模式见 Memory.md。**`memray`** 则**逐次追踪分配**（含 native 扩展与解释器自身），需要 `memray run` 包住进程，配 `flamegraph` / `table` / `live` / `summary` 报表，还能当 pytest 插件用 `@pytest.mark.limit_memory("24 MB")` 卡内存上限；`--native` 按需开关。采样剖析器与逐调用追踪器的取舍就在这里：前者便宜、可 attach、只有统计意义上的位置；后者贵、必须重跑、但栈是完整的。

| 场景 | 能不能重启进程 | 选它 |
| :--- | :--- | :--- |
| 开发期，想知道哪个函数吃 CPU | 能 | `cProfile` + `pstats`（按 `tottime` 排，必要时换 CPU 时间口径） |
| 开发期，热点藏在长循环里 | 能 | `py-spy record`（行/帧级采样） |
| 生产实例变慢，不能停服务、不能改代码 | 不能 | `py-spy top` / `py-spy dump` |
| 分配热点与泄漏，需要完整栈 | 能 | `memray run` + `flamegraph`；CI 里卡上限 |
| 只要一条"这次改动多吃了多少内存" | 能 | `tracemalloc` 快照对比（栈深设小，注意 5x 起） |
| 微基准 / 回归门槛 | — | `timeit`（脚本）+ `pytest-benchmark` 或 `hyperfine`（进程级） |

## Optimizations and Why They Work

每条都问一句"机制上为什么"，字节码层面的解释归 [Bytecode](/docs/CS/Python/Bytecode.md)，对象布局与内存数字归 Memory.md。实测倍率是本机数据，只用于排优先级。

| 手段 | 实测（3.12.5） | 机制依据 |
| :--- | :--- | :--- |
| 复杂度先于一切：`x in list(...)` 换成 `in set/dict` | 1000 元素里找第 500 个：2608 ns → 16 ns | 哈希表平均 O(1) vs 线性扫描；`set`/`dict` 要求元素可哈希且不可变，缓存哈希才有意义 |
| 选对容器：头部插入用 `deque` 不用 `list` | 1e4 次头部插入：0.23 ms vs 22.7 ms（约 99x） | `list.insert(0, x)` 每次整体搬移，是 O(n²)；`deque` 是分块双端 |
| 局部变量优于全局 | 1e5 次循环：2.73 ms vs 2.77 ms（**仅 1.4 %**） | `LOAD_FAST` 按下标取，`LOAD_GLOBAL` 走命名空间——但 3.11 起 PEP 659 给全局查找加了内联缓存，红利已被吃掉大半；别指望它救一个 O(n) 循环 |
| 循环内的属性查找提到循环外 | 每轮读 `B.value` 2.75 ms vs 先 `v = B.value` 1.89 ms（**省 31 %**） | 属性侧的特化只在"同一对象 + 同一类型"反复命中时才划算，循环里多一层 `LOAD_ATTR` 仍然是多一层；这与上一行合起来说明：**要不要 hoist 取决于测量，不取决于教条** |
| `str.join` 优于 `+=` | 1000 段：4.4 µs → 30.6 µs；**一旦有第二个引用**，16000 段：0.08 ms → 43.6 ms | `join` 先量总长再一次分配；CPython 的 `+=` 就地扩容只在目标对象唯一引用时成立，存进列表或写 `s = s + x` 就退化成整体复制 |
| 推导式优于手工 `append` | 1e5 元素：2.25 ms（推导式）vs 2.47 ms（`r.append(x)`）vs 2.83 ms（把 `append` 绑成局部变量） | 少一层属性查找与调用，但**"绑定 `append` 到局部"在今天反而更慢**——属性访问已被特化。生成器表达式给 `sum()` 反而更慢：3.67 ms vs 2.69 ms，多一层帧 |
| `map` / `filter` 不是魔法 | `list(map(abs, xs))` 1.07 ms 快于推导式 2.25 ms；`list(map(lambda x: x*x, xs))` 5.41 ms 慢一倍以上 | 决定成本的是**每个元素要不要跨一次 Python 调用**；内建函数免掉这层，lambda 反而多加一层 |
| `itertools` / `collections` 用 C 实现 | 展平 500 x 200 个列表：`chain.from_iterable` 0.41 ms vs `sum(LL, [])` 32.2 ms；1e5 元素计数：`Counter` 2.5 ms < 手写 `dict.get` 4.2 ms << `defaultdict(int)` 9.4 ms | 循环在 C 里跑；`defaultdict(int)` 每次未命中要进 `__missing__` 再写回，计数场景 `Counter` 才是对的工具 |
| `__slots__` | 三次属性读 46.8 ns → 44.6 ns（**速度基本无收益**），内存 344 B → 56 B | 属性从 `__dict__` 哈希查找变固定偏移，但同样被 `LOAD_ATTR` 特化抹平；它的真实收益在内存与海量实例，数字见 Memory.md，查找语义见 [Data Model](/docs/CS/Python/Data_Model.md) |
| `lru_cache` / `functools.cache` | 纯递归 `fib(25)` 7.98 ms → 缓存后 0.0035 ms（含清空） | 把指数级重复子问题变线性；代价是缓存本身常驻（实测 `@cache` 跑完 `fib(500)` 后 `cache_info().currsize` 为 501，`maxsize=None` 无上界），可哈希入参 + 内存预算是前提，否则它就是一个受控泄漏 |
| 批量优于逐条 | `os.write` 1 B x 20000：41.8 ms（其中 sys 37.1 ms）vs 4 KiB x 5：0.04 ms | 每次系统调用都是一次上下文切换与参数校验；同一逻辑适用于 DB 的 `executemany` / 批量 INSERT 与网络请求合并，见 [DB](/docs/CS/DB/DB.md) |
| `try` 只包住真正会失败的语句 | 包住整个 1e5 循环 2.759 ms vs 把 `try` 塞进循环内 2.816 ms（只差 2 %） | **这不是性能手段，是正确性手段**：范围过大除了几乎不省时间，还会误吞不属于它的异常、并让 `except` 分支里的变量可能未绑定（见 [Exceptions](/docs/CS/Python/Exceptions.md)） |
| CPU 任务并行化 | 见 GIL.md 实测（4 线程纯 Python 循环 0.964 → 0.968 s，零收益） | 多进程 / 子解释器才能吃多核，池与隔离的取舍见 [Concurrency](/docs/CS/Python/Concurrency.md) |

## Myths Worth Busting

| 迷信 | 事实 | 依据 |
| :--- | :--- | :--- |
| `del x` 让代码变快 | 6975.7 ns vs 不 `del` 6899.3 ns，噪声级差异 | 引用计数在离开作用域那一刻就释放；`del` 只影响峰值存活 |
| 用 `is` 比较字符串更快 | 同对象 5.9 vs 6.3 ns；等值不同对象 6.2 vs 6.4 ns | 差距在纳秒级，而 `==` 本来就有同一性快速路径；更严重的是 `is` 对字符串**语义就是错的**，interning 只是实现细节（边界见 Memory.md） |
| `except Exception: pass` 免费 | 不抛时的 try 块近乎零成本（20.9 ns/调用，3.11 起），抛出并捕获 134.4 ns，约 6.4 倍 | 时间上大致免费，**信息上是贵的**：吞掉异常等于放弃定位能力，代价见 [Exceptions](/docs/CS/Python/Exceptions.md) |
| 常量写成类属性比全局快 | 1e5 次循环里 `CFG.LIMIT` 3.59 ms vs 模块级 `LIM` 2.77 ms，**慢 30 %** | 多一次 `LOAD_ATTR`；类属性是组织手段，不是优化手段 |
| 上 NumPy 一定快 | 本机未安装 numpy，故**未实测**；机制上每次 ufunc 调用要付类型与形状检查、buffer 协商的固定成本，千级以下元素的逐元素 Python 循环常常更慢 | 判断要走向量化还是下沉 C，见 NumPy.md 的分界表 |
| 加线程一定提吞吐 | CPU 密集的纯 Python 加线程零收益（GIL.md 实测） | 见 GIL.md |
| 上 async 一定提吞吐 | 依赖栈里有同步实现时，退化成"带 `await` 的串行" | Asyncio.md 的"什么时候不该用"表更完整 |

## Free Wins From the Interpreter Build

不改一行业务代码、只换构建或版本就能拿到的收益，以及它们的边界：

| 机制 | 版本与开关 | 收益与代价 |
| :--- | :--- | :--- |
| PEP 659 特化自适应解释器 | 3.11 起默认 | 官方口径是两位数百分比量级；代价是首次执行要先"预热"，微基准不做 warmup 会低估 |
| Tier 2 + 实验性 JIT | 3.13 起 `--enable-experimental-jit`，运行时 `PYTHON_JIT=0/1`，3.14 官方 macOS/Windows 二进制已内置 | 只对热区、仅 amd64/AArch64，官方仍不推荐生产使用（见 Bytecode.md） |
| tail-call 解释器 | 3.14 的 `--with-tail-call-interp`，需 Clang 19+ 且 x86-64/AArch64，官方强烈建议配 PGO | pyperformance 几何平均约 **3 – 5 %**。⚠️ 这**不是** Python 函数层面的尾调用优化，与 `def f(n): return f(n-1)` 会不会爆栈无关 |
| free-threaded 构建 | 3.13 实验、3.14 官方支持（PEP 779 phase II），独立可执行文件 `python3.14t` | 3.14 起 **PEP 659 特化在该模式已启用**；多线程真并行，代价是单线程代码慢约 **5 – 10 %**，且要求扩展声明 `Py_mod_gil`（见 [GIL](/docs/CS/Python/GIL.md)） |
| PGO / LTO / BOLT | `--enable-optimizations --with-lto`（官方推荐组合）、实验性 `--enable-bolt` | 发行版与自建镜像的主要来源；好处不需要改代码，代价是构建时间与"你的构建 ≠ 官方构建"的可比性 |
| mimalloc 分配器 | 3.13 起内置，当前构建默认启用，`--without-mimalloc` 可关；free-threaded 构建**强制要求**它 | 分配密集负载受益，分层与 `PYTHONMALLOC` 归 Memory.md |
| GC 阈值调优 | `gc.set_threshold` | 本文开头那张分位数表就是它的收益形状：省的是停顿，不是算力；调错方向会变成内存压力 |

**这三类改动怎么选**：

| 情况 | 优先 | 理由 |
| :--- | :--- | :--- |
| 有明确算法/数据结构问题（O(n²) 在热路径上） | 改代码 | 数量级收益，任何解释器红利都救不了复杂度 |
| 代码已经合理，负载是分配密集或纯 CPU 循环 | 升级解释器 / 换构建 | 免费或近免费，但要重测依赖（C 扩展与 `Py_mod_gil`、ABI） |
| 稳态热点集中在少数几段、且能被向量化或 C 化 | 换实现语言 | 一次跨语言调用摊薄解释成本，代价是构建与调试矩阵 |
| 瓶颈是等待（`sys` 高或 wall ≫ user） | 都不是，改并发模型或批量化 | 见 Wall User and System Time 一节 |

## Switching the Implementation Language

| 路线 | 适用 | 开发成本 | 调试代价 |
| :--- | :--- | :--- | :--- |
| 向量化（NumPy / JAX） | 数据能表达成同构数组 | 最低，常是重写几行 | 慢在语义（误用 Python 层 `for` 逐行），不慢在工具链；分界见 NumPy.md |
| C 扩展与 Cython | 已有 C 库或需要精确控制内存 | 中：类型、引用计数、ABI | 段错误发生在解释器进程里，`faulthandler` / gdb / valgrind 才看得到；剖析要靠 py-spy `--native` 或 memray native 模式 |
| Rust + PyO3 / maturin | 新写的安全敏感热点、要发多平台 wheel | 中：借用检查 + `maturin` 构建链 | 崩溃同样落在宿主进程；GIL 与 `Py_mod_gil` 声明要自己处理 |

三条路共享一个前提：**C 扩展是成本的放大器**——每个（平台 × ABI × 是否 free-threaded）都要有二进制 wheel，这套发布矩阵属于 Ecosystem.md 与 Packaging.md，不在性能收益之外白送。

## Benchmark Traps

- **一个基准定结论**。`timeit` 测的是单点微基准，它变快了不等于端到端变快了；反过来，只跑端到端又看不出是谁退化的。至少两层都要有。
- **基准套件选对语境**。CPython 官方跟踪的是 `pyperformance`（仓库 `python/pyperformance`，本文不引用其站点域名），版本间的"快了几个百分点"就是它的几何平均；它是 CPython 自身的回归集，与你生产负载的相关性要自己验证——用自己的数据重跑，别把它的百分比当承诺。
- **机器状态会进读数**。CPU 频率爬坡、散热降频、后台进程、其他 VM 争抢、GC 与内存回收都会污染结果。做法：绑核、预热、`min()` 而不是平均值、多轮、对照组同机同时刻。本文里 `import asyncio` 的 cumulative 在同机不同批次间从 23.9 ms 漂到 44 ms，就是这种漂移的实例。
- **微基准外推到生产是错的**。缓存效应、真实数据分布、并发争用都不在你构造的循环里。进程级比较可以交给 `hyperfine`（自带 warmup 与统计）或 `pytest-benchmark`（把基准钉进回归），但两者都替代不了"先定义指标"。

## A One Page Triage Flow

1. **写下现象与指标**：是 p99 高、吞吐低、内存涨、还是启动慢。四个方向的工具链不同。
2. **分类**：`resource.getrusage` 或 `/proc` 采样，比较 wall / user / sys（本文第一刀）。wall ≫ user + sys → 在等；sys 占比高 → 系统调用太多；user 主导 → 算力。
3. **排除结构性原因**：等的是 IO 就查并发模型（Asyncio.md），CPU 密集且加了线程没效果就查 GIL（GIL.md）——这两类都不是"代码写得慢"。
4. **选工具拿热点**：能重启用 `cProfile`（注意调用次数失真与计时口径），不能重启用 `py-spy`；内存方向用 `memray` 或 `tracemalloc`。
5. **提一个假设并量化上限**：这段热点占总时间 8 %，就算优化到 0 也只快 8 %——先算 Amdahl，再决定是改它还是改数据结构。
6. **改一处，测一次**：多个改动同时上，就再也不知道哪个有效。留一个基线对照。
7. **回归防护**：把关键路径的指标做成 CI 里的基准（`pytest-benchmark` / `memray` 的内存上限标记），否则下一个人会把它改回去。

## Links

- [Python](/docs/CS/Python/Python.md)
- [memory](/docs/CS/memory/memory.md)
- [Debug](/docs/CS/SE/Debug.md)
- [APM](/docs/CS/SE/APM.md)
- [Compiler](/docs/CS/Compiler/Compiler.md)

## References

- [timeit — Measure execution time of small code snippets](https://docs.python.org/3/library/timeit.html)
- [The Python Profilers](https://docs.python.org/3/library/profile.html)
- [resource — Internet-specific resource usage functions](https://docs.python.org/3/library/resource.html)
- [tracemalloc — Trace memory allocations](https://docs.python.org/3/library/tracemalloc.html)
- [Python Command line and environment](https://docs.python.org/3/using/cmdline.html)
- [Configure Python](https://docs.python.org/3/using/configure.html)
- [What's New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [PEP 659 — Specializing Adaptive Interpreters](https://peps.python.org/pep-0659/)
- [PEP 779 — Criteria for supported status for free-threaded Python](https://peps.python.org/pep-0779/)
- [py-spy](https://github.com/benfred/py-spy)
- [memray](https://github.com/bloomberg/memray)
- [pyperformance](https://github.com/python/pyperformance)
- [PyO3](https://pyo3.rs/)
- [maturin](https://maturin.rs/)
- [Cython](https://github.com/Cython/Cython)
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/en/stable/)
- [hyperfine](https://github.com/sharkdp/hyperfine)
