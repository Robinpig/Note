## Introduction

Bootstrap 把"启动 Channel"的所有配置项封装成一条链式 API——客户端用 `Bootstrap.connect()`，服务端用 `ServerBootstrap.bind()`。两者共享 `AbstractBootstrap` 基类，差异在 init 的内容和 EventLoopGroup 数量（ServerBootstrap 有 parent/child 两个 group）。

本文以 **Netty 4.2.19.Final** 源码为准。

## Bootstrap 家族

| 类 | 用途 | EventLoopGroup | 核心方法 |
| :--- | :--- | :--- | :--- |
| `AbstractBootstrap<B,C>` | 基类，持有 channelFactory / handler / options / attrs | 1 个（group） | `bind()` / `register()` / `initAndRegister()` |
| `Bootstrap` | 客户端（TCP 连接 / UDP 无连接绑定） | 1 个 | `connect()` / `doResolveAndConnect()` |
| `ServerBootstrap` | 服务端监听 + accept | **2 个**（parent accept + child 处理） | `bind()` + 内嵌 `ServerBootstrapAcceptor` |

所有配置项都是 `volatile` 或同步容器（`LinkedHashMap options` / `ConcurrentHashMap attrs`），保证配置线程与 init 线程间可见。

## initAndRegister Core

`bind()` / `connect()` / `register()` 三条路径最终都汇入 `AbstractBootstrap.initAndRegister()`：

```java
final ChannelFuture initAndRegister() {
    Channel channel = null;
    try {
        channel = channelFactory.newChannel();  // ① 反射 or 用户自定义工厂
        init(channel);                         // ② 子类实现：塞 handler / options / attrs
    } catch (Throwable t) {
        if (channel != null) {
            channel.unsafe().closeForcibly();   // newChannel 成功但 init 失败 → 强制关
            return new DefaultChannelPromise(channel, GlobalEventExecutor.INSTANCE)
                    .setFailure(t);              // 失败 promise 绑定 GlobalEventExecutor 兜底
        }
        return new DefaultChannelPromise(new FailedChannel(), GlobalEventExecutor.INSTANCE)
                .setFailure(t);                  // newChannel 崩溃（too many open files）→ FailedChannel
    }
    final ChannelFuture regFuture = config().group().register(channel); // ③ 交给 EventLoopGroup 注册
    if (regFuture.cause() != null) {
        if (channel.isRegistered()) {
            channel.close();
        } else {
            channel.unsafe().closeForcibly();
        }
    }
    return regFuture;
}
```

**三步语义**：
1. **channelFactory.newChannel()**：反射 `ReflectiveChannelFactory`（默认）或用户自定义 `ChannelFactory`；失败时 channel 可能为 null（如 `SocketException("too many open files")`）
2. **init(channel)**：子类实现，往 pipeline 塞 handler、设 options / attrs、跑 ChannelInitializerExtension
3. **group.register(channel)**：把 Channel 交给 EventLoopGroup 的某个 EventLoop 线程去注册（IO 线程）

### 失败兜底的两种 Promise

init 阶段任何异常都导致 bootstrap 返回一个失败的 `ChannelFuture`。Netty 特意用 **`GlobalEventExecutor.INSTANCE`** 而不是 channel.eventLoop() 绑定这个 promise——因为此时 channel 还没注册，eventLoop() 会抛 `IllegalStateException`。分两种情况：
- **channel 对象已创建**（init 里抛）：promise 绑定真实 channel + GlobalEventExecutor，closeForcibly 关底
- **channel 没创建**（newChannel 崩溃）：用 `FailedChannel` 占位，promise 绑定 GlobalEventExecutor

### init 里跑什么

Bootstrap.init 比 ServerBootstrap.init 简单得多：

