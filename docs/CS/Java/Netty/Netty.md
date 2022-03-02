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




```sequence
title: bind sequence
participant User
participant ServerBootstrap as sb

participant ChannelFactory as cf
participant ChannelPipeline as cp
participant NioEventLoopGroup as we
participant NioEventLoop as bl
User ->> we: create NioEventLoopGroup
we ->> bl: create multiple NioEventLoops \n and bind Selector for each of them
User ->> sb: ServerBootstrap.bind()
sb ->> cf: initAndRegister NioServerSocketChannel
participant ChannelPipeline as cp
sb ->> we: request NioEventLoop
sb ->> bl: register NioServerSocketChannel \n into Selector of NioEventLoop
bl -->> bl: register OP_ACCEPT
```
Connect
```sequence
title: registe sequence
participant User
participant ServerBootstrap as sb
participant ChannelFactory as cf
participant BossNioEventLoopGroup as we
participant WorkerNioEventLoopGroup as wg
participant NioEventLoop as bl
User ->> we: create NioEventLoopGroup
we ->> bl: create multiple NioEventLoops \n and bind Selector for each of them
User ->> sb: ServerBootstrap.bind()
sb ->> cf: initAndRegister NioServerSocketChannel
sb ->> we: request NioEventLoop
sb ->> bl: register NioServerSocketChannel \n into Selector of NioEventLoop
bl -->> bl: register OP_ACCEPT
```


```sequence
participant User
User -->> User: send messages
participant WorkEventLoopGroup as we
participant Selector as se
we ->> se: selector.select()
se ->> we: OP_READ
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
ue ->> so: NioUnsafe.read()
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()
participant ChannelPipeline as pipe

```

Start sequence

```sequence
participant User
User -->> User: send messages
participant WorkEventLoopGroup as we
participant Selector as se
we ->> we: create threads and open Selectors
we ->> we: initAndRegister
we ->> we: doBind0
se ->> we: OP_READ
participant NioByteUnsafe as ue
we ->> ue: NioUnsafe.read()
participant NioSocketChannel as so
ue ->> so: NioUnsafe.read()
so ->> ue: -1(EOF)
ue -->> ue: closeOnRead()
participant ChannelPipeline as pipe

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


[Future and Promise](/docs/CS/Java/Netty/Future.md)


## Links
- [Java NIO](/docs/CS/Java/JDK/IO/NIO.md)


## References

1. [Netty](https://netty.io/)
2. [Thread model](https://netty.io/wiki/thread-model.html)