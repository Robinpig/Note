## Introduction

沙箱是 AgentScope Java 把 Agent 的 shell 命令与文件读写放进**隔离执行环境**的机制——agent 不再直接碰宿主 shell，而是由一套 `Sandbox` 抽象把命令发往容器 / 远端环境执行。它和 [工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md) 是同一件事的两个视角：Workspace 讲「文件世界的关系」（目录布局 / 身份 / 三种 filesystem 模式），本分册讲「隔离执行环境本身」——生命周期、隔离范围、工作区投影、快照、文件系统桥、后端实现与并发护栏。事实来自本地 `v2.0.4` 源码逐包核对（`agentscope-harness/.../sandbox/`、`.../filesystem/`、`agentscope-extensions-sandbox/*`、`agentscope-extensions-{redis,jdbc,mysql,postgresql,mongodb,aistio}`），冲突处以源码为准。

> 几个先说清的易错点（源码与直觉冲突，已逐条核实）：
> 1. **docker 后端默认不保存快照**——`DockerFilesystemSpec` 的 `snapshotSpec` 默认是 `NoopSnapshotSpec`，需显式配 `LocalSnapshotSpec` / `RemoteSnapshotSpec` 才持久化。
> 2. **`WorkspaceArchiveExtractor` 全仓只在单测被调用**——docker 后端的 persist / hydrate 走 `docker exec tar`，并未接 `WorkspaceArchiveExtractor`。
> 3. **`SANDBOXED` 不是「拒绝绝对路径」**——`LocalFsMode.SANDBOXED` 是把绝对路径去前导 `/` 后 re-root 到 workspace 根，真正拒绝的是 `..` 段与最终越界。
> 4. **四个扩展后端（k8s / e2b / daytona / agentrun）都没有自带 `SandboxExecutionGuard`**——并发串行化护栏由 store 级扩展（redis / jdbc / mysql / postgresql / mongodb / aistio）提供。

## Core Abstraction

沙箱核心是一组 harness 顶层抽象，所有后端共享同一套生命周期契约。

### Sandbox Interface

`Sandbox`（`agentscope-harness/.../sandbox/Sandbox.java:42`）是活跃沙箱的接口，生命周期由 javadoc 固定五步：`create/resume → start → use(exec/persist/hydrate) → stop → shutdown`，`close() = stop + shutdown`。它特别区分两种"停止"：

```java
// Sandbox.java:35-40, 44-53
void start() throws Exception;          // 初始化或恢复工作区
void stop() throws Exception;           // 仅持久化快照，安全用于自托管与用户托管
default void shutdown() throws Exception { }   // 销毁后端资源，仅自托管调用
void close() throws Exception;          // stop + shutdown
ExecResult exec(RuntimeContext rc, String command, Integer timeoutSeconds) throws Exception;
InputStream persistWorkspace() throws Exception;   // 打包 /workspace 成 tar
void hydrateWorkspace(InputStream archive) throws Exception;  // 解包进 /workspace
```

`stop()` 与 `shutdown()` 的分野是并发语义的关键：用户托管的沙箱（Priority 1）在多次 acquire/release 之间要保持存活，`release` 只调 `stop()` 而不 `shutdown()`（`SandboxManager.java:197-199`）。

### SandboxClient SPI

`SandboxClient<O extends SandboxClientOptions>`（`.../sandbox/SandboxClient.java:25-48`）是后端工厂接口，也是 SPI 扩展点：

```java
Sandbox create(WorkspaceSpec workspaceSpec, SandboxSnapshotSpec snapshotSpec, O options);  // 新建，pre-start 态
Sandbox resume(SandboxState state);              // 从序列化状态恢复
void delete(Sandbox sandbox);
String serializeState(SandboxState state);
SandboxState deserializeState(String json);      // 另有重载接受 snapshotSpec
```

### SandboxState And WorkspaceSpec

`SandboxState` 是可序列化状态（`getState()` 返回），携带 `containerId` / `workspaceRoot` / `snapshot` / `workspaceProjectionHash` 等；`WorkspaceSpec`（`.../sandbox/WorkspaceSpec.java:43-47`）只有三个字段——`root`（默认 `/workspace`）、`entries`（`Map<String, WorkspaceEntry>`）、`environment`。**没有**独立的 git / bind-mount / archive 字段，这些都由 `WorkspaceEntry` 子类型承载在 `entries` 里。

