## Introduction

运维 BookKeeper 本质上是在盯三件事：**写入的持久性（journal）、磁盘的回收（GC）、副本的齐全（auto-recovery）**。前两篇讲的是机制，本文给的是「该配什么、该看什么、出问题先查哪」。

> 版本基线：**4.18.1**（`release-4.18.1`）。配置默认与行号出自 `ServerConfiguration.java` / `ClientConfiguration.java`；shell 子命令出自官方 CLI 参考。
> 通过 [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md) 使用时，很多值被 Pulsar 的 `ServiceConfiguration` 覆盖（尤其是 E/Qw/Qa 与 managed-ledger 相关项），见 [ManagedLedger 存储层](/docs/CS/MQ/Pulsar/ManagedLedger.md)。

## Deployment Baseline

四类「不做就会出事」的部署约定：

1. **journal 与 ledger 目录分盘**：`journalDirectories` 与 `ledgerDirectories` 是两个独立配置键（`ServerConfiguration.java:174-175`）。journal 是顺序写 + fsync，entry log 是随机读，混在一块盘上会互相破坏顺序性。
2. **改掉默认的 journal 目录**：`journalDirectory` 默认 **`/tmp/bk-txn`**（`:1379`）—— 这是给本地测试用的，生产不改等于把 WAL 放在临时目录。
3. **显式开启 auto-recovery**：`autoRecoveryDaemonEnabled` 默认 **false**（`:2895`，见 [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)）。
4. **确认副本数**：BookKeeper 客户端 API 默认 3/2/2（`BookKeeper.java:918`），但 Pulsar 侧默认是 **2/2/2**（容忍 0 个 bookie 故障）。生产环境按「容忍几个节点挂」重新算 E/Qw/Qa，而不是沿用默认。

## Key Configuration Reference

### Write Path（客户端侧，`ClientConfiguration.java`）

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `throttleValue`（客户端限流 permits/s，0 关闭） | 5000 | 237 |
| `readTimeout` | 5 秒 | 621 |
| `addEntryTimeout` | = `readTimeout` | 646 |
| `readEntryTimeout` | = `readTimeout` | 694 |
| `addEntryQuorumTimeout` | **-1（关闭）** | 670 |
| `explicitLacInterval` | 0（关闭） | 770 |
| `numWorkerThreads` | CPU 核数 | 879 |
| `numIOThreads` | 2 × CPU 核数 | 905 |
| `recoveryReadBatchSize` | 1 | 1138 |
| `enableParallelRecoveryRead` | false | 1116 |
| `delayEnsembleChange` | false | 1875 |
| `diskWeightBasedPlacementEnabled` | false | 1559 |
| `reorderThresholdPendingRequests` | 0（读序重排关闭） | 1259 |

### Read Path

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `speculativeReadTimeout` | 2000 ms | 945 |
| `firstSpeculativeReadTimeout` | = `speculativeReadTimeout` | 971 |
| `maxSpeculativeReadTimeout` | = `speculativeReadTimeout` | 1036 |
| `speculativeReadTimeoutBackoffMultiplier` | 2.0 | 991 |

### Journal（bookie 侧，`ServerConfiguration.java`）

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `journalDirectory` | `/tmp/bk-txn` | 1379 |
| `journalMaxSizeMB` | 2048 | 844 |
| `journalMaxBackups` | 5 | 894 |
| `journalPreAllocSizeMB` | 16 | 866 |
| `journalWriteBufferSizeKB` | 64 | 875 |
| `journalAlignmentSize` | 512 | 917 |
| `journalQueueSize` | 10000 | 971 |
| `journalSyncData` | true | 2378 |
| `journalAdaptiveGroupWrites` | true | 2429 |
| `journalMaxGroupWaitMSec` | 2 | 2448 |
| `journalBufferedWritesThreshold` | 512 KB | 2469 |
| `numJournalCallbackThreads` | 1 | 2278 |

### EntryLog / Index / Cache

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `ledgerStorageClass` | **`SortedLedgerStorage`** | 68 |
| `sortedLedgerStorageEnabled` | true | 2298 |
| `skipListSizeLimit` | 64 MB | 2308 |
| `skipListArenaChunkSize` | 4 MB | 2333 |
| `flushInterval` | 10000 ms | 651 |
| `flushIntervalInBytes` | 0（关闭） | 678 |
| `logSizeLimit`（entry log 大小上限） | **1 GiB**（`MAX_LOG_SIZE_LIMIT`） | 85-91 |
| `entryLogPerLedgerEnabled` | false | 3981 |
| `pageSize` | 8192 | 750 |
| `pageLimit` | -1（按 openFileLimit 推导） | 729 |
| `openFileLimit` | 20000 | 708 |
| `indexDirectories` | 未配置时 = `ledgerDirectories` | 1488 |

