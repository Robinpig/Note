## Introduction

前两篇讲机制（[Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md) 的接口面、[ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md) 的实现层）。这一篇看**官方自己怎么用这些机制**——一手范本是官方插件，其中四个值得逐行读：`code-review`（按模型档位分层派 agent）、`feature-dev`（七阶段阶段化编排）、`ralph-loop`（用 `Stop` hook 做自主循环）、`hookify`（用 Python 规则引擎做用户可配 hook）。

事实基线：客户端 **2.1.326**（原 2.1.302，本次纠偏）；插件源码取 `anthropics/claude-plugins-official`（2.1.326 起官方插件已从本仓 `plugins/` 迁出，`plugins/` 只剩一个 README 指向该仓；`ralph-wiggum` 已更名为 `ralph-loop`），版本变更取 `CHANGELOG.md` 2.1.326→2.1.302 区间。2026-11-17 本地核对。

## Orchestration Pattern: Tier Agents By Model

`code-review` 的编排是整个仓库里最值得学的一段，它的核心手法是**按模型档位分层派 agent**。官方命令 `plugins/code-review/commands/code-review.md` 的原文（模型档位就在步骤里写死）：

```markdown
1. Launch a haiku agent to check if any of the following are true:
   - The pull request is closed
   - The pull request is a draft
   - The pull request does not need code review (e.g. automated PR, trivial change that is obviously correct)
   - Claude has already commented on this PR (check `gh pr view <PR> --comments` for comments left by claude)

   If any condition is true, stop and do not proceed.

Note: Still review Claude generated PR's.

2. Launch a haiku agent to return a list of file paths (not their contents) for all relevant CLAUDE.md files including:
   - The root CLAUDE.md file, if it exists
   - Any CLAUDE.md files in directories containing files modified by the pull request

3. Launch a sonnet agent to view the pull request and return a summary of the changes

4. Launch 4 agents in parallel to independently review the changes. Each agent should return the list of issues, where each issue includes a description and the reason it was flagged (e.g. "CLAUDE.md adherence", "bug"). The agents should do the following:

   Agents 1 + 2: CLAUDE.md compliance sonnet agents
   Audit changes for CLAUDE.md compliance in parallel. Note: When evaluating CLAUDE.md compliance for a file, you should only consider CLAUDE.md files that share a file path with the file or parents.

   Agent 3: Opus bug agent (parallel subagent with agent 4)
   Scan for obvious bugs. Focus only on the diff itself without reading extra context. Flag only significant bugs; ignore nitpicks and likely false positives. Do not flag issues that you cannot validate without looking at context outside of the git diff.

   Agent 4: Opus bug agent (parallel subagent with agent 3)
   Look for problems that exist in the introduced code. This could be security issues, incorrect logic, etc. Only look for issues that fall within the changed code.
```

值得注意的是 2.1.326 基线里这套流程已经比旧描述多了一步**验证回路**：第 4 步之后还有第 5 步——对 agents 3、4 报出的每个问题再并行派 subagent 去核实它是否真成立（bug/逻辑用 Opus、CLAUDE.md 违规用 sonnet），第 6 步再把没通过验证的过滤掉。判据原文：

```markdown
5. For each issue found in the previous step by agents 3 and 4, launch parallel subagents to validate the issue. These subagents should get the PR title and description along with a description of the issue. The agent's job is to review the issue to validate that the stated issue is truly an issue with high confidence. ... Use Opus subagents for bugs and logic issues, and sonnet agents for CLAUDE.md violations.

6. Filter out any issues that were not validated in step 5. This step will give us our list of high signal issues for our review.
```

把它整理成档位表：

| 阶段 | 模型 | 任务性质 |
| :--- | :--- | :--- |
| 第 1 步 | **haiku** ×1 | **门禁**：PR 是否已关闭 / 是 draft / 无需审查 / Claude 已评论过 |
| 第 2 步 | **haiku** ×1 | 返回**文件路径清单**（不是内容）——相关目录下的 `CLAUDE.md` |
| 第 3 步 | **sonnet** ×1 | 看 PR 并返回改动摘要 |
| 第 4 步 | **sonnet ×2 + opus ×2 并行** | 独立审查：2 个查 CLAUDE.md 合规、2 个找 bug |
| 第 5 步 | **opus**（bug/逻辑）+ **sonnet**（CLAUDE.md）并行 | 逐条验证第 4 步报出的问题是否真成立 |
| 第 6 步 | — | 滤掉未通过验证的，得到 high signal 清单 |

