# Context

## Introduction

本分册覆盖 AgentScope Java 的**状态与上下文管理**：`AgentState` 与它的存储实现、`RuntimeContext` 的 per-call 语义、Harness 如何把 System / 对话 / 状态 / 参考材料组织成一次模型请求、上下文压缩与工具结果卸载的取舍，以及两层长期记忆。

本分册所有类名、字段、默认值均核对自本地 `v2.0.4` 源码树（`agentscope-core/.../state/`、`.../memory/`，`agentscope-harness/.../memory/`、`.../middleware/`）。**最重要的一条订正：core 的 `memory` 包在 2.0.0 已整体废弃**——「Long-term memory is removed; conversation context now lives on `AgentState`」，v2 的记忆能力全部迁到 harness 层。

核心认知：**压缩后的工作历史用于「接着做」，长期记忆用于「以后还记得」，完整 Session Log 用于「回看当时发生了什么」——三者互不替代**。

## AgentState

`AgentState`（`state/AgentState.java`）是当前工作状态的完整快照，字段（源码顺序）：

```java
private final String sessionId;
private final String userId;
private String summary;                        // 压缩摘要
private final List<Msg> context;               // 工作上下文（可变）
private String replyId;
private int curIter;
private boolean shutdownInterrupted;
private PermissionContextState permissionContext;
private final ToolContextState toolContext;
private final TaskContextState tasksContext;
private final PlanModeContextState planModeContext;
```

访问器要点：`getContext()` 返回只读视图，**`contextMutable()` 才是可变入口**（压缩中间件就是先 `contextMutable()` 压实旧结果再落盘，防 legacy hook 把原始结果藏起来）；`toJson()` / `fromJsonString(String)` 提供序列化；Builder 支持 `sessionId/userId/summary/context/addMessage/replyId/curIter/shutdownInterrupted/permissionContext/toolContext/tasksContext/planModeContext`。

三个子状态类把不同关注点拆开：`PermissionContextState`（权限模式 + 工作目录 + 三张规则表）、`ToolContextState`、`TaskContextState`（任务/todo）、`PlanModeContextState`（`planActive` + `currentPlanFile`）。

## AgentStateStore

`AgentStateStore`（`state/AgentStateStore.java`）是按 **`(userId, sessionId)` 寻址 + 一个状态键**的持久化接口：

```java
long UNVERSIONED = -1L;   // 不支持乐观并发的后端哨兵；CAS 冲突时也返回它
void save(String userId, String sessionId, String key, State value);                 // 全量替换
void save(String userId, String sessionId, String key, List<? extends State> values);
<T extends State> Optional<T> get(String userId, String sessionId, String key, Class<T> type);
boolean exists(String userId, String sessionId);
void delete(String userId, String sessionId);
Set<String> listSessionIds(String userId);
```

javadoc 明确的槽位约定：`sessionId` 非空非空白；**`userId` 可空，`null` 表示匿名/单租户调用方**（CLI、测试），实现把所有匿名会话归到单一命名空间；调用方**不得**手工拼接两者，由实现决定怎么合成存储键。

并发控制：`supportsOptimisticConcurrency()` 默认 false，此时 `saveIfVersion(...)` 退化为无条件 `save`；支持时走 `getVersioned(...)` / `saveIfVersion(...)` 的 CAS。

**实现只有两个**：`InMemoryAgentStateStore`（测试用）与 `JsonFileAgentStateStore`（本地 JSON 文件）。默认本地根是 `~/.agentscope/state/<agentId>/`，可用 builder 的 `stateStore` 替换。

⚠️ **定位变化**：v2 默认是 **EVENT_LOG 模式**——`AgentState` 的 checkpoint 与完整执行事实都进原生 Session Log，`AgentStateStore` 退化为「LEGACY 恢复来源 + 显式迁移来源」。另有两个辅助类：`LegacyStateLoader`（读旧格式）、`VersionedState` / `ConflictPolicy`（版本与冲突策略）、`ConcurrentSessionModificationException`（CAS 冲突）、`SessionInfo`、`ReadCacheEntry`、`ListHashUtil`。

## RuntimeContext

`RuntimeContext`（`agent/RuntimeContext.java`）是 **per-call 瞬态上下文**，决定这次调用读写哪个状态槽位：

