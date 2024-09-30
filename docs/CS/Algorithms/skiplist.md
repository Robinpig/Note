## Introduction

In computer science, a skip list (or skiplist) is a probabilistic data structure that allows O(logn) average complexity for search as well as O(logn) average complexity for insertion within an ordered sequence of n elements


有序数组的好处是可以通过二分实现O(lgn)的高效查找，然而插入元素时，为了保证有序性，时间复杂度是O(n)的。链表则刚好相反，插入数据是O(1)，查找元素则是O(n)的。即使链表数据是有序的，查找元素仍然是O(n)的，因为本质上，链表不支持random access



跳表是一个多层的结构，第一层就是普通的有序链表，包含了序列中所有元素，如下图所示。仅有一层结构的跳表与普通的数据结构链表并无而致，为了提高跳表的性能，第一层之上添加了若干层，这些层有个fashion的名字——express lane(快车道)


对于如何从第i层逐层向上构建，维基百科给了这样一种说法：

给定一个固定的概率p(通常是1/2或者1/4)，第i层中的节点以概率p的可能性出现在第i+1层。在平均情况下，每个节点会出现在1/(1−p)个链表中，且顶层的元素会出现在每一层链表中。整个跳表平均包含log1/p​n个链表


1. 查询：

从顶层开始，每次找到最后一个小于key的节点n（如果等于，直接返回已找到；如果没找到这样的节点，则直接返回不存在），然后向下一层到第i层
从当前层继续重复步骤1，如果未返回找到或不存在，则从n‘所在层i再往下一层到i-1层；
重复步骤2操作
2. 插入:

插入也可以沿用查询操作时的逻辑判断，每次都从当前层找到最后一个小于key的节点n，插入的位置就是第1层节点n所在位置。

3. 删除:

同样的，我们每次都找到最后一个小于key的节点，直到第1层。将第1层中最后一个小于key的节点的后续第一个节点删除即可完成该操作




skiplist 相比 balanced trees的优势

For many applications, skip lists are a more natural representation than trees, also leading to simpler algorithms. The simplicity of skip list algorithms makes them easier to implement and provides significant constant factor speed improvements over balanced tree and self-adjusting tree algorithms. Skip lists are also very space efficient. They can easily be configured to require an average of 1 1/3 pointers per element (or even less) and do not require balance or priority information to be stored with each node.
建议同时设置一个 MaxLevel

Determining MaxLevel Since we can safely cap levels at L(n), we should choose MaxLevel = L(N) (where N is an upper bound on the number of elements in a skip list). If p = 1/2, using MaxLevel = 16 is appropriate for data structures containing up to 216 elements.



## Links

