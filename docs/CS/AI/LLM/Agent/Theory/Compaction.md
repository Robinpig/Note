## Introduction

Agent 上下文压缩（context compaction）指长会话逼近上下文窗口时，把较早的历史替换成摘要以腾出空间。它是 Harness 的**可选能力**，不是 Agent loop 主干的一部分——所以主流实现都把它做成可插拔组件，而不是写死在循环里。

> 一句话理解：**压缩 = 找到一段可安全折叠的历史区间 → 用一次（或零次）额外的 LLM 调用把它换成一条摘要节点 → 让后续请求的前缀变短。** 三步里每一步都能出事：区间选错会切开工具调用配对，摘要丢约束会让模型执行错误命令，前缀重写会让 KV 缓存失效。

本文所有行为细节均以官方文档与源码为准（核实日期 2026-10-05）。各家术语差异很大，但收敛成同一套骨架：**触发阈值 / 保留策略 / 摘要生成方式 / 可恢复性 / 失败处理 / 缓存交互**。

## 通用机制

### 触发阈值 绝对值、百分比还是双水位

**没有统一答案，实际有四种流派**，且阈值几乎都是「可配的」而非硬编码。

| 流派 | 代表 | 阈值形态 |
| :--- | :--- | :--- |
| 窗口百分比 + 余量双约束 | DSH | `floor(min(W × thresholdRatio, W − O − B))` |
| 绝对 token 值（可配scope） | Codex | `model_auto_compact_token_limit`（模型默认值，未设则用模型默认） |
| 百分比（单一数值） | Gemini CLI | `chatCompression.contextPercentageThreshold`，**默认 0.7** |
| 窗口绝对值 − 预留 | Claude Code / Pi / OpenCode | `contextWindow − reserve` 形式 |

**DSH 的公式最值得抄**，它把三个变量显式分开（`W` 上下文窗口、`O` 单次请求输出预留、`B` 额外 headroom）：

```
thresholdTokens = floor(min(W × thresholdRatio, W − O − headroomTokens))
```

默认 `thresholdRatio = 0.8`、`headroomTokens = 65536`、`retainRatio = 0.16`（逐字保留近期尾部的比例，按 `W − O` 计）。`thresholdRatio` 可调小以提早压缩；`headroomTokens` 为 0 时必须显式给 `maxTokens`。**校验极严**：`retainTokens` 必须小于解析后的阈值，`retainRatio ≥ thresholdRatio` 直接在加载期拒绝插件，`W − O − B ≤ 0` 抛目标特定配置错误。
来源：[`compaction-basic/README.zh.md`](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.zh.md)、[`config.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/config.ts)

**Codex 有一个别家都没有的「scope」概念**——同一个阈值可以按两种口径计费（[`AutoCompactTokenLimitScope`](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/AutoCompactTokenLimitScope.ts)）：

- `total`（默认）：按完整活跃上下文计
- `body_after_prefix`：只按「上一个压缩窗口前缀之后新增的量」计（`active_context_tokens − prefill_input_tokens`）

这个设计解决的是一个真实问题：一次压缩后前缀变短，若仍按总量计，会立刻再次触发压缩。源码里 `AutoCompactWindow` 专门维护 `prefill_input_tokens` 基线，并区分 `ServerObserved`（服务端报告）与 `Estimated`（估算）——**服务端观测值一旦存在就不再被估算值覆盖**，这正是「版本事实陷阱」的典型：判断当前行为要看消费方读哪个字段，不能只看配置项存在。
来源：[`context_window.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/context_window.rs)、[`auto_compact_window.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/state/auto_compact_window.rs)、[Config Reference](https://developers.openai.com/codex/config-file/config-reference)

**关于「两级水位」**：DSH 笔记把它列为「改进方向」，但源码里**已经是两个触发入口**，只是形态与笔记设想的不同——`CompactionTrigger = 'pressure' | 'context-overflow'`：

- `pressure`：常规水位检查，跑在 `agent/pre-step` waterfall 里，先于请求推导
- `context-overflow`：兜底，响应 `agent/request-error` 中提供方确认的 `CONTEXT_WINDOW_EXCEEDED`，**绕过常规阈值与保留策略**（`retainTokens` 传 `0`），尝试一次最大平衡缩减

所以「两级水位」的实质是**前瞻水位 + 事后兜底**，而非两个渐进的水位线。`maxOverflowRetries` 默认 `1`，即溢出后最多重试一次压缩。
来源：[`compaction.zh.md`](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.zh.md)、[`index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/index.ts)

### 保留策略 是 token 预算而非「最近 N 轮」

**「保留最近 N 轮」是民间简化说法。** 除 Gemini CLI 的 `maxSessionTurns`（-1 = 无限，且它触发的是**新开会话**而非压缩）外，主流实现全部按 **token 预算**而非轮数：

