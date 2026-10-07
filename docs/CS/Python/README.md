## Introduction

[Python](https://www.python.org/) 相关笔记的知识地图。

组织顺序不是"语法 → 标准库 → 框架"的教程顺序，而是**按解释器决定行为上限的程度**排列：语言层几乎看不到机制，但对象的表示方式、GIL 的边界、字节码管线的优化程度，共同决定了一段 Python 代码能跑多快、能不能并行、以及生态里那些"必须这样写"的规矩从何而来。因此这里的层次是：语言与对象模型 → 运行时三件套（内存、字节码、GIL）→ 并发与异步 → 工程实践 → 生态。

## The Language Layer

总览与入口是 [Python](/docs/CS/Python/Python.md)：发行版、库清单、以及运行时层的定位。

真正解释"为什么 Python 的鸭子类型能工作"的是 [Data Model](/docs/CS/Python/Data_Model.md)：语法糖几乎全是对特殊方法的调度，`for` / `with` / `a + b` / `len(x)` 背后都是协议；属性查找顺序、描述符、MRO 与 `super()` 的协作关系、`__init_subclass__` 与 metaclass 的取舍，以及 `dataclass` / `NamedTuple` / `TypedDict` 这一族"数据容器"该选哪个，都在那一篇。

## The Runtime Layer

三件事互相咬合，构成所有性能与并发结论的地基。

[Memory](/docs/CS/Python/Memory.md) 讲对象头里的引用计数如何决定"归零即释放"、循环引用为什么要分代回收兜底、pymalloc 的分层为什么让"逻辑释放"和"RSS 下降"成为两件事；它同时是 [GC](/docs/CS/memory/GC.md) 跨语言对照里 Python 那一侧的答案，并且专门记了一条 3.14 的补丁级行为回滚（增量 GC 上线又撤回）作为"文档条目存在 ≠ 它还生效"的样本。

[Bytecode](/docs/CS/Python/Bytecode.md) 讲源码到执行的全部路径：AST → code object → 栈机字节码 → 特化自适应解释器 → 实验性 JIT 与 3.14 的 tail-call 解释器，以及 `.pyc` 缓存从何而来。不读这一篇，"哪种写法更快"就只能是抄来的规矩。

[GIL](/docs/CS/Python/GIL.md) 是并行能力的边界线：锁保护的其实是解释器状态与引用计数，切换粒度只决定公平性而不决定并行度；绕开它的历史路径（多进程、扩展主动释放锁、per-interpreter GIL）与 3.13/3.14 直接拆掉它的 free-threading 代价，都在这一篇。

## Concurrency and Async

[GIL](/docs/CS/Python/GIL.md) 划出边界后，怎么走是 [Concurrency](/docs/CS/Python/Concurrency.md) 的职责：线程、进程、多解释器（3.14 的 `concurrent.interpreters`）、asyncio 与外部任务队列之间的选型，以及 `fork` 语义随版本变化带来的那批真实事故。

[Asyncio](/docs/CS/Python/Asyncio.md) 是单线程事件循环的机制层：为什么协程只在 `await` 处让出、`_run_once` 的一轮如何把 fd 就绪与到期定时器合流进同一个队列（定时器用最小堆，这一节也填了 [Scheduled Task](/docs/CS/SE/Scheduled_Task.md) 里点名的 Python 侧缺口）、Task 的取消为什么是协作式的、`TaskGroup` 与 `gather` 的差别。与 Go 的对照见 [netpoller](/docs/CS/Go/netpoller.md) 与 [timer](/docs/CS/Go/timer.md)。

[Exceptions](/docs/CS/Python/Exceptions.md) 处理的是并发下最容易被吞掉的那一类问题：异常链、`ExceptionGroup` 与 `except*`、线程与任务里"看不见的错误"。

## Engineering Practice

类型标注不是类型检查：[Typing](/docs/CS/Python/Typing.md) 讲注解求值语义的三段历史（立即求值 → PEP 563 字符串化 → 3.14 的 PEP 649/749 惰性求值）以及静态检查器、IDE、运行时校验库三方如何共用同一份标注。

依赖与环境是 Python 生态最混乱的领域，[Packaging](/docs/CS/Python/Packaging.md) 把"环境 / 声明 / 解析"三件事切开后，再看 [uv](/docs/CS/Python/uv.md)（现代一体化方案）与 [conda](/docs/CS/Python/conda.md)（连原生依赖一起管）各自的边界；与 Go 的 module 模型对照最能看出差异。

动手提速前先测量：[Performance](/docs/CS/Python/Performance.md) 给度量口径、剖析工具谱、有效手段与值得辟谣的迷信，并把"升级解释器本身能白拿多少"量化清楚。

## Ecosystem

[Ecosystem](/docs/CS/Python/Ecosystem.md) 是跨目录的选型地图（Web 协议分层、任务队列、数据与分析、AI 胶水层、工具链、分发与可观测性）；[NumPy](/docs/CS/Python/NumPy.md) 单独成篇，因为"连续内存 + 描述符 + 广播"这套数组模型是 Python 能当数据/AI 宿主语言的地基，也牵出 GIL 与 BLAS 线程的过度订阅问题。交互开发环境见 [Jupyter](/docs/CS/Python/Jupyter.md)。

## Cross-language Coordinates

同一个问题在本库其他语言里的位置：内存回收 [GC](/docs/CS/memory/GC.md) / [Go GC](/docs/CS/Go/GC.md)，解释执行与编译 [Compiler](/docs/CS/Compiler/Compiler.md) / [Go compile](/docs/CS/Go/compile.md)，并发原语 [C Thread](/docs/CS/C/Thread.md) / [pthread](/docs/CS/OS/Linux/proc/pthread.md) / [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) / [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md)，依赖模型 [Module](/docs/CS/Go/Module.md)，错误处理 [Errors](/docs/CS/Go/Errors.md)，横向速览在 [Languages](/docs/CS/Languages.md)。

## Links

- [Python](/docs/CS/Python/Python.md)
- [GIL](/docs/CS/Python/GIL.md)
- [Memory](/docs/CS/Python/Memory.md)
- [Concurrency](/docs/CS/Python/Concurrency.md)
- [Ecosystem](/docs/CS/Python/Ecosystem.md)
- [CS](/docs/CS/CS.md)

## References

- [Python 官方文档](https://docs.python.org/3/)
- [Python Developer's Guide](https://devguide.python.org/)
