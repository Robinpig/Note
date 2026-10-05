## Introduction

HTTP 是请求—响应式协议，服务端无法主动向浏览器推数据。需要实时推送时，可选的手段按代价从低到高排列：

| 手段 | 机制 | 方向 | 适用场景 |
| ---- | ---- | ---- | ---- |
| 轮询 | 客户端定时发请求 | 单向（拉） | 实时性要求低（分钟级），实现最简单 |
| 长轮询 | 请求挂起直到有数据 | 单向（伪推） | 兼容性要求高、不能升 WebSocket 的老环境 |
| **SSE** | HTTP 流，服务端持续写 | **单向（服务端→客户端）** | 行情推送、进度条、日志流；可用普通 HTTP 基础设施，自带断线重连 |
| **WebSocket** | 一次握手升级成全双工长连接 | **双向** | 聊天、协同编辑、在线游戏、实时看板 |

WebSocket 是其中唯一提供**双向、低开销长连接**的方案：握手用 HTTP（便于复用鉴权与反向代理），之后切换为帧协议，双方可随时互发，没有 HTTP 的请求头开销。

> [!NOTE]
> **分工**：本文讲 Spring 侧的编程模型；WebSocket 协议本身（握手过程、帧格式、掩码、心跳、掩码规则）见 [WebSocket](/docs/CS/CN/WebSocket.md)。

### 版本基线

Spring Framework **7.0** 把 baseline 提升到了 **Jakarta WebSocket 2.2**（配合 Servlet 6.1），应用应跑在 Tomcat 11+ / Jetty 12.1+。同时 7.0 **移除了老式 WebSocket 的 fallback 支持**（旧的浏览器降级机制），现代浏览器直接使用原生 WebSocket 即可。Spring Security **7.0** 则删除了遗留的 WebSocket 安全配置基类（见「鉴权」节）。

## 为什么还要 STOMP

WebSocket 只定义了"怎么传 bytes"，没有任何消息语义——没有目的地、没有订阅、没有发布/订阅寻址。直接用 `WebSocketHandler` 时，所有路由逻辑都得自己写。

**STOMP（Simple Text Oriented Messaging Protocol）** 是在 WebSocket 之上的一层轻量消息协议，用类 HTTP 的帧（CONNECT / SUBSCRIBE / SEND / MESSAGE / ACK）提供：

- **目的地（destination）**：`/topic/xxx`（广播，类似发布订阅）、`/queue/xxx`（点对点）；
- **订阅语义**：客户端订阅某个目的地，服务端按活跃订阅分发；
- **消息头**：内容类型、订阅 ID、自定义元数据；
- **心跳**：帧层的 keepalive 约定。

绝大多数 Spring WebSocket 应用都采用 **STOMP over WebSocket**，而非裸 WebSocket。

## 原生 WebSocket API

不需要 STOMP 时（如自定义二进制协议），用 `WebSocketHandler`：

```java
@Configuration
@EnableWebSocket
class RawWebSocketConfig implements WebSocketConfigurer {

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(new MyHandler(), "/ws")
            .setAllowedOriginPatterns("https://example.com")
            .addInterceptors(new HandshakeInterceptor() {

                @Override
                public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                               WebSocketHandler wsHandler, Map<String, Object> attributes) {
                    // 握手阶段还是 HTTP，可以拿到 cookie / header / session 做鉴权
                    attributes.put("user", resolveUser(request));
                    return true;
                }

                @Override
                public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                           WebSocketHandler wsHandler, Exception exception) {
                }
            });
    }
}
```

> [!WARNING]
> **必须显式配置允许的 Origin**。WebSocket **不受同源策略约束**——任意站点的脚本都能向你的 ws 端点发起握手，并带着用户的 cookie，这就是跨站 WebSocket 劫持（CSWSH）。
> 要用 `setAllowedOriginPatterns(...)` 白名单，不要图省事写 `"*"`。这也是 Origin 校验比普通 HTTP 更致命的地方。

## STOMP over WebSocket

