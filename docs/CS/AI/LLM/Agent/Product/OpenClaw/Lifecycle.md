## Introduction

这一页是 Gateway 的**运行期状态管理**：配置怎么热重载、连接上来的 node 与 session 有哪些生命周期服务、以及它们与 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 权威链的接法。它从 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) 的启动与协议面之后接手——那页讲「怎么起来、怎么说话」，这一页讲「活着的时候怎么变」。

这些子系统全部落**共享 state DB**（不是 per-agent DB），且共享同一条工程原则：**写前重校验 authority，权限校验放在事务 commit 内**。

## Config Reload

有效 runtime 契约是二元的：`resolveGatewayReloadSettings` 只收 `off | hybrid`（schema 里的 `restart` / `hot` 已退役，由 doctor 归一到 hybrid）。

检测有两条路：文件系统侧是 chokidar（`awaitWriteFinish` stability 200ms，watcher 重建最多 3 次）；另一条是 Gateway RPC 写的进程内 fast path——不等 fs 事件，自己写的配置立即感知。

config-diff 递归拆成 dotted path 后过 **policy 表分类**，不同 key 落不同动作：

| 分类 | 动作 |
| :--- | :--- |
| auth token + `secrets.egressProxy` | restart |
| `agents.defaults` / `gateway.controlUi` | hot |
| `plugins.load` / `installs` | reloadPlugins（capability ownership 变更会替换持有其 route 的插件代际） |

auth 凭据轮换是 restart 的热例外。reload 前有 blocker 环：六个 live 计数器、poll 500ms、30s warn，超时后仍执行 reload——**不无限等待活跃工作**。重启 sentinel 持久在 state DB（`gateway_restart_sentinel` 表，CAS 写入）。

## Node Registry

**node-registry 是活连接 roster**——纯内存 Map，没有 node 表。durable 身份在 device pairing 表族（`device_identities` / `device_auth_tokens` / `device_bootstrap_tokens`），经投影回读；**node 可 host worker，但 node 注册 ≠ worker placement**（后者是 durable 表，见 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的 Worker Placement）。

两条细节：declared caps 受 per-session ceiling 压制（node 自报的能力不是最终能力）；invoke 结果对**最近签发的 invoke** 精确匹配（TTL + grace，terminal 即忘）——过期 invoke 的结果不会被误当成新 invoke 的应答。

## Session Services

session-sharing 是 session-scoped 请求的授权 / 可见性 owner。方法集分两类：agent-run-start（`agent` / `chat.send` / `message.action` / `sessions.dispatch` / `talk.*` / `tools.invoke` / `wake`…）与 visibility-authorized。一处刻意保留的不便：**admin 旁路对 agent-run 授权与 progress-card 绑定刻意不給**——管理员可以看很多，但不能借 admin 身份跑别人的 run。

compaction checkpoints 与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的压缩决策互补：那页是「自动压缩怎么触发」，这里是「用户 / 系统主动捕获的检查点」。caps 25/session、64MiB leaf、128MiB retained；捕获是 **identity-only**（不复制 transcript），branch / restore 才在一个写事务里复制 transcript 行 + 更新 `session_nodes.entry_json`。

`chat.abort` 的中止顺序很有讲究：run-abort registry + **terminal ownership 先于 listeners 预留** → 释放 delegated authority → 级联取消（subagent → worker turn claim，见 [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md)）→ 广播一次触达 WS / node-session / 渠道三路。先占终态所有权再通知监听者，避免「中止途中又来一个新 run 抢同一个 slot」。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md) / [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md)