### AbstractBaseSandbox Four-Branch Init

`AbstractBaseSandbox` 提供标准的 `start()` 四分支工作区初始化，所有后端复用。逻辑（`.../sandbox/AbstractBaseSandbox.java:75-117`）：

```java
if (state.isWorkspaceRootReady()) {
    applyWorkspaceSpec(spec, true);                       // Branch A: 仅 replay ephemeral entries
    if (snapshot.isRestorable()) {
        snapshot.restore(); doHydrateWorkspace();         // Branch B
        applyWorkspaceSpec(spec, true);
    }
} else {
    if (snapshot.isRestorable()) {
        snapshot.restore(); doHydrateWorkspace();         // Branch C
        applyWorkspaceSpec(spec, false);
    } else {
        applyWorkspaceSpec(spec, false);                  // Branch D: 全新全量初始化
    }
}
applyWorkspaceProjectionIfChanged(spec);                 // 第 116 行：投影永远最后叠加
state.setWorkspaceRootReady(true);
```

要点：`isWorkspaceRootReady()==true` 表示根已初始化（resume 场景），只重放 `isEphemeral()` 的 entry；`false` 表示全新，全量物化。`snapshot.restore()` 与 spec 物化都在前面，**投影在 `start()` 末尾第 116 行执行**，所以投影是叠加层。

### SandboxContext

`SandboxContext`（`.../sandbox/SandboxContext.java:27-130`）是不可变的 per-call 沙箱配置：持有 `client` / `clientOptions` / `workspaceSpec` / `snapshotSpec` / `externalSandbox` / `externalSandboxState` / `isolationScope`，在 `HarnessAgent.build()` 时构造，attach 到 `RuntimeContext`。

## Lifecycle And Acquisition

### SandboxManager.acquire Priority Chain

`SandboxManager.acquire`（`.../sandbox/SandboxManager.java:69-155`）决定"这次 call 用哪个沙箱"，优先级链：

1. **Priority 1**：`getExternalSandbox() != null` → 用户托管，`guard` 不生效，直接 `userManaged`。
2. **Priority 2**：`getExternalSandboxState() != null` → `client.resume(state)`，`selfManaged`。
3. **Priority 3**：解析出 `scopeKey` 且 `stateStore.load(scopeKey)` 命中 → `client.resume(state)`；**恢复前用当前应用配置覆盖 stale `WorkspaceSpec`**（`state.setWorkspaceSpec(...copy())`，`:111-114`）。
4. **Priority 4**：否则 `client.create(...)` 全新沙箱。

带 `SandboxExecutionGuard` 时，**Priority 3/4 在 resume/create 之前**先 `executionGuard.tryEnter(scopeKey)` 拿 `SandboxLease`（`:94-98`），lease 由 `SandboxAcquireResult` 携带。一个关键容错：`resume` 失败时 fallback 到 `create`，但通过 `carryOverPersistedSnapshotId`（`:165-182`）保留旧的 snapshot id，使新建沙箱仍从上一 archive 恢复工作区，而不是静默重置。

### Guard Covers The Full Call Window

`SandboxExecutionGuard` 的契约（`.../sandbox/SandboxExecutionGuard.java:54-56`）明确：harness 在 `acquire` 前 `tryEnter`、在 `release` 完成后 `lease.close()`，覆盖 `acquire → start → (call) → stop → release → lease.close()` 全程。Priority 1/2 因调用方自管沙箱而绕过 guard。

### SandboxLifecycleMiddleware Borrow-Return

`SandboxLifecycleMiddleware`（`.../middleware/SandboxLifecycleMiddleware.java:56-180`）是沙箱与执行循环的交汇点，由 `ReActAgent.beforeAgentExecution()` / `afterAgentExecution()` 调用：

