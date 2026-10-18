## Introduction

Claude Code 的回复路径是「用户提问 → 模型回答」。cc-haha 多出一条**主动投递**线：assistant 模式（内部代号 Kairos）下 agent 可以在用户没提问时把消息、附件推给用户，公开版用 `Brief` 工具承载——它是官方 `SendUserMessage` 的公开版等价物。本篇串起这条线，并用一张表收口「哪些自有工具在公开版真的可用」，避免把 feature-gated 占位误当功能。

## Kairos Assistant Mode

Kairos 是一条编译期 + 运行时双重 gate 的模式开关：

- **编译期**：`feature('KAIROS') || feature('KAIROS_BRIEF')` 顶层 OR 判定——assistant 模式的 system prompt 硬依赖主动投递能力，故 `KAIROS` 单独也要 bundle Brief；而 `KAIROS_BRIEF` 让 Brief 能脱离 assistant 模式独立发布。
- **运行时**：GrowthBook `tengu_kairos_brief`（刷新周期 `KAIROS_BRIEF_REFRESH_MS = 5 分钟`）作 kill switch——中途关掉后，即使已 opt-in 的会话也会在下个刷新周期被禁用。
- **同族 gate**：计划任务侧的 `tengu_kairos_cron` / `tengu_kairos_cron_durable` 属同一家族（见 [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)）；两者都是「编译期常量折叠 + 运行时灰度」的双闸门写法。

> 一个易踩的实现细节：`isBriefEnabled()` 必须在**函数顶层**写 `feature()` 守卫。源码注释解释——若仅把 `isBriefEntitled()` 组合进来（它自己也有守卫），语义等价但 Bun 无法跨模块边界做常量折叠，外部构建里 BriefTool 对象就不会被 dead-code 掉。同理 `isBriefEntitled()` 内部用**正向三元**而非负向 early-return，避免 GB gate 字符串残留在外部构建。

## Brief Tool

**输入**：`message`（支持 markdown）、`attachments`（可选，照片/截图/diff/日志等）、`status`（`normal` / `proactive`）。`proactive` 用于「用户没问但现在必须看到」的场景——任务完成时用户不在、遇到阻塞、主动状态更新；`normal` 则是回应用户刚说的话。

**双重判定**（entitlement 与 activation 分离）：

- `isBriefEntitled()` 决定「用户**是否有资格**使用」——编译期 gate 为真时，再看 `getKairosActive()` 或环境变量 `CLAUDE_CODE_BRIEF`（开发/测试强授权，绕过灰度），或 GrowthBook `tengu_kairos_brief`。
- `isBriefEnabled()` 决定「本会话**是否实际激活****——`(getKairosActive() || getUserMsgOptIn()) && isBriefEntitled()`。源码注释点明这是修复「被灰度命中就默认开启」的写法：**没有显式 opt-in 就恒为 false**，无论灰度是否命中。

**opt-in 来源**（任一即可激活）：`--brief` 命令行参数、settings 里 `defaultView: 'chat'`、`/brief` 斜杠命令、`/config` 的 defaultView 选择器、`--tools` 或 SDK `tools` 选项里传 SendUserMessage、环境变量 `CLAUDE_CODE_BRIEF`。assistant 模式（`kairosActive`）**绕过 opt-in**——它的 system prompt 直接写死了「必须使用 SendUserMessage」。

**其它实现要点**：`isReadOnly` 为真（只是投递消息）；附件经 `resolveAttachments` 解析，与 `replBridgeEnabled` 状态相关；输出带 `sentAt`（在**发信进程侧**捕获的 ISO 时间戳）；output schema 里 `attachments` 必须保持可选，因为恢复会话会原样重放「附加附件之前」的旧输出，若设为必填会让 UI 渲染器在 resume 时崩溃。

## 自有工具可用性

cc-haha 有一批自有工具，其中相当一部分在公开版**不提供功能**。三种形态需分开看：

| 工具 | 公开版状态 | 形态 |
| :-- | :-- | :-- |
| `Brief` | 可用 | 真实实现，需 opt-in + Kairos gate |
| `ImageGen` / `ImageEdit` | 可用 | 真实实现，随 provider 启用（见 [GenerativeTools](/docs/CS/AI/LLM/Agent/Product/CcHaha/GenerativeTools.md)） |
| `StructuredOutput` | 可用 | 真实实现，仅非交互会话 |
| `tungsten` | 不可用 | **手写禁用占位**：`isEnabled()` 恒 false，文案 "Unavailable in this local recovery build." |
| `MonitorTool` | 不可用 | `@generated` stub |
| `REPLTool` | 不可用 | `@generated` stub（目录内 `constants.ts` / `primitiveTools.ts` 是真实代码，但主工具文件是占位） |
| `CtxInspectTool` | 不可用 | `@generated` stub |
| `ListPeersTool` | 不可用 | `@generated` stub（见 [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)） |
| `SnipTool` | 不可用 | `@generated` stub |

**形态差异的实操影响**：`@generated stub` 由 `scan-missing-imports` 自动生成（`export const __stubMissing = true` 的 Proxy 占位），对应 ant-internal 的 `feature()` gated 模块，公开构建 DCE 后不执行，通常**不会出现在工具列表**里；而 `tungsten` 那类手写占位是**普通对象**，`isEnabled()` 返回 false 才被排除——排查「模型为何调用不到某工具」时，这两类要分开确认。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)
- [GenerativeTools](/docs/CS/AI/LLM/Agent/Product/CcHaha/GenerativeTools.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)

## References

- [BriefTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/BriefTool/BriefTool.ts)
- [prompt.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/BriefTool/prompt.ts)
- [attachments.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/BriefTool/attachments.ts)
- [TungstenTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/TungstenTool/TungstenTool.ts)
- [REPLTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/REPLTool/REPLTool.ts)
- [MonitorTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/MonitorTool/MonitorTool.ts)