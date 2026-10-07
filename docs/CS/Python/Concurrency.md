## Introduction

Python 手上有六条并发的路：`threading`、`multiprocessing`、`asyncio`、`concurrent.futures`、`concurrent.interpreters`（3.14）、`subprocess`（以及进程外的任务队列 Celery）。选型的判断轴只有三条：

1. **要不要真并行**——多核同时执行 Python 字节码，还是只要"同时等待很多个慢操作"？
2. **状态能否共享**——共享就要处理读-改-写的一致性与生命周期，隔离就要付序列化与拷贝的成本。
3. **依赖的 C 扩展是否配合**——free-threaded 构建要扩展声明 `Py_mod_gil`，多解释器要扩展做过 module-state 隔离改造，进程池则要求一切可 pickle。

机制细节本篇不重复：GIL 的切换逻辑与 free-threading 的补偿机制在 [GIL](/docs/CS/Python/GIL.md)，事件循环的 tick 与定时器堆在 [Asyncio](/docs/CS/Python/Asyncio.md)。这里只回答"选完会踩什么坑"。

## Decision Table

| 负载 | 要真并行 | 状态共享 | C 扩展配合 | 首选 | 备选与理由 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 并发几十个 IO 调用（HTTP、DB、文件） | 否 | 需要（同进程对象） | 任意 | `ThreadPoolExecutor` | 阻塞 IO 期间释锁，代码仍是同步写法 |
| 上千并发连接 / 长连接网关 | 否 | 需要 | 需异步客户端 | `asyncio` | 线程数会被栈与 fd 拖死；驱动没有 async 版就别选 |
| 纯 Python CPU 密集（解析、压缩、图像逐像素） | 是 | 不需要（任务粒度粗） | 任意 | `ProcessPoolExecutor` | 唯一不挑扩展、不换解释器的多核方案 |
| CPU 密集但重活在 NumPy / BLAS / OpenCV 里 | 是 | 需要 | 已在 C 里放锁 | `threading` | 直接开线程，别为拿多核去上进程 |
| CPU 密集 + 要共享可变状态 + 可换构建 | 是 | 需要 | 需支持 free-threading | `python3.14t` + `threading` | 锁仍要自己加，见 GIL.md |
| CPU 密集 + 要进程级隔离 + 不想付 fork/spawn 成本 | 是 | 默认不共享 | 需支持多解释器 | `concurrent.interpreters` | 3.14 才有，限制见下文，不是银弹 |
| 混合：等高延迟 IO 的同时做重解析 | 是 | 部分 | 任意 | `asyncio` 收口 IO + **进程**池算 | 混进一个模型必卡循环，`to_thread` 救不了 CPU |
| 任务要跨机、要重试、要持久化 | 是 | 不需要 | 任意 | Celery / RQ 等外部 worker | 进程内池解决不了"这台机器关了" |
| 跑不可信或会崩的第三方原生代码 | 是 | 只能传数据 | 不相关 | `subprocess` | 崩溃与内存泄漏被进程边界兜住 |

## The concurrent.futures Layer

`Executor` 把"提交任务—取结果"抽象出来，`ThreadPoolExecutor` / `ProcessPoolExecutor` / `InterpreterPoolExecutor`（3.14）三者接口一致，换并发模型只改构造函数——所以先用线程池把逻辑写对，再按下面的实测决定要不要换进程。默认 `max_workers` 两家不同且跟版本有关：线程池 3.8 起是 `min(32, os.cpu_count() + 4)`、3.13 起改成 `min(32, (os.process_cpu_count() or 1) + 4)`（历史上 3.5 是 `cpu_count × 5`，为 IO 重叠留余量）；进程池 3.13 起默认 `os.process_cpu_count()`（Windows 上限 61）。`thread_name_prefix` 只有线程池有（3.6 加），用于在栈和日志里认出是你的线程。

本机 CPython 3.12.5、8 核 macOS arm64 实跑（每格取 3 次最小值，`# Python 3.12.5 实测`）：

| 负载 | 默认 workers | 单任务基线 | 并发后 | 结论 |
| :-- | :-- | :-- | :-- | :-- |
| CPU：4000 万次 `x += 1` | 线程 12 / 进程 8 | 1×40M = 1.035 s | 4 线程分摊 4×10M = **1.006 s** | 完全不加速，GIL 的指纹 |
| 同上 | 同上 | 同上 | 4 进程 = **0.31 s** | ≈3.3×，接近线性 |
| IO：8 次 `sleep(0.3)` | 同上 | 串行 ≈2.4 s | 8 线程 = **0.31 s** | ≈8× |
| 同上 | 同上 | 同上 | 4 进程 = **0.62 s** | 也并行，但被 worker 数卡住 |