- **acquireForCall**（`:89-143`）：读 `SandboxContext` → 跑 `beforeStartCallback`（让调用方先在宿主物化资源，如 `.skills-cache/`，使投影同次调用即生效）→ `sandboxManager.acquire` → `sandbox.start()`（4 分支）→ **per-call 绑定**：`ctx.put(SandboxAcquireResult.class, result)` 且 `filesystemProxy.setSandbox(sandbox)`。
- **releaseForCall**（`:151-179`）：读回本 call 建立的绑定 → CAS 式 `clearSandboxIfCurrent(sandbox)`（只清仍指向自己的 fallback 字段，防并发兄弟调用被误清，修 issue #2490）→ `sandboxManager.release(stop)` → `persistState` → `lease.close()`。

> **issue #2490 根因**：沙箱绑定必须是 **per-call** 落在 `RuntimeContext` 上，而非 agent 级共享 slot——同一 `HarnessAgent` bean 上不同 `(userId, sessionId)` 会话并行跑，共享 slot 会让并发调用互相覆盖对方的绑定。

post-call 的 persist / release 失败只记日志不抛异常（`SandboxLifecycleMiddleware.java:48-49`），保证 agent 调用结果总能返回给调用方。

### Release, Persist, Clear

- `release`（`:184-212`）：非自托管直接返回；自托管依次 `stop()`（持久化快照）与 `shutdown()`（销毁后端），各自异常只 warn。
- `persistState`（`:214-252`）：自托管才写；按 `scopeKey` 把 `client.serializeState(state)` 存入 `SessionSandboxStateStore`。
- `clearState`（`:254-269`）：删除 scope 对应的持久化状态（用 tombstone，见下）。

## Isolation Scope

### IsolationScope Four Values

`IsolationScope`（`.../agent/IsolationScope.java:53-87`）决定谁和谁共享同一份沙箱状态槽：

| Scope | 含义 | 默认 |
| :--- | :--- | :--- |
| `SESSION` | 每个 `sessionId` 独立 | |
| `USER` | 同一 `userId` 跨会话共享 | **默认** |
| `AGENT` | 同一 agent 所有用户/会话共享 | |
| `GLOBAL` | 全局共享一份 | |

缺 `userId` 时 `USER` 降级为 `SESSION`；`AGENT` / `GLOBAL` 不会因缺字段而降级（`agentId` 在 build 时固定）。

### SandboxIsolationKey.resolve

`SandboxIsolationKey.resolve(scope, ctx, agentId)`（`.../sandbox/SandboxIsolationKey.java:67-104`）按 scope 产出不可变 key：

- `SESSION`：需 `sessionId`，否则 empty；
- `USER`：用 `userId`，缺则降级 `SESSION` 用 `sessionId`，两者皆缺则 empty（跳过状态查找，新建）；
- `AGENT`：`agentId`（恒有）；
- `GLOBAL`：固定值 `__global__`（`:37`）；
- `null` scope：按 `USER` 处理。

### SessionSandboxStateStore Slot Encoding

`SessionSandboxStateStore`（`.../sandbox/SessionSandboxStateStore.java:32-103`）复用通用 `AgentStateStore`，因此**提供分布式 `AgentStateStore`（如 Redis）即自动启用分布式沙箱恢复**。slot 键编码（`slotSessionId`，`:84-92`）：

| Scope | slot sessionId |
| :--- | :--- |
| `SESSION` | `sandbox/session/<id>` |
| `USER` | `sandbox/user/<agentId>/<userId>` |
| `AGENT` | `sandbox/agent/<agentId>` |
| `GLOBAL` | `sandbox/global` |

`userId` 列恒为 `null`——沙箱状态概念上是 agent 范围的，`USER/AGENT/GLOBAL` 已编码进 sessionId 前缀。删除用 tombstone（`SandboxStateSlot.tombstone()`，`:99-102`），因为并非所有 `AgentStateStore` 支持按 key 删除。

### Sequential-Reuse, Not Live-Instance Sharing

`IsolationScope` 的 javadoc（`:49-52`）与源码一致地声明：沙箱模式下同一 scope key 的并发调用**各自启动独立容器**，调用结束时**最后写入的快照胜出**——是顺序复用，不是实时实例共享。这正是 [工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md) 第 153 行警告的含义，也是 `executionGuard` 存在的理由。

