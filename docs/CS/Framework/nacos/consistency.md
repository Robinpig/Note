# Nacos Consistency Abstraction Layer and AP/CP Routing

## Introduction

Nacos 最容易被混淆的一点是：同一个组件里**服务发现默认 AP、配置管理却是 CP**。这不是两套独立产品，而是同一进程内两套一致性协议并存。理解它的钥匙，是 Nacos 的**一致性抽象层**——把「数据怎么存、怎么在节点间达成一致」从业务模块（naming / config）里抽出来，做成可插拔的协议能力。

Nacos 有**两套**一致性抽象，容易混：

- **新 Core 层**（`ConsistencyProtocol`）：2.0 引入，协议接口下沉到内核，`ProtocolManager` 选 `CPProtocol`(JRaftProtocol) / `APProtocol`(DistroProtocol)，`LogProcessor4CP` 作为 Raft 状态机。这是当前命名 Client 模型的主路径，[Nacos](/docs/CS/Framework/nacos/Nacos.md) 的 `## Consistency` 已详述。
- **老 KV 层**（`ConsistencyService`）：以 key 为粒度的 KV 存储抽象，按 key 模式路由 AP/CP。本文聚焦这一层，因为它揭示了「临时实例走 Distro、持久实例走 Raft」那三行 if 的真实落点。

## ConsistencyService: Legacy KV Layer Interface

`ConsistencyService` 定义了 KV 存储的通用能力，与具体协议无关：

```java
public interface ConsistencyService {
    void put(String key, Record value) throws NacosException;
    void remove(String key) throws NacosException;
    Datum get(String key) throws NacosException;
    void listen(String key, RecordListener listener) throws NacosException;
    void unListen(String key, RecordListener listener) throws NacosException;
    boolean isAvailable();
}
```

实现类分两类：**代理类**（按 key 决定走哪条路）与**真实实现类**（Distro / Raft）。

## Routing: DelegateConsistencyServiceImpl

`DelegateConsistencyServiceImpl`（bean 名 `consistencyDelegate`）是代理类，核心是按 key 路由：

```java
@Service("consistencyDelegate")
public class DelegateConsistencyServiceImpl implements ConsistencyService {
    private final EphemeralConsistencyService ephemeralConsistencyService; // Distro
    private final PersistentConsistencyService persistentConsistencyService; // Raft / JRaft

    @Override
    public void put(String key, Record value) throws NacosException {
        mapConsistencyService(key).put(key, value);
    }

    private ConsistencyService mapConsistencyService(String key) {
        return KeyBuilder.matchEphemeralKey(key) ? ephemeralConsistencyService : persistentConsistencyService;
    }
}
```

判断条件就是 `KeyBuilder.matchEphemeralKey(key)`——key 是否匹配临时实例模式。对命名而言，分流的源头是 `instance.isEphemeral()`：

```java
// 简化但核心逻辑一致
if (value instanceof Instance && ((Instance) value).isEphemeral()) {
    distroService.put(key, value);   // 走 AP
} else {
    raftService.put(key, value);     // 走 CP
}
```

临时实例（默认）走 AP，持久实例走 CP；没有策略模式、工厂或 SPI，就是三行 if-else，但往下各自展开几百行完全不同的逻辑。

## AP Side: EphemeralConsistencyService → Distro

`EphemeralConsistencyService` 的真实实现是 `DistroConsistencyServiceImpl`，底层即 [Distro](/docs/CS/Framework/nacos/distro.md) 协议：

- `onPut(key, value)` 把实例写进本机内存 `DataStore`（一个 `ConcurrentHashMap`）。
- 随后 `distroProtocol.sync(...)` 异步把变更同步给集群其它节点（延迟合并、责任分片、定时校验见 [Distro](/docs/CS/Framework/nacos/distro.md)）。
- `Notifier` 异步把内存注册表变更应用到 `serviceMap` 并触发订阅推送。
- 临时实例不持久化，靠心跳保活；心跳断了被摘除，重新上报再注册。

## CP Side: Evolution of PersistentConsistencyService

持久实例 / 配置必须强一致 + 持久化，走 CP。这一层经历了演进：

### Old Implementation: RaftConsistencyServiceImpl (1.x / Early 2.x)

`PersistentConsistencyServiceDelegateImpl` 早期直接委托 `RaftConsistencyServiceImpl`，底层是老 Raft（`raftCore.signalPublish`）：

