## Introduction

asyncio 是 CPython 标准库里的**单线程事件循环 + 协程调度框架**：一个线程挂着成千上万个待办任务，靠底层 I/O 多路复用
（Linux 上 epoll、macOS 上 kqueue、Windows 上 IOCP）等就绪，靠 `await` 切换任务。它买到"同时等待很多个慢操作"，买不到
"同时计算很多件事"。与 Go netpoller 的分水岭是**抢占点**：goroutine 会被 Go 运行时强制让出（函数入口与栈增长处的协作式检查，加上 Go 1.14 起的信号式异步抢占），asyncio 的协程
**只在 `await` 处让出**——下面几乎所有纪律都是这一条的推论。

## Cooperative preemption at await

调度单位是回调，协程被包成 Task 后，`await` 是它唯一交回控制权的时机。于是有了这条铁律：**不要在协程里做阻塞调用**。
一次 `time.sleep(0.3)` 不是"这个任务睡了 0.3 秒"，而是**这个线程上所有任务、所有定时器、所有连接一起停 0.3 秒**。
它是 asyncio 最常见的性能塌方原因，因为它不报错、不死锁，只把整条链路的尾延迟拉长——压测时表现为并发越高吞吐越不涨。

| 阻塞写法 | 实际后果 | 非阻塞替代 |
| :--- | :--- | :--- |
| `time.sleep(n)` | 独占线程 n 秒，全循环停摆 | `await asyncio.sleep(n)` |
| `requests.get(...)` | 整个循环等在 socket 上 | `httpx.AsyncClient` / `aiohttp` |
| psycopg2、MySQLdb 等同步 DB 驱动 | 每次查询都是一次全循环停顿 | asyncpg / aiomysql |

`run_in_executor()` / `asyncio.to_thread()`（3.9 起）是**逃生门而不是正解**：默认 executor 只是一个普通
`ThreadPoolExecutor`，`max_workers` 有上限（3.13 起为 `min(32, os.process_cpu_count() + 4)`），丢 2000 个阻塞调用进去只是
把塌方点从事件循环挪到线程池排队；线程仍受 [GIL](/docs/CS/Python/GIL.md) 约束，换进程要付序列化成本（同步 / 线程 / 进程
怎么选见 [Concurrency](/docs/CS/Python/Concurrency.md)）。标准就一句：**能拿到异步客户端就用异步客户端**。

## The loop tick, loop._run_once

一轮循环三步：按堆顶算出本次最多能等多久 → 阻塞在 `selector.select()` → 把就绪事件与到期定时器排进 `_ready` 逐个
执行。CPython 3.12 `Lib/asyncio/base_events.py` 的片段（原样摘录，省去注释行与 `event_list = None`、`handle._scheduled = False` 两行）：

```python
        timeout = None
        if self._ready or self._stopping:
            timeout = 0
        elif self._scheduled:
            when = self._scheduled[0]._when
            timeout = min(max(0, when - self.time()), MAXIMUM_SELECT_TIMEOUT)
        event_list = self._selector.select(timeout)
        self._process_events(event_list)
        end_time = self.time() + self._clock_resolution
        while self._scheduled:
            handle = self._scheduled[0]
            if handle._when >= end_time:
                break
            handle = heapq.heappop(self._scheduled)
            self._ready.append(handle)
```

- **fd 就绪与定时到期同优先级，合流进同一个 `_ready` 双端队列**：`_process_events()` 先 append fd 回调，随后 append
  到期 timer，本轮按 FIFO 跑完；同一轮里 I/O 排在 timer 前面，但没有饿死机制。
- **本轮不执行本轮新排的回调**：只跑进入本轮时 `_ready` 里已有的 `ntodo` 个，源码注释明说新排的要等下一轮。自旋的 `call_soon`
  链因此天然让出，但一整批慢回调仍会把 tick 拖得很长。
- `_ready` 非空时 `timeout` 取 0（本轮不等待），没有 ready 也没有 scheduled 时是 `None`，循环真正睡死在系统调用里。
  `selector` 是平台多路复用器的封装（Linux 上即 [epoll](/docs/CS/OS/Linux/IO/epoll.md)），Windows 的 Proactor 走 IOCP。