## Workspace Projection

### Projection Roots And Hash

默认投影根常量 `DEFAULT_WORKSPACE_PROJECTION_ROOTS` 在 `SandboxFilesystemSpec.java:41-42`，值为 `AGENTS.md, skills, subagents, knowledge, .skills-cache`（注意：不在 `WorkspaceSpec` 里）。`WorkspaceProjectionApplier.build(spec)`（`.../sandbox/WorkspaceProjectionApplier.java:50-88`）把 `includeRoots` 下的宿主文件打成内存 tar，并对每个文件按 `rel路径 + (byte)0 + 内容` 累加 SHA-256（`:64-75`）；hash 存于 `state.getWorkspaceProjectionHash()`。

跳过 hydrate 的逻辑**不在 Applier 内**，而在调用方 `AbstractBaseSandbox.applyWorkspaceProjectionIfChanged`（`:267-287`）：

```java
WorkspaceProjectionApplier.ProjectionPayload payload = WorkspaceProjectionApplier.build(spec);
if (payload == null) return;
if (Objects.equals(payload.hash(), state.getWorkspaceProjectionHash())) {
    log.debug("[sandbox] Workspace projection unchanged, skipping");
    return;   // 命中：不重复 hydrate
}
state.setWorkspaceProjectionHash(payload.hash());
```

### Mount Root And What WorkspaceArchiveExtractor Does Not Do

投影默认挂到容器 `/workspace`（docker 默认 `workspaceRoot=/workspace`，`DockerSandboxClientOptions.java:39`；hydrate 走 `docker exec -i <cid> tar -xf - -C <root>`）。

`WorkspaceArchiveExtractor.extractTarArchive`（`.../sandbox/WorkspaceArchiveExtractor.java:54-81`，含 Zip-Slip 防护）**全仓仅在单测被调用**——docker 后端的打包/解包直接走 `docker exec tar`（`DockerSandbox.java:207-218` 打包带 bind-mount 排除、`262-280` 解包），并未接 `WorkspaceArchiveExtractor`。这是"直觉以为有统一工具类"与源码的差异点。

### Projection And Snapshot Cooperation

如 `AbstractBaseSandbox.start()` 四分支所示，**同 scope 一次调用的顺序 = 快照恢复（若有）→ spec entries 物化 → 投影叠加（带 hash 跳过）**。投影永远在最后，且自身有 hash 短路：内容未变则不重写，所以反复 `call()` 不会重复传相同文件。

## Snapshot

### Interfaces

- `SandboxSnapshot`（`.../sandbox/snapshot/SandboxSnapshot.java:37-92`）：`persist(InputStream)` / `restore()` / `isRestorable()` / `getId()` / `getType()`，默认 `isPersistenceEnabled()` 返回 `true`。
- `SandboxSnapshotSpec`（`.../sandbox/snapshot/SandboxSnapshotSpec.java:28-37`）：`build(String snapshotId)`，每会话独立 id。

### Three Spec Implementations

| Spec | 落点 | 行为 |
| :--- | :--- | :--- |
| `LocalSnapshotSpec` | `{basePath}/{id}.tar` | 原子写（先写 `.{id}.{uuid}.tmp` 再 `ATOMIC_MOVE`，`LocalSandboxSnapshot.java:69-95`） |
| `RemoteSnapshotSpec` | `RemoteSnapshotClient`（S3 / OSS / GCS，`RemoteSnapshotClient.java:28-56`） | 后端实现 `upload/download/exists` |
| `NoopSnapshotSpec` | 无 | **`isPersistenceEnabled()=false`**，`persist` 丢弃、`restore` 抛异常（`NoopSandboxSnapshot.java:44-70`） |

`DockerFilesystemSpec.java:35` 把 `snapshotSpec` 默认置为 `NoopSnapshotSpec`——即 **docker 后端默认不保存快照**，需显式覆盖才持久化。

### Tie-In With start/stop

