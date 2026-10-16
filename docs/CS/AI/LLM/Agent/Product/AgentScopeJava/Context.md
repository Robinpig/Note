## Introduction

本分册覆盖 AgentScope Java 的**状态与上下文管理**：`AgentState` 与它的四种存储实现、`RuntimeContext` 的 per-call 语义、Harness 如何把 System / 对话 / 状态 / 参考材料组织成一次模型请求、上下文压缩与工具结果卸载的取舍，以及两层长期记忆。这是 Java 版与 Python 版差异最大的区域之一——Python 版把压缩做进 `ContextConfig` 三 ratio，Java 版拆成「预算 → 卸载 → 压缩」三段管线，并且第一次把「模型实际拿到了什么」做成了可检查的 `ContextManifest`。

核心认知：**压缩后的工作历史用于「接着做」，长期记忆用于「以后还记得」，完整 Session Log 用于「回看当时发生了什么」——三者互不替代**。

## AgentState

`AgentState`（`io.agentscope.core.state.AgentState`）是 agent 当前运行状态的完整快照：

| 字段 | 内容 |
| :--- | :--- |
| `getSessionId()` | 本份状态所属会话标识 |
| `getUserId()` | 所属用户（匿名为 null） |
| `getContext()` / `contextMutable()` | 当前对话历史（用户输入、assistant 回复、工具调用与结果） |
| `getSummary()` | 压缩后的摘要 |
| `getPermissionContext()` | 工具权限规则 |
| `getPlanModeContext()` | Plan Mode 是否激活、计划文件路径 |
| `getTasksContext()` | Todo、修订号，以及可选的任务目标、需求、证据绑定版本和验证摘要 |
| `getToolContext()` | 工具组激活状态（activatedGroups） |

执行控制与 AgentState 分离——每次调用有独立的 `InterruptControl`，不随会话历史持久化。任务状态**不是自动业务判定**：Todo 由 `todo_write` 或应用更新、目标由 `beginTask` 设置、要求由可信调用方 `decide`、验证摘要由显式 `VerificationService` 调用产生；框架保存字段不代表会自动推断，Todo 完成 / 要求确认 / 检查通过是三个不同含义。

## AgentStateStore

持久化抽象，按 `(userId, sessionId)` 二元组寻址槽位：

| 实现 | 模块 | 适用 |
| :--- | :--- | :--- |
| `InMemoryAgentStateStore` | agentscope-core | 单元测试 / 单进程 demo，退出全丢 |
| `JsonFileAgentStateStore` | agentscope-core | 单机开发，按 (userId, sessionId) 分目录落 JSON；HarnessAgent LEGACY 模式默认，根目录 `~/.agentscope/state/<agentId>/` |
| `RedisAgentStateStore` | agentscope-extensions-redis | 多副本生产首选，支持 Jedis / Lettuce / Redisson（Standalone / Cluster / Sentinel） |
| `JdbcAgentStateStore` | agentscope-extensions-jdbc | 需要沉淀进关系型库（审计 / 报表） |

自动持久化链路：配了 store 时每次 call 结束把整份 `AgentState` 以 `agent_state` 键写回，下次同 `(userId, sessionId)` 的 call 自动加载。**Agent 实例对 session 无状态**——读写哪个槽位由该次调用的 `RuntimeContext` 决定，缺省回退 `defaultSessionId`。支持版本控制的后端（Redis / JDBC）保存时用 CAS，冲突由 `ConflictPolicy` 决定；CAS 不回滚已发生的工具副作用。

两条硬校验：`filesystem(RemoteFilesystemSpec)` 没换 stateStore 也没配 distributedStore → `build()` 直接抛 `IllegalStateException`；沙箱模式配本地 store → 构建期 warning（沙箱状态不能跨 JVM 恢复）。

### Session Log: The Default Authority

**HarnessAgent 默认是 EVENT_LOG 模式，不是 AgentStateStore**：`AgentState` 从原生 Session Log 的 checkpoint 及后续可应用事实重建，保存时向日志提交 checkpoint；`AgentStateStore` 只服务 LEGACY 模式与显式迁移。两者的关系与完整恢复链路见 [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)。

旁路读取用 `agent.getAgentState(userId, sessionId)`（`getContext().size()` / `toJson()`）；`clearContext(userId, sessionId)` 清空模型可见的历史缓冲与摘要（保留权限、工具、任务、Plan Mode 等非对话状态，立即持久化），适合「同会话开新话题」——完整新会话仍应用新 sessionId。1.0 的 `InMemoryMemory` / `LongTermMemory` 接口在 2.0 已 `@Deprecated(forRemoval = true)`，新代码用 `AgentState.getContext()` + `AgentStateStore`。

## RuntimeContext

`RuntimeContext`（`io.agentscope.core.agent.RuntimeContext`）是 per-call 元数据袋，三类槽位：

