## Introduction

Claude Code 支持把自身运行数据导出为 **OpenTelemetry**（OTel）信号——日志、指标、trace span。官方文档只给了一页概述，但 CHANGELOG 里积累了大量字段级事实（哪些事件、各带什么属性、哪些开关控制内容捕获），本文据CHANGELOG 整理，是少见的可以从变更记录反推完整事件模型的案例。

事实基线：`@anthropic-ai/claude-code` **2.1.302**（2026-10-16），据官方仓库 CHANGELOG（2026-10-18 全量核对）。

## Security Posture First

这是使用本文所有内容前必须知道的一条（2.1.282）：

> 项目级与本地级 settings **会忽略**所有用于开启导出、设置端点或捕获内容的 OpenTelemetry 变量，包括 `CLAUDE_CODE_ENABLE_TELEMETRY` 与全部 `OTEL_LOG_*`。

即：开启遥测与捕获内容只能在**用户级或 managed settings** 里做，项目仓库无法自行打开它。这是刻意的设计——否则一个 clone 下来的仓库就能把对话内容与工具输出送到攻击者的 collector。

## Core Events

| 事件 | 载荷要点 |
| :--- | :--- |
| `api_request` | 每次 API 请求；`cache_creation_5m_tokens` / `cache_creation_1h_tokens` 按缓存生存期拆分写入量（2.1.300+）；`request_id` 与 Claude apps gateway 的审计日志对齐（gateway 侧有 `request-id` 响应头，2.1.295+） |
| `user_prompt` | 用户提交的 prompt；**`prompt_text` 是 `prompt` 的副本**，给那些会把带点号的键嵌套处理的后端用——在丢弃或脱敏 `prompt` 的地方也要丢弃或脱敏 `prompt_text`（2.1.287，`anthropics/claude-code#70763`） |
| `tool_decision` | 工具调用的审批裁决。`classifier_verdict` 与 `permission_mode` 让auto mode 的 classifier 裁决能与权限规则区分开（2.1.301+）；`OTEL_LOG_TOOL_DETAILS=1` 时附`classifier_category`，点名命中的是哪条内置规则 |
| `tool_result` | 工具执行结果；含 `git_commit_id`，reftable 引用存储下`git commit -q` 也已能记录（2.1.296/2.1.300修复） |
| `hook_execution_complete` | 附 hook 输出大小与被存到文件的超大输出数量（2.1.280+） |
| `claude_code.auth` | 登录事件。Claude apps gateway 登录曾不发此事件，2.1.295 修复；条件是本机已配置 OTel 或会话已登录该 gateway |
| `claude_code.at_mention` | 每次读取 prompt 时的 @ 提及：agent 与 MCP resource 各至多 100 个事件（2.1.293+） |
| `claude_code.tool.blocked_on_user` | span。`-p` / SDK 会话与 PreToolUse hook 审批曾报`unknown` source/decision，2.1.288 修复 |

**内容捕获是严格门控的**：`OTEL_LOG_TOOL_CONTENT=1` 才把 MCP 工具、WebFetch、WebSearch 的输出放进 `tool.output` span 事件（2.1.283+）。不开这个开关，工具输出不会进遥测。

## Spans And Semantics

- v2.1.300 起 trace span 附带 **GenAI 语义约定**属性：`gen_ai.provider.name`、`gen_ai.conversation.id`、`gen_ai.tool.name`、`error.type` 等——即可以直接接入沿用 OTel GenAI 约定的后端，而不必写私有映射。
- 一个易错点：`prompt.submit` 这类 mod hook **改写或丢弃**后的 prompt 不得再被记成「用户原始输入」。2.1.295/2.1.300 修的正是这个——改写后的文本不再写进 prompt 历史与 transcript 的入队记录，`user_prompt` 事件与会话标题请求也不该用原样。这是「遥测要反映实际发生的事」的典型修正。

## Enterprise Gateway Forwarding

组织自建 Claude apps gateway 可以集中转发遥测：

- `telemetry.forward_to` 目的地（2.1.281+），`telemetry.resource_attributes` 给桌面与 `/login` 会话的遥测打固定标签（2.1.281+）。
- `auth: { google: {} }` 支持直接导到 Google Cloud 的 OTLP 端点，复用 gateway 的 Google Cloud 凭据（2.1.284+）。
- gateway 侧的 `inference` 审计事件带 `upstream_request_id`（来自 Bedrock / Anthropic API / 其他上游的请求 ID），用于对账支持工单（2.1.295+）。

Gateway hint header 里还有 `x-claude-code-prompt-id`，让 LLM gateway 能把服务同一个用户 prompt 的多次请求归组（`CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` 开启，2.1.283+）。

## Why It Matters

这套东西的实际用途有三类：把 auto mode 的 classifier 拦截与权限规则拦截在遥测里分开统计（`classifier_verdict` 就是为此加的）；用 `git_commit_id` 把工具动作对上真实提交；在接入 OTel GenAI 约定后，用现成后端而非自建管道看 agent 行为。`tool_decision` 在低 `OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT` 下曾把 `tool_use_id`/`tool_source`/`tool_parameters` 挤掉（2.1.302 修复）——如果你的 collector 属性上限偏低，这是第一个要查的地方。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)

## References

- [Claude Code monitoring usage](https://code.claude.com/docs/en/monitoring-usage)
- [Claude Code on GitHub](https://github.com/anthropics/claude-code)