语义上有两个反直觉点。**`map()` 的异常是延迟的**：它按输入顺序产出，某个任务抛了不会立刻告诉你，要等你迭代到那一格才抛——实测 `f(1)` 抛异常时前面只吐出 `[0]`，排在后面的 `f(3)` 的异常**永远看不到**。要"谁先完成先处理、每个异常都不丢"，用 `submit()` + `as_completed()`（实测完成序 `['boom-1', 2, 0, 'boom-3', 4, 5]`）。**`chunksize` 只对进程池有意义**：默认 1 表示每个任务一次 pickle + 一次 IPC，长迭代调大它能显著省开销；线程池与解释器池里它被忽略。3.14 起 `map()` 新增 `buffersize` 限制在飞结果数，替代过去"迭代器被立即全部收集"的行为。另有两条禁令：worker 里再取同一个 executor 的 future 会自锁（文档例：`wait_on_a` 等 `wait_on_b`）；`ProcessPoolExecutor` 的函数不能是 lambda 或 REPL 里定义的对象——`__main__` 必须能被子进程导入。

## threading Primitives and What the GIL Does Not Give You

原语清单与用途：`Lock`（互斥，不可重入）、`RLock`（同线程可重入，`Value` 的默认锁就是它）、`Condition`（等待某个谓词，配 `wait_for()`）、`Event`（一次性/可清的广播开关，用它做优雅停止）、`Semaphore` / `BoundedSemaphore`（限并发数，别拿它当锁）。这些**都是线程内的**，跨进程要用 `multiprocessing` 提供的同名版本（底层是信号量/命名对象），反过来把 `mp.Lock` 传给 spawn 出来的进程则不行。

**"有 GIL 就不需要锁"是错的**，错在把"单条字节码原子"当成了"一条语句原子"。本机 `dis` 看 `box[0] += 1`（3.12.5，省略地址列）：

```python
def inc(box):
    box[0] += 1

# LOAD_FAST 0 (box) | LOAD_CONST 1 (0) | COPY 2 | COPY 2
# BINARY_SUBSCR           <- 读
# LOAD_CONST 2 (1) | BINARY_OP 13 (+=)   <- 改
# SWAP 3 | SWAP 2 | STORE_SUBSCR          <- 写
```

读、改、写是三条独立步骤，中间任何一次切换都能塞进别人。诚实的实测补充：3.12 的求值断点主要落在 `RESUME` 与向后跳转处，所以**纯 int 的循环累加很难复现丢更新**——4 线程 × 200 万次共 800 万次，即使把 `sys.setswitchinterval()` 压到 1e-6 也仍是 800 万。但只要读与写之间出现一次能让出 GIL 的操作（一次 IO、一次锁等待、一次 Python 级函数调用），窗口立刻打开：实测 8 线程 × 200 次变成 1600 次读-改-写，结果只剩 **200**。也就是说 GIL 给的只是一份随时会作废的运气，不是保证；`multiprocessing.Value` 的文档干脆明写 `counter.value += 1` 不是原子操作，要 `with counter.get_lock():` 包住。free-threaded 构建里连这层运气都没了（见 GIL.md）。

**`threading.local` 与 `contextvars` 不是一回事**：前者的桶按**线程**分，后者的桶按**上下文**分。协程切换不换线程，所以 asyncio 里多个 Task 会共用同一个 `local` 桶并互相覆盖；每个 `Task` 创建时 `copy_context()` 快照一份，`ContextVar` 因此天然按 Task 隔离。实测两个 Task 同线程跑，`threading.local` 读出 `local=2 2`（串味），`contextvars` 读出 `ctxvar=1 2`（各归各）。另注意反向的坑：**新线程不会继承当前 Context**（实测子线程读到 `unset`），3.14 的 `-X thread_inherit_context` 只在 free-threaded 构建默认开。文档口径是：带状态的上下文管理器应该用 `contextvars`，不要用 `threading.local()`。

