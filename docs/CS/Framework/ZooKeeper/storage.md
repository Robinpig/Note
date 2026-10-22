## Introduction

ZooKeeper 的所有写操作都先落 **事务日志（TxnLog，WAL）**，再周期性地物化 **快照（SnapShot）**，二者配合在重启时恢复出完整的内存数据树（DataTree）。这套机制与 etcd 的 boltdb、Redis 的 RDB+AOF 思路一致，但 ZooKeeper 把"全量内存 + WAL + 快照"三者耦合得更紧：服务器把整棵 znode 树常驻内存，磁盘只是持久化与恢复的副产物。

本篇聚焦磁盘侧的存储引擎——`FileTxnLog` / `FileSnap` / `FileTxnSnapLog` 以及内存侧的 `ZKDatabase` / `DataTree` / `DataNode`，并解释 zxid 的构成、快照触发条件与启动恢复流程。共识层为何把这些事务广播出去，见 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md)；一次写请求如何流经各处理器并最终落到这里，见 [pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)。

> [!NOTE]
> 版本基线：事务日志的 Adler-32 校验和在 3.4.x 已默认开启；快照文件头含 `count` 字段（3.6+）；当前主线 3.9.6，维护线 3.9.x / 3.8.x，3.7 已 EOL。

## Overall Structure

```dot
digraph "ZKStorage" {
  rankdir = "LR";
  node [shape = box, style = rounded];
  Client [label = "写请求"];
  Sync [label = "SyncRequestProcessor"];
  TxnLog [label = "FileTxnLog\n(WAL, 顺序追加)", color = "#b30000", fontcolor = "#b30000"];
  Snap [label = "FileSnap\n(快照, 全量物化)", color = "#006d2c", fontcolor = "#006d2c"];
  ZKDB [label = "ZKDatabase\n(内存)"];
  Tree [label = "DataTree\n(DataNode map)"];

  Client -> Sync;
  Sync -> TxnLog [label = "append"];
  Sync -> Snap [label = "shouldSnapshot"];
  ZKDB -> Tree;
  TxnLog -> ZKDB [label = "replay(恢复)"];
  Snap -> ZKDB [label = "deserialize(恢复)"];
}
```

- **TxnLog**：接口，磁盘实现 `FileTxnLog`。顺序追加的 WAL，一个事务一条记录，是持久化的"真相来源"。
- **SnapShot**：接口，磁盘实现 `FileSnap`。某一时刻 DataTree 的全量物化，加速重启。
- **FileTxnSnapLog**：同时持有 TxnLog 与 SnapShot 的适配层，被 `ZKDatabase` 持有。
- **ZKDatabase**：内存数据库，持有 `DataTree`（znode 树）、会话超时表与 `lastProcessedZxid`。

## zxid: Unique Transaction Sequence Number

每个事务都带一个 64 位 `zxid = epoch(高 32 位) + counter(低 32 位)`：

- **epoch**：Leader 任期号，每次新 Leader 选举产生会自增（`currentEpoch` 文件持久化）。它让旧 Leader 的提案不会在新任期被误接受。
- **counter**：当前任期内的单调递增计数器。

zxid 同时是**快照与日志文件命名的依据**，也是数据一致性的全局版本号——客户端 `sync()` 后读到的是"已提交且 zxid 最大"的状态。DataNode 的 `Stat` 里 `czxid` / `mzxid` / `pzxid` 记录了创建、修改、子节点变更对应的 zxid。

## Transaction Log FileTxnLog

`FileTxnLog` 位于 `zookeeper-server/.../server/persistence/`，在 `dataLogDir` 下写入 `log.<zxid>` 文件，文件名中的 zxid 是**该文件第一条事务的 zxid**。

每条事务在磁盘上的布局（由 `TxnLog` 格式约定）：

