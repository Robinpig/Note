## Introduction

**RPC** 是通信双方（client 与 server）之间的一种通信机制。在分布式计算中，remote procedure call（RPC，远程过程调用）指计算机程序令某个过程（子程序）在另一地址空间（通常是共享网络上的另一台计算机）中执行，其编写方式就像一次普通的（本地）过程调用，程序员无需显式编写远程交互的细节。

## 概念模型

发起一次远程调用时，会涉及五段程序：user、user-stub、RPC 通信包（即 RPCRuntime）、server-stub 与 server。

当主程序调用过程时，实际发生的是：在客户端机器上，对名为 *client stub* 的特殊过程发起一次调用。

- *client stub* 将参数编组（marshall，即收集）进一条消息，然后将其发往服务端机器，由 *server stub* 接收。
- *server stub* 从消息中解包参数，再用标准调用序列调用服务端过程。

如此一来，主程序与被调用过程都只看到普通的本地过程调用，使用常规调用约定。只有 stub（通常由编译器自动生成）知道这次调用是远程的。具体而言，程序员完全无需关心网络，也无需关心消息传递的实现细节。程序分布在两台机器上这件事被称为**透明（transparent）**。此外，在两次 RPC 之间，client 与 server 之间不会建立任何连接。

我们接着要处理 RPC 模型固有的一系列问题：客户端发消息给服务端，然后阻塞直到收到回复。

### C/S 模型

RPC 并非适用于所有计算。一个不合适的简单例子是 UNIX 管道：

```shell
sort <infile | uniq | wc -l > outfile
```

这里很难分清谁是 client、谁是 server。一种可能的配置是让这三个程序各自在某些时刻同时充当 client 与 server，必要时内部再拆分为两个进程。

若让 sort 包含两个进程、都是 client —— 一个向文件服务器取数据、一个向 uniq 推送数据 —— 就形成了一种不对称局面：管道的第一个组件包含两个 client，其余部分各有一个 client 与一个 server。各种临时方案都有可能，例如让管道成为主动拉取/推送数据的进程，但无论如何看，都很清楚 RPC 模型在此并不适用。

### 线程模型

RPC 几乎强制操作系统设计者在多线程与单线程文件服务器之间做选择。

### 两军问题

考虑这样一种情形：client 请求 server 提供某些不可替换的数据，例如由 server 控制的实时物理实验采样。server 发出回复后不能简单地丢弃数据，因为回复可能丢失，届时 client stub 会超时并重发请求。问题在于："server 应保留这些不可替换的数据多久？"

这一问题被称为两军问题（two-army problem），在虚电路系统尝试优雅关闭连接时也会出现。

### 异构机器

若 client 与 server 运行在不同种类的计算机上，会出现另一类问题。ISO 模型通过 option negotiation（选项协商）这一通用机制处理了大部分此类问题。当打开一条虚电路时，client 可以描述本机的相关参数，并请求 server 描述其参数；随后双方协商，最终选出一组双方都能理解并接受的参数。而在透明 RPC 中，很难指望 client 去与其过程协商它们所运行机器的参数。

- 参数表示（Parameter Representation）
- 字节序（Byte Ordering）
- 结构体对齐（Structure Alignment）

### 关键考量

- 安全性（Security）：RPC 涉及网络通信，安全是重要关切。必须实现认证、加密、授权等措施，防止未授权访问并保护敏感数据。
- 可扩展性（Scalability）：随着 client 与 server 数量增加，RPC 系统性能不能退化。负载均衡与高效的资源利用对可扩展性很重要。
- 容错（Fault tolerance）：RPC 系统应对网络故障、server 崩溃及其它意外事件具备韧性。冗余、故障转移与优雅降级等措施有助于保障容错。
- 标准化（Standardization）：现有多种 RPC 框架与协议，选用被广泛接受的标准化方案，对跨平台、跨编程语言的互操作与兼容很重要。
- 性能调优（Performance tuning）：为最佳性能微调 RPC 系统很重要。这可能涉及优化网络协议、最小化网络传输的数据量、降低 RPC 调用相关的延迟与开销。

