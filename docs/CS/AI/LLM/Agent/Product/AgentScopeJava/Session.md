# Session

## Introduction

AgentScope Java 的 Session Log 是一层**独立于 Agent 执行的持久化基础设施**：它把 Agent 产生的每条消息、每次工具调用、每份上下文快照按 `sessionId` 组织成可回放、可分叉、可导出的历史。与 Python 版「内存态 conversation + 可选 SQLite 落盘」的做法不同，Java 版的 Session Log 从第一版起就是核心模块，Agent 本身反而是它的消费者——Agent 启动时先向 Session 要历史，执行中把事件写回 Session。

这层设计直接服务于生产环境的三个硬需求：多轮对话可恢复（进程重启不丢上下文）、长任务可审计（谁在什么时候改了什么）、多实例可共享（同一 session 在 Service 模式下被不同节点接管）。

## Architecture

Session Log 采用三层存储结构：

```text
SessionStorage
├── commits/          # 每次 append 的元数据记录（JSON）
│   └── <sessionId>/
│       └── <seq>.json
├── blobs/            # 大对象内容寻址存储（按 sha256 命名）
│   └── <sha256-prefix>/<sha256>
└── inbox/            # 未确认事件缓冲（崩溃恢复用）
    └── <sessionId>/
        └── <eventId>.json
```

- **commits**：一条 commit 记录一次 append 操作的元信息——追加了哪些事件 ID、父 commit 的 hash、时间戳、写入方标识。commit 之间通过 `parentHash` 串成链，天然形成可验证的追加日志。
- **blobs**：消息体、工具结果这类可能很大的负载不直接进 commit，而是按内容 sha256 存入 blobs，commit 里只存引用。重复内容自动去重，大工具结果不会把索引层撑爆。
- **inbox**：事件先写 inbox（带 `acked=false`），确认落盘后再标记。进程在「写 inbox 后、确认前」崩溃，重启时扫描未确认事件重放，保证 at-least-once 语义。

## Atomic CAS And Concurrency

多写方（Service 模式下多个节点、或同进程内多个 Agent）并发写同一 session 时，Session Log 用**乐观并发控制**：

- 每次 append 携带客户端已知的当前 head commit hash；
- 服务端比对本地 head，不匹配则拒绝并返回最新 head，客户端拉取增量后重试；
- 这一层没有全局锁，写冲突通过重试解决，读路径完全无锁。

实现细节上，原子性依赖底层存储的 compare-and-swap 原语：文件系统后端用「写临时文件 + 原子 rename + head 指针文件更新」模拟 CAS；SQLite 后端则直接用 `BEGIN IMMEDIATE` 事务。

## Windows SQLite Caveat

官方文档明确标注了一个 Windows 平台坑：SQLite 后端在 Windows 上的文件锁行为与 POSIX 不同，`BEGIN IMMEDIATE` 在部分网络文件系统（SMB 共享盘）上会退化，导致 CAS 语义被破坏。**结论：生产环境若部署在 Windows 或跨主机的共享卷上，应改用文件系统后端或服务端集中存储**，不要依赖本地 SQLite 做并发写。

## AgentSession API

`AgentSession` 是面向使用者的门面，核心操作：

```java
AgentSession session = AgentSession.builder()
    .sessionId("s-2024-abc")
    .storage(SessionStorage.fileSystem(Path.of("/data/sessions")))
    .build();

// 追加事件
session.append(event);

// 从某个位置回放（恢复 Agent 上下文用）
Flux<AgentEvent> replay = session.replay(fromSeq);

// 分叉：从历史任意点开出一条新分支
AgentSession branch = session.branch(fromSeq, "branch-name");

// 导出：整棵 commit 链 + 引用的 blobs 打包
session.export(Path.of("/tmp/export.zip"));
```

`replay` 返回 `Flux` 而非 `List`，长 session 的恢复是流式的——Agent 边收边往上下文里灌，不需要等全量加载完。

