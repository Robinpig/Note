## Introduction

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2`（`storage/innobase/include/dict0mem.h`、`include/btr0btr.h`、`btr/btr0cur.cc`） |
| 次要兼容目标 | MySQL 8.4.x LTS |
| 已停止支持 | MySQL 8.0（EOL **2026-04-30**）、MySQL 5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

> [!NOTE]
> 本篇正文按版本演进顺序写：`The 5.6 Implementation` / `The 5.7 Additions` / `The 8.0 Read Path` 三节是**旧版本的历史脉络**，保留它们是为了理解「为什么现在长这样」；当前行为以最后一节 [Current Implementation In MySQL 9.7](/docs/CS/DB/MySQL/B-Tree.md?id=current-implementation-in-mysql-97) 为准。本目录的版本坐标与勘误见 [Version Migration](/docs/CS/DB/MySQL/Version_Migration.md)。

在InnoDB 的实现中, btree 主要有两种lock: index lock 和 page lock

index lock 就是整个Index 的lock, 具体在代码里面就是 dict_index->lock

page lock 就是我们在btree 里面每一个page 的变量里面都会有的 lock





## The 5.6 Implementation

在5.6 的实现里面比较简单,btree latch 大概是这样的流程



1. 如果是一个查询请求

- 那么首先把btree index->lock  S LOCK
- 然后直到找到 [leaf node](https://zhida.zhihu.com/search?content_id=121775800&content_type=Article&match_order=1&q=leaf+node&zhida_source=entity)

-  以后, 对leaft node 也是 S LOCK, 然后把index-> lock 放开

1. 如果是一个修改leaf page 请求

- 同样把btree index-> lock  S LOCK
- 然后直到找到leaf node 以后, 对leaf node 执行 X LOCK, 因为需要修改这个page. 然后把index->lock 放开.   到这里又分两种场景了, 对于这个page 的修改是否会引起 btree 的变化
  - 如果不会, 那么很好, 对leaf node 执行了X LOCK 以后, 修改完数据返回就可以
  - 如果会, 那么需要执行悲观插入操作, 重新遍历btree. 
    对btree inex 加X LOCK, 执行btr_cur_search_to_nth_level 到指定的page. 
    因为leaft node 修改, 可能导致整个沿着leaf node 到root node 的btree 都会随着修改, 因此必须让其他的线程不能访问到,  因此需要整个btree 加X LOCK, 那么其他任何的查询请求都不能访问了, 并且加了index X LOCK 以后, 进行record  插入到page, 甚至可能导致上一个Level 的page 也需要改变, 这里需要从磁盘中读取数据, 因此可能有磁盘IO, 这就导致了加X  LOCK 可能需要很长一段时间, 这段时间sread 相关的操作就都不可访问了
    这里具体的代码在 row_ins_clust_index_entry
    首先尝试乐观的插入操作
    err = row_ins_clust_index_entry_low(  0, BTR_MODIFY_LEAF, index, n_uniq, entry, n_ext, thr,  &page_no, &modify_clock);
    然后这里如果插入失败, 再尝试悲观的插入操作, 
    return(row_ins_clust_index_entry_low(  0, BTR_MODIFY_TREE, index, n_uniq, entry, n_ext, thr,  &page_no, &modify_clock));
    从这里可以看到, 唯一的区别在于这里latch_mode = BTR_MODIFY_LEAF 或者 BTR_MODIFY_TREE.  并且由于btr_cur_search_to_nth_level 是在函数 row_ins_clust_index_entry_low 执行,  那么也就是尝试了乐观操作失败以后, 重新进行悲观插入的时候, 需要重新遍历btree



5.6 里面只有对整个btree  的index lock,  以及在btree 上面的leaf node page 会有lock, 但是btree 上面non-leaf node 并没有 lock.

这样的实现带来的好处是代码实现非常简单, 但是缺点也很明显由于在SMO 操作的过程中, 读取操作也是无法进行的, 并且SMO 操作过程可能有IO 操作, 带来的性能抖动非常明显, 我们在线上也经常观察到这样的现象.



## The 5.7 Additions

5.7 就引入两个改动

1. 引入了sx lock
2. 引入了non-leaf page lock



 SX Lock 在index lock 和 page lock 的时候都可能用到.

SX Lock 是和 S LOCK 不冲突, 但是和 X LOCK 冲突的, SX LOCK 和 SX LOCK 之间是冲突的.

SX LOCK 的意思我有意向要修改这个保护的范围, 但是现在还没开始修改, 所以还可以继续访问, 但是要修改以后, 就无法访问了.  因为我有意向要修改, 因此不能允许其他的改动发生, 因此和 X LOCK 是冲突的.

**目前主要用途因为index SX lock 和 S LOCK 不冲突, 因此悲观insert 改成index SX LOCK 以后, 可以允许用户的read/乐观写入**

SX LOCK 的引入由这个 WL 加入 [WL#6363](https://dev.mysql.com/worklog/task/?id=6363)

可以认为 SX LOCK 的引入是为了对读操作更加的优化,  SX lock 是和 X lock 冲突, 但是是和 S lock 不冲突的, 将以前需要加X lock 的地方改成了SX lock, 因此对读取更加友好了

**引入non-leaf page lock**

其实这也是大部分[商业数据库](https://zhida.zhihu.com/search?content_id=121775800&content_type=Article&match_order=1&q=商业数据库&zhida_source=entity)

都是这样, 除了leaf page 有page lock, non-leaf page 也有page lock.

主要的想法还是 Latch coupling, 在从上到下遍历btree 的过程中, 持有了[子节点](https://zhida.zhihu.com/search?content_id=121775800&content_type=Article&match_order=1&q=子节点&zhida_source=entity)

的page lock 以后, 再把父节点的page lock 放开, 这样就可以尽可能的减少latch 的范围. 这样的实现就必须保证non-leaf page 也必须持有page lock.

不过这里InnoDB 并未把index->lock 完全去掉, 这就导致了从 5.7 一直到 9.7，同一时刻仍然只有同时有一个 BTR_MODIFY_TREE 操作在进行, 从而在激烈并发修改btree 结构的时候, 性能下降明显.

这个约束的源码级证据在 9.7 依然存在：`btr_cur_latch_leaves()` 的 `BTR_MODIFY_TREE` 分支断言 index 的 `rw_lock` 必须已被 X 或 SX 持有（见 [Current Implementation In MySQL 9.7](/docs/CS/DB/MySQL/B-Tree.md?id=current-implementation-in-mysql-97)）。





在5.6 里面, 最差的情况是如果要修改一个btree leaf page, 这个btree leaf page 可能会触发btree  结构的改变, 那么这个时候就需要加一整个index X LOCK, 但是其实我们知道有可能这个改动只影响当前以及上一个level 的btree  page, 如果我们能够缩小LOCK 的范围, 那么肯定对并发是有帮助的



## The 8.0 Read Path

到了8.0

1. 如果是一个查询请求

- 那么首先把btree index->lock  S LOCK
- 然后沿着搜索btree 路径, 遇到的non-leaf node page 都加 S LOCK
- 然后直到找到 leaf node 以后, 对leaft node page 也是 S LOCK, 然后把index-> lock 放开


## Latch Coupling And SMO Sub-tree

在 B-tree 索引的并发访问控制上，通常利用物理锁 latch 来实现互斥，在共享数据访问结束后就可以立即释放。这区别于事务系统的逻辑锁 lock，事务锁需要在事务提交时释放，通常会持续较长时间


5.6 InnoDB 解决 B-tree 并发控制两个问题的方法：
1. page 并发读写/写写冲突：index latch 解决 non-leaf page 的冲突，page latch 解决 leaf page 的冲突；
2. B-tree 结构并发读写冲突：SMO 持有 index X latch，限制整个 B-tree 的访问；
   5.6 版本虽然使用先乐观写的方法，但是 index latch 在频繁并发写入的场景仍然成为明显的性能瓶颈。问题在于 SMO 持有 index X latch 后会进行一系列操作：分配 new page、移动数据、修改多个 page 的关联，这个耗时的过程中其它任何线程都无法访问 B-tree。
   更坏的情况是，大表的数据页无法被 buffer pool 容纳，SMO 过程中需要多个 read IO 获取相关节点，这进一步增加了 SMO 的耗时，在 IO 延迟大的云存储环境下，这个问题更是雪上加霜。
   因此 InnoDB index 上的并发能力是一个主要的系统瓶颈，一个长久以来的说法是，mysql 大表性能不好，表越大越慢，需要进行分区等操作。由于 index latch 的存在，单表上无法获得线性扩展能力

5.7 之后 InnoDB 就采用了 latch coupling + SMO latch sub-tree 的方法，将 SMO 锁范围降低到 sub-tree 级别，因此 B-tree 内部节点需要 加 page 读写锁进行并发控制，这解决了问题 1。对于问题 2，读线程 latch coupling 不会允许并发修改父子节点关系。
latch sub-tree 相比于 5.6 版本直接锁 B-tree，在并发读写场景下性能会好很多。不过 InnoDB 在实现这个方法时，也存在一定问题：

latch sub-tree 导致的单一操作加锁范围大：
 - SMO 线程：SMO 下降过程中无法精确判断 latch sub-tree 的最小范围，因此会充分加锁保证正确性，对于 B-tree 3-4 层的结构很容易锁住 root 节点，这就和 latch entire tree 没有差别了；
 - 乐观线程：latch coupling 没有实现最多持有 2 个节点。SMO 只锁住了 sub-tree 的一条路径，而 B-tree 存在节点左右指针，可能需要修改 uncle 节点。不能让 latch coupling 下降走到 sub-tree 内部形成死锁，需要在 sub-tree 根节点做互斥，因此下降路径上的所有节点都要保持 S latch，直到拿到 leaf page 后才释放上层所有 page latch；
 - 不允许 SMO 线程并发：SMO 线程持有 index SX latch，导致并发插入场景下 index latch 成为系统瓶颈。如果将这个限制放开，多个 SMO 线程并发进入 B-tree，每个线程要获取多个 page latch，会导致设计死锁避免的加锁规则异常困难



## Recap Of Latch Basics

在InnoDB 的实现中, btree 主要有两种lock: index lock 和 page lock
index lock 就是整个Index 的 rw_lock, 具体在代码里面就是 dict_index->lock
page lock 就是我们在btree 里面每一个page 的变量里面都会有的 lock
当我们说btree lock的时候, 一般同时包含 index lock 和 page lock 来一起实现


5.7以后引入
主要有这两个改动
1. 引入了sx lock
2. 引入了non-leaf page lock


## Current Implementation In MySQL 9.7

上面几节的结论在 9.7 一句话概括：**`index->lock` 没有被删，`RW_SX_LATCH` 仍是它的核心用法，变的是「申请 latch 时能把意图说得多细」。**

### index lock Is Still There

`dict_index_t::lock` 位于 `include/dict0mem.h`：

```c++
  /** read-write lock protecting the upper levels of the index tree */
  rw_lock_t lock;