## 技术细节

### 参数编组（Parameter Marshalling）

为编组参数，client stub 必须知道参数的个数与各自类型。

对强类型语言，这通常不成问题；但若允许 union 类型或变体记录（variant record），stub 可能无法推断传的是哪个 union 成员或变体记录。

对 C 这类非类型安全的语言，问题更严重。例如 printf 以多种不同参数被调用；若 printf 或类似的过程要被远程调用，client stub 很难确定参数个数与类型。

### 参数传递

client 调用其 stub 时，使用常规调用序列。stub 随后收集参数并放入发往 server 的消息中。若所有参数都是值参数（value parameters），则无问题，直接拷贝进消息即可。

但若存在引用参数或指针，事情就更复杂。虽然把指针拷进消息显然可行，但当 server 试图使用它们时会出错，因为指针所指向的对象并不在 server 端。

这些正是一作者提出的疑问，很容易看出它们破坏了 RPC 试图提供的透明性。

### 全局变量

这与上述指针问题类似，且同样棘手。

有人会说："别用全局变量。" 这是一种应对方式，但与指针的情形一样，它破坏了 RPC 的透明性承诺。

### 时序

### 绑定

最灵活的方案是使用动态绑定（dynamic binding），在首次发起 RPC 时于运行时查找 server。client stub 首次被调用时，会联系 name server 以确定 server 所在的传输地址。

绑定包含两部分：

- 命名（Naming）：
- 定位（Locating）：

- 提供服务的 server 导出（export）一个接口供其使用。导出接口即将其注册到系统，使 client 可以使用。
- client 必须在通信开始前导入（import）一个（已导出的）接口。

## 异常情况

### 异常处理

本地执行过程时，要么完成、要么完全失败。远程过程引入了关于网络通信的新错误，以及一方失败时的错误。

问题在于 RPC 以本地与远程调用之间的透明承诺被"贩卖"给了程序员，而显然程序员必须处理这些新错误。

### 重复执行语义

对此主题，区分两类远程过程很重要：幂等（idempotent）的与非幂等的。

当某条消息丢失时，框架无法决定该如何处理。处理此类问题的设施总是受欢迎的，但无论如何，应由开发系统的程序员来决定。

主要分类如下：

- 重试请求消息（Retry request message）：当 server 故障或接收方未收到消息时，是否重发请求消息。
- 重复过滤（Duplicate filtering）：去除重复的 server 请求。
- 结果重传（Retransmission of results）：在不于 server 端重新执行操作的前提下，重发丢失的消息。

### 状态丢失

即便 server 在两次 RPC 之间崩溃，并在下一次 RPC 发生前重启，仍可能出现严重问题。

参与系统的程序员应考虑可能的故障，并设计系统以应对问题发生时的情形。这可能导致他们避免使用 RPC，这没问题 —— 构建分布式系统本就没有唯一方法，应始终考虑其它选择。

### 孤儿调用（Orphans）

目前为止我们只讨论了 server 崩溃，client 崩溃同样带来问题。若 client 在 server 仍忙碌时崩溃，server 的计算就成了孤儿（orphan）。

无论如何，这是另一个无法对程序员隐藏的问题，因为决定如何应对正属于他们的职责。

## 编组（Marshalling）

[Marshalling](/docs/CS/Distributed/RPC/Marshalling.md)

## 异步

大多数网络框架都是异步的

Netty的`Channel.writeAndFlush` 会返回一个 `channelFuture`返回true只代表写入网络缓冲区成功 不代表发送成功

客户端如何知道失败？

一个常见的设计是：客户端发起一个 RPC 请求，会设置一个超时时间 `client_timeout`，发起调用的同时，客户端会开启一个延迟 `client_timeout` 的定时器