## Identity Model

Session Log 里有三层身份，容易混淆：

| 层级 | 标识 | 作用域 | 说明 |
|---|---|---|---|
| turn | `turnId` | 一次用户输入到 Agent 回复完成 | 一次 `agent.call()` 产生一个 turn |
| run | `runId` | 一次 Agent 执行生命周期 | 一次 run 可包含多个 turn（如会话式 agent 持续运行） |
| session | `sessionId` | 整个会话 | 跨 run、跨进程重启保持同一份历史 |

事件记录同时带这三层 ID，因此既能按 turn 聚合「这一轮用了哪些工具」，也能按 run 聚合「这次执行总共烧了多少 token」，还能按 session 做全量审计。

## Event Catalog

写入 session 的事件类型（与 Message 分册的 AgentEvent 对应，这里是持久化侧）：

- `MsgAdded`：新增一条消息（引用 blob）；
- `CtxUpdated`：上下文状态变更（如 compaction 后写入新 manifest）；
- `ToolCalled` / `ToolReturned`：工具调用与返回；
- `StateChanged`：AgentState 键值对变更；
- `RunStarted` / `RunFinished` / `RunFailed`：run 生命周期边界；
- `SubAgentSpawned` / `SubAgentFinished`：子 agent 派生与回收。

每类事件都带 `seq`（session 内单调递增）与 `ts`，replay 按 `seq` 排序保证因果序。

## Storage Backends

| 后端 | 适用场景 | 并发模型 | 备注 |
|---|---|---|---|
| FileSystem | 单机生产、容器本地卷 | 乐观 CAS（rename 原子性） | 默认后端；commit 文件小、blobs 内容寻址 |
| SQLite | 单机开发、轻量部署 | 事务 CAS | Windows/SMB 上锁语义退化，慎用于并发写 |
| Remote / Service | 多节点共享 session | 服务端串行化 append | 配 Service 的 Session Event Log 使用 |

## Service Agent API

Service 模块把 Session Log 的能力包装成 HTTP 服务，两个入口：

- `POST /v1/agent/chat`：提交一次对话，服务端内部完成「取历史 → 构造上下文 → 调模型 → 写回 session」全流程，以 SSE 流式返回事件；
- `GET /v1/session/{id}/events`：按 session 拉取事件流，支持 `fromSeq` 增量拉取，用于审计或前端重建 UI。

服务端同时暴露 `session-event-log` 端点，把上面 Event Catalog 里的事件原样透出——这也是前端「打字机效果 + 工具调用卡片」实时渲染的数据源。

## Migration, Branch And Export

- **Migration**：版本升级导致事件 schema 变化时，`session.migrate()` 按注册的 migration 链式重放旧事件，产出新 schema 的 commit 链（旧链保留，可回退）。
- **Branch**：`branch(fromSeq)` 复制 head 之前的历史开新链，用于「同一个 session 尝试两种提示词策略」的 A/B 对比，两个分支互不影响。
- **Export**：导出为自包含 zip（commit 链 + 全部引用 blob + manifest），可在另一台机器 `import` 后完整重放。

## Channel And Gateway

Channel 抽象把「同一个 Agent 对外暴露成多个入口」标准化——Web、IM、API 共用同一个 session 与同一份 Session Log，只是接入协议不同：

- **Gateway**：协议适配层，负责把外部协议（如企业微信回调、Slack event）翻译成内部事件进 session；
- 一条来自 IM 的消息和一条来自 Web 的消息进入同一 session 后，Agent 看到的是统一的事件序列，不感知来源差异。

## Links

- [AgentScopeJava 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [Message](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)
- [Context](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- https://java.agentscope.io/v2/zh/docs/harness/session-log
- https://java.agentscope.io/v2/zh/docs/harness/channel
- https://java.agentscope.io/v2/zh/service/session-event-log
