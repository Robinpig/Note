## Introduction

安全是 OpenClaw 的两条设计哲学之一，主轴是 **run authority / live authority**。这一页覆盖认证与设备身份、scope 授权、审批状态机、审计与巡检，并在末尾用 **The Authority Chain** 把散落在渠道准入、worker placement、会话写路径、压缩、审批、出站投递里的同一种范式串成一条主线——那是理解整个 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md) 架构最省力的一条线索。

## Security and Approval

安全模型的主轴是 **run authority / live authority**：任何执行前先认领（turn claim / admitted run context），副作用前再重校验。

**Gateway 认证**：token / password / device token / bootstrap token 多源，认证优先级 explicit token → bootstrapToken → password → stored device token；传输层 WebSocket `wss` 优先，TLS 证书钉扎（SHA-256 leaf fingerprint，Rust 侧常量时间比较，Swift 侧支持 required / TOFU 两种策略）；**设备身份用非对称签名证明持有私钥**。协议面（Gateway 侧 owner `infra/device-identity.ts`）是 **Ed25519**：`deviceId = SHA-256(raw 32-byte public key)` 的 hex，签名覆盖 pipe-delimited canonical payload `v3|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce|platform|deviceFamily`，`signedAt` 与服务器时钟偏差容忍 10min；此后每次连接把 Gateway 签发的 deviceToken（opaque base64url 32B）并入 payload，**签名绑定 token**。Swift/macOS app 侧走 Secure Enclave 的 **P-256**——Apple 安全芯片不支持 Ed25519，这是平台硬件约束下的另一条签名路径（架构文档自标「待进一步确认」；外部客户端实现——Android / Node / 第三方逆向参考——全部只描述 Ed25519 协议面）。connect 握手两端镜像：challenge（nonce + ts）→ connect（协议版本协商 / role / scopes / caps）→ hello（auth 绑定）。一条易被忽略的策略（`connect-policy.ts`）：既不是 control-ui、也不是 loopback 上的 gateway-client+backend、又未完成 Ed25519 设备配对的连接，**scope 直接被剥成空集**——远程 / Tailscale 访问只有设备配对一条路。

**授权**：operator scope 是 8 个闭集（admin / read / write / approvals / questions / pairing / talk / talk.secrets），write 蕴含 read/talk，**未分类 default-deny**；controlPlaneWrite 方法有节流（按 method + device + IP 计窗口）。HTTP 面另有 device-token 回退与自宣 scope 仅可信 ingress 采纳的策略。

**审批**：`operator-approval-store` 是审批状态转换的唯一 durable owner，纯状态机 + 持久，**first-answer-wins**；状态机在 DDL 的 CHECK 元组里强制（pending 无 decision、allowed 必带 allow-*、expired 必 deny+timeout…）；过期是 lazy + claim-time（非 timer）；重启时孤儿 pending 行以 `gateway-restart` 统一取消。exec-approval-manager 坚持**持久先于任何 wait / deliver**，且 allowed verdict 仍复校 live authority——本地 binding 没了即返 null，存储失败 fail-closed。执行身份伴随表只记 provenance，**永不授予权限**。

**审计**（`src/audit/`）是真正的审计事件系统，落 per-agent state DB 的 `audit_events` 表。事件契约 `AUDIT_EVENT_SCHEMA_VERSION = 1`，三类 `kind`：`agent_run` / `tool_action` / `message`；生命周期动作覆盖 `agent.run.started/finished`（status 含 succeeded / failed / cancelled / timed_out / blocked）、`tool.action.started/finished`（带 toolName / toolCallId）、`message.inbound.processed` 与出站三态。脱敏语义是硬性的：每条记录 `redaction: "metadata_only"`，**只存元数据不存消息正文**。出站抑制原因码里出现 `cancelled_by_message_sending_hook` / `empty_after_message_sending_hook`——那是 hooks 在广播前取消或清空出站消息的**落盘证据**。

