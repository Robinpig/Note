## Introduction

由于 B 树已经存在了很长时间，多年来开发了许多优化措施也就不足为奇了。
仅举几例：

- 一些数据库（如 LMDB）使用写时复制方案，而不是覆盖页面和维护 WAL 进行崩溃恢复。
  修改后的页面会写入不同的位置，并在树中创建父页面的新版本，指向新位置。这种方法也适用于并发控制。
- 我们可以在页面中通过不存储整个键，而是缩写键来节省空间。
  特别是在树的内部节点中，键只需要提供足够的信息来充当键范围之间的边界。
  在页面中放入更多键可以使树具有更高的分支因子，从而减少层级。
- 通常，页面可以位于磁盘上的任何位置；没有要求具有相近键范围的页面在磁盘上相邻。
  如果查询需要按键的排序顺序扫描键范围的大部分，这种逐页布局可能效率低下，因为读取的每个页面可能都需要磁盘寻道。
  因此，许多 B 树实现试图将树布局为叶子页按顺序出现在磁盘上。
  然而，随着树的增长，维护这种顺序很困难。
  相比之下，由于 LSM 树在合并期间会一次性重写存储的大段内容，因此它们更容易在磁盘上保持连续的键彼此靠近。
- 树中添加了额外的指针。
  例如，每个叶子页可能有指向其左右兄弟页的引用，这样可以在不返回到父页的情况下按键顺序扫描。
- B 树变体如分形树借鉴了一些日志结构化思想来减少磁盘寻道（它们与分形无关）。

B 树是排序的：B 树节点内部的键按顺序存储。
因此，要定位搜索的键，我们可以使用像二分查找这样的算法。
这也意味着 B 树中的查找具有对数复杂度。例如，在 40 亿（4×10^9）个元素中查找一个搜索键大约需要 32 次比较。
如果每次比较都需要一次磁盘寻道，那将大大减慢我们的速度，但由于 B 树节点存储数十甚至数百个项目，我们只需要在每个层级进行一次磁盘寻道。

B 树由多个节点组成。每个节点最多持有 N 个键和 N+1 个指向子节点的指针。这些节点逻辑上分为三组：

- 根节点<br>没有父节点，是树的顶层。
- 叶子节点<br>是最底层节点，没有子节点。
- 内部节点<br>是所有其他节点，连接根节点和叶子节点。通常有多层内部节点。

这种层次结构如图 9 所示。

<div style="text-align: center;">

![B-Tree node hierarchy](../img/B-Tree-Hierarchy.png)

</div>

<p style="text-align: center;">
Fig.7. B 树节点层次结构。
</p>

由于 B 树是一种页面组织技术（即用于组织和导航固定大小的页面），我们通常互换使用术语节点和页面。

节点容量与其实际持有的键数量之间的关系称为占用率。

B 树的特征在于其扇出：每个节点中存储的键数量。更高的扇出有助于摊销保持树平衡所需的结构变化成本，并通过在单个块或多个连续块中存储键和指向子节点的指针来减少寻道次数。平衡操作（即分裂和合并）在节点满或几乎为空时触发。

> [!NOTE]
> 我们使用术语 B 树作为一系列数据结构的统称，这些结构共享全部或大部分所述的属性。所描述的数据结构的更准确名称是 B+ 树。[KNUTH98] 将高扇出的树称为多叉树。
>
> B 树允许在任何层级存储值：根节点、内部节点和叶子节点。B+ 树仅在叶子节点存储值。内部节点仅存储分隔键，用于引导搜索算法到叶子层级上关联的值。
>
> 由于 B+ 树的值仅存储在叶子层级，所有操作（插入、更新、删除和检索数据记录）仅影响叶子节点，仅在分裂和合并期间传播到更高层级。
>
> B+ 树已广泛使用，我们将其称为 B 树，与其他关于该主题的文献一样。例如，MySQL InnoDB 将其 B+ 树实现称为 B-tree。

### Separator Keys

