# Session

## Introduction

AgentScope Java 的 Session Log 是一层**独立于 Agent 执行的持久化基础设施**：它把 Agent 产生的每条事件按会话组织成可回放、可恢复、可导出的历史，`AgentSession` 则在它之上提供「提交任务、后台执行、中断续做」的会话级操作入口。

与 Python 版「内存态 conversation + 可选 SQLite 落盘」的做法不同，Java 版的 Session Log 从第一版起就是核心模块，Agent 本身反而是它的消费者——Agent 启动时先向 Session 要历史，执行中把事件写回 Session。这层设计直接服务于生产环境的三个硬需求：多轮对话可恢复（进程重启不丢上下文）、长任务可审计（谁在什么时候改了什么）、多实例可共享（同一 session 在 Service 模式下被不同节点接管）。

本分册事实来自本地 `v2.0.4` 源码树（`agentscope-core/.../session/`、`agentscope-harness/.../memory/session/`、`.../transcript/`、`agentscope-service/`）与官方文档站 v2 会话日志页，冲突处以源码为准。

## Object Layout

日志对象与输入队列按会话保存如下（**身份段用 Base64URL 编码**）：

```text
agents/s_<agent>/sessions/s_<user>/s_<session>/
  session.json                          # 会话元数据
  head.json                             # 日志头（当前 head 指针）
  commits/<batch-hash>.json             # 提交批次
  blobs/<sha256>                        # 较大载荷（内容寻址）
  exports/<sink-hash>.json              # 各导出目标的确认位置
  inbox/                                # 任务、引导、材料、回复的接收记录
    session.json
    head.json
    commits/<batch-hash>.json
```

四类对象的分工：**commits** 保存提交批次；**blobs** 保存较大载荷；**exports** 保存各导出目标的进度；**inbox** 保存任务/steer/材料/回复的接收记录，使输入在执行前也能持久保留。

⚠️ 三个容易搞错的点：

1. **这些对象不是供应用逐行解析的 JSONL**。POSIX 本地对象带版本前缀；Windows 则把逻辑路径、版本和载荷存成 SQLite 数据行——一律通过 SessionLog API 读。
2. **inbox 有独立的序号**，不与执行日志的 `seq` 或 SSE cursor 混用。输入在 checkpoint 提交后才标记为已应用，消费也不会删除原接收记录。
3. **备份必须覆盖**：会话头、日志头及其可达的 commits、blobs、导出记录，**以及 inbox/ 下的日志头及其可达对象**——否则尚未执行的已接收输入会丢。

## Storage Backends

默认情况下 `HarnessAgent` 使用 `WorkspaceSessionLogStore`，日志跟随 Workspace 的 Filesystem 保存：

| 配置 | 记录位置 |
| :--- | :--- |
| 本地 Filesystem | 当前身份解析后的 Filesystem 根下 `.agentscope-runtime/` |
| RemoteFilesystem | 对应 BaseStore namespace 下的 `__agentscope_session_log_v1__` 分区 |
| 单独配置 | `.sessionLogStore(store)` 指定的后端 |
| AgentScope Service 托管 | 服务配置的原生日志 + 公共事件存储 |

「当前身份」由 `SessionKey(userId, agentId, sessionId)` **和** Filesystem 的 namespace 共同确定。开启用户或会话隔离后实际根目录会随身份变化——**不能把所有会话理解为写入 Workspace 下同一个固定目录**。多副本必须连接同一份日志存储并使用一致的身份与 namespace；仅让每个副本使用同名本地目录并不共享会话。

### Atomicity And The Windows Caveat

- **Linux / macOS**：先写临时文件、同步，再通过**原子替换**提交记录，并同步父目录。
- **Windows**：Java 文件系统不能打开目录执行这种同步，因此本地 Session 存储改用 `.agentscope-runtime/journal.sqlite3` 的 SQLite 事务（启用回滚日志 + `synchronous=EXTRA`）。写入仍需通过原子的版本比较，存储错误会返回给调用方。
- **跨平台**：POSIX 文件与 Windows 数据库存放的是**同一套逻辑对象但物理格式不同**，跨平台迁移历史需要做日志迁移，或改用共享后端。备份 Windows 工作区应先暂停所有写入再复制数据库，或用 SQLite 的一致性备份。