| 槽位 | 设置 / 读取 |
| :--- | :--- |
| 会话字段 | `sessionId` / `userId`（builder 设置，getter 读） |
| 字符串属性 | `put(String, Object)` / `get(String)`，任意 key-value |
| 类型化属性 | `put(Class<T>, T)` / `get(Class<T>)`，按类型注入业务 POJO |

外加 `getRunId()`：恒非 null，显式传入或 build 时生成 32 位 hex。它的用途是把一次执行在执行层与产品层串起来——中间件、工具、日志、tracing 都能用同一个 runId 关联；`prepareRun` / `prepareCall` 的句柄直接采纳 ctx 的 runId（`run.runId() == ctx.getRunId()`）；子 agent 派生上下文拷贝 runId，即使子 agent 有独立 sessionId 也能串起整条链路。每次创建新执行句柄要用**新的 RuntimeContext**（要保留会话与其他属性可用 `RuntimeContext.builder(previous).runId(null).build()`）；启用原生日志后重复使用已记录的 runId 会被拒绝。

关键边界：**自由 / 类型属性不进 AgentState、不落盘**；`sessionId` / `userId` 才驱动持久化寻址。`ctx.getAgentState()` 是框架在 call 入口注入的 call-scoped 状态，中间件和工具应读它（或 `RuntimeContext.resolveAgentState(ctx, agent)`），**不要用无参 `agent.getAgentState()`**（已废弃，返回匿名用户默认槽位）。

## Building The Model Input

Harness 在最终模型调用边界统一组织输入，顺序固定四层：

| 顺序 | 内容 | 例子 |
| :--- | :--- | :--- |
| System | 合并后的稳定指令、项目规则、模式规则（AGENTS.md、工作原则、环境信息、instruction） | 编码约定、修改后跑测试 |
| 对话历史 | 用户输入、assistant 消息、工具调用与结果；必要时含历史摘要 | 已读代码、刚才的测试结果 |
| 当前状态 | 从任务、计划和动态来源生成的临时消息（TASK_STATE、RUNTIME_STATE） | 当前待办、计划模式、最新构建状态 |
| 参考材料 | 工作区记忆、知识资料、动态参考（HARNESS_CONTEXT） | 项目背景、相关文档片段 |

工具 Schema 随请求单独提供，也占预算。**这些临时组织不出现在持久化对话历史里**，不会每轮重复追加。工作区文件（AGENTS.md / MEMORY.md / knowledge/）在一次 call 开始时加载，执行期间改动下一次 call 才生效。

### ContextSource: Dynamic Business Data

会变化的业务信息注册 `contextSource`，每次准备推理请求时重新读取：

```java
builder.contextSource("build-status", request -> Mono.just(List.of(
        ContextBlock.runtime("latest", "当前构建：测试失败，登录模块有 2 项失败。")
)));
```

`ContextRequest` 带 agentId / userId / sessionId / callId / purpose 可据此选数据（业务服务仍需自行鉴权）。`ContextBlock.runtime` 提供当前事实，`ContextBlock.reference` 提供参考资料（可附 `withRevision` 与 `withPriority`）。动态来源**不能创建 System 指令**——稳定业务规则用 `instruction`。

失败策略：默认失败即停止准备请求（超时 5s）；可有可无的材料配 `SourceFailurePolicy.OMIT`（省略本次失败来源，不悄悄沿用旧值，也不能用于含 `required` 块的来源）。来源应只读、可安全重复调用——一次执行可能准备多个模型请求，不要在这里扣费或执行业务动作。返回约定：`Mono<List<ContextBlock>>`，无内容返回空列表；`Mono.empty()` 不等同「没有材料」，会作为加载失败处理。

### Budget And Manifest

`ContextPolicy` 管最终请求预算（最大输入预算、模型输出预留、安全余量、token 估算器、观察回调）；模型没报窗口时输入预算回退 64,000 token。`ContextManifest` 是每次准备模型请求自动生成的清单——`callId` / `purpose` / `model` 标识这次请求，`estimatedInputTokens()` / `inputLimit()` 是估算量与上限（不是供应商账单用量），`items()` 列出保留的消息 / 工具 Schema / 材料元数据，`transforms()` 记录 `tool_result_offload`、`history_compaction`、材料省略与来源失败，`validation()` 给出 passed / budget_exceeded / invalid_tool_pairs / state_conflict 等结论。

排查「模型没看到某条信息」的标准动作：先看 `validation()` 和预算，再按 `sourceId()` 找材料——在 `items()` 里找到且版本对，说明已纳入本轮；没找到就看 `transforms()`：`omitted_for_budget:...` 是预算不足被省略，`source_unavailable:...` 是 OMIT 的来源读取失败。构建过早失败时清单可能没有条目、token 为 -1，不能据此认定全部被省略。

## Compaction And Eviction

请求变长时按「先减负担、再压缩历史」的顺序处理：