- 非 Leader 则转发给 Leader。
- Leader 经 `onPublish` 把 datum 持久化到文件，异步更新内存。
- 用 `CountDownLatch(peers.majorityCount())` 等多数派确认（`/raft/datum/commit` HTTP 同步）。
- 此时持久实例是**纯 Raft**，不走 Distro 双写。

### New Implementation: BasePersistentServiceProcessor (2.x Client Model)

2.x 引入 Client 模型后，`PersistentConsistencyServiceDelegateImpl` 内部用 `switchNewPersistentService` 开关切到新实现 `BasePersistentServiceProcessor`，它**组合了两个协议**：

```dot
digraph persistent {
  rankdir=LR;
  node [shape=box, style=rounded];
  Put [label="PersistentConsistencyServiceDelegateImpl.put"];
  E [label="EmbeddedDistroProtocol\n(AP: 同步进命名内存, 供读)"];
  R [label="JRaftConsistencyServiceImpl\n(CP: 过 Raft 写 DB)"];
  Put -> E;
  Put -> R;
}
```

- **`EmbeddedDistroProtocol`**：把持久实例也同步进 Distro 内存（与临时实例同套命名内存），保证读路径统一从本地内存返回。
- **`JRaftConsistencyServiceImpl`**：把写提交给 JRaft，过 Raft 复制 + 应用状态机（[LogProcessor4CP](/docs/CS/Framework/nacos/jraft.md)）+ 写 MySQL。

这就是「双写」：持久实例既要进内存供读（AP 式读），又要过 Raft 保证一致与持久（CP 式写）。delegate 用开关平滑切换新旧实现，运维无感。

## Why AP + CP Can Coexist

CAP 理论针对的是「**数据的一致性**」，不是「整个组件」。Nacos 把数据按性质拆开：

- 命名的临时实例：允许短暂分歧、分区可独立响应 → AP（Distro）。
- 命名的持久实例 + 配置：要求读己之写、全局有序、不丢 → CP（Raft/JRaft）。

两套一致性策略的**数据存储互不影响**——Distro 的内存注册表与 Raft/JRaft 的日志 + DB 各管各的，所以一个组件内 AP 与 CP 并存不矛盾。这正是 Eureka（纯 AP）和 ZooKeeper（纯 CP）做不到的。

## Config Side vs Naming Side

- **配置（config）**：全程走 `PersistentConsistencyService`（JRaft）+ MySQL。配置没有「临时/持久」之分，必须强一致，因此 config 模块不接 Distro。
- **命名（naming）**：临时实例走 Distro，持久实例走 JRaft。3.x 的 Client 模型把 naming 的写路径接到新 Core 层（`DistroProtocol` / `JRaftProtocol` + `LogProcessor4CP`），但「临时 vs 持久」的分流语义不变——持久实例仍映射到 JRaft。

## Comparison with etcd-raft / Zab

| 维度 | Nacos | etcd | ZooKeeper |
| :-- | :-- | :-- | :-- |
| 一致性范围 | AP（命名临时）+ CP（命名持久/配置）并存 | 全程 CP | 全程 CP |
| 协议 | Distro + JRaft | etcd-raft | Zab |
| 分流点 | `instance.isEphemeral()` / key 模式 | 无（全 Raft） | 无（全 Zab） |
| 存储 | Distro 内存 + Raft 日志/DB | bbolt | DataTree + txnlog/snapshot |

etcd / ZK 不需要分流，因为它们是「通用协调底座」，所有数据都走同一强一致协议；Nacos 是「寄存器 + 配置中心」合体，把可用性（AP）留给注册发现、把可靠性（CP）留给配置。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Registry（Distro 事件驱动层）](/docs/CS/Framework/nacos/registry.md)
- [Distro（AP 协议深潜）](/docs/CS/Framework/nacos/distro.md)
- [JRaft（CP 共识）](/docs/CS/Framework/nacos/jraft.md)
- [Storage](/docs/CS/Framework/nacos/storage.md)
- [etcd Raft](/docs/CS/Framework/etcd/raft.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://www.cnblogs.com/coloz/p/14314512.html>
- <https://blog.csdn.net/huohuo5211314/article/details/162103453>
- <https://www.cnblogs.com/mjunz/p/18863383>
- <https://nacos.io/docs/v3.0/manual/admin/cluster/>
