# Events：扩展事件 / 钩子总表

Pi 的扩展用 `pi.on(event, handler)` 订阅 agent 生命周期事件，`on()` 返回取消订阅的函数。本文是 `main` 分支 `packages/coding-agent/src/core/extensions/types.ts` 中 `ExtensionEvent` 联合类型与 `ExtensionAPI.on()` 全部重载的**权威总表**，纠正了散落各页的旧事件名（如 `beforeToolCall`/`afterToolCall` 已不存在，真实是 `tool_call`/`tool_result` + `tool_execution_*`）。

handler 的通用签名为 `(event, ctx) => R | void`；不同事件对返回值的处理分六种组合模式（见下）。所有事件的精确 payload 字段都在 `types.ts`，下表只列关键字段与行为。

```sequence
Title: 单次 turn 的事件流（生产路径）

participant R as runLoop
participant C as context/context_with_system
participant P as before_provider_*
participant T as tool_call/tool_result
participant E as tool_execution_*
participant B as turn_end
participant S as agent_before_settle
participant D as agent_settled

R->>C: turn_start
R->>C: context (过滤消息, 链式)
R->>C: context_with_system (含system, 链式)
R->>P: before_provider_request (替换payload, 链式)
R->>P: before_provider_headers (改headers, 原地)
P->>P: provider_stream_event (只读, 通知)
P->>P: after_provider_response (通知)
R->>T: message_start/update/end
loop 每个 toolCall
  R->>T: tool_call (Gate: 改input/block)
  R->>E: tool_execution_start/_update/_end (通知)
  R->>T: tool_result (脱敏/替换, 链式)
end
R->>B: turn_end (BoundaryResult: 可提议compaction/context_edit, continue)
B->>S: agent_before_settle (可追加entries)
S->>D: agent_settled (通知)
```

## Handler 组合的六种模式

| 模式 | 语义 | 涉及事件 |
| --- | --- | --- |
| **通知型** | 返回值被忽略，纯观察 | `agent_start` / `agent_end` / `after_provider_response` / `provider_stream_event` / `message_start` / `message_update` / `tool_execution_start` / `tool_execution_update` / `tool_execution_end` / `agent_settled` / `session_start` / `session_compact` / `session_compact_failed` / `session_tree` / `session_shutdown` / `resources_discover` / `mcp_servers_change` / `ui_prompt_start` / `ui_prompt_end` / `model_select` / `thinking_level_select` / `turn_start` / `session_info_changed` |
| **原地修改** | 改 `event` 上的可变字段，后续 handler 见改动 | `before_provider_headers`（改 `headers`）、`before_agent_start`（改 `systemPromptOptions`）、`tool_call`（改 `input`） |
| **链式转换** | 返回值传给下一个 handler，Pi 随后恢复自身状态 | `input`、`context`、`context_with_system`、`message_end`、`tool_result`、`before_provider_request` |
| **Gate（阻断）** | 停止该操作的正常 fallback 路径 | `input`（返回 `handled`）、`tool_call`（返回 `{ block }`）、`user_bash`（返回 `operations`/`result`）、`session_before_switch`/`session_before_fork`/`session_before_tree`/`session_before_compact`（返回 `cancel`） |
| **行为边界（BoundaryResult）** | 看到已提议 entries 与延续决策，可追加 `custom`/`context_edit`/`compaction` 或 `continue` | `turn_end`、`agent_before_settle` |
| **最后覆盖（last override）** | 最后一个返回有效 action 的处理器胜出 | `cache_warming_decision`（返回 `{ action: "warm" | "stop" }`） |

> **fail-safe**：`tool_call` 的 handler 若抛错，调用被阻断（不执行）；`user_bash` 抛错也阻断命令且不 fallback。这是权限控制的兜底。

## A. 启动与资源

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `project_trust` | 受信项目资源加载前（进新目录可能重跑） | `cwd` | 仅**个人 / 显式 CLI 扩展**可参与；返回 `{ trusted: "yes"\|"no"\|"undecided", remember? }` 做信任决策 |
| `resources_discover` | `session_start` 之后 | `cwd`、`reason: startup\|reload` | 返回 `{ skillPaths?, promptPaths?, themePaths? }` 提供额外资源路径 |
| `mcp_servers_change` | 扩展注册/注销 MCP 服务器后 | `servers: RegisteredMcpServer[]` | 供接管已注册服务器连接的 MCP 扩展使用 |