```java
// Bootstrap.init —— 客户端
void init(Channel channel) throws Throwable {
    ChannelPipeline p = channel.pipeline();
    p.addLast(config.handler());                          // 一个 handler（ChannelInitializer 直接挂）
    setChannelOptions(channel, newOptionsArray(), logger);
    setAttributes(channel, newAttributesArray());
    for (ChannelInitializerExtension ext : extensions) {   // SPI 扩展（4.2 新增）
        ext.postInitializeClientChannel(channel);
    }
}

// ServerBootstrap.init —— 服务端
void init(Channel channel) throws Throwable {
    setChannelOptions(channel, newOptionsArray(), logger);
    setAttributes(channel, newAttributesArray());

    final Entry<ChannelOption<?>, Object>[] currentChildOptions = newOptionsArray(childOptions);
    final Entry<AttributeKey<?>, Object>[] currentChildAttrs = newAttributesArray(childAttrs);
    final Collection<ChannelInitializerExtension> extensions = getInitializerExtensions();

    p.addLast(new ChannelInitializer<Channel>() {        // ServerBootstrapAcceptor 包装成 ChannelInitializer
        void initChannel(final Channel ch) {
            ChannelHandler handler = config.handler();
            if (handler != null) {
                pipeline.addLast(handler);                // ① 用户配置的 accept 侧 handler
            }
            ch.eventLoop().execute(() -> {                // ② 下一个 EventLoop 循环才 add Accept —— 防 handlerAdded 里 re-pipeline
                pipeline.addLast(new ServerBootstrapAcceptor(
                        ch, currentChildGroup, currentChildHandler,
                        currentChildOptions, currentChildAttrs, extensions));
            });
        }
    });
}
```

**差异要点**：
- ServerBootstrap 把 ServerBootstrapAcceptor 加进 pipeline **是在 eventLoop.execute 的异步块里**（见上文 `ch.eventLoop().execute`）——issue #1328 实锤：如果直接在 initChannel 里 addLast，handlerAdded 回调里若有 re-pipeline 操作，新 handler 会被 Accept 抢先 add 进去
- ServerBootstrap init 里先 `newOptionsArray(childOptions)` 拿一个快照（数组），ServerBootstrapAcceptor 闭包捕获的是这个数组而非 volatile 字段——防止 bootstrap.clone() 共享同一 map 的写竞争
- 两边都支持 `ChannelInitializerExtension` SPI（4.2 新增，`extensionsClassLoader(classLoader)` 指定加载器）

## bind Path

```java
private ChannelFuture doBind(final SocketAddress localAddress) {
    final ChannelFuture regFuture = initAndRegister();
    final Channel channel = regFuture.channel();
    if (regFuture.cause() != null) {
        return regFuture;            // initAndRegister 失败直接返回
    }
    if (regFuture.isDone()) {
        // 快路径：注册已完成（一般我们在 EventLoop 线程调用）
        ChannelPromise promise = channel.newPromise();
        doBind0(regFuture, channel, localAddress, promise);
        return promise;
    } else {
        // 慢路径：注册还没完成（从非 EventLoop 线程启动）
        final PendingRegistrationPromise promise = new PendingRegistrationPromise(channel);
        regFuture.addListener(future -> {
            Throwable cause = future.cause();
            if (cause != null) {
                promise.setFailure(cause);
            } else {
                promise.registered();   // 成功才让 promise 用 channel.eventLoop()
                doBind0(regFuture, channel, localAddress, promise);
            }
        });
        return promise;
    }
}
```

### PendingRegistrationPromise 的 executor() 技巧

```java
static final class PendingRegistrationPromise extends DefaultChannelPromise {
    private volatile boolean registered;
    @Override
    protected EventExecutor executor() {
        if (registered) {
            return super.executor();  // channel.eventLoop()
        }
        return GlobalEventExecutor.INSTANCE; // 兜底，issue #2586
    }
}
```

**issue #2586 的场景**：从非 EventLoop 线程调用 `doBind()`，regFuture 未完成时 Channel 的 eventLoop 还没绑定。此阶段 promise.executor() 若返回 `super.executor()`（依赖 channel.eventLoop()），会抛 IllegalStateException。所以返回 GlobalEventExecutor 兜底，等注册成功后 `promise.registered()` 才切回 channel.eventLoop()。

### doBind0 —— 为什么又 execute 一次？

```java
private static void doBind0(ChannelFuture regFuture, Channel channel,
                            SocketAddress localAddress, ChannelPromise promise) {
    channel.eventLoop().execute(new Runnable() {
        public void run() {
            if (regFuture.isSuccess()) {
                channel.bind(localAddress, promise).addListener(ChannelFutureListener.CLOSE_ON_FAILURE);
            } else {
                promise.setFailure(regFuture.cause());
            }
        }
    });
}
```

