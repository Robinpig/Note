## Introduction

全局解释器锁（Global Interpreter Lock，GIL）是 CPython 解释器内部的一把互斥锁：任一时刻只允许一个线程执行 Python 字节码。它常被误解为"保护用户对象不被并发访问"，其实恰恰相反——GIL 保护的是**解释器自身的内部状态**与**引用计数的原子性**，而不是替你保证应用级数据结构的线程安全。理解这一层，才能看懂"IO 密集多线程有效、CPU 密集多线程无效"这个反复被误传的现象，也才能看懂 3.13/3.14 用 free-threading（PEP 703 / PEP 779）拆掉这把锁时，代价到底落在了哪里。

这一篇是 Python 子树的"并行能力边界"页：讲锁的机制、切换的真实逻辑、绕过它的历史路径，以及拆掉它之后编程模型的变化，最后给一张选型判断表。API 罗列交给具体库文档。

## Why CPython has a GIL

CPython 的内存管理以引用计数为主：几乎每一次取属性、传参、赋值都会 `ob_refcnt` 加一或减一。如果两个线程同时改同一个对象的引用计数，这个"加一/减一"就可能丢更新，进而提前释放或永不释放对象——解释器内部的空闲链表（free list）、对象分配器、类型缓存等共享结构同理。GIL 的思路很简单：与其给每一处引用计数都加原子操作或细粒度锁（单线程会付出持续开销），不如在顶层放一把大锁，让"任意时刻只有一个线程在跑字节码"成为全局不变式。

由此，GIL 顺带带来三个好处：

- **C 扩展写法简单**：扩展作者可以默认"进入 Python/C API 时独占解释器"，引用计数的 `Py_INCREF/Py_DECREF` 不需要原子版本。
- **单线程没有锁开销**：热路径上每次对象访问不必再套一层原子指令或互斥量。
- **内部状态天然一致**：分配器与缓存的多步更新不会被别的线程插队。

代价则是：纯 Python 的多线程无法利用多核，CPU 密集的并行度被锁死在单核。这也是这篇笔记存在的原因。

## Lock granularity and switching

GIL 不是"每执行 100 条字节码就切一次"——那是 **Python 3.2 之前**的旧模型（旧资料常见的"每 100 条字节码"说法对应 3.2 前的 `sys.setcheckinterval()` 默认值 100，单位是解释器"tick"，**已过时**）。3.2 起切换改为按时间片，由 `sys.getswitchinterval()` 控制：

```python
import sys
print(sys.getswitchinterval())     # 0.005  # Python 3.12.5 实测，即默认 5 ms
```

一个持有 GIL 的线程运行约 5 ms 后，解释器请求它释放 GIL、交给另一个等待中的线程。**但切换间隔只决定"多久换手一次"，也就是公平性与响应性；它并不决定"能不能多核并行"**——只要 GIL 存在，同一时刻仍只有一个线程能执行字节码，无论间隔调多小。CPU 密集多线程不加速的根因是"独占执行"这个事实本身，不是切换频率。

真正让多线程对 IO 有效的，是**在阻塞期间主动放开 GIL**：

- 标准库的阻塞式 IO（socket 读写、文件操作）与 `time.sleep()` 在系统调用前会释放 GIL，进入等待，返回后再抢回来。
- C 扩展用 `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` 宏，在跑一段纯 C、不碰 Python 对象的长计算前放开 GIL，算完再取回——NumPy 的重活正走这条路，所以 NumPy 场景下多线程能吃满多核。
- 非 Python 创建的线程（外部原生线程回调 Python）用 `PyGILState_Ensure()` 抢锁（必要时为该线程建立 `PyThreadState`）、用完 `PyGILState_Release()` 归还，二者必须成对。

一句话判断：一段代码是否受益于多线程，看它执行时**手上有锁还是手上没锁**——忙等在 IO 或无锁的 C 计算里就并行，跑纯 Python 字节码就串行。

## CPU-bound benchmark

本机 CPython 3.12.5、8 核 macOS arm64。用纯 Python 计数循环（无 IO、无扩展释放 GIL），让 1/2/4 个线程分摊**同样的总工作量**，取 3 次最小值：

```python
import threading, time
N = 40_000_000
def count(n):
    x = 0
    for _ in range(n):
        x += 1
    return x
count(5000)                       # 预热，排除首次特化偏差

def run_k(k):                     # k 个线程分摊同样的总工作量
    hs = [threading.Thread(target=count, args=(N // k,)) for _ in range(k)]
    t0 = time.perf_counter()
    for h in hs:
        h.start()
    for h in hs:
        h.join()
    return time.perf_counter() - t0

for k in (1, 2, 4):
    print(k, round(min(run_k(k) for _ in range(3)), 3))

# Python 3.12.5 实测:
# 1 -> 0.964
# 2 -> 0.967
# 4 -> 0.968
```

三个线程数几乎完全一样、甚至略微变慢：机器有 8 核却一点没吃到并行，这正是 GIL 的指纹。同一台机器上把负载换成阻塞 IO（4 次 `time.sleep(0.3)`），串行是 1.232 s，4 线程并发降到 0.308 s——约 4 倍。同一段 `sleep` 因为释放了 GIL 就立即并行起来，反证了上一节的判断逻辑。

## Bypassing the GIL before free-threading

在拆锁之前，绕过它的成熟路径有四条：

