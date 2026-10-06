# Jetty WebSocket

## Introduction

Jetty 12 把 WebSocket 重构为清晰的三层：最底下是一套**协议引擎**（core），上面分别搭着 **Jetty 原生 API** 和 **jakarta.websocket API** 两套编程模型。这样设计有两个动机：

1. **一套帧引擎服务两套编程模型**。core 层负责 RFC 6455 帧解析、扩展协商（permessage-deflate 等）、会话状态机，原生 API 和 jakarta API 只是同一个引擎之上不同的"端点外观"。
2. **服务端与客户端复用**。core 层同时被 `jetty-websocket-core-server` 与客户端模块引用，升级握手（Handshaker）只属于服务端，帧处理与扩展栈两端共用。

对从 9/10/11 迁移过来的读者，本篇最重要的结论是：**`WebSocketServerFactory`、`WebSocketServer`、`WebSocketSession`、`WebSocketAdapter` 这些旧类在 12 里全部不存在**，职责被拆进了 `Handshaker` + `WebSocketUpgradeHandler` + `ServerWebSocketContainer` 三组新角色（[Jetty](/docs/CS/Framework/Jetty/Jetty.md) 的迁移表已有此条目）。

下文所有源码结论均标注 `相对 /tmp/src/tree/` 下 12.1.14 源码镜像的路径与行号；`jetty-websocket-core-common`、`jetty-websocket-jetty-api/common`、`jetty-ee10/ee11-websocket-jakarta` 不在镜像中，相关类名凡只经 `import` 语句核实的都会注明。

## Module Layout of the Three Layers

| 模块 | 角色 | 镜像情况 |
| :--- | :--- | :--- |
| `jetty-websocket-core-common` | 帧引擎：`Frame`/`OpCode`、`ExtensionStack`、`WebSocketCoreSession`、`WebSocketConnection`、`WebSocketComponents` | 不在镜像，类名经 core-server 的 import 核实 |
| `jetty-websocket-core-server` | 服务端升级机制：`Handshaker`、`WebSocketMappings`、`WebSocketUpgradeHandler`、`WebSocketNegotiator`/`WebSocketCreator`、`WebSocketServerComponents` 及 `internal/*` | 在镜像（21 文件） |
| `jetty-websocket-jetty-api` / `jetty-websocket-jetty-common` | 原生 API：`Session`、`WebSocketContainer`、`Configurable`；`JettyWebSocketFrameHandler` 调度 | api 不在镜像；common 类名经 import 核实 |
| `jetty-websocket-jetty-server` | 原生 API 服务端入口：`ServerWebSocketContainer`、`WebSocketUpgradeHandler` | 在镜像（11 文件） |
| `jetty-ee10-websocket-jakarta` / `jetty-ee11-websocket-jakarta` | jakarta.websocket 适配层 | **未在镜像中确认**，本篇不列其类名 |

`module-info.java` 可以佐证分层：`jetty-websocket-jetty-server` 同时 `requires` 了 `websocket.core.server`、`websocket.common`、`websocket.api`（相对 `/tmp/src/tree/jetty-websocket-jetty-server-12.1.14/module-info.java:16-21`），即原生 API 层站在 core 层之上。

## The Upgrade Handshake Chain

### The Handshaker Contract

core 层把"HTTP 请求升级为 WebSocket"抽象成一个两方法接口（`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/Handshaker.java:24-59`）：

```java
public interface Handshaker
{
    static Handshaker newInstance()
    {
        return new HandshakerSelector();
    }

    // ... 注释略
    boolean isWebSocketUpgradeRequest(Request request);

    boolean upgradeRequest(WebSocketNegotiator negotiator, Request request, Response response,
                           Callback callback, WebSocketComponents components,
                           Configuration.Customizer defaultCustomizer) throws WebSocketException;
}
```

返回值语义是整个链路的基石（`Handshaker.java:42-48` 的 javadoc）：`upgradeRequest` 返回 `true` 表示**已经生成了响应**（无论成功还是失败）并会完成 callback；返回 `false` 表示**没有生成响应**，调用方可以继续处理——这正是"WebSocket handler 与普通 handler 共存"的机制来源。