注释写得很清楚：**"This method is invoked before channelRegistered() is triggered"**。initAndRegister 刚把注册任务丢进 EventLoop 队列，回调还没执行。让 bind 也排队，就能保证 **channelRegistered 先触发完 pipeline 的 handlerAdded，bind 才真正调 doBind**——给用户 handler 在 channelRegistered 回调里做 pipeline 初始化的时间窗口。

## connect 路径 —— 地址解析 + 连接两段式

Bootstrap.connect 比 bind 复杂：它把**名字解析**和**TCP connect**串在一起：

```java
private ChannelFuture doResolveAndConnect(SocketAddress remoteAddress, SocketAddress localAddress) {
    final ChannelFuture regFuture = initAndRegister();
    if (regFuture.isDone()) {
        if (!regFuture.isSuccess()) return regFuture;
        return doResolveAndConnect0(channel, remoteAddress, localAddress, channel.newPromise());
    } else {
        final PendingRegistrationPromise promise = new PendingRegistrationPromise(channel);
        regFuture.addListener(future -> {
            Throwable cause = future.cause();
            if (cause != null) { promise.setFailure(cause); }
            else { promise.registered(); doResolveAndConnect0(...); }
        });
        return promise;
    }
}
```

### doResolveAndConnect0 —— 名字解析的三种情况

```java
promise.addListener(ChannelFutureListener.CLOSE_ON_FAILURE); // ① 取消或失败时自动 close
if (disableResolver) {                                       // ② 显式关闭解析
    doConnect(remoteAddress, localAddress, promise);
    return promise;
}
resolver = ExternalAddressResolver.getOrDefault(externalResolver).getResolver(eventLoop);
if (!resolver.isSupported(remoteAddress) || resolver.isResolved(remoteAddress)) {
    doConnect(remoteAddress, localAddress, promise);         // ③ 已解析 or resolver 不支持 → 直接连
    return promise;
}
resolveFuture = resolver.resolve(remoteAddress);
if (resolveFuture.isDone()) {
    if (resolveFuture.cause() != null) {                     // ④ 立即解析失败
        channel.close(); promise.tryFailure(resolveFuture.cause());
    } else {
        doConnect(resolveFuture.getNow(), localAddress, promise); // ⑤ 立即缓存命中
    }
    return promise;
}
resolveFuture.addListener(...);                              // ⑥ 异步等待解析完成
```

**ExternalAddressResolver 用 Holder 静态内部类**——netty-resolver 包是可选依赖（UDP 不用解析），如果用户 pom 里没引会触发 `NoClassDefFoundError`。Holder 里的静态初始化把异常吞了，不影响 bootstrap 其它方法。

### doConnect —— 同 doBind0，又是 execute 一次

```java
private static void doConnect(SocketAddress remoteAddress, SocketAddress localAddress,
                              ChannelPromise connectPromise) {
    final Channel channel = connectPromise.channel();
    channel.eventLoop().execute(new Runnable() {
        public void run() {
            if (localAddress == null) {
                channel.connect(remoteAddress, connectPromise);
            } else {
                channel.connect(remoteAddress, localAddress, connectPromise);
            }
        }
    });
}
```

原因同 doBind0：让 channelRegistered 的 pipeline 初始化先完成。

## ServerBootstrapAcceptor —— Child Channel Register

```java
private static class ServerBootstrapAcceptor extends ChannelInboundHandlerAdapter {
    public void channelRead(ChannelHandlerContext ctx, Object msg) {
        final Channel child = (Channel) msg;
        child.pipeline().addLast(childHandler);          // ① 用户配置的子 handler
        setChannelOptions(child, childOptions, logger);   // ② childOptions（SO_SNDBUF/RCVBUF 等）
        setAttributes(child, childAttrs);                // ③ childAttrs
        for (ChannelInitializerExtension ext : extensions) {
            ext.postInitializeServerChildChannel(child); // ④ SPI 扩展
        }
        try {
            childGroup.register(child).addListener(future -> {
                if (!future.isSuccess()) {
                    forceClose(child, future.cause());   // ⑤ 子 register 失败 → 强制 close
                }
            });
        } catch (Throwable t) {
            forceClose(child, t);                         // ⑥ group.register() 抛 → 强制 close
        }
    }
    public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
        config.setAutoRead(false);                       // 停止 accept，让 server channel 喘息
        ctx.channel().eventLoop().schedule(enableAutoReadTask, 1, SECONDS); // 1 秒后恢复
        ctx.fireExceptionCaught(cause);
    }
}
```

