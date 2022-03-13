## Introduction

[Netty](https://netty.io) is a NIO client server framework which enables quick and easy development of network applications such as protocol servers and clients.
It greatly simplifies and streamlines network programming such as TCP and UDP socket server.

- [Bootstrap](/docs/CS/Java/Netty/Bootstrap.md)
- [EventLoop](/docs/CS/Java/Netty/EventLoop.md)
- [ByteBuf](/docs/CS/Java/Netty/ByteBuf.md)
- [Future](/docs/CS/Java/Netty/Future.md)
- [FastThreadLocal](/docs/CS/Java/Netty/FastThreadLocal.md)

## Architecture

### Combining and Slicing ChannelBuffers

When transfering data between communication layers, data often needs to be combined or sliced.
For example, if a payload is split over multiple packages, it often needs to be be combined for decoding.
Traditionally, data from the multiple packages are combined by copying them into a new byte buffer.
Netty supports a zero-copy approach where by a ChannelBuffer "points" to the required buffers hence eliminating the need to perform a copy.

### Universal Asynchronous I/O API

Traditional I/O APIs in Java provide different types and methods for different transport types.
Netty has a universal asynchronous I/O interface called a [Channel](/docs/CS/Java/Netty/Channel.md), which abstracts away all operations required for point-to-point communication.
That is, once you wrote your application on one Netty transport, your application can run on other Netty transports.

### Event Model based on the Interceptor Chain Pattern

A well-defined and extensible event model is a must for an event-driven application.
Netty has a well-defined event model focused on I/O.
It also allows you to implement your own event type without breaking the existing code because each event type is distinguished from another by a strict type hierarchy.
This is another differentiator against other frameworks.

## Writing a Discard Server



From [writing a Discard Server](https://netty.io/wiki/user-guide-for-4.x.html#writing-a-discard-server)

### Sequence

#### Bind

```plantuml
title: bind sequence
actor User
participant ServerBootstrap as sb
participant ChannelFactory as cf
participant EventLoopGroup as we
participant EventLoop as bl
User ->> we: create EventLoopGroup
we ->> bl: create EventLoops \n and its own Selector
note right: EventLoop for IO tasks
User ->> sb: bind()
sb ->> cf: new ServerSocketChannel
cf -->> sb: ServerSocketChannel with OP_ACCEPT
sb ->> we: register()
we ->> bl: register()
bl --> bl: startThread()
activate bl
bl ->> bl: register 0 and ServerSocketChannel into Selector
bl ->> bl: fireChannelRegistered
sb ->> we: doBind()
we ->> bl: doBind()
participant Channel as cc
bl ->> cc: Channel.bind()
participant AbstractUnsafe as au
cc ->> au: bind()
au -->> cc: doBind()
note left: javaChannel().bind()
au ->> cc: fireChannelActive
au ->> cc: doBeginRead()
note left: selectionKey.interestOps(OP_ACCEPT)
deactivate bl
```

#### Connect

```plantuml
title: connect sequence
actor User
participant Selector as sr
participant NioUnsafe as us
participant BossNioEventLoopGroup as bg
participant NioServerSocketChannel as sc
participant ServerBootstrapAceptor as sa
participant WorkerNioEventLoopGroup as wg
participant WorkerNioEventLoop as wl
participant NioEventLoop as el
sr ->> sr: selector.select()
bg ->> us: NioUnsafe.read()
us ->> sc: create NioSocketChannel
note right: ServerSocketChannel.accept()
sc -->> us: NioSocketChannel
us ->> sa: pipeline.fireChannelRead()
sa ->> sa: init NioSocketChannel
us ->> wg: regster NioSocketChannel into Selector
wg ->> el: register()
activate el
note right: register(selector, 0, Channel)
el --> el: pipeline.fireChannelActive()
note left: register OP_READ
```

```plantuml
title: conn
actor User
participant BossEventLoop as bp
bp -->> bp: selector.select()
User -->> bp: send messages

participant NioByteUnsafe as ue
bp ->> ue: NioUnsafe.read()
participant NioServerSocketChannel as ss
ue ->> ss: create NioSocketChannel
ss -->> ue: NioSocketChannel
participant ServerBootstrapAcceptor as sa
ue ->> sa: pipeline.fireChannelRead()
sa -->> sa: init NioSocketChannel
participant WorkEventLoop as we
sa -->> we: regster NioSocketChannel into Selector
we ->> we: register OP_WRITE | OP_READ
we -->> we: pipeline.fireChannelActive()

```

#### Read

```plantuml
title: read sequence
actor User
User -->> User: send messages
participant WorkEventLoop as we
participant Selector as se
activate we
we ->> se: select
note right: selector.select()
se ->> we: OP_READ
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
participant ChannelPipeline as pipe
ue ->> so: read()
note right: doReadMessages
ue ->> pipe: fireChannelRead()
ue -->> so: data
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()

```

Start sequence
#### Write

```plantuml
actor User
User -->> User: send messages
participant WorkEventLoopGroup as we
participant Selector as se
we ->> we: create threads and open Selectors
we ->> we: initAndRegister
we ->> we: doBind0
se ->> we: OP_READ
participant NioByteUnsafe as ue
participant HeadContext as hc
we ->> ue: NioUnsafe.write()
participant NioSocketChannel as so
participant ChannelPipeline as pipe
participant ChannelOutboundBuffer as ob
ue ->> ob: outboundBuffer.addMessage()
hc ->> ue: flush()
activate ue
ue ->> ob: outboundBuffer.addFlush()
ue ->> so: doWrite
note right: SocketChannel.write()
ue ->> so: NioUnsafe.read()
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()

```

#### Shutdown

```plantuml
title: shutdown
actor User
participant EventLoopGroup as eg
participant EventLoop as el
activate el
el -> el: runAllTasks()
User -> eg: shutdownGracefully()
eg -> el: shutdownGracefully()
note right: cas set state \n ST_STARTED -> ST_SHUTTING_DOWN
el -> el: confirmShutdown()
el -> el: closeAll()
participant Channel as ch
participant Selector as se
el -> se: cancel registed channels
el -> ch: close NIO channels
deactivate el
```

```java
/**
 * Discards any incoming data.
 */
public class DiscardServer {
  
    private int port;
  
    public DiscardServer(int port) {
        this.port = port;
    }
  
    public void run() throws Exception {
        EventLoopGroup Group = new NioEventLoopGroup(); // (1)
        EventLoopGroup workerGroup = new NioEventLoopGroup();
        try {
            ServerBootstrap b = new ServerBootstrap(); // (2)
            b.group(Group, workerGroup)
             .channel(NioServerSocketChannel.class) // (3)
             .childHandler(new ChannelInitializer<SocketChannel>() { // (4)
                 @Override
                 public void initChannel(SocketChannel ch) throws Exception {
                     ch.pipeline().addLast(new DiscardServerHandler());
                 }
             })
             .option(ChannelOption.SO_BACKLOG, 128)          // (5)
             .childOption(ChannelOption.SO_KEEPALIVE, true); // (6)
  
            // Bind and start to accept incoming connections.
            ChannelFuture f = b.bind(port).sync(); // (7)
  
            // Wait until the server socket is closed.
            // In this example, this does not happen, but you can do that to gracefully
            // shut down your server.
            f.channel().closeFuture().sync(); // (8)
        } finally {
            workerGroup.shutdownGracefully();
            Group.shutdownGracefully();
        }
    }
  
    public static void main(String[] args) throws Exception {
        int port = 8080;
        if (args.length > 0) {
            port = Integer.parseInt(args[0]);
        }

        new DiscardServer(port).run();
    }
}
```

1. [Create EventLoopGroup](/docs/CS/Java/Netty/EventLoop.md?id=create-nioeventloopgroup)
2. [Create ServerBootstrap](/docs/CS/Java/Netty/Bootstrap.md?id=create-serverbootstrap)
3. Set [Channel](/docs/CS/Java/Netty/Channel.md)
4. Set [ChannelHandler](/docs/CS/Java/Netty/ChannelHandler.md)
5. Option
6. ChildOption
7. [ServerBootstrap#bind()](/docs/CS/Java/Netty/Bootstrap.md?id=bind)
8. [ChannelFuture](/docs/CS/Java/Netty/Future.md)

### close

## Under Hood

AllocateByteBuf

## Zero Copy

Direct Memory
Composite Buf
File transfer

## recycler

count

Chunk
Page
SubPage

## Log

- The default factory is *Slf4JLoggerFactory*.
- If SLF4J is not available, *Log4JLoggerFactory* is used.
- If Log4J is not available, *JdkLoggerFactory* is used.
-

You can change it to your preferred logging framework before other Netty classes are loaded: `InternalLoggerFactory.setDefaultFactory(Log4JLoggerFactory.INSTANCE)`;

> [!NOTE]
>
> The new default factory is effective only for the classes which were loaded after the default factory is changed.
> Therefore, setDefaultFactory(InternalLoggerFactory) should be called as early as possible and shouldn't be called more than once.

[Future and Promise](/docs/CS/Java/Netty/Future.md)

## Links

- [Java NIO](/docs/CS/Java/JDK/IO/NIO.md)

## References

1. [Netty](https://netty.io/)
2. [Thread model](https://netty.io/wiki/thread-model.html)
