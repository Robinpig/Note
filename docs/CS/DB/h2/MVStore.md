## Introduction

MVStore（Multi-Version Store）是 H2 2.x 的默认存储层：一个**日志结构（log-structured）的多版本键值存储**，上面跑 copy-on-write 的 B-tree。它有两个身份——既是 H2 的落地引擎（`.mv.db` 文件就是一个 MVStore），又是一套**可以脱离 SQL 单独使用的持久化 `java.util.Map`**。

> [!NOTE]
> **H2 2.5.252 的官方文档里没有 MVStore 章节**（`h2database.com/javadoc/org/h2/mvstore/package-summary.html` 返回 404）。本节所有事实取自该 tag 的 sources jar（路径以 `org/h2/mvstore/` 开头），行号即在其中。文档里那句 `features.html#logging_recovery`「变更先写事务日志、主数据区随后落盘」描述的是**已不存在的独立事务日志模型**（`RawStore` / `PageStore` 已删），别按它理解现代 H2。

## Standalone Key-Value Usage

入口两个：`MVStore.open(String fileName)`（`MVStore.java:541`）与流式构造器 `new MVStore.Builder()...open()`（`:2192`）。`Builder` 上**真实存在**的方法：

```
fileName · readOnly · encryptionKey(char[]) · autoCommitDisabled
autoCommitBufferSize(int kb) · autoCompactFillRate(int %) · keysPerPage(int)
pageSplitSize(int) · cacheSize(int mb) · cacheConcurrency(int)
compress() · compressHigh() · recoveryMode() · backgroundExceptionHandler(...)
fileStore() / adoptFileStore() · 静态 Builder.fromString(String)
```

注意几个**不存在**的名字：没有 `Open()`、没有 `offHeap()`——堆外要靠 `fileStore(new OffHeapStore())`（且该 store 必须已打开），也没有 `autosave`、`writeDelay`、`verifyStores`、`TTLMap`、`expirePageMachines`。

Map 侧 API 是 `openMap(name)` / `openMap(name, MVMap.MapBuilder)` / `openMap(int id, ...)`，配 `hasMap`、`removeMap`、`renameMap`、`getMapNames`、`getMetaMap`、`getLayoutMap`。`MVMap` 实现 `java.util.Map` 且额外提供有序操作：`firstKey` / `lastKey` / `getKeyIndex` / `keyIterator` / `cursor` / `sizeAsLong` / `append`（单写者快速追加），以及 **`openVersion(v)`——打开一个更早的只读快照版本**。

> [!WARNING]
> 两个坑：① **没有 `createSnapshot()`**，回滚是 store 级的 `rollback()` / `rollbackTo(version)`；② `openMap` 时传一个与已存在 map 类型不同的 `MVMap.Builder` 会**被静默忽略**（只有一句 `assert`，`MVStore.java:580`），而 map 的类型信息**不会持久化**（`MVMap.java:1097` 只写 name/createVersion/type）。跨进程用不同类型打开同一个 map，读出来就是错的——这是「H2 文件被人用别的进程打开过就乱码」这类报告的真实来源之一。

## File Structure

磁盘块固定 4096 字节（`FileStore.java:85`）。**第 0、1 块是两份完全相同的 store header**，内容是一个十六进制编码的文本 map：

```
H:2,blockSize:1000,format:3,created:...,chunk:...,block:...,version:...,clean:...,fletcher:...
```

它只在「预测值不匹配 / 版本数超过 20 / 有 chunk 被移除」时才惰性重写（`RandomAccessStore.java:410-441, 622-641`）。`format` 的读写范围都是 **3**（`FileStore.java:87-90`）——**所以 2.x 打不开 1.4.x 时代的 MVStore 文件**，这不是配置问题。