- 接收到正常响应时，移除该定时器。
- 定时器倒计时完毕，还没有被移除，则认为请求超时，构造一个失败的响应传递给客户端。

## 泛化调用

基于动态代理技术，RPC框架客户端做到了调用RPC方法与调用本地方法相同的体验。一般情况下服务端定义服务接口，并将接口打包到二方jar包发布。服务端在服务进程中实现该接口，而调用方在进程中根据该接口创建动态代理进行调用，与调用本地方法体验一致

泛化调用是指在调用方没有服务方提供的 API（SDK）的情况下，对服务方进行调用，并且可以正常拿到调用结果
泛化调用主要用于实现一个通用的远程服务 Mock 框架，可通过实现 GenericService 接口处理所有服务请求。比如如下场景：
1. 网关服务：如果要搭建一个网关服务，那么服务网关要作为所有 RPC 服务的调用端。但是网关本身不应该依赖于服务提供方的接口 API（这样会导致每有一个新的服务发布，就需要修改网关的代码以及重新部署），所以需要泛化调用的支持。
2. 测试平台：如果要搭建一个可以测试 RPC 调用的平台，用户输入分组名、接口、方法名等信息，就可以测试对应的 RPC 服务。那么由于同样的原因（即会导致每有一个新的服务发布，就需要修改网关的代码以及重新部署），所以平台本身不应该依赖于服务提供方的接口 API。所以需要泛化调用的支持。

## 性能

### 并行性

使用 RPC 时，server 忙碌期间 client 始终空闲、等待响应，因此不可能有并行。client 与 server 实际上是协程（coroutines）。当 server 等待（如磁盘操作）时，所有 client 都只能等待。

异步方法在多线程 server 中也是更好的选择。

### 流式传输

在数据库场景中，client 常请求 server 执行某操作以查找满足谓词的元组。使用 RPC 时，server 必须等找到所有元组后才能回复。若查找全部元组耗时较长，client 可能长时间空闲等待最后一条元组。

如今 [gRPC](/docs/CS/Framework/gRPC/gRPC.md) 与 Finagle 支持构建流式 client 与 server。

[Thrift](/docs/CS/Distributed/RPC/Thrift.md)

[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)

[Kitex](/docs/CS/Framework/kitex.md)：字节跳动开源的 Go RPC 框架，默认 Thrift + [Netpoll](/docs/CS/Framework/Netpoll.md)

Motan：微博内部使用的 RPC 框架，于 2016 年对外开源，仅支持 Java 语言

Tars：腾讯内部使用的 RPC 框架，于 2017 年对外开源，仅支持 C++ 语言

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [Marshalling](/docs/CS/Distributed/RPC/Marshalling.md)
- [Protocol Buffers](/docs/CS/Distributed/RPC/ProtoBuf.md)
- [Thrift](/docs/CS/Distributed/RPC/Thrift.md)
- [Fury](/docs/CS/Distributed/RPC/Fury.md)
- [RESTful](/docs/CS/Distributed/RPC/RESTful.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)

## References

1. [RFC 647 - Procedure Call Protocol Documents，Version 2](https://datatracker.ietf.org/doc/rfc647/)
2. [Implementing Remote Procedure Calls](https://web.eecs.umich.edu/~mosharaf/Readings/RPC.pdf)
4. [RFC 1057 - RPC: Remote Procedure Call Protocol Specification Version 2](https://datatracker.ietf.org/doc/rfc1057/)
2. [A Critique of the Remote Procedure Call Paradigm](https://www.win.tue.nl/~johanl/educ/2II45/2010/Lit/Tanenbaum%20RPC%2088.pdf)
5. [A Note on Distributed Computing](https://scholar.harvard.edu/files/waldo/files/waldo-94.pdf)
1. [Remote Procedure Call](https://christophermeiklejohn.com/pl/2016/04/12/rpc.html)
