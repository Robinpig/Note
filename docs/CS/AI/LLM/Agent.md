## Introduction

在人工智能领域，智能体被定义为任何能够通过传感器（Sensors）感知其所处环境（Environment），并自主地通过执行器（Actuators）采取行动（Action）以达成特定目标的实体

真正赋予智能体"智能"的，是其自主性（Autonomy）。
智能体并非只是被动响应外部刺激或严格执行预设指令的程序，它能够基于其感知和内部状态进行独立决策，以达成其设计目标。
这种从感知到行动的闭环，构成了所有智能体行为的基础。



传统智能体的能力源于工程师的显式编程与知识构建，其行为模式是确定且有边界的；而 LLM 智能体则通过在海量数据上的预训练，获得了隐式的世界模型与强大的涌现能力，使其能够以更灵活、更通用的方式应对复杂任务

我们正从开发专用自动化工具转向构建能自主解决问题的系统。核心不再是编写代码，而是引导一个通用的“大脑”去规划、行动和学习。



## Agent Loop


一个最小可行性 Agent（MVP）必须具备一个完整的 “感知-思考-行动-观察”闭环。





## Advance

一个成熟的Agent系统，都由以下几个核心模块组成：

![image](https://img2024.cnblogs.com/blog/2238006/202604/2238006-20260410152514831-2098084564.png)



## Tool







## Memory





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

六种核心设计模式


### ReAct

ReAct模式的核心思想是将“推理”和“行动”分离。

Agent先推理当前情况，决定下一步做什么，然后执行行动，观察结果，再继续推理，形成一个闭环


如何防止 ReAct 死循环
1. 最大步数限制——通常设 15 步，超过就强制终止
2. 重复动作检测——连续 3 次调用同一个工具且参数相同，直接退出循环
3. 超时控制——整个任务设置最大执行时间





Tool Use 也是Function Calling



反思模式允许Agent对自己的输出进行批评和修正。它通过多轮迭代来提升输出质量


### Plan-and-Execute

规划模式是应对复杂任务的核心武器。Plan Agent先将大任务拆解成多个子任务，再按顺序或并行执行




### Multi-Agent

多智能体协作模式是规划模式的进化版。

它不仅仅是串行执行，而是通过消息通信实现智能体间的动态协作


> 不要过早引入 Multi-Agent。一个强大的单 Agent 往往比多个简单 Agent 协作更稳定、更省钱。只有任务明确需要并行处理或专业分工时，才引入多 Agent。




人机协同模式是AI Agent落地的安全阀。在涉及资金、权限、敏感数据的操作上，必须加入人工确认环节，而不是完全交给AI自主决策



在实际项目中，这六种模式往往不是孤立使用的，而是根据业务场景灵活组合：

- **智能客服** = ReAct + Tool Use（查订单、查库存）+ Reflection（提升回答质量）
- **数据分析平台** = Planning + Multi-Agent + Human-in-the-Loop（数据敏感需审批）
- **代码生成助手** = ReAct + Reflection + Tool Use（执行代码、运行测试）











### SubAgent


为什么需要SubAgent？

- 上下文隔离
- 注意力机制
- 成本控制 上下文限制
- 

如何设计SubAgent





设计一个企业级 Agent 系统，需要考虑哪些点？

必答五个要点：

工具管理层——MCP Server 统一管理，工具权限分级（只读/读写/管理员），工具调用审计日志
记忆与状态——短期对话上下文管理（滑动窗口/摘要压缩），长期向量数据库（用户偏好/历史经验），会话 Redis（任务状态/中间结果）
可靠性保障——最大步数限制防死循环，工具调用超时控制，关键操作人工审批，失败重试 + 熔断机制
可观测性——完整的 Trace（思考链 + 工具调用 + 结果），Token 消耗监控控制成本，错误分类统计
安全——Prompt Injection 防御，最小权限原则，数据脱敏



Agent 的 Token 消耗很大，怎么优化成本？

优化策略从易到难排：

工具选择优化——只给 Agent 它真正需要的工具（减少工具描述 Token），按任务类型动态加载工具子集
模式选择——简单任务用 Workflow 代替 Agent（节省4倍 Token），Plan-and-Execute 代替 ReAct（节省规划 Token）
上下文压缩——摘要压缩历史对话，中间结果只保留关键信息
模型路由——简单子任务用小模型（如 GPT-4o-mini），复杂推理才用大模型（如 GPT-4o / Claude 3.5）
缓存——工具调用结果缓存（相同参数直接返回），Prompt 缓存（Anthropic 支持 Prompt Cache）







## Links