```

注释 `read-write lock protecting the upper levels of the index tree` 就是它的职责边界：**只保护上层（非叶子）节点**，叶子层由 page latch 负责。这也解释了为什么 5.6 时代「一次 SMO 锁住整棵树」在后来变得可以接受——真正长期被保护的只剩 root 附近几层。

`RW_SX_LATCH` 也仍在使用，例如 `include/btr0btr.h` 里 `btr_node_ptr_get_child()` 的 latch 类型默认值：

```c++
buf_block_t *btr_node_ptr_get_child(const rec_t *node_ptr, dict_index_t *index,
                                    const ulint *offsets, mtr_t *mtr,
                                    rw_lock_type_t type = RW_SX_LATCH);
```

沿树下探取子节点时默认就是 SX：既允许读者继续 S latch 上层，又排除掉其它 SMO 与整树 X。**SX 是 InnoDB 特有的「共享但排斥 SX 和 X」的意图锁**，5.7 之后并发能力的提升全部建立在这一点上。

### Intention Flags That Narrow The Latch Range

9.7 里可以把「我到底要干什么」直接编码进 latch_mode 的 flag（`include/btr0btr.h`），让被调方少加一把 latch：

```c++
/** In the case of BTR_SEARCH_LEAF or BTR_MODIFY_LEAF, the caller is
already holding an S latch on the index tree */
constexpr size_t BTR_ALREADY_S_LATCHED = 16384;