## Timer heap, call_later and call_at

定时事件不进队列，进**最小堆**：`loop._scheduled` 是用 `heapq` 维护的 list，`call_later(delay, cb)` 与 `call_at(when, cb)`
都构造 `TimerHandle` 后 `heappush`，注册顺序不影响到期顺序，代价 O(log n)。以 0.3/0.1/0.4/0.2 四个延时入堆，堆数组是
`[0.1, 0.2, 0.4, 0.3]`（满足堆序、非全序），`heappop` 依次取出 0.1 → 0.2 → 0.3 → 0.4（Python 3.12.5 实测）。
`TimerHandle.__lt__` **只比 `_when`**，同一时刻注册的两个回调谁先跑未定义（`call_later` docstring 明说）；`cancel()`
掉的 handle 不立刻出堆、只留 `_cancelled` 墓碑，堆内超过 100 个元素且取消占比过半才 `heapify` 重建。

**精度**是这里与"定时器库"最大的差别：tick 多长取决于上一个回调跑了多久。同一个 0.05 秒的 `call_at`，协程里执行 `time.sleep(0.3)`
会让它迟到 0.261 秒，`await asyncio.sleep(0.3)` 则误差 0.002 秒（Python 3.12.5 实测）——即 `call_later` 承诺"**不早于**某时刻"，
不是"准时"；`time.get_clock_info('monotonic').resolution` 是这件事的权威读数（本机 macOS 3.12.5 实测 `4.166…e-08` 秒，即 `mach_absolute_time()` 的约 41.7 ns），Windows 上该值要粗几个数量级，亚 10 ms 定时在那边本就不现实（Windows 数值未在本机验证）。这一节正是
[Scheduled_Task](/docs/CS/SE/Scheduled_Task.md) 的 Open Gaps 点名的 Python 侧缺口。对照 Go：[timer](/docs/CS/Go/timer.md) 的
`runtime.timer` 同样按 `when` 排序（四叉堆、每个 P 一份本地堆），但 fd 就绪走 [netpoller](/docs/CS/Go/netpoller.md) 的独立
路径、只在 `findrunnable` 里合流；asyncio 把两者汇成同一个 `_ready` 队列。

## Future, Task and await

协程对象本质是 yield 状态机：`await x` 沿 `x.__await__()` 把某个对象**上抛给驱动方**，在 asyncio 里那就是一个 Future。
`create_task()` 把协程包成 Task 并 `loop.call_soon(self.__step)`：`__step` 才是循环里被反复调用的回调，它
`coro.send(None)` 推进一步，撞上 Future 就挂上回调，Future 就绪时再把自己排回 `_ready`。所以 `await` 不是"等"，而是
"交出去 + 被叫回来"。

- `await coro()` 与 `create_task(coro())` 的差别不是写法而是**并发与否**。两次 `sleep(1)` 的实测耗时：

  ```python
  a = await work(1); b = await work(2)   # bare await  : 2.005
  x = asyncio.create_task(work(1))       # create_task : 1.003
  y = asyncio.create_task(work(2))       # TaskGroup   : 1.002
  await x; await y                       # 以上 Python 3.12.5 实测
  ```

- `ensure_future()` 是兼容老代码的包装（给 Future / Task 原样返回，给其它 awaitable 先套一层协程）；`create_task()` 只接受协程对象。
- **取消是协作式的**：`Task.cancel()` 只置标志并向当前挂起点抛 `CancelledError`；该异常直接继承 `BaseException`，就是为了
  躲开 `except Exception` 顺手吞掉。3.11 起有计数器：`cancelling()` 读未消化的取消次数、`uncancel()` 扣一次，不 `uncancel()`
  就没真正消化这次取消（实测计数从 1 回到 0 后 `cancelled()` 仍为 `False`）。`asyncio.timeout()` 与 TaskGroup 全靠这套机制，
  **吞掉 `CancelledError` 会让它们直接失效**。

## Structured concurrency

`asyncio.TaskGroup`（3.11）把"创建任务"与"等它们全部结束"绑进同一个 `async with` 作用域，与裸 `gather` 的差别：

