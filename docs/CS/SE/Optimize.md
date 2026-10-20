## Introduction

这一页是**代码级 / 机器级**的性能优化：站在编译器与 CPU 的视角，改写计算本身，让同样的算法跑更少的指令、更少的访存。它与 [Performance](/docs/CS/SE/Performance.md) 是上下两层关系——后者回答"慢在哪里、用什么指标衡量"，本页回答"定位到热点之后，这段代码还能怎么改"。因此顺序永远是**先度量后改写**：没有 profile 支撑的优化只是在猜。

一条前提要记住：编译器已经很聪明，现代编译器会做强度削弱、公共子表达式消除、循环展开；手工做这些只有在**编译器因为别名（aliasing）或过程调用边界而不敢动**时才有效。所以优化的第一步通常是"别挡着编译器"，而不是替它干活。

## Reduction in Strength

强度削弱（Reduction in Strength）：用更便宜的操作替换昂贵的操作。

- 用移位、加法替代乘法/除法（乘以 2 的幂 → 左移）；
- **机器相关**：是否真的更快取决于乘法/除法指令的代价。例如在 Intel Nehalem 上，整数乘法需要 3 个 CPU 周期，而移位是 1 个周期——但换一个微架构，这个比值就可能不同，任何强度削弱都要回到目标机器上验证；
- 识别乘积序列（Recognize sequence of products）：连续乘以同一变量时合并成一次乘法，或把循环内的乘法转化为累加。

## Share Common Subexpressions

公共子表达式消除：同一个表达式在多处重复计算时，只算一次并复用结果。编译器在基本块内会自动做，跨基本块或存在指针别名时就得靠人把中间结果提到变量里。

## Getting High Performance

- **好的编译器 + 合适的编译选项**：`-O2` 通常是性价比起点，更高等级不保证更快。
- **别做蠢事（Don't do anything stupid）**：这一条收益最大也最常被跳过。
  - 警惕隐藏的算法低效：一个不该出现的 O(n²) 抵消掉所有局部优化；
  - 写对编译器友好的代码：注意优化阻碍（optimization blockers）——过程调用与内存引用是两大典型，编译器因为无法确定副作用而不敢重排、不敢缓存到寄存器；
  - 重点看最内层循环，大部分时间花在那里。
- **针对机器调优**：
  - 利用指令级并行（ILP）：拆掉循环携带的数据依赖，让多条指令能同时发射；
  - 避免难以预测的分支：分支预测失败的代价远高于一条算术指令；
  - 让代码对缓存友好：顺序访问、提高时间/空间局部性，缓存未命中的代价是算术指令的几十倍。

## Relationship with Measurement

上述手段全部是"局部改写"，收益上限由算法复杂度与访存模式决定。因此它的正确用法是：先用 [APM](/docs/CS/SE/APM.md) 与压测找到热点，确认瓶颈确实在计算本身而不是 IO、锁或数据库，再动手；改完必须复测。定位问题的方法见 [Debug](/docs/CS/SE/Debug.md)，压测见 [Stress testing](/docs/CS/SE/Stress_testing.md)。

## Links

- [Performance](/docs/CS/SE/Performance.md)
- [APM](/docs/CS/SE/APM.md)
- [Stress testing](/docs/CS/SE/Stress_testing.md)
- [Debug](/docs/CS/SE/Debug.md)
- [Programming](/docs/CS/SE/Programming.md)

## References

1. [CS:APP — Computer Systems: A Programmer's Perspective](http://csapp.cs.cmu.edu/)
