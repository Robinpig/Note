## Introduction




Netpoll 是由 字节跳动 开发的高性能 NIO(Non-blocking I/O) 网络库，专注于 RPC 场景。
RPC 通常有较重的处理逻辑，因此无法串行处理 I/O。而 Go 的标准库 net 设计了 BIO(Blocking I/O) 模式的 API，使得 RPC 框架设计上只能为每个连接都分配一个 goroutine。 这在高并发下，会产生大量的 goroutine，大幅增加调度开销。此外，net.Conn 没有提供检查连接活性的 API，因此 RPC 框架很难设计出高效的连接池，池中的失效连接无法及时清理。
另一方面，开源社区目前缺少专注于 RPC 方案的 Go 网络库。类似的项目如：evio , gnet 等，均面向 Redis, HAProxy 这样的场景。
因此 Netpoll 应运而生，它借鉴了 evio 和 netty 的优秀设计，具有出色的 性能，更适用于微服务架构。 同时，Netpoll 还提供了一些 特性，推荐在 RPC 设计中替代 net 。
基于 Netpoll 开发的 RPC 框架 Kitex 和 HTTP 框架 Hertz，性能均业界领先


## Links
