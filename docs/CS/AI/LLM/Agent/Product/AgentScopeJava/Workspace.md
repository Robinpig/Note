# Workspace

## Introduction

Workspace 解决的是 Agent 与「文件世界」的关系问题：模型只能看见上下文里的文本，但真实任务几乎都要读写文件。AgentScope Java 把这件事拆成三个正交的关注点——**工作区目录**（文件放在哪、谁能改）、**文件系统访问模式**（Agent 以什么身份看这些文件）、**沙箱后端**（这些文件实际落在哪种隔离环境里）。

官方文档对它的定位一句话概括：**工作区是 HarnessAgent 智能体定义与进化的 source of truth**——「智能体是什么」以及「它在运行中学到了什么」全部以一个目录 + 普通 Markdown / JSON 文件组织，不散落在代码里，不绑死在某个数据库表上。

Python 版把这三件事揉在工具层各自实现，Java 版则提升为一等模块：同一套 Agent 代码，通过替换 Workspace 配置就能从「本地开发直接读写」切换到「共享 KV 多副本」再到「容器内隔离执行」。

本分册事实来自本地 `v2.0.4` 源码树（`agentscope-harness/.../workspace/`、`.../filesystem/`、`.../sandbox/`）与官方文档站 v2 工作区 / 文件系统页，冲突处以源码为准。

## Directory Layout

```text
.agentscope/workspace/
├── AGENTS.md                    ← 静态：人格 + 行为约定
├── MEMORY.md                    ← 长期记忆：策划后的长期事实
├── tools.json                   ← 静态：MCP server + 工具白名单（可选）
├── memory/                      ← 长期记忆：每天追加的事实流水账
│   └── YYYY-MM-DD.md
├── knowledge/                   ← 静态：领域知识入口 + 任意参考文件
│   ├── KNOWLEDGE.md
│   └── ...
├── skills/                      ← 静态：技能目录，每个子目录一份 SKILL.md
│   └── <skill-name>/SKILL.md
├── subagents/                   ← 静态：子 agent 声明（文件名即 agent_id）
│   └── <agent-id>.md
├── plans/                       ← 运行时：Plan Mode 写下的计划文件
│   └── PLAN.md
└── agents/<agentId>/            ← 运行时：每个 agent 自己的运行时根
    └── tasks/                   ← 运行时：子 agent 后台任务记录
        └── <sessionId>.json
```

⚠️ **这是逻辑布局，不是固定磁盘路径**。画成 `.agentscope/workspace/...` 只是默认本机落点；同一份布局可以物理上落在本机磁盘、远端分布式存储（Redis / JDBC / OSS，经 `RemoteFilesystemSpec`）、或映射进沙箱容器（`SandboxFilesystemSpec`）——相对路径在三种模式下完全一致，变的只是后端存储。

内容按生命周期分三类，框架内部走不同的读写路径（混在一棵树里只是为了部署方便——一个目录拷走就是完整 agent）：

| 类型 | 谁写 | 谁读 | 例子 |
| :--- | :--- | :--- | :--- |
| 静态资产（工程师编辑） | 你 / 团队 | 框架按指令/参考资料分层加载，或按需读取 | `AGENTS.md`、`knowledge/`、`skills/`、`subagents/`、`tools.json` |
| 运行时文件（每次 call 写回） | 框架 / agent | 框架下次 call 时还原 | `agents/<agentId>/sessions/`、`agents/<agentId>/tasks/`、`plans/` |
| 长期记忆（跨会话累积） | agent + 后台任务 | 每次 call 加载为参考上下文 + agent 用工具查询 | `MEMORY.md`、`memory/YYYY-MM-DD.md` |

**区分文件产物和恢复状态**：计划、技能、记忆是 Workspace 文件；`AgentState` 是结构化运行状态，默认 EVENT_LOG 模式把 checkpoint 放进原生 Session Log，LEGACY 才以独立 `AgentStateStore` 为恢复来源。

## Builder And Resolution

```java
HarnessAgent agent = HarnessAgent.builder()
    .name("MyAgent")
    .model(model)
    .workspace(Paths.get(".agentscope/workspace"))   // 不传则走下面的解析顺序
    .additionalContextFile("SOUL.md")                // 任意 workspace 相对路径，全文注入
    .additionalContextFile("PREFERENCES.md")
    .maxContextTokens(8000)                          // MEMORY 注入预算
    .build();
```

