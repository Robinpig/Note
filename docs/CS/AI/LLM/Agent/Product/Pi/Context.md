## Introduction

一次模型请求的上下文由四块拼成：**系统提示**（基础指令 + 发现的上下文文件）、**活跃分支**的会话历史、**工具定义**、**技能描述**。本页覆盖前两块与第三块的加载机制（上下文文件、系统提示定制），以及 context 逼近窗口上限时的**压缩**机制。

交互侧细节在 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)；会话树与分支摘要在 [Session](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)。

## Context Files

上下文文件是 Pi 的「项目记忆」：从 agent 目录（`~/.pi/agent`）、工作目录及其父目录递归发现，在对应目录或其任何子目录下运行 Pi 时生效。

| 文件 | 作用 |
| :--- | :--- |
| `~/.pi/agent/AGENTS.md` | 全局指令，所有项目生效 |
| 项目/各级目录的 `AGENTS.md` 或 `CLAUDE.md` | 项目级指令，逐级向上查找 |
| `AGENTS.override.md` | **只替代同目录**的那份 AGENTS.md/CLAUDE.md |
| `SYSTEM.md` / `APPEND_SYSTEM.md` | 替换 / 追加系统提示（agent 目录与 `.pi` 两级） |

两个容易踩的点：

- `AGENTS.override.md` 的作用域仅限**同一目录**，它不屏蔽 agent 目录或其他目录的上下文文件。
- 上下文文件的发现**不需要 project trust**——拒绝信任一个项目也不会让它的 `AGENTS.md` 失效，文件夹里的指令一律按不可信输入对待（详见 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)）。想彻底关闭用 `--no-context-files`。

受信任项目的 `SYSTEM.md` / `APPEND_SYSTEM.md` 优先于 agent 目录里的同名文件（同级不合并，各取一份）。改完任何上下文文件，`/reload` 立即生效，不用重启。

## Compaction

压缩解决的是「活跃分支越来越长，装不进模型窗口」的问题。Pi 有两套摘要机制，格式同源：

| 机制 | 触发 | 目的 |
| :--- | :--- | :--- |
| Compaction | context 超阈值或 `/compact` | 摘要旧消息，腾出上下文 |
| Branch summarization | `/tree` 切换分支 | 把被放弃分支的工作带进新分支 |

### When It Triggers

自动压缩的判据是一条不等式：

```text
contextTokens > contextWindow - reserveTokens
```

`reserveTokens` 默认 **16384**（给响应留的空间），`keepRecentTokens` 默认 **20k**（保留多新的消息不摘要），两者都在 `settings.json` 可配。检查点有三处：一轮工具批次结束、下一轮 assistant 响应发起前（`prepareNextTurn` 内；批次终止 run 且无排队消息则跳过）；新 user prompt 之前；以及低级 run 结束后的**最后一次溢出恢复**。provider 报 context-overflow 或提前出现 `stopReason: "length"` 时，会选中一次「压缩 + 重试」恢复。

### How It Works

1. **找切割点**：从投影尾部向前累计 token 估算，够到 `keepRecentTokens` 为止；
2. **抽取消息**：从上一个保留边界（或会话开始）取到切割点；
3. **生成摘要**：调 LLM 按结构化格式总结，有上一次摘要时作为迭代上下文传入；
4. **落条目**：追加 `CompactionEntry`（`summary` + `firstKeptEntryId` + `tokensBefore` + 生成摘要的 `usage`）；
5. **重建上下文**：后续请求 = 摘要 + `firstKeptEntryId` 之后的消息。

切割点只能落在 user 消息、assistant 消息、BashExecution 与 custom 消息上——**绝不切在 tool result 上**（它必须跟着自己的 tool call）。当一个 user-message span 自己就超过 `keepRecentTokens` 时，切割点落进该 span 内部的 assistant 消息处（split user-message span），此时生成「历史摘要 + span 前缀摘要」两份再合并。重复压缩时，被摘要的区间从**上一次压缩的保留边界**起算，让早前幸存的消息进入本轮再摘要；`tokensBefore` 按重建后的投影重算，保证计数对应真实被替换的上下文。

压缩**不删原始条目**——只是往投影里插一条摘要，之后的消息改从 `firstKeptEntryId` 开始走。所以会话文件始终完整，导出、检索、计费看到的都是全量历史。

### Summary Format

默认摘要是结构化 Markdown：Goal → Constraints & Preferences → Progress（Done / In Progress / Blocked）→ Key Decisions → Next Steps → Critical Context，并累积跟踪读/改过的文件（`readFiles` / `modifiedFiles` 进 `details`）。摘要请求会**禁用 prompt-cache 写**——这种一次性 prompt 不会被复用，写了反而污染缓存。

### Extension Hooks

压缩对扩展开放三个钩子：`session_before_compact`（可提供自定义摘要，或改写序列化文本）、`session_compact_failed`（失败通知）、`session_before_tree`（分支切换前）。恢复顺序有严格契约：先持久化最终响应 → `turn_end` / `agent_end` → 追记 `context_edit` 省略 → 溢出/长度场景跑压缩 → 以全新 run 重试；恢复压缩失败时保留省略编辑、不追加重试，排队工作回到普通 steering/follow-up 规则。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Session：会话树](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md) — 分支摘要与 `/compact` 的用户侧工作流
- [Compaction 理论](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 各家 harness 压缩机制横向对比
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md) — 压缩钩子只是扩展事件的一角

## References

- [Pi Compaction Reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md)
- [Pi Configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md)
- [Pi How Pi Works](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/how-pi-works.md)
