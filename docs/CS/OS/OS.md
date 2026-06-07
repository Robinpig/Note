## 简介

事实上，有一组软件负责使程序易于运行、允许程序共享内存、使程序能够与设备交互以及其他类似的有趣功能。
这组软件称为操作系统，因为它负责确保系统以易于使用的方式正确高效地运行。
操作系统是作为其他应用程序与计算机或移动设备硬件之间接口的软件程序。

操作系统具备的功能

- 抽象
- 多路复用、共享和隔离
- 安全
- 性能

### 实现策略

目前，操作系统的实现基于两种主要范式：

1. 微内核——其中只有最基本的功能直接在中央内核（微内核）中实现。
   所有其他功能委托给自治进程，这些进程通过明确定义的通信接口与中央内核通信——例如，各种文件系统、内存管理等。
   （当然，控制与系统本身通信的最基本级别的内存管理在微内核中。然而，系统调用级别的处理在外部服务器中实现。）
   从理论上讲，这是一种非常优雅的方法，因为各个部分彼此清晰分离，这迫使程序员使用"干净"的编程技术。
   这种方法的其他好处是动态可扩展性和在运行时交换重要组件的能力。
   然而，由于需要额外的 CPU 时间来支持组件之间的复杂通信，微内核在实践中并未真正确立自己的地位，尽管它们已经作为活跃且多样化的研究主题一段时间了。
2. 宏内核——它们是另一种传统的概念。
   在这里，内核的整个代码——包括其所有子系统，如内存管理、文件系统或设备驱动程序——打包到单个文件中。
   每个函数都可以访问内核的所有其他部分；如果编程不谨慎，这可能导致精心嵌套的源代码。

微内核和宏内核之间的主要区别如下：

| Features                                       | Microkernel                                                  | Monolithic Kernel                                            |
| :--------------------------------------------- | :----------------------------------------------------------- | :----------------------------------------------------------- |
| **Definition**                                 | It is a kernel type that implements an operating system by providing low-level address space management, IPC, and thread management. | It is a type of kernel in which the complete operating system runs at the kernel speed. |
| **Size**                                       | It is smaller in size.                                       | It is bigger than the microkernel.                           |
| **Speed**                                      | Its process execution is slower.                             | Its process execution is faster.                             |
| **Basic**                                      | It implements kernel and user services in different address spaces. | It implements both user and kernel services in the same address space. |
| **Security**                                   | It is more secure than the monolithic kernel.                | It is less secure than the microkernel.                      |
| **Stability**                                  | A single process failure does not affect other processes.    | In a monolithic kernel, if a service fails, the entire system fails. |
| **Extendible**                                 | It is easy to extend.                                        | It is hard to extend.                                        |
| **Code**                                       | More code is necessary to write a microkernel.               | Less code is necessary to write a monolithic kernel.         |
| **Inter-Process**                              | Communication Microkernels use the messaging queues to achieve IPC. | The monolithic kernels use signals and sockets to achieve IPC. |
| **Maintainability It is easily maintainable.** | Maintenance takes extra time and resources.                  |                                                              |
| **Debug**                                      | It is easy to debug.                                         | It is hard to debug.                                         |
| **Example**                                    | Symbian, L4Linux, K42, Mac OS X, PikeOS, HURD, etc.          | Linux, BSDs, Solaris, OS-9, DOS, OpenVMS, etc.               |



目前，宏内核的性能仍然高于微内核，因此 Linux 过去和现在都是按照这种范式实现的。
然而，引入了一项重大创新。
具有内核代码的模块可以在系统运行期间插入或移除，支持向内核动态添加各种功能，从而弥补了宏内核的一些缺点。
这得益于内核和用户空间之间精密的通信手段，允许实现热插拔和模块的动态加载。

## 虚拟化

操作系统实现此功能的主要方式是通过一种称为虚拟化的通用技术。
也就是说，操作系统获取物理资源（如处理器、内存或磁盘）并将其转换为更通用、更强大且更易于使用的虚拟形式。
因此，我们有时将操作系统称为虚拟机。

为了虚拟化 CPU，操作系统需要以某种方式在看似同时运行的许多作业之间共享物理 CPU。
基本思想很简单：运行一个进程一段时间，然后运行另一个，依此类推。通过这种方式对 CPU 进行时分复用，实现了虚拟化。

然而，在构建这样的虚拟化机制时存在一些挑战。

- 首先是性能：我们如何在不为系统增加过多开销的情况下实现虚拟化？
- 其次是控制：我们如何在保留对 CPU 的控制的同时高效运行进程？

> THE CRUX:
> HOW TO EFFICIENTLY VIRTUALIZE THE CPU WITH CONTROL
> The OS must virtualize the CPU in an efficient manner while retaining control over the system.

### 如何执行受限操作？

进程必须能够执行 I/O 和其他一些受限操作，但不能让进程完全控制系统。
操作系统和硬件如何协同工作来实现这一点？