## B. 会话生命周期

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `session_start` | 启动 / 加载 / 重载 / new / resume / fork | `reason`、`previousSessionFile?` | 初始化会话级资源；可从此读 `pi.getMcpServers()`（通知） |
| `session_info_changed` | 会话元信息变化 | `name` | 通知 |
| `session_before_switch` | `/new` 或 `/resume` 触发 | `reason`、`targetSessionFile?` | **Gate**：返回 `{ cancel? }` 取消 |
| `session_before_fork` | `/fork` 或 `/clone` 触发 | `entryId`、`position` | **Gate**：返回 `{ cancel?, skipConversationRestore? }` |
| `session_before_compact` | 压缩前 | `preparation`、`branchEntries`、`reason: manual\|threshold\|overflow`、`willRetry`、`signal` | **Gate + 自定义**：返回 `{ cancel?, compaction? }` 可直接提供 `CompactionResult` 替换默认摘要 |
| `session_compact` | 压缩成功 | `compactionEntry`、`fromExtension`、`reason`、`willRetry` | 通知 |
| `session_compact_failed` | 压缩失败 / 中止 | `reason`、`errorMessage?`、`aborted`、`willRetry`、`fromExtension` | 通知 |
| `session_shutdown` | 退出 / 重载 / 替换 / 切换（汇聚） | `reason`、`targetSessionFile?` | 释放资源，**需幂等** |
| `session_before_tree` | `/tree` 分支导航前 | `preparation: TreePreparation`、`signal` | **Gate + 自定义摘要**：返回 `{ cancel?, summary?, customInstructions?, replaceInstructions?, label? }` |
| `session_tree` | 分支导航后 | `newLeafId`、`oldLeafId`、`summaryEntry?` | 通知 |

> 压缩链路：从 `types.ts` 看，压缩是**一等事件**（`session_before_compact`/`session_compact`/`session_compact_failed`），而非早期某些文档暗示的隐藏钩子；`turn_end` 的 `BoundaryResult` 还可主动提议 `compaction` entry 触发压缩。

## C. Agent 运行

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `before_agent_start` | 运行前（用户消息或空闲 custom 触发） | `systemPrompt`、`systemPromptOptions`（可变）、`messageType: user\|custom`、`prompt`/`message`、`images?` | **原地修改 + 转换**：改 `systemPromptOptions`；返回 `message` 追加运行；返回 `systemPrompt` 替换整段 prompt |
| `agent_start` | 一次底层 agent 运行开始 | — | 通知 |
| `agent_end` | 一次底层运行结束（重试/恢复可能重启，**非**空闲终态） | `messages` | 通知 |
| `agent_before_settle` | 自动处理停止前、最终化前 | `entries`、`continue`、`context`、`outcome` | **行为边界**：可追加 entries 或 `continue: true` 做最后一次延续 |
| `agent_settled` | 所有自动延续结束后（无重试/压缩/排队延续） | `aborted` | 通知，仅做通知类工作 |

## D. 模型轮次与转录转换

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `turn_start` | 每个模型请求轮次开始 | `turnIndex`、`timestamp` | 通知 |
| `turn_end` | 一次模型响应及其工具调用后 | `message`、`toolResults`、`messageEntryId`、`toolResultEntryIds`、`entries`、`continue`、`context` | **行为边界**：可链式提议 `custom`/`context_edit`/`compaction` entries，返回 `continue: true` 触发下一请求 |
| `context` | 每次提供方请求前，过滤会话消息（**不含** prompt/工具系统消息） | `messages: AgentMessage[]` | **链式转换**：返回值传给下一处理器；Pi 之后恢复 prompt/工具状态 |
| `context_with_system` | `context` 全部跑完后，含系统消息的完整转录 | `messages` | **链式转换**：handler 拥有 prompt 与工具声明（需保留 index 0 系统消息） |

## E. 提供方调用

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `before_provider_request` | 请求体序列化前 | `payload` | **链式转换**：返回值作为新 payload 传给下一处理器 |
| `before_provider_headers` | 请求头发送前 | `headers` | **原地修改**：改 `headers`（返回忽略；`null` 删除该头） |
| `after_provider_response` | 响应后、流消费前 | `status`、`headers` | 通知，观察元数据 |
| `provider_stream_event` | 每个解析后的提供方流事件（Pi 规范化前） | `provider`、`api`、`model`、`data` | **通知 + 只读**：不持久化；慢处理器会阻塞流消费 |