- **恢复**：`start()` Branch B / C 调 `snapshot.restore()` → `doHydrateWorkspace`（`AbstractBaseSandbox.java:86-107`）。
- **持久化**：`stop()` 中 `if (snapshot != null && snapshot.isPersistenceEnabled()) { try(InputStream a=doPersistWorkspace()){ snapshot.persist(a); } }`（`:132-141`）。
- docker `doPersistWorkspace` 用 `tar -cf - -C <root> .` 全量打包整个 `/workspace`（`DockerSandbox.java:207-218`），非增量。

## Filesystem Bridge

### AbstractFilesystem

Agent 访问文件世界的统一抽象是 `AbstractFilesystem`（`.../filesystem/AbstractFilesystem.java:44`）——**不是** `Filesystem`（无此接口）。核心方法：`ls` / `read` / `write`（只写新文件）/ `edit` / `grep` / `glob` / `uploadFiles` / `downloadFiles` / `delete`（幂等）/ `move` / `exists`；**无** `mkdir` / `copy`（mkdir 仅作 shell 串出现）。接口内建静态 `validatePath`（`:178-188`）拒绝 null/blank 与 `..` 段。

### LocalFsMode Three Values

`LocalFsMode`（`.../agent/workspace/LocalFsMode.java:37-41`）取值 `SANDBOXED` / `ROOTED`（默认）/ `UNRESTRICTED`——**没有 `DIRECT`**。路径解析在 `LocalFilesystem.resolveSandboxed`（`.../filesystem/local/LocalFilesystem.java:609-621`）：

```java
private Path resolveSandboxed(String effectiveKey) {
    String vpath = effectiveKey.startsWith("/") ? effectiveKey : "/" + effectiveKey;
    if (vpath.contains("..") || vpath.startsWith("~"))
        throw new SecurityException("Path traversal not allowed");
    Path full = cwd.resolve(stripWindowsDrive(vpath.substring(1))).normalize();
    if (!full.startsWith(cwd))
        throw new SecurityException("Path " + full + " outside root directory: " + cwd);
    return full;
}
```

**关键纠正**：`SANDBOXED` 不是"拒绝绝对路径"——它把绝对路径去前导 `/` 后 re-root 到 `cwd`（所以 `/etc/passwd` 会变成 `cwd/etc/passwd`），真正拒绝的是 `..` 段与 `!full.startsWith(cwd)` 的越界兜底。`ROOTED` 用 `PathPolicy.isAllowed`（allow-list，本身不抛异常，抛异常在 `LocalFilesystem.rootAccessDenied`）校验。

### SandboxBackedFilesystem Forwards To Sandbox.exec

`SandboxBackedFilesystem extends BaseSandboxFilesystem implements SandboxAware`（`.../filesystem/sandbox/SandboxBackedFilesystem.java:60`）**不直接构造 cat/ls 命令**——读/列/删等命令在基类 `BaseSandboxFilesystem` 里拼成 shell 串（`read` 用 `sed`/`base64`、`ls` 用 shell 循环+`stat`、`grep` 用 `grep`、`glob` 用 `find`），再调抽象方法 `execute(...)`，而 `SandboxBackedFilesystem` 把 `execute` 重写为调用 `Sandbox.exec(...)`（`SandboxBackedFilesystem.java:100-120`）。也有 `SandboxFileTransfer` 原生单文件上传（`uploadFile`）优先、否则回退 tar hydrate（`:136-167`）；下载回退用 `base64 <path>` 经 `exec`。

`setSandbox` 只是给**无 `RuntimeContext` 的调用者**（如 `WorkspaceMessageBus`）留的 fallback 字段；并发安全的真实绑定是 `RuntimeContext` 上的 `SandboxAcquireResult`，`requireSandbox` 优先读它，`clearSandboxIfCurrent` 做 CAS 比较（`:72-92`）。

### Overlay / ProjectAwareOverlay / Pinned

