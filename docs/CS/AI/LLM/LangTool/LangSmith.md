## Introduction

LangSmith 是 LangChain Inc. 的商业侧产品，官方定位是 **Agent Engineering Platform**。它要解决的不是"怎么把 Agent 搭出来"，而是"怎么把 Agent 的开发变成可重复的工程"——把"改完就发、发了再看"变成 **建 → 测 → 上线 → 观测 → 迭代** 的闭环。

两个容易被忽略的属性，先摆在前面：

- **它是框架无关的**。不是 LangChain 的专属调试器：官方提供 Python / TypeScript / Go / Java SDK，主流 Agent 框架都有原生追踪，还能通过 OpenTelemetry 接入任意技术栈。
- **它改过名字**。原来的 **LangGraph Platform 已被并入 LangSmith 产品线，现在叫 LangSmith Deployment**。查部署文档、翻旧教程时都要按新名字找。

在家族里的位置是**最上面一层（Platform）**：下面的 [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md) 与 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 负责把 Agent 跑起来，它负责让你看见跑得怎么样，并把它推进生产。

## 模块划分

| 模块 | 解决什么 |
| --- | --- |
| Observability | 把一次 run 拆成结构化时间线，看清每一步的顺序与因果关系；多轮对话用 message threading 归组；带 analytics 与 AI 驱动的模式洞察 |
| Evaluation | 从生产 trace 造数据集，用可复用的 LLM-as-judge 与多轮 eval 打分，人类反馈用于校准；支持在线与离线打分 |
| Deployment | 原 LangGraph Platform。Agent server 自带记忆、会话线程与持久 checkpoint；支持人在环路、输入并发、后台 Agent、类型化流式；原生支持 A2A 与 MCP 协议 |
| Fleet | 无代码 Agent 构建器：用日常语言描述需求，做成可复用的定时 Agent，可接远程 MCP server 扩展工具 |
| Engine | 自动把生产失败聚成按优先级排序的 issue，在 trace 与代码里定位根因，**并把修复方案提出来供你审阅** |

此外还有两项配套能力：**Sandboxes**（给 Agent 生成的代码提供临时隔离沙箱，可快照与 fork，Engine 依赖它）与 **LLM Gateway**（成本控制、限流、模型 fallback、PII 与密钥脱敏）。

注意 Evaluation 的设计意图：它**不是让你手工写测试用例**，而是把线上真实 trace 转成测试集。这条链路是否跑通，决定了这套东西是"又一个监控面板"还是"能持续变好的系统"。

## 接进去

LangChain / LangGraph 代码一行都不用改，两个环境变量就能开始追踪：

```shell
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=<your-api-key>
```

跑起来就有 trace，默认落到名为 `default` 的项目。

> [!WARNING]
> **账号不在 US 区域时，必须额外设 `LANGSMITH_ENDPOINT`**，否则 API key 不被识别、请求直接认证失败。对应关系：GCP EU 用 `https://eu.api.smith.langchain.com`，GCP APAC 用 `https://apac.api.smith.langchain.com`，AWS US 用 `https://aws.api.smith.langchain.com`。**URL 末尾不能带斜杠**，否则也会引发认证错误。

其他常用变量：`LANGSMITH_PROJECT`（自定义项目名）、`LANGSMITH_WORKSPACE_ID`（一个 API key 关联多个工作区时指定）。

⚠️ **命名已变更**：旧教程里的 `LANGCHAIN_TRACING_V2`、`LANGCHAIN_PROJECT` 已经被 `LANGSMITH_TRACING`、`LANGSMITH_PROJECT` 取代（后者仅在 JS SDK < 0.2.16 时才需要）。照着旧文章配环境变量会静默不生效——这类"变量名变了但没人报错"的坑，和内核里 sysctl 存在却不生效是同一族问题。

## 两个实操坑

- **无服务器环境会丢 trace**。追踪默认在后台线程上报，进程可能在数据送出去之前就结束了。serverless 下设 `LANGCHAIN_CALLBACKS_BACKGROUND=false`；Python 还可以在退出前调 `wait_for_all_tracers()` 强制等待。
- **只想追踪一部分调用**。Python 用 `ls.tracing_context(enabled=True/False)` 精确开关，或用 `@traceable` 手工划定 span。跨服务场景可以 `get_current_run_tree().to_headers()` 取出上下文头并传给下游，实现分布式追踪。

## 部署形态与自托管

平台有三种托管形态：**Cloud**（全托管，数据在 LangChain 云，US 或 EU 区域）、**Hybrid**（控制面在云、数据面自持）、**Self-Hosted**（全部在自家 VPC）。

> [!WARNING]
> **自托管不等于功能对等**。Deployment、Fleet、Insights、Chat、Sandboxes、Engine 这些都需要 **Enterprise 计划**才能开启，且各有独立组件（Fleet / Insights / Chat 各自需要 api-server + queue + postgres + redis，靠 KEDA 按队列长度扩容），部署在 Kubernetes 上。基础平台可以自托管，但真正值钱的那几块要买单。

配置项里也留着这次改名的痕迹：**v0.12.0 起 `langgraphPlatform` 选项废弃，改用 `config.deployment`**——这正是"LangGraph Platform 变成 LangSmith Deployment"在配置文件里的具体表现。升级旧自托管实例时，照着老配置改会直接不生效。

## 怎么选

一句话：**要"看得见、测得了、部署得起"，且数据出内网没问题，直接用它；数据不能出内网，就得走自托管，且准备好 Enterprise 预算。**

观测与评测这一层不止一家，同类候选还有 LangFuse、Arize Phoenix、Comet Opik、W&B Weave、Braintrust、Helicone 等。它们的分野通常不在功能清单，而在三个硬条件：**能不能自托管、用的是什么许可、认不认 OpenTelemetry**。LangSmith 满足第三条，前两条要花钱——这也是它和开源方案之间最真实的取舍。

## Links

- [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)
- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [Deep Agents](/docs/CS/AI/LLM/LangTool/DeepAgents.md)
- [LangTools](/docs/CS/AI/LangTools.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Platform](/docs/CS/AI/LLM/Platform/Platform.md)

## References

1. [LangSmith 文档](https://docs.langchain.com/langsmith/home)
2. [Trace LangChain applications](https://docs.langchain.com/langsmith/trace-with-langchain)
3. [Enable additional LangSmith features（自托管）](https://docs.langchain.com/langsmith/self-host-sandboxes)
4. [LangSmith Engine](https://docs.langchain.com/langsmith/engine)