### The HTTP/1.1 Path (RFC 6455)

`RFC6455Handshaker` 先做协议判定：GET 方法 + HTTP/1.1（`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/internal/RFC6455Handshaker.java:41-58`）；基类 `AbstractHandshaker` 再统一校验 `Sec-WebSocket-Version: 13`（`internal/AbstractHandshaker.java:145-156`），缺 `Sec-WebSocket-Key` 直接 400（`RFC6455Handshaker.java:72-74`）。

主流程在 `AbstractHandshaker.upgradeRequest`（`AbstractHandshaker.java:54-140`）：解析头部（`negotiation.negotiate()`）→ 让 `WebSocketNegotiator` 产出 `FrameHandler` → 校验子协议与扩展 → 组装 `ExtensionStack` → 创建 `WebSocketCoreSession` 与 `WebSocketConnection` → 准备 101 响应：

```java
// RFC6455Handshaker.java:86-94
@Override
protected void prepareResponse(Response response, WebSocketNegotiation negotiation)
{
    response.setStatus(HttpStatus.SWITCHING_PROTOCOLS_101);
    HttpFields.Mutable responseFields = response.getHeaders();
    responseFields.put(UPGRADE_WEBSOCKET);
    responseFields.put(CONNECTION_UPGRADE);
    responseFields.put(HttpHeader.SEC_WEBSOCKET_ACCEPT, WebSocketUtils.hashKey(((RFC6455Negotiation)negotiation).getKey()));
}
```

连接接管点也在这里分野：h1 路径直接从当前 HTTP 连接取 `EndPoint`（`RFC6455Handshaker.java:78-84`，`connectionMetaData.getConnection().getEndPoint()`），并靠 `request.setAttribute(HttpStream.UPGRADE_CONNECTION_ATTRIBUTE, connection)`（`AbstractHandshaker.java:134`）通知 HTTP 层把流交出去。

```sequence
Client->Server: GET /ws HTTP/1.1 (Upgrade: websocket)
Note over Server: WebSocketUpgradeHandler.handle
Server->Server: WebSocketMappings 匹配路径 -> WebSocketNegotiator
Server->Server: RFC6455Handshaker.upgradeRequest
Note over Server: negotiate() 解析 Sec-WebSocket-* 头
Server->Server: negotiator.negotiate() -> FrameHandler
Server->Server: ExtensionStack.negotiate(permessage-deflate...)
Server->Server: new WebSocketCoreSession + WebSocketConnection
Server-->Client: 101 Switching Protocols
Note over Server: EndPoint 换绑到 WebSocketConnection
```

### The HTTP/2 Path (RFC 8441)

WebSocket over HTTP/2 走 **Extended CONNECT**：方法不是 GET 而是 `CONNECT`，协议版本是 HTTP/2，`:protocol` 为 `websocket`（`internal/RFC8441Handshaker.java:31-48`）。校验靠隧道支持而非 Upgrade 头（`internal/RFC8441Negotiation.java:31-37`）：

```java
@Override
public boolean validateHeaders()
{
    TunnelSupport tunnelSupport = getRequest().getTunnelSupport();
    if (tunnelSupport == null)
        return false;
    return "websocket".equals(tunnelSupport.getProtocol());
}
```

与 h1 路径的两点关键差异：

- **没有 101**。响应就是 `200 OK`（`RFC8441Handshaker.java:65-68`），因为 Extended CONNECT 在语义上是"建立隧道成功"，不是切换协议。
- **EndPoint 来自隧道**。字节流不是整条 HTTP/2 连接，而是该 stream 的 tunnel EndPoint：`request.getTunnelSupport().getEndPoint()`（`RFC8441Handshaker.java:57-62`）。