`workspace(...)` 不显式调用时，`build()` 按以下优先级确定目录（从高到低）：

| 优先级 | 来源 |
| :--- | :--- |
| 1 | `workspace(Path)` / `workspace(String)` builder 显式设置，覆盖一切 |
| 2 | 系统属性 `-Dagentscope.workspace=/data/workspace` |
| 3 | 环境变量 `AGENTSCOPE_WORKSPACE=/data/workspace` |
| 4 | 默认值 `${user.dir}/.agentscope/workspace` |

空白值（如 `"   "`）视为未设置，继续往下一级回退。系统属性与环境变量主要服务镜像打包 / 容器部署。

可关掉的子系统（生产很少用，调试或自管时有用）：

| 方法 | 关掉的是 |
| :--- | :--- |
| `disableWorkspaceContext()` | 工作区指令和参考材料加载（AGENTS.md / MEMORY.md / knowledge/） |
| `disableMemoryHooks()` | 记忆 flush + 后台维护 |
| `disableMemoryTools()` | `memory_search` / `memory_get` / `memory_save` / `session_search` 工具 |
| `disableSubagents()` | 整个子 agent 子系统 |
| `disableDynamicSkills()` | 每次 call 重新合并技能 → 改成 build 时一次 |
| `disableToolsConfig()` | 不读 `tools.json` |
| `disableSessionPersistence()` | 兼容 no-op；**不能用它关闭原生 Session Log** |

## Two-Layer Read

对所有「被注入到 prompt 的关键文件」（`AGENTS.md` / `MEMORY.md` / `knowledge/KNOWLEDGE.md` / `additionalContextFile`），`WorkspaceManager.readWithOverride()` 走两层读：

```text
1. 问当前配置的 AbstractFilesystem：有没有这个 relative path？
   ├─ 有 → 返回该内容（"覆盖"层）
   └─ 没有 → 走第 2 步
2. 读本地磁盘 workspace.resolve(relativePath)
```

**写入永远走第 1 层（filesystem 后端），从不直接落到本地磁盘。**

这套机制的价值在共享存储模式最明显：第一个副本启动时本地磁盘上有团队 git 同步过来的 `AGENTS.md` 模板，立刻可用；之后任何节点对 `AGENTS.md` 的覆盖（例如管理台编辑）写到共享 KV，所有副本下一次 `call()` 就读到最新版本——**模板是 fallback，远端覆盖是事实**。

## Three Filesystem Modes

同一份目录布局落在三种地方，这是 HarnessAgent「代码不动、部署形态切换」的根因。在 `HarnessAgent.Builder` 上用 `filesystem(...)` **三选一**（不调就是默认模式 3）；`filesystem(...)` 与 `abstractFilesystem(...)` 互斥，后者是完全自管的逃生口。

### Mode 1 · Shared Store (`RemoteFilesystemSpec`)

多副本共享 MEMORY.md / 对话日志 / 子任务到 KV，**不提供 shell**（故意的：要 shell 用模式 2 或 3）。

```java
HarnessAgent agent = HarnessAgent.builder()
    .name("store-agent")
    .model(model)
    .workspace(workspace)
    .distributedStore(store)                       // stateStore + baseStore 一键配置
    .filesystem(new RemoteFilesystemSpec()
        .isolationScope(IsolationScope.USER)       // 按 userId 分命名空间
        .anonymousUserId("anonymous"))             // userId 为空时的兜底标识，默认 "_default"
    .build();
```

配置项：`isolationScope`（默认 USER）、`anonymousUserId`、`addSharedPrefix(String)`（额外路由到 KV 的工作区相对路径前缀，如 `"prompts/"`）、`workspaceIndex(WorkspaceIndex)`（加速远端 ls/glob/grep 的 SQLite 索引，默认不加索引走全量扫描）。

**内置路由规则**——以下路径自动进 KV，每个路径段各自独立命名空间：

| 路径 | KV 命名空间段 |
| :--- | :--- |
| `AGENTS.md`、`MEMORY.md`、`tools.json` | root |
| `memory/` | memory |
| `skills/` | skills |
| `subagents/` | subagents |
| `knowledge/` | knowledge |
| `agents/<agentId>/sessions/` | sessions |
| `agents/<agentId>/tasks/` | tasks |