chunk 的头尾同样是**纯文本**：`chunk:x,len:y,version:z,fletcher:w`，头部 ≤1024 字节、尾部 128 字节补齐、以 `\n` 结束（`Chunk.java:38-63, 224-278, 391-403`）。**2.5.252 里没有任何 `!MC` 之类的魔数**——网上「MVStore chunk 以 `!` 结尾」的说法对应的是更早的实现。

页位置的打包方式解释了为什么单页有上限：

```
chunkId = pos >>> 38      // chunk 编号占 26 位（Chunk.java:31）
bit 1-5 = 长度码（31 表示 PAGE_LARGE，2 MiB）
bit 0   = 叶子页 / 内部页
类型标志 |= 2（LZF 压缩）| 6（Deflate 压缩）
真实字节偏移移到 chunk 的 TOC 里（tocElement >> 6）
```

两类内部 map 承载元数据：meta map 的键是 `name.{n}` / `map.{id}` / `setting.storeVersion`；layout map 的键是 `chunk.{id}` / `root.{mapId}`（`MVStore.java:676-712`）。

## Commit and Background Write

| 机制 | 事实 | 出处 |
| :--- | :--- | :--- |
| `commit()` | 同步：等待并写入 | `MVStore.java:877-935` |
| `tryCommit()` | 已有提交在途时立即返回，**可能在本次线程的变更尚未持久化时就返回** | 同上 |
| 自动提交线程 | 守护线程 `MVStore background writer …`，轮询间隔 `max(10, delay/3)` ms | `FileStore.java:2294-2305` |
| 序列化/落盘线程 | 单线程执行器 `H2-serialization` 与 `H2-save` | `FileStore.java:456-470` |
| **fsync** | **只有** `MVStore.sync()` → `FileChannel.force(true)`，对应 SQL 的 `CHECKPOINT SYNC` | `MVStore.java:1091`、`SingleFileStore.java:176` |
| `WRITE_DELAY` | 映射到 `setAutoCommitDelay`，SQL 层默认 **500 ms** | `Database.java:1788`、`Constants.java:228` |

默认值一览（这些数字决定了 H2 的内存/延迟曲线）：`autoCommitDelay` 1000 ms、`keysPerPage` **48**、`cacheSize` **16 MB**、`cacheConcurrency` 16、`pageSplitSize` = `DEFAULT_PAGE_SIZE` **16 KiB**（并被夹到 `cache.getMaxItemSize() >> 4`）、`retentionTime` **45000 ms**（堆外 store 为 0）、`autoCommitBufferSize` = `min(19, 64 × Xmx/1GB) MB`——**Builder 的 javadoc 里那句「default is 1024 KB」已经过期**。页分裂条件是 `keyCount > keysPerPage || memory > maxPageSize`（`MVMap.java:1786`）。

> [!WARNING]
> **`commit()` 与 `tryCommit()` 在持久性上不可互换**，而「自动提交延迟」根本不等于 fsync：默认路径下数据进了 page cache 就算完成，掉电窗口由磁盘写缓存决定（见 [H2 的持久性边界](/docs/CS/DB/h2/H2.md)）。
>
> 还要破除一个心智模型：**2.x 的 H2 没有一条独立于主文件的 WAL**。官方 `features.html#database_file_layout` 列出的持久化库文件是 `.mv.db`、`.newFile`、`.tempFile`、`.lock.db`、`.trace.db`、`<db>.<id>.temp.db`——**里面没有 `.log`**；而 `.mv.db` 自己的描述就是「Contains the transaction log, indexes, and data for all tables」，即日志在 MVStore 文件内部。`features.html#logging_recovery` 那段「变更先写事务日志、主数据区稍后落盘」的叙述属于已删除的 `PageStore` / `RawStore` 时代（两个类在源码里已不存在），别按它理解恢复流程。讨论「H2 有没有 WAL」，正确答案是「存储层本身就是 log-structured」——这也正是 [WAL](/docs/CS/DB/Concept/WAL.md) 与 LSM 设计的共同根脉（对照 [RocksDB Write Path](/docs/CS/DB/RocksDB/Write_Path.md) 里 WAL 与 memtable 分离的做法）。
>
> 另一个单位陷阱：`Builder.cacheSize(mb)` 与 `getCacheSize()` 单位是 **MB**，而 `setCacheSize(int kb)` 内部会除以 1024、单位是 **KB**（`MVStore.java:2094/1205/1225`）；SQL 层 `SET CACHE_SIZE` 也是 KB（默认按内存自动取 64 MB/每 GB RAM 并向上取 2 的幂）。三层单位混过一次就会写出 1024 倍误差的配置。

