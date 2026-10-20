## Introduction

软件构建（Software Construction）是软件工程里最容易被低估的一环：它常被直接等同于"写代码"，但实际上它是**需求之后、系统测试之前那一整段把设计变成可运行软件的密集活动**——编码、调试、单元测试、集成，以及大量"为了让审查者看懂"的细节打磨。Steve McConnell 在《代码大全》里把构建当作一项独立的活动来讨论，正是因为它同时消耗最多人力、引入最多缺陷，也最容易在没有纪律的情况下失控。

软件开发可以很复杂。过去数十年里，研究者梳理出软件开发中若干彼此不同的活动，包括：

- 问题定义（Problem definition）
- 需求开发（Requirements development）
- 构建规划（Construction planning）
- 软件架构 / 高层设计（Software architecture）
- 详细设计（Detailed design）
- 编码与调试（Coding and debugging）
- 单元测试（Unit testing）
- 集成测试（Integration testing）
- 系统测试（System testing）
- 纠正性维护（Corrective maintenance）

构建的主体是编码与调试，但它同样涉及详细设计、构建规划、单元测试、集成与集成测试等活动——**这正是它在估算时被系统性低估的原因**：看起来只有 coding 一项，实际包含了半打隐蔽活动。

## Boundary with Neighboring Activities

划清边界能省掉大部分协作摩擦：

| 相邻活动 | 边界在哪 | 本库对应笔记 |
|---------|---------|-------------|
| 需求 | 需求回答"要什么"，构建回答"怎么实现它"；需求没定就动手是返工的主因 | [Basic](/docs/CS/SE/Basic.md) |
| 架构 | 架构定组件边界与通信方式，构建在其内部展开 | [Architecture](/docs/CS/SE/Architecture.md) |
| 详细设计 | 类签名、数据结构、算法选择——通常就在构建过程中完成 | [DDD](/docs/CS/SE/DDD.md) |
| 测试 | 构建期的测试是"我的代码对不对"，系统级的验证属于测试活动 | [Test](/docs/CS/SE/Test.md) |
| 调试 | 调试是构建的一部分（首先要能跑起来），上线后的排查属于运维反馈 | [Debug](/docs/CS/SE/Debug.md) |

## Tasks in Construction

构建过程中具体包括这些任务：

- 确认前置工作已经就绪（地基打好了，构建才能顺利进行）
- 确定代码将如何被测试
- 设计与编写类和例程
- 创建并命名变量与具名常量
- 选择控制结构、组织语句块
- 对自己的代码做单元测试、集成测试与调试
- 评审其他成员的低层设计与代码，也让对方评审你的
- 通过仔细的格式化和注释打磨代码
- 把分别开发的软件组件集成到一起
- 调优代码，让它更快、占用更少资源

这份清单有个容易被忽略的共同点：**过半条目都不是"写"而是"检查与整理"**。这解释了为什么两名产出相同功能的程序员效率能差出数倍——慢的那部分时间大多花在验证与返工上，而不是打字上。

## Why Discipline Matters Here

构建是缺陷的主要引入阶段，也是唯一可以在引入当天就低成本修复的阶段——同一处错误拖到生产环境的修复代价要高出一到两个数量级，见 [Bug](/docs/CS/SE/Bug.md)。因此 [Clean Code](/docs/CS/SE/Clean_Code.md) 的命名与函数约束、[Refactoring](/docs/CS/SE/Refactoring.md) 的重构手法、[Programming](/docs/CS/SE/Programming.md) 的范式选择，本质上都是给这一阶段的复杂度装护栏。性能相关的取舍留到 [Optimize](/docs/CS/SE/Optimize.md)，不要在设计阶段就替编译器干活。

## Links

- [Clean Code](/docs/CS/SE/Clean_Code.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)
- [Programming](/docs/CS/SE/Programming.md)
- [Bug](/docs/CS/SE/Bug.md)
- [Test](/docs/CS/SE/Test.md)
- [Engineering](/docs/CS/SE/Engineering.md)

## References

1. 《代码大全（Code Complete）》— Steve McConnell
