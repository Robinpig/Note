## Introduction

Pi 的会话不是一段线性聊天记录，而是一棵**树**：每次对话自动保存为 JSONL 文件，每个条目带 `id` 与 `parentId`，当前条目所在的路径即**活跃分支**——只有它进入下一次模型请求。这意味着「回到过去」不是撤销，而是换一条分支继续：被放弃的分支原样保留，随时可以走回去。

本页覆盖树的三种操作、持久化与存储位置、导出分享；压缩（context 超限时的摘要机制）在 [Context](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)，交互细节在 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)。

> 版本基线：v1.3.0（2026-10-15 发布）与 `main` 分支（2026-10-16 拉取）双核实。v1.0.0 之前社区文章里的「会话树 + `/sessions`」表述已过期——查看会话树现在是 `/tree`，挑选历史会话是 `/resume`。

## Sessions Are Trees

一个会话文件里，消息、工具调用与结果、模型切换、压缩条目都是树上的条目。模型看到的「历史」是活跃分支的投影，不是整个文件——所以在 A 分支聊过的内容不会泄漏进 B 分支的请求。

三种分支操作的分工：

| 操作 | 作用范围 | 适用场景 |
| :--- | :--- | :--- |
| `/tree` | 在**当前会话文件内**移动 | 相关备选方案想留在同一棵树里 |
| `/fork` | 从某条早期 user message **新建会话** | 备选方案应成为独立的工作 |
| `/clone` | 把活跃分支**复制**成新会话 | 想要当前状态的一份独立副本 |

在 `/tree` 里选中一条 user message，它的文本会回到编辑器，改完提交即从该点分叉；选中 assistant 回复或其他条目，则从该条目之后以空编辑器续写。**离开一个分支时，Pi 会提议给被放弃的分支生成摘要**，附到进入的新分支上——相关工作的上下文得以保留，而不必把每条消息都搬过去。

## Persistence and Storage

会话默认写在 `~/.pi/agent/sessions/`，按工作目录分组；除非用 `--no-session` 显式关掉持久化（关掉后是不可恢复的内存会话）。存储位置的三级优先级：

```text
--session-dir <dir>            # CLI 参数，最高
PI_CODING_AGENT_SESSION_DIR    # 环境变量
sessionDir 设置                # settings.json，最低
```

其他会话入口：

| 入口 | 行为 |
| :--- | :--- |
| `pi --continue`（`-c`） | 打开当前工作目录最近的会话 |
| `pi --resume`（`-r`） | 打开会话挑选器（交互内同名 `/resume`） |
| `pi --session <path\|id>` | 按路径、精确 ID 或部分 ID 打开；跨项目命中会提议 fork |
| `pi --session-id <id>` | 打开指定项目会话 ID，不存在则创建 |
| `pi --fork <path\|id>` | 把已有会话 fork 成当前项目的新会话 |
| `pi --name <name>`（`-n`） | 设置会话显示名（交互内 `/name`） |

会话挑选器支持搜索、改名、删除，也能显示路径、切换排序、过滤「仅有名字」的会话（`ctrl+p` / `ctrl+s` / `ctrl+n` / `ctrl+r` / `ctrl+d`）。`/session` 随时查看当前会话的文件、ID、消息数、token 用量与成本。

约束：`--fork` 不能与 `--session` / `--continue` / `--resume` / `--no-session` 组合；会话 ID 首尾必须是字母或数字。

## Export and Share

- `/export`：把当前会话存为 HTML 或 JSONL；CLI 侧对应 `pi --export <input> [output]`。
- `/share`：上传会话并拿一个查看链接。默认走 Radius 制品（配了 Radius 登录时）；否则经 GitHub CLI 建**私有 gist**。`sessionShareDestination` 设置可强制 `gist` 或 `radius`。

导出/分享前先过一遍内容——会话里可能有提示词、工具参数、命令输出、文件内容和对话中暴露的凭证。同理，`/bug [description]` 生成的诊断报告默认可以不带 transcript，带上之前也要 review。

## Session Format

持久化文件是 JSONL：每个条目有 `id`、`parentId`、`timestamp`，header 记录会话元信息，条目类型覆盖 user/assistant 消息、工具结果、模型切换（`ModelChangeEntry`）、思考级别切换、压缩（`CompactionEntry`）、分支摘要（`BranchSummaryEntry`）与自定义条目。格式升级由 `migrations.ts` 迁移（`CURRENT_SESSION_VERSION` 标记当前版本），所以旧版本 Pi 写的会话能被新版本读取。

条目与投影的对应关系（`sessionEntryToContextMessages` / `buildSessionProjection`）是「会话树 → 模型上下文」的转换层：压缩条目把被摘要掉的旧消息从投影里替换掉，但**原始条目始终留在树里**——这是「会话即数据」的底层保证，导出与检索看到的都是完整历史。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md) — 压缩如何改写投影而不动树
- [Interaction：终端交互](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md) — `/tree` 内的树导航快捷键
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 「状态恢复」共性在 Pi 身上的落地形态

## References

- [Pi Sessions and Context](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md)
- [Pi Session Format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md)
- [Pi Command Line](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)