```
+---------------------------------------------------------------+
| TxnHeader: clientId | cxid | zxid | time | type              |  <- Jute 序列化
+---------------------------------------------------------------+
| Record(body): 具体事务负载，如 CreateTxn / SetDataTxn / ...   |  <- Jute 序列化
+---------------------------------------------------------------+
| checksum: Adler-32(long)，覆盖前面所有字节                    |
+---------------------------------------------------------------+
```

要点：

- **顺序追加 + `forceSync`**：`SyncRequestProcessor` 默认在返回客户端响应前把事务刷盘（`forceSync=yes`，调用 `fsync`），这正是 ZooKeeper 写吞吐受事务日志磁盘 I/O 约束的根因——因此官方建议把 `dataLogDir` 挂到独立磁盘。
- **预分配**：最后一个日志文件按 `preAllocSize`（默认 64KB）预先 `preallocate`，减少文件系统元数据开销。
- **滚动**：当 `shouldRoll()` 命中（文件大小超过阈值或跨 epoch）时换新文件。
- **校验**：默认开启 Adler-32，读取时若校验失败会报日志损坏，可用 `zkTxnLogToolkit.sh` 检查/修复。

> [!WARNING]
> 不要把 `dataLogDir` 和放快照的 `dataDir` 放在同一块盘上。事务日志的写延迟直接决定集群写吞吐；快照生成与日志写入争抢 I/O 会让 P99 延迟陡增。

## Snapshot FileSnap

`FileSnap` 在 `dataDir` 下写入 `snapshot.<zxid>`，文件名中的 zxid 是**该快照包含的最后一条事务的 zxid**。文件内含：

1. `FileHeader`：`magic` / `version` / `dbId` / `count`（3.6+ 记录节点数，用于快速校验）。
2. 序列化的 `DataTree`：所有 `DataNode`（path → data、acl、stat、children）、ACL 字典（去重后的 `ACL` 列表）、以及会话超时表。
3. 末尾 Adler-32 校验和。

快照是**模糊快照（fuzzy snapshot）**：生成期间仍有写请求落到内存树，因此快照内容对应的是"某一瞬间的近似值"，但配合其后 replay 的日志即可还原到精确状态。

## Snapshot Trigger: shouldSnapshot

`SyncRequestProcessor.shouldSnapshot()` 决定何时物化快照（见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 的 `Issues` 段源码）：

```java
private boolean shouldSnapshot() {
    int logCount = zks.getZKDatabase().getTxnCount();
    long logSize = zks.getZKDatabase().getTxnSize();
    return (logCount > (snapCount / 2 + randRoll))
           || (snapSizeInBytes > 0 && logSize > (snapSizeInKB / 2 + randSize));
}
```

- `snapCount`（`zookeeper.snapCount`，默认 100000）：当事务数超过 `snapCount/2 + randRoll`（随机抖动，避免集群同时打快照）时触发。
- `snapSizeLimitInKb`（`zookeeper.snapSizeLimitInKb`，3.6+）：按事务日志体积触发，默认 4GB。
- `randRoll` / `randSize`：随机量，`(0, 阈值/2)`，打散各节点快照时机。

触发快照的另外两类场景：节点启动加载完数据、集群产生新 Leader。

**调大 `snapCount` / `snapSizeLimitInKb`** 能降低快照频率，但会让重启时 replay 的日志变长、恢复变慢——这是"写入频率 vs 恢复时间"的权衡。

## In-Memory Data Tree ZKDatabase / DataTree / DataNode

`ZKDatabase`（内存）是服务器的"实时状态"，所有读请求直接打这里：

- **DataTree**：`ConcurrentHashMap<String, DataNode> nodes`（path → DataNode），`ephemerals`（sessionId → 该会话的临时节点集合），ACL 前缀树 `pTrie`。
- **DataNode**：`byte[] data`、`Long acl`、`StatPersisted stat`、`Set<String> children`（排序的有序集合）。
- **sessionsWithTimeouts**：`sessionId → timeout`，用于会话恢复后重建。
- **lastProcessedZxid**：已应用到内存的最新事务号，恢复时作为日志 replay 的起点。

