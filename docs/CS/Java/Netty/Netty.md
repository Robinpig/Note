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

## Sequence

> [Example writing a Discard Server](https://netty.io/wiki/user-guide-for-4.x.html#writing-a-discard-server)


### Bind

- BossEventLoop starts thread when register
- first register(Selector, 0, ServerSocketChannel)
- selectionKey.interestOps(OP_ACCEPT) when fireChannelActive() after bind

```plantuml
skinparam backgroundColor #DDDDDD

title: Bind sequence
participant MainThread as ma
participant ServerBootstrap as sb
participant BossEventLoopGroup as we
participant BossEventLoop as bl
participant ServerSocketChannel as cc
activate ma
ma ->> we: create EventLoopGroup
we ->> bl: create EventLoops
bl -->> bl: openSelector
note right: EventLoop for IO tasks
we -->> ma: EventLoopGroup
ma ->> sb: bind()
sb ->> cc: init ServerSocketChannel
note right
init ChannelPipeline 
with ServerBootstrapAceptor
end note
cc -->> sb: ServerSocketChannel with OP_ACCEPT
sb ->> we: register()
note right: not inEventLoop
we ->> bl: execute
sb --> ma: ChannelFuture
deactivate ma
bl --> bl: startThread()
activate bl
bl ->> cc: register(Selector, 0, ServerSocketChannel)
cc ->> cc: invokeHandlerAddedIfNeeded
cc ->> cc: notify the promise
note right: call doBind task
cc ->> cc: fireChannelRegistered
cc --> bl: Registration was complete and successful
bl ->> cc: Channel.bind()
participant AbstractUnsafe as au
cc ->> au: bind()
au -->> cc: doBind()
note left: javaChannel().bind()
cc ->> au: fireChannelActive
au -->> cc: doBeginRead()
note left: selectionKey.interestOps(OP_ACCEPT)
deactivate bl
```

### Connect

- BossEventLoop select() for OP_ACCEPT
- WorkerEventLoop starts thread when register
- first register(Selector, 0, SocketChannel)
- selectionKey.interestOps(OP_READ) when fireChannelActive()

```plantuml
skinparam backgroundColor #DDDDDD

title: Connect sequence
participant BossNioEventLoop as bg
participant Channel.Unsafe as us
participant ServerSocketChannel as sc
participant ServerBootstrapAceptor as sa
participant WorkerEventLoopGroup as wg
participant WorkerEventLoop as el
participant SocketChannel as sl
participant ChannelPipeline as pipe
activate bg
bg ->> bg: Selector.select()
note left: OP_ACCEPT event
bg ->> us: NioUnsafe.read()
us ->> sc: create SocketChannel
note right: ServerSocketChannel.accept()
sc -->> us: SocketChannel
us ->> sa: pipeline.fireChannelRead()
sa ->> sa: init SocketChannel
us ->> wg: regster()
wg ->> el: execute()
el --> el: startThread()
activate el
el -> sl: register(selector, 0, Channel)
sl ->> pipe: fireChannelRegistered()
sl ->> pipe: fireChannelActive()
note right: selectionKey.interestOps(OP_READ)
```


### Read

- ReadComplete contains multiple Reads(max 16)
- AdaptiveRecvByteBufAllocator try 2 reduce size and expand quickly
- default execute in WorkerEventLoop, also can define own ThreadPool when add Handlers

```plantuml
skinparam backgroundColor #DDDDDD

title: Read sequence
participant WorkEventLoop as we
participant Selector as se
activate we
we ->> we: Selector.select()
note right: OP_READ event
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
participant Allocator as ac
participant ByteBuf as bb
participant ChannelPipeline as pipe
participant ChannelInboundHandler as ch
ue ->> so: read()
loop continueReading
so ->> ac: allocate()
ac -->> so: ByteBuf 
so -->> bb: doReadBytes(ByteBuf) 
note over bb #FFAAAA
readBytes from javaChannel
end note
alt nothing left
bb -->> bb: release()
note over so #FFAAAA
    close = true
end note
else readPending
so ->> pipe: fireChannelRead()
pipe ->> ch: fireChannelRead()
note right
    handle data
    From Head to Tail
end note
end
end
so ->> ac: readComplete()
so ->> pipe: fireChannelReadComplete()
alt close == true
so -->> so: closeOnRead()
end

```

### Write

```plantuml
skinparam backgroundColor #DDDDDD

participant WorkerEventLoop as we
participant Selector as se
participant ByteBuf as bb

we ->> bb: write()
participant Channel.Unsafe as ue
participant HeadContext as hc

bb -->> ue: addMessage()
participant SocketChannel as so
participant ChannelPipeline as pipe
participant ChannelOutboundBuffer as ob
ue ->> ob: addMessage()
hc ->> ue: flush()
activate ue
so ->> ob: addFlush()
ue ->> so: doWrite()
note right: SocketChannel.write()
ue ->> so: NioUnsafe.read()
so ->> ue: OP_WRITE
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()

```

### Shutdown

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

- Direct Memory
- Composite ByteBuf
- FileChannel transfer

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
- [Dubbo](/docs/CS/Java/Dubbo/Dubbo.md)

## References

1. [Netty](https://netty.io/)
2. [Thread model](https://netty.io/wiki/thread-model.html)
