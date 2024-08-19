## Introduction

Dledger 作为一个轻量级的 Java Library，它的作用就是将 Raft 有关于算法方面的内容全部抽象掉，开发人员只需要关心业务即可
部署 RocketMQ 时可以根据需要选择使用DLeger来替换原生的副本存储机制。

> Etcd 虽然也实现了 Raft 协议，但它是自己封装的一个服务，对外提供的接口全是跟它自己的业务相关的

Dledger 只做一件事情，就是 CommitLog。
Dledger 的定位就是把上一层的 StateMachine 给去除，只留下 CommitLog。这样的话，系统就只需要实现一件事：就是把操作日志变得高可用和高可靠。

这样做对消息系统还有非常特别的含义。消息系统里面如果还采用 StateMachine + CommitLog 的方式，会出现 double IO 的问题，因为消息本省可以理解为是一个操作记录。
所以 Dledger 会提供一些对原生 CommitLog 访问的 API。通过这些 API 可以直接去访问 CommitLog。这样的话，只需要写入一次就可以拿到写入的内容。
Dledger 对外提供的是简单的 API，如下图 6 所示。可以把它理解为一个可以无限写入操作记录的文件，可以不停 append，每一个 append 的记录会加上一个编号。
所以直接去访问 Dledger 的话就是两个 API：一个是 append，另一个是 get，即根据编号拿到相应的 entry（一条记录）。


## Architecture



主要有两件事：选举和复制，对应到上面的架构图中，也就是两个核心类：DLedgerLeaderElector 和 DLedgerStore，选举和文件存储。
选出 leader 后，再由 leader 去接收数据的写入，同时同步到其他的 follower，这样就完成了整个 Raft 的写入过程。



build

```shell
mvn clean install -DskipTests
```

选举核心类

- DLedgerConfig
- MemberState 节点状态机
- DLedgerClientProtocol 客户端通信协议





```java
package io.openmessaging.storage.dledger.protocol;

import java.util.concurrent.CompletableFuture;

/**
 * Both the RaftLogServer(inbound) and RaftRpcService (outbound) should implement this protocol
 */
public interface DLedgerClientProtocol {

    CompletableFuture<GetEntriesResponse> get(GetEntriesRequest request) throws Exception;

    CompletableFuture<AppendEntryResponse> append(AppendEntryRequest request) throws Exception;

    CompletableFuture<MetadataResponse> metadata(MetadataRequest request) throws Exception;

    CompletableFuture<LeadershipTransferResponse> leadershipTransfer(LeadershipTransferRequest request) throws Exception;
}
```

- DLedgerProtocol 服务端通信协议

```Java
/**
 * Both the RaftLogServer(inbound) and RaftRpcService (outbound) should implement this protocol
 */
public interface DLedgerProtocol extends DLedgerClientProtocol {

    CompletableFuture<VoteResponse> vote(VoteRequest request) throws Exception;

    CompletableFuture<HeartBeatResponse> heartBeat(HeartBeatRequest request) throws Exception;

    CompletableFuture<PullEntriesResponse> pull(PullEntriesRequest request) throws Exception;

    CompletableFuture<PushEntryResponse> push(PushEntryRequest request) throws Exception;

}
```

## RocketMQ

Dledger 虽然只需要写 CommitLog，但是基于 CommitLog 是可以做很多事情的。
RocketMQ 原来的架构里是有 CommitLog 的，现在用 Dledger 去替代原来的 CommitLog。
由于 Dledger 提供了一些可以直接读取 CommitLog 的 API，于是就可以很方便地根据 CommitLog 去构建 ConsumerQueue 或者其他的模块。
这就是 Dledger 在 RocketMQ 上最直接的应用

加了 Dledger 之后，其实就是在原来的消息上面加了一个头。这个头就是 Dledger 的头，本质上是一些简单的属性，例如 size 等

在使用的时候会有格式上的差异，所以社区在升级的时候做了一个平滑升级的考虑，如图 11 所示。要解决的问题是：如何将原来已有的 CommitLog 和现在基于 Dledger 的 CommitLog 混合？现在已经支持自动混合，但是唯一的一个要求是旧版的 CommitLog 需要自己去保持它的一致性。因为 Dledger 的复制是从新写入的记录开始。假设旧的 CommitLog 已经是一致的情况下，然后直接启动 Dledger ，是可以在旧的 CommitLog 基础上继续 append，同时保证新写消息的一致性，高可靠和高可用。这是 Dledger 直接应用到 RocketMQ 上的时候一个格式上的区别。

对于用户来说，这样做最直接的好处是：若使用 Master/Slave 架构模式，一旦一个 broker 挂了，则需要手动控制。但是使用 Dledger 之后不需要这么做。因为 Dledger 可以通过自己选举，然后把选举结果直接传给 RocketMQ 的 broker，这样通过 nameserver 拿到路由的时候就可以自动找到 leader 节点去访问消息，达到自动切换的目的。



## Links

- [Broker](/docs/CS/MQ/RocketMQ/Broker.md)


## References

1. [Dledger](https://rocketmq.apache.org/zh/docs/bestPractice/02dledger/)
2. [openmessaging/dledger](https://github.com/openmessaging/dledger)