- `OverlayFilesystem`（`.../filesystem/OverlayFilesystem.java:56`）：upper（读写，优先）/ lower（只读）copy-on-write；`ls` 取并集、`read` 先 upper 后 lower、`delete` 只删 upper（删共享层抛 `Cannot delete shared file`）、`exists` 任一层存在即真。
- `ProjectAwareOverlay`（`.../filesystem/ProjectAwareOverlay.java:54`）：在 overlay 之上按 `WORKSPACE_PREFIXES` 把写路由到 project 层（`projectWritable(true)` 时由 `LocalFilesystemSpec` 产出，`write` 路由 `:133-140`）。
- `PinnedSandboxFilesystem`（`.../filesystem/sandbox/PinnedSandboxFilesystem.java:34`）：`extends SandboxBackedFilesystem`，构造时钉死一个 `Sandbox`，`clearSandboxIfCurrent` 为 **no-op**——用于 call 释放后的异步镜像上传仍需该引用。

### Routed / Composite

- `CompositeFilesystem`（`.../filesystem/CompositeFilesystem.java:64`）：按**路径前缀**最长匹配路由到不同 backend（默认 backend 兜底），刻意**不实现 `execute`**（跨 store 路由 shell 命令是歧义的），`move` 跨 backend 降级为 读→写→删。
- `RoutedSandboxFilesystem`（`.../filesystem/RoutedSandboxFilesystem.java:41`）：持 `primary`（沙箱后端）+ `CompositeFilesystem`；文件操作委派 composite，但 `execute` / `id` **永远走 primary**（`:70-74`），可保留 shell 执行同时把 `memory-stores/` 等前缀挂到 JPA 后端。**路由维度是路径前缀，不是 `scope`/`userId`**——会话/用户隔离由 `RuntimeContext` 的 namespace（`NamespaceFactory`）实现。

### Path Safety Summary

| 输入 | `SANDBOXED`（`:609-621`） | `ROOTED`（`:633-669`） | `UNRESTRICTED`（`:681-687`） |
| :--- | :--- | :--- | :--- |
| `read("/workspace/x")` | `/` 去掉 → `cwd/workspace/x` | 落 cwd/Policy root 才放行 | 原样 `cwd.resolve` 或绝对透传 |
| `read("../../etc/passwd")` | `contains("..")` → `SecurityException` | `validatePath` 抛 `IllegalArgumentException` | `cwd.resolve(...).normalize()` → **可能真实越界读宿主文件** |
| `read("/etc/passwd")` | 去 `/` → `cwd/etc/passwd`（非真 /etc） | 不在 cwd/Policy root → 拒绝 | 原样读真实 `/etc/passwd` |

沙箱端（`SandboxBackedFilesystem` + `BaseSandboxFilesystem`）路径直接作为**容器内**路径传 `exec`，天然限制在容器内；上传额外有 workspace 根约束 `resolveArchivePath`（越界 → `IOException "outside the sandbox workspace"`）。

## Backends

### Five Backends Overview

| 后端 | 模块坐标 | 底层机制 | 是否 harness 自带 | 状态持久化方式 |
| :--- | :--- | :--- | :--- | :--- |
| Docker | `.../impl/docker/` | `docker` CLI via `ProcessBuilder`（无 docker-java / Testcontainers） | **是** | 序列化 `containerId/containerName`；工作区 tar 进 state store；resume 复用/重启容器 |
| Kubernetes | `agentscope-extensions-sandbox-kubernetes` | fabric8 + agent-sandbox CRD；`SandboxClaim` + warmPool；隧道 port-forward / gateway / direct | 否 | 以 `SandboxClaim`（claimName/namespace）为锚；工作区走运行时文件 API 或 exec tar |
| E2B | `agentscope-extensions-sandbox-e2b` | exec 走 envd protobuf；生命周期/快照走 Platform HTTP（OkHttp） | 否 | `sandboxId` + 原生 snapshot templates（`snapshotIds` 列表，retention 清理） |
| Daytona | `agentscope-extensions-sandbox-daytona` | 纯 HTTP 数据面（`DaytonaHttp` / OkHttp） | 否 | `sandboxId`（+可选 `snapshotId`）；工作区 tar|base64 over HTTP |
| AgentRun | `agentscope-extensions-sandbox-agentrun` | HTTP 控制面（`AgentRunDataPlaneHttp`）+ MCP 执行面（`AgentRunMcpChannel`） | 否 | 确定性 `sandboxId`（SHA-256→Crockford32）；**NAS/OSS 挂载下无操作持久化**，否则 tar|base64 over MCP |