自定义后端：实现 `SessionLogStore`，或实现 `AtomicSessionStorage` 并复用 `JournalSessionLog`。它们必须支持**原子版本比较写入、执行写入租约与旧写入者隔离、有序幂等提交、导出进度持久化**——普通文件读写接口不足以保证这些语义。使用 `AgentSession` 命令还要求 `SessionLog.inbox()` 支持持久输入队列（默认 Workspace 与内存日志已提供）。

## AgentSession API

入口是 `agent.session(ctx)`，返回的 `AgentSession` 由框架持有后台执行——HTTP 请求或前端观察连接结束**不会**取消任务。

```java
var session = agent.session(ctx);

// 提交：先持久保存输入再安排执行；requestId 是业务幂等键（重试沿用同标识得到同一次提交的回执）
var task = session.submit("request-001", "比较方案 A 和方案 B。");
System.out.println(task.turnId());        // 排队时 runId 可能尚未分配

// 观察：完成 / 挂起 / 中断 / 失败后返回；suspended 表示在等用户答复，不代表任务完成
var outcome = session.await(task).block();
System.out.println(outcome.status());

// 读取完整对话（含已被压缩出模型上下文的消息，带稳定消息 ID、角色、时间戳）
session.transcript().messages().forEach(m -> System.out.println(m.getTextContent()));

// 执行中调整当前任务（不是新任务）；已发出的模型请求与正在执行的工具参数不会被改写
session.steer(task, "重点比较运维成本。");

// 只存参考资料，不单独启动任务
session.inject("补充材料：团队只有两名运维人员。");

// 待办与答复
session.pending().forEach((requestId, request) ->
        System.out.println(requestId + " " + request.data().get("kind")));
session.respond("external-request-id", "部署在自建 Kubernetes 集群。");   // 外部执行
session.respond(requestId, true);                                         // confirmation 布尔
session.respond(requestId, SessionAnswer.reject("原因"));                  // 带拒绝原因
session.respond(Map.of(id1, ans1, id2, ans2));                             // 多个并行工具一起答

// 中断与续做
session.interrupt();                       // 或 session.interrupt(runId) 避免旧页面误停
var stopped = session.await(task).block();
if ("interrupted".equals(stopped.status())) {
    var continued = session.resume(stopped.turnId());
}

// 重启后：相同 agentId / userId / sessionId / 日志后端重建 Agent
session.start();                           // 检查持久队列；不擅自恢复已中断任务

// 核对结果未知的工具（进程在记录工具结果前退出的场景）
session.inspect().uncertainToolCalls();
agent.reconcileToolOutcomes(ctx, Map.of(result.getId(), result), "已核对订单系统记录");
```

三个语义要点：

- **`await` 只负责观察**，取消对 `await` 的订阅不会取消后台任务。
- **`resume` 只能继续最新的未完成任务**；已完成/取消的不能 resume；有待答交互时应先 `respond`。恢复用的是 checkpoint——不还原 Java 线程、网络请求或工具内部执行进度，也不回滚工具已产生的外部效果。
- **同一会话只能选一套执行方式**：直接 `call` / `streamEvents`，或由 `AgentSession` 调度。已提交任务的进度通过日志观察，再调 `streamEvents` 会启动另一次执行。直接调用的应用中断仍用运行实例上的 `agent.interrupt`——日志负责保存状态，会话入口负责安排后续任务，二者不是互替机制。

## Identity Model

session / turn / run 三层身份，官方文档用一张表说得最清楚：

| 用户操作或执行状态 | turnId | runId |
| :--- | :--- | :--- |
| 提交比较任务，Agent 开始推理并查询资料 | T1 | R1 |
| 刷新页面，恢复消息和工具卡片 | T1 | 仍是 R1 |
| 补充「重点比较成本」（steer） | T1 | 仍是 R1 |
| 中断任务，之后点击继续 | T1 | R1 结束，新建 R2 |
| Agent 挂起等待确认，用户答复后继续 | T1 | R2 结束，新建 R3 |
| 完成后提交另一项任务 | 新建 T2 | 新建 R4 |

`sessionId` 始终是 S1。**四个 ID 不要混用**：提交请求的幂等 key（`requestId`）、HITL 的 `requestId`、工具调用 ID、事件 `eventId` 分别用于防重复提交、回答待办、关联工具结果、去重事件。

## Event Structure And Reading

每条 `SessionEvent` 的载荷都会冻结为 JSON，后续修改原对象不会改变已记录内容：