ZooKeeper 把整棵树常驻内存，因此**数据量受 JVM 堆上限约束（GB 级）**——这是它与 etcd（boltdb 仅缓存热数据、可存 TB 级）最本质的容量差异（对比见 [与 etcd 对照](/docs/CS/Framework/ZooKeeper/ZooKeeper.md?id=comparison-with-etcd)）。

## Startup Recovery Flow

服务器 `loadData()` 的双阶段恢复，等价于"快照打底 + 日志增量 replay"：

```dot
digraph "Recover" {
  rankdir = "TB";
  node [shape = box, style = rounded];
  A [label = "找到最新 snapshot.<zxid>"];
  B [label = "FileSnap.deserialize\nDataTree 载入内存"];
  C [label = "lastProcessedZxid = 快照的 zxid"];
  D [label = "找到 zxid > lastProcessedZxid 的 log 文件"];
  E [label = "逐条 replay TxnHeader+Record\n应用到 DataTree"];
  F [label = "ZKDatabase 完整恢复，对外服务"];

  A -> B -> C -> D -> E -> F;
}
```

1. 选定 `dataDir` 中 zxid 最大的快照文件，反序列化为 DataTree，把 `lastProcessedZxid` 设为快照 zxid。
2. 扫描 `dataLogDir` 中 zxid 大于该值的日志文件，按序 replay 每条事务到内存树。
3. 恢复完成，进入选举/同步阶段。

> [!TIP]
> 因为恢复靠"最新快照 + 其后的日志"，所以 `autopurge` 清理旧文件时**绝不能只删日志不删快照**——保留的快照必须与其后的日志配套，否则会丢数据。清理策略见 [troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md)。

## Operations-Related Parameters

| 参数 | 含义 | 默认 |
| :--- | :--- | :--- |
| `dataDir` | 快照存放目录（也放 `myid`、`currentEpoch`） | — |
| `dataLogDir` | 事务日志目录，建议独立磁盘 | 同 `dataDir` |
| `snapCount` | 触发快照的事务数阈值 | 100000 |
| `snapSizeLimitInKb` | 触发快照的日志体积阈值（3.6+） | 4194304 KB |
| `preAllocSize` | 日志文件预分配大小 | 65536 KB |
| `forceSync` | 每条事务是否 fsync | yes |
| `autopurge.snapRetainCount` | 保留的快照/日志文件数 | 3 |
| `autopurge.purgeInterval` | 自动清理间隔（小时，0=关） | 0 |

## Purge: 自动清理快照与事务日志

由于 ZooKeeper 的任何一个变更操作都产生事务，事务日志需要持久化到硬盘；写操作达到阈值后会把内存数据快照到磁盘以加快启动。随着运行时间增长，transaction log 和 snapshot 越来越多，需定期清理。`DatadirCleanupManager` 启动一个 `Timer` 定时任务清理 DataDir 中的 snapshot 及对应 transaction log。

相关配置见上方参数表（`autopurge.purgeInterval` / `autopurge.snapRetainCount`）。`start()` 中当 `purgeInterval <= 0` 时不启动定时任务；`dataDir` / `dataLogDir` 两目录分别存 snapshot 与事务日志（默认只有 dataDir），ZK 自身不会清理，需靠此定时任务或管理员处理。

查看 snapshot 内容可运行 `SnapshotFormatter` 类（`-d` 指定快照绝对路径）。

具体清理方法主要调用 `PurgeTxnLog` 类的 `purge` 方法：