存储在 B 树节点中的键称为索引条目、分隔键或分隔单元格。它们将树分割成子树（也称为分支或子范围），持有相应的键范围。键按排序顺序存储以允许二分查找。通过定位键并沿着从高层到低层的相应指针找到子树。

节点中的第一个指针指向持有小于第一个键的项目的子树，最后一个指针指向持有大于或等于最后一个键的项目的子树。其他指针引用两个键之间的子树：Ki-1 ≤ Ks < Ki，其中 K 是一组键，Ks 是属于子树的键。图 2-10 显示了这些不变性。

<div style="text-align: center;">

![How separator keys split a tree into subtrees](../img/Separator-Keys.png)

</div>

<p style="text-align: center;">
Fig.7. 分隔键如何将树分割成子树。
</p>

一些 B 树变体也有兄弟节点指针，通常在叶子层级，以简化范围扫描。这些指针有助于避免返回到父节点来查找下一个兄弟节点。一些实现具有双向指针，在叶子层级形成双向链表，这使得反向迭代成为可能。

B 树的不同之处在于，它们不是从上到下构建（如二叉搜索树），而是反过来——从下到上构建。叶子节点数量增长，从而增加内部节点数量和树的高度。

由于 B 树在节点内部为未来的插入和更新保留额外空间，树的存储利用率可能低至 50%，但通常要高得多。更高的占用率不会对 B 树性能产生负面影响。

### B-Tree Lookup Complexity

B 树查找复杂度可以从两个角度来看：块传输的数量和查找过程中进行的比较次数。

在传输次数方面，对数的底是 N（每个节点的键数量）。每个新层级上的节点数是 K 倍，而跟随子指针将搜索空间缩小 N 倍。在查找过程中，最多寻址 $\log_K M$（其中 M 是 B 树中的项目总数）个页面以找到搜索的键。在根到叶子的路径上必须跟随的子指针数量也等于层级数，即树的高度 h。

从比较次数的角度来看，对数的底是 2，因为每个节点内部的键搜索使用二分查找。每次比较将搜索空间减半，因此复杂度为 $\log_2 M$。
在教科书和文章中，B 树查找复杂度通常记为 $\log M$。

要在 B 树中查找项目，我们必须执行一次从根到叶子的遍历。搜索的目标是找到搜索的键或其前驱。查找精确匹配用于点查询、更新和删除；查找其前驱对范围扫描和插入很有用。

算法从根开始，执行二分查找，将搜索键与根节点中存储的键进行比较，直到找到第一个大于搜索值的分隔键。这定位了搜索的子树。正如我们之前讨论的，索引键将树分割成相邻两个键之间有边界的子树。一旦找到子树，我们就跟随其对应的指针，并继续相同的搜索过程（定位分隔键，跟随指针），直到到达目标叶子节点，在那里我们要么找到搜索的键，要么通过定位其前驱得出结论它不存在。

在每个层级上，我们获得树的更详细视图：我们从最粗略的层级（树的根）开始，下降到下一层级，其中键代表更精确、更详细的范围，直到最终到达叶子节点，数据记录位于其中。

在点查询期间，搜索在找到或未找到搜索的键后完成。在范围扫描期间，迭代从找到的最接近的键值对开始，并通过跟随兄弟指针继续，直到达到范围的末尾或范围谓词耗尽。

### Node Splits and Merges

要向 B 树中插入值，我们首先必须定位目标叶子节点并找到插入点。定位叶子节点后，键和值被追加到其中。B 树中的更新通过使用查找算法定位目标叶子节点并将新值与现有键关联来工作。

如果目标节点没有足够的可用空间，我们称该节点已溢出 [NICHOLS66]，必须分裂成两个以容纳新数据。更准确地说，如果满足以下条件则节点分裂：
- 对于叶子节点：如果节点最多可容纳 N 个键值对，而插入一个更多键值对使其超过最大容量 N。
- 对于非叶子节点：如果节点最多可容纳 N + 1 个指针，而插入一个更多指针使其超过最大容量 N + 1。