| 字段 | 用途 |
| :--- | :--- |
| `schemaVersion` | 事件结构版本 |
| `eventId` | 单条事件的稳定 ID，用于去重 |
| `seq` | 会话内的持久顺序（从 1 递增），排序和续读都用它 |
| `occurredAt` | 事件时间；**排序仍使用 seq** |
| `type` | 选择解析和处理方式 |
| `turnId` / `executionRunId` | 关联逻辑任务与实际执行；部分管理操作没有 turnId |
| `payloadJson` / `data()` | JSON 载荷及解析后的 Map |
| `required` | 恢复时是否必须识别该事件类型 |

读取范围从当前日志末尾确定，不会触发模型或工具：

```java
var log = session.log();              // 也可用 agent.sessionLog(ctx)
long through = log.head().seq();
for (var event : log.scan(0, through)) {
    System.out.printf("%d %s turn=%s run=%s%n",
            event.seq(), event.type(), event.turnId(), event.executionRunId());
}
```

分批续读用 `readAfter(lastSeq, limit)`，处理完保存最后一条的 `seq`。**`eventId` 用于接收端去重，不能当作顺序号**。

在 WebFlux handler 里，这些日志读写和 AgentSession 的同步操作会访问存储，应用 `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())` 调度，避免阻塞网络事件线程（`await` 自身已安排好状态轮询）。

### Event Catalog

| 关注什么 | 事件类型 |
| :--- | :--- |
| 执行开始、结束与停止请求 | `run/start`、`run/end`、`run/stop_requested` |
| 任务开始、接续与输出 | `turn/start`、`turn/resumed`、`turn/output` |
| 任务终态 | `turn/completed`、`turn/suspended`、`turn/failed`、`turn/interrupted`、`turn/cancelled` |
| 推理步骤 | `step/start`、`step/end` |
| 输入 | `input/received`、`input/applied`、`input/discarded` |
| 消息 | `message/system`、`message/user`、`message/assistant` |
| 模型 | `request/prepared`、`model/dispatch`、`model/chunk`、`model/end`、`model/retry` |
| 工具 | `tool/requested`、`tool/decision`、`tool/dispatch`、`tool/chunk`、`tool/result` |
| 工具内动作边界 | `action/start`、`action/end` |
| 人工待办 | `interaction/requested`、`interaction/resolved` |
| 上下文与压缩 | `context/build`、`context/replaced`、`compaction/start`、`compaction/end` |
| 状态变更 | `task/changed`、`plan/changed`、`permission/changed`、`verification/result` |
| 子 Agent | `subagent/spawned`、`subagent/completed`、`subagent/linked` |
| 快照与恢复 | `state/checkpoint`、`state/restored`、`recovery/applied`、`migration/baseline` |
| 展示与应用扩展 | `presentation/hint`、应用自定义类型 |
| 输入队列 | `inbox/accepted`、`inbox/opened`、`inbox/closed`、`inbox/handled`、`inbox/rejected`；执行侧 `inbox/started`、`inbox/applied` |

记录范围是**模型适配器可见的请求与输出、工具和框架执行过程**——不含模型服务内部过程，也不会自动备份被引用的文件。原始请求和工具结果可能含业务数据，面向浏览器的接口应挑选需要展示的字段。

## Migration, Branch And Export

| 需求 | API |
| :--- | :--- |
| 将完整状态导入空目标，并记录来源 | `SessionMigration.importBaseline(target, state, source, sourceVersion)` |
| 导出状态及其日志位置 `asOfSeq` | `SessionMigration.exportSnapshot(source)` |
| 只导出工作状态 | `SessionMigration.exportState(source)` |
| 用新身份从当前状态建立会话 | `SessionMigration.fork(source, destination, destinationKey, sourceReference)` |

导出或分支前应**停止源执行**，并处理未知工具结果、尚未结束的执行和待答交互。导入保留的是当时的状态，不会补造更早的执行历史；分支也不会自动复制原会话的完整历史、沙箱或外部资源。

导到其他系统用 `SessionLogExporter` + 应用实现的 `SessionExportSink`：

```java
var exporter = new SessionLogExporter(session.log(), sink);
exporter.drain();
```