```java
public class DatadirCleanupManager {

    private PurgeTaskStatus purgeTaskStatus = PurgeTaskStatus.NOT_STARTED;

    private final File snapDir;

    private final File dataLogDir;

    private final int snapRetainCount;

    private final int purgeInterval;

    private Timer timer;
    public DatadirCleanupManager(File snapDir, File dataLogDir, int snapRetainCount, int purgeInterval) {
        this.snapDir = snapDir;
        this.dataLogDir = dataLogDir;
        this.snapRetainCount = snapRetainCount;
        this.purgeInterval = purgeInterval;
        LOG.info("autopurge.snapRetainCount set to {}", snapRetainCount);
        LOG.info("autopurge.purgeInterval set to {}", purgeInterval);
    }
}
```


```java
public void start() {
    if (PurgeTaskStatus.STARTED == purgeTaskStatus) {
        return;
    }
    // Don't schedule the purge task with zero or negative purge interval.
    if (purgeInterval <= 0) {
        return;
    }

    timer = new Timer("PurgeTask", true);
    TimerTask task = new PurgeTask(dataLogDir, snapDir, snapRetainCount);
    timer.scheduleAtFixedRate(task, 0, TimeUnit.HOURS.toMillis(purgeInterval));

    purgeTaskStatus = PurgeTaskStatus.STARTED;
}
```

### PurgeTask

创建清理任务PurgeTask开启定时器以一定间隔时间来执行PurgeTask中的定时任务，定时任务在执行的时候会触发定时任务的run方法

```java
static class PurgeTask extends TimerTask {

    private File logsDir;
    private File snapsDir;
    private int snapRetainCount;

    @Override
    public void run() {
        try {
            PurgeTxnLog.purge(logsDir, snapsDir, snapRetainCount);
        } catch (Exception e) {
            LOG.error("Error occurred while purging.", e);
        }
        LOG.info("Purge task completed.");
    }

}
```


```java
public static void purge(File dataDir, File snapDir, int num) throws IOException {
    if (num < 3) {
        throw new IllegalArgumentException(COUNT_ERR_MSG);
    }

    FileTxnSnapLog txnLog = new FileTxnSnapLog(dataDir, snapDir);

    List<File> snaps = txnLog.findNValidSnapshots(num);
    int numSnaps = snaps.size();
    if (numSnaps > 0) {
        purgeOlderSnapshots(txnLog, snaps.get(numSnaps - 1));
    }
}
```

创建事物快照日志文件对象FileTxnSnapLog，然后根据参数获取获取到需要保留的文件数量， 然后根据保留的文件数量计算出保留文件中最小的那个zxid， 然后根据最小的zxid找到需要保留的事物日志文件列表 (事物日志当前最小的那个id之前的1个不能清理在zookeeper事物日志中可能发生滚动日志之前的文件也是会记录到最新的数据)， 然后过滤所有事物日志文件过滤出来需要删除的事物日志文件， 在过滤所有的快照文件找到所有需要删除的快照文件，最后循环删除需要删除的事物日志和快照文件

#### findNValidSnapshots

```java
public List<File> findNValidSnapshots(int n) {
    FileSnap snaplog = new FileSnap(snapDir);
    return snaplog.findNValidSnapshots(n);
}

protected List<File> findNValidSnapshots(int n) {
        List<File> files = Util.sortDataDir(snapDir.listFiles(), SNAPSHOT_FILE_PREFIX, false);
        int count = 0;
        List<File> list = new ArrayList<>();
        for (File f : files) {
            // we should catch the exceptions
            // from the valid snapshot and continue
            // until we find a valid one
            try {
                if (SnapStream.isValidSnapshot(f)) {
                    list.add(f);
                    count++;
                    if (count == n) {
                        break;
                    }
                }
            } catch (IOException e) {
                LOG.warn("invalid snapshot {}", f, e);
            }
        }
        return list;
    }
```

#### purgeOlderSnapshots

在处理事物日志和快照的时候，事物日志不能直接删除掉所有比需要保留最小zxid更小的日志文件 ，因为比需要保留最小zxid快照文件的事物日志可能存在于当前最小需要保留zxid的前一个文件中， 也就是说事物日志要比快快照日志多保留一个，这个于日志写入时的滚动机制有关