分裂通过分配新节点，将一半元素从分裂节点转移到新节点，并将其第一个键和指针添加到父节点来完成。在这种情况下，我们说键被提升了。执行分裂的索引称为分裂点（也称为中点）。分裂点之后的所有元素（在非叶子节点分裂的情况下包括分裂点）被转移到新创建的兄弟节点，其余元素保留在分裂节点中。

如果父节点已满且没有空间容纳提升的键和指向新创建节点的指针，则它也必须进行分裂。此操作可能递归传播一直到根。

一旦树达到其容量（即分裂一直传播到根），我们必须分裂根节点。当根节点分裂时，会分配一个持有分裂点键的新根。旧根（现在只持有半数条目）与其新创建的兄弟节点一起降级到下一层级，使树的高度增加 1。当根节点分裂并分配新根，或当两个节点合并形成新根时，树的高度发生变化。在叶子节点和内部节点层级，树只进行水平增长。

总结一下，节点分裂分四步完成：

1. 分配一个新节点。
2. 将一半元素从分裂节点复制到新节点。
3. 将新元素放入相应的节点。
4. 在分裂节点的父节点中，添加一个分隔键和一个指向新节点的指针。

删除也是通过首先定位目标叶子节点来完成的。定位叶子节点后，键及其关联的值被移除。

如果相邻节点的值太少（即它们的占用率低于阈值），则兄弟节点会被合并。这种情况称为下溢。
[BAYER72] 描述了两种下溢情况：如果两个相邻节点有共同的父节点且它们的内容可以放入一个节点，则它们的内容应合并（拼接）；
如果它们的内容不能放入一个节点，则在它们之间重新分配键以恢复平衡。
更准确地说，如果满足以下条件则合并两个节点：

- 对于叶子节点：如果一个节点最多可容纳 N 个键值对，且两个相邻节点中键值对的总数小于或等于 N。
- 对于非叶子节点：如果一个节点最多可容纳 N + 1 个指针，且两个相邻节点中指针的总数小于或等于 N + 1。

总结一下，假设元素已被移除，节点合并分三步完成：

1. 将所有元素从右节点复制到左节点。
2. 从父节点移除右节点指针（或在非叶子节点合并的情况下降级）。
3. 移除右节点。

B 树中常用来减少分裂和合并数量的技术之一是再平衡。

## Rebalancing

一些 B 树实现尝试推迟分裂和合并操作，通过在层级内重新平衡元素来摊销成本，或者在最终执行分裂或合并之前，尽可能长地将元素从较满的节点移动到较空的节点。这有助于提高节点占用率，并可能以减少树中的层级数，尽管再平衡的维护成本可能更高。

负载平衡可以在插入和删除操作期间执行。
为了提高空间利用率，不是在溢出时分裂节点，而是可以将一些元素转移到某个兄弟节点，为插入腾出空间。类似地，在删除期间，可以选择从相邻节点移动一些元素，而不是合并兄弟节点，以确保节点至少半满。

B* 树持续在相邻节点之间分配数据，直到两个兄弟节点都满。
然后，该算法不是将一个节点分裂成两个半空的节点，而是将两个节点分裂成三个节点，每个节点三分之二满。
SQLite 在其实现中使用了这种变体。
这种方法通过推迟分裂来改善平均占用率，但需要额外的跟踪和平衡逻辑。
更高的利用率也意味着更高效的搜索，因为树的高度更小，在通往搜索叶子节点的路径上需要遍历的页面更少。

图 4-9 显示了在相邻节点之间分配元素，其中左兄弟比右兄弟包含更多元素。
元素从较满的节点移动到较空的节点。
由于平衡会改变兄弟节点的最小/最大不变量，我们必须更新父节点中的键和指针以保持它。

<div style="text-align: center;">

![B-Tree balancing](../img/B-Tree-Balancing.png)

</div>