```sequence
Client->Server: HEADERS :method=CONNECT :protocol=websocket (HTTP/2)
Note over Server: SETTINGS 已宣告 ENABLE_CONNECT_PROTOCOL
Server->Server: RFC8441Handshaker.upgradeRequest
Note over Server: validateHeaders 要求 TunnelSupport(protocol=websocket)
Server->Server: negotiator.negotiate() -> FrameHandler
Server->Server: EndPoint 取自 request.getTunnelSupport()
Server-->Client: 200 OK (同一条 HTTP/2 连接上的新 stream)
```

服务端是否宣告 Extended CONNECT 能力由 `AbstractHTTP2ServerConnectionFactory` 的开关决定，**12.1.14 默认打开**（`jetty-http2-server-12.1.14/org/eclipse/jetty/http2/server/AbstractHTTP2ServerConnectionFactory.java:65`，getter/setter 在 `:231-240`）：

```java
private boolean connectProtocolEnabled = true;
```

两个 Handshaker 的选择由 `HandshakerSelector` 完成：**先试 RFC6455，若响应尚未提交再试 RFC8441**（`internal/HandshakerSelector.java:30-47`）：

```java
@Override
public boolean upgradeRequest(WebSocketNegotiator negotiator, Request request, Response response, Callback callback, WebSocketComponents components, Configuration.Customizer defaultCustomizer) throws WebSocketException
{
    // Try HTTP/1.1 WS upgrade, if this fails try an HTTP/2 WS upgrade if no response was committed.
    return rfc6455.upgradeRequest(negotiator, request, response, callback, components, defaultCustomizer) ||
        !response.isCommitted() && rfc8441.upgradeRequest(negotiator, request, response, callback, components, defaultCustomizer);
}
```

### WebSocketMappings: Path to Negotiator

`WebSocketMappings` 是"路径 → 端点"的登记表（`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/WebSocketMappings.java:51`），内部是 `PathMappings<WebSocketNegotiator>` 加一个 `HandshakerSelector` 字段（`:124-126`）。路径支持三种语法：Servlet 风格 `/path`、`*.ext`、`servlet|{spec}`，正则 `^{spec}`/`regex|{spec}`，URI 模板 `uri-template|{spec}`（`parsePathSpec`，`:102-122`）。它按 ContextHandler 属性共享（`WEBSOCKET_MAPPING_ATTRIBUTE`，`getMappings`/`ensureMappings`，`:54-83`）。`upgrade(request, ...)` 先 `getMatchedNegotiator`（按 `Request.getPathInContext` 匹配，`:231-244`），匹配不到返回 `false`，匹配到就交给 Handshaker（`:261-297`）。

## WebSocketUpgradeHandler and Where It Sits

core 层的 `WebSocketUpgradeHandler` 是 `Handler.Wrapper`（`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/WebSocketUpgradeHandler.java:27`）：

```java
@Override
public boolean handle(Request request, Response response, Callback callback) throws Exception
{
    try
    {
        if (_mappings.upgrade(request, response, callback, _customizer))
            return true;
        return super.handle(request, response, callback);
    }
    catch (Throwable x)
    {
        Response.writeError(request, response, callback, x);
        return true;
    }
}
```

（`:88-101`。）三个要点：

- **不中就放行**。路径没匹配到映射、或请求根本不是 WebSocket 升级，`_mappings.upgrade` 返回 `false`，请求原样交给下一个 handler——这解释了它为什么可以嵌在任意 Handler 树里与普通业务 handler 共存（整体请求链见 [Jetty 请求处理流程](/docs/CS/Framework/Jetty/RequestFlow.md)）。
- **默认末端是 404**。构造函数给它挂了个写 `HttpStatus.NOT_FOUND_404` 的子 handler（`:53-61`），映射全部落空且后面没有别的 handler 时客户端得到 404 而非悬死。
- **异常转写错误响应**。升级过程中抛出的 `WebSocketException` 由 `Response.writeError` 兜底。

`jetty-websocket-jetty-server` 有同名包装类（`org.eclipse.jetty.websocket.server.WebSocketUpgradeHandler`），但它包装的是下一节的 `ServerWebSocketContainer`：`from(server, context, configurator)` 内部 `ServerWebSocketContainer.ensure(server, context)`（`jetty-websocket-jetty-server-12.1.14/org/eclipse/jetty/websocket/server/WebSocketUpgradeHandler.java:83-108`），`handle` 先试容器再放行、异常同样转 `Response.writeError`（`:206-228`）。javadoc 明确它可以挂在 `ContextHandler` 子树或 `Server` 直接子级（`:26-39`）。

