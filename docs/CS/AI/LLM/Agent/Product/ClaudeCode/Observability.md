## Introduction

Claude Code 支持把自身运行数据导出为 **OpenTelemetry**（OTel）信号——日志、指标、trace span。官方文档只给了一页概述，但 CHANGELOG 里积累了大量字段级事实（哪些事件、各带什么属性、哪些开关控制内容捕获），本文据 CHANGELOG 与随二进制发布的 mod 类型契约反推完整事件模型，是少见的可以从变更记录复原遥测设计的案例。

事实基线：`@anthropic-ai/claude-code` **2.1.326**，覆盖 2.1.302→2.1.326 的全部相关变更；2026-11-17 据官方仓库 CHANGELOG 与 `mods/types/claude-code.d.ts` 全量核对。旧版 2.1.302 基线里的若干结论已被推翻，逐节标注。

## Security Posture First

这是使用本文所有内容前必须知道的一条（2.1.282）：

> 项目级与本地级 settings **会忽略**所有用于开启导出、设置端点或捕获内容的 OpenTelemetry 变量，包括 `CLAUDE_CODE_ENABLE_TELEMETRY` 与全部 `OTEL_LOG_*`。

即：开启遥测与捕获内容只能在**用户级或 managed settings** 里做，项目仓库无法自行打开它。这是刻意的设计——否则一个 clone 下来的仓库就能把对话内容与工具输出送到攻击者的 collector。2.1.304 又补了一个漏洞：首次启动登录流程中、或 `/logout` 后首次启动时，经 server-managed settings 下发的 OTel 设置曾被整段忽略，现已生效。

另一个反直觉点是**安全事件本身也受版本摆布**：`claude_code.safety_event` 在 2.1.307 加入，本意是每次工具调用被权限规则、auto mode、安全检查、hook 或沙箱拦下、询问或打回时都发一条；但 2.1.312 已**停止发送**。任何把它当作长期信号的看板都是错的，改用 `tool_decision` 与 `permission_denials`。

## Core Events

| 事件 | 载荷要点 |
| :--- | :--- |
| `api_request` | 每次 API 请求；`cache_creation_5m_tokens` / `cache_creation_1h_tokens` 按缓存生存期拆分写入量（2.1.300+）；`request_id` 与 Claude apps gateway 的审计日志对齐（gateway 侧有 `request-id` 响应头，2.1.295+） |
| `user_prompt` | 用户提交的 prompt；**`prompt_text` 是 `prompt` 的副本**，给那些会把带点号的键嵌套处理的后端用——在丢弃或脱敏 `prompt` 的地方也要丢弃或脱敏 `prompt_text`（2.1.287，`anthropics/claude-code#70763`）。2.1.325 修复了工具调用运行中发送的消息此前**缺 user_prompt 事件**的问题：此类事件带 `delivery.mode: "mid_turn"` 以及正在运行的 turn 的 `prompt.id`；同版还修复了 VS Code 把排队消息合并成一个 turn、或消息带图片时，早前消息文本被漏写的问题 |
| `tool_decision` | 工具调用的审批裁决。`classifier_verdict` 与 `permission_mode` 让 auto mode 的 classifier 裁决能与权限规则区分开（2.1.301+）；`classifier_category` 在 `OTEL_LOG_TOOL_DETAILS=1` 时点名命中的内置规则（2.1.301 加入），但多数 auto 分类器阻断曾缺该字段，直到 2.1.302 才补全；同一修复还处理了新增属性在低 `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT` 下挤掉 `tool_use_id`/`tool_source`/`tool_parameters` 的问题。2.1.326 又修复了 managed settings 中的 PreToolUse hooks 拒绝直接工具调用时不留 `tool_decision` 事件与 `permission_denials` 条目的问题 |
| `tool_result` | 工具执行结果；含 `git_commit_id`，reftable 引用存储下 `git commit -q` 也已能记录（2.1.296/2.1.300 修复） |
| `hook_execution_complete` | 附 hook 输出大小与被存到文件的超大输出数量（2.1.280+）；2.1.321 起非交互会话在 Bash / PowerShell 调用后把两个内置 hook 排除在 `num_hooks` / `num_success` 之外 |
| `claude_code.auth` | 登录事件。Claude apps gateway 登录曾不发此事件，2.1.295 修复；条件是本机已配置 OTel 或会话已登录该 gateway |
| `claude_code.at_mention` | 每次读取 prompt 时的 @ 提及：agent 与 MCP resource 各至多 100 个事件（2.1.293+） |
| `claude_code.tool.blocked_on_user` | span。`-p` / SDK 会话与 PreToolUse hook 审批曾报 `unknown` source/decision，2.1.288 修复 |
| `claude_code.safety_event` | **已移除**：2.1.307 加入，2.1.312 停止发送，不再产出数据 |
| `claude_code.session.count` | 指标。Cowork 云会话曾把组织的 OTel 导出延后到第一条 turn，而没有消息的会话什么都不发，因此该计数可能下降（2.1.326） |