这个分层的逻辑很清晰：**判定「要不要做」用最便宜的模型**（haiku 做四个布尔判断，答错的代价只是多跑一轮），**汇总与合规检查用 sonnet**，**真找 bug 与验证用 opus**。而且第 2 步只返回路径不返回内容——**省 token 的关键动作是缩小后续 agent 的输入面**。第 5→6 步又加了一层：**报出问题不等于问题成立，再派一轮把它证伪/坐实**，这是「high signal」名副其实的关键。

它还给所有 agent 挂了一条统一的「agent 假设」，值得原样学：

> **所有工具都功能正常、不会报错。不要测试工具、不要做探索性调用**——并且「要把这一点明确告诉每一个被派出的 subagent」。
> 只在完成任务确实需要时才调工具；每次工具调用都要有明确目的。

后一句是防止 agent 浪费预算的关键约束——**主 agent 必须显式把它传下去**。

### High-Signal Criteria

`code-review` 对「什么该报」的划定比「怎么报」更有价值。它**只报**这三类：编译/解析会失败的（语法错误、类型错误、缺失 import、未解析引用）、**无论输入都必定产生错误结果的**（明确的逻辑错误）、以及能**逐字引用被违反的那条规则**的 CLAUDE.md 违规。

**明确不报**：代码风格或质量顾虑、依赖特定输入或状态的可能问题、主观改进建议、无法在 diff 内验证的猜测、吹毛求疵与可能的误报。命令原文把这张负面清单写得很细（"Pre-existing issues"、"Pedantic nitpicks that a senior engineer would not flag"、"Issues that a linter will catch"、"General code quality concerns ... unless explicitly required in CLAUDE.md"）——**把「误报会侵蚀信任」当成一等公民来设计**。

两条配套规则同样关键：**评估 CLAUDE.md 合规时只考虑与该文件同路径或其父目录的 CLAUDE.md**（否则会拿无关规则硬套）；**bug agent 只看 diff 本身，不读额外上下文**——不报那些「不进上下文就无法验证」的问题。

## Orchestration Pattern: Phased Workflow

`feature-dev` 是阶段化编排的样本，七个阶段里嵌着三次并行派 agent：

| 阶段 | 做什么 | 派 agent |
| :--- | :--- | :--- |
| 1 Discovery | 建覆盖全部阶段的 todo list | — |
| 2 Codebase Exploration | 摸清现状 | **2–3 个 `code-explorer` 并行** |
| 3 Clarifying Questions | **澄清提问**（标注为最关键阶段，不许跳） | — |
| 4 Architecture Design | 出方案 | **2–3 个 `code-architect` 并行**，各自不同取向（最小改动 / 干净架构 / 务实平衡） |
| 5 Implementation | 实现（**DO NOT START WITHOUT USER APPROVAL**） | — |
| 6 Quality Review | 质量复核 | **3 个 `code-reviewer` 并行**，不同焦点（简洁/DRY/优雅 · bug/功能正确 · 项目约定/抽象） |
| 7 Summary | 总结 | — |

三个要点：

- **每次派多个 agent 都给它们不同的「焦点」**，而不是让它们做同样的事——并行派 agent 只有在视角不同时才有意义，否则是重复劳动。
- **阶段 2 的核心原则写得很实在**：派 agent 时让它们**返回最重要的文件列表**（"a list of 5-10 key files to read"），agent 回来后**主 agent 自己读那些文件**再继续。把「广度扫描」外包出去，把「深度理解」留给自己。
- 三个 agent 全是只读工具（`Glob, Grep, LS, Read, NotebookRead, WebFetch, WebSearch` + todo/输出类，无任何写工具）——**架构师与评审者不该有能力改代码**，这是刻意的权限隔离，比在提示词里叮嘱可靠。
- 阶段 3「澄清提问」被标为 CRITICAL 且 DO NOT SKIP——**把「需求不清」这一步显式化**，而不是让 agent 猜着往下做。阶段 5 还要求先拿到用户明确批准才动手。

### Workflow Resume Reads The Run Journal