<p style="text-align: center;">
Fig.7. B 树平衡：在较满的节点和较空的节点之间分配元素。
</p>

每个内部节点包含指向子节点的指针 p1, p2, ..., pm，以及值 k1, k2, ..., km-1，分别表示子树 p2, p3, ..., pm 中的最小键。
当然，其中一些指针可能为 NULL，相应的 ki 则未定义。对于每个节点，子树 p1 中的所有键都小于子树 p2 中的键，以此类推。
叶子节点包含所有实际数据，要么是键本身，要么是指向包含键的记录的指针。为简化示例，我们假设前者。
B 树有各种定义，大多在细节上略有不同，但这是其中一种流行的形式。
我们还要（暂时）坚持叶子节点中的键数量也在 m/2 和 m 之间。

4 阶 B 树更广为人知的名称是 2-3-4 树，3 阶 B 树称为 2-3 树。

对于一般的 m 阶 B 树，当插入一个键时，唯一的困难出现在要接受该键的节点已经有 m 个键的情况下。
这个键给节点带来了 m+1 个键，我们可以将其分裂成两个节点，分别包含 (m+1)/2 和 (m+1)/2 个键。
由于这给父节点增加了一个额外节点，我们必须检查父节点是否可以接受这个节点，如果父节点已经有 m 个子节点，则分裂父节点。
我们重复这个过程，直到找到一个子节点少于 m 的父节点。如果分裂了根节点，则创建一个具有两个子节点的新根。

B 树的深度最多为 $\log_{[M/2]}{N}$。

B 树的真正用途在于数据库系统，其中树保存在物理磁盘上而不是主存中。
访问磁盘通常比任何主存操作慢几个数量级。
如果我们使用 m 阶 B 树，则磁盘访问次数为 O(log_m n)。
尽管每次磁盘访问需要 O(log m) 的开销来确定分支方向，但执行此计算的时间通常远小于读取一个内存块的时间，因此可以认为无关紧要（只要 m 选择合理）。
即使执行更新并且每个节点需要 O(m) 的计算时间，这通常也不显著。
m 的值被选择为使内部节点恰好能放入一个磁盘块的最大值，通常在 32 ≤ m ≤ 256 范围内。
存储在叶子节点中的最大元素数量被选择为，如果叶子节点满了，它可以恰好放入一个块中。
这意味着一条记录总是可以在很少的磁盘访问中找到，因为典型的 B 树深度只有 2 或 3，并且根（可能还有第一层）可以保留在主存中。

分析表明 B 树将会是 ln 2 = 69% 满。
如果当树获得第 (m+1) 个条目时，不是总是分裂节点，而是搜索一个可以接收额外子节点的兄弟节点，可以获得更好的空间利用率。

## Links

- [Trees](/docs/CS/Algorithms/tree/tree.md?id=B-Trees)

## References