其余不在表内的路径落到本地 `LocalFilesystem`（无 shell）。`BaseStore` 三个内置实现：`RedisStore`（Jedis，低延迟高并发）、`JdbcStore`（MySQL / PostgreSQL / H2 / SQLite）、`InMemoryStore`（测试）。

### Mode 2 · Sandbox (The SandboxFilesystemSpec Family)

隔离执行、跨调用恢复同一份工作区、可选快照 + 分布式。五个后端：

| Spec | 关键配置 |
| :--- | :--- |
| `DockerFilesystemSpec` | `image`（必填）、`memorySizeBytes`、`cpuCount`、`network`、`exposedPorts`、`environment`、`workspaceRoot`（默认 `/workspace`）、`additionalRunArgs`、`snapshotSpec`、`workspaceSpec`、`executionGuard` |
| `KubernetesFilesystemSpec` | `namespace`（default）、`warmPoolName`（必填，SandboxWarmPool 名）、`workspaceRoot`（须落在模板声明的 PVC 挂载点）、`fileApiBaseDir`、`apiUrl` / `gatewayName` / `gatewayNamespace` / `gatewayScheme`、`serverPort`（8888）、`kubernetesClient` |
| `E2bFilesystemSpec` | `apiKey`、`templateId`、`sandboxTimeoutSeconds`；自建兼容后端可设 `envdSandboxUrl`（数据面按 `E2b-Sandbox-Id` / `E2b-Sandbox-Port` 路由，免泛域名 DNS） |
| `DaytonaFilesystemSpec` | `apiKey`、`controlPlaneBaseUrl`、`image`、`cpu`、`memory`（GiB）、`disk`（GiB） |
| `AgentRunFilesystemSpec` | `apiKey`、`accountId`、`region`、`templateName`、`sandboxIdleTimeoutSeconds` |

公共配置（继承 `SandboxFilesystemSpec`）：`isolationScope`（默认 USER）、`snapshotSpec`（默认 `NoopSnapshotSpec`）、`executionGuard`、`workspaceProjectionEnabled`（默认 true）、`workspaceProjectionRoots`（默认 `AGENTS.md, skills, subagents, knowledge, .skills-cache`）。

K8s 后端完全基于 **agent-sandbox**：沙箱 pod 由集群里的 agent-sandbox 控制器管理，镜像、资源、PVC 都声明在集群侧的 `SandboxTemplate` / `SandboxWarmPool` 里（**不在 Java 侧配置**），Java 侧通过 `SandboxClaim` 从预热池领实例。`apiUrl` / `gateway*` 都不配时默认用 `kubectl port-forward` 建本地隧道（适合开发环境）；运行时镜像必须满足运行时镜像约束，工作区持久化依赖模板里的 PVC 配置。

**快照策略**五种：`NoopSnapshotSpec`（默认，不快照）、`LocalSnapshotSpec(Path)`、`RedisSnapshotSpec`、`OssSnapshotSpec`（阿里云 OSS）、`RemoteSnapshotSpec`（BaseStore）。

⚠️ **沙箱模式下 IsolationScope 是顺序复用的共享，不是实时实例共享**：同一 scope key 的并发调用各自启动独立容器，每次调用结束时**最后写入的快照胜出**。AGENT / GLOBAL 这种多用户共享 scope 需要串行化时，用 `executionGuard(SandboxExecutionGuard)`。

**工作区投影（Workspace Projection）**：沙箱启动时框架把宿主工作区的静态资产打成 tar、hydrate 进容器 `/workspace`。投影对所有被包含的文件按内容算整体 SHA-256，与上次一样就跳过 hydrate——反复 `call()` 不会重复传相同文件，只有内容变了才重新注入。

### Mode 3 · Local + Shell (default)

工作区落到 `${cwd}/.agentscope/workspace/`，shell 在宿主上跑（`execute` 是宿主 `sh -c`）。**生产不要直接用这个模式跑不可信代码。**