- **多进程**：每个进程有独立解释器与独立 GIL，天然多核；代价是进程隔离带来的启动开销与对象不能直接共享（fork / spawn 的差异见 [Concurrency](/docs/CS/Python/Concurrency.md)）。
- **`concurrent.futures.ProcessPoolExecutor`**：把多进程包成任务池，是 CPU 密集 Python 的默认答案。
- **在 C 扩展里释放 GIL**：重活下沉到无锁的 C/BLAS 代码，多线程只负责调度，于是能并行（上一节 NumPy 的例子）。
- **per-interpreter GIL（PEP 684，3.12）**：让每个子解释器持有自己的 GIL，解释器之间即可真并行，而每个解释器内部仍是单锁模型。

## free-threading with PEP 703 and PEP 779

free-threading 不再"绕过"而是"移除"GIL。PEP 703 定稿、随 3.13 以**实验性**引入；PEP 779 定义了转正标准，3.14 起进入 **phase II：官方支持、但仍可选**——是否推进到 phase III（成为默认乃至唯一构建）**尚未决定**。关键落点：

- 独立可执行文件 `python3.13t` / `python3.14t`；源码构建用 `--disable-gil`；官方 macOS/Windows 安装器可选装。
- 运行时开关：环境变量 `PYTHON_GIL`、命令行 `-X gil=0`（关）/ `-X gil=1`（开）；`sys._is_gil_enabled()` 查询进程内是否真的没锁。`python -VV` 与 `sys.version` 含 `free-threading build`。
- 3.14 起 **PEP 659 特化自适应解释器在 free-threaded 模式下已启用**；单线程代码的惩罚约 **5–10%**（视平台与 C 编译器），换来的是多核并行。
- Windows 上从 3.14 起为 free-threaded 构建编译扩展时，`Py_GIL_DISABLED` 需由构建后端**显式指定**，编译器不再自动判定；运行中的解释器用 `sysconfig.get_config_var("Py_GIL_DISABLED")` 查询。
- 两个新开关在 free-threaded 构建默认 true：`-X context_aware_warnings`，以及 `thread_inherit_context`（让 `threading.Thread` 继承调用方的 `Context()`）。

## Programming model without the GIL

拆掉这把大锁，原来靠它兜底的机制必须逐个补上，编程模型随之改变：

- **引用计数不再靠 GIL 保原子**。free-threading 改用**延迟计数（deferred reference counting）**：计数变更先攒在线程本地缓冲、再异步合并；配合**偏向计数（biased reference counting）**——对象只被一个线程持有时用本地计数，被其他线程访问时才切换成共享原子计数。对象头里这些计数与锁字段的具体布局属于对象模型，见 [Memory](/docs/CS/Python/Memory.md)。
- **依赖 GIL 原子性的旧代码不再安全**。有 GIL 时，单条不外调的 C 级操作（如 `list.append`）事实上原子，多步的读-改-写如 `x += 1`（加载-相加-存储）其实跨多条字节码、本就非硬保证，只是窗口小、鲜少暴露。去掉 GIL 后多线程真正并行跑同一段字节码，丢更新会真实发生：这类逻辑需**显式加锁**。CPython 用每对象临界区（critical sections）保住内建容器单步操作的原子性，但你的多步组合不再免费。
- **C 扩展要主动表态**。扩展通过 `Py_mod_gil` 槽声明自己支持无 GIL（`Py_MOD_GIL_NOT_USED`）；导入一个未声明支持的扩展时，运行时会打印警告并**把 GIL 重新启用**，以保兼容。

## Relation to multiple interpreters

移除 GIL 与多解释器是互补而非替代：`concurrent.interpreters`（PEP 734，3.14）把 C-API 里存在多年的子解释器开放到 Python 层，配合 PEP 684 的 per-interpreter GIL，**不改任何 C 扩展也能拿到真并行与进程级隔离**；具体 API 与限制留给 [Concurrency](/docs/CS/Python/Concurrency.md)，此处不展开。

## Choosing a parallelism strategy

| 场景 | 需要真多核 | 生态兼容要求 | 推荐方案 |
| :-- | :-- | :-- | :-- |
| 少量并发 IO 调用 | 否 | 高 | 线程（阻塞 IO 自动释放 GIL）或 asyncio |
| 海量并发连接 | 否 | 高 | asyncio 单线程事件循环（机制见 [Asyncio](/docs/CS/Python/Asyncio.md)） |
| CPU 密集、纯 Python | 是 | 高（要用任意第三方扩展） | 多进程 / `ProcessPoolExecutor` |
| CPU 密集、重活在无锁 C 扩展里 | 是 | 高 | 线程（扩展主动释放 GIL） |
| CPU 密集、纯 Python、可换独立构建 | 是 | 低（依赖扩展标注 `Py_mod_gil`） | free-threaded 构建 `python3.14t` |
| 要真并行 + 强隔离，不想换解释器 | 是 | 中 | `concurrent.interpreters`（PEP 734） |

## Links

- [Python](/docs/CS/Python/Python.md)
- [runtime](/docs/CS/Go/runtime.md)
- [GC](/docs/CS/Go/GC.md)
- [Thread](/docs/CS/C/Thread.md)
- [pthread](/docs/CS/OS/Linux/proc/pthread.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)

## References

- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [PEP 779 – Criteria for supported status for free-threaded Python](https://peps.python.org/pep-0779/)
- [PEP 684 – A Per-Interpreter GIL](https://peps.python.org/pep-0684/)
- [PEP 659 – Specializing Adaptive Interpreter](https://peps.python.org/pep-0659/)
- [PEP 734 – Multiple Interpreters in the Stdlib](https://peps.python.org/pep-0734/)
- [Free-threaded CPython how-to guide](https://docs.python.org/3/howto/free-threading-python.html)
- [What's New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [C-API Initialization, Finalization, and Threads](https://docs.python.org/3/c-api/init.html)
- [sys – sys.getswitchinterval()](https://docs.python.org/3/library/sys.html)