**ServerBootstrap 的 EventLoop 拓扑**：
- BossEventLoopGroup（parent）：ServerSocketChannel 的 accept 循环（NIO accept → 返回 NioSocketChannel → 包装成 msg 触发 channelRead）
- WorkerEventLoopGroup（child）：接收 ServerBootstrapAcceptor 派发的 NioSocketChannel，每个新 socket round-robin 到一个 worker EventLoop

父→子的 EventLoop 传递发生在 `childGroup.register(child)` 这行——Bootstrap.init 里的 `newOptionsArray(childOptions)` 快照机制就是为了让 accept 时的数组与配置时一致，避免多个 accept 线程共享同一 LinkedHashMap 并发写。

**enableAutoReadTask** 提前创建 Runnable（issue #1328 注释明确）——避免 server channel 已经因为 accept 风暴触发 "too many open files"，此时 URLClassLoader 的 file descriptors 也耗尽了，schedule 任务时连这个 Runnable 类都加载不了。提前 new 好就不会再触发 class loading。

## validate —— 哪些配置漏了会崩

| Bootstrap | validate() 抛条件 |
| :--- | :--- |
| Abstract | group == null / channelFactory == null |
| Bootstrap | super 全部 + **handler == null** |
| ServerBootstrap | super 全部 + **childHandler == null** + childGroup == null 只 warn 不抛（自动 fallback 到 parentGroup） |

**ServerBootstrap 故意允许 childGroup 未设**：单 EventLoopGroup（一个 group）的服务端场景下，parent 和 child 共用同一个 EventLoopGroup——这是最简单的多线程模型（accept 和 IO 在同一个 group 里 round-robin）。

## 选项设置的容错

```java
static void setChannelOptions(Channel channel, Map.Entry[] options, InternalLogger logger) throws Throwable {
    for (Map.Entry<ChannelOption<?>, Object> e: options) {
        try {
            if (!channel.config().setOption(e.getKey(), e.getValue())) {
                logger.warn("Unknown channel option '{}'", e.getKey());
            }
        } catch (Throwable t) {
            logger.warn("Failed to set channel option '{}'", e.getKey(), t);
            if (CLOSE_ON_SET_OPTION_FAILURE) {        // 默认 true
                throw t;                             // 让 init 崩溃→ channel 被 closeForcibly
            }
        }
    }
}
```

`CLOSE_ON_SET_OPTION_FAILURE` 是系统属性 `io.netty.bootstrap.closeOnSetOptionFailure`，默认 `true`——让 setOption 失败也能把 `initAndRegister` 推到 catch 块里，最终 channel 被 closeForcibly。若设为 false，失败只 warn，channel 继续创建。

## Links

- [Netty Channel 与注册路径](/docs/CS/Framework/Netty/Channel.md)
- [ChannelPipeline 与 Handler](/docs/CS/Framework/Netty/ChannelHandler.md)
- [Transport 与 IoHandler 抽象](/docs/CS/Framework/Netty/Transport.md)
- [EventLoop 与线程模型](/docs/CS/Framework/Netty/EventLoop.md)
- [Future and Promise](/docs/CS/Framework/Netty/Future.md)
- [ServerSocketChannel accept —— NioServerSocketChannel.doReadMessages](/docs/CS/Framework/Netty/Channel.md?id=serversocketchannel-accept)

## References

1. [Netty 4.2 AbstractBootstrap source](https://github.com/netty/netty/blob/4.2/transport/src/main/java/io/netty/bootstrap/AbstractBootstrap.java)
2. [Netty #2586 — PendingRegistrationPromise executor fallback](https://github.com/netty/netty/issues/2586)
3. [Netty #1328 — enableAutoReadTask pre-create + autoRead 1s recovery](https://github.com/netty/netty/issues/1328)
4. [Netty #4805 — autoRead on re-register](https://github.com/netty/netty/issues/4805)
5. [Netty #11981 — ServerBootstrapAcceptor exceptionCaught autoRead stop](https://github.com/netty/netty/issues/11981)