```java
.filesystem(new LocalFilesystemSpec()
    .executeTimeoutSeconds(120)       // 单条 shell 命令超时（秒）
    .maxOutputBytes(100_000)          // 单条命令最大捕获输出字节数
    .env("MY_VAR", "value")           // 额外环境变量
    .inheritEnv(true)                 // 是否继承父进程环境，默认 false
    .mode(LocalFsMode.ROOTED)         // 路径解析策略
    .project(Paths.get("/my/project"))// 项目根（shell 的 cwd + overlay 下层）
    .addRoot(Paths.get("/extra/dir")) // 额外可访问目录
    .projectWritable(true))           // 文件工具写项目文件直接落项目目录，默认 false
```

**`LocalFsMode` 三值**（路径解析策略）：

| 模式 | 行为 |
| :--- | :--- |
| `ROOTED`（默认） | 绝对路径只允许 workspace + project + additionalRoots 范围内；`..` 穿越被拒绝 |
| `SANDBOXED` | 所有路径强制锚定到 workspace 根，绝对路径和 `..` 全部拒绝 |
| `UNRESTRICTED` | 绝对路径原样透传，不做限制。仅用于测试或完全信任的环境 |

**Overlay 文件系统**——本机模式实际产出的是 `OverlayFilesystem`：

- 上层（读写）：`LocalFilesystemWithShell`，根在 workspace，提供 shell；
- 下层（只读）：`LocalFilesystem`，根在 project。

读取时先看 workspace，没有再退到 project（copy-on-write 语义）；shell 的 pwd 是 project 目录，所以 agent 执行 `ls` 看到的是项目文件。

**项目可写模式（`projectWritable(true)`）**：默认所有写入都落 workspace——阅读/分析类场景够用，但核心任务是生成代码时文件会全写到 `.agentscope/workspace/` 而不是项目目录。开启后按路径路由：

| 路径类型 | 写入位置 | 示例 |
| :--- | :--- | :--- |
| 工作区元数据 | workspace | `MEMORY.md`、`memory/`、`agents/`、`skills/`、`knowledge/`、`plans/`、`subagents/`、`rules/`、`tools.json` |
| 其他所有文件 | 项目目录 | `src/main/java/App.java`、`pom.xml`、`README.md`、`docker-compose.yml` |

读取行为不变——仍 是 workspace 优先、project 兜底。

## IsolationScope

模式 1 与模式 2 共用同一个 `IsolationScope`，决定谁和谁共享同一份状态：

| Scope | 含义 | 命名空间键 | 典型场景 |
| :--- | :--- | :--- | :--- |
| `SESSION` | 每个 sessionId 独立 | `agents/<agentId>/sessions/<sessionId>/...` | 多用户 SaaS，每段对话完全隔离 |
| `USER`（默认） | 同一 userId 跨会话共享 | `agents/<agentId>/users/<userId>/...` | 同一用户的多个会话共享长期记忆 |
| `AGENT` | 该 agent 的所有用户/会话共享 | `agents/<agentId>/shared/...` | 公共知识库型 agent |
| `GLOBAL` | 全局共享一份 | `global/...` | 谨慎使用 |

**降级规则**：

- `USER` scope 下 `RuntimeContext.userId` 为空 → 降级为 `SESSION`（按 sessionId 隔离）；
- `SESSION` scope 下 `sessionId` 为空 → 跳过状态查找，创建全新环境；
- `AGENT` scope 的命名空间键由 agent name（build 时固定）决定，不因缺少上下文字段而降级。

IsolationScope 决定 Filesystem 分桶；**原生日志在桶内继续以 `(userId, stableAgentId, sessionId)` 隔离**，旧 `AgentStateStore` 以 `(userId, sessionId)` 寻址。改变 scope 或日志后端前应迁移数据。

### Static Assets vs Runtime Data

| | 行为 |
| :--- | :--- |
| 运行时数据（对话日志、tasks、memory） | 跟着 IsolationScope / userId 走，自动隔离 |
| 静态资产（`AGENTS.md`、`tools.json`、`knowledge/`） | **对所有用户共享，不按 userId 自动分区**；差异化只能通过「用户覆盖目录」 |

用户覆盖目录（下层独有仍保留，重名时被上层挡住）：

```text
workspace/
├── skills/code-reviewer/SKILL.md     ← 共用版（所有人可见）
└── alice/
    ├── skills/code-reviewer/SKILL.md ← 只对 alice 生效，覆盖共用版
    └── subagents/researcher.md
```