写入是**单写者 FIFO 队列**而非每事件直写：pending 上限 4096，`structuredClone` 入队后 `setImmediate` 逐条 drain，维护定时器 1 小时做过期数据 prune，SQLite 锁竞争用 busy-timeout + 指数退避。保留策略 30 天 / 10 万行——单写者设计正是为了避免每消息都去扫这 10 万行。

`executionIdentityToken` 是 run authority 在**审计层的物理固化**，形态值得展开看：

- ingress 12 种（local-cli / gateway-client / channel / api / schedule / webhook / task / subagent / acp / worker / plugin / recovery / system 一族），各带 boundary 与 state；
- runtime 5 种（gateway / embedded / worker / plugin-harness / acp）；
- assurance 10 种 kind（durable-profile / trusted-proxy / tailscale-whois / device-proof / channel-admission / local-process / spawn-lineage / worker-admission / runtime-binding / other）× 3 级 strength（**self-asserted < boundary-verified < cryptographic**）。

完整 envelope 是 TypeBox 严格 schema 且有 16 KB / 16 项上限，实际随事件携带的是精简令牌（`tokenVersion` + contextId / executionId / runId）。签发时机很关键：在**权威 run admission** 处捕获，与会话写路径的写前权限校验同源——不是事后补记。

**安全巡检**（`src/security/`）：`src/security/` 里大量 `audit-*` 前缀文件是**安全自检扫描器，不是运行时权限执行点**，真正的执行点在写路径、压缩与授权层。聚合的 finding 包括危险配置标志、exec 文件系统策略漂移、gateway 配置、DM 策略、deep code safety、mcporter registry、插件信任；其中 exec 漂移检测专门抓「mutating fs 工具（write / edit / apply_patch）被禁、但 exec / process 仍可改文件」的**策略错位**，插件供应链侧则查 `plugins.allow` 幽灵条目（可被新插件抢注 id）、无 allowlist 的扩展、宽松工具策略、npm 未钉版本 / 缺 integrity / 版本漂移。密钥遮蔽 `maskApiKey` 是 **UTF-16 安全**的（边缘不切断代理对），与审计 / 日志输出同源。

另有一层容易被忽略的护栏：仓库 `git-hooks/pre-commit` 会在提交前扫描 blocked literals，命中即 `[REDACTED]` 并拒绝提交（`GIT_LITERAL_PATHSPECS` 防 glob 绕过）——那是 OpenClaw **源码自身**的安全护栏，独立于运行期安全层。

**Hooks**：本地可信代码扩展点，每个 hook 是一个目录（HOOK.md frontmatter + handler）；四种来源优先级 bundled < plugin < managed < workspace，**workspace 钩子默认禁用**需显式启用；加载有边界检查（handler 必须落在 hook root 内），整代原子提交，单 handler 抛错不阻断其余。

**Secrets**：SecretRef 语义 fail-closed——provider 必须 enabled、未被 deny、在 allowlist 内才应用。

## The Authority Chain

前面各节是分系统视角；把这些节串起来看，会发现 **run authority / live authority** 不是某个子系统的私有机制，而是贯穿全栈的一条主线。一条入站消息从平台事件走到出站投递，沿途有九个校验点：

```
平台原始事件
  │ adapter.ingest → classify → preflight
  │                                           ❶ ChannelTurnAdmission（dispatch/observeOnly/handled/drop）
  │                                              + 防回声（自己发的被回传）+ 防 bot 互触发
  ▼ 纯函数路由 resolveAgentRoute（九档）       → routeSessionKey
  ▼ session 读投影（三元组身份 / federation 多副本 / incognito 隔离）
  ▼ run 准入：admitted run context + run authority
  │                                           ❷ 远端走 turn claim；每次 worker RPC 重校验 live ownership
  ▼ prompt 构建 + 压缩决策（四路由）
  │                                           ❸ writerFence（expectedWriterRunId / lifecycleRevision）
  ▼ provider 调用 → 双层 tool-call 循环
  │                                           ❹ admitToolCallBatch + 循环检测器；执行前/副作用前重校验
  ▼ 工具结果回灌 context.messages
  ▼ 写回（两条独立写路径）
  │   A. 元数据 mutation                       ❺ commitGuard 多处重校验 + lifecycle mutex + snapshot 再解析
  │   B. transcript 事件                       ❻ writer fence，压缩不绕过写权限
  ▼ 产出分发（三条并行）
  │   WS 广播                                  ❼ scope guards + run ownership（claimId + generation）
  │   node-session 推送（远端 worker 本地渲染）
  │   外部渠道投递                             ❽ custody fence + 出站白名单
  ▼ 审计落盘                                   ❾ executionIdentityToken 在准入点签发、随事件携带
```