**内容捕获是严格门控的**：`OTEL_LOG_TOOL_CONTENT=1` 才把 MCP 工具、WebFetch、WebSearch 的输出放进 `tool.output` span 事件（2.1.283+）。不开这个开关，工具输出不会进遥测。同理，`OTEL_LOG_ASSISTANT_RESPONSES=0` 时后台 agent 的回复本不该出现，但 2.1.323 之前 `user_prompt` 事件与交互 span 仍会把它记进去——这是门控语义的修复，不是新增开关。

## Spans And Semantics

- v2.1.300 起 trace span 附带 **GenAI 语义约定**属性：`gen_ai.provider.name`、`gen_ai.conversation.id`、`gen_ai.tool.name`、`error.type` 等——即可以直接接入沿用 OTel GenAI 约定的后端，而不必写私有映射。
- 2.1.317 又给 OTel 的 metrics、events 与 spans 一并加上 `anthropic.plan`、`anthropic.seat_type`、`anthropic.provider`、`anthropic.custom_base_url` 四个属性：前者是通用约定，这一组是 Anthropic 特有的维度，两者可以叠加，不要把 `anthropic.provider` 与 `gen_ai.provider.name` 当成同一字段。
- 一个易错点：`prompt.submit` 这类 mod hook **改写或丢弃**后的 prompt 不得再被记成「用户原始输入」。2.1.295/2.1.300 修的正是这个——改写后的文本不再写进 prompt 历史与 transcript 的入队记录，`user_prompt` 事件与会话标题请求也不该用原样。这是「遥测要反映实际发生的事」的典型修正。2.1.312 同类修正针对 `effort`：任务中途选定新档位、模型尚未应用时，OTel `effort` 值与 transcript 曾提前报新档位，现只报实际生效的档位。

## Export Pipeline

导出路径本身的坑集中在 2.1.317 与 2.1.323，按「协议 → 代理 → 属性 → 超时」四段看：

- **协议**：`otlp` exporter 填了 endpoint 但没设 `OTEL_EXPORTER_OTLP_PROTOCOL` 时曾静默失败，2.1.323 起默认 `http/protobuf`；同版修复了导出到默认 `localhost:4318` 时误走已配置代理的问题。
- **代理**：2.1.317 修复了经代理导出到 `https://` 端点时、若上一次导出尚未结束就永远发不出去，以及对拦截 OTel 导出的代理（HTTP 403）疯狂重试连接的问题。
- **属性**：一条畸形 `OTEL_RESOURCE_ATTRIBUTES` 条目曾让该变量**全部**属性都被丢弃，2.1.323 起保留其余条目，并由 `/status` 点名被略去的那条。2.1.326 新增 `OTEL_RESOURCE_INCLUDE_HOST`，把 `host.name` / `host.id` 加入 resource attributes，**默认关**。
- **超时**：2.1.317 之前代理永不响应会让导出无限挂起；该版改为 10 秒超时，且 `OTEL_EXPORTER_OTLP_TIMEOUT` 上限 30 秒。2.1.323 起针对慢代理放宽到 25 秒，并且这个 25 秒同时成为 `OTEL_EXPORTER_OTLP_TIMEOUT` 的新上限（原为 30 秒）——所以「上限 30 秒」是旧结论，不再是当前事实。

## Type Contract

