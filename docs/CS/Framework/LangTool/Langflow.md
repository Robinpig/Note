## Introduction

Langflow 是一个开源的**低代码可视化 LLM 应用编排工具**：把提示词、模型、检索器、向量库、工具、记忆、输出解析都做成带类型端口的积木节点，在画布上连线组成 flow，然后发布成 REST API、WebSocket，或直接导出成 Python 脚本。

它的出身值得记一笔：2023 年由 Logspace（巴西的一家咨询公司）发起，**最初只是 LangChain 的一层可视化外壳**，后来长成了独立的编排工具；2024 年 4 月 DataStax 收购 Logspace；2025 年 2 月 IBM 宣布收购 DataStax，于是 Langflow 现在挂着 "DataStax, an IBM company" 的名头，但**核心代码依旧是 MIT 许可**，免费、可自托管、可商用，这一点从未改变。

它与 [LangChain](/docs/CS/Framework/LangTool/LangChain.md) 是同源兄弟（编译出来的 flow 就是 LangChain 代码），与 [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md) 是互补关系（后者是代码层状态机，Langflow 是它之上的画布），与 [Dify](/docs/CS/AI/LLM/Dify.md) / [Flowise](/docs/CS/AI/LLM/Platform.md) 属同一赛道的不同选择。

## 它的核心差异化：可视化不锁死你

低代码工具的通病是"上手快、深入时卡死"——做到一半发现表达不了，只能重来。Langflow 的解法是**每个组件都是可编辑的 Python 类**：画布上搭骨架，需要定制的地方直接掀开盖子改底层 Python，不必在"全可视化"和"全代码"之间二选一。自定义组件带上输入/输出端口和 build 方法，Langflow 会自动为它生成 UI，还能打包分享给团队复用。

一句话概括它的卖点：**不是"不用写代码"，而是"可以先不写代码，但随时能写"。**

## 关键能力与这片画布的边界

| 能力 | 说明 |
|------|------|
| 组件库 | 数百个内置组件：各类 LLM/Embedding/向量库/文档加载器/切分器/检索器/Agent/工具/记忆/输出解析器 |
| 自定义组件 | 任意 Python 类可变成画布组件，可就地编辑、可分享复用 |
| Playground 调试 | 不用搭完应用就能测，支持单步执行和单独跑某个组件验证依赖 |
| 发布形态 | REST API（`POST /api/v1/run/{flow_id}`）、WebSocket、导出 JSON、**导出可运行的 Python 脚本** |
| MCP | 既支持 MCP Client（调用外部 MCP Server），也能把整条 flow **暴露为 MCP Server** 给 Claude Desktop / Cursor 等调用 |
| 桌面版 | Langflow Desktop（Electron），Windows/macOS 一键装，本地开发不必配 Python 环境 |
| 可观测 | 可接 LangSmith、LangFuse 等做逐节点 Trace |
| 会话记忆 | 会话管理器支持一条 flow 同时持有多条独立对话历史 |

**边界也很清楚，别在画布上硬撑**：超过约 20 个节点后，连线会变成一团难以维护的毛线；开源版**没有内置 SSO 与 RBAC**，多租户/受监管场景需要额外的企业方案或自建中间件；高并发下的 CPU 与内存表现是已知短板。这些情况的正确答案通常都是"落回代码"。

## 版本与部署（含一条重要变更）

- **当前稳定版**：1.11.4（PyPI，2026-08），要求 Python 3.10–3.14；默认端口 `7860`。
- **发版节奏极快**（近乎周更），好处是功能迭代快，代价是版本间可能有破坏性变更——**生产务必锁死版本号**，先看 changelog 再升级。
- ⚠️ **DataStax 托管的 Langflow Cloud 已于 2026-03-09 宣布废弃、2026-04-09 关停**，自托管成为默认选项。原本依赖托管云免费层的团队必须迁移。

```shell
# 最快试用
pip install langflow -U
langflow run                      # → http://localhost:7860

# 正式一点：Langflow + Postgres
git clone https://github.com/langflow-ai/langflow.git
cd langflow/docker_example && docker compose up -d
```

一条必说的安全提醒：`LANGFLOW_AUTO_LOGIN=true` 只适合本机试玩。**只要服务暴露到本机之外，就必须关掉它并设置 `LANGFLOW_SUPERUSER` 与 `LANGFLOW_SUPERUSER_PASSWORD`**——否则画布和你填进去的模型 API Key 等于裸奔在公网上，这是自托管工具最常见的事故来源。

## 怎么选

| 场景 | 建议 |
|------|------|
| Python 团队做 RAG 原型，之后可能转成代码 | **Langflow**（同赛道最快，且能落回 Python） |
| 想要开箱即用的 LLM 应用平台成品（多人协作、日志、评测、限流） | [Dify](/docs/CS/AI/LLM/Dify.md) |
| 前端 / Node 技术栈，想 15 分钟出个能聊的知识库 | Flowise |
| 要深度控制状态机、长任务、断点恢复 | [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md) |
| 业务流程自动化为主，AI 只是其中一步 | n8n |

Langflow 最适合的是**"先快速验证、后慢慢落地"**这条路径：原型阶段用它把 LLM 应用搭出来验证想法，确认可行后再把关键流程导出成代码接入自有工程体系。反过来，如果需求只是"调几个 API 的小脚本"，上画布是负担而非帮助。

## Links

- [LangChain4j](/docs/CS/Framework/LangTool/LangChain4j.md)
- [LangTools](/docs/CS/AI/LangTools.md)
- [MCP](/docs/CS/AI/LLM/MCP.md)
- [RAG](/docs/CS/AI/RAG.md)

## References

1. [Langflow 官网](https://www.langflow.org/)
2. [Langflow 开源仓库](https://github.com/langflow-ai/langflow)
3. [Langflow 文档](https://docs.langflow.org/)
4. [Langflow Review 2026: Visual AI Workflow Builder for LLM Orchestration（含 Langflow Cloud 关停时间线）](https://baeseokjae.github.io/posts/langflow-review-2026)