| # | 校验点 | 校验的是什么 | 失败后果 |
| :--- | :--- | :--- | :--- |
| ❶ | Channel Turn Admission | 这个入站事件**值不值得**唤醒 agent | `observeOnly` / `handled` / `drop` |
| ❷ | Turn claim / placement 准入 | 谁**独占**这一轮执行权（owner + sessionId + runId + environmentId + ownerEpoch 全匹配） | 拒执行；stale worker build 拿不到 authority |
| ❸ | Writer fence | 压缩 / 转录写入方是不是**当前** writer | `SessionTranscriptWriterClaimReboundError` |
| ❹ | Tool-loop admission | 这一批工具调用是否越过循环阈值 | critical 级 veto 直接中断 |
| ❺ | Commit guard | 从 preflight 到落盘，authority 是否**中途变了** | `SessionMutationAuthorizationChangedError` / `sessionChangedError`（要求 retry） |
| ❻ | Writer fence（转录） | 同 ❸，作用于事件流路径 | 写入被拒 |
| ❼ | Run ownership（广播前） | `contextClaimId` + `lifecycleGeneration` 仍匹配吗 | detach / supersession 吊销终态事件 |
| ❽ | Custody fence（出站） | 投递前的 adapter handoff 与 delivery 队列身份 | 不投递 |
| ❾ | Execution identity | 「谁、从哪、以何强度准入」在准入点固化 | 审计链断（不阻断执行） |

同一条原则在六个不同子系统里各自落地，形态不同但内核一致：**worker placement**（每次 RPC 重校验 live ownership）、**原生 App**（`ServerLease` / socket / route generation，注释写 "revalidate before either outcome reaches a replacement owner"）、**session 写路径**（commit guard 在写前、写时、写事务内反复校验）、**压缩**（复用 run authority，不绕过写权限）、**审批解析**（allowed verdict 执行前仍复校 live authority，本地 binding 消失即返回 null，存储失败 fail-closed）、**出站投递**（投递前 custody fence）。

它还有一次**物理固化**：`session_nodes` 上的 AFTER 触发器在元数据写入时把 `entry_valid` 置 0——**写即失效、读前重准入**，把「依赖事实而非凭据」这条原则直接钉进存储层。写路径里另外两条同源设计也值得记住：lifecycle mutex 按 `storePath + identity` 串行化，防止活跃 run 从两次 writer 获取之间溜进去；以及**权限校验放在事务 commit 内**——失败整事务回滚，而不是 COMMIT 之后再 repair（那会让调用方重试一个已经持久化的事务）。

一句话概括这套范式，是三条不等式：

1. **匹配标识 ≠ live authority**——credential hash、TTL、id 都对，不代表此刻仍持有权限。
2. **等待不授予权限**——任何 `await` 之后、任何副作用之前都要重校验。
3. **已持久化的 verdict ≠ 可立即执行**——审批、claim、placement 落库只是记录，执行前仍要复校。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [OpenClaw Gateway Client V3 Device Auth Reference](https://github.com/KangCaijun/openclaw-gateway-client)
- [OpenClaw Assistant Device Identity and Pairing（DeepWiki）](https://deepwiki.com/yuga-hashimoto/openclaw-assistant/3.3-device-identity-and-pairing)
