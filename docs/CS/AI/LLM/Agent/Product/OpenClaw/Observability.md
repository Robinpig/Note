## Introduction

这一页是 OpenClaw 的观测与数据面：日志与运行时自诊断、LLM 流量旁路抓包、会议转写捕获、agent 执行轨迹（trajectory），以及数据库快照与 Git 版本化备份。它和 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的分工在两处容易混，先立清楚：**trajectory 记 run 内部发生了什么**（tool 调用 / 步骤 / 错误，用于 debug 与回放），**transcript 记用户看到的对话**；而 `src/transcripts/` 管的却是第三样东西——会议转写，与 per-agent 的 `transcript_events` 完全不是一族表。

## Logging and Runtime Diagnostics

`src/logging/` 生产日志与诊断事件、持有脱敏与级别策略，但**不拥有外部导出**（OTEL / Prometheus 是 edge 插件），也**不拥有 V8 启动堆预算**（那是 Daemon 的 `gateway-heap.ts`）。日志按 `AGENTS.md` 属「具名用户产物」，因此**落文件、不入 SQLite**——文件名 `openclaw[-<profile>]-YYYY-MM-DD.log`，滚动上限 100 MB、超 24h 剪除；`routeLogsToStderr()` 保 stdout 干净留给 RPC/JSON 输出，`enableConsoleCapture()` 把 `console.*` 一并转文件。级别是 `silent|fatal|error|warn|info|debug|trace`，每条记录带 hostname / agent_id / session_id / channel / trace 字段。

脱敏与 Security 的 secret-mask 同源，默认 mode `"tools"`（最小长度 18、保留前 6 后 4），模式注册表覆盖 PEM、AWS key、支付凭据、tool payload。注释写得很直白：漏凭据的抓取不如不抓。

诊断探针是**进程内采样**而非常驻采集：

| 探针 | 机制与上限 |
| :--- | :--- |
| heap profile | V8 `HeapProfiler.startSampling`，进程内采样，≤ 30s |
| cpu profile | 5s / 10ms 采样，16k 节点 / 65k 样本上限 |
| GC 观察 | `PerformanceObserver("gc")`，**仅在有监听者时**才发 `diagnostic.gc` |
| heartbeat | 周期驱动 run-activity / stability / GC / memory / liveness，含 stuck-session recovery |

两类触发要分清：**按需**经 Gateway RPC `diagnostics.cpuProfile` / `diagnostics.heapProfile`（`hasCurrentClientAuthority` 权威门控，连接退役即中止投递），**周期** heartbeat 由 Gateway 生命周期启动。结构化记录同时扇上诊断事件总线成为 `log.record` 与 `diagnostic.*`。

两处同名异主值得记住：`gateway-heap.ts`（启动 `--max-old-space-size` 预算）与 `diagnostic-heap-profile.ts`（运行期采样快照）不是一回事；OTEL / Prometheus 也不是 logging 子系统成员，而是 `extensions/diagnostics-otel` / `extensions/diagnostics-prometheus` 两个 edge 插件经 `plugins/services.ts` 注册为**可信诊断监听者**后订阅总线。

## Proxy Capture

`src/proxy-capture/` 是 LLM 流量的旁路观测，落共享 state DB 的 `capture_sessions` / `capture_events` / `capture_blobs` 三表，**默认 debug-only opt-in**。

富抓取靠**全局 `fetch` patch，抓的是明文 pre-TLS**——不解密 HTTPS。HTTP 代理模式下 `http://` 请求/响应会被记录（脱敏头、body 预览 8192 B），但 `server.on("connect")` 是**裸 TCP 隧道**（`clientSocket.pipe(upstreamSocket)`），只记 connect/error 与脱敏后的 CONNECT 头，**不终止 TLS**。所以把它描述成「本地 MITM 代理抓包」并不准确：真正的 TLS-MITM（leaf 签发 + `NODE_EXTRA_CA_CERTS`）归 `src/secrets/egress-proxy/`，只是**借用**了这里的 `ca.ts`。两个 CA 的有效期也刻意拉开：debug proxy root CA 7 天（`CN=OpenClaw Debug Proxy`），egress proxy CA 3650 天。

另有 `coverage.ts` 的静态清单给每个 seam 标注 `captured` / `proxy-only` / `uncovered`——它是**覆盖率清单**，不是流量统计。

## Meeting Transcripts

`src/transcripts/` 拥有会议/语音转写会话（live 音频/字幕 provider 或手动导入的话语流），表族是共享 state DB 上的 `meeting_transcript_sessions` / `utterances` / `summaries`，**从不触碰** per-agent 的 `transcript_events`。生命周期由 `startTranscripts`（进程本地 ownership map + 带 retry admission 的 `TranscriptStartError`）与 `finalizeTranscriptCapture`（durable 停止 + summary 持久）两端夹住；store 的定位是 canonical meeting-capture store，**文件仅用于显式导出**。