| 成员 | 说明 |
| :--- | :--- |
| `getSessionId()` / `getUserId()` | 身份 |
| `getAgentState()` / `setAgentState(...)` | 本次执行挂的状态 |
| `getToolExecutionContext()` / `asToolExecutionContext()` | 工具执行上下文 |
| `getToolRequestConfig()` / `setToolRequestConfig(...)` | 本次调用的工具面（激活组、过滤） |
| `getExtra()` | 字符串键属性表 |
| `put(String, Object)` / `put(Class<T>, T)` | **两套属性槽**：字符串键 + 类型化键 |
| `resolveAgentState(ctx, fallbackAgent)` | 静态解析：ctx 没有就退回 agent 自带的 |

Builder 支持 `sessionId/userId/agentState/put/putAll/toolExecutionContext/toolRequestConfig/from(source)`。类型化槽（`put(Class<T>, T)`）是框架内部传递单例对象的通道——例如子 Agent 的 `AgentSpawnTool.CTX_FORCE_SYNC`、`CTX_EXPOSE_TO_USER` 都走这类 key。

## Context Construction

工作区材料每次 call 读取一次，由最终 Context 构建器分层组织，**不把全部文件直接追加进 System**：

| 材料 | 模型中的位置 | 预算行为 |
| :--- | :--- | :--- |
| `AGENTS.md` | System / `project_rules` | 不直接淘汰，计入最终预算 |
| 工作原则、环境信息 | System / `working_principles`、`environment` | 计入最终预算 |
| `MEMORY.md` | USER 参考消息 / `HARNESS_CONTEXT`，`kind=memory` | 准备时可截断，最终预算不足时可省略 |
| `knowledge` 入口及路径索引 | USER / `HARNESS_CONTEXT`，`kind=knowledge` | 可因最终预算省略 |
| `additionalContextFile` | USER / `HARNESS_CONTEXT`，`kind=additional` | **必需材料，不能任意淘汰** |

- `maxContextTokens` 默认 **8000**，只用于工作区材料准备，**不代表**最终模型输入上限；
- 最终预算还包括 System、历史、状态和工具 Schema，仍超限则**拒绝请求**；
- `MEMORY.md` 在记忆工具与 hooks 都关闭时不加载；
- 知识目录只加载入口和索引，其余文件由模型按需读取；
- 同一次 call 内文件变化不自动刷新，下一次 call 重新加载。

## Compaction

`CompactionConfig`（harness `memory/compaction/CompactionConfig.java`）的默认值全部是**动态**的：

| 项 | 默认行为 |
| :--- | :--- |
| 触发 | 估算 token 数达到 `model.contextWindow - reserved(20k)` 时动态触发；模型不上报上下文窗口时退化为固定 token 数或 **50 条消息**（先到者） |
| 保留尾部 | 动态算 `min(8k, max(2k, usable * 0.25))` token；模型不上报窗口时退化为 **20 条消息** |
| Prune | **默认开启**：聚合旧工具结果输出，可裁剪总量超 **20k** token 时修剪（保护最近 **40k** token） |
| 摘要 | 开启 |

`ConversationCompactor` 的六步算法（javadoc 原文）：

```text
1. Check trigger    — token 数或消息条数超阈值
2. Determine cutoff — 找保住尾部预算的最早下标；绝不把 ASSISTANT tool-call 和它的 TOOL result 拆开
3. Memory flush     — （可选）经 MemoryFlushManager 从前缀抽取长期记忆
4. Message offload  — （可选）把完整对话持久化进 session JSONL
5. Summarize        — 一次 LLM 调用把前缀蒸馏成结构化摘要
6. Rebuild          — 返回 [summaryUserMsg] + preservedTail
```

调用方（`CompactionMiddleware`）负责同时更新 agent 工作记忆与面向 LLM 的消息列表；该中间件在 `onReasoning` 触发，并把 `ReasoningInput` 重建成 `[systemMsg] + ...`。

压缩事件进 Session Log：`compaction/start` / `compaction/end`，其中 **`compaction/end` 的载荷含 `compactionId`、`status`、`beforeMsgCount`、`beforeTokenCount`**；仅当 `status` 为 completed 时才带 `afterMsgCount` / `afterTokenCount`——失败或取消时**不伪造压缩后指标**。

