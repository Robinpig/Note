## Introduction

B-Link-Tree 是 B+Tree 面向**多线程并发访问**的工程化改良，由 Lehman & Yao 在 1981 年论文《Efficient Locking for Concurrent Operations on B-Trees》（L&Y 论文）提出。纯 B+Tree 在并发插入时，一次节点分裂会同时改动父节点，搜索者若恰好持有旧页指针就会读到被分裂走的 key；传统做法只能用粗粒度的树级锁或复杂的锁耦合（latch crabbing），并发度很低。

数据结构本身的推导与分裂场景示例见算法侧笔记 [B_Link_Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)，本篇聚焦它在数据库存储引擎中的落地。

## Two Key Properties

1. **右向兄弟指针**：每个节点（含内部节点与叶子）额外保存指向右侧兄弟的指针；
2. **high-key**：每个节点记录它（及其所有子孙）允许容纳的最大 key。

搜索时即使目标节点刚刚分裂、想要的 key 已被移到右兄弟，当前节点的 high-key 也会告诉搜索者"key 超出我的范围"，顺着右兄弟指针继续走即可，不会读到错误结果。

## Concurrency Protocol: Why Reads Can Be Lock-Free

- **搜索（读）**：自根向下，每层至多拿一个节点的读闩（latch），拿到子节点闩后立即释放；遇到分裂就沿右链横移。极端情况下读甚至可以不加闩，靠页面的一致性（页面版本/CRC）重试。
- **插入（写）**：沿路径**只加写闩**（不必像标准 lock-coupling 那样同时持有三层锁），先查安全节点（不会溢出的节点）再向下，分裂时先把新右兄弟写好、再原子地把分隔 key 插到父节点。右链 + high-key 保证这段"分裂已发生、父节点尚未更新"的窗口内，读操作依然能走到正确页面。
- 节点删除/合并更复杂，多数引擎选择不立刻合并（只做"惰性删除"，后台再重整），避免反向移动带来的加锁复杂度。

> latch vs lock：这里保护的是内存中页面物理一致性的短生命周期 **latch**（闩，spinlock/mutex），不是事务语义上的 **lock**（行锁、间隙锁）。二者对照见 [MySQL 锁](/docs/CS/DB/MySQL/lock.md)。

## Each Engine Implementation

| 系统 | B+Tree 并发方案 |
|------|----------------|
| PostgreSQL nbtree | 采用 L&Y 方案，右兄弟指针 + high-key；PG 8.3 后优化为只缓存最小锁计数、VACUUM 安全剪枝 |
| InnoDB | 基于 B-Link 思想的 B+Tree，用 `sync rw_lock` + 自适应哈希（AHI）；页分裂时先分配新页再在父节点插入 |
| WiredTiger（MongoDB） | page  reconciliation + hazard pointer，读不阻塞写 |
| Bw-Tree（SQL Server Hekaton/无锁） | 取消 latch，用 delta chain + mapping table，是 B-Link 的无闩化演进 |

## Recovery (ARIES Perspective)

分裂必须是**可重做（redo）且可补偿（undo）**的物理日志操作：典型顺序是先记录"分配新页 + 设置右链/high-key"的日志并强制刷盘，再更新父节点。崩溃恢复时，如果父节点的插入丢了，右链结构仍然完整——后续搜索与插入会沿右链找到新页，并由插入逻辑补做父节点分隔（结构提交，structure commit）。这是 B-Link 结构对崩溃恢复友好的核心：中间状态天然一致。

## Limitations

- 右链只朝右：搜索者可以追赶"向右分裂"，但无法处理"向左合并"，因此删除合并仍是难点；
- 高并发热点页（如自增主键的最右叶子）仍会串行化，实践中常用前缀反转、hash 分区索引缓解；
- B-Link 解决的是单机多核并发，分布式 B+Tree（如 [OceanBase](/docs/CS/DB/OceanBase.md) 的合并树）需要额外处理跨节点的分裂与路由。

## Links

- [B_Link_Tree（算法推导）](/docs/CS/Algorithms/tree/B_Link_Tree.md)
- [B-Tree（MySQL）](/docs/CS/DB/MySQL/B-Tree.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)

## References

1. [Lehman & Yao, Efficient Locking for Concurrent Operations on B-Trees (1981)](https://dl.acm.org/doi/10.1145/319628.319636)