与 meeting-bot 的归属划分很清楚：本目录拥有 store + 捕获生命周期 + provider 契约 + configured auto-start，meeting-bot 拥有自己的会议会话，并**每 5s 轮询把字幕桥进同一个 `TranscriptsStore`**。消费方是 agent 内置 tool `transcripts`（`list|show|start|stop|import|summarize|status`）、只读 RPC `transcripts.*`（operator-role 可见性门）与 CLI `openclaw transcripts`。一处容易误读的边界：`configured-start-status.ts` 是 process-only 诊断，**从不持久也从不授权捕获**。

## Trajectory

trajectory 是版本化的 agent 执行 trace（schema v1），合并 run 期间记录的 runtime events（prompt / model / tool / turn 事实，已脱敏）与导出时投影的会话转录条目，供 debug / replay 导出，**不是 chat 历史**。

recorder **默认开启**（仅 `OPENCLAW_TRAJECTORY=0` 关闭），单事件 256 KiB 上限并带固定 shedding 顺序（messagesSnapshot → messages → systemPrompt），落盘前 `sanitizeDiagnosticPayload` / `redactSecrets` 脱敏。捕获是 **SQLite-first，JSONL 是 legacy 路径**：写侧 `appendSqliteTrajectoryRuntimeEvents` 每批 32 条，per-session 按 `octet_length` 做 newest-suffix trim 到预算，全局超 14 天 / 512 MiB 则整 run 驱逐；全部落在 `runOpenClawAgentWriteTransaction` 同步事务里。每个 embedded run 各得一份 recorder，远端 worker 的 live projection 复用同一路径；受限的 settled-tool-finalization 会刻意传 `disableTrajectory: true` 退出。

导出 bundle 由 runtime events 与会话分支投影合成，写 `events.jsonl` / `session-branch.json` / `manifest.json` / `system-prompt.txt` / `tools.json`，上限 200k runtime / 250k total / 50 MiB；入口是 CLI `sessions export-trajectory` 与 chat slash `/export-trajectory`（owner-gated）。这里要守一条诚实线：**没有直接 wiring 把 trajectory 导出喂给 subagent 或 media-eval**，不要写「导出即评测数据源」。

## Snapshot and Git Backup

`src/snapshot/` 管理的是 **OpenClaw 数据库**（全局 state DB + per-agent DB）的快照与回滚，**不是 workspace 文件回滚**；两 provider 一契约 `SqliteSnapshotProvider{create,list,restoreFresh,verify}`，DB 身份角色分 `global|agent|generic`。

- **规范 copy 原语**：`createOpenClawSnapshotCopy` 做校验+紧凑 copy，转换时消毒（global 快照清 lease 行），并**嵌入会话 cold archives**；护栏 `assertNotUpdateCapturePath` 保证原始 update-capture 产物绝不进消毒备份或支持导出。
- **本地 provider**：目录 `<repo>/{global|agents/<id>|generic}/` 含 `manifest.json` + `database.sqlite`，manifest 带 sha256 / size / userVersion，拒 hardlink 与 symlink，权限 0700/0600 并带 `.pending` marker。
- **Git provider**：真 git repo（`git init` 或采纳 operator repo，必须在 state dir 之外且私密）。每次备份把每个库 snapshot copy 成**确定性文本 dump**（`manifest.json` + `schema.sql` + `tables/…`），**故意排除投影表**（`backup_runs` / `session_transcript_index_state`）以保幂等；staged 在 repo 外、拷进树、一条 scoped commit `openclaw backup <ISO>`。恢复走 `restoreGitBackupRef`（从 ref 物化到私密 tmp 重建 SQLite），校验走 `verifyGitBackupRef`（restore 到 scratch 逐表 digest 比对），push 前还有 guard 拒推含非备份 commit 的 repo。

调用方是 CLI `openclaw backup sqlite|git`，计划备份被 provisioned 成 Gateway cron job `openclaw-backup-scheduled`，结果账本 `backup_runs` best-effort 写。

**一条重要的事实修正**：updater / doctor 的回滚路径**不调 `src/snapshot`**——`openclaw backup create|verify|restore`（archive 形态）归 `src/infra/backup-create.ts`（config / credentials / sessions / workspace archive），同命令组但异 owner。`src/snapshot` 在 update 流里唯一的触点就是那条排除护栏。

## Data Plane Appendages

- **session-cards**：per-session 进度卡（markdown + checklist steps），落 per-agent `session_progress_cards`，按 `sessionKey` rev-bump replace-on-write，reset 留 tombstone；输入最多一个 `in_progress` step。经 agent tool `progress_card` / `update_plan`、Gateway RPC `progressCard.get/put` + `progressCard.changed` 事件、渠道 edit-streaming 摘要投影生效。
- **projects**：Gateway 可建会话 / worktree 的 git 仓库注册表，落共享 state DB 的 `projects` 表；每 agent workspace 自动浮现为合成 `workspace:<agentId>` 记录。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Clients](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Clients.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) / [Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md)
- [Deployment](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Deployment.md)
