## Introduction

[Netty](https://netty.io) is *an asynchronous event-driven network application framework* for rapid development of maintainable high performance protocol servers & clients

Netty is a [NIO](/docs/CS/Java/JDK/IO/NIO.md) client server framework which enables quick and easy development of network applications such as protocol servers and clients.
It greatly simplifies and streamlines network programming such as TCP and UDP socket server.

- **Ease of use**: Netty is simpler to use than plain Java NIO and has an extensive set of examples covering most use cases
- **Minimal dependency**: As we will see in a minute, you can get the whole framework with just a single dependency
- **Performance**: Netty has better throughput and reduced latency than core Java APIs. It is also scalable thanks to its internal pooling of resources.
- **Security**: Complete SSL/TLS and StartTLS support.





- [EventLoop](/docs/CS/Framework/Netty/EventLoop.md)
- [ByteBuf](/docs/CS/Framework/Netty/ByteBuf.md)
- [Future](/docs/CS/Framework/Netty/Future.md)
- [FastThreadLocal](/docs/CS/Framework/Netty/FastThreadLocal.md)

## Architecture

<div style="text-align: center;">

![Fig.1. Netty architecture](https://netty.io/images/components.png)

</div>

<p style="text-align: center;">
Fig.1. Netty architecture.
</p>


Netty 结构一共分为三个模块：

- Core
  Core 核心层是 Netty 最精华的内容，它提供了底层网络通信的通用抽象和实现，包括可扩展的事件模型、通用的通信 API、支持零拷贝的 ByteBuf 等。
- Protocol Support 协议支持层
  协议支持层基本上覆盖了主流协议的编解码实现，如 HTTP、SSL、Protobuf、压缩、大文件传输、WebSocket、文本、二进制等主流协议，此外 Netty 还支持自定义应用层协议。Netty 丰富的协议支持降低了用户的开发成本，基于 Netty 我们可以快速开发 HTTP、WebSocket 等服务。
- Transport Service 传输服务层
  传输服务层提供了网络传输能力的定义和实现方法。它支持 Socket、HTTP 隧道、虚拟机管道等传输方式。Netty 对 TCP、UDP 等数据传输做了抽象和封装，用户可以更聚焦在业务逻辑实现上，而不必关系底层数据传输的细节



Netty 的逻辑处理架构为典型网络分层架构设计，共分为网络通信层、事件调度层、服务编排层，每一层各司其职

网络通信层的**核心组件**包含**BootStrap、ServerBootStrap、Channel**三个组件



[Bootstrap](/docs/CS/Framework/Netty/Bootstrap.md) 是“引导”的意思，它主要负责整个 Netty 程序的启动、初始化、服务器连接等过程，它相当于一条主线，串联了 Netty 的其他核心组件



Netty 自己实现的 Channel 是以 JDK NIO Channel 为基础的，相比较于 JDK NIO，Netty 的 Channel 提供了更高层次的抽象，同时屏蔽了底层 Socket 的复杂性，赋予了 Channel 更加强大的功能



事件调度层的职责是通过 Reactor 线程模型对各类事件进行聚合处理，通过 Selector 主循环线程集成多种事件（ I/O 事件、信号事件、定时事件等），实际的业务处理逻辑是交由服务编排层中相关的 Handler 完成。

事件调度层的**核心组件**包括 **EventLoopGroup、EventLoop**





服务编排层的职责是负责组装各类服务，它是 Netty 的核心处理链，用以实现网络事件的动态编排和有序传播。

服务编排层的核心组件包括 ChannelPipeline、ChannelHandler、ChannelHandlerContext

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

- [Create EventLoopGroup](/docs/CS/Framework/Netty/EventLoop.md?id=create-eventloopgroup)
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

1. [Create EventLoopGroup](/docs/CS/Framework/Netty/EventLoop.md?id=create-nioeventloopgroup)
2. [Create ServerBootstrap](/docs/CS/Framework/Netty/Bootstrap.md?id=create-serverbootstrap)
3. Set [Channel](/docs/CS/Framework/Netty/Channel.md)
4. Set [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)
5. Option
6. ChildOption
7. [ServerBootstrap#bind()](/docs/CS/Framework/Netty/Bootstrap.md?id=bind)
8. [ChannelFuture](/docs/CS/Framework/Netty/Future.md)

### close

## Under Hood


### Memory

- use primitive type rather than wrapper type(long + AtomicLongFieldUpdater rather than AtomicLong)
- reduce object creative
  - class field rather than instance field
- expect map size to reduce expand, AdaptiveRecvByteBufAllocator
- zero copy


AllocateByteBuf


[Memory Pool](/docs/CS/Framework/Netty/memory.md)



### Zero Copy

- Direct Memory
- Composite or wrap ByteBuf
- FileChannel transfer

[Future and Promise](/docs/CS/Framework/Netty/Future.md)

## Links

- [Java NIO](/docs/CS/Java/JDK/IO/NIO.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [RocketMQ](/docs/CS/MQ/RocketMQ/RocketMQ.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Hadoop](/docs/CS/Java/Hadoop/Hadoop.md)
- [ElasticSearch](/docs/CS/Framework/ES/ES.md)

## References

1. [Netty](https://netty.io/)
2. [Thread model](https://netty.io/wiki/thread-model.html)