## Compression and Encryption

压缩是**页级**的：`compress: 1` = LZF，`compress: 2` = Deflate；而 `compressHigh()` 写入的配置键其实是同一个 `compress`（值 2，`MVStore.java:2135`）。只有当载荷 >16 字节且确实变小才压（`Page.java:746-780`）。SQL 层 `COMPRESS=true` 会把 `pageSplitSize` 提到 64 KiB（`Store.java:112-117`）——大页更利于压缩。

**加密的真相与文档不同**：`.mv.db` 主文件的加密由 `FileEncrypt` 负责，算法固定为 **AES-128 in XTS 模式**，4 KiB 粒度，头部是 `"H2encrypt\n"` + 8 字节 salt，密钥由 `SHA256.getPBKDF2(UTF-16 口令, salt, 10 轮, 16 字节)` 派生（`FileEncrypt.java:29-54, 113-126`）。URL 里的 `CIPHER=AES|XTEA|FOG`（`CipherFactory.java:69-78` 确实只认这三个）**并不决定主文件算法**，它的作用是：把口令拆成「文件口令 + 用户口令」两段，以及为 LOB/临时文件与脚本文件选择 `SecureFileStore` 的加密（那里迭代次数是 1024）。

由此有两条实用结论：`CIPHER=XTEA/FOG` 写进 `.mv.db` 仍然是 AES-XTS，别据此以为降低了主文件强度（`FOG` 只是伪加密，用于让文本编辑器看不出内容）；而**主文件 KDF 只有 10 轮 SHA-256，不能拿它替代磁盘级加密**——H2 文档对加密边界的定位也是如此：防的是「文件被离线拿走」，不防有写权限的人。

## SQL Layer Mapping

表与索引在 MVStore 里就是若干具名 map，命名规则值得记住（排障时 `-dump` 出来的就是这些）：

| 内容 | map 名 | 出处 |
| :--- | :--- | :--- |
| 主索引（表数据本体） | `table.<indexId>` | `MVPrimaryIndex.java:52`（SQL 侧索引名 `<TBL>_DATA`） |
| 二级 / 空间索引 | `index.<indexId>` | `MVSecondaryIndex.java:56`、`MVSpatialIndex.java:101` |
| 临时表 | `temp.<n>` | — |
| 大对象 | `lobMap` / `lobData` / `tempLobMap` / `lobRef` | `LobStorageMap.java:98-146` |
| LOB 数据块 | StreamStore，块大小 256 B – 256 KiB；**≤256 B 的 LOB 内联存储** | `StreamStore.java:52`、`Constants.java:200` |

H2 打开库时会先删掉没人引用的孤儿 `table.*` / `index.*` map（`Store.java:269-278`），store 以 `autoCommitDisabled()` 打开再 `setVersionsToKeep(0)`（`:126-133`）。

## Space Reclamation

**「DROP TABLE 之后文件没变小」不是 bug，而是这套多版本结构的必然结果**，链条是：