```java
@Configuration
@EnableWebSocketMessageBroker
class WebSocketBrokerConfig implements WebSocketMessageBrokerConfigurer {

    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        // 客户端订阅地址前缀：凡是 /topic、/queue 开头的目的地都交给 broker
        registry.enableSimpleBroker("/topic", "/queue");
        // 服务端 @MessageMapping 地址前缀
        registry.setApplicationDestinationPrefixes("/app");
        // 点对点消息的用户前缀（默认就是 /user，可省略）
        registry.setUserDestinationPrefix("/user");
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.addEndpoint("/ws")
            .setAllowedOriginPatterns("https://example.com")
            .withSockJS();
    }
}
```

### 内存 broker 与中继 broker

| 模式 | 配置 | 特性 |
| ---- | ---- | ---- |
| Simple Broker | `enableSimpleBroker("/topic", "/queue")` | 内存 + 进程内维护订阅关系；零依赖、上手快 |
| Relay Broker | `enableStompBrokerRelay("/topic", "/queue")` | 转发给外部 STOMP broker（RabbitMQ、ActiveMQ 等），支持集群广播、持久化订阅 |

> [!WARNING]
> **集群部署必须换 relay**：内存 broker 的订阅表只在本 JVM 里。多个实例时，用户 A 连在实例 1、用户 B 连在实例 2，广播消息只会落在其中一个实例上，另一个实例的订阅者永远收不到。
> 这是 WebSocket 应用上多实例后最常见的"消息时有时无"故障。解法是 `enableStompBrokerRelay` 接到 RabbitMQ 之类的外部 broker（需先开启其 STOMP 插件，参见 [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)），或在应用层用消息中间件自行桥接各实例的订阅。

## 消息处理

```java
@Controller
class ChatController {

    private final SimpMessagingTemplate messaging;

    ChatController(SimpMessagingTemplate messaging) {
        this.messaging = messaging;
    }

    // 客户端 SEND 到 /app/chat.send → 处理后广播到 /topic/room.{id}
    @MessageMapping("chat.send")
    @SendTo("/topic/room/{roomId}")
    ChatMessage send(@DestinationVariable String roomId, ChatMessage message) {
        return message;
    }

    // 订阅即返回一次数据（不进 broker），适合拉取初始快照
    @SubscribeMapping("/topic/room.{roomId}")
    List<ChatMessage> history(@DestinationVariable String roomId) {
        return chatService.recent(roomId);
    }

    // 点对点推送 owner；客户端订阅 /user/queue/notify
    void notify(String username, Notification n) {
        messaging.convertAndSendToUser(username, "/queue/notify", n);
    }

    @MessageExceptionHandler
    @SendToUser("/queue/errors")
    String handle(ChatException e) {
        return e.getMessage();
    }
}
```

几个要点：

- **`@MessageMapping` 的地址不带 `/app` 前缀**——前缀是客户端 SEND 时用的，服务端方法写的是前缀之后的部分；
- `@SendTo` / `@SendToUser` 只是语法糖，复杂场景（条件推送、外部事件触发）直接用 `SimpMessagingTemplate`；
- `convertAndSendToUser` 依赖 handshake 阶段建立的 `Principal`，底层会转换成形如 `/user/<username>/queue/notify` 的私有队列。

## 鉴权

分两个层级，二者不可互相替代：

1. **握手层（HTTP）**：此时还是普通 HTTP 请求，`HandshakeInterceptor` 能拿到 cookie / header / session。拒绝就返回 false，连升级都不会发生。这是第一道门。
2. **帧层（STOMP）**：连接已建立，客户端可以发任意 SUBSCRIBE / SEND。需要在 STOMP 帧级别限制"这个用户能不能订阅这个目的地"，用 `ChannelInterceptor`。

```java
@Override
public void configureClientInboundChannel(ChannelRegistration registration) {
    registration.interceptors(new ChannelInterceptor() {

        @Override
        public Message<?> preSend(Message<?> message, MessageChannel channel) {
            StompHeaderAccessor accessor = StompHeaderAccessor.wrap(message);
            if (StompCommand.SUBSCRIBE.equals(accessor.getCommand())
                && !canAccess(accessor.getUser(), accessor.getDestination())) {
                throw new AccessDeniedException("denied");
            }
            return message;
        }
    });
}
```