userId 的物理表现按模式分：本机 = 路径前缀 `workspace/alice/...`；共享存储 = KV 键前缀 `agents/<agentId>/users/alice/...`；沙箱 = 快照 slot key。**不传 userId 走单租户默认，所有人共享一个根。**

## Material Loading And Budget

工作区材料每次 call 读取一次，再由最终 Context 构建器分层组织：

| 材料 | 模型中的位置 | 预算行为 |
| :--- | :--- | :--- |
| `AGENTS.md` | System / `project_rules` | 不直接淘汰，计入最终预算 |
| 工作原则、环境信息 | System / `working_principles`、`environment` | 计入最终预算 |
| `MEMORY.md` | USER 参考消息 / `HARNESS_CONTEXT`，`kind=memory` | 准备时可截断，最终预算不足时可省略 |
| knowledge 入口及路径索引 | USER / `HARNESS_CONTEXT`，`kind=knowledge` | 可因最终预算省略 |
| `additionalContextFile` | USER / `HARNESS_CONTEXT`，`kind=additional` | 必需材料，不能任意淘汰 |

`maxContextTokens` 默认 **8000**，只用于工作区材料准备，不代表最终模型输入上限；最终预算还包括 System、历史、状态和工具 Schema，仍超限则拒绝请求。

`knowledge/` 只把 `KNOWLEDGE.md` 全文进 `<domain_knowledge_context>`，同目录其它文件（任意深度）只列路径清单进 prompt，让 agent 用 `read_file` / `grep_files` / `glob_files` 按需读取——「目录里全是细节，prompt 里只放索引」，避免把整个知识库塞进 token 预算。

## tools.json

工作区根下的 JSON，框架在 `build()` 时一次性读完（走 `WorkspaceManager`，支持两层读）：

```json
{
  "allow": ["read_file", "grep_files", "execute"],
  "deny":  ["write_file"],
  "mcpServers": {
    "amap":    { "transport": "streamableHttp", "url": "https://mcp.amap.com/mcp?key=${AMAP_API_KEY}" },
    "local-py":{ "transport": "stdio", "command": "python", "args": ["mcp_servers/my_server.py"],
                 "env": {"PYTHONUNBUFFERED": "1"} }
  }
}
```

行为细节：

- MCP server 在构建期一次性注册到 toolkit，agent 看到的就是这些 server 暴露的工具；
- **allow / deny 在所有工具注册完之后才应用**——所以也会过滤掉 Harness 的内置工具（`read_file` / `memory_search` / `agent_spawn` 等）；用 allow 列白名单时**务必把要保留的内置工具一并列出**，否则会一起被砍掉；
- `${ENV_VAR}` 语法做环境变量替换，未设置时给 warning 并替换成空字符串；
- 不想用文件就 `builder.toolsConfig(ToolsConfig.builder()...)` 编程注入；完全关掉读取用 `disableToolsConfig()`；
- 共享存储模式下 `tools.json` 也走「远端为上层、本地模板为下层」的 overlay——管理台改完后**需要重新 build agent 才能生效**（MCP 注册是一次性的）。

## Write Safety

`additionalContextFile`、`writeUtf8WorkspaceRelative`、`memory_get` 这些接口接受工作区相对路径，框架做基本的 path-traversal 校验（拒绝 `../../etc/passwd` 这种逃出工作区的写法）。

**需要写文件时通过 `HarnessAgent#getWorkspaceManager()` 而不是 `java.nio.Files`**——后者在沙箱或共享存储模式下会写到错的地方（写到宿主磁盘而不是沙箱里 / KV 里）。唯一例外：builder 装配时的初始化脚本（如 `initWorkspaceIfAbsent` 生成 `AGENTS.md` 种子），那时还没有运行时上下文，用 `java.nio.Files` 是对的——它本来就是要落本地模板。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)
- [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [AgentScope Java 工作区](https://java.agentscope.io/v2/zh/docs/harness/workspace)
- [AgentScope Java 文件系统](https://java.agentscope.io/v2/zh/docs/harness/filesystem)
- [AgentScope Java 沙箱](https://java.agentscope.io/v2/zh/docs/harness/sandbox)
