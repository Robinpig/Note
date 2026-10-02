## Introduction

在人工智能领域，智能体被定义为任何能够通过传感器（Sensors）感知其所处环境（Environment），并自主地通过执行器（Actuators）采取行动（Action）以达成特定目标的实体

真正赋予智能体"智能"的，是其自主性（Autonomy）。
智能体并非只是被动响应外部刺激或严格执行预设指令的程序，它能够基于其感知和内部状态进行独立决策，以达成其设计目标。
这种从感知到行动的闭环，构成了所有智能体行为的基础。



传统智能体的能力源于工程师的显式编程与知识构建，其行为模式是确定且有边界的；而 LLM 智能体则通过在海量数据上的预训练，获得了隐式的世界模型与强大的涌现能力，使其能够以更灵活、更通用的方式应对复杂任务

我们正从开发专用自动化工具转向构建能自主解决问题的系统。核心不再是编写代码，而是引导一个通用的“大脑”去规划、行动和学习。



## Agent Loop

**AI Agent 是一个能够调用工具的循环系统**。这个定义抓住两个本质特征：

1. 核心工作机制：`Loop` 循环（ReAct 模式）
2. 行动能力：对 `Tools` 工具的调用

Agent 与 LLM 的区别：给 LLM 输入文本、输出文本（Chatbot）；而 Agent 输出的是**一次具体行动**（执行 Tool），行动结果继续输入给 LLM，LLM 据此判断下一步——循环往复直到目标达成。

ReAct 循环四步：

1. **Reason（推理）**：LLM 调研规划，明确做什么、怎么做
2. **Act（行动）**：模型调用 Tools 干活
3. **Observe（观察）**：评估结果是否满足预期
4. 回到下一轮 Reason……前面的行动结果作为输入，直到 Agent 判断得出目标答案

这个 Loop 循环是**对人类实际工作过程的模拟抽象**，类似 PDCA 戴明环。所有 Agent（coding、研究、做 PPT、客服……）表面不同，底层机制都是这个循环。LLM 本身仍在思考推理生成文本，只是 Agent 里生成的文本可以是"运行某个 Tool"这样的执行指令。

> 一个最小可行性 Agent（MVP）必须具备一个完整的"感知-思考-行动-观察"闭环。

循环强依赖两个条件：①执行结果要被保留并作为 Context 输入后续执行（否则每轮都是全新过程）；②需要指挥官统一协调循环与工具调用——由此引出 `Memory` 和 `Harness` 两个模块。**Agent 由四个核心构成：Loop、Tools、Memory、Harness。**



## Advance

一个成熟的Agent系统，都由以下几个核心模块组成：

![image](https://img2024.cnblogs.com/blog/2238006/202604/2238006-20260410152514831-2098084564.png)



## Tool

**Tool 就是可供 LLM 调用的一项具体能力**（打开浏览器、搜索网页、查询数据库……），像给大脑提供手脚。

- Tools 需要有明确的名称和描述（description）——LLM 和人一样，需要知道"按钮的功能说明"才能判断什么时候按哪个
- **最佳实践**：一个 tool 对应一项简单具体的任务，简单到 description 一两句话能说清——LLM 判断更准，执行效果越好
- 来源三类：系统预置、外部接入（MCP 开放标准协议）、自制
- **Tool 是能力，不是知识**：Tool 负责"能做什么、做了什么"，不承担"怎么做"——后者属于 Memory/知识库的范畴





## Memory

为什么需要 Memory？Loop 要求上一次循环的执行结果和历史资料作为 Context 输入下一次循环——必须有地方把每次的 Context 存下来供读取。

技术方案演进：

- **早期：向量数据库**——Context 做 embedding 转向量，运行时找相似度最高的数据块
- **现在：知识库（markdown 文件夹集合）**——Agent 通过关键词搜索，读取文件标题/描述/目录树结构判断相关性，比向量相似度更准；像新员工读公司 Wiki/交接文档

知识库的两个关键优势：

1. **文件与文件夹结构化**，比相似度检索更容易判断相关性
2. **文件可改写**——Context 内容可随时更新迭代（上个任务的日志、报错记录、新增数据文档）

当前 Memory 的工作方式实质是**每次执行过程中对 Context 文件的读取和增删改写**——这也是 Agent"越用越懂你"的原因。Skill 采用 markdown 文件夹（可随时迭代修改）的交互范式正被越来越多厂商接受。



## Harness

Agent 作为系统不是魔法，需要处理一堆执行细节：

- 谁来发起并控制 Loop 循环？谁执行 Tools？谁管理 Context（尤其过长时）？
- 执行出错如何处理？工具调用的权限管控？何时让用户提供更多信息、确认是否往下进行？

**Harness 是 Agent 的底层架构、基础设施、操作系统**（可译作框架/编排/运行环境）。Codex、Claude Code、DeepSeek Harness 这类 Agent 产品，从工程角度看主要构成就是 Harness——像 Windows/macOS/Linux 之于应用程序。

在这些产品出现之前，搭一个 Agent 要自己用 Python 手搓：条件循环实现 Loop 调度、任务中止/重试、Context 间的注意力跳转……如今这些编排调度工作都被 Harness 接管。

四组件合起来的完整图景：

- **Loop 机制**：调用模型、工具，执行、重复，直到任务完成
- **Tools 执行**：行动能力（读文件、Shell、MCP）
- **Memory 知识库**：管理循环中的 Context，决定哪些内容进 context window
- **Harness**：基础设施——错误处理、权限验证（哪些操作自行把控、哪些请求用户允许；授权频率是门艺术：太频繁觉得事儿多，一路干到底又心虚）

广义产品意义上，Harness 基本等同于我们在用的 Agent。最终可总结为：**Agent = LLM + Harness**。

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

- [Harness](/docs/CS/AI/LLM/Harness.md)
- [Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md)
- [MCP](/docs/CS/AI/LLM/MCP.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md)
- [DSH](/docs/CS/AI/LLM/DSH.md)
- [Skill](/docs/CS/AI/LLM/Skill.md)
- [Codex](/docs/CS/AI/LLM/Codex.md)

## References

- [深入拆解 Agent 的工作机制和构成](https://mp.weixin.qq.com/s/H7gAhzx2F432z_ewBanP8A)
