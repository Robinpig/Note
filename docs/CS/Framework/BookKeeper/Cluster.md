## Introduction

前面几篇都是「一个客户端和一个 ledger 之间发生了什么」。到了集群视角，多出三件事：**bookie 怎么被发现、副本放在哪、ledger 副本不够了谁去补**。

BookKeeper 集群有个容易被忽略的特点：**bookie 之间完全不通信**。没有心跳、没有 gossip、没有选主。协调发生在客户端与元数据存储之间 —— 集群的「一致性」几乎全部落在 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)（或其它 `RegistrationManager` / `LedgerManager` 实现）的 znode 上。

> 版本基线：**4.18.1**（`release-4.18.1`）。元数据路径常量出自 `util/BookKeeperConstants.java`。

## Metadata Layout

BookKeeper 在元数据存储上的根路径默认是 **`/ledgers`**（`BookKeeperConstants.java` `DEFAULT_ZK_LEDGERS_ROOT_PATH`）。其下的结构：

| 路径（相对 `/ledgers`） | 常量 | 内容 |
| ---------------------- | ---- | ---- |
| `LAYOUT` | `LAYOUT_ZNODE` | 集群布局格式（含 `LedgerManagerFactory` 类名） |
| `INSTANCEID` | `INSTANCEID` | 集群实例 ID，参与 cookie 校验 |
| `available/` | `AVAILABLE_NODE` | **在线 bookie 的注册节点**，ephemeral 节点：bookie 启动即注册、宕机即消失 |
| `cookies/` | `COOKIE_NODE` | 每个 bookie 一个 cookie 节点，记录它的 journal/ledger 目录与实例 ID |
| `underreplication/` | `UNDER_REPLICATION_NODE` | 待补副本的 ledger 列表（Auditor 写、ReplicationWorker 消费） |
| `underreplication/locks/` | `UNDER_REPLICATION_LOCK` | 补副本任务的锁，防止多个 worker 重复处理 |
| `lostBookieRecoveryDelay` | `LOSTBOOKIERECOVERYDELAY_NODE` | 判定「bookie 永久丢失」前的等待秒数，可运行时改 |
| `checkallledgersctime` | `CHECK_ALL_LEDGERS_CTIME` | 全量审计上次执行时间 |
| `placementpolicycheckctime` | `PLACEMENT_POLICY_CHECK_CTIME` | 放置策略合规检查的执行时间 |
| `replicascheckctime` | `REPLICAS_CHECK_CTIME` | 副本检查的执行时间 |
| `disable` | `DISABLE_NODE` | 手动禁用某 bookie 的节点 |
| `{hash}/L{ledgerId}` | `LEDGER_NODE_PREFIX = "L"` | **ledger 元数据本身**，按 id 分桶（如 `/ledgers/00/0000/L0001`） |

### LedgerManager 层级路径（源码级）

第 26 行的 `{hash}/L{ledgerId}` 不是随意哈希，而是 `HierarchicalLedgerManager` 按 id 区间选两种布局之一（`StringUtils.java:103-108`）：

| 布局 | 位数 / 补零 | 拆分 | 路径模板 | 源码 |
| ---- | ---------- | ---- | -------- | ---- |
| legacy（短） | 10 位 `%010d` | **2-4-4**（3 层） | `/ledgers/XX/XXXX/LXXXXXXXX` | `StringUtils.java:70-80` |
| long | 19 位 `%019d` | **3-4-4-4-4**（5 层） | `/ledgers/XXX/XXXX/XXXX/XXXX/LXXXXXXXXXXXXX` | `StringUtils.java:89-101` |

- `HierarchicalLedgerManager`（`HierarchicalLedgerManager.java:42`）内部同时持有 legacyLM（31-bit）与 longLM（63-bit），`getLedgerPath`（`:74-76`）按 `ledgerId < Integer.MAX_VALUE` 分流到两种实现。
- `LongHierarchicalLedgerManager`（`LongHierarchicalLedgerManager.java:58`）处理超过 31-bit 的 id，5 层布局把每个 znode 子节点数限制在 ≤10000，避免 ZK `getChildren` 列表过长与 GC 压力（`:53-55`）。
- 创建 / 读取 / 删除由 `AbstractZkLedgerManager` 编排：`createLedgerMetadata`（`:272-357`）用 `asyncCreateFullPathOptimistic`（`:354-355`）一次性建好整条父层级 + 叶子 znode；`readLedgerMetadata`（`:480-530`）即 `open` 的元数据读取；`removeLedgerMetadata`（`:360-418`）层级实现走 `asyncDeleteFullPathOptimistic` 递归清理空父节点。