| 维度 | `gather(...)` | `TaskGroup` |
| :--- | :--- | :--- |
| 首个异常 | 立刻向上抛，但**兄弟任务继续跑**，成了没人管的孤儿 | 取消组内剩余任务，等它们收尾后才抛 |
| 多异常 | 只看得见第一个 | 打包成 `ExceptionGroup`（`except*` 语法，细节见 [Exceptions](/docs/CS/Python/Exceptions.md)） |
| 子任务被外部取消 | 视作该子任务抛 `CancelledError`，`gather()` 自身**不被取消** | 取消波及整组，任务同生共死 |

`gather(..., return_exceptions=True)` 看着解决了异常逃逸，实际把异常降级成**结果列表里的一个元素**：没有 `raise`、没有 traceback，
除非显式遍历返回值判类型否则就是静默失败——实测它返回两个 `ValueError` 而日志毫无痕迹，同一份代码换成 `TaskGroup` 抛出的是带
2 个子异常的 `ExceptionGroup`。

## Timeouts, run and Runner

- `asyncio.timeout(s)` / `timeout_at(t)`（3.11）给**当前任务**设上下文超时：到点取消当前任务，在上下文出口把
  `CancelledError` 翻译成 `TimeoutError`，所以 `TimeoutError` 只能在 `async with` **外面**捕获。别再堆 `wait_for()`。
- `asyncio.run(coro)` 是顶层入口：新建循环 → `run_until_complete` → 取消残留任务、终结异步生成器、关 executor
  （限时 5 分钟）→ 关循环；文档明确"应只用一次"，**同线程已有循环在跑时调用必 `RuntimeError`**。
- `run_until_complete()` 的常见滥用是在还活着的循环里再套一层（REPL、框架的同步回调），或 `new_event_loop()` 后忘记关；要连续跑多个顶层协程就用 `asyncio.Runner`（3.11，`run()` 的内部机制就是它），复用同一个循环与 `contextvars.Context`。
- eager task factory（3.12 引入、3.14 文档仍在）：`loop.set_task_factory(asyncio.eager_task_factory)` 后协程在 **Task
  构造时就同步跑起来**，只在真正阻塞时才进循环排队（实测 `enter eager` 先于 `after create_task`），省下同步完成型协程的
  调度开销，代价是执行顺序更反直觉。

## Concurrency limits and backpressure

`create_task` 没有天然上限：一次扔出 10 万个任务等于对下游同时发起 10 万个请求，连接池、fd、下游 QPS 会先炸，然后才轮到内存：

```python
sem = asyncio.Semaphore(50)                       # 只让 50 个在飞
async def one(item):
    async with sem:
        await handle(item)
async with asyncio.TaskGroup() as tg:             # 对象全建，在飞的只有 50 个
    for item in items: tg.create_task(one(item))
```

- **`Semaphore` 限并发**最简单（对象照样全建出来，拿内存换清晰）；要连对象一起限就分片：每 N 个一批 `gather`、批间 `await`。
- **有界 `asyncio.Queue(maxsize=k)` 做背压**：`maxsize <= 0` 无界，`> 0` 时 `await q.put()` 挂起生产者直到某个 `get()`
  腾出位置，生产者被自动拖慢。它不是线程安全的，只能在同一循环里用；跨进程同类机制见 [MQ](/docs/CS/MQ/MQ.md)。要"到点
  就丢"而不是"排队等"，用 `asyncio.timeout` 包住 `get()`，别把背压转成无限延迟。

## Platform differences

| 平台 | 默认循环 | 子进程 | 信号 |
| :--- | :--- | :--- | :--- |
| Linux | `SelectorEventLoop`（epoll） | 支持 | `loop.add_signal_handler` 可用 |
| macOS / BSD | `SelectorEventLoop`（kqueue） | 支持 | 同上 |
| Windows（3.8 起） | `ProactorEventLoop`（IOCP） | Proactor 支持；Selector **不支持** `subprocess_exec/shell` | **不支持** `add_signal_handler` |