## Extension Points: WebSocketNegotiator and WebSocketCreator

扩展点有两个层级（`jetty-websocket-core-server-12.1.14/org/eclipse/jetty/websocket/core/server/`）：

- `WebSocketCreator` 只负责"从请求造一个端点 POJO"，返回 `Object`；**返回 null 时必须自行发送响应并完成 callback**（`WebSocketCreator.java:25-39`）。它适合按 origin、子协议做准入过滤。
- `WebSocketNegotiator` 更底层，直接产出 core 的 `FrameHandler`，且本身 `extends Configuration.Customizer`（`WebSocketNegotiator.java:21-35`）；静态工厂 `from(creator, factory[, customizer])` 把 Creator 包成 `CreatorNegotiator`（`:37-45`）。

`CreatorNegotiator.negotiate` 展示了两者的接缝：先在请求的 Context 里跑 `createWebSocket`，再用 `FrameHandlerFactory` 把 POJO 包成 `FrameHandler`（`internal/CreatorNegotiator.java:51-74`）：

```java
// ...
Context context = request.getContext();
Object websocketPojo;
// ...
context.run(() -> result.set(creator.createWebSocket(request, response, callback)));
websocketPojo = result.get();
// ...
FrameHandler frameHandler = factory.newFrameHandler(websocketPojo, request, response);
// ...
return frameHandler;
```

`FrameHandlerFactory` 即 core 的第二个扩展缝（`FrameHandlerFactory.java`）：不同编程模型各给一个工厂，这正是三层共引擎的实现手段。

## ServerWebSocketContainer: the Native API Entry

原生 API 的服务端入口只有一个类（`jetty-websocket-jetty-server-12.1.14/org/eclipse/jetty/websocket/server/ServerWebSocketContainer.java:57`）：

```java
public class ServerWebSocketContainer extends ContainerLifeCycle
    implements WebSocketContainer, Configurable, Invocable, Request.Handler
```

它**自己就是 `Request.Handler`**，所以既可以直接塞进 Handler 树，也可以由 `WebSocketUpgradeHandler` 包着用。关键行为：

- **获取与共享**：`ensure(server, contextHandler)` 创建组件池、`WebSocketMappings` 和容器本身并挂为 managed bean（`:74-89`）；启动时把自己写进 context 属性 `WebSocketContainer.class.getName()`（`doStart`，`:140-145`），任意代码用 `ServerWebSocketContainer.get(context)` 取回（`:117-120`）。
- **登记端点**：`addMapping(pathSpec, creator)` 查重后把原生 API 的 `WebSocketCreator` 包成 core creator，配 `ServerFrameHandlerFactory` 和容器级 `Configuration` 一起交给 `mappings.addMapping`（`:292-310`）。工厂侧 `ServerFrameHandlerFactory extends JettyWebSocketFrameHandlerFactory implements FrameHandlerFactory`，把端点 POJO 包成 `JettyWebSocketFrameHandler` 并补上已完成的 upgrade request/response（`internal/ServerFrameHandlerFactory.java:25-39`）——`JettyWebSocketFrameHandler` 本体在 `jetty-websocket-jetty-common`（不在镜像）。
- **两个升级入口**：`handle` 一行委托映射（`:335-338`）；`upgrade(creator, request, response, callback)` **跳过路径映射**直接造 negotiator 升级（`:359-364`），适合在自有 handler 里手工接管某个请求。
- **配置**：容器实现 `Configurable`（idle timeout、max message/frame size、autoFragment 等，`:188-282`），内部 `Configuration extends core 的 ConfigurationCustomizer`（`:411-413`）；这些值作为 `defaultCustomizer` 在 `AbstractHandshaker.upgradeRequest` 里 customize 到 `WebSocketCoreSession`（`AbstractHandshaker.java:111-114`）。
- **阻塞声明**：`InvocationType` 默认 `BLOCKING`，端点确定不用阻塞 API 时可设 `NON_BLOCKING`（`:394-409`），`WebSocketUpgradeHandler` 用 `Invocable.combine` 向上合并（`WebSocketUpgradeHandler.java:230-234`）。