`sink.accept` 返回即表示目标已持久接收；导出失败可能**重复投递**，目标端需按 `eventId` 去重；`sink.name()` 应跨部署稳定（框架用它保存各目标的导出进度）。想让执行时自动触发，先把 sink 放进 `RuntimeContext` 的 `SessionExportSink.CONTEXT_KEY`，再首次调用 `agent.session(ctx)`——这不能替代失败后的补投安排。

应用自己的事件用 `SessionRecorder`：

```java
SessionRecorder recorder = SessionRecorder.from(context);
recorder.append("acme/review_note", Map.of("note", note), false);   // false = 仅诊断，恢复不要求识别
recorder.flush();
```

自定义事件若要参与状态恢复，需在运行和恢复前通过 `SessionEventCodecRegistry` 注册校验器与状态还原逻辑；**标记为 `required` 却无法识别的事件会阻止恢复**，所以普通业务诊断事件用 `required=false`。

## Compat Session Tree

`agents/<agentId>/sessions/` 下保留了一套**兼容消息视图**（pi-mono 启发的 JSONL 会话树），与原生 Session Log 并存：

```text
agents/{agentId}/sessions/{sessionId}.jsonl        — LLM 上下文（会被压缩）
agents/{agentId}/sessions/{sessionId}.log.jsonl    — 完整历史（append-only，永不压缩，可 grep）
```

`SessionTree` 管理这棵 append-only 树，每行一个 `SessionEntry`，通过 `id` / `parentId` 形成树。条目类型：`MessageEntry`（对话消息）、`ToolUseEntry` / `ToolResultEntry`（结构化工具调用与结果，按 `toolCallId` 配对）、`CompactionEntry`（标记压缩事件，非破坏性）、`SummaryEntry`（压缩摘要）。`SessionTranscriptWriter` 在 turn 边界写盘，**独立于 memory flush**——transcript 完整性不应依赖 memory-flush 触发器。

跨副本持久化走 `TranscriptStore`（**不可变段**写入，并发写者永不互相覆盖）：

```text
{tenant}/{agentId}/{sessionId}/events/{seqStart}-{seqEnd}-{writerId}.jsonl
```

两个实现：`FilesystemTranscriptStore`（本地 / NAS 目录）与 `ObjectStoreTranscriptStore`（经 `AbstractFilesystem` 写 S3 / OSS / NAS，每次 flush 传新 key，绝不重写已有对象）。legacy 的整文件镜像方式是 O(N²) 上传 + last-writer-wins，不要用。

`SessionFreshnessEvaluator` 支持两种重置策略：**每日重置**（每天到点重置）与**空闲超时**（超过阈值不活动则重置）。

## Channel And Gateway

Channel 把消息平台适配成 Gateway 的路由模型，Gateway 负责会话管理、per-session 并发控制与多 agent 路由：

```java
ChatUiChannel chat = agent.channel(ChatUiChannel.create());   // 懒加载创建内部 gateway 并自动接线

Msg reply = chat.send(SendOptions.userId("user-1"), "你好！").block();       // 每用户一个 session
chat.send(SendOptions.of("user-1", "session-a"), "话题 A").block();          // 同用户多对话
chat.send(SendOptions.userId("user-1").withAgentId("support"), "...").block(); // 多 agent 路由
chat.send(SendOptions.userId("user-1").withAttribute("tenant", "acme"), "...").block();
```

`SendOptions` 五 个工厂/方法：`userId(...)`、`of(userId, sessionId)`、`withAgentId(...)`、`withAttribute(...)`、`withRuntimeContext(...)`（携带完整 RuntimeContext，例如 force-sync 开关）。

RuntimeContext 合并顺序（Gateway 内）：以 caller 上下文为起点 → 若配置了 `ChannelRuntimeContextResolver` 且返回非 null 则**替换** caller base → Gateway 再覆盖身份字段（`sessionId`（`gw-…`）、`userId`、`msgContext`、`gateKey`、`outboundAddress`），冲突时以 Gateway 为准。

多 agent 场景用 `GatewayBootstrap.builder().agent("main", b -> ...)` 接线；子 Agent 暴露给用户直接交互的完整机制见 [技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)
- [工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [AgentScope Java 会话日志](https://java.agentscope.io/v2/zh/docs/harness/session-log)
- [AgentScope Java Channel](https://java.agentscope.io/v2/zh/docs/harness/channel)
- [AgentScope Java 上生产指南](https://java.agentscope.io/v2/zh/docs/others/going-to-production)
