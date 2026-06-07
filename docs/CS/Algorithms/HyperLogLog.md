## Introduction

HyperLogLog 是一种用于 count-distinct 问题的算法，用于近似计算多重集中不同元素的数量。
计算多重集中不同元素的精确基数需要与基数成正比的内存，这对于非常大的数据集是不切实际的。
概率性基数估计器，如 HyperLogLog 算法，使用的内存显著更少，但只能近似估计基数。

HyperLogLog 算法的基础是这样一个观察结果：可以通过计算集合中每个数字的二进制表示中前导零的最大数量，来估计均匀分布随机数的多重集的基数。
如果观察到的前导零最大数量为 n，则集合中不同元素数量的估计值为 2^n。

在 HyperLogLog 算法中，对原始多重集中的每个元素应用哈希函数，以获得一个与原始多重集具有相同基数的均匀分布随机数的多重集。
然后可以使用上述算法来估计这个随机分布集合的基数。

使用上述算法获得的简单基数估计存在方差大的缺点。
在 HyperLogLog 算法中，通过将多重集分割成多个子集，计算每个子集中数字的最大前导零数量，并使用调和平均数将这些子集的估计值组合成整个集合的基数估计值，从而最小化方差。

HyperLogLog 有三个主要操作：add 用于向集合中添加新元素，count 用于获取集合的基数，merge 用于获取两个集合的并集。
可以使用容斥原理计算一些衍生操作，如交集基数或两个 HyperLogLog 之间的差集基数，通过组合 merge 和 count 操作来实现。

HyperLogLog 的数据存储在一个包含 m 个计数器（或"寄存器"）的数组 M 中，这些计数器初始化为 0。
从多重集 S 初始化的数组 M 称为 S 的 HyperLogLog sketch。

## Complexity

为了分析复杂度，使用了数据流 ${\displaystyle (\epsilon ,\delta )}$ 模型，该模型分析在固定成功概率 ${\displaystyle 1-\delta }$ 下获得 ${\displaystyle 1\pm \epsilon }$ 近似值所需的空间。
HLL 的相对误差为 ${\displaystyle 1.04/{\sqrt {m}}}$，需要 ${\displaystyle O(\epsilon ^{-2}\log \log n+\log n)}$ 的空间，其中 n 是集合基数，m 是寄存器数量（通常小于一个字节大小）。

add 操作取决于哈希函数输出的大小。由于这个大小是固定的，我们可以认为 add 操作的运行时间为 ${\displaystyle O(1)}$。

count 和 merge 操作取决于寄存器数量 m，理论开销为 ${\displaystyle O(m)}$。
在某些实现（[Redis](/docs/CS/DB/Redis/struct/HyperLogLog.md)）中，寄存器数量是固定的，文档中认为其开销为 ${\displaystyle O(1)}$。

## Links
