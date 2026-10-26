## Introduction

软件工程（Software Engineering）研究的是如何在**规模、时间和不确定性**下持续交付可靠软件：1968 年 NATO 会议创造这个词，正是为了应对"软件危机"——个人写程序的手艺无法直接扩展到多人、多年、数十万行代码的系统。它覆盖从需求、设计、编码、测试、发布到运维的全生命周期，核心矛盾是：需求会变、人会流动、系统会腐化，而代码必须在这些变化中持续可演进。

## Map of This Section

这一节的笔记可以按"一个人做工程时依次会遇到的问题"来读，而不是按主题字母序。

**先建立判断框架，再谈手段。** [Basic](/docs/CS/SE/Basic.md) 记的是那些非技术性的认知——本质复杂度与偶然复杂度、抽象的反噬、测试只能证伪——它们决定后面每一个手段什么时候该用；这些认知在真实业务系统里如何表现为"改不动"，由 [Complexity](/docs/CS/SE/Complexity.md) 展开（隐性耦合的长尾、架构短视是开发方式的产物）。[Programming](/docs/CS/SE/Programming.md) 与 [reactive](/docs/CS/SE/reactive.md) 是范式层的选择，写出来的代码是否整洁看 [Clean Code](/docs/CS/SE/Clean_Code.md)、腐化之后怎么收拾看 [Refactoring](/docs/CS/SE/Refactoring.md) 与 [Code](/docs/CS/SE/Code.md)；出错之后，缺陷的分类与定位思路在 [Bug](/docs/CS/SE/Bug.md) 与 [Debug](/docs/CS/SE/Debug.md)。

**然后决定系统的形状。** [Architecture](/docs/CS/SE/Architecture.md) 给出风格谱系与微服务的真实代价，[DDD](/docs/CS/SE/DDD.md) 解决"边界画在哪"，[registry](/docs/CS/SE/registry.md) 是服务化的第一块基础设施，[中台](/docs/CS/SE/中台.md) 讲组织与复用的张力，[Serverless](/docs/CS/SE/Serverless.md) 与 [Mini Program](/docs/CS/SE/MiniProgram/Mini_Program.md) 是两种交付/端形态；综合演练见 [SystemDesign](/docs/CS/SE/SystemDesign.md)。

**形状定了之后是正确性。** 并发让"看起来对"的代码出错：基础模型见 [Concurrency](/docs/CS/SE/Concurrency.md)，互斥与分布式锁见 [Lock](/docs/CS/SE/Lock.md)，跨服务的一致性见 [Transaction](/docs/CS/SE/Transaction.md)，多步骤业务的过程保证见 [Workflow](/docs/CS/SE/Workflow.md)。

**再往后是规模与韧性。** 流量上来后第一道防线是缓存：[Cache](/docs/CS/SE/Cache.md) 讲体系与一致性，[Caffeine](/docs/CS/SE/Caffeine.md) 与 [JetCache](/docs/CS/SE/JetCache.md) 是两种落地；保护自己的手段是 [RateLimiter](/docs/CS/SE/RateLimiter.md) 与 [CircuitBreaker](/docs/CS/SE/CircuitBreaker.md)；异步与兜底靠 [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)，支付这类"不能少一次"的场景看 [掉单机制](/docs/CS/SE/掉单机制.md)。

**最后是反馈回路。** 快慢要先度量：[Performance](/docs/CS/SE/Performance.md) 定指标，[Optimize](/docs/CS/SE/Optimize.md) 是定位到热点之后的机器级改写，[Stress testing](/docs/CS/SE/Stress_testing.md) 与 [Test](/docs/CS/SE/Test.md) 做验证，线上真相对照 [APM](/docs/CS/SE/APM.md)。

**场景类笔记是上述所有手段的合流处**：[Feed](/docs/CS/SE/Feed.md)、[秒杀](/docs/CS/SE/秒杀.md)、[Live](/docs/CS/SE/Live.md)，以及自成体系的 [IM](/docs/CS/SE/IM/IM.md)（[Client](/docs/CS/SE/IM/Client.md)、[DTIM](/docs/CS/SE/IM/DTIM.md)、[MQTT](/docs/CS/SE/IM/MQTT.md)、[闲鱼 IM](/docs/CS/SE/IM/闲鱼IM.md)）。

## Coding Standards