2.1.305 修了一个揭示内部机制的 bug：`Fixed Workflow resume re-running already-completed `pipeline()` and `parallel()` agents instead of serving them from the run's journal`。也就是说 **Workflow 有一个 run 级的 journal 持久化已完成 agent 的结果**，resume 本应从 journal 取回、而不是重跑；在 2.1.305 之前 resume 会把已完成的 `pipeline()` / `parallel()` agent 又跑一遍。2.1.326 又补了一刀：`Fixed workflow resume telling Claude every finished agent would be reused after a call failed; Claude is now told how many results were reused and where reuse stopped`——resume 现在会如实告诉 Claude 复用了多少结果、复用从哪一步停下，而不是笼统声称「全部复用」。**凡是依赖 resume 的长 workflow，都要按「journal 是真相源、重跑是 bug」来设计幂等性。**

### Agent Hand-Back And Safeguards

2.1.319 在两处收紧了 subagent 的展示与安全语义：`Fixed subagent hand-back reports showing an internal marker and provenance note when expanded outside verbose mode`——hand-back 报告在非 verbose 展开时不再漏出内部标记与 provenance note；`Changed what Claude is told after safeguards stop a subagent: retry with a narrower prompt or tell you, instead of doing the work itself`——**safeguards 拦停 subagent 后，Claude 被要求「用更窄的 prompt 重试，或告诉用户」，而不是自己把活接过去做**。2.1.323 把这条进一步扩到 forked skill / workflow agent（`after safeguards stop a forked skill or a workflow agent`）。对编排的含义是：**子代理被安全策略拦下时，主 agent 不得越俎代庖绕过护栏**，只能收窄任务重试或上报人。

## Pattern: Self-Referential Loop With A Stop Hook

`ralph-loop`（`/ralph-loop`，原 `ralph-wiggum`，2.1.326 更名）实现的是「把输出喂回输入、直到真正完成」的自主循环，机制只用了一个 `Stop` hook——**这是 hook 最巧妙的一种用法**。

它的完整机制：

1. `/ralph-loop` 的 frontmatter 里 `allowed-tools` 只允许跑自己的 setup 脚本，且有 `hide-from-slash-command-tool`；命令本体用 ```` ```! ```` 动态注入执行脚本。
2. setup 脚本写一个**状态文件** `.claude/ralph-loop.local.md`（Markdown + YAML frontmatter）：`active` / `iteration` / `max_iterations` / `completion_promise` / `session_id` / `started_at`，后接 prompt 正文。其中 `session_id` 是后来加的隔离字段——`Stop` hook 在项目里每个会话都会触发，若状态文件的 `session_id` 与当前 hook 会话不符就直接 `exit 0`，避免另一个会话误拦。
3. `Stop` hook 在每次模型试图结束 turn 时跑：读状态文件 → 校验字段 → 从 **transcript（JSONL）里取最后 100 条 assistant 行、用 jq 提取最后一个文本块**。
4. **若设置了 `completion_promise` 且模型输出了 `<promise>…</promise>` 且文本相符** → 删状态文件、`exit 0`，循环结束。
5. 否则**把同一份 prompt 原样喂回**：递增 `iteration`、原子改写状态文件（临时文件 + `mv`）、输出 `decision: "block"`。官方 `plugins/ralph-loop/hooks/stop-hook.sh` 的原文片段：

```bash
# Build system message with iteration count and completion promise info
if [[ "$COMPLETION_PROMISE" != "null" ]] && [[ -n "$COMPLETION_PROMISE" ]]; then
  SYSTEM_MSG="🔄 Ralph iteration $NEXT_ITERATION | To stop: output <promise>$COMPLETION_PROMISE</promise> (ONLY when statement is TRUE - do not lie to exit!)"
else
  SYSTEM_MSG="🔄 Ralph iteration $NEXT_ITERATION | No completion promise set - loop runs infinitely"
fi

# Output JSON to block the stop and feed prompt back
# The "reason" field contains the prompt that will be sent back to Claude
jq -n \
  --arg prompt "$PROMPT_TEXT" \
  --arg msg "$SYSTEM_MSG" \
  '{
    "decision": "block",
    "reason": $prompt,
    "systemMessage": $msg
  }'

# Exit 0 for successful hook execution
exit 0
```

`Stop` hook 的 `decision: "block"` 加 `reason` 就是「不让我结束、把这段话还给我」的官方接口——**与 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md) 里 mod 的 `asyncRewake` 互补**：`asyncRewake` 是后台跑完主动唤醒（用于重活），`decision:block` 是**阻止收尾并注入新输入**（用于循环）。

### Version Correction In 2.1.326: Wider `block` Scope

**这是本次升级最可能推翻旧结论的一条。** 2.1.326 change log 原文：`Changed a hook's "decision": "block" to hold in more cases, so a hook that always prints one may start blocking calls`。