关闭与退出：`daemon=True` 的含义只是"当进程里只剩 daemon 线程时，程序就退出"，而退出时 daemon 线程**被硬停**，它手上的文件、事务、缓冲都不保证释放——想要优雅收尾就必须是非 daemon 线程 + `Event` 通知（`ThreadPoolExecutor` 的线程本来就都是非 daemon 且会在解释器退出前被 join，它的退出钩子还跑在 `atexit` 之前，所以主线程未处理的异常不会通知 worker 收工，文档据此建议别把它用作 `__main__` 的替代）。数据面用 `queue.Queue`（线程安全、有 `maxsize` 背压、`task_done()`/`join()` 可等全部处理完），关闭用哨兵：`q.put(None)` 让 worker 取到 `None` 才 break；多个 worker 就每个塞一枚，或者用 `n_workers` 计数广播。`asyncio.Queue` 与前两者都不同，它**不是线程安全的**，只能在同一循环里用。

## multiprocessing Start Methods Are the Real API

三种启动方式的差别不是"快慢"，而是"子进程继承了什么"：

| 方式 | 子进程状态 | 代价 | 约束 |
| :-- | :-- | :-- | :-- |
| `spawn` | 全新解释器，只拿到跑 `run()` 必需的资源，fd 不继承 | 最慢（要重新 import） | 目标函数与参数必须可 pickle，入口要 `if __name__ == "__main__":`——实测漏掉它：子进程重新执行 `__main__` 又去起进程，递归到 `RuntimeError: ... bootstrapping phase` 为止 |
| `fork` | 与父进程逐字节相同，全部 fd/锁/内存都继承 | 最快 | 多线程父进程里 fork 不安全 |
| `forkserver` | 从一个"干净、单线程"的服务进程 fork | 中等 | POSIX（需支持 Unix 管道传 fd），首次调用要已完成 import |

**默认值随版本与平台变过两次**（核实自 3.14.8 文档 `multiprocessing.html` 的 Contexts and start methods 一节）：`spawn` 是 Windows 与 macOS 的默认（macOS 自 3.8 起，因为系统库会自己起线程使 fork 崩子进程）；`fork` **从 3.14 起不再是任何平台的默认**；同一版本里 POSIX（Linux 等）的默认从 `fork` 改成 `forkserver`。也就是说"Linux 上默认 fork"这句话只对 3.13 及以下成立。本机 3.12.5 macOS 实测 `get_start_method()` = `spawn`；3.12 里在已有多线程的进程中调 `os.fork()` 实测会抛 `DeprecationWarning: This process is multi-threaded, use of fork() may lead to deadlocks in the child`。

`fork` 的两类经典事故：

- **锁状态被复制**。fork 只保留调用线程，但父进程里别的线程正持有的锁在子进程里仍然是"已锁定"，而它的持有者不存在——子进程一旦碰它就永久等待。同理，OpenSSL 与 CPU feature 探测状态、`atexit` 钩子、日志 handler 也被原样复制，表现为子进程偶发 hang 或双份日志。这就是 macOS 改默认值的根因。
- **fd 与随机状态被继承**。继承下来的 socket、连接池会被父子同时读写（表现为串包），且每个子进程都往池里再开一批连接 → 连接数按进程数爆炸。`random` 的**模块级默认实例**在 3.x 已被 `os.register_at_fork(after_in_child=_inst.seed)` 兜住（本机 `random.py` 里可读到），实测两个 fork 子进程的 `random.random()` 给出不同的值；但**你自己 `random.Random(seed)` 出来的实例不在兜底范围内**，实测它们在两个子进程里产出**同一个** 0.323833。经典缓解是把 pid 混进种子：`Random(base + os.getpid())`，实测两个子进程立刻分开。

`Pool(processes, initializer, initargs, maxtasksperchild)` 里，`initializer` 是每 worker 建一次资源的正解（连 DB 池、加载模型），`maxtasksperchild` 用"处理 N 个任务就换人"止住内存只增不减；Pool 的方法只应由创建它的进程调用，跨进程共享一个 Pool 不成立。`Manager()` 起的"共享 dict / list"其实是**另一个进程里的对象 + 代理**，每次方法调用都是一次 IPC + pickle，写进热循环就是性能陷阱；代理对象本身还要自己加锁才能给多线程用。要真共享走下一节。

## Data Passing and Sharing

