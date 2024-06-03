## Introduction

[Netty](https://netty.io) is a [NIO](/docs/CS/Java/JDK/IO/NIO.md) client server framework which enables quick and easy development of network applications such as protocol servers and clients.
It greatly simplifies and streamlines network programming such as TCP and UDP socket server.

- **Ease of use**: Netty is simpler to use than plain Java NIO and has an extensive set of examples covering most use cases
- **Minimal dependency**: As we will see in a minute, you can get the whole framework with just a single dependency
- **Performance**: Netty has better throughput and reduced latency than core Java APIs. It is also scalable thanks to its internal pooling of resources.
- **Security**: Complete SSL/TLS and StartTLS support.
- [Bootstrap](/docs/CS/Java/Netty/Bootstrap.md)
- [EventLoop](/docs/CS/Java/Netty/EventLoop.md)
- [ByteBuf](/docs/CS/Java/Netty/ByteBuf.md)
- [Future](/docs/CS/Java/Netty/Future.md)
- [FastThreadLocal](/docs/CS/Java/Netty/FastThreadLocal.md)

## Architecture

<div style="text-align: center;">

![Fig.1. Netty architecture](https://netty.io/images/components.png)

</div>

<p style="text-align: center;">
Fig.1. Netty architecture.
</p>

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

In Java-based networking, the fundamental construct is the class Socket .
Netty’s Channel interface provides an API that greatly simplifies the complexity of working directly with Socket.
To work with TCP/IP Channels, we will deal with SocketChannel which represents the TCP connection between client and servers:

SocketChannels are managed by EventLoop which is looking for new events, such as incoming data.. When an event occurs, it is eventually passed on to the appropriate Handler for example a ChannelHandler.

Next, to share resources like threads, Netty groups each EventLoop into an EventLoopGroup.

Finally, to handle the bootstrapping of Netty and its resources, you can use the BootStrap class.

Let’s see how to use the above Classes with a simple Server echo example.

> [Example writing a Discard Server](https://netty.io/wiki/user-guide-for-4.x.html#writing-a-discard-server)

### Bind

- [Create EventLoopGroup](/docs/CS/Java/Netty/EventLoop.md?id=create-eventloopgroup)
- BossEventLoop starts thread when register ServerSocketChannel
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
note right: one Selector per EventLoop
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
note left #AAAAAA: javaChannel().bind()
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
sa ->> wg: regster()
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

> [!TIP]
>
> Don't use EventLoopGroup to execute business because of its thread affinity.

```plantuml
skinparam backgroundColor #DDDDDD

title: Read sequence
participant WorkEventLoop as we
participant Selector as se
activate we
we ->> we: Selector.select()
note right: OP_READ event
participant Channel.Unsafe as ue
we ->> ue: read()
participant NioSocketChannel as so
participant Allocator as ac
participant ByteBuf as bb
participant ChannelPipeline as pipe
participant ChannelInboundHandler as ch
loop continueReading
    ue ->> ac: allocate()
    ac -->> ue: ByteBuf 
    ue ->> so: doReadBytes(ByteBuf) 
        note over so, bb #AAAAAA
            javaChannel.readBytes()
        end note
    break read EOF
    bb -->> bb: release()
        note over so #AAAAAA
            close = true
        end note
    end
    break IOException | OOM
        so -->> so: closeOnRead()
    end
    alt readPending
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
participant ChannelOutboundBuffer as ob
alt close == true
    so -->> so: closeOnRead()
    so -->> pipe: deRegister()
    so -->> so: doCLose()
        note right 
        close javaChannel
        cancel SelectionKey
        end note
    so -->> pipe: deRegister()
    so -->> ob: fail pending message \n ChannelOutboundBuffer = null
    so -->> pipe: fireChannelInactive()
    so -->> pipe: fireChannelUnRegister()
end

```

### Write

- check isActive & isWritable
- OP_WRITE for could write
- write/flush run in EventLoop

```plantuml
skinparam backgroundColor #DDDDDD

participant Handler as hl
participant ChannelPipeline as pipe
participant ByteBuf as bb
participant HeadContext as hc
participant Channel.Unsafe as ue
participant WorkerEventLoop as we
activate we
hl ->> pipe: write()
pipe ->> hc: write()
hc ->> ue: write()

bb -->> ue: addMessage()
participant SocketChannel as so
participant ChannelOutboundBuffer as ob
alt ChannelOutboundBuffer == null
    note over ue
        release msg prevent resource-leak
        safeSetFailure
    end note
else 
    ue ->> ob: addMessage()
    note over ob: Increment the pending bytes
end
hl ->> pipe: flush()
pipe ->> hc: flush()
hc ->> ue: flush()
ue ->> ob: addFlush()
ue ->> so: doWrite()
loop writeSpinCount > 0
    break msg done
        so ->> so: clearOpWrite()
    end
    ue ->> so: writeInternal()
    so -->> ue: doWriteBytes/doWriteFileRegion
    note left #AAAAAA: javaChannel.write()
end

alt incompleteWrite
    so ->> so: setOpWrite()
else completely
    so ->> so: clearOpWrite()
    so -->> we: Schedule flush again later
end
```

### Shutdown

```plantuml
skinparam backgroundColor #DDDDDD

title: shutdown
actor User
participant EventLoopGroup as eg
participant EventLoop as el
activate el
el -> el: runAllTasks()
User -> eg: shutdownGracefully()
eg -> el: shutdownGracefully()
loop shutdown

    break isShuttingDown
        note over el #AAAAAA: return
    end
    note over el: cas set state \n ST_STARTED -> ST_SHUTTING_DOWN
end
el -> el: confirmShutdown()
note right: runAllTasks() || runShutdownHooks()
el -> el: closeAll()
activate el
participant Channel as ch
participant Selector as se
el -> se: cancel registed channels
el -> ch: close NIO channels
el -> se: cleanup()
se -> se: Selector.close()
deactivate el
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


### Memory

- use primitive type rather than wrapper type(long + AtomicLongFieldUpdater rather than AtomicLong)
- reduce object creative
  - class field rather than instance field
- expect map size to reduce expand, AdaptiveRecvByteBufAllocator
- zero copy


AllocateByteBuf


[Memory Pool](/docs/CS/Java/Netty/memory.md)



### Zero Copy

- Direct Memory
- Composite or wrap ByteBuf
- FileChannel transfer

[Future and Promise](/docs/CS/Java/Netty/Future.md)

## Links

- [Java NIO](/docs/CS/Java/JDK/IO/NIO.md)
- [Dubbo](/docs/CS/Java/Dubbo/Dubbo.md)
- [Flink](/docs/CS/Java/Flink.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Hadoop](/docs/CS/Java/Hadoop/Hadoop.md)
- [ElasticSearch](/docs/CS)

## References

1. [Netty](https://netty.io/)
2. [Thread model](https://netty.io/wiki/thread-model.html)