旧笔记把 `decision:block` 当作一个稳定的「回灌 prompt」接口；**2.1.326 起它的生效情形变多**——官方明确警告：**总是输出 `block` 的 hook 可能开始真正拦截调用**。对 ralph-loop 的含义：

- ralph 的 `Stop` hook 只在「状态文件存在 + 会话匹配 + 未到上限 + promise 未达成」时才输出 `decision:block`，其余所有失败路径都是**删状态文件 + `exit 0`（放行）**，不是无条件 block——所以这个插件本身仍是「条件 block」，不会被新语义直接放大成卡死。
- 但**任何借鉴这套写法、把 `decision:block` 当成常规「注入输入」手段的 hook，都必须按 2.1.326 重新验证**：过去能放行的调用现在可能真的被拦。判据从「输出 block 就会被回灌」改为「只有确实要拦时才输出 block」。

### Three Anti-Pitfall Details

这套脚本的健壮性写法很值得抄（前三条在 2.1.326 源码里依旧原样存在）：

- **提取 `<promise>` 用 Perl 的 `-0777` slurp 模式**并配 `s` 标志让 `.` 匹配换行、非贪婪 `.*?` 取第一个标签，随后 `s/^\s+|\s+$//g; s/\s+/ /g` 归一化空白：

  ```bash
  PROMISE_TEXT=$(echo "$LAST_OUTPUT" | perl -0777 -pe 's/.*?<promise>(.*?)<\/promise>.*/$1/s; s/^\s+|\s+$//g; s/\s+/ /g' 2>/dev/null || echo "")
  ```

  用 grep/sed 处理多行标签是常见错法。

- **`[[ "$A" = "$B" ]]` 而不是 `==`**——源码注释写得很清楚：`==` 在 `[[ ]]` 里做 glob 匹配，`*`、`?`、`[` 会把它搞坏；

  ```bash
  # Use = for literal string comparison (not pattern matching)
  # == in [[ ]] does glob pattern matching which breaks with *, ?, [ characters
  if [[ -n "$PROMISE_TEXT" ]] && [[ "$PROMISE_TEXT" = "$COMPLETION_PROMISE" ]]; then
  ```

- **每一处失败都先删状态文件再 `exit 0`**（而不是 `exit 1`）——校验 frontmatter、转录文件存在、grep 到 assistant 消息、jq 解析、空文本、prompt 非空，任何一步失败都**优雅停机**并给出可操作提示，而不是让会话卡在反复重试的状态里。数值字段在任何算术前先用正则 `^[0-9]+$` 校验。
- **提取最后一个 assistant 文本块比旧描述更细致**：每个 content block（text/tool_use/thinking）各占一行 JSONL，所以取最后 100 条 assistant 行、`map(.message.content[]? | select(.type == "text") | .text) | last // ""`——全是工具调用的 turn 得到空文本，继续循环而不是误判完成，jQ 失败也被 `$?` 捕获后优雅停机。

### Prompt-Level Guardrails

命令正文里那段约束值得原样记住——**它在防模型为了逃出循环而撒谎**：

> 设了 completion promise 时，**只有当那个陈述完全且无可置疑地为真时**才可以输出它。不要为了逃出循环而输出虚假的 promise，即便你觉得卡住了或因其他原因该退出。这个循环的设计就是持续到真正完成。

`systemMessage` 里也重复了一遍「**ONLY when statement is TRUE - do not lie to exit!**」。这是把「对抗性激励」的防护写进提示词，因为循环机制天然给了模型一个逃生出口。

另外注意默认行为：**未设 `completion_promise` 时循环会无限跑**——`--help`、setup 输出与 `systemMessage` 三处都明说这一点，所以 `--max-iterations` 被官方当作首要安全网（`The --completion-promise uses exact string matching ... Always rely on --max-iterations as your primary safety mechanism`）。

## Pattern: Code Mode Orchestration

这是 2.1.323 引入、**2.1.326 才补齐关键编排组合**的一种新范式，值得单列。2.1.323 change log：`Added Code Mode, an experimental opt-in in which Claude writes JavaScript to call its tools`。2.1.326 紧接着：`Added support for turning on Code Mode while agent teams are enabled; if you already turned it on, sessions with teams on now start in Code Mode`。