> [!NOTE]
> 这套布局是 **BookKeeper 自己的**。如果通过 [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md) 使用，Pulsar 的 topic / namespace / bundle 元数据在**另一棵**树上（`/admin/policies`、`/managed-ledgers`、`/namespace/...`），见 [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)。两者可以共享同一个 ZooKeeper，也可能分离（Pulsar 的 `bookkeeperMetadataServiceUri`）。

## Cookie: The Bookie's Identity

cookie 记录一个 bookie 的**磁盘身份**：journal 目录、ledger 目录、所属集群实例 ID。bookie 启动时读出自己的 cookie 并与配置比对：

```java
// Cookie.java:162-166
} else if ((instanceId == null && c.instanceId != null)
        || (instanceId != null && !instanceId.equals(c.instanceId))) {
    // instanceId should be same in both cookies
    errMsg = "instanceId " + instanceId + " is not matching with " + c.instanceId;
}
// Cookie.java:171
public void verify(Cookie c) throws BookieException.InvalidCookieException { ... }
```

> [!WARNING]
> **cookie 不匹配是 BookKeeper 最常见的启动失败**，典型成因：
> - 换了磁盘或改了 `journalDirectory` / `ledgerDirectories` 但没清 cookie —— bookie 认为「这不是我原来那块盘」并拒绝启动，以免把数据写乱；
> - 两个集群共用一个 ZooKeeper 的 `/ledgers`（`INSTANCEID` 不同）；
> - 目录列表顺序变化、主机名变更。
>
> 修复方式是**确认数据归属后再决定**是清空 cookie 节点（丢弃旧数据）还是恢复原目录配置 —— 不要无脑 `delete cookie`，那等于让 bookie 忘了自己盘上有什么。

## Ensemble Placement

选哪些 bookie 存副本，由 `EnsemblePlacementPolicy` 决定，**默认实现是 `RackawareEnsemblePlacementPolicy`**：

```java
// ClientConfiguration.java:1233-1237
public Class<? extends EnsemblePlacementPolicy> getEnsemblePlacementPolicy() {
    return ReflectionUtils.getClass(this, ENSEMBLE_PLACEMENT_POLICY,
            RackawareEnsemblePlacementPolicy.class,    // ★默认
            EnsemblePlacementPolicy.class);
}
```

关键行为与开关：

| 项 | 说明 | 默认值 / 位置 |
| -- | ---- | ------------- |
| 机架感知 | 尽量把 write quorum 打散到不同 rack | `RackawareEnsemblePlacementPolicy.java` |
| `minNumRacksPerWriteQuorum` | 要求一个 write quorum **至少跨几个 rack** | 构造参数，见 `:57-63`；不满足时降级或抛 `BKNotEnoughBookiesException` |
| `enforceMinNumFaultDomainsForWrite` | 已满足 Qa 但跨故障域不够时**延迟回调** | 见 [Write](/docs/CS/Framework/BookKeeper/Write.md)；`PendingAddOp.java:396` |
| `diskWeightBasedPlacementEnabled` | 按磁盘使用加权而非按 bookie 数 | **false**（`ClientConfiguration.java:1559`） |
| `reorderReadSequenceEnabled` / `reorderThresholdPendingRequests` | 读序重排 | 阈值默认 **0（关闭）**（`:1259`） |
| `delayEnsembleChange` | 攒够失败再换 ensemble，而不是立即换 | **false**（`:1875`） |

> [!TIP]
> `minNumRacksPerWriteQuorum` 与 `enforceMinNumFaultDomainsForWrite` 是**两件事**：前者在**选副本**时约束，后者在**判定写成功**时约束。只配前者而不配后者时，仍可能出现「选了跨机架的副本，但确认的副本都来自同一机架」的情况。

## Auto-Recovery

副本缺失（bookie 永久下线、写入时未达 Qw）由 auto-recovery 补齐。它由**两个独立角色**组成：