### Garbage Collection

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `minorCompactionThreshold` | 0.2 | 1785 |
| `minorCompactionInterval` | 3600 秒 | 1865 |
| `majorCompactionThreshold` | 0.8 | 1813 |
| `majorCompactionInterval` | 86400 秒 | 1890 |
| `gcWaitTime` | 600000 ms | 424 |
| `compactionRate` | 1000 条/秒 | 3016 |
| `compactionRateByBytes` | 1000000 | 3058 |
| `isForceGCAllowWhenNoSpace` | — | 113 / 213 |
| `gcEntryLogMetadataCacheEnabled` / `gcEntryLogMetadataCachePath` | — | 120-121 |

### Disk And Cluster

| 配置 | 默认 | 行号 |
| ---- | ---- | ---- |
| `diskUsageWarnThreshold` | 0.90 | 2587 |
| `diskUsageThreshold` | 0.95 | 2631 |
| `diskCheckInterval` | 10000 ms | 2679 |
| `readOnlyModeEnabled` | true | 2544 |
| `readOnlyModeOnAnyDiskFullEnabled` | true | 2566 |
| `minUsableSizeForEntryLogCreation` | 1.2 × `logSizeLimit` | 3620 |
| `autoRecoveryDaemonEnabled` | **false** | 2895 |
| `lostBookieRecoveryDelay` | 0 | 2903 |
| `auditorPeriodicCheckInterval` | 604800 秒 | 2700 |
| `auditorPeriodicBookieCheckInterval` | 86400 秒 | 2723 |
| `auditorPeriodicPlacementPolicyCheckInterval` | 0（关闭） | 2746 |

## What To Monitor

| 指标 / 观察点 | 说明 | 异常时的含义 |
| ------------- | ---- | ------------ |
| journal sync 耗时（`Journal.java:548-550` 采样） | 单次 fsync 耗时 | 持续升高 → journal 盘瓶颈或与 entry log 同盘 |
| force write 队列长度（`Journal.java:509`） | 待 fsync 的请求数 | 逼近 `journalQueueSize`（10000）→ 写被阻塞 |
| group commit 批量大小（`Journal.java:524-525`） | 每次 fsync 合并的 entry 数 | 长期为 1 → 吞吐没起来（并发不足或 `flushWhenQueueEmpty` 行为） |
| ensemble change 计数 | ledger 换副本的次数 | 高 → bookie 不稳定或元数据服务压力大 |
| `addOpUrCounter`（`PendingAddOp.java:304`） | 回调成功后仍有副本失败的计数 | 升高 → 集群处于「副本不齐」状态，等 auto-recovery 补 |
| `writeDelayedDueToNotEnoughFaultDomains`（`PendingAddOp.java:406`） | 因跨故障域不足而延迟回调 | 只在开了 `enforceMinNumFaultDomainsForWrite` 时有意义；升高说明 rack 分布不均 |
| `underreplication/` 节点数 | 待补副本的 ledger 数 | 持续增长 → auto-recovery 没开 / 补不过来 |
| GC 时长与压缩次数 | entry log 压缩 | 长时间不降 → 空间回收不了 |
| 磁盘使用率 | 相对 `diskUsageThreshold` | 接近 0.95 → 即将只读 |

> [!TIP]
> 排障顺序建议：**先看 `underreplication/` 与 ensemble change，再看 journal fsync，最后看磁盘**。BookKeeper 的写延迟问题绝大多数是副本不齐或 journal 盘慢，而不是 entry log 读慢。

## Common Failures

| 现象 | 常见原因 | 先查什么 |
| ---- | -------- | -------- |
| bookie 启动失败，报 cookie 相关异常 | 换了磁盘 / 改了目录 / 实例 ID 不匹配（`Cookie.java:162-166`） | `bin/bookkeeper shell cookie_get`、`whatisinstanceid`；确认数据归属后再决定是否 `bookieformat -d` |
| 磁盘持续写满 | GC 没跑、或存活率高于阈值 | `listfilesondisc -log`；检查 `minorCompactionThreshold` 与 GC 是否真的在执行 |
| bookie 进入只读 | 磁盘使用率 ≥ 0.95 | `bookieinfo`、`listfilesondisc`；扩容或先腾出 ≥ `1.2 × logSizeLimit` |
| 重启一个 bookie 后全集群流量暴涨 | `lostBookieRecoveryDelay = 0` 导致立刻大规模补副本 | 重启前先 `lostbookierecoverydelay -set <秒>`，重启后再设回 |
| 删除数据后磁盘不降 | GC 尚未压缩对应 entry log | 见 [Storage](/docs/CS/Framework/BookKeeper/Storage.md)「Garbage Collection」 |
| 写延迟毛刺 | ensemble change / speculative / journal fsync | ensemble change 计数、journal sync 耗时 |
| 队列打满写阻塞 | force write 队列逼近 `journalQueueSize` | journal 盘 IOPS、`numJournalCallbackThreads` |