嵌入式最小用法（源自该类 javadoc 内的 Typical usage 示例，`WebSocketUpgradeHandler.java:41-58`）：

```java
Server server = new Server(8080);
ContextHandler context = new ContextHandler("/app");

WebSocketUpgradeHandler wsHandler = WebSocketUpgradeHandler.from(server, context, container ->
{
    container.setMaxTextMessageSize(65536);
    container.addMapping("/ws", (upgradeRequest, upgradeResponse, callback) -> new EchoEndPoint());
});
context.setHandler(wsHandler);

server.setHandler(context);
server.start();
```

运行期拿到容器的等价方式是属性查找：`request.getContext().getAttribute(WebSocketContainer.class.getName())`（同文件 javadoc `:59-67`）。

## The jakarta.websocket Layer

`jetty-ee10-websocket-jakarta` 与 `jetty-ee11-websocket-jakarta` 是独立构件，**不在本篇源码镜像中，类名一律未确认**。可以确认的只有结构事实：EE 层在同一个 core 引擎之上提供 jakarta.websocket 编程模型（`WebSocketContainer` 属性共享、`ServerFrameHandlerFactory` 的工厂替换点都是为它准备的），ee10 与 ee11 各出一个构件以适配 `jakarta.*` 的版本差异，并存机制见 [Jetty EE Layer](/docs/CS/Framework/Jetty/EeLayer.md)。用 jakarta API 时必须单独引入对应 EE 构件，只有 core + jetty-server 构件时原生 API 可用而 jakarta API 不可用。

## Comparison with Tomcat

同一问题（把 HTTP 升级成 WebSocket）Tomcat 的解法是 Servlet 容器内生的（[Tomcat WebSocket 实现](/docs/CS/Framework/Tomcat/WebSocket.md)）：`WsSci implements ServletContainerInitializer` 在部署期扫描端点并挂 `WsServerContainer`（Tomcat/WebSocket.md 引 `tomcat-websocket` 源码 `WsSci`），升级后的连接交给 `UpgradeProcessorInternal` 这类 `WebConnection` 适配器。Jetty 12 的解法没有 SCI 环节：

| 维度 | Tomcat | Jetty 12 |
| :--- | :--- | :--- |
| 入口机制 | `ServletContainerInitializer`（`WsSci`） | Handler 树中的 `WebSocketUpgradeHandler` / `ServerWebSocketContainer`（本身就是 `Request.Handler`） |
| 每上下文登记处 | `WsServerContainer` | `WebSocketMappings`（按 ContextHandler 属性共享）+ `ServerWebSocketContainer` |
| 升级后连接载体 | `UpgradeProcessorInternal`（`WebConnection`） | `WebSocketConnection` 换绑 EndPoint，经 `HttpStream.UPGRADE_CONNECTION_ATTRIBUTE` 移交（`AbstractHandshaker.java:134`） |
| h2 WebSocket | — | RFC 8441 Extended CONNECT，`connectProtocolEnabled` 默认开 |
| 帧引擎与 API 的关系 | API 与实现同模块 | core 引擎与两套 API 三个模块分层 |

Servlet 侧背景见 [Servlet](/docs/CS/Java/JDK/Servlet.md)。

## Legacy Name Map (9/10/11 to 12)

