## Introduction

etcd、[ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)、[Nacos](/docs/CS/Framework/nacos/Nacos.md)、Consul 这类组件都对外提供"分布式一致性的键值存储 + 协调能力"，选型时容易混淆。它们的实质差异不在 API 形态，而在**一致性模型、数据模型、运维形态**三个层面的取舍。

这一篇以 etcd 为主轴做横向对照。etcd 自己的 [etcd.md](/docs/CS/Framework/etcd/etcd.md) 里已有一节简短的 Comparison，但那是 etcd 视角的简表；这里补上共识算法、树模型、依赖栈、典型选型倾向等更完整的维度。

> [!NOTE]
> 选型的第一性问题不是"哪个更好"，而是**"这个数据能不能丢"**。etcd 与 Consul 的数据是**状态**（丢了就是事故），Nacos 的配置是**意图**（丢了可以回滚），ZooKeeper 的 znodes 多数是**协调用的临时状态**。能接受偶发不一致的场景，用更轻的方案往往更划算。

## 版本基线

本文是一篇**选型对比**（不是 etcd 版本对比），etcd 侧的签名与行为描述以 **3.7.2** 为基线；其余组件的版本取各自官方发布页在 2026-10 的状态。

| 组件 | 当前版本 | 生态位置 |
| :--- | :--- | :--- |
| etcd | **3.7.2**（维护线 3.6.15 / 3.5.34） | Kubernetes 后端唯一存储实现 |
| ZooKeeper | **3.9.6**（2026-09-15）；**3.8 仍在维护**，最新 3.8.7 | 传统大数据组件（HBase、Kafka）内置依赖 |
| Nacos | **3.2.4**（2.x 维护线最新 2.5.4） | 国内云原生配置中心 + 注册中心 |
| Consul | **2.0.4**（维护线 1.22.x / 1.21.x） | 服务发现 + 服务网格 + 多数据中心（HashiCorp，BSL 许可） |