## Frequently Used Commands

入口统一是 `bin/bookkeeper shell <子命令>`（完整列表见官方 CLI 参考）：

| 场景 | 命令 |
| ---- | ---- |
| 看集群成员 | `listbookies -rw` / `-ro` / `-a` / `-h` |
| 看某个 ledger 的元数据 | `ledgermetadata -l <ledgerId>`、`ledger -m <ledgerId>` |
| 看磁盘上的文件 | `listfilesondisc -txn` / `-log` / `-idx` |
| 看副本缺失 | `listunderreplicated [-missingreplica <bookieId>]`、`whoisauditor` |
| 手动触发审计 / 补副本 | `triggeraudit`、`decommissionbookie`、`forceauditchecks` |
| 开关 auto-recovery | `autorecovery -e` / `-d`；状态：`queryautorecoverystatus` |
| 调整丢节点等待 | `lostbookierecoverydelay -get` / `-set <秒>` |
| 读数据排查 | `readledger <ledgerId>`、`readlog`、`readjournal`、`readlogmetadata` |
| cookie 相关 | `cookie_get` / `cookie_generate` / `cookie_delete` / `cookie_update` / `updatecookie` |
| 磁盘与一致性检查 | `bookieinfo`、`localconsistencycheck`、`clusterinfo`、`lastmark` |
| 格式化（**危险**） | `bookieformat [-d]`、`initbookie`、`initnewcluster`、`nukeexistingcluster` |
| 本地验证 | `bin/bookkeeper localbookie <N>`、`bookiesanity`、`simpletest` |

> [!WARNING]
> `bookieformat` / `nukeexistingcluster` / `metaformat` 是**破坏性操作**，会丢数据或丢元数据。`metaformat` 自 4.7.0 起已废弃，应改用 `initnewcluster` / `nukeexistingcluster`。执行前先确认操作的是哪个集群（看 `whatisinstanceid`）。

## Version And Upgrade Notes

| 版本 | 值得注意的变化 |
| ---- | -------------- |
| 4.17.3 | `LedgerHandleImpl` / `PackagePrivateLedgerHandleImpl` 合并为单一 `LedgerHandle`（引用旧类名会编译失败；4.18.1 为 2563 行）。[Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md) 4.2.4 依赖这一版 |
| 4.18.x | 元数据格式继续演进（`cToken` 等字段）；`bookie/` 包下 entry log 实现为 `DefaultEntryLogger`（不再有 `EntryLogger.java`） |
| 4.18.2（已公告，仓库仅 `v4.18.2-rc0`） | 公告提到分区化 entry location RocksDB 的 index/filter block 以提升读吞吐；尚未作为稳定基线 |

> [!NOTE]
> 官方文档站点（`bookkeeper.apache.org/releases`）的「最新版本」展示滞后于代码仓库（当前页仍写 4.17.3）。确认版本时以 GitHub tag 为准，不要以官网首页为准。

## Corrections To Common Claims

| 说法 | 4.18.1 实况 |
| ---- | ----------- |
| 「journal 默认目录就是生产路径」 | ❌ 默认 `/tmp/bk-txn`（`:1379`） |
| 「entry log 默认 2 GB，所以磁盘要留 2.4 GB」 | ❌ 1 GiB，对应 `minUsableSizeForEntryLogCreation` 默认 1.2 GiB |
| 「默认会开启 auto-recovery」 | ❌ `autoRecoveryDaemonEnabled` 默认 false |
| 「GC 按「垃圾率」触发」 | ❌ 按**存活率**阈值（minor 0.2 / major 0.8） |
| 「bookie 只读后磁盘不再写入」 | ❌ compaction 与 journal replay 仍可写，前提是剩余 ≥ 1.2 × entry log 上限 |

## Links

- [BookKeeper](/docs/CS/Framework/BookKeeper/BookKeeper.md)
- [Storage](/docs/CS/Framework/BookKeeper/Storage.md)
- [Cluster](/docs/CS/Framework/BookKeeper/Cluster.md)
- [Write](/docs/CS/Framework/BookKeeper/Write.md)
- [Read](/docs/CS/Framework/BookKeeper/Read.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [BookKeeper CLI tool reference](https://bookkeeper.apache.org/docs/next/reference/cli/)
2. [ServerConfiguration.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/conf/ServerConfiguration.java)
3. [ClientConfiguration.java (release-4.18.1)](https://github.com/apache/bookkeeper/blob/release-4.18.1/bookkeeper-server/src/main/java/org/apache/bookkeeper/conf/ClientConfiguration.java)
4. [BookKeeper — Admin guide](https://bookkeeper.apache.org/docs/latest/admin/bookies)