两条硬约束：`add_signal_handler()` 只在 Unix 可用，且**必须像 `signal.signal()` 一样在主线程调用**（回调被排进循环、与 `_ready`
里其他回调同批执行，这是从信号处理里安全驱动循环的正解）；Windows 的 Proactor 不支持 `add_reader()` / `add_writer()`，Selector
反过来不支持管道与子进程。信号与跨线程唤醒（`call_soon_threadsafe`）的边界见 [Concurrency](/docs/CS/Python/Concurrency.md)；async 路由见 [FastAPI](/docs/CS/Framework/FastAPI.md)。

## Third-party alternatives

| 库 | 定位与选型 |
| :--- | :--- |
| [uvloop](https://github.com/MagicStack/uvloop) | libuv 之上、Cython 绑定的标准循环 drop-in 替换件，README 称可让 asyncio 快 2–4 倍；换循环不改业务代码，但只发布 POSIX 与 macOS 支持，Windows 仍用标准循环 |
| [anyio](https://anyio.readthedocs.io/en/stable/) | asyncio 与 trio 之上的统一抽象层（任务组、取消、阻塞函数卸载）；库要同时支持两种后端时用它 |
| [trio](https://trio.readthedocs.io/en/stable/) | 把结构化并发做成原语：`nursery` 作用域内任务同生共死、取消由 nursery 统一下发；新项目把它当设计约束看待 |

## Debug mode and introspection

- 调试模式开关：`PYTHONASYNCIODEBUG=1`、`-X dev`（Python 开发模式）、`asyncio.run(main(), debug=True)`、`loop.set_debug(True)`。
  它记录未 await 的协程与 Task 创建栈，并让 `call_soon` 的线程安全检查真的生效；其中**慢回调检测**会把执行时长超过
  `loop.slow_callback_duration`（默认 100 毫秒）的回调记成 `Executing ... took ... seconds` 警告——它量的是回调真实占用循环的时长，
  是抓"协程里混进阻塞调用"最省事的工具。
- 现场看有什么在跑：`asyncio.all_tasks()`（不传参取当前循环）列出未完成的 Task，`Task.get_coro()` 拿到包的协程（3.12 起
  eager 执行且已完成的 Task 返回 `None`），`repr(task)` 带挂起点——先分清"在等 I/O"还是"等没人 set 的 Future"。
- 3.14 补上了任务图自省：`asyncio.capture_call_graph()` / `print_call_graph()` 打印当前 Task 或某个挂起 Future 的 await
  链；`python -m asyncio` 可在**不改动、不重启目标进程**的前提下查看另一个运行中进程的任务图。

## When asyncio is the wrong tool

| 场景 | 为什么不该用 | 该用什么 |
| :--- | :--- | :--- |
| CPU 密集计算 | 没有 yield 点，协程只会排队，吞吐不变 | 多进程、C 扩展、NumPy 等释放 GIL 的实现 |
| 靠并发降单次延迟 | 单线程 + GIL，再忙也只有一份算力 | 多进程 / 多线程；free-threading 见 [GIL](/docs/CS/Python/GIL.md) |
| 依赖栈只有同步实现 | 每次调用都钉住整个循环，退化成"带 await 的串行" | 同步框架 + 线程池，或先补齐异步驱动 |
| 团队没有异步经验 | 忘 `await`、吞 `CancelledError`、任务泄漏的排错成本高于收益 | 先把同步代码写好，再谈事件循环 |

## Links

- [Python](/docs/CS/Python/Python.md)
- [runtime](/docs/CS/Go/runtime.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)

## References

- [asyncio — Asynchronous I/O (event loop)](https://docs.python.org/3/library/asyncio-eventloop.html)
- [Coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Runners](https://docs.python.org/3/library/asyncio-runner.html)
- [Development Mode](https://docs.python.org/3/library/asyncio-dev.html)
- [Platform Support](https://docs.python.org/3/library/asyncio-platforms.html)
- [Call graph introspection](https://docs.python.org/3/library/asyncio-graph.html)
- [Command-line introspection tools](https://docs.python.org/3/library/asyncio-tools.html)
- [PEP 654 — Exception Groups and except\*](https://peps.python.org/pep-0654/)
- [uvloop on PyPI](https://pypi.org/project/uvloop/)
- [CPython Lib/asyncio/base_events.py](https://github.com/python/cpython/blob/main/Lib/asyncio/base_events.py)
