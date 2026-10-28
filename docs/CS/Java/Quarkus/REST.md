## Introduction

Quarkus 的 Web 栈核心是 **Quarkus REST**——原名 RESTEasy Reactive，2021 年随 Quarkus 2.0 引入，如今是唯一主推的 REST 实现，RESTEasy Classic 只剩遗留价值。它把 HTTP 处理直接架在 Vert.x 上，注解扫描与 metamodel 生成全部前移到构建期，命令式代码也能跑在非阻塞引擎上。总览见 [Quarkus](/docs/CS/Java/Quarkus.md)，构建期原理见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)。

## Execution Model: Event Loop by Default

Quarkus REST 的默认执行模型与 Servlet 容器相反：**端点方法默认跑在 Vert.x 事件循环线程上，不得阻塞**。需要阻塞操作时用两个注解显式表态：

| 注解 | 语义 |
| :--- | :--- |
| `@Blocking` | 方法分发到 worker 线程；开启虚拟线程时即运行在虚拟线程上 |
| `@NonBlocking` | 显式声明非阻塞（默认行为） |

判断标准不是"方法返回 void 还是 Uni"，而是方法体内有没有阻塞调用。返回 `Uni`/`Multi`/`CompletionStage` 时请求自动挂起，等待期间不占用事件循环线程。阻塞方法论在事件循环上是 Quarkus 应用最常见的线上事故来源——症状是事件循环饥饿导致的整体延迟抖动，而非某个接口变慢，调试时可对照 [Netty EventLoop](/docs/CS/Framework/Netty/EventLoop.md) 的线程模型理解。

虚拟线程是这条模型的延伸：`@Blocking` 方法在启用虚拟线程的 Quarkus REST 上直接跑在虚拟线程里，同步 JDBC 代码无需改写即可获得非阻塞的并发密度。

## Return Types and Streaming

| 返回类型 | 行为 |
| :--- | :--- |
| 实体 / `void` | 常规响应 |
| `Uni<T>` | 单值异步；就绪后恢复处理，等待期不占事件循环 |
| `Multi<T>` / `RestMulti<T>` | 流式响应，`encodeAsArray(false)` 可关掉 JSON 数组包装 |
| `@Produces(SERVER_SENT_EVENTS)` + `Multi<OutboundSseEvent>` | SSE 推送，配合 `@RestStreamElementType` 指定元素媒体类型 |

连接关闭时 `Uni` 管线随连接取消传播，需要自定义取消语义时用 `@Cancellable`。multipart 输出被限制为阻塞端点。

## JSON Serialization

默认 Jackson（3.40.1 平台锁 2.21.7）。3.37 引入 **reflection-free Jackson serializers**：序列化器不再依赖运行期反射注册，改为构建期生成——这同时砍掉了 native image 下最大的一类反射配置文件和对应的镜像体积。Quarkus 4 将升级到 Jackson 3，属破坏性变更，`quarkus update` 不自动处理 Jackson API 迁移。

## Qute and REST Clients

- **Qute**：Quarkus 的模板引擎，编译期完成模板解析与类型检查，也可独立做邮件/报表渲染，不绑定 Web 层。
- **REST Client**：`@RegisterRestClient` + 接口声明式调用，编译期生成实现，支持异步返回 `Uni`，与 RESTEasy Classic 时代的 MicroProfile REST Client 生态兼容但实现走反应式底座。
- **WebSockets Next**：新一代 WebSocket 扩展，取代早期的 `quarkus-websockets`，同样建立在统一 HTTP/Vert.x 层之上。

## Stack Comparison

| 维度 | Quarkus REST | RESTEasy Classic | Spring MVC |
| :--- | :--- | :--- | :--- |
| 底座 | Vert.x 事件循环 | Servlet 阻塞模型 | Servlet / 可选事件循环 |
| 扫描时机 | 构建期 | 启动期 | 启动期 |
| 阻塞模型 | 默认非阻塞，`@Blocking` 显式下沉 | worker 线程 | 每请求一线程 |
| 虚拟线程 | 与 `@Blocking` 自然集成 | 无 | 需显式配置 |
| 异步返回 | `Uni`/`Multi` 一等公民 | `CompletionStage` | `Mono`/`Flux`（WebFlux）或响应式返回值 |

## Links

- [Architecture](/docs/CS/Java/Quarkus/Architecture.md)
- [NativeImage](/docs/CS/Java/Quarkus/NativeImage.md)
- [Netty EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Undertow](/docs/CS/Framework/Undertow/Undertow.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)

## References

- https://quarkus.io/guides/resteasy-reactive
- https://resteasy.dev/2020/12/07/resteasy-reactive
- https://quarkus.io/blog/quarkus-3-37-released/
- https://github.com/quarkusio/quarkus/discussions/52020
