## Introduction

前两篇讲机制（[Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) 的接口面、[ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md) 的实现层）。这一篇看**官方自己怎么用这些机制**——仓库 `plugins/` 下 9 个官方插件是唯一的一手范本，其中三个值得逐行读：`code-review`（按模型档位分层派 agent）、`feature-dev`（七阶段阶段化编排）、`ralph-wiggum`（用 `Stop` hook 做自主循环）、`hookify`（用 Python 规则引擎做用户可配 hook）。

事实基线：官方仓库 [`plugins/`](https://github.com/anthropics/claude-code/tree/main/plugins)（2026-10-18 本地取全仓核对），客户端 2.1.302。

## Orchestration Pattern: Tier Agents By Model

`code-review` 的编排是整个仓库里最值得学的一段，它的核心手法是**按模型档位分层派 agent**：

| 阶段 | 模型 | 任务性质 |
| :--- | :--- | :--- |
| 第 1 步 | **haiku** ×1 | **门禁**：PR 是否已关闭 / 是 draft / 无需审查（如自动 PR、显然正确的琐碎改动）/ Claude 已评论过 |
| 第 2 步 | **haiku** ×1 | 返回**文件路径清单**（不是内容）——相关目录下的 `CLAUDE.md` |
| 第 3 步 | **sonnet** ×1 | 看 PR 并返回改动摘要 |
| 第 4 步 | **sonnet ×2 + opus ×2 并行** | 独立审查 |

这个分层的逻辑很清晰：**判定「要不要做」用最便宜的模型**（haiku 做四个布尔判断，答错的代价只是多跑一轮），**汇总与合规检查用 sonnet**，**真找 bug 用 opus**。而且第 2 步只返回路径不返回内容——**省 token 的关键动作是缩小后续 agent 的输入面**。

它还给所有 agent 挂了一条统一的「agent 假设」，值得原样学：

> **所有工具都功能正常、不会报错。不要测试工具、不要做探索性调用**——并且「要把这一点明确告诉每一个被派出的 subagent」。
> 只在完成任务确实需要时才调工具；每次工具调用都要有明确目的。

后一句是防止 agent 浪费预算的关键约束——**主agent 必须显式把它传下去**。

### 高信号判据

`code-review` 对「什么该报」的划定比「怎么报」更有价值。它**只报**这三类：编译/解析会失败的（语法错误、类型错误、缺失 import、未解析引用）、**无论输入都必定产生错误结果的**（明确的逻辑错误）、以及能**逐字引用被违反的那条规则**的 CLAUDE.md 违规。

**明确不报**：代码风格或质量顾虑、依赖特定输入或状态的可能问题、主观改进建议、无法在 diff 内验证的猜测、吹毛求疵与可能的误报。

两条配套规则同样关键：**评估 CLAUDE.md 合规时只考虑与该文件同路径或其父目录的 CLAUDE.md**（否则会拿无关规则硬套）；**bug agent 只看 diff 本身，不读额外上下文**——不报那些「不进上下文就无法验证」的问题。

## Orchestration Pattern: Phased Workflow

`feature-dev` 是阶段化编排的样本，七个阶段里嵌着三次并行派 agent：

| 阶段 | 做什么 | 派 agent |
| :--- | :--- | :--- |
| 1 Discovery | 建覆盖全部阶段的 todo list | — |
| 2 Codebase Exploration | 摸清现状 | **2–3 个 `code-explorer` 并行** |
| 3 Clarifying Questions | **澄清提问**（标注为最关键阶段，不许跳） | — |
| 4 Architecture Design | 出方案 | **2–3 个 `code-architect` 并行**，各自不同取向（最小改动 / 干净架构 / 务实平衡） |
| 5 Implementation | 实现 | — |
| 6 Quality Review | 质量复核 | **3 个 `code-reviewer` 并行**，不同焦点（简洁/DRY/优雅 · bug/功能正确 · 项目约定/抽象） |
| 7 Summary | 总结 | — |

三个要点：

- **每次派多个 agent 都给它们不同的「焦点」**，而不是让它们做同样的事——并行派 agent 只有在视角不同时才有意义，否则是重复劳动。
- **阶段 2 的核心原则写得很实在**：派 agent 时让它们**返回最重要的文件列表**，agent 回来后**主 agent 自己读那些文件**再继续。把「广度扫描」外包出去，把「深度理解」留给自己。
- **三个 agent 全是只读工具**（`Glob, Grep, LS, Read, NotebookRead, WebFetch, WebSearch` + todo/输出类，无任何写工具）——**架构师与评审者不该有能力改代码**，这是刻意的权限隔离，比在提示词里叮嘱可靠。
- 阶段 3「澄清提问」被标为 CRITICAL 且 DO NOT SKIP——**把「需求不清」这一步显式化**，而不是让 agent 猜着往下做。

`code-reviewer` 的 description 里还写明了它的判据是**基于置信度过滤、只报真正要紧的高优先级问题**——把过滤策略写进 agent 的定义而不是每次调用时重复交代。

## Pattern: Self-Referential Loop With A Stop Hook

`ralph-wiggum`（`/ralph-loop`）实现的是「把输出喂回输入、直到真正完成」的自主循环，机制只用了一个 `Stop` hook——**这是 hook 最巧妙的一种用法**。

它的完整机制：

1. `/ralph-loop` 的 frontmatter 里 `allowed-tools` 只允许跑自己的 setup 脚本，且有 `hide-from-slash-command-tool`；命令本体用 ```` ```! ```` 动态注入执行脚本。
2. setup 脚本写一个**状态文件** `.claude/ralph-loop.local.md`（Markdown + YAML frontmatter），记 `iteration` / `max_iterations` / `completion_promise` 与 prompt 正文。
3. `Stop` hook 在每次模型试图结束 turn 时跑：读状态文件→ 校验字段 → 从 **transcript（JSONL）里 grep 最后一条 assistant 消息** → 提取文本。
4. **若设置了 `completion_promise` 且模型输出了 `<promise>…</promise>` 且文本相符** → 删状态文件、`exit 0`，循环结束。
5. 否则**把同一份 prompt 原样喂回**：递增 `iteration`、原子改写状态文件（临时文件 + `mv`）、输出

```json
{"decision": "block", "reason": "<原 prompt>", "systemMessage": "🔄 第 N 轮 | 停止方式：输出 <promise>…</promise>"}
```

`Stop` hook 的 `decision: "block"` 加 `reason` 就是「不让我结束、把这段话还给我」的官方接口——**与 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md) 里 mod 的 `asyncRewake` 互补**：`asyncRewake` 是后台跑完主动唤醒（用于重活），`decision:block` 是**阻止收尾并注入新输入**（用于循环）。

### 三个防坑细节

这套脚本的健壮性写法很值得抄：

- **提取 `<promise>` 用 Perl 的 `-0777` slurp 模式**并配**非贪婪 `.*?`**——注释写明原因是多行支持与「取第一个标签」。用 grep/sed 处理多行标签是常见错法。
- **`[[ "$A" = "$B" ]]` 而不是 `==`**——注释说得很清楚：`==` 在 `[[ ]]` 里做 glob 匹配，`*`、`?`、`[` 会把它搞坏。
- **每一处失败都先删状态文件再 `exit 0`**（而不是 `exit 1`）——校验 frontmatter、转录文件存在、grep 到 assistant 消息、jq 解析、空文本，任何一步失败都**优雅停机**并给出可操作提示，而不是让会话卡在反复重试的状态里。数值字段在任何算术前先用正则 `^[0-9]+$` 校验。

### 提示词层面的护栏

命令正文里那段约束值得原样记住——**它在防模型为了逃出循环而撒谎**：

> 设了 completion promise 时，**只有当那个陈述完全且无可置疑地为真时**才可以输出它。不要为了逃出循环而输出虚假的 promise，即便你觉得卡住了或因其他原因该退出。这个循环的设计就是持续到真正完成。

`systemMessage` 里也重复了一遍「**仅在为真时——不要撒谎来退出**」。这是把「对抗性激励」的防护写进提示词，因为循环机制天然给了模型一个逃生出口。

另外注意默认行为：**未设 `completion_promise` 时循环会无限跑**——提示词里明说这一点。

## Pattern: User-Configurable Hooks In Markdown

`hookify` 是另一种范式：**用 `.local.md` 文件让用户自己写 hook 规则**，Python 侧做规则引擎。

- 规则存在 `*.local.md`（用 `.local.` 前缀天然 gitignore——仓库里就带 `.gitignore`），每条声明 matcher（工具名）、condition（条件）、action（动作）。
- 四个 hook 脚本（`pretooluse.py` / `posttooluse.py` / `stop.py` / `userpromptsubmit.py`）共用 `core/rule_engine.py`（313 行）与 `core/config_loader.py`，**每个 `timeout: 10`**。
- `RuleEngine` 的结构很清晰：`evaluate_rules` 遍历规则 → `_rule_matches` → `_matches_tool`（工具名匹配）→ `_check_condition` → `_extract_field`（从工具输入里按字段名取值）→ `_regex_match`（`compile_regex` 先编译缓存）。
- 配套有 `conversation-analyzer` agent（按对话模式推断该生成什么规则）与 `writing-rules` skill，外加 4 个示例规则（危险 `rm`、敏感文件告警、要求测试才停、console.log 告警）。

**范式价值**：规则与代码分离——用户改 `.md`，引擎不改。这与 `security-guidance` 的「26 条规则纯数据 + 一个纯函数」是同一种思路（规则数据不写死在代码里）。

## Which Pattern To Use When

| 想要 | 用什么 | 代价 |
| :--- | :--- | :--- |
| 减少重复劳动、卡点判断交给模型 | `code-review` 式：按模型档位分层派 agent | 每次审查多轮 API |
| 多视角覆盖一个复杂任务 | `feature-dev` 式：阶段化 + 每阶段不同焦点的并行 agent | 阶段多、token 消耗大 |
| 让模型反复迭代直到真正做完 | `ralph-wiggum` 式：`Stop` hook + `decision:block` + 完成承诺 | **可能无限循环**，必须设 `max_iterations` |
| 重活异步但结论必须回到对话 | mod 的 `asyncRewake` | 需要写成 mod（进程内 TS） |
| 让用户自己配 hook | `hookify` 式：`.local.md` 规则 + 规则引擎 | 需要自己实现引擎 |

## Traps

- **并行派 agent 必须给不同焦点**——相同焦点的并行是重复劳动。
- **必须显式把「不要测试工具」的约束传给每个 subagent**——主 agent 自己知道没用，得说出来。
- **`Stop` hook 失败要「删状态文件 + exit 0」优雅停机**，别让状态残留导致无限重试。
- **计数类字段在任何算术前校验**（`[[ =~ ^[0-9]+$ ]]`），否则被手改的状态文件会让 hook 崩在算术错误上。
- **`<promise>` 这类带标签的多行提取用 Perl slurp + 非贪婪**，别用 sed。
- **`[[ "$A" = "$B" ]]` 用单等号**；双等号会做 glob 匹配，`*`/`?`/`[` 会出事。
- **只读 agent 靠工具列表实现隔离**，不要靠提示词叮嘱——`feature-dev` 三个 agent 的 `tools` 里没有任何写工具。

## Links

- [PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)
- [HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)
- [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)

## References

- [`plugins/code-review/commands/code-review.md`](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/commands/code-review.md)
- [`plugins/feature-dev/commands/feature-dev.md`](https://github.com/anthropics/claude-code/blob/main/plugins/feature-dev/commands/feature-dev.md)
- [`plugins/ralph-wiggum/hooks/stop-hook.sh`](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/hooks/stop-hook.sh)
- [`plugins/hookify/core/rule_engine.py`](https://github.com/anthropics/claude-code/blob/main/plugins/hookify/core/rule_engine.py)
- [官方插件目录](https://github.com/anthropics/claude-code/tree/main/plugins)