We delete all files with a zxid in their name that is less than leastZxidToBeRetain. This rule applies to both snapshot files as well as log files, with the following exception for log files.

A log file with zxid less than X may contain transactions with zxid larger than X.  More
precisely, a log file named log.(X-a) may contain transactions newer than snapshot.X if
there are no other log files with starting zxid in the interval (X-a, X].  Assuming the latter condition is true, log.(X-a) must be retained to ensure that snapshot.X is recoverable.  In fact, this log file may very well extend beyond snapshot.X to newer snapshot files if these newer snapshots were not accompanied by log rollover (possible in the learner state machine at the time of this writing).  We can make more precise determination of whether log.(leastZxidToBeRetain-a) for the smallest 'a' is actually needed or not (e.g. not needed if there's a log file named log.(leastZxidToBeRetain+1)), but the complexity quickly adds up with gains only in uncommon scenarios.  It's safe and simple to just preserve log.(leastZxidToBeRetain-a) for the smallest 'a' to ensure recoverability of all snapshots being retained.  We determine that log file here by calling txnLog.getSnapshotLogs().


```java
static void purgeOlderSnapshots(FileTxnSnapLog txnLog, File snapShot) {
    final long leastZxidToBeRetain = Util.getZxidFromName(snapShot.getName(), PREFIX_SNAPSHOT);

    final Set<File> retainedTxnLogs = new HashSet<>();
    retainedTxnLogs.addAll(Arrays.asList(txnLog.getSnapshotLogs(leastZxidToBeRetain)));

    /**
     * Finds all candidates for deletion, which are files with a zxid in their name that is less
     * than leastZxidToBeRetain.  There's an exception to this rule, as noted above.
     */
    class MyFileFilter implements FileFilter {

        private final String prefix;
        MyFileFilter(String prefix) {
            this.prefix = prefix;
        }
        public boolean accept(File f) {
            if (!f.getName().startsWith(prefix + ".")) {
                return false;
            }
            if (retainedTxnLogs.contains(f)) {
                return false;
            }
            long fZxid = Util.getZxidFromName(f.getName(), prefix);
            return fZxid < leastZxidToBeRetain;
        }

    }
    // add all non-excluded log files
    File[] logs = txnLog.getDataLogDir().listFiles(new MyFileFilter(PREFIX_LOG));
    List<File> files = new ArrayList<>();
    if (logs != null) {
        files.addAll(Arrays.asList(logs));
    }

    // add all non-excluded snapshot files to the deletion list
    File[] snapshots = txnLog.getSnapDir().listFiles(new MyFileFilter(PREFIX_SNAPSHOT));
    if (snapshots != null) {
        files.addAll(Arrays.asList(snapshots));
    }

    // remove the old files
    for (File f : files) {
        final String msg = String.format(
            "Removing file: %s\t%s",
            DateFormat.getDateTimeInstance().format(f.lastModified()),
            f.getPath());

        LOG.info(msg);
        System.out.println(msg);

        if (!f.delete()) {
            System.err.println("Failed to remove " + f.getPath());
        }
    }

}
```

## Links

- [ZooKeeper（架构与数据模型）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Zab（共识与日志复制）](/docs/CS/Framework/ZooKeeper/Zab.md)
- [请求处理器链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [故障排查](/docs/CS/Framework/ZooKeeper/troubleshooting.md)
- [集群运维 cluster](/docs/CS/Framework/ZooKeeper/cluster.md)

## References

1. [ZooKeeper Internals: File Tx Log](https://zookeeper.apache.org/doc/current/zookeeperInternals.html)
2. [Recovery in ZooKeeper](https://zookeeper.apache.org/doc/r3.9.0/zookeeperAdmin.html#sc_maintenance)
3. [ZooKeeper: Wait-free coordination for Internet-scale systems](https://www.usenix.org/legacy/event/atc10/tech/full_papers/Hunt.pdf)