| 手段 | 语义 | 代价 / 坑 |
| :-- | :-- | :-- |
| `mp.Queue` | pipe + 若干锁/信号量 + **feeder 线程**，put 的对象全被 pickle | 没有 `task_done()` / `join()`（那是 `JoinableQueue`）；`qsize()` 在 macOS 可能 `NotImplementedError`；子进程 put 过就要等 flush 完才退出，`p.join()` 在 `q.get()` 之前必死锁；`terminate()` 会损坏队列内容 |
| `mp.SimpleQueue` | 接近"带锁的 pipe"：一个 pipe + 两把锁，**无 feeder 线程、无内部缓冲** | 只有 `get()`/`put()`/`empty()`/`close()`，`empty()` 在关闭后必抛 `OSError`；好处是不会出现 Queue 那种"缓冲区没 flush 完，子进程不退出"的死锁 |
| `mp.Pipe(duplex=False)` | 两连接对象，`send`/`recv` 各含一次 pickle | 同一端被两个进程并发读写会损坏数据；单向时两端角色固定 |
| `mp.Value` / `mp.Array` | `multiprocessing.sharedctypes`，共享内存上的 ctypes 对象 | 默认自带一把递归锁；要快就 `lock=False` + 用 `raw`，但一致性全归你管，官方文档明写 `counter.value += 1` 不是原子操作 |
| `shared_memory.SharedMemory`（3.8+） | 命名共享块，`.buf` 是 `memoryview`，配 NumPy 直接建 ndarray 视图 | `close()` 每实例一次、`unlink()` 全块只一次；实际大小可能按页向上取整；3.13 起 `track` 参数——非 multiprocessing 派生的进程（如 `subprocess`）要 `track=False`，否则最先退出那个进程的资源跟踪器会把块删掉 |
| `mmap` | 文件或匿名内存映射（`mmap.mmap(-1, n)` 实测可用） | 匿名映射不能跨进程，跨进程要靠同一个文件 |
| pickle 本身 | 一切默认走序列化 | 本机 3.12.5 `DEFAULT_PROTOCOL = 4`（`HIGHEST_PROTOCOL = 5`），协议 5 才有 out-of-band 大缓冲零拷贝，标准 mp 队列没帮你用上 |

## Multiple Interpreters with PEP 734

3.14 新增 `concurrent.interpreters`：把存在二十多年的子解释器从 C-API 开放到 Python 层。自 3.12（PEP 684 每解释器独立 GIL）起，解释器之间才可真并行。官方定位一句话：**"拥有进程般的隔离、线程般的效率"**——同进程内，不复制地址空间，资源占用远低于起进程。

API 面（3.14 文档）：模块级 `create()`、`create_queue()`、`get_current()`、`get_main()`、`list_all()`；`Interpreter` 有只读 `id`、`whence`、`is_running()`、`close()`、`prepare_main()`、`exec()`、`call()`、`call_in_thread()`；异常 `ExecutionFailed`（带 `excinfo`）、`NotShareableError`、`InterpreterError`、`InterpreterNotFoundError`；跨解释器队列 `Queue`（实现 `queue.Queue` 接口，配 `QueueEmptyError` / `QueueFullError`）。

```python
from concurrent import interpreters
interp = interpreters.create()          # 不自动起线程
interp.exec('print("spam!")')           # 在**当前**线程里切过去执行
def run(arg): return arg
res = interp.call(run, "spam!")         # 同上，仍是你这个线程
t = interp.call_in_thread(run); t.join()   # 这才是"另一个解释器 + 另一个 OS 线程"
```

关键判断：解释器**本身不提供并发**，它只是"当前线程用哪份运行时状态"。并发来自你把解释器和线程组合起来——文档的说法是 **threads with opt-in sharing**，默认什么都不共享：`None`/`bool`/`bytes`/`str`/`int`/`float` 与不可变 tuple 被直接共享或高效拷贝，其余对象过 pickle，可变对象**不能共享**（真共享就等于丢掉 GIL 提供的线程安全），真正共享可变数据的只有 `memoryview` 和 `Queue` 两类。

这套"隔离 + 消息传递"的形状正是 CSP / actor 模型，文档直接点名 Go——对照 Go 的 goroutine 与 [Channel](/docs/CS/Go/Concurrency/Channel.md)：那边是"廉价并发原语 + channel 做同步"，这边是"解释器做隔离 + `Queue` 做同步"，而 Go 的 goroutine 默认共享堆、要靠 [RaceDetector](/docs/CS/Go/Concurrency/RaceDetector.md) 兜着，Python 的解释器则把共享直接禁掉。

