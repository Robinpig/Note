## Introduction

在人工智能领域，智能体被定义为任何能够通过传感器（Sensors）感知其所处环境（Environment），并自主地通过执行器（Actuators）采取行动（Action）以达成特定目标的实体

真正赋予智能体"智能"的，是其自主性（Autonomy）。
智能体并非只是被动响应外部刺激或严格执行预设指令的程序，它能够基于其感知和内部状态进行独立决策，以达成其设计目标。
这种从感知到行动的闭环，构成了所有智能体行为的基础



传统智能体的能力源于工程师的显式编程与知识构建，其行为模式是确定且有边界的；而 LLM 智 能体则通过在海量数据上的预训练，获得了隐式的世界模型与强大的涌现能力，使其能够以更灵活、更通用 的方式应对复杂任务

我们正从开发专用自动化工具转向构建能自主解决问题的系统。核心不再是编写代码，而是引导 一个通用的“大脑”去规划、行动和学习



## Agent Loop





## Advance



会话管理

上下文



## Practice


Agent 的使用

让agent说人话： 

不许说黑话，给我好好说人话！
把上下文带上，前因后果都给我讲清楚！



AGENTS.md is an open standard for agent-specific documentation. 

```markdown

# AGENTS.md
## Dev Environment
- How to set up and navigate
## Standards
- Code style, naming, patterns
## Testing
- How to run and write tests
## Docs Reference
| Topic | File |
|-------|------|
| API contracts | docs/api.md |
| Architecture | docs/architecture.md |
| Deployment | docs/deploy.md |

```





## Pattern

一个成熟的Agent系统，都由以下几个核心模块组成：

![image](https://img2024.cnblogs.com/blog/2238006/202604/2238006-20260410152514831-2098084564.png)

六种核心设计模式



ReAct模式的核心思想是将“推理”和“行动”分离。

Agent先推理当前情况，决定下一步做什么，然后执行行动，观察结果，再继续推理，形成一个闭环



Tool Use 也是Function Calling



反思模式允许Agent对自己的输出进行批评和修正。它通过多轮迭代来提升输出质量



规划模式是应对复杂任务的核心武器。Plan Agent先将大任务拆解成多个子任务，再按顺序或并行执行





多智能体协作模式是规划模式的进化版。

它不仅仅是串行执行，而是通过消息通信实现智能体间的动态协作



人机协同模式是AI Agent落地的安全阀。在涉及资金、权限、敏感数据的操作上，必须加入人工确认环节，而不是完全交给AI自主决策



在实际项目中，这六种模式往往不是孤立使用的，而是根据业务场景灵活组合：

- **智能客服** = ReAct + Tool Use（查订单、查库存）+ Reflection（提升回答质量）
- **数据分析平台** = Planning + Multi-Agent + Human-in-the-Loop（数据敏感需审批）
- **代码生成助手** = ReAct + Reflection + Tool Use（执行代码、运行测试）











## SubAgent


为什么需要SubAgent？

- 上下文隔离
- 注意力机制
- 成本控制 上下文限制
- 


如何设计子


## Links

