## Introduction

REST（Representational State Transfer）是 Roy Fielding 在 2000 年博士论文中提出的一种**网络应用架构风格**，
不是协议也不是标准。符合其约束的 Web API 常被称为 RESTful API。它与 [RPC](/docs/CS/Distributed/RPC/RPC.md) 风格相对：
RPC 关注「调用远端的一个动作/方法」，REST 关注「操作网络上的一组资源」，用统一的资源标识与接口语义换取通用性、可缓存性与松耦合。

## Constraints

Fielding 给出的 REST 约束（满足全部才是真正的 REST，多数所谓 REST API 只是「HTTP + JSON」）：

1. **Client-Server（客户端-服务器分离）**：通过统一接口分离关注点，客户端不管数据存储，服务端不管界面，两端可独立演进。
2. **Stateless（无状态）**：每个请求必须包含处理它所需的全部信息，服务端不保存客户端的会话上下文。任何请求都能落到任意实例，天然利于水平扩展；会话状态放在客户端（token）或集中存储（如 [Spring Session](/docs/CS/Framework/Spring/Session.md)）。
3. **Cacheable（可缓存）**：响应必须显式或隐式标注可否缓存。命中缓存可省掉一次客户端-服务端往返，复用 HTTP 既有的缓存基础设施。
4. **Uniform Interface（统一接口）**：REST 的核心，包含四个子约束——
   - 资源用 URI 标识（identification of resources）；
   - 通过表示（representation，如 JSON/XML）操作资源，表示与服务端内部状态解耦；
   - 自描述消息（self-descriptive）：用标准 `Content-Type`、HTTP 方法、状态码说明如何处理；
   - **HATEOAS**：见下节。
5. **Layered System（分层系统）**：客户端无法判断自己直连的是末端服务器还是中间的网关/负载均衡/CDN，各层可独立替换。
6. **Code-On-Demand（可选）**：服务端可以临时下发可执行代码（如 JS）扩展客户端功能，唯一可选约束。

## Resource Model

- 资源用**名词**的 URI 标识：`/users/123/orders`，而非 `/getUserOrders`；
- 用 HTTP 方法表达动词语义，并天然携带幂等/安全属性：

| 方法 | 语义 | 安全（不改资源） | 幂等 |
| --- | --- | --- | --- |
| GET | 读取 | 是 | 是 |
| POST | 创建/触发动作 | 否 | 否 |
| PUT | 整体替换（不存在则建） | 否 | 是 |
| PATCH | 局部更新 | 否 | 视实现 |
| DELETE | 删除 | 否 | 是 |

- 用状态码表达结果：`200/201/204`、`400`（请求错）、`401`（未认证）、`403`（无权限）、`404`、`409`（冲突）、`429`（限流）、`5xx`（服务端错）。
- 版本、内容协商通过 header/URI 处理（`Accept: application/json`、`/v1/...`），而不是塞进方法名。

## HATEOAS

**Hypermedia As The Engine Of Application State**：资源的表示中应包含客户端下一步可用的**超链接/超媒体控件**，
应用状态的迁移由服务端返回的链接驱动，而不是客户端把所有 URL 硬编码在代码里。

```json
{
  "id": 123,
  "amount": 99.0,
  "state": "UNPAID",
  "_links": {
    "self":   { "href": "/orders/123" },
    "pay":    { "href": "/orders/123/pay",   "method": "POST" },
    "cancel": { "href": "/orders/123/cancel","method": "POST" }
  }
}
```

订单未支付时返回 `pay` 链接，支付后这一步链接消失、改为返回 `refund`——客户端根据当前表示中存在哪些链接来决定能做什么，
从而服务端可以在不破坏老客户端的前提下调整 URI 与流程。HATEOAS 是统一接口约束里「最常被省略」的一条，
绝大多数业务 API 只做到资源 + HTTP 方法，属 Richardson 成熟度模型的第 2 级，HATEOAS 才是第 3 级。

## REST vs RPC

| 维度 | RESTful | RPC（gRPC/Dubbo 等） |
| --- | --- | --- |
| 抽象 | 资源（名词） | 方法/动作（动词） |
| 协议 | 通常 HTTP/1.1 + JSON | 多为 HTTP/2 + [ProtoBuf](/docs/CS/Distributed/RPC/ProtoBuf.md)，或自定义 TCP |
| 契约 | 较松散（OpenAPI 补齐） | 强 IDL 契约 + 代码生成 |
| 性能 | 文本编码、头部开销大 | 二进制、多路复用，更高 |
| 缓存 | 可直接借 HTTP 缓存 | 需要额外机制 |
| 适用 | 开放 API、浏览器/跨组织、CRUD | 内部服务间高频调用、流式调用 |

实践中二者并非对立：对外用 REST 便于第三方与浏览器集成，内部微服务间用 [gRPC](/docs/CS/Framework/gRPC/gRPC.md)/[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
追求性能与强契约，网关层做协议转换。

## Links

- [RPC](/docs/CS/Distributed/RPC/RPC.md)
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md)

## References

1. [Roy Fielding - Architectural Styles and the Design of Network-based Software Architectures](https://www.ics.uci.edu/~fielding/pubs/dissertation/top.htm)
2. [Richardson Maturity Model](https://martinfowler.com/articles/richardsonMaturityModel.html)
3. [REST APIs must be hypertext-driven (Fielding)](https://roy.gbiv.com/untangled/2008/rest-apis-must-be-hypertext-driven)