文档明列的**当前限制**（原样五条，别当银弹）：单个解释器的启动尚未优化；每解释器内存偏高（内部共享仍在做）；跨解释器真正共享对象的手段还很少（除 `memoryview` 外）；PyPI 上大量第三方扩展模块尚不兼容多解释器（**标准库扩展模块全部兼容**）；这种写法对多数 Python 用户还很陌生。同版本还给了 `concurrent.futures.InterpreterPoolExecutor`（`ThreadPoolExecutor` 的子类），任务是 pickle 进 worker 自己的解释器再跑，是迁移成本最低的入口。⚠️ 本机是 3.12，本节全部来自 3.14.8 文档，**无法实跑，未做任何实测**。

## Cross-language Comparison

| 语言 | 并发单位 | 调度者 | 共享模型 | 廉价百万级？ |
| :-- | :-- | :-- | :-- | :-- |
| Python `threading` | OS 线程 | 内核 | 全共享 + GIL（free-threaded 无 GIL） | 否，千级就要看栈与 fd |
| Python `multiprocessing` | 进程 | 内核 | 不共享，pickle / 共享内存 | 否 |
| Python `concurrent.interpreters` | 解释器 + OS 线程 | 内核 | 默认不共享，显式传 | 否，但比进程省 |
| Python `asyncio` | 协程 | 单线程事件循环，只在 `await` 让出 | 全共享（同线程） | **是**，这是它唯一买到的东西 |
| Go | goroutine（见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)） | runtime M:N | 默认共享堆，channel 传消息 | 是 |
| Java | 平台线程 / 虚拟线程（见 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)） | 内核 / JVM | 共享堆 + JMM | 虚拟线程是 |
| OS 层 | pthread（见 [pthread](/docs/CS/OS/Linux/proc/pthread.md)） | 内核 | 共享地址空间 | 否 |

Python 的关键差异一句话：**没有廉价的百万级并发原语**。`thread` 是 OS 线程（内核调度、MB 级栈、还得分 GIL 的排队权），`interpreter` 介于两者之间（省掉 fork 的拷贝，但仍绑一个 OS 线程、默认不许共享），唯一买到"百万级"的是 `asyncio` 的协程——而它买的是"同时等待"，不是"同时计算"。别家缺的也不是调度器，而是一个像 Go runtime 那样做 M:N 复用、又允许安全共享堆的运行时。

## Signals and Subprocess

`signal` 与线程的边界很硬：**Python 的信号处理函数永远只在主解释器的主线程里执行**，即使信号投递自别的线程——因此信号不能用作线程间通信（用 `threading` 的原语），`signal.signal()` 在非主线程调用直接 `ValueError`，而处理函数里**不要碰 `threading.Lock`**（可能永远等不到）。`SIGINT` 会变成 `KeyboardInterrupt`，文档明说它可能在**任意一条字节码之后**抛出，标准库都不保证对它安全，别指望 `try/finally` 精确覆盖。asyncio 侧的正解是 `loop.add_signal_handler()`（同样只能在主线程调，见 [Asyncio](/docs/CS/Python/Asyncio.md?id=platform-differences)）。子进程收到的是默认处置，`SIGTERM` 不会被你的 `except` 接住，需要每个 worker 自己注册。

