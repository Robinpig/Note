## Introduction

渠道是 OpenClaw 的入站 / 出站两端：消息从 Slack / Telegram / WhatsApp / CLI / Web UI / 原生 app 进来，路由到 agent，再投递回平台。这一页展开 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md) 枢纽那条主链路的两端——入站 turn 管线与出站双路径；消息进来之后交给 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)，落哪个会话由 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 决定，准入与投递的校验点属于 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的 authority 主线。

## Message Path

核心运行链路：

```
Channel（telegram / whatsapp / slack / 本地 CLI / Web UI / 原生 App）
  │ 入站消息
  ▼ Gateway（auth 校验 + session 投影）
  │ session-row-projection 绑定请求上下文到运行时 owner
  ▼ Agent runtime（装配 agent、建立 admitted run context、run authority）
  │ 选择模型 / 工具（按 plugin owner 的 availability & selection 契约）
  ▼ LLM provider（provider-runtime → provider 插件，如 anthropic / bedrock）
  │ stream / tool-call
  ▼ Tools / Plugins / MCP（经 plugin-sdk 契约执行）
  │ 结果
  ▼ 回写 Session（SQLite 投影）/ 经 Channel 出站回复
```

agent run 产生事件后，一次事件有三条分发路径：**WS 广播**（给 operator 连接：原生 app / Web / ACP client，远端 worker 连接被刻意排除在 chat 广播之外）、**node-session 推送**（给远端 worker 上的 session 做本地渲染）、**外部渠道投递**（Slack / WhatsApp 等平台 API，由 agent 运行时主动调用 message send，独立于 WS 广播）。

## Channel Adapters

渠道接入的边界要先分清：**具体渠道（Slack / Telegram / WhatsApp / Discord / Feishu / IRC / Matrix / Mattermost / MS Teams / Signal 等）不在 `src/channels/`，而是作为 extension 插件存在；`src/channels/` 只提供核心机制层**（registry / pairing / threading / allow-from / 消息适配器 / 入站分类 / turn 管线），且明确禁止插件直接 import 这一层，必须经 plugin-sdk 契约接入。这正是「一次接入，全渠道响应」的适配器模式。

渠道插件实现的是 `ChannelPlugin` 契约——一个聚合多个 adapter surface 的对象，按需组合：

```
id / meta / capabilities     # 身份与能力声明（chatTypes / media / threads / reactions…）
config / setup / setupWizard # 账户列举、接入向导
pairing / security / groups / mentions / allowlist / command-gating
gateway                      # startAccount 启动平台连接、收消息、调 AI 回复
outbound                     # 主动发消息到平台（message tool 用）
threading / message / messaging / streaming
directory / resolver / actions / heartbeat
```

入站是一条 adapter-driven 的 turn 管线：

```
平台原始事件
  → adapter.ingest(raw)           # 解析成 NormalizedTurnInput
  → adapter.classify(input)       # user_request 唤醒 agent / room_event 被动
  → adapter.preflight(input)      # ChannelTurnAdmission 准入
  → adapter.resolveTurn(...)      # 解析成 routed turn（含 routeSessionKey）
  → runPreparedChannelTurn        # 触发 agent run
```

准入模型 `ChannelTurnAdmission` = `dispatch | observeOnly | handled | drop`，与 worker placement 的 run authority 同源：**入站事件也先过 admission 再执行**。执行核心还内建两项治理：丢弃 agent 自己发出、被平台回传当入站的消息（防回声），以及检测两个 bot 互相触发（防循环）。群里未 @ 的消息默认 `room_event` 不唤醒，mention / 控制命令才视为 `user_request`。

出站有两条路径：**被动 reply**（agent run 的回复阶段自动投递，缓冲分块后经渠道 reply adapter 发回原会话）与 **主动 send**（agent 调用 `message` 工具，经 `runMessageAction` 解析目标后调 outbound adapter，做出站白名单校验）。

## Inbound Routing

入站消息落到哪个 agent 由 `src/routing/` 的**纯函数**决定——无运行时、无 I/O，仅凭 config 把渠道流量解析成 `agentId + accountId + sessionKey`，唯一回写是挂在 config 对象上的进程稳定 WeakMap 缓存。设计意图写在 `src/agents/AGENTS.md` 里：target 解析用轻量纯 helper，**不为分类去加载 channel plugin**。

入口 `resolveAgentRoute` 出入都是显式结构，输出带 `matchedBy` 溯源标签枚举每档优先级；渠道侧唯一调用者是入站信封 `resolveChannelInboundRouteEnvelope`，由 `route.sessionKey` 派生 store path。优先级阶梯是一条有序 `||` 链：

```
binding.peer → binding.peer.parent（线程继承）→ binding.peer.wildcard
  → binding.guild+roles → binding.guild → binding.team
  → binding.account → binding.channel → default
```

落不到就回退 `defaultAgentId` / legacy agent，并给出「加 channel-wide binding」的提示。

account 归一有几条硬规则：`DEFAULT_ACCOUNT_ID = "default"`，`normalizeAccountId` 把 undefined / 空串 / 非法值一律归到 `"default"`，带 512 上限缓存且**拒绝原型键**；wildcard `*` 与隐式 default 分两路——`accountId="*"` 进 `byAnyAccount`，具体或省略的经归一进 `byAccount`。这与 CLI 语义一致：`--bind <channel>` 不带 accountId 时只匹配字面 `default`，`*` 是更弱的 channel-wide 回退。

**一条事实修正**：路由读的是**顶层 `cfg.bindings: AgentBinding[]`**（zod 根字段），**不是 `agents.entries.*.bindings`**——`AgentsConfig` 根本没有 per-entry `bindings` 字段；`agents bind` / `applyAgentBindings` 写的就是 `cfg.bindings`。另外 ACP bindings 常被人写成 `agents.entries.*.bindings[].acp`，那其实是同一数组 `cfg.bindings` 按 `normalizeBindingType` 分出 route / acp 两支。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)
