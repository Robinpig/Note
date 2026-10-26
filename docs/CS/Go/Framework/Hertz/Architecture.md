# Hertz Architecture

## Introduction

Hertz 的核心设计目标是「**高扩展**」：它从一开始就不是把 fasthttp 直接暴露给业务，而是在 fasthttp 的血统之上做了一层**分层解耦**。fasthttp 把协议解析、连接管理、请求上下文揉在一个 `*fasthttp.RequestCtx` 里，扩展（换网络库、换协议）成本高；Hertz 把这层关系拆成可替换的四层，业务代码只依赖最上层的 `RequestContext` 与接口，下层实现可以随时替换。

理解 Hertz 的四个分层，本目录所有分册都围绕它们展开：

1. **应用层（Application）**：路由注册、`HandlerFunc`、中间件链、以及作为请求载体的 `app.RequestContext`。
2. **路由层（Route）**：基于 radix tree（trie）的 URL 匹配，把请求分发给正确的 handler。
3. **协议层（Protocol）**：`pkg/protocol` 下的 `Request` / `Response` / `RequestContext`，原生支持 HTTP/1.1，通过 ALPN 支持 HTTP/2，并允许注册自定义协议。
4. **传输层（Transport）**：`pkg/network` 下的 `Transporter` 接口，默认 Netpoll，可切换标准库 `net`。

## Engine and Bootstrap

引擎是 `server.Hertz`，两个入口：

- `server.Default()`：在 `server.New()` 基础上默认挂上 **Recovery** 与 **AccessLog** 两个中间件，是绝大多数业务的起点。
- `server.New(opts ...server.Option)`：纯净引擎，中间件全部自己加。

启动链路上，框架做几件事：初始化 `engine` → 构建 `router`（radix tree）→ 根据选项选择 `Transporter`（Netpoll 或 Go Net）→ `h.Spin()` / `h.Run()` 阻塞监听。其中 `h.Spin()` 与 `h.Run()` 等价，都负责最终把连接交给传输层并阻塞当前 goroutine。

传输层切换通过选项完成，例如 `server.WithTransport(netpoll.NewTransporter)` 或 `server.WithTransport(standard.NewTransporter)`——这正是「分层可插拔」最直接的落点：**业务侧零改动，仅换一个选项**。

## RequestContext and Lifecycle

`app.RequestContext` 是 Hertz 与 fasthttp 血统最明显的痕迹：它是一个**被对象池复用的大结构体**，承载请求与响应的全部字段（`Request` / `Response` / 参数 / 中间件状态等），并在每次请求结束后归还对象池以减少 GC 压力。

由此带来两条必须遵守的纪律（fasthttp 用户同样熟悉）：

- **handler 返回后不要持有 `*RequestContext` 或其内部切片**：上下文会被回收复用，异步逻辑若需要其中的数据，必须显式拷贝出来。
- **v0.9.0 引入 `Exile` / `IsExiled`**：专门解决「异步任务想复用 RequestContext」的场景——通过 `ctx.Exile()` 把上下文从复用池中「放逐」出来，交还给异步 goroutine 独占，代价是轻微的性能开销，仅在确有异步复用时启用。

Hertz 的 handler 签名 `func(c context.Context, ctx *app.RequestContext)` 把 Go 原生 `context.Context` 显式放在第一位，超时 / 取消 / 链路透传可以直接用标准库语义，不必像 gin/echo 那样再从自有类型里取。

## Zero-copy and Reference Counting

为压住高并发下的内存开销，Hertz 在协议层做了两块优化（与 Netpoll 的零拷贝思路同源）：

- **byte buffer 池化**：请求体 / 响应体的字节缓冲从 `sync.Pool` 取用，避免每次请求都向堆申请。
- **引用计数（reference counting）**：body 在「网络层 ↔ 应用层」之间移动时用引用计数代替拷贝，减少大 payload 下的 buffer 复制。

这两点共同支撑了 Netpoll 默认模式下的吞吐优势——但代价是上面提到的「上下文复用」纪律，业务侧需要适应「数据用完即还」的模型。

## Protocol and Transport Pluggability

- **协议层**：HTTP/1.1 是内建默认实现；HTTP/2 通过 ALPN 由 `hertz-contrib/http2` 接入；自定义协议则实现协议层接口后注册，Hertz 的「分层设计支持自定义协议解析逻辑」正是为此留的口子（字节内部曾用其承载自研 RPC over HTTP 的协议）。
- **传输层**：`pkg/network` 抽象出 `Transporter`，Netpoll 实现面向高并发非阻塞 I/O，标准库 `net` 实现面向兼容与调试。切换只改 `server.WithTransport`，业务代码无感。

## Relation to net/http and fasthttp

| 关系 | 说明 |
| :-- | :-- |
| fasthttp | Hertz 起点是 fasthttp 的 fork；`RequestContext` 复用模型、零拷贝思路都源自此，但 Hertz 已重分层、不再绑定 fasthttp 的紧耦合实现 |
| `net/http` | Hertz 提供 **适配（adapter）** 能力，可把现有 `net/http` 的 `http.Handler` 桥接到 Hertz 引擎；但标准库中间件**不能**直接以原签名挂到 Hertz 中间件链上（handler 签名不同），需经适配器或改用 hertz-contrib 同名实现 |
| Kitex | 同门 RPC 框架，共享 Netpoll 与代码生成理念，但协议层是 Thrift/gRPC 而非 HTTP |

一句话：**Hertz 把 fasthttp 的「快」与 gin/echo 的「好用」揉到一起，再用分层把「可换」做成一等公民**——这是它区别于其它 Go Web 框架最本质的一点。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Routing](/docs/CS/Go/Framework/Hertz/Routing.md)
- [Client](/docs/CS/Go/Framework/Hertz/Client.md)
- [Go netpoller](/docs/CS/Go/netpoller.md)
- [Go net](/docs/CS/Go/net.md)

## References

- <https://github.com/cloudwego/hertz>
- <https://www.cloudwego.io/docs/hertz/overview/>
- <https://github.com/cloudwego/netpoll>
- <https://github.com/valyala/fasthttp>