四个扩展后端**均无自带 `SandboxExecutionGuard`**，并发串行化依赖 store 级护栏（见下节）。

### Docker (Built-in)

注释明确「`Uses the docker CLI via ProcessBuilder; no docker-java library dependency is required`」（`DockerSandbox.java:49`）。`doExec`（`:150-158`）拼 `docker exec -w <root> <cid> sh -c <command>` 经 `ProcessBuilder` 启动，超时 `process.destroyForcibly()`；打包/解包走 `docker exec tar`（`:207-218` / `262-280`）；单文件走 `docker cp`（`:386-428`）。容器用 `docker run -d --name agentscope-sandbox-<sessionId> ... sh -c "trap 'exit 0' TERM; while :; do sleep 3600 & wait $!; done"` 常驻（`:519-583`）。默认 `image=ubuntu:22.04`、`workspaceRoot=/workspace`；resume 时若容器仍在则直连，已停则重启，**无 warmPool 概念**。

### Kubernetes

`KubernetesSandboxClient.create`（`KubernetesSandboxClient.java:122-128`）走 `sdkClient.createSandbox(CreateSandboxOptions.builder(warmPoolName).namespace(...).claimName(...))`——即 **warmPool + SandboxClaim**（CRD `SandboxClaim` / `SandboxClaimSpec` / `SandboxClaimStatus`）。隧道三选一（`toConnectionConfig`，`:224-245`）：`apiUrl`→Direct、`gatewayName`→Gateway、否则 `LocalTunnelConnectionConfig`（port-forward）。`doExec`（`KubernetesSandbox.java:97-98`）走 `sdkSandbox.commands().run(...)`；归档 `fileApiEnabled()` 时走运行时文件 API，否则 `tar|base64` 经 exec（`:112-167`）。`shutdown`（`:65-86`）仅 `claimOwned` 时 `terminate()`，否则只关连接。

### E2B

`E2bSandbox extends AbstractBaseSandbox`（**未实现 `SandboxFileTransfer`**），exec 走 envd protobuf（`E2bSandbox.java:128`），生命周期/快照走 Platform HTTP（`E2bPlatformHttp.java:38-39`）。`doPersistWorkspace`（`:132-155`）两种模式：`NATIVE_SNAPSHOT`（`platform.createSandboxSnapshot` 返回 `snapshotID` 标记进归档流）或 `TAR`（envd 流式 tar）；`doHydrateWorkspace`（`:158-188`）命中 snapshot id 则 `createSandbox(snapshotTemplateId)` 重建，否则 base64→tar 经 envd。`shutdown`（`:112-123`）`killSandbox` + 按 `snapshotRetention` 清理。默认 `workspaceRoot=/home/user`、`persistenceMode=TAR`。

### Daytona

`DaytonaSandbox extends AbstractBaseSandbox`（`:33`），全部经 `DaytonaHttp`（OkHttp）。`doExec`（`:73-92`）`http.execute(sandboxId, command, cwd, timeout)` 解析 JSON `exitCode/result`（truncate 512KB）；打包 `tar|base64` 经 `http.execute`、解包分块 base64→`python3`→`tar xf`（`:95-155`）。默认 `workspaceRoot=/home/daytona/workspace`、`image=ubuntu:22.04`。

### AgentRun

`AgentRunSandbox extends AbstractBaseSandbox`（`:39`），持 `AgentRunDataPlaneHttp`（控制面）+ `AgentRunMcpChannel`（执行面，经模板内嵌的 AgentRun MCP server 跑命令/传归档）。`doExec`（`:120`）走 `mcp.exec`；`workspaceOnNas=true` 时 `doPersistWorkspace` 直接返回空流（交给 NAS/OSS 挂载，`:135-151`）。`ensureSandbox`（`:213-233`）用**确定性** `sandboxId`（`deriveSandboxId` 由 `SHA-256(sessionId)`→Crockford Base32 取 26 字符，`AgentRunSandboxClient.java:243-271`），故同 session resume = 重建同 id 沙箱。默认 `workspaceRoot=/home/agentscope/workspace`。

## Execution Guard

### SPI And Lifecycle