| 实现 | 保留判据 | 默认值 |
| :--- | :--- | :--- |
| DSH | `retainRatio × (W − O)` | 0.16 |
| Pi | `keepRecentTokens` | 20000 |
| OpenCode | `clamp(usable × 0.25, 2000, 15000)` | 动态，随窗口缩放 |
| Codex | **保留 user message，最多 20K token** | `COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000` |
| Claude Code | 重读最多 5 个文件 + 重新注入 skill 正文 | 见下文 |

三个值得记的细节：

**OpenCode 的保留预算是窗口的函数**，`preserveRecentBudget = min(15000, max(2000, floor(usable × 0.25)))`——小窗口不会被固定 20K 尾部撑爆。
来源：[`overflow.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/overflow.ts)、[`compaction.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)

**Codex 保留的是 user message 而非「最近轮次」**，从最旧往回累积到 20K token 上限，超限则退化为纯文本 fallback（`truncate_text` + `TruncationPolicy::Tokens`），并且**只重建文本、绝不克隆被丢弃的媒体**。
来源：[`compact.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs)

**切点必须避开工具调用配对。** 这是硬约束不是优化：DSH 用 `toolPairingBalancedBefore/After` 校验区间两端，`basic-region.ts:selectCompactableRange` 从后往前累积 token 时若不满足配对就继续前移；Pi 的合法切点是「user 消息 / assistant 消息 / BashExecution / 自定义消息」，**绝不切在 tool result 上**（必须与其 tool call 相伴）。DSH 额外保证位于 surface 节点 0 的 `system/message` 永不被遮蔽。

### 摘要由谁生成 几乎总是一次额外的 LLM 调用

**除 Claude Code 与 DSH 有复用缓存的优化外，摘要基本都是一次全新的、独立的 LLM 调用**——这直接意味着额外成本与延迟。

- **DSH**：`ctx.llm.stream()` 一次，`GenerateOptions.purpose = 'compaction'`，`maxTokens` 默认等于 `headroomTokens`（65536）。可配 `summarizationProvider`/`summarizationModel` 换模型（必须成对设置）。**只保留返回的文本**，图片输出以 `UNSUPPORTED_CONTENT` 失败而非静默丢弃。
- **Codex**：`SUMMARIZATION_PROMPT` 是一段 9 行英文指令，要求 handoff summary；产物以 `SUMMARY_PREFIX`（"Another language model started to solve this problem…"）包裹，使其对模型而言是**已建立的上下文**而非新任务。
- **Pi**：结构化格式（`Goal / Constraints & Preferences / Progress / Key Decisions / Next Steps / Critical Context` + `<read-files>`/`<modified-files>`），且**把上一次摘要作为迭代上下文传入**；序列化时 tool result 截断到 2000 字符并标注截断量。**摘要请求禁用 prompt cache 写入**（官方理由：一次性 prompt 不太可能被复用）。
- **OpenCode**：走隐藏 agent `compaction`（`mode: primary`, `hidden: true`），模型解析为 `agent.model ?? userMessage.model`。提示词极短（3 段），要求「不要继续对话、不要回答对话里的问题、只输出结构化摘要」。

**Pi 的 `pi-vcc` 确实做到了不调 LLM**——已核实为真实第三方扩展（`sting8k/pi-vcc`，MIT，478 star，最后推送 2026-10-05）：

> | Method | Pi default | pi-vcc |
> | Method | LLM-generated summary | Algorithmic extraction, no LLM |
> | Determinism | Non-deterministic, can hallucinate | Same input, same output |
> | Size reduction | Varies | 97.6% median, 89% at p10 |
> | Latency | Waits for an LLM call | 1 ms median, 11 ms p90 |
> | History after compaction | Gone, the agent only sees the summary | **Searchable with `vcc_recall`** |

它接管 `/compact` 与自动压缩（`overrideDefaultCompaction: false` 可退回 Pi 内核），并提供 `/pi-vcc [keep:N]`。注意这是**社区扩展而非 Pi 官方机制**，其「不调 LLM」也意味着摘要质量取决于提取规则而非语义理解。
来源：[pi-vcc README](https://github.com/sting8k/pi-vcc)、[Pi Compaction Reference](https://pi.dev/docs/latest/compaction)

DSH 官方明确提到「基于 tokenizer 或模板的后端是实现同一接口的兄弟包」，且 `summarize()` 是唯一的子类钩子——**纯算法摘要是官方预留的扩展点**，但仓库内未提供该后端。

### 可恢复性 「遮蔽而非删除」并非常态

**这是本主题最容易被写错的一条。** DSH 的 append-only 日志确实让原文永远在盘上，但**其他家不是这样**：

| 实现 | 原文是否在盘上 | 模型能否取回 |
| :--- | :--- | :--- |
| DSH | **是**（append-only，仅遮蔽 surface） | 否——`recall_history` 类工具**仍是 proposed 状态的 Agent Note**，未实现 |
| Codex | 是（thread 历史 + `compaction_checkpoint`） | 有 `CompactionCheckpoint` 结构记录 model_hash，但不暴露给模型 |
| Pi | 是（raw entries 保留，`context_edit omissions` 只是不计入投影） | 否，但「raw transcript history、exports、history-search 扩展仍可检查被省略的那次尝试」 |
| Claude Code | 是（transcript jsonl） | 否，但可用 `/rewind` 选择「Summarize from here / up to here」 |
| pi-vcc（扩展） | — | **是**，提供 `vcc_recall` 工具 |

DSH 的 Agent Note 把这一点讲得很直白：

> Compaction is irreversible from the model's current context. The summary the model sees carries no reference to what it shadows — `shadowedRange` lives only on the log-only `compaction/summary` event — and no tool lets the model read a shadowed span back.

并指出一个被忽视的代价：**反复压缩会复合恶化**——头部检查点每次都被重写，导致请求前缀每次都吃满 prompt-cache miss，且更早的摘要被一代代重新摘要。该 Note（`2026-07-06-recallable-compaction`，状态 **proposed**）提出的方案是拆分「冻结索引检查点」（约 100–200 token 的 stub，含代码拼装的指针行，模型不写指针）+「可变状态检查点」，并加一个**膨胀守卫**（压缩后尺寸必须严格小于压缩前，否则不提交）。
来源：[recallable-compaction](https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/proposed/feature/2026-07-06-recallable-compaction.md)

**结论：「遮蔽而非删除」是 DSH 一家的架构选择，不是行业通例。** 底层日志保留原文 ≠ 模型能取回。

### 失败处理 留一把锁，不要半应用状态

压缩是「读—调模型—写」的多步事务，中途崩溃最怕留下不一致状态。各家的做法收敛到同一原则：**用日志标记对做锁，锁释放放在最后**。

DSH 的三段式（笔记记录正确，此处补齐细节）：

```
compaction/start（取锁，数字标识未结束轮次，null 标识独立手动尝试）
  → compaction/summary（摘要 + shadowedRange/shadowedSeqs/shadowedTokenCount + provider/model/usage）
  → user/message（surfaceOp: replace，唯一真正的 surface 变更）
compaction/end（释放锁，error 字段记录失败）
```

**锁括住整个操作，且最后才释放**——中途崩溃表现为**可检测的遗留锁**（有 start 无 end），而非一个谎称压缩已完成的 end。恢复时：较新 `session/end-seed` 之前的未匹配 start 被视为陈旧证据忽略，活跃的未匹配 start 阻塞所有入口。

关键设计细节：**三个 compaction 事件都只写日志、绝不进 surface**，因此有意不扩展 `SurfaceEventType`；摘要本身承载在另一条带 `surfaceOp` 的 `user/message` 上。还有一个坑：`shadowedRange` 是**surface 位置跨度而非数值区间**——前一次 replace 会把新的高 seq 摘要节点放到旧区间位置上，导致 `start` 可能**大于** `end`，`shadowedSeqs` 才是权威集合。

**失败即保留旧 surface**（笔记记录正确）：「摘要失败会保留最新持久表层——任何替换前，自动路径会记录警告，并携带完整超预算历史继续。」另有**收缩校验**：若 `framedSummaryTokenCount >= shadowedRouteTokenCount`，直接抛错拒绝提交——**摘要必须真的变小**，否则宁可不压。

失败分类（`ManualCompactionErrorCode`）：`busy` / `cancelled` / `changed` / `summary` / `commit` / `persistence`。`changed` 与 `summary` 闭合失败并持久化，不写摘要替换；`commit` 可能发生在部分变更之后；`persistence` 表示内存标记对已闭合但 flush 失败。异步摘要期间若 surface 被改写（`SurfaceChangedError`），自动路径要求**整个 surface 稳定**，手动路径只要求**所选 span 稳定**。

还有一条扩展点：`compaction/summary-error` waterfall 事件——恢复监听器必须先记录持久的输入变更才能请求重试，后端随即重新派生选区并重新计价。

Claude Code 的失败语义不同且更微妙：`PreCompact` 退出码 2 可阻止压缩，但**阻止自动压缩的效果取决于它何时触发**——

> If compaction was triggered proactively before the context limit, Claude Code skips it and the conversation continues uncompacted. If compaction was triggered to recover from a context-limit error already returned by the API, the underlying error surfaces and the current request fails.

Codex 的 `PreCompactHookOutcome::Stopped` 直接 `TurnAborted`。OpenCode 与 Pi 在压缩失败时保留原始投影（Pi 明确「保留 omission edits、不追加 compaction、不调度内部重试」）。

### 与 KV cache 和前缀缓存的交互

**「压缩必然导致前缀缓存失效」——对最终状态成立，但过程中有一处关键例外，且这个例外是各家优化重点。**

DSH 官方对 KV cache 的说明精确到两种情况：

| 操作 | KV Cache 影响 |
| :--- | :--- |
| **检查点落地** | 「它是替换，而非仅追加。每个检查点都会使**从第一个已替换历史 token 起**的复用失效；该范围之前未更改的请求前缀仍可复用。」 |
| **辅助摘要器请求** | 「已回放系统提示词、工具与已遮蔽区域消息与**会话最后一个已路由请求逐字匹配**，因此提供方的热前缀 cache 可复用至尾随指令之前；只有该指令与摘要输出未缓存。」 |

实现手法很聪明：把压缩指令放在**回放前缀之后作为最后一条 user 消息**，而不是塞进一个新的 system prompt。原因是「system slot 恰是 provider 缓存的第一个 token 区间，一个不同的 summarizer system prompt 会让整个前缀失效」。源码注释写明「The summarization directive moves from the **front** of the request (a fresh `system` prompt) to the **end** of the conversation」——这是一次**有意的 bug 修复**（Agent Note `2026-07-21-compaction-summary-prefix-cache-reuse`，状态 implemented / archived）。

复用是 best-effort：把摘要器路由到不同 provider/model，或压缩非头部范围（手动 `compactRegion`），都会放弃复用。DSH 文档直接点明「**没有任何主流 coding harness 给模型 in-loop 召回，也没有任何被调研的实现让压缩感知前缀缓存**」。

Claude Code 走的是同一思路，且给出了成本量化：「为了生成摘要，Claude Code 发送一个独立请求，带与你对话相同的 system prompt、tools 和 history，外加一条作为最后 user 消息追加的摘要指令。**缓存温热时该请求从缓存读取前缀，所以会话中段的 `/compact` 花费远低于上下文体积所暗示的量**。」冷缓存（休息超过 cache lifetime）时则全量重算——这正是「从摘要恢复旧会话时 `/compact` 最贵」的原因。同时它明确：压缩**按设计使 conversation 层失效**，但复用 system prompt 层，并从磁盘重新加载 project context（仅当 CLAUDE.md 与 memory 自会话开始未变才命中缓存）。

关于笔记中「真正失效的是 surface 变化（工具集改、提示词改写、模型切换、compaction）」这句话：**方向正确但需修正两点**——① compaction 造成的是**局部**失效（从第一个被替换 token 起），不是全量；② 各家在压缩过程中本身就在**刻意保住**缓存（DSH 前缀重放、Claude Code 复用 system prompt 层、Pi 干脆禁用摘要请求的 cache 写入）。

Pi 的做法值得单独记：**「Summarization requests disable prompt-cache writes because these one-off prompts are unlikely to be reused.」**——反向利用缓存机制。

### 副作用 官方承认的能力损失

**压缩导致后续能力下降是公开承认的，不是猜测。** Codex 在每次压缩后向用户发一条警告：

> Heads up: Long threads and multiple compactions can cause the model to be less accurate. Start a new thread when possible to keep threads small and targeted.

Claude Code 的对应表述：「你的请求和关键代码片段被保留；**对话早期的详细指令可能丢失**」，并给出 thrashing 保护——若单个文件或工具输出大到每次摘要后立刻重新填满窗口，「Claude Code stops auto-compacting after a few attempts and shows an error instead of looping」（报错 `Autocompact is thrashing: the context refilled to the limit...`）。

可量化的公开数据目前只有 `pi-vcc` 自带的那套（1,884 个真实会话；尺寸缩减中位数 97.6%、p10 为 89%；延迟中位数 1ms）。其基准方法学值得注意：从完整 transcript 抽取**加权事实**作为 ground truth，再用**同一个抽取器**解析两侧 brief 做配对打分（recall / density / precision / size），避免解析器偏袒。DSH 则**诚实标注了度量不可靠**：「token meter 每 token 四字符的启发式对 CJK 文本与 JSON Schema **定价偏低**」，精确 token 化仍是开放方向。

另一个反复出现的隐性代价：**「不可分单元」无法被压缩**。DSH 明列：「部分不可分单元与仅 envelope 溢出仍不在表层压缩范围内——恢复无法缩减系统／工具／前缀、拆分不可分的非工具节点，或修复不可剪枝剩余部分仍超出窗口的工具单元。」Claude Code 的 thrashing 错误正是这个问题的产物。

## 各家实现对比

| 维度 | Claude Code | Codex | Pi | DSH | OpenCode |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **触发条件** | 达auto-compact window（1M 模型约 **967K**；200K 模型在 200K 边界）；云会话为「接近上限时」 | `model_auto_compact_token_limit`（未设用模型默认）+ `full_context_window_limit`（窗口 × `effective_context_window_percent`） | `contextTokens > contextWindow − reserveTokens` | `floor(min(W×0.8, W−O−65536))` | `count >= usable`（`limit.input − reserved` 或 `context − maxOutputTokens`） |
| **保留策略** | 重读最多 5 个最近修改文件；skill 正文重新注入（每 skill ≤5K、总 ≤25K token）；CLAUDE.md/auto memory/plan 重新注入 | user message ≤ **20K token**（从最旧累积，超限退化为纯文本） | `keepRecentTokens` = **20000**；切点避 tool result；单个 user span 超预算则切在 assistant 消息并生成两份摘要合并 | `retainRatio` × (W−O) = **0.16**；校验 tool-call/result 配对；surface 节点 0 的 system 消息永不遮蔽 | `clamp(usable×0.25, 2000, 15000)`；另有 `tail_turns` 按轮数 |
| **摘要生成** | 独立请求，**复用同 system prompt + tools + history**，指令作为最后 user 消息；v2.1.198 起继承会话 extended thinking 配置 | `SUMMARIZATION_PROMPT`（9 行 handoff 指令），结果以 `SUMMARY_PREFIX` 包裹 | LLM 结构化摘要（`Goal`/`Constraints & Preferences`/`Progress`/`Key Decisions`/`Next Steps`/`Critical Context` + 文件列表）；传入上次摘要作迭代上下文 | `ctx.llm.stream()` 一次，`purpose: 'compaction'`，`maxTokens` 默认 65536；可配独立 provider/model | 隐藏 agent `compaction`（`mode: primary`, `hidden: true`），模型 = `agent.model ?? userMessage.model` |
| **可恢复性** | 原文在 transcript；`/rewind` 可选「Summarize from here/up to here」；模型不可取回 | thread 历史 + `CompactionCheckpoint`（含 `model_hash`）；模型不可取回 | raw entries 保留，omissions 不计入投影；history-search 扩展仍可检查 | **append-only 日志，仅遮蔽 surface**；召回工具仍是 **proposed** | `revert-compact` 测试存在（可回退） |
| **手动命令** | `/compact [instructions]`、`/autocompact [auto\|<tokens>]` | `/compact` | `/compact [instructions]` | `/compact`（需挂 `dsh-command-compact`） | `/compact` |
| **Hook / 配置项** | `PreCompact`（可 `exit 2`阻止；入参 `trigger`、`custom_instructions`）、`PostCompact`（入参 `trigger`、`compact_summary`，**无决策控制**）；`CLAUDE_CODE_AUTO_COMPACT_WINDOW`、`CLAUDE_CODE_DISABLE_1M_CONTEXT`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `PreCompact`/`PostCompact` hook（`trigger` 字段）；`compact_prompt`、`experimental_compact_prompt_file` 覆盖摘要提示词；`model_post_turn_compact_threshold_percent` | `session_before_compact`（可 `cancel` 或提供自定义 summary）、`session_compact_failed`、`session_before_tree`；`compaction.{enabled,reserveTokens,keepRecentTokens}` + `modelOverrides` | `compaction/start\|summary\|end` 会话事件 + `compaction/summary-error` waterfall；`thresholdRatio`/`headroomTokens`/`retainRatio`/`retainTokens`/`compactionRetries`/`maxOverflowRetries`/`modelPolicies`/`auto` | `compaction.{auto,prune,tail_turns,preserve_recent_tokens,reserved}`；`experimental_compact_prompt_file`；plugin 钩子 `experimental.*` |

### 其他值得记的实现

- **Gemini CLI**（`google-gemini/gemini-cli`）：`chatCompression.contextPercentageThreshold` **默认 0.7**，同时管自动压缩与 `/compress`。另有独立的 `summarizeToolOutput.{tool}.tokenBudget`（**仅支持 `run_shell_command`，默认关闭**）与 `model.maxSessionTurns`（-1 无限，超限则**新开 chat**而非压缩）。来源：[PR #5721](https://github.com/google-gemini/gemini-cli/pull/5721)
- **OpenCode 的工具结果剪枝**：`PRUNE_PROTECT = 40_000`、`PRUNE_MINIMUM = 20_000`、`TOOL_OUTPUT_MAX_CHARS = 2_000`，且 **`PRUNE_PROTECTED_TOOLS = ["skill"]`**——skill 工具输出永不被剪。倒序遍历时遇`turns < 2` 跳过、遇 `msg.info.summary` 或 `time.compacted` 停止。默认 `prune: false`。
- **Codex 的 token-budget 压缩**（`compact_token_budget.rs`）：一条**完全跳过模型/服务端摘要**的路径——「Token-budget compaction skips model/server summarization and installs a fresh context window instead」，但仍建模为压缩生命周期，使 compact hooks 与 `ContextCompaction` turn item 观察到同一套生命周期。另注意 Codex 的压缩有 **local / remote 两种实现**（`compact_remote_v2.rs` 系列）。
- **Aider**：官方命令表里**没有 `/compact`，只有 `/clear`**（"Clear the chat history"）与 `/drop`（"Remove files from the chat session to free up context space"）——它用**丢弃**而非摘要来管理上下文，与主流做法相反。

## 陷阱与易踩点

### 「压缩后不可恢复」是普遍情况吗

**分层回答，否则容易写成两个极端。** 「模型看不到原文」是**普遍**的；「原文还在盘上」在 DSH / Codex / Pi / Claude Code 上也**普遍**；但「模型能主动取回」**几乎不存在**，唯一例外是社区扩展 `pi-vcc` 的 `vcc_recall`。

所以正确表述是：**压缩对模型不可逆（irreversible from the model's current context），但对持有 transcript / session log 的宿主可恢复。** 写「压缩后内容丢失」过度简化，写「压缩不丢任何东西」则是误导——两者都错。DSH 的 Agent Note 标题就是精确表述：**Recallable compaction**（*Compaction is irreversible from the model's current context*）。

### 手动 `/compact` 与自动压缩的触发时机一致吗

**不一致，且差异有实质后果。** Claude Code 官方明说「The automatic pass works the same way as the `/compact` step in the timeline」——**流程一致但触发条件不同**：自动压缩有窗口阈值，`/compact` 无视阈值立即执行。Gemini CLI 更明确：「a value between 0 and 1 that applies to both automatic compression and the manual `/compress` command」——阈值同时作用于两者。

DSH 的差异最结构化：`compactIfNeeded(agent, trigger, signal)` 用于自动（pressure / context-overflow），`compactNow(agent, signal)` 用于**即使未达压力也对空闲会话做一次有效缩减**，两者的锁归属、稳定性校验模式、错误类型**全都不同**——`compactNow` 用 `turn: null` 标记对、允许所选 span 之外追加上下文、在 `finally` 中释放接纳预留。另有一条硬约束：**`compactRegion` 要求存在未结束的轮次**，在完全关闭的会话上手动调用会抛「no open turn」。

还有一个易忽略的差异：**自动压缩可以 PreCompact 阻止，手动也可以**——但阻止后的行为不同（见上文失败处理节）。

### 压缩会丢 skill 加载状态或系统提示词吗

**这是本主题里最值得单列的一条，因为「压缩把 skill 正文压掉了」是**部分**成立的担忧——精确的失效边界很少有人写清。**

Claude Code 官方有专门章节 [What survives compaction](https://code.claude.com/docs/en/context-window#what-survives-compaction)，权威表（原文逐行）：

| 机制 | 压缩后 |
| :--- | :--- |
| System prompt and output style | **Both still apply** |
| Project-root CLAUDE.md and unscoped rules | **Re-injected from disk** |
| Auto memory | Re-injected from disk |
| Git status snapshot | 重新读取 |
| Plan mode 写的 plan | Re-injected from disk |
| Rules with `paths:` frontmatter | **随文件读取时重新加载** |
| Nested CLAUDE.md in subdirectories | 读取该目录文件时重新加载 |
| Files Claude read or edited | **重读最多 5 个**，最近修改优先 |
| **Invoked skill bodies** | **Re-injected, capped at 5,000 tokens per skill and 25,000 tokens total; oldest dropped first** |
| Background commands / background subagents | 继续运行，并提醒 Claude 哪些还在跑 |
| **Context that hooks added earlier** | **Summarized with the rest of the conversation** |
| SessionStart hooks matching `compact` source | 运行并把输出加入压缩后上下文 |

三条可直接照做的结论：

1. **系统提示词不会丢**——它在请求最前，不在可压缩范围内。DSH 从架构上保证「位于 surface 节点 0 的 `system/message` 永不被遮蔽」，并明确「**它无法缩减系统提示词、工具或会话前缀**」。
2. **skill 正文会重新注入，但有配额且会截断**——每个 skill 上限 5,000 token、总计 25,000 token，**超限时最老的 skill 先被丢弃**；「Truncation keeps the start of the file, so put the most important instructions near the top of `SKILL.md`」。**这就是行为突变的真实机制**：不是 skill 消失，而是大 skill 被截断（只留开头）或最老的 skill 被静默丢弃——后者会让模型「忘记」某项能力可用。
3. **`paths:` 作用域的规则会丢**——「Path-scoped rules and nested CLAUDE.md files load into message history when their trigger file is read, so compaction summarizes them away with everything else.」官方建议：「If a rule must persist across compaction, drop the `paths:` frontmatter or move it to the project-root CLAUDE.md.」

OpenCode 从另一侧防这个问题：`PRUNE_PROTECTED_TOOLS = ["skill"]` 把 skill 工具输出排除在剪枝之外。

**推论：Claude Code 的 skill 设计是「按需加载 + 压缩后按配额重新注入」，与本库 [Skill.md](/docs/CS/AI/LLM/Agent/Theory/Skill.md) 记录的「skill 正文一旦加载就跨轮持续占用上下文」是同一机制的两面。** 压缩不会让正文永久消失，但会让**大 skill 退化成开头几行**——这比消失更隐蔽，因为模型仍「认为」skill 可用。

### OpenCode 小模型压缩的成本与收益边界

**先纠正一个流传的说法：`small_model` 不是「压缩专用小模型」。** 源码里 `small_model` 的 schema 描述是「Small model to use for tasks **like title generation**」，`getSmallModel` 由 `Provider` 提供，优先级列表是 `gemini-flash` / `gpt-nano` / `claude-haiku`。

**压缩默认不用它**——`session/compaction.ts` 的模型解析是：

```ts
const agent = yield* agents.get("compaction")
const model = agent.model
  ? yield* provider.getModel(agent.model.providerID, agent.model.modelID)
  : yield* provider.getModel(userMessage.model.providerID, userMessage.model.modelID)
```

即：压缩 agent 显式配了 `model` 就用它；**否则回落到当前对话使用的模型**。而内置 `compaction` agent 定义是 `options: {}`——**没有指定模型**。所以「OpenCode 用小模型压缩」**默认不成立**；要让它用小模型，必须显式配置 `agent.compaction.model`。

**代价与收益边界**（基于已核实事实推导）：

- **收益**：摘要质量对格式模板的遵循度通常随模型下降，但压缩任务本身比编码任务对模型能力要求低。
- **代价 1（已核实）**：跨模型/跨 provider 路由会**放弃前缀缓存复用**（DSH 文档明确「将摘要器路由到不同提供方／模型……都会放弃该复用」）。
- **代价 2**：摘要失败率上升。而 DSH 的收缩校验会拒绝「摘要不比原文小」的结果——小模型更容易写出冗长摘要。
- **代价 3（官方警告）**：Claude Code 明确**不会**在压缩时回落到窗口更小的模型：「Claude Code won't fall back to a model with a smaller context window than the primary's, since **summarizing there would cut off part of the conversation first**」——小窗口模型的摘要请求本身就装不下输入。`model-config` 里的 fallback chain 也遵循此规则。这是压缩选模型时最容易被忽略的硬约束。
- **配置位置混淆**：`reserved` / `preserve_recent_tokens` / `tail_turns` 属于 `compaction.*`；`small_model` 是**顶层**键，不在 `compaction` 下。

### Claude Code 的压缩时机 与「超过 50 轮就 compact」这个民间经验

**这个民间经验与官方机制不符，且方向上错了一半。**

首先，**50 轮不是任何阈值**：Claude Code 的判据是 token 与窗口比例（1M 模型约 967K、200K 模型在 200K 边界），与轮数无关。Pi 有 `model.maxSessionTurns`，Gemini CLI 有 `model.maxSessionTurns`（默认 -1），但这两个都是**上限截断**（超限则新开会话），不是压缩触发器。

其次，**它低估了压缩频率**：Claude Code 官方给的成本建议是「Pick your model and effort level at the top of a session, then **save `/compact` for natural breaks between tasks**」——即**按任务边界手动压缩**，而不是按轮数。轮数完全不可靠：一轮里读 5 个大文件就能撞上 200K 边界，而 50 轮纯文本对话可能连 10K token 都不到。

官方在多个位置重复的建议是**任务边界**而非计数：

- 「Use `/clear` to start fresh when switching to unrelated work」（`/clear` 不花钱，压缩才花钱）
- 「run `/compact` with a focus ... before starting a long new task」
- 「run `/compact` at a natural break in your work, such as between tasks, **instead of waiting for auto-compaction to trigger mid-task**」——最后半句直接否定了「按计数主动压缩」：官方建议的恰恰是**别抢在自动压缩之前**，因为缓存温热时手动压缩成本极低，而自动压缩总在任务中途最不合适的位置触发。

还有一条常被忽略的省 token 手段：**`/rewind` 选择性压缩**（「Summarize from here / Summarize up to here」）与 `/autocompact 500k` 调阈值——后者说明**阈值本身是可调的产品特性**，不必接受默认。

## Links

- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) / [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode.md) / [Codex](/docs/CS/AI/LLM/Agent/Product/Codex.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi.md) / [DSH](/docs/CS/AI/LLM/Agent/Product/DSH.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode.md)

## References

1. [Claude Code — Explore the context window](https://code.claude.com/docs/en/context-window)（含 What survives compaction 权威表）
2. [Claude Code — How Claude Code uses prompt caching](https://code.claude.com/docs/en/prompt-caching)
3. [Claude Code — Model configuration](https://code.claude.com/docs/en/model-config)（Default auto-compact thresholds、Set the auto-compact window）
4. [Claude Code — Hook reference](https://code.claude.com/docs/en/hooks)（33 事件；PreCompact / PostCompact）
5. [Claude Code — How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)（When context fills up）
6. [Claude Code — Troubleshooting](https://code.claude.com/docs/en/troubleshooting)（Auto-compaction stops with a thrashing error）
7. [Claude Code — Manage costs effectively](https://code.claude.com/docs/en/costs)
8. [Claude Code — Glossary](https://code.claude.com/docs/en/glossary)（Compaction / CLAUDE.md 条目）
9. [OpenAI Codex — Config Reference](https://developers.openai.com/codex/config-file/config-reference)（`model_auto_compact_token_limit*`）
10. [OpenAI Codex — Sample Configuration](https://developers.openai.com/codex/config-file/config-sample)
11. [openai/codex — core/src/compact.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs)
12. [openai/codex — core/src/session/context_window.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/context_window.rs)
13. [openai/codex — core/src/state/auto_compact_window.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/state/auto_compact_window.rs)
14. [openai/codex — core/src/compact_token_budget.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/compact_token_budget.rs)
15. [openai/codex — prompts/templates/compact/prompt.md](https://github.com/openai/codex/blob/main/codex-rs/prompts/templates/compact/prompt.md)
16. [openai/codex — hooks/src/events/compact.rs](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/events/compact.rs)
17. [Pi — Compaction Reference](https://pi.dev/docs/latest/compaction)
18. [sting8k/pi-vcc](https://github.com/sting8k/pi-vcc)（社区扩展，非 Pi 官方）
19. [DeepSeek Harness — docs/subsystems/compaction.zh.md](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.zh.md)
20. [DeepSeek Harness — packages/compaction/compaction-basic/README.zh.md](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.zh.md)
21. [DeepSeek Harness — compaction-basic/src/config.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/config.ts)
22. [DeepSeek Harness — compaction-basic/src/summarizer.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/summarizer.ts)
23. [DeepSeek Harness — compaction-basic/src/region.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/region.ts)
24. [DeepSeek Harness — Agent Note: compaction summary prefix cache reuse](https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/archived/bug-fix/2026-07-21-compaction-summary-prefix-cache-reuse.md)
25. [DeepSeek Harness — Agent Note: recallable compaction（proposed）](https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/proposed/feature/2026-07-06-recallable-compaction.md)
26. [anomalyco/opencode — session/compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
27. [anomalyco/opencode — session/overflow.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/overflow.ts)
28. [anomalyco/opencode — Agent docs](https://opencode.ai/docs/agents)
29. [google-gemini/gemini-cli — PR #5721（chatCompression.contextPercentageThreshold）](https://github.com/google-gemini/gemini-cli/pull/5721)
30. [aider.chat — In-chat commands](https://aider.chat/docs/usage/commands.html)

## 未查到项

以下内容在本次核实中**未能从官方源确认**，正文中未据此下结论：

- **Claude Code 自动压缩的精确算法**：官方只说「当对话达到 auto-compact window 时压缩」「先清旧工具输出再摘要对话」，**未公开**折叠区间的选择算法、保留多少最近轮次、以及摘要请求的具体构造（除「同 system prompt + tools + history + 尾部指令」外）。Claude Code 为闭源产物，无源码可查。
- **Claude Code 的 `reserved` / `retainTokens` 类配置项是否存在**：官方只暴露 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`、`/autocompact`、`CLAUDE_CODE_DISABLE_1M_CONTEXT`、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`。是否存在等价的「保留 token 预算」配置项**未查到**。
- **OpenCode 的 `/compact` 是否真为 `/summarize` 别名**：源码中确认了 `compaction` / `title` / `summary` 三个隐藏 agent 与 `compaction.{auto,prune,tail_turns,preserve_recent_tokens,reserved}` 配置，但**未找到** `/summarize` 别名的定义（可能在 TUI 层，未检索到）。`opencode.ai/docs/compaction` 返回 404，站点 TLS 在本机握手失败（curl exit 60），`small_model` 是否被 compaction 实际调用**未能从运行时确认**（只确认了 `getSmallModel` 的存在与「用于 title generation 之类任务」的描述、以及压缩的模型解析不经过它）。
- **Pi 的 `headroom` 扩展**：**未查到官方来源**。`pi.dev/docs/latest/extensions` 全文**零次**出现 `headroom` 或 `vcc`；GitHub 仅有 0–1 star 的第三方仓库（`irfansofyana/pi-headroom-ext`、`alex77g/headroom-pi-learn` 等），其中 `pi-headroom-ext` **无 README**。本库记录的「`headroom`（本地代理压缩，断连自动直通）」**无法核实**，建议删除或标注待考。`pi-vcc` 则已完整核实（见正文）。
- **「两级水位」的官方定义**：DSH 官方文档与 Agent Notes 中**均未出现**该术语。源码中对应的是 `CompactionTrigger` 的两个入口（`pressure` / `context-overflow`），本库笔记的「改进方向」表述**已过时**——该改进已落地为双入口，但形态是「前瞻 + 兜底」而非双水位线。
- **Codex 各模型的 `auto_compact_token_limit` 默认具体数值**：官方配置参考只说「unset uses model defaults」，**未给出per-model 的默认数值表**。`model_auto_compact_token_limit = 64000` 出现在 Sample Configuration 的**注释示例**中，不能确认是任何模型的真实默认值。
- **各家压缩的定量能力损失评测**：除 `pi-vcc` 自带基准（1,884 会话、97.6% 中位缩减）外，**未查到**任何厂商发布的、有公开方法学的「压缩前后任务成功率」对照评测。Codex 与 Claude Code 仅有定性警告。
- **Claude Code 的 microcompact**：在 `code.claude.com/docs` 全文（含 skills、how-claude-code-works、troubleshooting、commands、context-window）**零次**出现 `microcompact`。可能已改名、移除或仅存在于实验特性，**未查到**。
- **Codex 的 `remote` 压缩细节**：`compact_remote_v2*.rs` 存在但本轮GitHub API 触发速率限制，未读取实现细节，故正文只列出「存在 local/remote 两种实现」而不描述其行为。
- **DSH `minimal` preset 不加载 compaction**：本库 DSH 笔记有此记录，我**未在本次核实中确认**该preset 定义（`agent.minimal.yml` 未读取）。