SDK 侧的遥测只暴露在 mod 层。读取 `mods/types/claude-code.d.ts` 的连续片段可见目标地址是一个**闭合联合**，且 hook 只能改内容、不能改去向：

```ts
  /**
   * Where a telemetry record goes: `anthropic`, Anthropic's first-party
   * analytics, or `collector`, the one the session's operator configured.
   *
   * A closed union and the record's identity: `e.to` reads the same at every
   * hook as it was raised, so a hook may rewrite what a record carries, never
   * redirect or copy it. A hook picks its stream with the matcher.
   *
   * @example
   * on("telemetry.log", { to: "collector" }, ($, e, next) => next(e))
   */
  export type TelemetryDestination = 'anthropic' | 'collector';
```

字符串属性必须是「取值 + 候选集」的成对结构，自由文本进不了 first-party 行：

```ts
  /**
   * A string property of a first-party row: the value and the list it is
   * chosen from, so no free text reaches a row.
   *
   * Every member of `of` is a lowercase token of letters, digits, `_` and `-`,
   * at most 32 of them; `value` is one of them.
   *
   * @example
   * const page = { value: "ready", of: ["ready", "later"] }
   */
  export type TelemetryChoice = {
      /**
       * What the row carries, one member of `of`.
       */
      value: string;
      /**
       * Every value the property may take.
       */
      of: readonly string[];
  };
```

类型上，`TelemetryProp` 只接受 `number | boolean | TelemetryChoice`，所以 first-party 行与 feature mark 的 `props` 里没有任意字符串的位置；但** collector 记录不同**——它的 `attributes` 类型是 `TelemetryAttribute`（`string | number | boolean | readonly string[]`），自由文本在这里是合法的。把「遥测值只接受有限数字/布尔/Choice」无限推广到 collector 记录是错的，这条约束只针对 first-party 行。

这与官方 mod `telemetry` 的实现正好呼应：`$.telemetry.log` / `$.telemetry.mark` 分别落到 `telemetry.log` / `telemetry.mark` 事件；first-party 行由内置插件入队、只服务内置与引擎，collector 记录只在引擎亲自发起时才真正到达 collector；任何插件都可以 hook。实现机制的展开见同目录的 mod 内部机制分册。

## Enterprise Gateway Forwarding

组织自建 Claude apps gateway 可以集中转发遥测：

- `telemetry.forward_to` 目的地（2.1.281+），`telemetry.resource_attributes` 给桌面与 `/login` 会话的遥测打固定标签（2.1.281+）。
- `auth: { google: {} }` 支持直接导到 Google Cloud 的 OTLP 端点，复用 gateway 的 Google Cloud 凭据（2.1.284+）。
- gateway 侧的 `inference` 审计事件带 `upstream_request_id`（来自 Bedrock / Anthropic API / 其他上游的请求 ID），用于对账支持工单（2.1.295+）。

Gateway hint header 里还有 `x-claude-code-prompt-id`，让 LLM gateway 能把服务同一个用户 prompt 的多次请求归组（`CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` 开启，2.1.283+）。

## Why It Matters

这套东西的实际用途有几类：把 auto mode 的 classifier 拦截与权限规则拦截在遥测里分开统计（`classifier_verdict` 就是为此加的，`classifier_category` 点名命中规则，但要注意 2.1.302 前多数阻断其实缺这个字段）；用 `git_commit_id` 把工具动作对上真实提交；在接入 OTel GenAI 约定后，用现成后端而非自建管道看 agent 行为。

排障顺序也随版本改写了：`tool_decision` 在低 `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT` 下挤掉 `tool_use_id`/`tool_source`/`tool_parameters` 是 2.1.302 修复的， collector 属性上限偏低仍要查；若 `user_prompt` 在工具运行中途消失，先确认是否该读 `delivery.mode: "mid_turn"`；若导出静默失败，检查协议默认值、代理与 25 秒上限；若 Cowork 云会话的 `claude_code.session.count` 掉下去，先想「没有消息的会话现在什么都不发」，而不是当成数据丢失。最后，别再给已停止发送的 `claude_code.safety_event` 建看板。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=architecture)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)
- [ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)

## References

- [Claude Code monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- [Claude Code on GitHub](https://github.com/anthropics/claude-code)
- [Claude Code CHANGELOG](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md)