- 因此，我们采用的方法是引入一种新的处理器模式，称为**用户模式**；在用户模式下运行的代码在其操作能力上受到限制。
- 与用户模式相对的是**内核模式**，操作系统（或内核）在此模式下运行。
  在此模式下，运行的代码可以做任何想做的事，包括特权操作，如发出 I/O 请求和执行所有类型的受限指令。

为了允许用户进程在希望执行某种特权操作时能够做到，几乎所有现代硬件都为用户程序提供了执行**系统调用**的能力。
还提供了陷入内核和从陷阱返回到用户模式程序的特殊指令，以及允许操作系统告诉硬件陷阱表在内存中位置的指令。

内核通过在引导时设置**陷阱表**来实现这一点。
当机器启动时，它以特权（内核）模式启动，因此可以根据需要自由配置机器硬件。
因此，操作系统最先做的事情之一就是告诉硬件在发生某些异常事件时运行什么代码。

### 如何重新获得 CPU 控制权

协作方法：等待系统调用

非协作方法：操作系统接管控制

#### 如何在无协作的情况下重新获得控制

添加定时器中断使操作系统即使在进程以非协作方式运行时也能重新在 CPU 上运行。

在引导序列期间，操作系统必须启动定时器，这当然是一个特权操作。
一旦定时器启动，操作系统就可以放心，控制权最终会归还给它，因此操作系统可以自由运行用户程序。
定时器也可以关闭（也是一个特权操作）。

请注意，当中断发生时，硬件有一些责任，特别是要保存足够的中断发生时正在运行的程序的状态，以便后续的从陷阱返回指令能够正确恢复正在运行的程序。
这组操作与硬件在显式系统调用陷入内核期间的行为非常相似，各种寄存器被保存（例如，保存到内核栈上），然后可以通过从陷阱返回指令轻松恢复。

现在操作系统已经重新获得控制权，无论是通过系统调用协作地还是通过定时器中断强制地，都必须做出决定：是继续运行当前正在运行的进程，还是切换到另一个进程。
这个决定由操作系统中称为调度器的部分做出。

##### 上下文切换

如果决定切换，操作系统会执行一段低级代码，我们称之为**上下文切换**。
上下文切换在概念上很简单：操作系统只需为当前正在执行的进程保存一些寄存器值（例如保存到其内核栈上），并为即将执行的进程恢复一些寄存器值（从内核栈恢复）。
通过这样做，操作系统确保了当从陷阱返回指令最终执行时，系统不会返回到之前正在运行的进程，而是恢复执行另一个进程。

为了保存当前运行进程的上下文，操作系统会执行一些低级汇编代码来保存当前运行进程的通用寄存器、程序计数器和内核栈指针，然后恢复这些寄存器、程序计数器，并切换到即将执行的进程的内核栈。
通过切换栈，内核在一个进程（被中断的那个）的上下文中进入对切换代码的调用，并在另一个进程的上下文（即将执行的那个）中返回。
当操作系统最终执行从陷阱返回指令时，即将执行的进程成为当前正在运行的进程。
至此上下文切换完成。

> [!TIP]
>
> Reboot is Useful
>
> The only solution to infinite loops (and similar behaviors) under cooperative preemption is to reboot the machine.
>
> - Specifically, reboot is useful because it moves software back to a known and likely more tested state.
> - Reboots also reclaim stale or leaked resources (e.g., memory) which may otherwise be hard to handle.
> - Finally, reboots are easy to automate.

## Architecture

- [Processes and Threads](/docs/CS/OS/process.md)
- [Memory Management](/docs/CS/OS/memory/memory.md)
- [File Systems](/docs/CS/OS/file.md)
- [Input/Output](/docs/CS/OS/IO.md)
- [Security](/docs/CS/OS/Security.md)

> *Adding more code adds more bugs.*

> [!TIP]
>
> *Don’t hide power.*

System Structure

Layered Systems

Exokernels

Microkernels

Extensible Systems

Top-Down vs. Bottom-Up

虽然最好是从上到下设计系统，但从理论上讲，它可以自上而下或自下而上地实现。
这种方法的问题在于，只有顶层过程可用时很难测试任何东西。
因此，许多开发者发现实际自下而上地构建系统更实用。

同步与异步通信

其他操作系统使用异步原语构建进程间通信。在某种程度上，异步通信甚至比其同步版本更简单。
客户端进程向服务器发送消息，但不等待消息送达或回复返回，而是继续执行。
当然，这意味着它也异步接收回复，并且应当在回复到达时记住它对应哪个请求。
服务器通常作为事件循环中的单个线程处理请求（事件）。

每当请求需要服务器联系其他服务器进行进一步处理时，它会发送自己的异步消息，并且不阻塞，继续处理下一个请求。
不需要多线程。只有单个线程处理事件时，多线程访问共享数据结构的问题不会发生。
另一方面，长时间运行的事件处理程序会使单线程服务器的响应变得迟缓。

