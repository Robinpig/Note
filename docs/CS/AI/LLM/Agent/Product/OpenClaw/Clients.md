## Introduction

这一页是 OpenClaw 的「外部形态」：用户从哪些入口进来（CLI 命令层 / TUI / 原生 app / Control UI / OpenAI 兼容 API）。入口全部连到 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) 的 18789 单端口；部署与托管（容器 / 平台 / Daemon / Fleet）在 [Deployment](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Deployment.md)；其余没展开成独立页的子系统收在末尾的对照表里，作为 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 枢纽的补充索引。

## Command Implementation Layer

命令层要先分清**三个目录三种角色**：`src/cli/program/` 是 Commander dispatcher（`register.*.ts` 声明 `.command()/.option()/.action()`），`src/commands/` 是**命令实现主体**（纯函数式 handler `(opts, runtime, deps?)`，**不 self-register**，没有 `registerXxxCommand` 这种东西），`src/tui/` 与 `src/wizard/` 则是客户端与向导。

关键设计是**两条进入路径共用同一实现**：Path A 的 `findRoutedCommand` 是热路径 fast lane，遍历 `cliCommandCatalog`，对带 route id 的 entry 直接到 `routedCommandDefinitions` 里按该 id 取出定义并传入 argv；Path B 是 Commander `.action()`。两条都 lazy-import **同一个** `src/commands/*` handler——**routed ≠ 独立实现**，只是预先解析 argv 的快车道。懒加载统一用 `createLazyRuntimeModule` 保启动时间。

`agent` 命令是最能体现「同一入口、两条执行形态」的例子。真正的 dispatcher 是 `agentCliCommand`（`src/commands/agent-via-gateway.ts`）：

- **`--local`**：先 `acquireEmbeddedAgentStateLock`（若 Gateway 已持有 state dir 则直接拒），再懒加载 agent、启动一次性 OTel diagnostics 与本地 audit writer，**同进程跑完整个 agent**。
- **默认走 Gateway**：`agentViaGatewayCommandWithTransientRetries` 的**退避阶梯是 `[1s, 2s, 5s, 10s, 15s]`**，然后 `callGateway({ method: "agent", …, idempotencyKey })` 配 spinner；**SIGINT / SIGTERM 桥通过 `chat.abort` 中止已被 accepted 的 Gateway run**；而 **transport loss 故意不 auto-retry**，提示用户自行检查双执行——这正是「等待不授予权限」那条原则在 CLI 侧的体现。
- 输入加固：`--message-file` 有 4 MiB 上限且走 fd-based symlink-safe 读取。

还有一处值得记的复用关系：`src/commands/models/` **既是 CLI handler，又是 claws 与 doctor 复用的校验库**——`inspectModelReference` 导出 `known | unknown-model | uncatalogued-provider | unknown-provider` 四态，`claws/application-plan.ts` 与 `flows/doctor-core-checks.ts` 都 import 它。

## TUI

TUI 是**手写组件式**终端 UI，框架是 `@earendil-works/pi-tui`——**不是 Ink/React，也不是 blessed**。组件类包括 `ChatLog extends Container`、assistant-message、tool-execution、question-prompt、filterable-select-list、custom-editor、hyperlink-markdown、osc8-hyperlinks（终端超链接）。

`TuiBackend` 契约是「传输无关的后端契约」，三个实现各自对应一种形态：

- **injected**：测试与 system-agent 用；
- **EmbeddedTuiBackend**：local 模式，启动整个 TUI 生命周期之前先拿 canonical state lock，若 Gateway 已运行则拒——这就是 VISION.md 里「个人安装独占」的**每台机器、无 daemon 形态**；
- **GatewayChatClient**：WebSocket + 设备身份 + edge auth + 协议版本协商，与原生 app 共用 `chat.send` / `sessions.subscribe` 广播面，对应**共享 Gateway 形态**。

`openclaw tui` 别名 `terminal` / `chat`，`--local` 与 `--url/--token` 互斥。重连由 `resolveGatewayDisconnectState` 分类，`tui-last-session.ts` 记忆上一次会话。

## Setup Wizard

`src/wizard/` 用 `@clack/prompts` 做终端实现，但**同一份 wizard 同时服务两个调用者**：CLI `openclaw onboard` / `setup --wizard`，以及 **Gateway 的 `wizard` server method**（Control UI 与远端 UI 驱动的就是它）。这避免了「终端一套向导、Web 一套向导」的双实现漂移。