/** In the case of BTR_MODIFY_TREE, the caller specifies the intention
to insert record only. It is used to optimize block->lock range.*/
constexpr size_t BTR_LATCH_FOR_INSERT = 32768;

/** In the case of BTR_MODIFY_TREE, the caller specifies the intention
to delete record only. It is used to optimize block->lock range.*/
constexpr size_t BTR_LATCH_FOR_DELETE = 65536;
```

- `BTR_LATCH_FOR_INSERT` / `BTR_LATCH_FOR_DELETE`：走 `BTR_MODIFY_TREE` 时告诉被调方「我只插入」或「我只删除」，据此缩小叶子层的 `block->lock` 加锁范围——不必像过去那样为了正确性把左右兄弟一起 X latch。这正是针对上文「latch sub-tree 加锁范围过大」问题的修补。
- `BTR_ALREADY_S_LATCHED`：调用方已经持有 index 的 S latch 时用它跳过重复加锁，避免同一把 `index->lock` 被重入。

真正执行叶子层加锁的是 `btr_cur_latch_leaves()`（`btr/btr0cur.cc`）：

```c++
/** Latches the leaf page or pages requested.
@param[in]      block           Leaf page where the search converged
@param[in]      page_id         Page id of the leaf
@param[in]      page_size       Page size
@param[in]      latch_mode      BTR_SEARCH_LEAF, ...
@param[in]      cursor          Cursor
@param[in]      mtr             Mini-transaction
@return blocks and savepoints which actually latched. */
btr_latch_leaves_t btr_cur_latch_leaves(buf_block_t *block,
                                        const page_id_t &page_id,
                                        const page_size_t &page_size,
                                        ulint latch_mode, btr_cur_t *cursor,
                                        mtr_t *mtr) {
```

`case BTR_MODIFY_TREE:` 分支开头那条断言，就是「同一时刻只有一个 SMO」这个约束在 9.7 仍然成立的证据：

```c++
    case BTR_MODIFY_TREE:
      /* It is exclusive for other operations which calls
      btr_page_set_prev() */
      ut_ad(mtr_memo_contains_flagged(mtr, dict_index_get_lock(cursor->index),
                                      MTR_MEMO_X_LOCK | MTR_MEMO_SX_LOCK) ||
            cursor->index->table->is_intrinsic());
      /* x-latch also siblings from left to right */
```

也就是说：进 `BTR_MODIFY_TREE` 必须已经持有 index 的 X 或 SX latch，兄弟页再按插入 / 删除的意图补 X latch。函数内部另有 `btr_intention_t`（`BTR_INTENTION_DELETE` / `BTR_INTENTION_BOTH` / `BTR_INTENTION_INSERT`）表达「要往哪边走」，与上面的 `BTR_LATCH_FOR_*` flag 配合决定实际 latch 的邻居范围。

### Side Effects Of Holding index X Latch Less Often

`btr/btr0cur.cc` 里留着一段很宝贵的注释，说明这次「index->lock 可扩展性改造」唯一观察到的性能回退来自 history list 变长——原来 index X latch 顺带起到了给 purge 预留 free block 与读 IO 带宽的作用，收窄之后这层隐式优先级没了：

```c++
/** For the index->lock scalability improvement, only possibility of clear
performance regression observed was caused by grown huge history list length.
That is because the exclusive use of index->lock also worked as reserving
free blocks and read IO bandwidth with priority. To avoid huge glowing history
list as same level with previous implementation, prioritizes pessimistic tree
operations by purge as the previous, when it seems to be growing huge.

 Experimentally, the history list length starts to affect to performance
throughput clearly from about 100000. */
constexpr uint32_t BTR_CUR_FINE_HISTORY_LENGTH = 100000;
```

所以 9.7 的做法是：当 history list 长度接近 `100000` 这个实测门槛时，显式让 purge 优先执行悲观树操作，把过去靠 index X latch「顺带」拿到的效果补回来。这也是读 B-tree 并发时必须和 undo / purge 一起看的原因。


## Links

- [Lock](/docs/CS/DB/MySQL/lock.md)
- [Index](/docs/CS/DB/MySQL/Index.md)
- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Memory](/docs/CS/DB/MySQL/memory.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)


## References

1. [A Survey of B-Tree Locking Techniques](https://15721.courses.cs.cmu.edu/spring2019/papers/06-indexes/a16-graefe.pdf)
2. [MySQL Worklog WL#6363](https://dev.mysql.com/worklog/task/?id=6363)