### Tool Result Eviction

超大工具结果全文写盘（工作区逻辑路径 `large_tool_results/`），上下文只留首尾各约 2,000 字符预览 + 文件位置，模型用 `read_file` 按需取回。**默认阈值 80,000 字符**；`read_file` / `write_file` / `edit_file` / `memory_search` / `memory_get` / `session_search` 默认不参与卸载（读取工具应合理分页，避免回读完又占满窗口）。

### Compaction

默认启用。先做不需要模型的轻量处理（裁剪较旧的大量工具输出，默认保护最近约 40,000 token 的工具输出；更早的可裁剪内容累计约 20,000 token 时缩为预览；`write_file` 类长参数可开 `truncateArgs` 预截断），仍满足条件再调模型把较早对话整理成摘要（含会话目标、重要结论、文件产物、下一步）。

| 参数 | 默认 | 含义 |
| :--- | :--- | :--- |
| `triggerMessages` | 50 | 按条数触发（0 关闭） |
| `triggerTokens` | 0 | 按 token 估算触发（0 = 依据最终请求的对话剩余预算动态计算） |
| `keepMessages` | 20 | 保留尾部条数 |
| `keepTokens` | -1 | -1 动态计算；0 用 keepMessages；>0 固定 token 预算 |
| `flushBeforeCompact` | true | 压缩前先把新事实写入日流水账 |
| `summaryPrompt` | 默认 | 摘要 prompt（必须含 `{messages}` 占位符） |
| `model` | null（用主模型） | 压缩摘要的独立模型 |

压缩维护工具调用与结果的配对，保留范围不能把一次工具交互切开。摘要与压缩可用更轻量的辅助模型（`CompactionConfig.builder().model(...)`）。

### Overflow Fallback

发送前检查最终预算与工具配对，System / 必需材料仍放不下会抛 `ContextBudgetExceededException`。估算通过后供应商仍可能报溢出：压缩未禁用时，默认 EVENT_LOG 模式会**强制压缩并在同一次执行内重发当前推理一次**——不重新提交用户任务、不重跑已完成的工具；仍失败才把错误返回调用方。

## Long-Term Memory

两层结构：`memory/YYYY-MM-DD.md`（日流水账，只追加不去重）+ `MEMORY.md`（策划后的长期事实，每次 call 加载为**参考上下文**，不是 System 指令）。三处独立 LLM 调用，定制时最容易混：

| # | 操作 | 写入目标 | 定制入口 |
| :--- | :--- | :--- | :--- |
| 1 | Flush —— 从对话窗口抽取长期事实 | `memory/YYYY-MM-DD.md`（追加） | `MemoryConfig.flushPrompt(...)` |
| 2 | Consolidation —— 日流水账合并去重 | `MEMORY.md`（整体重写） | `MemoryConfig.consolidationPrompt(...)` |
| 3 | Compaction summary —— 对话前缀蒸馏 | 注入当前上下文 | `CompactionConfig.summaryPrompt(...)` |

前两个是「沉淀长期记忆」归 `MemoryConfig`，第三个是「压缩当下上下文」归 `CompactionConfig`；三处默认共享主模型，各自支持 `.model(...)` 覆盖。Flush 三个触发点：每次 call 结束（`flushTrigger` 可改 NEVER 或 THROTTLED，首次符合条件的 call 立即放行，间隔只限制后续）、压缩前预提取（`flushBeforeCompact`）、上下文溢出兜底。自定义 consolidation prompt **必须包含恰好两个 `%d` 占位符**（max-tokens 与 max-chars），否则 build 时直接拒绝。

`MemoryConfig` 其余字段：`consolidationMaxTokens`（默认 4,000）、`consolidationMinGap`（默认 30 min）、`dailyFileRetentionDays`（默认 90，超期归档到 `memory/archive/`）。后台维护按节流跑：没有新增日流水账内容时 consolidation 跳过 LLM 请求。

Agent 自用四个工具：`memory_search`（关键词扫，`matchMode` 支持 phrase / all / any）、`memory_get`（读指定行范围）、`memory_save`、`session_search`。记录边界为一行，不跨记录组合关键词；不自动拆分连续中文，不解析「昨天」等日期表达式。全关用 `disableMemoryHooks()` + `disableMemoryTools()`（核选项，只想节流用 `flushTrigger`）。

## Links

- [AgentScope Java 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [AgentScope Java 会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [AgentScope Java 工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md)
- [Compaction Theory](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [Harness Theory](/docs/CS/AI/LLM/Agent/Theory/Harness.md)

## References

- [AgentScope Java 上下文与 AgentState](https://java.agentscope.io/v2/zh/docs/building-blocks/context)
- [AgentScope Java 上下文管理](https://java.agentscope.io/v2/zh/docs/harness/context)
- [AgentScope Java 记忆](https://java.agentscope.io/v2/zh/docs/harness/memory)
