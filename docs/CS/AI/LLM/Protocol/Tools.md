## Introduction

LLM 本身只会输出 token，是**工具（Tools / Function Calling）**让它从「会说」变成「能做」：模型输出结构化的调用请求，由外部 Harness 执行真实动作（查数据库、读文件、调 API、执行代码），再把结果回灌上下文。这条「模型决策 → 框架执行 → 结果回填」的闭环是一切 Agent 的行动基础，其真正所有者是包裹模型的 Harness，而不是模型本身——详见 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 与 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)。

本笔记梳理工具生态的三个层次：函数调用能力本身、工具接入协议、以及面向 AI 编程的现成工具/技能集合。

## 三个层次

| 层 | 解决的问题 | 代表 |
| --- | --- | --- |
| Function Calling | 模型如何稳定输出「调哪个函数、传什么参数」 | OpenAI tools API、各家兼容接口 |
| 工具接入协议 | 工具如何一次实现、处处接入，而不是每个 Agent 重写一遍 | [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)（Model Context Protocol） |
| 工具/技能资产 | 现成可用的能力包与规范 | [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)、superpowers、各类 code-agent 内置工具 |

### Function Calling

模型不直接执行代码，而是输出 JSON 形式的意图（函数名 + 参数），由客户端执行后把结果作为 tool message 回传。关键工程点：

- **schema 即契约**：参数用 JSON Schema 描述，描述写得越清楚（含枚举、示例、边界），误调用率越低。
- **结果必须回写上下文**：否则模型「刚做完就忘」，无法基于结果继续推理。
- **副作用走审批**：删改文件、下单付款等动作要经策略层和人工确认，设计参考 Codex 的沙箱/策略/审批/schema 四层（fail closed）。
- **并行/顺序调用**：无依赖的调用可并发；有依赖的由模型多轮决策。

### MCP：工具接入标准化

没有协议时，N 个 Agent × M 个工具要写 N×M 个适配；[MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 把它降为 N+M：工具实现为 MCP Server，任何支持 MCP 的 Agent（Client）都能发现（list tools）并调用。这与 JDBC/ODBC 之于数据库、LSP 之于编辑器是同一种「统一驱动」思想。

### Skill：打包可复用的做事方法

[Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) 比单个函数粒度更大：一个 `SKILL.md` + 脚本 + 参考资料，描述「遇到某类任务该按什么步骤做、有哪些约束和坑」，按需加载（渐进式披露）。自进化 Agent（如 [Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md)）能在使用中自动创建和修补自己的 Skill。

## AI 编程工具集

面向 code agent 的「超能力」工具箱，通常以 Skill / 指令集形式分发：

- [superpowers-zh](https://github.com/jnMetaCode/superpowers-zh)（AI 编程超能力 · 中文增强版）：给编码 Agent 用的方法论与技能集合，覆盖需求拆解、TDD、调试、子代理委派等工作流。
- 各 code agent 的内置工具：文件读写、grep/glob、shell 执行、浏览器自动化等——它们是 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 的预置工具间，让 Agent 面对真实代码库而非单轮问答。

工具设计的通用经验：**给动作而不是给数据**（写操作封装成显式工具）、**工具内做校验与错误回传**（让模型能自我纠正）、**读多写少、写操作可审计**。

## Links

- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) — Agent 四构成
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 工具闭环的真正所有者、四层安全模型
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) — 工具接入标准协议
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) — 技能包规范
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) — 平台侧的插件/工具生态（Coze 插件、Dify 插件市场）
- [Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) — 自动创建/修补 Skill 的自进化案例
- [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md) — 生产级工具路由与沙箱实例

## References

- [superpowers-zh（AI 编程超能力 · 中文增强版）](https://github.com/jnMetaCode/superpowers-zh)
