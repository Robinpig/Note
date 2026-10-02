## Introduction

[io_uring](/docs/CS/OS/Linux/IO/io_uring.md) 是 Linux 5.1 引入的异步 I/O 接口：应用通过共享的 SQ/CQ 两个 ring buffer
与内核批量提交 I/O 请求、收割完成事件，一次提交可以处理多个请求，从而大幅减少系统调用次数，并支持真正异步的 buffered/direct 文件 I/O 与网络 I/O。

Java 生态访问 io_uring 的路径分三类：

1. **JDK 主线**：Linux 上的 NIO Selector 长期基于 [epoll](/docs/CS/OS/Linux/IO/epoll.md) 实现（`sun.nio.ch.EPoll*`），
   主线 JDK 截至目前没有提供内置的 io_uring Channel/Selector，仍以 NIO/[NIO](/docs/CS/Java/JDK/IO/NIO.md) 为标准接口。
2. **第三方库 JUring**：通过 FFM API（Foreign Function & Memory API，JEP 454 于 JDK 22 转正，
   前身为 JEP 424/442 预览）直接调用 liburing / io_uring 系统调用，无需编写 JNI 本地代码，主要面向文件 I/O。
3. **Netty incubator io_uring transport**：Netty 官方实验性传输实现，在 Linux native 环境下用 io_uring 替换 epoll 事件循环，
   是目前生产上最主流的 Java io_uring 落地方案。

## JUring

JUring 是一个把 io_uring 文件 I/O 暴露给 Java 的实验性库，其关键意义在于**不再需要 JNI**：

- 传统 JNI 方式要写一份 C/C++ shim，通过 [JNI](/docs/CS/Java/JDK/Basic/JNI.md) 桥接；
- FFM API 让 Java 代码直接 `dlopen` liburing 并调用其函数（`Linker`、`FunctionDescriptor`、`MemorySegment`），
  本地头文件中的结构体用 Java 端的 MemoryLayout 描述即可。

典型使用形态（示意）：创建一个 ring（对应内核的 `io_uring_setup`），把 `read`/`write`/`accept` 等 opcode 对应的
SQE 填入 Submission Queue，调用一次 enter（提交屏障），再从 Completion Queue 收割 CQE。
批量提交、避免每个 I/O 一次 syscall 正是 io_uring 相对 [epoll](/docs/CS/OS/Linux/IO/epoll.md) + 非阻塞读写的核心收益。

## 与现有 Java I/O 模型的关系

| 模型 | Linux 实现 | 系统调用/事件 | 文件 I/O 异步性 |
| --- | --- | --- | --- |
| BIO（java.io） | 阻塞 read/write | 每连接一线程 | 阻塞 |
| NIO（java.nio.channels） | epoll（Linux） | selector 批量收事件，read/write 仍各一次 syscall | 文件 Channel 始终模拟为「立即就绪」，磁盘读写仍会阻塞 carrier 线程 |
| AIO（AsynchronousChannel） | Linux 下由 epoll/线程池模拟（Windows 才是真正的 IOCP） | 无原生 Linux 异步通道 | 名义异步，实为线程池 |
| io_uring（JUring/Netty incubator） | 原生 SQ/CQ ring | SQE 批量提交，收割 CQE | 支持真正异步（配合 direct I/O / fixed files 更明显） |

对 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) 而言，NIO 的文件 I/O 遇到缺页仍会阻塞
（从而 pin 住 carrier 平台线程），io_uring + 多线程卸载内核 worker 是解决「文件 I/O 不服从非阻塞语义」这一缺口的候选方向，
也是社区讨论把 io_uring 引入 JDK 的主要动机。

## Caveats

- **平台限制**：仅 Linux 5.1+；部分 opcode 要求更高内核版本；macOS/Windows 不可用，需要在抽象层保留 epoll/NIO 回退。
- **安全策略**：io_uring 暴露面大，历史上出现过多个内核提权 CVE，不少容器/沙箱环境（seccomp、较旧 Docker 默认配置、部分云厂商）直接禁用 io_uring 系统调用，部署前需确认 `io_uring_setup` 未被拦截。
- **生态成熟度**：JDK 标准 API 尚未覆盖；JUring 偏实验性；生产采用通常跟随 Netty 这类自带 native 传输层的框架，而不是业务代码直接包 SQE。

## Links

- [IO uring](/docs/CS/OS/Linux/IO/io_uring.md) — 内核侧 SQ/CQ、SQE/CQE 与 opcode 机制
- [NIO](/docs/CS/Java/JDK/IO/NIO.md) — Selector/Channel 标准模型与 epoll 映射
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [JNI](/docs/CS/Java/JDK/Basic/JNI.md) — FFM 出现之前的本地调用方式
- [Netty](/docs/CS/Framework/Netty/Netty.md) — incubator io_uring transport

## References

1. [JUring: File I/O for Java using IO_uring](https://github.com/davidtos/JUring)
2. [JEP 454: Foreign Function & Memory API](https://openjdk.org/jeps/454)
3. [Netty incubator transport io_uring](https://github.com/netty/netty-incubator-transport-io_uring)
4. [Efficient IO with io_uring](https://kernel.dk/io_uring.pdf)