```dot
digraph AutoRecovery {
    rankdir=LR;
    node [shape=box, style=rounded];
    auditor [label="Auditor\n（一个集群只有一个）\n发现哪些 ledger 副本不足"];
    ur [label="underreplication/ znode"];
    worker [label="ReplicationWorker\n（每个 bookie 一个）\n实际搬运 entry"];
    bk [label="Bookie 集群"];

    auditor -> ur [label="标记待补副本"];
    ur -> worker [label="取任务 + 加锁"];
    worker -> bk [label="openLedgerNoRecovery\n→ replicateLedgerFragment"];
}
```

- **Auditor**（`replication/Auditor.java`）：周期性扫描，把副本不足的 ledger 标记为 underreplicated。
- **ReplicationWorker**（`replication/ReplicationWorker.java`）：从 `underreplication/` 取任务，用 **不触发恢复**的方式打开 ledger 并搬运片段：

  ```java
  // ReplicationWorker.java:450
  try (LedgerHandle lh = admin.openLedgerNoRecovery(ledgerIdToReplicate)) {
  // :474
  admin.replicateLedgerFragment(lh, ledgerFragment, onReadEntryFailureCallback);
  ```

  用 `openLedgerNoRecovery` 而不是 `openLedger` 的原因见 [Ledger](/docs/CS/Framework/BookKeeper/Ledger.md)：恢复动作有截断副作用，补副本不应该截断。

> [!IMPORTANT]
> **`autoRecoveryDaemonEnabled` 默认是 false**（`ServerConfiguration.java:2895`）。也就是说，**BookKeeper 默认不会因为丢了一个 bookie 就自动补副本** —— 必须显式开启 `autoRecoveryDaemonEnabled=true` 才会启动 Auditor。这是部署时最容易漏掉的一项。

### Auto-Recovery 源码级

上文是角色概览，落地到守护进程 `AutoRecoveryMain` 的源码：

- **启动与角色组装**：`AutoRecoveryMain`（`AutoRecoveryMain.java:88-115`）创建系统级 BK 客户端、`AuditorElector`（集群唯一 Auditor 选举，`:103-108`）、`ReplicationWorker`（`:109-113`），`start()`（`:120-128`）依次启动三者 + `deathWatcher`（任一退出即 shutdown，`:234-246`）。
- **Auditor 如何发现故障**：不轮询，而是 `watchWritableBookiesChanged` / `watchReadOnlyBookiesChanged`（`Auditor.java:612-615`）监听 ZK `/bookies` 变化触发 `submitAuditTask`（`:241-322`）；差异计算 `bookiesToBeAudited = knownBookies − availableBookies`（`:275`），`lostBookieRecoveryDelay`（`:281-311`）控制立即审计或延迟（多 bookie 同时丢失则立即，单 bookie 丢失可调度延迟并在恢复时 cancel）。
- **标记 under-replicated**：`AuditorBookieCheckTask.auditBookies`（`:101-154`）建立 `bookie → 其持有 ledger` 映射（`BookieLedgerIndexer`），对每个疑似 ledger 调 `markLedgerUnderreplicatedAsync`（`AuditorTask.java:80-109`），落 ZK `underreplication/ledger_<id>`（`ZkLedgerUnderreplicationManager.java:165`）。
- **ReplicationWorker 补齐**：`run()`（`:244-275`）循环 `rereplicate()`（`:289-307`）；`rereplicate(long)`（`:444-548`）用 `openLedgerNoRecovery`（`:450`）打开，取 under-replicated 片段（`getUnderreplicatedFragments`，`:451`，含 data-loss 与 placement 两类），对 closed 片段调 `replicateLedgerFragment`（`:474` → `BookKeeperAdmin.java:1182-1227` 从源副本读、写新 bookie）。
- **锁联动**：RW 取任务时在 `urLedgerPath` 下建 **EPHEMERAL** 锁 znode（`ZkLedgerUnderreplicationManager.java:506-574`），已存在（他人持有）则 `NodeExistsException` 跳过（`:544-545`）；GC 的 `ScanAndCompareGarbageCollector` 删 over-replicated ledger 前也复用同一把锁（`:281`），避免与 RW 抢删。