当隔离才是目的时，`subprocess` 比 `multiprocessing` 更省心：边界由内核给出，不需要 pickle 协议、不需要 `__main__` 可导入、不需要处理 fork 继承的 fd，崩溃/内存泄漏/被 OOM 杀都留在孩子身上，超时与 kill 语义就是进程语义；代价是只能靠 argv/stdin/stdout/文件传数据。反过来 `multiprocessing` 的 `Process.terminate()` 很危险——它会让该进程正持有的锁、pipe、队列对其他进程永久不可用。跨机异步任务（重试、定时、结果回存）交给 [Celery](https://docs.celeryq.dev/en/stable/) 这类外部 broker 驱动的系统，别在进程内模拟。

## Pitfall Checklist

| 现象 | 根因 | 规避 |
| :-- | :-- | :-- |
| 多线程 `print` 输出交错 | 一次 print 是多次 write，中间可被切 | 用 `logging` 或自己加锁，别拼字符串 |
| 子进程里日志重复或丢失 | `fork` 复制了已配置的 handler，两边各一份 | 在 `initializer` 里重建 handler；或走 `spawn` |
| "logging 不是线程安全的" | 误解：handler 有锁，不安全的是**多进程写同一文件** | 多进程用 `QueueHandler` + 一个进程消费写文件 |
| 换进程池后 DB 连接数暴涨 | 每 worker 各自继承/新建整份连接池 | 连接池在 `initializer` 里建、按 worker 数预算上限 |
| 子进程随机序列完全相同 | `fork` 复制了自建 `Random` 的状态（模块级实例已被 at-fork 重播种） | 种子混入 `os.getpid()`，或用 `secrets` / 各进程自播种 |
| fork 后子进程偶发 hang / SSL 报错 | 别的线程持有的锁与 OpenSSL 状态被复制 | 别在已起线程的进程里 fork，改 `spawn`/`forkserver` |
| 几百线程后吞吐反降 | 无界线程池 → 内核上下文切换与栈内存抖动 | 显式 `max_workers`，用队列长度而不是线程数表达背压 |
| asyncio 程序整体卡死 | 协程里混进一次阻塞调用，独占整个线程 | `to_thread`/executor 只是逃生门，根治是换异步客户端 |
| 退出时丢最后一批数据 | daemon 线程被硬停，缓冲没 flush | 非 daemon + `Event`/哨兵，或显式 `join()`/`flush()` |
| `mp.Queue` 消费完仍不退出 | put 过数据的进程要等 feeder flush，`join()` 与 `get()` 顺序反了 | 先 `get()` 再 `join()`，或 `cancel_join_thread()` / 用 Manager 队列 |

## Observability

线程与进程卡住时，先拿到"每个线程此刻在跑哪一行"。`py-spy` 是采样式外部工具，不侵入目标进程：`py-spy dump --pid <PID>` 打印目标进程每个线程当前的 Python 栈，`py-spy top` / `record` 看热点与火焰图，`--native` / `--subprocesses` 按需放开可见性（要不要 `sudo` 取决于本机 ptrace 权限）。进程内的死锁用 `faulthandler`：`faulthandler.enable()` 让段错误等致命信号打出栈，`faulthandler.dump_traceback_later(timeout, repeat=True)` 起一个 watchdog，超时就把**所有线程**的栈打到 stderr——这是抓"某个锁永远等不到"最省事的手段；`python -X faulthandler` 可在不改代码的前提下打开。手写版是 `threading.enumerate()` 配 `sys._current_frames()`。注意它们默认都只给 Python 帧，卡在 C 里的锁要看 native 栈。

## Links

- [Python](/docs/CS/Python/Python.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [Concurrency](/docs/CS/SE/Concurrency.md)
- [process](/docs/CS/OS/process.md)
- [MQ](/docs/CS/MQ/MQ.md)
- [Patterns](/docs/CS/Go/Concurrency/Patterns.md)

## References

- [concurrent.futures — Launching parallel tasks](https://docs.python.org/3/library/concurrent.futures.html)
- [threading — Thread-based parallelism](https://docs.python.org/3/library/threading.html)
- [multiprocessing — Process-based parallelism](https://docs.python.org/3/library/multiprocessing.html)
- [multiprocessing.shared_memory — Shared memory for direct access across processes](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- [concurrent.interpreters — Multiple interpreters in the same process](https://docs.python.org/3/library/concurrent.interpreters.html)
- [contextvars — Context Variables](https://docs.python.org/3/library/contextvars.html)
- [queue — A synchronized queue class](https://docs.python.org/3/library/queue.html)
- [signal — Implementation of POSIX signals](https://docs.python.org/3/library/signal.html)
- [subprocess — Subprocess management](https://docs.python.org/3/library/subprocess.html)
- [faulthandler — Dump the Python traceback](https://docs.python.org/3/library/faulthandler.html)
- [pickle — Python object serialization](https://docs.python.org/3/library/pickle.html)
- [os — Optional register_at_fork support](https://docs.python.org/3/library/os.html)
- [PEP 734 – Multiple Interpreters in the Stdlib](https://peps.python.org/pep-0734/)
- [PEP 684 – A Per-Interpreter GIL](https://peps.python.org/pep-0684/)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [py-spy: Sampling profiler for Python programs](https://github.com/benfred/py-spy)
- [Celery documentation](https://docs.celeryq.dev/en/stable/)