`SandboxExecutionGuard`（`.../sandbox/SandboxExecutionGuard.java:59-93`）是 `@FunctionalInterface`：`SandboxLease tryEnter(SandboxIsolationKey key)` + `static noop()`。用途是给 `USER` / `AGENT` / `GLOBAL` 这种多并发调用者就同一持久化 slot 串行化——否则 `SandboxManager` 的"最后写入快照胜出"会让并发调用互相覆盖。`SandboxLease`（`SandboxLease.java:27-55`）是 `AutoCloseable`，实现须幂等。默认 `noop()` 不限制。

### Six Distributed Implementations

| 实现 | 模块 | 互斥原语 | 阻塞 | 超时/自动释放 | `Lease.close` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Redis | redis | `SET NX PX` + Lua CAS（token=UUID） | 轮询 500ms | TTL 30min 安全阀，无获取超时 | Lua `get==token then del` |
| JDBC | jdbc | 委托 `SandboxLockStrategy`；默认表级 `INSERT` 唯一键冲突 | 指数退避 50→1000ms | `lockTimeout` 1800s | `DELETE WHERE lock_name` |
| MySQL | mysql | `GET_LOCK(name,timeout)` 服务端命名锁 | 服务端阻塞 | 1800s；**连接关即释放** | `RELEASE_LOCK` + conn.close |
| PostgreSQL | postgresql | `pg_try_advisory_lock`（64-bit key） | 轮询 100ms | 1800s；**连接关即释放** | `pg_advisory_unlock` + conn.close |
| MongoDB | mongodb | 唯一 `_id` 文档 + TTL 索引 + 看门狗续租 | 轮询 500ms | `leaseTtl` 30min + TTL 监控删 | `deleteOne(_id AND token)` |
| Aistio | aistio | 控制面 `POST /locks/acquire`（holder=UUID, ttl=60s） | 轮询 500ms | ttl 60s + 续租 20s；不可达 30s 降级 `ReentrantLock` | `POST /locks/release` |

细节要点（均源码核对）：

- **Redis**（`RedisSandboxExecutionGuard.java:139-159`）：`SET NX PX` 轮询拿锁，释放是 Lua 脚本 CAS（`if get==ARGV[1] then del`），只删自己 token 的锁；键 `<prefix><scope>:<value>`，默认前缀 `agentscope:sandbox:lock:`。
- **JDBC**（`JdbcSandboxExecutionGuard.java:68-72`）：零 DB 逻辑，委托方言 `SandboxLockStrategy`；默认表级锁 `INSERT INTO <prefix>distributed_locks (lock_name) VALUES (?)`，唯一主键冲突（SQLState 23xx / SQLite 19）即重试（`AbstractJdbcDialect.java:257-294`）。
- **MySQL**（`MysqlDialect` 用 `GET_LOCK`）：锁**绑定连接**，连接关闭即自动释放（`JdbcSandboxExecutionGuard.java:70-140`）。
- **PostgreSQL**（`PostgresDialect` 用 `pg_try_advisory_lock`）：key 由 `MurmurHash3.hash128(raw)` 取 `hash[0]`（`:129-133`）。
- **MongoDB**（`MongoSandboxExecutionGuard.java:133-216`）：`insertOne` 原子获取（重复键 11000 则 reclaim 过期锁），TTL 索引 `expireAfter(0)` 自动删，看门狗每 `leaseTtl/3` 续租，`close` 用 `deleteOne(_id AND token)` 防误删他人锁。
- **Aistio**（`ControlPlaneSandboxExecutionGuard.java:75-147`）：控制面不可达持续 >30s 降级为进程内 `ReentrantLock`（仅单 JVM 有效，跨进程失效，仅兜底）。

> 注意：各 guard 中**没有 `SELECT FOR UPDATE` 式显式行锁**——JDBC 默认走唯一键 INSERT 冲突，MySQL/PG 走原生 advisory lock，已据实区分。

## Links

- [工作区](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md)
- [执行内核](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Execution.md)
- [技能](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)
- [智能体](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [会话](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [AgentScope Java 枢纽](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)

## References

- [AgentScope Java 沙箱](https://java.agentscope.io/v2/zh/docs/harness/sandbox)
