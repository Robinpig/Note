## Introduction

缺陷（defect / bug）是软件与其期望之间的偏差。工程上真正关心的不是"有没有 bug"（一定有），而是三个可管理的问题：**它什么时候被引入、什么时候被发现、从引入到发现中间隔了多久**——这三者决定了修复成本。同一个编码错误，在写代码的当天发现是几分钟的事，到了生产环境则要付上排查、回滚、数据修复与对外解释的代价，见 [Engineering](/docs/CS/SE/Engineering.md) 的成本曲线。

相邻的两件事要划分清楚：**发现**缺陷主要靠 [Test](/docs/CS/SE/Test.md) 与线上 [APM](/docs/CS/SE/APM.md)，**定位**缺陷的手段在 [Debug](/docs/CS/SE/Debug.md)。本页讲的是缺陷本身的管理：怎么分类、怎么描述、怎么排优先级、怎么找根因。

## Classification

分类不是形式主义，它决定"该找谁来修"：

| 维度 | 取值 | 用途 |
|------|------|------|
| 引入阶段 | 需求 / 设计 / 编码 / 运维配置 | 决定流程该在哪补：需求评审、设计评审、code review、配置校验 |
| 表现类型 | 功能错误、性能劣化、并发竞态、资源泄漏、兼容性 | 决定技术手段，如竞态见 [Concurrency](/docs/CS/SE/Concurrency.md) 与 [Lock](/docs/CS/SE/Lock.md) |
| 可复现性 | 必现 / 偶现 / 环境相关 | 偶现缺陷通常指向时序、缓存、脏数据，排查成本高一个量级 |
| 影响面 | 单个用户 / 全量用户 / 数据损坏 | 决定优先级，而不是"看起来严不严重" |

## Lifecycle

一个缺陷从提出到收敛的典型状态：

```
New → Triaged → Assigned → Open → Fixed → Verified → Closed
                    │                         │
                    └→ Duplicate / Won't Fix  └→ Reopened
                       / Deferred / Not Reproducible
```

几个容易做坏的环节：

- **Triaged（分诊）**：先判断是不是真缺陷、归属谁，再谈排期。未经分诊就流转，是最大的时间黑洞。
- **Not Reproducible**：不等于没修。要记录环境、版本、数据量级，同时补上足以支撑下次定位的日志或埋点。
- **Reopened**：验证必须发生在与报告方相同的环境下，且由修复者之外的人来做；本地一句"我这没问题"不算验证。

## Prioritization

优先级 = **影响面 × 严重程度**，再加一个"是否在持续扩大"的时间维度：

- **P0**：全量用户不可用、数据正在损坏、资产直接损失 —— 立即停下手上的事；
- **P1**：核心功能不可用但有临时绕过方案，或影响到明确的重要客户；
- **P2**：边缘场景错误、体验劣化，排进本迭代；
- **P3**：优化项与"以后再说"，登记但不排期。

安全类缺陷不走这套标准——它的严重程度取决于可利用性与暴露面，而不是用户可见的症状，处理见 [Vulnerability Analysis](/docs/CS/Security/Vulnerability_Analysis.md)。

## Reproduce and Minimize

描述一个缺陷的最小可用信息集：

1. **确切的输入**（请求参数、数据量、文件内容），而不是"点了某个按钮"；
2. **环境**（版本号、配置开关、机器规格、依赖版本）——大量"在我机器上是好的"最后都落在配置差异上；
3. **期望与实际**（看到了什么、以为应该看到什么）；
4. **最小复现步骤**：不断删掉与结果无关的步骤，直到不能再删。最小化这一步常常直接把答案指出来——排除到最后剩下的那一行通常就是根因所在。

## Root Cause Analysis

目标是找**哪一次变更引入的**，而不是"谁引入的"——后者会让所有人学会掩饰。

- **二分定位**：引入范围明确时用 `git bisect` 自动二分提交区间，把嫌疑从几百次提交压到一次；
- **5 Whys**：对表面原因连问五次为什么，答案悬停在流程层（"因为这类改动没有人 review"）才能真正防止复发；
- **时序类缺陷**：不要靠"再加个 sleep"掩盖，竞态的根因是缺少 happens-before 约束；
- **复发检查**：修复的同时补一条会失败的测试用例，否则下一次重构会把它带回来，见 [Refactoring](/docs/CS/SE/Refactoring.md)。

## Links

- [Test](/docs/CS/SE/Test.md)
- [Debug](/docs/CS/SE/Debug.md)
- [APM](/docs/CS/SE/APM.md)
- [Concurrency](/docs/CS/SE/Concurrency.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)
- [Vulnerability Analysis](/docs/CS/Security/Vulnerability_Analysis.md)

## References

1. [git-bisect — git Documentation](https://git-scm.com/docs/git-bisect)