线程和事件哪个是更好的编程模型，这是一个长期存在争议的问题，自从 John Ousterhout 的经典论文《Why threads are a bad idea (for most purposes)》（1996）以来，就激起了双方狂热者的热情。
Ousterhout 认为线程使一切变得不必要的复杂：锁定、调试、回调、性能——你能想到的都有。当然，如果每个人都同意，就不会有争议了。
在 Ousterhout 的论文几年后，Von Behren 等人（2003）发表了一篇题为《Why events are a bad idea (for high concurrency servers)》的论文。
因此，为系统设计者决定正确的编程模型是一个困难但重要的决定。没有绝对的赢家。
像 apache 这样的 Web 服务器坚定地采用同步通信和线程，但像 lighttpd 等其他服务器基于事件驱动范式。两者都非常流行。
在我们看来，事件通常比线程更容易理解和调试。
只要不需要每核并发，它们可能是一个不错的选择。

## Lifecycle

[BootLoader](/docs/CS/OS/BootLoader.md)


## OSs

1971年11月3日: [UNIX](/docs/CS/OS/unix/Unix.md) 第1版（UNIX V1）诞生 出版的第一版《Unix 程序员手册》中，将1971/1/1作为Unix纪元的开始
1973年: 汤普逊和里奇用C语言重写了Unix，形成第三版UNIX

1978年: 大约600台计算机在运行UNIX。伯克利大学推出以第6版UNIX为基础，加上改进和新功能而成的Unix，命名为BSD，开创Unix的另一分支：BSD系列

DOS是1979年由微软公司为IBM个人电脑开发的MS-DOS,它是一个单用户单任务操作系统

1984年，苹果公司发布Macintosh

1985年11月20日，微软正式发布 [Windows](/docs/CS/OS/Windows/Windows.md) 1.0
早期的 windows，其实就是套在 DOS 外面的一个"壳"，只是起到操作界面的作用。最开始，微软把它称之为"界面管理器"


1991年年底，Linux Torvalds公开了 [Linux](/docs/CS/OS/Linux/Linux.md) 内核源码0.02版

1995年，System 7 的 7.5.1 版本发布，Mac 系统开始改名为Mac OS


2016 年 WWDC 上，苹果发布了macOS 10.12 Sierra。Mac OS X 的名字被更简洁优雅的 [macOS](/docs/CS/OS/mac/mac.md) 所取代

随着智能手机和平板电脑的兴起 IOS 和 [Android](/docs/CS/OS/Android/Android.md) 成为移动设备的主流操作系统

[xv6](/docs/CS/OS/xv6/xv6.md) 是 MIT 开发的一个教学用的完整的类 Unix 操作系统，并且在 MIT 的操作系统课程 6.828 中使用


[Fuchsia](/docs/CS/OS/Fuchsia/Fuchsia.md) 是Google开发的操作系统，与基于Linux内核的ChromeOS和Android等不同，
Fuchsia基于新的名为Zircon的微内核，受Little Kernel启发，用于嵌入式系统，主要使用C语言和C++编写

## 性能

性能指标是由系统、应用程序或附加工具生成的选择性统计信息，用于衡量感兴趣的活动。
它们用于性能分析和监控，可以在命令行以数字形式查看，或使用可视化工具以图形方式展示。

系统性能指标的常见类型包括：

- **吞吐量：** 每秒的操作数或数据量
- **IOPS：** 每秒 I/O 操作数
- **利用率：** 资源的繁忙程度，以百分比表示
- **延迟：** 操作时间，以平均值或百分位数表示

吞吐量的使用取决于其上下文。数据库吞吐量通常以每秒查询或请求（操作）数来衡量。
网络吞吐量以每秒比特或字节（数据量）来衡量。

IOPS 是仅针对 I/O 操作（读写）的吞吐量度量。同样，上下文很重要，定义可能有所不同。

性能指标不是免费的；在某种程度上，必须消耗 CPU 周期来收集和存储它们。
这会导致开销，可能对测量目标的性能产生负面影响。
这称为**观察者效应**。

你可能认为软件供应商提供的指标选择良好、无错误并提供完全的可见性。
实际上，指标可能令人困惑、复杂、不可靠、不准确，甚至完全错误（由于错误）。
有时一个指标在一个软件版本中是正确的，但没有更新以反映新代码和代码路径的添加。

## 其他

[容器化](/docs/CS/Container/Container.md) 是将软件代码与运行代码所需的操作系统库和依赖项打包在一起，创建一个称为容器的单个轻量级可执行文件，该文件在任何基础设施上都能一致地运行。

## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Network](/docs/CS/CN/CN.md)
- [Distributed system](/docs/CS/Distributed/Distributed)

## References

1. [Operating Systems: Three Easy Pieces](https://pages.cs.wisc.edu/~remzi/OSTEP/)
2. [Operating Systems Concepts]()
3. [Modern Operating Systems](https://media.pearsoncmg.com/bc/abp/cs-resources/products/product.html#product,isbn=013359162X)
