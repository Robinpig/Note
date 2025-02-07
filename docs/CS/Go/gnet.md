## Introduction



gnet 是一个基于事件驱动的高性能和轻量级网络框架。它直接使用 epoll 和 kqueue 系统调用而非标准 Go 网络包：net 来构建网络应用，它的工作原理类似两个开源的网络库：netty 和 libuv，这也使得gnet 达到了一个远超 Go net 的性能表现。

gnet 设计开发的初衷不是为了取代 Go 的标准网络库：net，而是为了创造出一个类似于 Redis、Haproxy 能高效处理网络包的 Go 语言网络服务器框架。

gnet 的卖点在于它是一个高性能、轻量级、非阻塞的纯 Go 实现的传输层（TCP/UDP/Unix Domain Socket）网络框架，开发者可以使用 gnet 来实现自己的应用层网络协议(HTTP、RPC、Redis、WebSocket 等等)，
从而构建出自己的应用层网络应用：比如在 gnet 上实现 HTTP 协议就可以创建出一个 HTTP 服务器 或者 Web 开发框架，实现 Redis 协议就可以创建出自己的 Redis 服务器等等。

gnet，在某些极端的网络业务场景，比如海量连接、高频短连接、网络小包等等场景，gnet 在性能和资源占用上都远超 Go 原生的 net 包（基于 netpoller）

gnet 已经实现了 Multi-Reactors 和 Multi-Reactors + Goroutine Pool 两种网络模型，也得益于这些网络模型，使得 gnet 成为一个高性能和低损耗的 Go 网络框架


## Links

- [Go](/docs/CS/Go/Go.md)