## Introduction



在InnoDB 的实现中, btree 主要有两种lock: index lock 和 page lock

index lock 就是整个Index 的lock, 具体在代码里面就是 dict_index->lock

page lock 就是我们在btree 里面每一个page 的变量里面都会有的 lock





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



5.7 就引入两个改动

1. 引入了sx lock
2. 引入了non-leaf page lock



 SX Lock 在index lock 和 page lock 的时候都可能用到.

SX Lock 是和 S LOCK 不冲突, 但是和 X LOCK 冲突的, SX LOCK 和 SX LOCK 之间是冲突的.

SX LOCK 的意思我有意向要修改这个保护的范围, 但是现在还没开始修改, 所以还可以继续访问, 但是要修改以后, 就无法访问了.  因为我有意向要修改, 因此不能允许其他的改动发生, 因此和 X LOCK 是冲突的.

**目前主要用途因为index SX lock 和 S LOCK 不冲突, 因此悲观insert 改成index SX LOCK 以后, 可以允许用户的read/乐观写入**

SX LOCK 的引入由这个 WL 加入 [WL#6363](https://link.zhihu.com/?target=https%3A//dev.mysql.com/worklog/task/%3Fid%3D6363)

可以认为 SX LOCK 的引入是为了对读操作更加的优化,  SX lock 是和 X lock 冲突, 但是是和 S lock 不冲突的, 将以前需要加X lock 的地方改成了SX lock, 因此对读取更加友好了

**引入non-leaf page lock**

其实这也是大部分[商业数据库](https://zhida.zhihu.com/search?content_id=121775800&content_type=Article&match_order=1&q=商业数据库&zhida_source=entity)

都是这样, 除了leaf page 有page lock, non-leaf page 也有page lock.

主要的想法还是 Latch coupling, 在从上到下遍历btree 的过程中, 持有了[子节点](https://zhida.zhihu.com/search?content_id=121775800&content_type=Article&match_order=1&q=子节点&zhida_source=entity)

的page lock 以后, 再把父节点的page lock 放开, 这样就可以尽可能的减少latch 的范围. 这样的实现就必须保证non-leaf page 也必须持有page lock.

不过这里InnoDB 并未把index->lock 完全去掉, 这就导致了现在InnoDB 同一时刻仍然只有同时有一个 BTR_MODIFY_TREE 操作在进行, 从而在激烈并发修改btree 结构的时候, 性能下降明显.





在5.6 里面, 最差的情况是如果要修改一个btree leaf page, 这个btree leaf page 可能会触发btree  结构的改变, 那么这个时候就需要加一整个index X LOCK, 但是其实我们知道有可能这个改动只影响当前以及上一个level 的btree  page, 如果我们能够缩小LOCK 的范围, 那么肯定对并发是有帮助的



到了8.0

1. 如果是一个查询请求

- 那么首先把btree index->lock  S LOCK
- 然后沿着搜索btree 路径, 遇到的non-leaf node page 都加 S LOCK
- 然后直到找到 leaf node 以后, 对leaft node page 也是 S LOCK, 然后把index-> lock 放开











## Links



