## Introduction

双指针算法是一种常用的算法技巧，它通过使用两个指针在数组或链表中按特定方式移动，来解决多种问题

若两个指针指向同一数组，遍历方向相同且不会相交，则也称为滑动窗口（两个指针包围的区域即为当前的窗口），经常用于区间搜索。
若两个指针指向同一数组，但是遍历方向相反，则可以用来进行搜索，待搜索的数组往往是排好序的



## 快慢指针

对于链表找环路的问题，有一个通用的解法——快慢指针（Floyd 判圈法）
给定两个指针，分别命名为 slow 和 fast，起始位置在链表的开头
每次 fast 前进两步，slow 前进一步。如果 fast可以走到尽头，那么说明没有环路；如果 fast 可以无限走下去，那么说明一定有环路，且一定存在一个时刻 slow 和 fast 相遇
当 slow 和 fast 第一次相遇时，我们将 fast 重新移动到链表开头，并让 slow 和 fast 每次都前进一步
当 slow 和 fast 第二次相遇时，相遇的节点即为环路的开始点



## 滑动窗口








## Links

- [Array](/docs/CS/Algorithms/struct/array.md)
- [Linked List](/docs/CS/Algorithms/struct/linked-list.md)
- [Algorithm Design](/docs/CS/Algorithms/Algorithms.md)