1. [Performance of B+ tree concurrency control algorithms](https://minds.wisconsin.edu/bitstream/handle/1793/59428/TR999.pdf)
2. [Concurrency of operations on B*-trees](https://pdf.sciencedirectassets.com/272574/1-s2.0-S0022000000X01225/1-s2.0-0022000086900218/main.pdf?X-Amz-Security-Token=IQoJb3JpZ2luX2VjEC0aCXVzLWVhc3QtMSJHMEUCIQD27XDmuGxMs4yImd%2BILjF%2FH0sGVfcpKd1VwLQx127mNAIgFoQKO9Q%2BRR%2FTzZl8ydedJDta2o%2FNM9i4uz6x1%2Fa0YuIqvAUI5v%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FARAFGgwwNTkwMDM1NDY4NjUiDHVpWrAT4qq9czzHGyqQBSH2oyVb3Q4luWBlpSGzpgzG%2BBUhoe4qiu%2FeDDFwUzo4KXOTmGDMhE447UOWILfkc4khtVIQnNbOX7s96%2FT1sOig5GndnhS4CxSvGXLErW005%2BnMRTX3JsD8%2FdgM5d8lVXJ6bxb3azXcI6rcpI65kxHofRZyDUqhV4vKQHv3WI%2FqYqeqJPwowUl0NB0tVu9AANT0o4u%2BRo5tq1U3IxjWkPBIQB8wwMQAKPlvIffnRCh%2BPV2QEOwQXsxfhKQZdyVy1TNKDb3UaW7DqxCo9R9cda5h26OEklSY0vh9aC8fBVB5MXHxYm1tqkINmp766YelXzPZoN5C7U0aQ%2Fq9jdJdQtS1r%2B8NYggYeHcH36efPWCJkyYD3f58jSl1EoYl5dsuRA7xOrpUfGPvoSyzSRCtAZ97c7%2F%2Fmk%2B6MhuPxbN7MQLBLSStsj3RtsqQ6CuKdkPGtEaQlphPtiJphakc3i48JuaEZS%2F2wI8rnPq6g6fAVKQrW%2Fy4ZBenkez1U57M95JWeI7wWrI6GjWNhDnS5psDzjWD0fMSHWCUlhYrV4vYeiEQWFo3H7KztrwxtKJmdvTjAB%2FvFxQftzSCPRhnOvjuEh%2FFyivdjheEkw9I%2BB34kAcWj78IZXcZ4SfDVzQJ0uQqWNmVtST4zAd8GSmr7nao6HebirrCeHTYbccjLWuXE%2BzangbEKXSmRwkpkTBCkdhnvpWJpD3wI4HU%2B6iJTWPbcklsFV%2B0XOOseMHioTMLh7nM155vL3k0WVBDuP5A%2FwUr2%2B6k5ve%2F1zRQKFlnzsFzu%2FCqKMpRY86YRVX5i2vmabKoPNt2sFNzDxBbLXwVepUj5dLqv8PINYs4KkrCoC92vbiDakOFNBAZKlWaiGpw1W3wMLyQ9LoGOrEBaN2SJcZV607%2Fdy%2BR68F6v4%2FsRJ%2FZJXZ%2FFdZsJhT61ReR0jbjcYoj0YjtiIdFE2CayyI1azMF6rYGjo5Uox2zdXfZXtF%2FyffntM%2FbtyYr%2BCFxwtW8%2BfmZifbrzFXHUifdaHvdKdmlZqnoeVfiZIspghY9cJizJs8LPuigNMOkdUskKVMAMuHXAkfiDXRUZPZ%2BAdDP1ID2PrjyDG70QLh1h4nD687EwHqZjVMHPTz9h4nH&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=20241214T052608Z&X-Amz-SignedHeaders=host&X-Amz-Expires=300&X-Amz-Credential=ASIAQ3PHCVTY626EJEBG%2F20241214%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Signature=5efb467fb106a0147aa833ddbd817b1730ec1f8899a1d71d2699feac7426bc20&hash=1cf3663ad6d5c7847a2b1107e379f2e9e8a5e661de23a994a76624dd9d68e667&host=68042c943591013ac2b2430a89b270f6af2c76d8dfd086a07176afe7c76c2c61&pii=002200... (line truncated)
3. [Concurrent B-trees with Lock-free Techniques](http://www.cs.umanitoba.ca/~hacamero/Research/BtreeTechrpt2011.pdf)
4. [Efficient Locking for Concurrent Operations on B-Trees](https://www.cs.utexas.edu/users/dsb/cs386d/Readings/ConcurrencyControl/Lehman-Yao.pdf)
5. [A SYMMETRIC CONCURRENT B-TREE ALGORITHM](https://dl.acm.org/doi/pdf/10.5555/324493.324589)
6. [Concurrent Operations on B*-Trees with Overtaking](https://pdf.sciencedirectassets.com/272574/1-s2.0-S0022000000X01225/1-s2.0-0022000086900218/main.pdf?X-Amz-Security-Token=IQoJb3JpZ2luX2VjEFwaCXVzLWVhc3QtMSJGMEQCIFm5xr2dI6oRd8d7qWRHA%2BCTXjD%2FOP%2F1%2FMiJSmgrFNoqAiB2%2Bt0mUJjN2iGUJmZ6T2hnH5TiHeq8C6X99E9BbsYIIiqyBQhFEAUaDDA1OTAwMzU0Njg2NSIMw10qqP1Ui4JGzQGKKo8FKNxZE3OYkrU0S%2FlDw4YuIvh95hbcXUmDtwWTrZoB3bbbhbgPSR7Fszch9yxcEBdYY%2FdziADBYrUxAZHXINM%2FUaJY1DWvymm7Zyo1IQb7%2FU2g7WT6bI%2FMKtmtO3Nv%2FiqwvFzk75V5DyJbVXetMoSoHGKCF0f8zw0BgYjX2HrZgOfTYtgMHJboCWcJcCK9Lip%2BNwlu5RVoho35%2BT9LYge5dTRlmTb%2FU8qtJgGELm7%2Fmkxjlss3d%2BhBhhynLONX9GIXGuTF9fZb5CFjlqBcXYKDXHmrDOOA%2Fl8aqxsm6O48L9IZkmDWMps1czvxYC7fd46golEy06V5WssVvhY%2F30VGdTrsKKFafcaRVgigqCT9SZNiMkBPXdDAYWlzIXCAqPoY5KfY6t%2FE1uWkGfbSAFmqDWZ0Vqhb67eV3ejRpFn1af7eHQNvXOlIKn2PL5TOqtnNBezPBRYAvVOGBlIN1ovdDs3cQF8TJLI5wosV90UlM6vmikosS%2FzsyG8SznqR9DS7vY9DZj7k3NTgGbRBcmjmTB0zGyajvbhMnTJa4YwfxQJKwM2Q3WB2PugI6sPtMpiYK2vzBHL2CT42Wy%2Bjf4TgiZ73lRoEwRyDkSjhmfdUHNAVvb5mhA0iS%2FQ%2F4oZypax0SHkwqf%2BUx3pPcRi2PANEGdEuyuYeRwcZR%2FptzcGsDiq%2BPN7J3abz0UFq7SxASn17Dwqwz%2FHA24ziaxVQsmamfzMIe8Qwsa0s3cnbotWcrYyN5AWD9xnxLqabTW2uGeWf014F8Scu4%2F4v5kYdNMvkC1OZPWf8TvP2ucwdMIxb%2Fw0%2B%2F4iTDZCK5HRxn7%2Btf3OVAClJX%2Blmi%2Bxbe7KM3FTxLf8wir%2BxQg3mnHa8FT%2FIJjDL%2F%2B67BjqyAVytV4eY9XFMr6JIDsi56bGvyHCWDMezHkBXt%2FXzmLlX%2FSvhSifVRMAfJdNnPEGaR6TylZHTGAh9mP3Kz5TOqVTPqkQYQHSlbuNh4BDYPjgpMhK5B4kJUb%2BaJJ%2FoxuOTGw0iD%2F2LutVsoADAHBQjW1FnxP%2BnPW9WUuCa%2BJsX5sdUQpzcbeWv49DSItUzswzQ8Ru4CpZuibYWnKRkp%2F2ljvfOQQIp2rZ8phgSX4wKG3Sf6Go%3D&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=20250106T123339Z&X-Amz-SignedHeaders=host&X-Amz-Expires=300&X-Amz-Credential=ASIAQ3PHCVTY6UFWTID2%2F20250106%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Signature=b248d751c47ee130381de69d2cae583e6f362a8f1d11ab0a7cd4d4b326c33ff4&hash=619903e4b18684764d30d45353cebdc0dc8a25193e2b6149c8c7f1e01866df18&host=68042c943591013ac2b2430a89b270f6af2c76d8dfd086a07176afe7c76c2c61&pii=00220000869002... (line truncated)