> [!WARNING]
> **ZooKeeper 的 EOL 结论极易记错**：官方宣布 EOL 的是 **3.7**（2024-02-02 生效，末版 3.7.2），**3.8 并没有 EOL**——3.8.7 与 3.9.6 在 2026-09-15 同期发布。ZooKeeper 官方同时只维护两条分支（stable + current），但 3.8 仍在发布 bugfix。看到"3.8 已 EOL"的说法，先去 [官方 news 页](https://zookeeper.apache.org/news) 核对发布日期。

## 一致性模型

| 维度 | etcd | ZooKeeper | Nacos | Consul |
| :--- | :--- | :--- | :--- | :--- |
| 共识算法 | **Raft**（外置 `go.etcd.io/raft/v3`） | **Zab** | Raft（自研简化实现 JRaft） | Raft |
| 强一致操作 | 所有写 + 线性读（ReadIndex） | 写 + `sync()` 路径 | 写（naming 走 AP） | 所有写 |
| 读一致性 | 默认线性一致，可选 serializable | 本地读 + watch 缓存 | 配置读多为内存缓存 | 一致性读 / stale 读可选 |
| 历史版本 | **MVCC，多版本可回溯** | 无（只有当前状态） | 无 | 无 |
| 写入确认 | 多数派（quorum） | 多数派 | 多数派 | 多数派 |

**"读"是最大的差异点。** ZooKeeper 和 Consul 的读默认走本地状态（ZooKeeper 靠 watch 机制让客户端缓存，客户端缓存是它读性能高的原因），因此需要显式 `sync()` 才能保证读到最新。etcd 默认提供线性一致读（走 [ReadIndex](/docs/CS/Framework/etcd/raft.md)），代价是一次网络往返；需要吞吐时可显式请求 serializable read。

etcd 的 MVCC 是它独有的能力：同一个 key 的历史版本可按 revision 读取，这直接支撑了 [watch](/docs/CS/Framework/etcd/watch.md) 的可靠回溯——Kubernetes 靠 `resourceVersion` 语义实现的增量同步就建立在这之上。

> [!TIP]
> ZooKeeper 用 **znode 树模型**（`/a/b/c` 层级命名 + 节点类型 `persistent`/`ephemeral`/`container`），etcd 用**扁平 key + 前缀范围查询**模拟层级。前者的父子关系是数据结构的一部分，后者的 `/` 只是 key 的一部分——`get --prefix /a/b` 和逐层 `getChildren` 语义类似，但 etcd 没有"父节点必须存在"这类约束，写入更自由。

## 数据模型与能力

| 能力 | etcd | ZooKeeper | Nacos | Consul |
| :--- | :--- | :--- | :--- | :--- |
| 键值存储 | ✅ | ✅（数据量小，不适合大 value） | ✅ | ✅ |
| 层级命名空间 | 前缀模拟 | ✅ 原生树 | ✅ | 前缀模拟 |
| Watch 机制 | gRPC 双向流，**支持历史回溯** | Watch（一次性触发） | 长轮询 | blocking query |
| 分布式锁 | ✅（`Concurrency` / [lease](/docs/CS/Framework/etcd/lease.md) + CAS） | ✅ 临时节点实现 | ✅ | ✅ `lock` API |
| Leader 选举 | ✅ | ✅ 临时顺序节点 | ✅ | ✅ |
| 服务发现 | 需自行封装 | ✅ 原生（注册/订阅） | ✅ **原生主打** | ✅ **原生主打** |
| 配置管理 | ✅ | ⚠️ 无版本化、非专用 | ✅ **原生主打** | ✅ |
| 分布式事务 | ✅ **Txn**（CAS 原子操作） | ❌ | ⚠️ | ❌ |
| 多租户/命名空间 | ✅ 多实例隔离 | ⚠️ 靠路径区分 | ✅ 显式 namespace | ✅ |
| 权限模型 | RBAC + [TLS 双向认证](/docs/CS/Framework/etcd/security.md) | digest / IP ACL | ✅ | ACL + token |

**服务发现与配置管理**是选型的分水岭：

- 要**通用协调底座**（自己做上层）→ etcd
- **开箱即用的注册中心**（Java 生态尤其如此，如 Dubbo 用 ZooKeeper）→ ZooKeeper / Nacos
- **服务发现 + 服务治理一体化** → Consul / Nacos

**分布式事务**只有 etcd 原生支持。它的 Txn 是一组带条件的原子操作（`If...Then...Else`），条件为 false 时只执行 else 分支。这个能力组合起来能实现"仅当某 key 版本未变才更新"这类逻辑。

## 架构与依赖

| 维度 | etcd | ZooKeeper | Nacos |
| :--- | :--- | :--- | :--- |
| 语言 | Go | Java | Java |
| 依赖 | 无外部依赖（单二进制） | 无（单 jar 集） | MySQL（配置持久化） |
| 部署形态 | 单进程，`etcd`/`etcdctl`/`etcdutl` | 单进程，QuorumPeer | Server 集群 + Raft 内核 + MySQL |
| 存储引擎 | bbolt（单文件） | 自研快照 + 事务日志 | 嵌入式存储 + MySQL 双写 |
| 客户端协议 | gRPC（[HTTP/JSON 网关](/docs/CS/Framework/etcd/client.md) 兼容） | 私有 ZTP 协议 + Curator | HTTP/JSON + gRPC |

etcd 的**零外部依赖**是运维上最大的优势：一个二进制 + 一个 [data-dir](/docs/CS/Framework/etcd/cluster.md)，没有额外组件会挂。Nacos 需要 MySQL 存配置，ZooKeeper 虽无外部依赖但 JVM 内存开销大（这正是 etcd 被 CoreOS 造出来替代它的原因之一，详见 [etcd.md](/docs/CS/Framework/etcd/etcd.md) 的 Introduction）。

**私有协议**的代价要留意：ZooKeeper 的 Jute 序列化 + 私有 RPC 使得无法用 `curl` 等通用工具调试，Nacos 与 etcd 早期版本也有类似问题。etcd v3 改用 gRPC + protobuf 后，这个问题才根本解决。

## 选型倾向

| 场景 | 推荐 | 理由 |
| :--- | :--- | :--- |
| Kubernetes 后端 | **etcd** | 事实标准，无选择余地 |
| 云原生通用协调 | **etcd** | 多租户、RBAC、事务、gRPC 一应俱全 |
| Java 微服务注册中心 | Nacos | 服务发现 + 配置开箱即用，Spring 生态成熟 |
| 大数据组件依赖 | **ZooKeeper** | HBase、Kafka、Hadoop 历史上只认它 |
| 服务网格 | **Consul** | 与 Consul / Envoy 深度集成 |
| 需要跨语言、HTTP 调试 | **etcd** | gRPC 生态 + 统一 API |

## ZooKeeper 特有能力

ZooKeeper 有几项能力在其他组件里没有对应物，值得单独说明：

- **ephemeral 节点（临时节点）**：会话结束自动删除，这是它实现分布式锁、Leader 选举的基础——锁 = 创建临时顺序节点 + watch 前驱。etcd 里对应的机制是 [lease](/docs/CS/Framework/etcd/lease.md) 过期自动删除 key。
- **ZooKeeper Watch 是一次性的**：触发后需要重新注册，这是它"惊群"问题的来源。etcd 的 watch 是可续的流，配合 MVCC 还能从指定 revision 续接。
- **Zab 与 Raft 的关键差异**：Zab 是**只写 leader**的原子广播协议，followers 只能转发不能直接服务读；Raft 让 leader 也走日志（no-op + ReadIndex）来实现线性一致读。

## Consul 特有能力

Consul 在服务发现之上补了 etcd 和 ZooKeeper 都不内置的东西：**服务网格**（Service Mesh）、多数据中心（WAN gossip）、ACL token 体系、以及原生 KV 的**阻塞查询**（long polling，语义上比 watch 更灵活但不支持历史回溯）。

etcd 社区因此常出现"用 etcd + Envoy 自己搭"的组合，但 Consul 的服务治理全家桶对不想自己拼装的团队仍有价值。

## Nacos 特有能力

Nacos 在 etcd / ZooKeeper 之外走出一条"配置 + 注册中心一体化"的路线，有几点其他组件没有或不主打：

- **服务发现默认 AP（Distro）**：Nacos 的 naming 模块默认走 Distro 最终一致协议，网络分区时各节点可独立响应、允许短暂分歧，把"注册中心不因分区全挂"看得比强一致更重；etcd 与 ZooKeeper 都是 CP。需要一致时，Nacos 的配置与 CP 模式才切到 **JRaft**（自研简化 Raft）。
- **配置中心是原生主打**：Nacos 的配置（dataId + group + namespace，版本化、支持灰度 / 回滚）是独立产品级能力；etcd 的配置只是 KV 的一层用法，没有版本化治理。
- **强依赖 MySQL**：配置持久化落 MySQL，多一个会挂的外部组件；etcd 单二进制 + data-dir 零外部依赖（对照见上方「架构与依赖」表）。
- **Spring / Dubbo 生态开箱**：Nacos 与 Spring Cloud Alibaba、Dubbo 深度集成，注册 / 配置一站接入；etcd 需要业务自行封装上层。

etcd 社区因此常出现"用 etcd + Envoy 自己搭"的组合，但 Nacos 的配置治理全家桶对 Java 微服务团队仍更省心。

## 陷阱清单

> [!WARNING]
> 跨组件对比最容易踩的不是技术差异，而是**版本事实抄错**——几个高频坑：

1. **别信"某个 ZooKeeper 版本已 EOL"的二手说法** —— 官方只维护 stable + current 两条分支，但哪条被砍会变。3.7 已 EOL（2024-02-02），3.8、3.9 都在维护。以 [官方 news](https://zookeeper.apache.org/news) 的发布日期为准。
2. **etcd 的 raft 不在主仓库里** —— 3.7 起算法实现已外置为独立 module `go.etcd.io/raft/v3`，主仓库没有 `server/etcdserver/api/raft/`。想读 `RawNode`/`Ready` 实现要去外置仓库，主仓库的调用侧是 `server/etcdserver/raft.go`。
3. **Nacos 2.x 与 3.x 不能混谈** —— 当前稳定线已是 3.2.x，2.x 的维护线停在 2.5.4。谈 Nacos 时务必钉小版本：3.x 要求 Java 17（2.x 是 Java 8），且 Spring Cloud Alibaba 对 3.x 的兼容进度本身就是选型变量。
4. **etcd "无外部依赖" 指的是运行时，不含 etcd 自己的 Raft** —— 别把它理解为"没有一致性协议实现"。另外新版本的 grpc-proxy 与 gRPC 后端是独立 module（`cache/`），且明确不支持 gRPC proxy。
5. **ZooKeeper 客户端向下兼容、服务端不向下兼容** —— 3.5.x 及以后的客户端连 3.9.x 服务端没问题，但服务端混版本集群要按官方 Upgrade FAQ 走，不能随便混搭分支。
6. **etcd 与 Consul 的读默认值不同** —— 见「一致性模型」表：etcd 默认线性读，ZooKeeper / Consul 默认可能读到本地旧状态。把 Consul/ZooKeeper 的默认值当成 etcd 的默认值写代码，是最常见的跨组件移植 bug。

## Links

- [etcd（架构与启动流程）](/docs/CS/Framework/etcd/etcd.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Consul](/docs/CS/Framework/consul/Consul.md)
- [K8s 中的 etcd 存储](/docs/CS/Container/k8s/etcd.md)

## References

1. [etcd Documentation - Features](https://etcd.io/docs/v3.7/op-guide/features/)
2. [etcd Documentation - Comparison to other systems](https://etcd.io/docs/v3.7/op-guide/comparison/)
3. [Apache ZooKeeper Documentation - Overview](https://zookeeper.apache.org/doc/r3.9.6/zookeeperOver.html)
4. [Apache ZooKeeper News（版本与 EOL 时点的一手来源）](https://zookeeper.apache.org/news)
5. [Nacos Documentation - Architecture](https://nacos.io/en-us/docs/next/arch/)
6. [Nacos Server 发布历史](https://nacos.io/download/release-history)
7. [Consul Documentation - What is Consul?](https://developer.hashicorp.com/consul/docs/intro)
