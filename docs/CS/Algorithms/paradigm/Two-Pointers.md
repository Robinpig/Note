## Introduction

双指针算法是一种常用的算法技巧，它通过使用两个指针在数组或链表中按特定方式移动，来解决多种问题

若两个指针指向同一数组，遍历方向相同且不会相交，则也称为滑动窗口（两个指针包围的区域即为当前的窗口），经常用于区间搜索。
若两个指针指向同一数组，但是遍历方向相反，则可以用来进行搜索，待搜索的数组往往是排好序的



## Floyd's Cycle Detection

对于链表找环路的问题，有一个通用的解法——快慢指针（Floyd 判圈法）
给定两个指针，分别命名为 slow 和 fast，起始位置在链表的开头
每次 fast 前进两步，slow 前进一步。如果 fast可以走到尽头，那么说明没有环路；如果 fast 可以无限走下去，那么说明一定有环路，且一定存在一个时刻 slow 和 fast 相遇
当 slow 和 fast 第一次相遇时，我们将 fast 重新移动到链表开头，并让 slow 和 fast 每次都前进一步
当 slow 和 fast 第二次相遇时，相遇的节点即为环路的开始点



## Sliding Window

滑动窗口是同向双指针的标准形态：两个指针 `left`、`right` 圈定一个区间 `[left, right)`，`right` 单向右移负责「扩张」，`left` 在满足条件时右移负责「收缩」。每一步两个指针各走一次，整体把 $O(n^2)$ 的区间枚举压到 $O(n)$——前提是**窗口内状态的更新可增量**（进一个元素、出一个元素都是 $O(1)$），且**窗口的伸缩具有单调性**。

### Window Types

- **定长窗口**：窗口大小固定为 $k$，每右移一格就更新一次答案。如「每 $k$ 个元素的最大和」。
- **变长窗口**：窗口大小随条件变化，是最常见的形态。如「和大于等于 target 的最短子数组」——`right` 一直扩张到满足条件，再收缩 `left` 直到不满足，记录过程中每个合法窗口。

### Template

```text
right = 0
for left in 0 .. n-1:
    while right < n and can_extend(window):
        window.add(a[right]); right += 1
    update_answer(window)          # 此时窗口为 [left, right)
    window.remove(a[left])         # left 即将右移，先退出左边界元素
```

注意模板的循环不变量：**每个 `left` 只对应一个 `right`**，`right` 全程只增不减，因此总步数 $O(n)$。

### Typical Problems

- 长度最小的子数组（和 ≥ target）：变长窗口，更新时机在收缩前。
- 无重复字符的最长子串：窗口内维护字符计数，出现重复就收缩。
- 至多包含 $k$ 个不同字符的最长子串：维护窗口内不同字符数。
- 字符串的排列 / 异位词判定：定长窗口 + 字符频次差。
- 滑动窗口最大值：窗口内最值需要 **单调队列** 维护，见 [MonotonicStack](/docs/CS/Algorithms/struct/MonotonicStack.md)。

### When Not to Use It

窗口法依赖两个性质：**单调性**（right 扩张后最优 left 只会右移）与**可增量维护**。若窗口内判定本身需要重新计算（如乘积子数组、含通配的复杂匹配），滑动窗口并不适用，此时应回到二分答案 + 可行性判定，见 [search](/docs/CS/Algorithms/search.md) 与 [DP](/docs/CS/Algorithms/DP/DP.md)。

## Links

- [Array](/docs/CS/Algorithms/struct/array.md)
- [Linked List](/docs/CS/Algorithms/struct/linked-list.md)
- [Monotonic Stack](/docs/CS/Algorithms/struct/MonotonicStack.md)
- [Search](/docs/CS/Algorithms/search.md)

## References

1. [双指针 - OI Wiki](https://oi-wiki.org/misc/two-pointer/)
2. [Slow and Fast Pointers (Floyd's Cycle Detection) - CP-Algorithms](https://cp-algorithms.com/others/tortoise_and_hare.html)
