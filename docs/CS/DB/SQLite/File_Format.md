## Introduction

SQLite 的数据库文件格式自 3.0.0（2004-06-18）起冻结，**向后兼容是硬承诺**：今天写的文件二十年前的库必须能读。理解它有三个直接收益：敢用十六进制编辑器排障、敢把库文件当跨系统的数据交换格式、能准确评估「拷贝文件就算备份」在什么模式下是错的（WAL 模式下是错的，因为 `-wal` 里可能有已提交事务）。

本页以官方 file format 规范为准。所有多字节字段大端，偏移均从文件头起算。

## File Header

前 100 字节（仅第 1 页有）：

| 偏移 | 字段 | 说明 |
| :--- | :--- | :--- |
| 0 | 魔数字符串 | `SQLite format 3\0`，16 字节 |
| 16 | 页大小 | 512~65536 的 2 的幂；**默认 4096**（3.12.0 起）；值 `0x0001` 表示 65536 |
| 18/19 | 读写版本号 | 回滚日志模式 = 1/1；WAL 模式 = 2/2。写版本大于读版本 → 只读打开；读版本大于 2 → 打不开 |
| 20 | 每页保留字节 | 通常 0；加密扩展放 nonce 用。可用大小 = 页大小 − 保留字节，不得小于 480 |
| 24 | 文件变更计数器 | 每次修改并解锁后递增；多进程据此发现页面缓存已过期 |
| 28 | 头内数据库大小 | 页数；**仅当偏移 92 与偏移 24 相等时才可信**（老版本写入时不更新 92，这是兼容机制） |
| 32/36 | 第一个 freelist trunk 页 / freelist 页总数 | auto_vacuum 之外的 freelist 入口 |
| 40 | schema cookie | schema 每次变更递增；预编译语句发现它变了会重新编译或返回 `SQLITE_SCHEMA` |
| 44 | schema format 号 | 1~4；4 支持 serial type 8/9（常数 0/1）等新记录特性 |
| 48 | 默认页缓存大小 | 建库时 `PRAGMA cache_size` 的快照，仅建议值 |
| 52 | 最大自动 vacuum 页号 | 0 = 禁用 auto_vacuum |
| 56 | 文本编码 | 1=UTF-8、2=UTF-16le、3=UTF-16be；创建后不可改 |
| 60/64 | user version / incremental vacuum | 前者归应用用；后者非 0 表示 incremental vacuum 模式 |
| 68 | application_id | 归应用用；可被 `file(1)` 识别具体文件类型 |
| 92/96 | version-valid-for / SQLITE_VERSION_NUMBER | 见偏移 28 行 |

## Page Layout and B-tree

页从 1 开始编号，每页有且仅有一种用途：表/索引 B-tree 页（内部或叶子）、freelist 页、溢出页、指针映射页（ptrmap）、锁字节页。B-tree 页头 8 字节（叶子）或 12 字节（内部，多一个最右子页指针）：

| 偏移 | 大小 | 字段 |
| :--- | :--- | :--- |
| 0 | 1 | 页类型：2=索引内部、5=表内部、10=索引叶子、13=表叶子 |
| 1 | 2 | 首个 freeblock 偏移（无则 0） |
| 3 | 2 | cell 数量 |
| 5 | 2 | cell 内容区起始偏移（0 解释为 65536） |
| 7 | 1 | 内容区内碎片化空闲字节数 |
| 8 | 4 | 最右子页指针（仅内部页） |

页头之后是**按键序排列的 cell 指针数组**（2 字节偏移 × cell 数），中间夹着未分配空间；cell 从页尾向前分配。freeblock 是页内被删除 cell 留下的空洞，链在页头偏移 1 上，insert 时优先复用，复用不了才动内容区。

**第 1 页同时是 `sqlite_schema` 表的根页**——schema 本身就是一张表（`type, name, tbl_name, rootpage, sql`），`.schema` 命令读的就是它。这意味着「数据库的结构」与「数据库的数据」在文件里是同一种东西，这也是「数据库文件即数据交换格式」的根基。`sqlite_schema` 的别名 `sqlite_master` 仍可用。

## Record Format and Varint

一行数据 = 记录头（varint 头长 + 每列一个 serial type）+ 主体：

| serial type | 含义 |
| :--- | :--- |
| 0 | NULL |
| 1~6 | 1/2/3/4/6/8 字节大端二进制补码整数 |
| 7 | 8 字节 IEEE 754 浮点 |
| 8 / 9 | 常数 0 / 1（schema format 4 起） |
| 12 偶数 N | BLOB，(N−12)/2 字节 |
| 13 奇数 N | TEXT，(N−13)/2 字节，不存 nul 结尾 |

整数用 **varint**：1~9 字节，前 8 字节各贡献低 7 位、第 9 字节贡献 8 位，大端。小整数（0~127）只占 1 字节——这是「SQLite 文件比想象中小」的原因之一。serial type 10、11 保留给内部使用。

## Overflow Pages

payload 超过页内容放得下的部分进溢出页链。设可用大小 `U`、payload `P`：

- 表叶子页 `X = U − 35`；索引页 `X = ((U−12)×64/255) − 23`；公共下限 `M = ((U−12)×32/255) − 23`；`K = M + ((P − M) mod (U − 4))`。
- `P ≤ X` 全部放页内；`P > X` 且 `K ≤ X` 时页内存 `K` 字节、其余溢出；`K > X` 时页内只保 `M` 字节。**叶子页承载量永不低于 M**。