1. `removeMap` 是**延迟**执行的——要等当前版本不再被引用才真正删（`MVStore.java:1594-1628`）。
2. chunk 只有在「时间 + `retentionTime`（默认 45 s）已过」且不被 `oldestVersionToKeep` 引用时才可覆写（`FileStore.java:729`、`MVStore.java:213`）。**一个长事务会直接把空间回收钉住**，因为它压低了 `oldestVersionToKeep`。
3. 空闲页复用由 `setReuseSpace`（默认开，SQL 侧 `REUSE_SPACE`）与 `autoCompactFillRate`（默认 **90**，0 关闭）决定：只有当前 chunk 填充率低于阈值才去复用旧空间。
4. 文件截断只能砍掉尾部空闲块（`RandomAccessStore.java:728-745`）；关闭时的自动压缩默认只给 **200 ms**。

所以要真正缩库，只有两条路：`SHUTDOWN COMPACT`（或 `DbSettings.DEFRAG_ALWAYS`），或做一次全量重写——`SHUTDOWN DEFRAG`、`MVStore.compact()`（写 `*.tempFile` 后原子替换，回退用 `*.newFile`），最彻底的是 `SCRIPT` 导出 + `RUNSCRIPT` 重建（顺带重建索引）。

## Recovery and Offline Tools

`org.h2.mvstore.MVStoreTool`（注意：**在 `mvstore` 包下，不在 `org.h2.tools`**）的子命令是 `-dump -info -compact -compress -rollback <version> -repair`（`MVStoreTool.java:54-76`）——**没有 `-copy`**。`info`/`dump` 会以 `recoveryMode().readOnly()` 打开（`:349-355`），因此损坏文件也能读。`repair` 的策略很直白：逐版本回滚到 `*.temp`，成功后把原文件改名 `*.back`（`:495-521`）。

SQL 层还有 `Recover` 工具（产出 `*.mv.txt` 与 `*.h2.sql`）与较新的 `DirectRecover`。每次用 SQL 打开库时，`MVStoreTool.compactCleanUp` 会顺手清理上一次遗留的临时文件（`Store.java:92`）。

## Limits and Pitfalls

- chunk 编号 26 位；`MVMap.size()` 会封顶在 `Integer.MAX_VALUE`，**大表必须用 `sizeAsLong()`**（`MVMap.java:976`）。
- 单页编码上限 2 MiB，更大的走 `PAGE_LARGE`；MVStore 本身没有「单键/单值大小」限制，实际限制来自 H2 的类型层（见 [SQL_Language](/docs/CS/DB/h2/SQL_Language.md)）。
- 并发打开事务数默认 **255**（`TransactionStore.java:129`，由 `h2.maxOpenTransactions` 控制，**它是 JVM 全局静态量，按库设置无效**），而文档 `Limits` 写的是 65535。
- 文档里还在介绍的 `CACHE_TYPE=TQ` / `SOFT_LRU` 是**死代码**：`getCacheType()` 没有调用方，MVStore 永远使用 `CacheLongKeyLIRS`。
- 与 RocksDB/LevelDB 对照读的话，这里的形状很像「把 LSM 换成了 cow-B-tree + 日志结构 chunk」：同样靠追加写换随机写性能，同样把回收代价推给后台（compact），同样有「长事务钉住旧版本」的空间放大问题（见 [RocksDB Write Path](/docs/CS/DB/RocksDB/Write_Path.md)）。

## Links

- [H2](/docs/CS/DB/h2/H2.md)
- [Transactions and Locks](/docs/CS/DB/h2/Transactions_and_Locks.md)
- [Connection and Servers](/docs/CS/DB/h2/Connection_and_Servers.md)
- [Tools and Operations](/docs/CS/DB/h2/Tools_and_Operations.md)
- [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)
- [RocksDB Table Format](/docs/CS/DB/RocksDB/Table_Format.md)

## References

1. [H2 Database Engine](https://h2database.com/html/main.html)
2. [H2 Database Engine - Features](https://h2database.com/html/features.html)
3. [H2 source at tag 2.5.252: org/h2/mvstore/MVStore.java](https://github.com/h2database/h2/blob/2.5.252/src/main/h2/org/h2/mvstore/MVStore.java)
4. [H2 Database Engine - Advanced Features](https://h2database.com/html/advanced.html)