> [!WARNING]
> Spring Security **7.0 已删除** `AbstractSecurityWebSocketMessageBrokerConfigurer` 与 `MessageSecurityMetadataSourceRegistry` 这套遗留配置（自 5.8 起就已被更直接的 ChannelInterceptor / `@MessageMapping` 方法级鉴权取代）。升级后应改为自己实现 `ChannelInterceptor`，或直接在 `@MessageMapping` 方法上加 `@PreAuthorize`（见 [Spring Security](/docs/CS/Framework/Spring/Security.md)）。

### SockJS 与 CSRF

SockJS 回退 transport 会用 HTTP POST 发送 CONNECT 帧，而它**无法**把 CSRF token 放进 HTTP 头或参数——只能放进 STOMP 帧头。因此服务端必须为连接端点放行 CSRF，否则 SockJS 降级后直接 403：

```java
@Bean
SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    http
        .csrf(csrf -> csrf
            .ignoringRequestMatchers("/ws/**"))          // 仅放行连接端点
        .headers(headers -> headers
            .frameOptions(frameOptions -> frameOptions.sameOrigin()));  // SockJS 的 iframe transport 需要
    return http.build();
}
```

注意这里**只放行连接端点**，不能全局关闭 CSRF——那样整个站就裸奔了。STOMP 侧的 CSRF token 由客户端在 CONNECT 帧头里带上，服务端 SockJS 会校验。

## 心跳与连接保活

长连接穿过 NAT、负载均衡、CDN 时，空闲一段时间会被中间设备默默掐掉，而两端都收不到 FIN——表现为"连接看起来在但发不出去"。解法是双向心跳：

```java
@Override
public void configureMessageBroker(MessageBrokerRegistry registry) {
    registry.enableSimpleBroker("/topic")
        .setHeartbeatValue(new long[]{10_000, 10_000})   // [服务端最小发送间隔, 期望接收间隔]
        .setTaskScheduler(heartbeatScheduler());
}
```

客户端从 CONNECTED 帧拿到协商后的心跳值后，会按此发送 `\n` 心跳帧。生产环境的 Nginx / K8s Ingress 通常有 60s 的空闲超时，心跳间隔务必远小于它。

## 集群下的其他考虑

| 问题 | 说明 |
| ---- | ---- |
| 订阅表分散 | 见上文「内存 broker 与中继 broker」，必须换 relay 或自行桥接 |
| 负载均衡算法 | WebSocket 是长连接，Round-Robin 可用；但若用了 HTTP session 亲和，需确认握手与后续帧不会跨实例（推荐 STATELESS + JWT，参见 [Spring Session](/docs/CS/Framework/Spring/Session.md)） |
| 优雅停机 | 滚动发布时要先摘流量、再等待连接自然关闭；直接 kill 会造成客户端批量重连风暴。配合 K8s `preStop` 与 Boot 的 `server.shutdown: graceful` |
| 消息可靠性 | STOMP over WebSocket 本身**不做持久化**：客户端断线期间发出的广播就是丢了。重要通知必须落库 + 重连后补推，不能依赖 broker |

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [WebSocket](/docs/CS/CN/WebSocket.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [Spring Session](/docs/CS/Framework/Spring/Session.md)
- [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md)
- [RabbitMQ](/docs/CS/MQ/RabbitMQ.md)

## References

1. [Spring Framework Reference - WebSocket](https://docs.spring.io/spring-framework/reference/web/websocket.html)
2. [Spring Framework 7.0 Release Notes](https://github.com/spring-projects/spring-framework/wiki/Spring-Framework-7.0-Release-Notes)
3. [Spring Security Reference - WebSocket Security](https://docs.spring.io/spring-security/reference/servlet/integrations/websocket.html)
4. [STOMP 协议规范](https://stomp.github.io/stomp-specification-1.2.html)