`WizardPrompter` 抽象出 `select / multiselect / text / confirm / note / outro`，**敏感输入 masked**，让 secret 永不进 scrollback；导航支持 back/forward。步骤顺序是：风险确认与 telemetry 同意 → config snapshot / merge-base 保留已有 roster → 可选 migration import → model auth → gateway config → memory import → search setup → 官方插件安装 → app 推荐 → 推理验证 → finalize（可直接拉起 TUI）。

其中 `plugin-capability-consent.ts` 是插件 capability consent 的**唯一 UI 契约**：把 `WizardPrompter` 适配成 `PluginCapabilityConsentHandler`，渲染成 note 后要求**显式 confirm（默认 false）**，拒绝即 `prompter.cancel` 结束 setup，接受才返回 `{ reviewToken }`；消费者横跨终端 wizard、Gateway-backed setup 与普通 commands。

顺带澄清一个命名陷阱：`src/interactive/` **不是终端相关的**——它是跨渠道**交互消息 payload 归一**（buttons / question presentations / approval ids / model-picker actions），消费者是 outbound 与渠道 presentation 代码，也就是 IM 里那些按钮的 schema 层。

## Clients and Interfaces

- **原生 app**：Swift 为主（macOS / iOS / Android 等），经 `GatewayChannelActor` 连 Gateway；端点解析支持 local / remote（ssh tunnel / direct）与 Tailscale 发现。
- **Control UI**：与 Gateway 同端口挂载，**活状态不走 HTTP 轮询，走同端口 WS RPC**。
- **OpenAI 兼容 API**：`/v1/models`、`/v1/chat/completions`、`/v1/responses`、`/v1/embeddings`——**默认关闭**；开启后 OpenClaw 作为 provider 服务端被调用，请求经进程内 run 与 WS chat 路共享同一执行器（不是另立 executor），SSE 推增量。
- **其他入口**：watchOS 走有界 HTTPS 轮询（不能用通用 WS）；MCP loopback 是独立的 ephemeral 127.0.0.1 listener。

## Peripheral Subsystems

| 子系统 | 一句话 |
| :--- | :--- |
| Cron | command（纯 exec，不启动 agent）与 agent（真触发一次 run）两类 payload；执行权绑定 admitted run + 一次性消息动作权。完整机制（含任务账本判活）见 [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md) |
| Boards / Canvas | widget 落 per-agent SQLite，pinned widget 需显式 grant；`show_widget` 工具是内容生产端。canvas 文档服务走**主端口 18789**（node-capability auth 门后），18790 sandbox 只服务 `/mcp-app-sandbox` |
| Flows | **不是业务工作流**，是安装与诊断的流程编排（channel onboarding + doctor 健康自检） |
| meeting-bot / talk | 会议机器人（agent / bidi / transcribe 三模式，CDP 驱动真实浏览器入会）与语音交互（唤醒名 ≤2 词、语音 turn 有界上下文 32）；语音是 Channels 之外的另一 I/O 模态，见 [Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md) |
| Routing | 纯函数入站路由（无 I/O）：九档 binding 优先级 + `matchedBy` 溯源；读顶层 `cfg.bindings` |
| Model catalog / plugin-state | 模型清单 = manifest + remote overlay（merge-key 冲突整条丢弃）；插件数据落 `plugin_state_entries` + `plugin_blob_entries` 两表（专用 worker 同步事务，journal 是表上 append 约定非独立表，`core:` 前缀保留是 core/plugin 边界） |
| session-cards / projects | 进度卡落 per-agent `session_progress_cards`，项目注册表落共享 state `projects` 表 |
| pairing | 两套不相关的配对：渠道 DM 配对（8 位码、1h TTL、每 account 上限 3）与设备配对（join code burn-once + 10min bootstrap token + setup payload 带 TLS 指纹）；细节见 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) |

## Deployment, Daemon and Fleet

部署与托管形态（容器 / 平台 / Daemon / Fleet）已独立成页：[Deployment](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Deployment.md)。那页与这一页是「用户从哪进来 / Gateway 被谁托管」的分工。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Deployment](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Deployment.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) / [Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md)
- [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md) / [Nodejs](/docs/CS/front-end/Nodejs.md)