证据只取 change log 与类型契约（`mods/types/claude-code.d.ts`），**不臆测内部实现**：Code Mode 是**实验性 opt-in**，开启后由 **Claude 写 JavaScript 来调用它自己的工具**；这套 JS 通过 `$.tool.call` / `$.tool.check` 等入口落到工具层，类型契约里 `$.tool` 的形状是：

```ts
          /**
           * @example
           * const { text } = await $.tool.call({ tool: "Read", file_path: "a.md" })
           */
          call: EventCalls['tool']['call'];
          /**
           * Asks the engine's permission decision for a tool call now: the event
           * `tool.check`, resolved to its verdict (`{ decision, reason?, ... }`).
           *
           * The hooks run (the calling hook's own frame skipped, `next.origin` this
           * plugin, no `tool_use_id`); nothing runs, no dialog opens, no PreToolUse
           * hook or classifier is asked.
           *
           * @example
           * const { decision } = await $.tool.check({ tool: "Read", input })
           */
          check: EventCalls['tool']['check'];
```

同一契约里还有 `$.model.complete` / `$.model.classify`（把子模型调用当函数用）、`$.session.usage()`、`$.tool.register`（注册新工具）、`$.agent.spawn`——所以「Claude 写 JS 调工具」本质上是**把编排从「一条条工具调用」上移到「一段可含循环、分支、并行的脚本」**。2.1.326 允许它与 agent teams 同时开启，等于脚本编排 + 多 agent 协作两条轴可以叠加；同版本还修了 `mods` 在 Code Mode 下无法用 `$.tool.call`/`$.tool.check` 调 Bash/Read 的问题。

**编排含义**：前几种 pattern 是「提示词/命令里写好派 agent 的步骤」，Code Mode 是「让模型自己写一段程序来编排工具与 teammate」——表达力更强，但类型契约也明确 `$.tool.call` 对部分工具（如 `Workflow`）是 `refused` 的，能力边界由契约而非提示词划定。

## Pattern: User-Configurable Hooks In Markdown

`hookify` 是另一种范式：**用 `.local.md` 文件让用户自己写 hook 规则**，Python 侧做规则引擎。

- 规则存在 `*.local.md`（用 `.local.` 前缀天然 gitignore——仓库里就带 `.gitignore`），每条声明 matcher（工具名）、condition（条件）、action（动作）。
- 四个 hook 脚本（PreToolUse / PostToolUse / Stop / UserPromptSubmit）在 `hooks/hooks.json` 里注册，**每个 `timeout: 10`**，共用 `core/rule_engine.py` 与 `core/config_loader.py`。
- `RuleEngine` 的结构很清晰：`evaluate_rules` 遍历规则，分出 blocking / warning 两组 → `_rule_matches` → `_matches_tool`（工具名匹配）→ `_check_condition`（6 种 operator）→ `_extract_field`（从工具输入里按字段名取值）→ `_regex_match`（`compile_regex` 用 `lru_cache` 先编译缓存）。2.1.326 源码里 `evaluate_rules` 的**按事件选拦截格式**值得原样看：

  ```python
          if hook_event == 'Stop':
              return {
                  "decision": "block",
                  "reason": combined_message,
                  "systemMessage": combined_message
              }
          elif hook_event in ['PreToolUse', 'PostToolUse']:
              return {
                  "hookSpecificOutput": {
                      "hookEventName": hook_event,
                      "permissionDecision": "deny"
                  },
                  "systemMessage": combined_message
              }
  ```

  **同一个「block」动作在不同 hook 事件上落成不同的 JSON 字段**（Stop 用 `decision:block`、Pre/PostToolUse 用 `permissionDecision: deny`）——写通用规则引擎时必须按事件分发，不能一套 payload 走天下。注意这里 Stop 分支也输出 `decision:block`，**正好落在 2.1.326 的生效范围变更之内**，需要按上一节的纠偏重新验证。
- 配套有 conversation-analyzer agent（按对话模式推断该生成什么规则）与 `writing-rules` skill，外加若干示例规则（危险 `rm`、敏感文件告警、debug 代码告警）。
- 2.1.325 起对本范式有一处运行时约束：`Changed scheduled tasks and /loop to ask before running a skill that declares allowed-tools or hooks; add Skill(name) to permissions.allow to run it unattended`——**定时任务与 `/loop` 在跑「声明了 `allowed-tools` 或 hooks 的 skill」之前会先问人**；要无人值守，必须把 `Skill(name)` 加进 `permissions.allow`。hookify 的 `writing-rules` skill 一旦被 loop/定时任务驱动，就受这条限制。