| 旧类（9/10/11） | 12 中的去向 |
| :--- | :--- |
| `org.eclipse.jetty.websocket.server.WebSocketServerFactory` | 不存在。职责拆成 `WebSocketMappings`（路径映射与升级）+ `Handshaker`/`HandshakerSelector`（协议协商）+ `ServerWebSocketContainer`（编程入口） |
| `org.eclipse.jetty.websocket.server.WebSocketServer` | 不存在。配置改在 `ServerWebSocketContainer`（setter）或 `WebSocketUpgradeHandler.from(...)` 的 configurator 里做 |
| `org.eclipse.jetty.websocket.servlet.WebSocketServlet` | 原生 API 不再经 Servlet：用 `ServerWebSocketContainer`/`WebSocketUpgradeHandler`；jakarta 层入口在 EE 构件（未在镜像中确认） |
| `org.eclipse.jetty.websocket.common.WebSocketSession` | 拆成 core 的 `WebSocketCoreSession`（core-common，不在镜像）+ 原生 API 的 `Session`（由 `JettyWebSocketFrameHandler` 调度，jetty-common） |
| `org.eclipse.jetty.websocket.common.WebSocketAdapter` | 不存在。原生 API 改用 listener 方法或注解方法声明端点（`ServerWebSocketContainer.java:394-402` javadoc 措辞）；具体注解名未在镜像中确认 |

## Common Pitfalls

- **jakarta 层要单独引构件**。`jetty-ee10-websocket-jakarta` / `jetty-ee11-websocket-jakarta` 不随 core/native 构件带入，缺了会直接找不到 API（该模块未在镜像中确认）。
- **permessage-deflate 的配置点在 core-common**。扩展协商由 `ExtensionStack.negotiate` 完成（`AbstractHandshaker.java:99-106`），`ExtensionStack`/`WebSocketExtensionRegistry` 本体在 core-common；而 deflater/inflater 池通过 context/server 属性注入，`WebSocketServerComponents` 定义了 `jetty.websocket.deflater`、`jetty.websocket.inflater`、`jetty.websocket.bufferPool` 三个属性名并默认复用 `Server` 上的池（`jetty-websocket-core-server-12.1.14/.../WebSocketServerComponents.java:39-42, 49-63`）。
- **h2 WebSocket 依赖 Extended CONNECT 开关**。`connectProtocolEnabled` 默认 `true`（`AbstractHTTP2ServerConnectionFactory.java:65`）；显式设为 `false` 后 h2 层不再支持带 `:protocol` 的 CONNECT，`RFC8441Handshaker` 这条路径自然失效。HTTP/2 细节见 [HTTP/2](/docs/CS/Framework/Jetty/Http2.md)。
- **Handshaker 的返回值即放行协议**。自定义 Handler 桥接 WebSocket 时，`false` 意味着"没写响应、没完成 callback"，调用方必须接手；`negotiator.negotiate` 返回 null 也是同样约定（`WebSocketNegotiator.java:23-34`）。
- **pathSpec 只有三种语法**（servlet / regex / uri-template，`WebSocketMappings.java:102-122`），写别的形式直接 `IllegalArgumentException`；同一路径重复 `addMapping` 会被 `ServerWebSocketContainer` 拒绝（`:303-310`）。
- **默认 `InvocationType.BLOCKING`**。端点全部非阻塞却忘了设 `NON_BLOCKING` 只损失吞吐；反过来设了 `NON_BLOCKING` 却用阻塞 API，javadoc 明言可能导致服务器锁死（`ServerWebSocketContainer.java:394-409`）。线程预算见 [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)。

## Links

- [Jetty](/docs/CS/Framework/Jetty/Jetty.md)
- [Jetty 请求处理流程](/docs/CS/Framework/Jetty/RequestFlow.md)
- [HTTP/2](/docs/CS/Framework/Jetty/Http2.md)
- [Jetty EE Layer](/docs/CS/Framework/Jetty/EeLayer.md)
- [Jetty 线程模型](/docs/CS/Framework/Jetty/Threading.md)
- [Tomcat WebSocket 实现](/docs/CS/Framework/Tomcat/WebSocket.md)

## References

- [RFC 6455 - The WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
- [RFC 8441 - Bootstrapping WebSockets with HTTP/2](https://datatracker.ietf.org/doc/html/rfc8441)
- [Jetty Project Source (jetty.project)](https://github.com/jetty/jetty.project)
- [Jetty 12 Documentation](https://jetty.org/docs/jetty12/index.html)
