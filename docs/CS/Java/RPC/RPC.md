## Introduction

Within the operating system research community, remote procedure call has achieved sacred cow status. It is almost universally assumed to be the appropriate paradigm for building a distributed operating system.

RPC is a communication mechanism between two parties, a client and a server.

In particular, the programmer does not have to be aware of the network at all or the details of how message passing works. The distribution of the program over two machines is said to be **transparent**.

## Problems

### Conceptual

In this section we will deal with a variety of problems that are inherent in the RPC model of a client sending a message to a server then blocking until a reply is received.

#### C/S Model


#### Unexpected Messages

#### Single Threaded Servers

Another server design decision that RPC virtually forces on the operating system designer is the choice of a multi-threaded over a single threaded file server.

#### The Two Army Problem


#### Multicast



### Technical

#### Parameter Marshalling

#### Parameter Passing

#### Global Variables

#### Timing Problems

### Abnormal Situations

#### Exception Handling

#### Repeated Execution Semantics

For this topic it is important to distinguish two kinds of remote procedures, those that are idempotent and those that are not.


#### Loss of State

Even if a server crashes between RPCs and reboots itself before the next RPC occurs, serious problems can occur.

#### Orphans

So far we have only dealt with server crashes. Client crashes also pose problems.
If a client crashes while the server is still busy, the server’s computation has become an *orphan*.

### Heterogeneous Machines

Another class of problems occurs if the client and server run on different kinds of computers. The ISO model handles most of these problems with the general mechanism of *option negotiation*.
When a virtual circuit is opened, the client can describe the relevant parameters of its machine, and ask the server to describe its parameters. 
Then the two parties can negotiate and finally choose a set of parameters that both sides understand and can live with. 
With transparent RPC, the client can hardly be expected to negotiate with its procedures concerning the parameters of the machine they are running on.

Parameter Representation

Byte Ordering

Structure Alignment

### Performance

#### Parallelism

With RPC, when the server is active, the client is always idle, waiting for the response. 
Thus there is never any parallelism possible. The client and the server are effectively coroutines. 
With other communication models it may be possible to have the client continue computing while the server is working, in order to gain performance.
Furthermore, with a single threaded server and multiple clients, the situation is even worse. 
While the server is waiting for, say, a disk operation, all the clients have to wait.

#### Streaming

In data base work it is common for a client to request a server to perform an operation to look up tuples in a data base that meet some predicate. 
With RPC, the server must wait until all the tuples have been found before making the reply. 
If the operation of finding all the tuples is a time consuming one, the client may be idle for a long time waiting for the last tuple to be found.

With virtual circuits, the situation is quite different. Here the server can send the first tuple back to the client as soon as it has been located. 
While the server continues to search for more tuples, the client can be processing the first one. As the server finds more tuples, it just sends them back. There is no need to wait until all have been found.


With nontransparent communication it can never happen that an important little procedure runs remote.

三大基本问题
- 表示数据-序列化、反序列化
- 传递数据—网络协议
- 表示方法-方法签名 UUID

发展方向
- 面向对象
- 性能
- 简化
- 插件化

功能强大的框架往往要在传输中加入额外的负载和控制措施，导致传输性能降低，而如果既想要高性能，又想要强功能，这就必然要依赖大量的技巧去实现，进而也就导致了框架会变得过于复杂，这就决定了不可能有一个“完美”的框架同时满足简单、普适和高性能这三个要求。


Procedure Call Protocol Documents，Version 2


## Links

## References

1. [Remote Procedure Call](https://christophermeiklejohn.com/pl/2016/04/12/rpc.html)
2. [A Critique of the Remote Procedure Call Paradigm](https://www.win.tue.nl/~johanl/educ/2II45/2010/Lit/Tanenbaum%20RPC%2088.pdf)