**范式价值**：规则与代码分离——用户改 `.md`，引擎不改。这与 `security-guidance` 的「规则纯数据 + 一个纯函数」是同一种思路（规则数据不写死在代码里）。

## Which Pattern To Use When

| 想要 | 用什么 | 代价 |
| :--- | :--- | :--- |
| 减少重复劳动、卡点判断交给模型 | `code-review` 式：按模型档位分层派 agent + 验证回路 | 每次审查多轮 API |
| 多视角覆盖一个复杂任务 | `feature-dev` 式：阶段化 + 每阶段不同焦点的并行 agent | 阶段多、token 消耗大 |
| 让模型反复迭代直到真正做完 | `ralph-loop` 式：`Stop` hook + `decision:block` + 完成承诺 | **可能无限循环**，必须设 `max_iterations`；且 2.1.326 起 block 生效范围变大 |
| 重活异步但结论必须回到对话 | mod 的 `asyncRewake` | 需要写成 mod（进程内 TS） |
| 让编排变成可含循环/分支的程序、并与多 agent 叠加 | Code Mode（2.1.323 opt-in，2.1.326 可与 agent teams 同开） | 实验性；能力边界由类型契约划定 |
| 让用户自己配 hook | `hookify` 式：`.local.md` 规则 + 规则引擎 | 需要自己实现引擎；skill 被定时任务驱动时要加 `Skill(name)` 权限 |

## Traps

- **并行派 agent 必须给不同焦点**——相同焦点的并行是重复劳动。
- **必须显式把「不要测试工具」的约束传给每个 subagent**——主 agent 自己知道没用，得说出来。
- **`Stop` hook 失败要「删状态文件 + exit 0」优雅停机**，别让状态残留导致无限重试。
- **计数类字段在任何算术前校验**（`[[ =~ ^[0-9]+$ ]]`），否则被手改的状态文件会让 hook 崩在算术错误上。
- **`<promise>` 这类带标签的多行提取用 Perl `-0777` slurp + 非贪婪 + `s` 标志**，别用 sed。
- **`[[ "$A" = "$B" ]]` 用单等号**；双等号会做 glob 匹配，`*`/`?`/`[` 会出事。
- **只读 agent 靠工具列表实现隔离**，不要靠提示词叮嘱——`feature-dev` 三个 agent 的 `tools` 里没有任何写工具。
- **2.1.326 起别写「总是输出 `decision:block`」的 hook**——block 生效情形变多，可能开始真正拦截调用；只在确实要拦时输出。
- **通用 hook 引擎按事件分发 payload**：Stop 用 `decision:block`、Pre/PostToolUse 用 `permissionDecision: deny`，一套 payload 走天下会失效。
- **hook 里取会话隔离字段**（如 ralph 的 `session_id`）——`Stop` hook 在项目内每个会话都触发，不校验会话就会误拦别的会话。
- **依赖 workflow resume 的编排按 journal 是真相源设计**（2.1.305），别假设 resume 会自动跳过已完成 agent 而不重跑。
- **safeguards 拦停 forked skill / workflow agent 后不要自己接手**（2.1.319/2.1.323）——收窄 prompt 重试或告知用户。
- **定时任务 / `/loop` 跑带 `allowed-tools` 或 hooks 的 skill 前会被问人**（2.1.325）——要无人值守就把 `Skill(name)` 加进 `permissions.allow`。

## Links

- [PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)
- [HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)
- [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)

## References

- [`plugins/code-review/commands/code-review.md`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-review/commands/code-review.md)
- [`plugins/feature-dev/commands/feature-dev.md`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/feature-dev/commands/feature-dev.md)
- [`plugins/ralph-loop/hooks/stop-hook.sh`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/ralph-loop/hooks/stop-hook.sh)
- [`plugins/ralph-loop/scripts/setup-ralph-loop.sh`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/ralph-loop/scripts/setup-ralph-loop.sh)
- [`plugins/hookify/core/rule_engine.py`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/hookify/core/rule_engine.py)
- [`mods/types/claude-code.d.ts`](https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts)
- [Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)
- [Code Mode 官方文档](https://code.claude.com/docs/en/code-mode)
- [官方插件仓库 claude-plugins-official](https://github.com/anthropics/claude-plugins-official)
