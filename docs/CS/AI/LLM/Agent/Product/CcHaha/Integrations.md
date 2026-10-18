## Introduction

cc-haha 把「会话不止在桌面」做成了核心卖点：通过 **H5 远控**与 **IM 整合**，会话可以从手机浏览器或聊天软件继续驱动。此外还有**计划任务**做无人值守运行。三者都依赖同一套 `adapters/common/ws-bridge.ts` 的 WebSocket 桥。

## IM Integration

`adapters/` 下实际实现的平台目录（相对仓库根）：**wechat / feishu / dingtalk / telegram / whatsapp / qq / slack / wecom**（共 8 个）；本次深挖只读到 wechat / telegram / feishu 三端源码，其余以 README 文档为准。这与 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 的「本地优先个人助手网关、接管 20+ 通讯软件」路线相似，区别在于 cc-haha 以编程工作台为本体、IM 是附属通道，而 OpenClaw 以网关为本体。

**公共架构** `adapters/common/ws-bridge.ts`（`WsBridge`）：

- 维护 `chatId → sessionId` 映射，连接服务端 `/ws/:sessionId`（`connect()`，`ws-bridge.ts:200`）。
- 心跳 30s（`ws-bridge.ts:456`），指数退避重连（`ws-bridge.ts:431`）。
- 每个聊天的**串行化 handler 链**，避免状态竞态（`ws-bridge.ts:251`）。
- 空闲释放 `IDLE_SESSION_RELEASE_MS = 30min`（`ws-bridge.ts:61`）。

**入站消息流**（以已读三端为例）：平台事件 → adapter 处理器（微信 `pollLoop`/`getWechatUpdates`，`wechat/index.ts:610`；Telegram `bot.on('message:text')`，`telegram/index.ts:670`；飞书 `im.message.receive_v1` 分发器，`feishu/index.ts:1266`）→ 配对校验 `isAllowedUser`/`tryPair`（wechat `index.ts:473`、feishu `index.ts:944`、telegram `index.ts:551`）→ `ensureSession` → `createSessionForChat`（`httpClient.createSession` + `bridge.connectSession`，wechat `index.ts:303`）→ `bridge.sendUserMessage`。服务端回包经各端 `handleServerMessage` 渲染成 IM 消息；权限请求以 Telegram InlineKeyboard（`telegram/index.ts:382`）或飞书 interactive 卡片（`feishu/index.ts:531`）呈现，用户「允许 / 永久允许 / 拒绝」，经 `bridge.sendPermissionResponse` 回传。

## H5 Remote Access

`src/server/services/h5AccessService.ts` 是核心：

- `enable()` 生成 token `h5_<base64url 32字节>`（`h5AccessService.ts:159`），以 **sha256 哈希**存入 managed settings 的 `h5Access` 块（`h5AccessService.ts:630`），**重启后保留**（避免已配对手机失效）。
- `validateToken` 比对哈希（`h5AccessService.ts:785`）。
- `publicBaseUrl` 自动探测局域网 IPv4（`findPrivateLanAddress`，`h5AccessService.ts:452`），可经 `CLAUDE_H5_AUTO_PUBLIC_URL` 或手动设置。
- `staticH5.ts` 把 `desktop/dist` 的 H5 页面与 `/assets/*` 提供给手机浏览器（`staticH5.ts:26-55`）。
- 手机扫码 → 浏览器加载 H5 → 经 `/ws/:sessionId?token=...` 连接；鉴权 = token 哈希 + `allowedOrigins` CORS 白名单。`disconnectGraceSeconds` 控制断连后 CLI 子进程的宽限回收。

> 注意 `src/bridge/remoteBridgeCore.ts` 是**另一种特性**——「Env-less Remote Control」云端桥（OAuth → `POST /v1/code/sessions` → `/bridge` → `worker_jwt` → SSE CCRClient），**不是**本地 H5 扫码，勿混淆。

H5 远控的完整令牌 / 配对 / 网络策略 / keepalive / 权限桥协议见 [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)。

## Scheduled Tasks

- **定义**：向导 8 步——Name / Description / Prompt / Model / Permission / Folder / Schedule / Confirm（`ScheduledTaskWizard.tsx:4-11`）。
- **执行**：`useScheduledTasks` 挂载 `createCronScheduler`，`onFire` 把 prompt 以 `'later'` 优先级入队（`useScheduledTasks.ts:84-122`）；SDK / `-p` headless 模式共享同一调度核心。
- **Cron 方案**：自研 `cronMatches` / `fieldMatches`（`cron-scheduler.test.ts:110-223`），**5 字段** `* * * * *`，支持 `,` 列表、`-` 区间、`*/n` 步进、周日 = 0，**拒绝 6 字段**。完整引擎（两套独立调度器、jitter、持久化形态、headless 执行、跨会话锁、7 天自动过期）见 [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)。
- 任务是 **headless 执行**：调度器 spawn 独立 CLI 子进程运行 prompt。

## Desktop Pet

窗体宠物常驻桌面、跟随 agent 活动切换动作与气泡点评（[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) 均无此能力）。内置 4 只（搭搭 Dada / 弧弧 Huhu / 补补 Bubu / 回回 Huihui），DOM/CSS spritesheet 渲染、透明置顶点击穿透窗口；会话集成靠 2s 轮询全局聚合所有 session。完整渲染 / 窗口 / 会话集成 / 自定义宠物校验见 [Pets](/docs/CS/AI/LLM/Agent/Product/CcHaha/Pets.md)。

## Usage Stats

内置用量统计，便于观察模型调用与成本分布。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [ComputerUse](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)
- [MCP_Skills](/docs/CS/AI/LLM/Agent/Product/CcHaha/MCP_Skills.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [adapters/README.md](https://github.com/NanmiCoder/cc-haha/blob/main/adapters/README.md)
- [h5AccessService.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/h5AccessService.ts)