## Tool Result Eviction

`ToolResultEvictionConfig` 与压缩**正交**，这一点 javadoc 说得最清楚：

> **Eviction addresses context *width*** — individual messages that are too large.
> **Compaction addresses context *depth*** — too many accumulated messages.

两者触发条件与生命周期事件都不同。机制：单个工具结果的文本内容超 `maxResultChars()`（默认 **80K 字符**）时，`ToolResultEvictionMiddleware` 把完整输出写到 `{evictionPath}/{agentName}/{sanitized-toolCallId}-{contentHash}`，上下文里的 `ToolResultBlock` 换成带 head+tail 预览 + 「用 `read_file` 读全文」指引的紧凑占位符。写盘前先压实 `AgentState.contextMutable()`，防止 legacy pre-reasoning hook 把原始结果藏过持久化清理。

## Memory In V2

⚠️ **core 的 `memory` 包整体废弃**：`LongTermMemory`、`Memory`、`StateBackedMemory`、`InMemoryMemory`、`AgentStateMemoryView`、`LongTermMemoryTools`、`StaticLongTermMemoryHook`、`LongTermMemoryMode` 全部 `@Deprecated(forRemoval = true, since = "2.0.0")`。`LongTermMemory` 的 javadoc 原文：「Long-term memory is removed; conversation context now lives on `AgentState#getContext()`」；`Memory`：「Conversation context is now held on ...」。`ReActAgent.Builder` 里的 `longTermMemory(...)` / `longTermMemoryMode(...)` / `longTermMemoryAsyncRecord(...)` 只是 1.x 兼容 setters。

**v2 的两层记忆在 harness**，落点是工作区两个文件：

```text
workspace/
├── MEMORY.md                  ← 策划后的长期记忆，每次 call 加载为参考上下文
└── memory/
    └── YYYY-MM-DD.md          ← 每天追加的事实流水账（未去重）
```

职责边界由两个类严格分开（javadoc 原文）：

| 层 | 文件 | 唯一写者 | 性质 |
| :--- | :--- | :--- | :--- |
| Layer 1 | `memory/YYYY-MM-DD.md` | `MemoryFlushManager` | append-only 日流水账，每次压缩 flush 追加一个带时间戳的小节 |
| Layer 2 | `MEMORY.md` | `MemoryConsolidator` | 全局策划、去重、有界；按周期读取自上次 consolidation 水位以来的日账 + 当前 `MEMORY.md`，让 LLM 合并/去重/裁剪后覆写 |

写入路径：压缩前 `MemoryFlushMiddleware` 从对话前缀抽新事实追加进日账（`onAgent` 的 `doOnComplete`，fire-and-forget 不阻塞 agent 流）；后台节流任务定期合并去重写回 `MEMORY.md`。读取路径：框架自动读 `MEMORY.md`（两层读，filesystem 优先），agent 也可主动调 `memory_search` / `memory_get`。

`MemoryConfig`（harness `memory/MemoryConfig.java`）的可调项与默认值：

| 字段 | 默认 |
| :--- | :--- |
| `mode`（`FlushMode`：`ALWAYS` / `NEVER` / `THROTTLED`） | — |
| `minGap` | — |
| `consolidationMaxTokens` | **4000** |
| `consolidationMinGap` | **30 分钟** |
| `dailyFileRetentionDays` | **90** |
| `sessionRetentionDays` | **180** |
| `flushTrigger` | `FlushTrigger.always()`（`never()` 只关 per-call flush，不动后台维护） |
| `model` / `flushPrompt` / `consolidationPrompt` | null（用默认提示词） |

配套：`MemoryBackgroundTasks`（后台任务）、`memory/.consolidation_state`（记录上次成功合并的时间戳水位）。关掉的开关：`disableMemoryHooks()`（flush + 后台维护）、`disableMemoryTools()`（`memory_search` / `memory_get` / `memory_save` / `session_search`）。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [AgentScope Java 上下文管理](https://java.agentscope.io/v2/zh/docs/harness/context)
- [AgentScope Java 工作区](https://java.agentscope.io/v2/zh/docs/harness/workspace)
- [AgentScope Java 会话日志](https://java.agentscope.io/v2/zh/docs/harness/session-log)
