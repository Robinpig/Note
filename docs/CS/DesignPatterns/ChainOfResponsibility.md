## Introduction

> Avoid coupling the sender of a request to its receiver by giving more than one object a chance to handle the request. Chain the receiving objects and pass the request along the chain until an object handles it.
> —— GoF

责任链模式把请求沿着一条处理器链传递，每个节点有权处理它、改它，或者原样传给下一个。发送方只把请求交给链头，完全不知道最终由谁处理——这把"请求的处理顺序"从调用方代码里抽出来，变成可配置的流水线。

它是**Servlet Filter、Spring Security、Netty Pipeline、Dubbo Filter、OkHttp Interceptor** 的共同骨架：这些框架的扩展点全部是责任链的实例，掌握这一个模式等于拿到大半 Java 中间件的扩展模型。

## Anatomy

三个角色：**Handler**（抽象处理器，声明 `handle(request)` 并持有 `next` 引用）、**ConcreteHandler**（判断是否属于自己管，处理或下传）、**Client**（组装链、提交请求）。

```java
abstract class Handler {
    protected Handler next;
    public Handler link(Handler next) { this.next = next; return next; }  // 流式组装

    public void doFilter(Request req) {
        if (!intercept(req)) return;          // 短路：拦截，不再下传
        if (next != null) next.doFilter(req); // 下传
        else serve(req);                      // 链尾兜底
    }
    protected abstract boolean intercept(Request req);
}
```

两种终止条件必须分清：**链尾兜底**（Netty 的 inbound 一定走到 tail）与**中途短路**（Spring Security 任一 filter 拒绝即返回 401）——框架的语义差异全在这里。

## Where the Chain Lives

| 框架 | 链的载体 | 节点单位 | 短路语义 |
|------|---------|---------|---------|
| Servlet | `FilterChain` | Filter | 任一 filter 不调 `chain.doFilter` 即截断 |
| Spring Security | `SecurityFilterChain` bean | Filter | 认证/鉴权失败直接返回响应 |
| Netty | `ChannelPipeline` | `ChannelHandler` | inbound 必到 tail，outbound 必到 head |
| Dubbo | Filter 链 | 消费端/提供端 Filter | 抛异常即中断并触发回退 |
| OkHttp | `Interceptor.Chain` | Interceptor | 不调 `chain.proceed` 即短路 |

- **Servlet Filter**：`web.xml`/`@WebFilter` 声明顺序，一个 filter 同时持有 `ServletRequest` 与 `FilterChain`，`doFilter` 内做前处理 → 放行 → 后处理，是责任链最直白的形态；
- **Netty Pipeline**：把链升级为**双向**——入站从头到尾、出站从尾到头，且节点可动态增删（`addLast`、`remove`），SSL、idle、编解码、业务各占一层，见 [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)；
- **OkHttp Interceptor**：`chain.proceed(request)` 前后都可动手，重试与缓存天然是一层。注意应用拦截器只执行一次，网络拦截器在重定向时可能多次执行；
- **Spring Security**：十几把 filter 的顺序是安全边界的核心配置，`DelegatingFilterProxy` 把 servlet 容器与 Spring 的链桥接起来。

## Design Considerations

**顺序即语义**：日志应在最外层（看到完整耗时）、事务次之、权限在最内层前——顺序错了不会报错，只会静默出错。所以链的组装要集中（一个 `SecurityConfig`/一个 `FilterRegistrationBean` 列表），不要散落在各模块。

**不要无限延长**：节点超过七八个就该合并关注点。Netty 允许动态增删是特例（长连接生命周期管理），普通请求处理链每加一个节点都增加排障成本——排查"这个 header 是谁加的"在十层链里是噩梦。

**与 [装饰器](/docs/CS/DesignPatterns/Decorator.md)的区别**：装饰器的每一层通常**都**参与处理（层层叠加），责任链只有一个节点真正处理；装饰器强调增强，责任链强调分发。OkHttp Interceptor 同时具备两副面孔，这也是它难归类的原因。

**与 [Observer](/docs/CS/DesignPatterns/Observer.md)的区别**：责任链是同一请求的顺序加工，观察者是一事件的并行广播；前者有上下游，后者无顺序约定。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Decorator](/docs/CS/DesignPatterns/Decorator.md)
- [Observer](/docs/CS/DesignPatterns/Observer.md)
- [Netty ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)

## References

1. [Refactoring.Guru - Chain of Responsibility](https://refactoring.guru/design-patterns/chain-of-responsibility)
2. [OODesign - Chain of Responsibility Pattern](https://www.oodesign.com/chain-of-responsibility-pattern)
3. [Netty 4.1 ChannelPipeline Javadoc](https://netty.io/4.1/api/io/netty/channel/ChannelPipeline.html)
4. [Spring Security 架构文档（Servlet FilterChain）](https://docs.spring.io/spring-security/reference/servlet/architecture.html)