> 代码行长度应该不超过 80 个字符——这条惯例常被追溯到 Fortran 时代的穿孔卡片（80 列），后来被终端 80×24 字符界面固化。现代宽屏下 Google Java Style 取 100、Python PEP 8 取 79，本质目的不变：便于并排 diff、控制单行复杂度、让眼睛扫视不换行。

规范真正的价值不是美学，而是**降低协作的认知税**：命名、格式化、目录结构一旦统一，读者就能把注意力放在逻辑差异上。因此规范应当工具化（Checkstyle/Spotless、ESLint、Prettier、gofmt），靠 code review 争论格式是最低效的执行方式。代码整洁的具体准则见 [Clean Code](/docs/CS/SE/Clean_Code.md)，坏味道与重构手法见 [Refactoring](/docs/CS/SE/Refactoring.md)。

## Lifecycle Model

| 模型 | 特点 | 适用 |
|------|------|------|
| 瀑布 | 需求→设计→实现→测试串行，文档驱动 | 需求极稳定（航天、军工） |
| 迭代/增量 | 分版本交付，逐步精化 | 大多数商业软件 |
| 敏捷（Scrum/Kanban） | 短周期反馈、持续集成、拥抱变化 | 需求不确定的互联网产品 |
| DevOps | 开发运维一体化，CI/CD + 监控形成闭环 | 高频发布的服务 |

敏捷不是"没有设计"，而是把大设计拆成连续的小决策，用反馈代替预测。工程实践支撑（CI 自动化测试、trunk-based 开发、特性开关）缺失时，"敏捷"只会退化为混乱的排期会。

## Quality Assurance

- **测试金字塔**：大量单元测试（快、隔离）→ 适量集成测试（验证组件协作）→ 少量端到端测试（慢、脆弱但真实），见 [Test](/docs/CS/SE/Test.md)。
- **代码评审**：主要目的是知识共享与设计把关，而非抓语法 bug（那是 linter 的工作）。
- **静态分析**：编译期发现空指针、资源泄漏、依赖漏洞（SonarQube、SpotBugs、依赖扫描）。
- **可观测性**：日志、指标、链路追踪三件套，线上是新的调试器，见 [APM](/docs/CS/SE/APM.md)。
- 质量是内建的（quality in）：缺陷越晚发现修复成本指数上升，需求阶段 1、编码 10、生产环境 100。

## Cost and Debt

- **技术债务**：为短期速度选择的次优方案相当于借债——不还也能跑，但每次修改都要付"利息"（理解成本、bug 率），复利累积最终拖慢一切。债务要显式登记并在迭代中偿还，不能假装不存在。扩张期借债像加杠杆，收益可能覆盖利息；问题从来不是"要不要欠债"，而是"何时还、还多少、怎么还"。
- **Brooks's Law**：向延期项目加人只会更延期——新成员需要老人培训，沟通成本按人数平方增长。
- **没有银弹（No Silver Bullet）**：Brooks 指出软件的本质复杂度（业务本身）无法靠语言/工具消除，工程管理只能压缩偶然复杂度。工具链提效解决的是偶然复杂度那一半，业务建模、隐性耦合与架构腐化属于另一半，见 [Complexity](/docs/CS/SE/Complexity.md)。
- **过早优化是万恶之源**（Knuth）：先 [度量](/docs/CS/SE/Performance.md)再优化，针对瓶颈而非臆测。

## Metrics

- 生产力不能用代码行数衡量（"用代码行数衡量进度，就像用重量衡量飞机制造进度"）；
- DORA 四指标更能反映工程效能：部署频率、变更前置时间、变更失败率、故障恢复时间（MTTR）；
- 系统侧指标：可用性（SLA/SLO）、延迟分位数（P99 而非平均值）、错误率、饱和度（USE 方法）。

## Links

- [Architecture](/docs/CS/SE/Architecture.md)
- [Clean Code](/docs/CS/SE/Clean_Code.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)
- [Test](/docs/CS/SE/Test.md)
- [SystemDesign](/docs/CS/SE/SystemDesign.md)
- [Programming](/docs/CS/SE/Programming.md)

## References

1. [Software Engineering Body of Knowledge (SWEBOK)](https://www.computer.org/education/bodies-of-knowledge/software-engineering)
2. [No Silver Bullet — Fred Brooks (UNC TR86-020)](https://www.cs.unc.edu/techreports/86-020.pdf)
3. [DORA DevOps Research and Assessment](https://dora.dev/research/)
