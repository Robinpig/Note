## Introduction

[etcd](/docs/CS/Framework/etcd/etcd.md) 的**高层特性**：基于 etcd 实现服务发现的原理与 Apache APISIX 实战，以及 v3 迷你事务（Txn）的 API、ACID 实现与隔离级别。服务发现的 gRPC resolver 实现细节见 [naming](/docs/CS/Framework/etcd/naming.md)；分布式锁 / 选举 / STM 见 [concurrency](/docs/CS/Framework/etcd/concurrency.md)。

> [!NOTE]
> 版本基线同 [etcd](/docs/CS/Framework/etcd/etcd.md)：**3.7.2**（raft 已外置 `go.etcd.io/raft/v3` v3.7.0）。
## Features

### Discovery

如何基于etcd实现服务发现呢?

下面我给出了一个通用的服务发现原理架构图，通过此图，为你介绍下服务发现的基本原理。详细如下：

- 整体上分为四层，client层、proxy层(可选)、业务server、etcd存储层组成。引入proxy层的原因是使client更轻、逻辑更简单，无需直接访问存储层，同时可通过proxy层支持各种协议。
- client层通过负载均衡访问proxy组件。proxy组件启动的时候，通过etcd的Range RPC方法从etcd读取初始化服务配置数据，随后通过Watch接口持续监听后端业务server扩缩容变化，实时修改路由。
- proxy组件收到client的请求后，它根据从etcd读取到的对应服务的路由配置、负载均衡算法（比如Round-robin）转发到对应的业务server。
- 业务server启动的时候，通过etcd的写接口Txn/Put等，注册自身地址信息、协议到高可用的etcd集群上。业务server缩容、故障时，对应的key应能自动从etcd集群删除，因此相关key需要关联lease信息，设置一个合理的TTL，并定时发送keepalive请求给Leader续租，以防止租约及key被淘汰

Apache APISIX其实就是上面服务发现原理架构图中的proxy组件 它由控制面和数据面组成。
控制面顾名思义，就是你通过Admin API下发服务、路由、安全配置的操作。控制面默认的服务发现存储是etcd，当然也支持consul、nacos等。
数据面是在实现基于服务路由信息数据转发的基础上，提供了限速、鉴权、安全、日志等一系列功能，也就是解决了我们上面提的分布式及微服务架构中的典型痛点

APISIX数据存储如下信息：

Apache APSIX 2.x系列版本使用的是etcd3。
服务、路由、ssl、插件等配置存储格式前缀是/apisix + “/” + 功能特性类型（routes/services/ssl等），我们通过Admin API添加的路由、服务等配置就保存在相应的前缀下。
路由和服务配置的value是个Json对象，其中服务对象包含了id、负载均衡算法、后端节点、协议等信息。

Apache APISIX在启动的时候，首先会通过Range操作获取网关的配置、路由等信息，随后就通过Watch机制，获取增量变化事件。

使用Watch机制最容易犯错的地方是什么呢？

答案是不处理Watch返回的相关错误信息，比如已压缩ErrCompacted错误。Apache APISIX项目在从etcd v2中切换到etcd v3早期的时候，同样也犯了这个错误

etcd 作为服务发现后端时，上层系统在其下约定不同 key 前缀。以 Apache APISIX 为例：

| 前缀 | 内容 |
|---|---|
| `/apisix/routes` | 路由配置（匹配规则、上游、插件） |
| `/apisix/services` | 服务配置（负载均衡算法、后端节点、协议） |
| `/apisix/ssl` | SSL 证书与密钥 |
| `/apisix/upstreams` | 上游节点定义 |
| `/apisix/consumers` | 消费者与认证信息 |

业务 server 注册时把地址 / 协议写入对应前缀，并关联 Lease + keepalive 续租；proxy 侧通过 Watch 监听变化、实时更新路由。服务注册的 gRPC resolver 实现（如何把 etcd 的 watch 事件转换为 gRPC 的 `resolver.UpdateState`）见 [naming](/docs/CS/Framework/etcd/naming.md)；基于 etcd 的分布式锁、选举与 STM 见 [concurrency](/docs/CS/Framework/etcd/concurrency.md)。

### Transaction

etcd v3为了解决多key的原子操作问题，提供了全新迷你事务API，同时基于MVCC版本号，它可以实现各种隔离级别的事务。它的基本结构如下：

```
client.Txn(ctx).If(cmp1, cmp2, ...).Then(op1, op2, ...,).Else(op1, op2, …)
```

它的基本原理是，在If语句中，你可以添加一系列的条件表达式，若条件表达式全部通过检查，则执行Then语句的get/put/delete等操作，否则执行Else的get/put/delete等操作

If语句支持哪些检查项呢？

首先是**key的最近一次修改版本号mod_revision**，简称mod。你可以通过它检查key最近一次被修改时的版本号是否符合你的预期。比如当你查询到Alice账号资金为100元时，它的mod_revision是v1，当你发起转账操作时，你得确保Alice账号上的100元未被挪用，这就可以通过mod(“Alice”) = “v1” 条件表达式来保障转账安全性。

其次是**key的创建版本号create_revision**，简称create。你可以通过它检查key是否已存在。比如在分布式锁场景里，只有分布式锁key(lock)不存在的时候，你才能发起put操作创建锁，这时你可以通过create(“lock”) = “0”来判断，因为一个key不存在的话它的create_revision版本号就是0。

接着是**key的修改次数version**。你可以通过它检查key的修改次数是否符合预期。比如你期望key在修改次数小于3时，才能发起某些操作时，可以通过version(“key”) < “3”来判断。

最后是**key的value值**。你可以通过检查key的value值是否符合预期，然后发起某些操作。比如期望Alice的账号资金为200, value(“Alice”) = “200”。

If语句通过以上MVCC版本号、value值、各种比较运算符(等于、大于、小于、不等于)，实现了灵活的比较的功能，满足你各类业务场景诉求

剖析在etcd中事务的ACID特性的实现。

- 原子性是指一个事务要么全部成功要么全部失败，etcd基于WAL日志、consistent index、boltdb的事务能力提供支持。
- 一致性是指事务转账前后的，数据库和应用程序期望的恒等状态应该保持不变，这通过数据库和业务应用程序相互协作完成。
- 持久性是指事务提交后，数据不丢失，
- 隔离性是指事务提交过程中的可见性，etcd不存在脏读，基于MVCC机制、boltdb事务你可以实现可重复读、串行化快照隔离级别的事务，保障并发事务场景中你的数据安全性

etcd社区基于以上介绍的事务特性，提供了一个简单的事务框架[STM](https://github.com/etcd-io/etcd/blob/v3.4.9/clientv3/concurrency/stm.go)，构建了各个事务隔离级别类，帮助你进一步简化应用编程复杂度

etcd 基于 MVCC + boltdb 事务可实现的隔离级别：

| 隔离级别 | 实现机制 | 可见性保证 |
|---|---|---|
| 读已提交（Read Committed） | boltdb 单事务 | 仅见已提交数据 |
| 可重复读（Repeatable Read） | MVCC 多版本 + 固定 revision 快照 | 事务内多次读看到同一快照 |
| 串行化快照隔离（SSI） | MVCC revision + 冲突检测 | 并发事务串行化，无脏读 / 幻读 |

社区 `STM`（`clientv3/concurrency/stm.go`）已封装上述隔离级别，简化应用编程。

## Links

- [MVCC（多版本与事务隔离）](/docs/CS/Framework/etcd/MVCC.md)
- [compare（etcd / ZooKeeper / Nacos / Consul 对比）](/docs/CS/Framework/etcd/compare.md)