> [!WARNING]
> `ReplicationException` 在 4.18.x **只有** `UnavailableException` / `NonRecoverableReplicationException` / `CompatibilityException` / `BKAuditException`（`ReplicationException.java:57-113`）四类，**没有 `LockedOutException` 或 `CompactionException`** —— 「被锁挡住」由 ZK ephemeral 锁的 `NodeExistsException` 表达，不要照抄旧文档的异常名。

相关配置：

| 配置 | 默认 | 行号 | 说明 |
| ---- | ---- | ---- | ---- |
| `autoRecoveryDaemonEnabled` | **false** | 2895 | 是否在本 bookie 上运行 auto-recovery |
| `lostBookieRecoveryDelay` | **0** | 2903 | bookie 失联后等待多少秒才判定为永久丢失并开始补副本。0 = 立即 |
| `auditorPeriodicCheckInterval` | **604800 秒（7 天）** | 2700 | 全量审计周期，0 表示关闭 |
| `auditorPeriodicBookieCheckInterval` | **86400 秒（1 天）** | 2723 | 按 bookie 维度的检查周期 |
| `auditorPeriodicPlacementPolicyCheckInterval` | **0（关闭）** | 2746 | 放置策略合规检查（副本是否满足跨 rack 要求） |
| `openLedgerRereplicationGracePeriod` | —（`ReplicationWorker.java:195`） | | 打开中的 ledger 重复制的宽限期 |

> [!WARNING]
> `lostBookieRecoveryDelay = 0` 意味着**bookie 一掉线就立刻开始大规模补副本**。计划内重启 bookie 前，通常先把这个值设成大于重启耗时的秒数（它可以在运行时通过 znode 修改，Auditor 会检测到变化并重新调度，见 `Auditor.java:331-365`），避免「重启一次触发全集群数据搬运」。

## Scaling

| 动作 | 发生了什么 | 数据搬迁 |
| ---- | ---------- | -------- |
| **加 bookie** | 注册到 `/ledgers/available`，此后**新建的 ledger** 才可能选中它 | **无** —— 旧 ledger 的副本集合不变 |
| **减 bookie（优雅下线）** | 从 `available` 摘除，Auditor 判定其上的数据副本不足，进 auto-recovery | 由 ReplicationWorker 逐步补齐到其它 bookie |
| **减 bookie（永久丢失）** | ephemeral 节点消失，等 `lostBookieRecoveryDelay` 后开始补副本 | 同上 |

> [!TIP]
> 这正是 BookKeeper 与「分区 + 副本」型系统扩缩容体验不同的根源：**BookKeeper 扩容是零成本的**（新数据用新 bookie），代价是**旧数据的副本数会被动不足**，需要 auto-recovery 慢慢追。因此扩缩容的运维重点是盯 `underreplication/` 的积压量，而不是看有没有数据迁移任务。

## Corrections To Common Claims

| 说法 | 4.18.1 实况 |
| ---- | ----------- |
| 「默认会自动补副本」 | ❌ `autoRecoveryDaemonEnabled` 默认 **false**（`ServerConfiguration.java:2895`） |
| 「bookie 之间通过心跳维持集群」 | ❌ bookie 之间不通信；在线状态靠 ZooKeeper 的 ephemeral 节点 |
| 「元数据默认存在 `/bookkeeper`」 | ⚠️ 根路径常量是 `/ledgers`（`DEFAULT_ZK_LEDGERS_ROOT_PATH`） |
| 「auto-recovery 用 `openLedger` 打开 ledger」 | ❌ 用 `openLedgerNoRecovery`（`ReplicationWorker.java:450`），避免截断 |
| 「补副本按整个 ledger 进行」 | ❌ 按 **fragment/segment 片段**搬运（`LedgerFragment`、`replicateLedgerFragment`） |

## Links

- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)
- [Ledger](/docs/CS/Framework/BookKeeper/Ledger.md)
- [Storage](/docs/CS/Framework/BookKeeper/Storage.md)
- [Ops](/docs/CS/Framework/BookKeeper/Ops.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)

## References

1. [Auditor.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/replication/Auditor.java)
2. [ReplicationWorker.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/replication/ReplicationWorker.java)
3. [RackawareEnsemblePlacementPolicy.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/client/RackawareEnsemblePlacementPolicy.java)
4. [BookKeeper — Autorecovery](https://bookkeeper.apache.org/docs/latest/admin/autorecovery)