这套怪异的公式是为了保证索引 B-tree 的最小扇出为 4，且记录头通常不必访问溢出页就能读。溢出页自身组成单向链，每页前 4 字节是下一页页号——大 BLOB 的顺序读因此是「页内一段 + 溢出链一段」的跳跃模式，随机读大 BLOB 的代价远高于等量小行。

## Freelist and Pointer Map

- **freelist**：trunk 页与 leaf 页两级结构。trunk 页头 4 字节是下一个 trunk 页号，随后 4 字节是「本 trunk 直接挂的 leaf 页数」，再往后是这些 leaf 页号（最多 `(U/4) − 2` 个）。头内偏移 32/36 记录第一个 trunk 与总页数。`auto_vacuum=NONE`（默认）下删除产生的空闲页进 freelist 复用，文件不缩小。
- **ptrmap**：auto_vacuum 非 NONE 时出现，每页对应一个 5 字节条目，记录该页被谁引用（根页 / 页 1 / 空闲页 / 溢出第一页 / 溢出后续页）。它让 auto_vacuum 能移动页而不破坏引用；对老版本 SQLite 保持向后兼容——ptrmap 页在文件里「隐身」，老库直接跳过。
- **锁字节页**：偏移约 1 GiB 处的特殊页，只被遗留 VFS 使用，现代实现不需要。

## WAL File Format

`-wal` 文件 = 32 字节头 + 零到多帧，每帧 = 24 字节帧头 + 一整页数据。两者都是 8 / 6 个大端 32 位无符号整数：

| WAL 头偏移 | 字段 | 说明 |
| :--- | :--- | :--- |
| 0 | 魔数 | `0x377f0682` 或 `0x377f0683`；**决定校验和按大端还是小端解释**（0683=大端，0682=小端） |
| 4 | 文件格式版本 | 当前 3007000 |
| 8 | 数据库页大小 | |
| 12 | checkpoint 序列号 | |
| 16/20 | salt-1 / salt-2 | 每次 checkpoint 时 salt-1 递增、salt-2 随机 |
| 24/28 | 头校验和 | 只覆盖头前 24 字节 |

帧头偏移 0/4/8/12/16/20 依次是：页号、**提交后数据库页数（非 0 即提交帧）**、salt-1、salt-2、两个累积校验和。帧有效需同时满足 salt 与 WAL 头一致、累积校验和吻合（覆盖头前 24 字节 + 各帧头前 8 字节 + 页内容）。

崩溃恢复就是把这些规则用起来：wal-index 是**瞬态结构**，崩溃后从 WAL 文件重建，因此恢复时逐帧验证 salt 与校验和，找到最后一个有效提交帧，把之后的页写回数据库；WAL 重置（salt-1 递增、salt-2 随机化）让已 checkpoint 但未覆写的旧帧自然失效，防止被重复 checkpoint。

## Rollback Journal Format

`-journal` = 28 字节头（后接零填充至一个扇区，保证头部独占一个扇区）+ 若干页记录：

| 偏移 | 字段 | 说明 |
| :--- | :--- | :--- |
| 0 | 魔数 | `d9 d5 05 f9 20 a1 63 d7` |
| 8 | 页记录数 | 或 -1 表示「到文件尾」 |
| 12 | 随机 nonce | 该校验和的种子 |
| 16 | 数据库初始页数 | 回滚时据此截断 |
| 20 | 扇区大小 | 写日志进程假定的值 |
| 24 | 页大小 | |

页记录 = 4 字节页号 + N 字节**原始页内容** + 4 字节校验和。校验和是**稀疏采样**：从页尾向前每 200 字节采一个字节累加——全程校验整页性能代价太大，SQLite 选择「检出陈旧日志」而不是「检出一切损坏」。同一页在一个日志里不得出现两次；freelist 叶子页不含需恢复信息，不写日志。

多段日志（页计数大于 0）允许在同一文件内追加新日志头；多库事务的 super-journal 只记各单日志的**文件名**，删除 super-journal 即跨库提交时刻。

## Facts Worth Pinning Down

1. **头内数据库大小不是永远可信**：只有当偏移 92（version-valid-for）等于偏移 24（变更计数器）时才是。老版本 SQLite 写入时只更新后者——这是刻意的兼容设计，不是 bug。
2. **WAL 魔数同时决定校验和字节序**：跨机器拷 `-wal` 时这一点无关紧要（校验和值本身始终大端存储），但自己写解析器时会踩。
3. **页大小可以不同库不同，但库内必须统一**；改页大小等于重建库（`VACUUM`），见 [Operations](/docs/CS/DB/SQLite/Operations.md)。
4. **`-journal` 里存的是旧页，`-wal` 里存的是新页**：一个是回滚（undo），一个是前滚（redo），方向相反，别混。
5. **ptrmap 与 freelist trunk 是「结构性页」**：它们占页号但不属于任何表，`integrity_check` 会校验它们，手工拼库文件时最容易在这里出错。

## Links

- [SQLite](/docs/CS/DB/SQLite.md)
- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [Indexes](/docs/CS/DB/Concept/Index.md)
- [RocksDB Table_Format](/docs/CS/DB/RocksDB/Table_Format.md)

## References

1. [Database File Format](https://sqlite.org/fileformat2.html)
2. [CREATE TABLE](https://sqlite.org/lang_createtable.html)