## F. 消息生命周期

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `message_start` | 消息（user/assistant/toolResult）开始 | `message` | 通知 |
| `message_update` | assistant 流式 token 级更新 | `message`、`assistantMessageEvent` | 通知 |
| `message_end` | 消息终结 | `message` | **链式转换**：返回 `{ message }` 替换最终消息，**必须保留原角色** |

## G. 工具执行（权限与脱敏的主战场）

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `tool_execution_start` | 工具调用执行开始 | `toolCallId`、`toolName`、`args`、`parentToolCallId?` | 通知 |
| `tool_execution_update` | 执行期间部分结果 | `toolCallId`、`partialResult`、`parentToolCallId?` | 通知 |
| `tool_execution_end` | 执行结束 | `toolCallId`、`result`、`isError`、`durationMs?`、`parentToolCallId?` | 通知 |
| `tool_call` | 工具调用授权 / 改写时 | `toolCallId`、`toolName`、`input`（可变）、`parentToolCallId?` | **Gate + 原地修改**：改 `input` 修补参数（**不重新校验**）；返回 `{ block?, reason?, terminate? }` 阻止；抛错也阻断（fail-safe） |
| `tool_result` | 工具结果返回 | `toolCallId`、`input`、`content`、`structuredContent?`、`isError`、`usage?`、`parentToolCallId?` | **链式转换 + 组合**：各 handler 见先前改动；可脱敏/替换 `content`/`structuredContent`/`details`/`isError`/`usage` |

> **嵌套调用贯穿**：工具内部经 `ctx.executeTool()` 再调子工具时，子调用 id 形如 `<parent id>/<n>`，其 `tool_call`/`tool_result`/`tool_execution_*` 同样携带 `parentToolCallId`，**权限检查不漏底**；嵌套调用不进转录，只在调用方结果的 `nestedCalls` 里留有限记录（参数 >8KiB、结果 >32KiB 省略，至多 256 条）。

## H. 模型与思考级别

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `model_select` | 新模型被选中 | `model`、`previousModel`、`source: set\|cycle\|restore` | 通知 |
| `thinking_level_select` | 思考级别切换 | `level`、`previousLevel` | 通知 |

## I. 输入与 Shell

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `input` | 用户输入进入、agent 处理前 | `text`、`images?`、`source: interactive\|rpc\|extension`、`streamingBehavior?` | **链式转换 + Gate**：返回 `{ action: "continue" }` / `{ action: "transform", text, images? }` / `{ action: "handled" }` |
| `user_bash` | 用户经 `!`/`!!` 前缀执行 bash | `command`、`excludeFromContext`、`cwd` | **Gate**：返回 `undefined` 透传本地执行；返回 `{ operations }` 或 `{ result }` 接管执行；抛错阻断命令（不 fallback） |

## J. UI 提示与缓存

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `ui_prompt_start` / `ui_prompt_end` | 阻塞式扩展 UI 提示起 / 止 | `kind: select\|confirm\|input\|editor\|custom`、`title?` | 通知 |
| `cache_warming_decision` | 空闲提示缓存刷新决策 | `CacheWarmingDecisionEvent` | **最后覆盖**：最后返回 `{ action: "warm" }` 或 `{ action: "stop" }` 的处理器生效 |

## 生命周期顺序（典型一次会话）

`session_start` → `resources_discover` → （`project_trust` 视情况）→ `before_agent_start` → `agent_start` → `turn_start` → `context`/`context_with_system` → `before_provider_*` → `provider_stream_event` → `after_provider_response` → `message_*` → `tool_execution_*`/`tool_call`/`tool_result` → `turn_end`（可续跑）→ … → `agent_before_settle` → `agent_settled`；退出时 `session_shutdown`（需幂等）。

## Links

- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md) — 四层扩展与工具的 exposure 五态
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md) — `tool_call`/`tool_result` 钩子的落点
- [Architecture：架构](/docs/CS/AI/LLM/Agent/Product/Pi/Architecture.md) — 工具批次与事件持久化顺序
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md) — `session_before_compact` 等压缩事件的用户侧语义
- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)

## References

- [pi/packages/coding-agent/src/core/extensions/types.ts](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/extensions/types.ts) — `ExtensionEvent` 联合类型与 `ExtensionAPI.on()` 全部重载（权威事件清单）
- [pi/packages/coding-agent/docs/extensions.md](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) — 扩展作者文档
