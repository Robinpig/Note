## Introduction

OpenClaw 把「可选能力」一律下沉到插件，理由是 core 里每多一个 tool / prompt / config key 都会对每次模型请求「按调用征税」。这一页覆盖插件的两平面结构、注册契约、激活规划、生命周期事务链，以及 Claw 包分发，是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md) 枢纽里「精简 core + 插件化」那条设计哲学的落地细节；插件贡献的工具如何被调用见 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)。

## Plugin System

插件系统是整个架构的扩展基座，核心是 **control-plane / runtime-plane 分离**：

- **control-plane**：discovery → manifest 解析 → config 校验 → activation 规划，只消费元数据，**不加载 plugin runtime**。
- **runtime-plane**：真正 `import()` 插件模块、执行 `register(api)`、把能力贡献进 `PluginRegistry`。
- 插件通过 `openclaw/plugin-sdk/*` 的窄版本化 subpath 接入，**不得反向 import host 内部**（`src/channels`、`src/agents`、`src/plugins` 等）。

公开契约是 `definePluginEntry({ id, name, description, configSchema?, register })`，`register` 是插件唯一 hook 入口。manifest（固定名 `openclaw.plugin.json`）有硬约束：`id` 与 `configSchema` 缺失即失败、`id` 不能与 core 保留 id 冲突、文件 ≤ 256KB、路径经 `rejectHardlinks` 禁止硬链逃逸插件根。

激活有两个独立 planner：

| Planner | 时机 | 行为 |
| :--- | :--- | :--- |
| 启动期 `canStartGatewayStartupPlugin` | Gateway 启动 | 按固定优先级序（harness → root → worker → speech → provider → hook → tool…）判定谁随启动加载 runtime |
| 请求期 `resolveManifestActivationPlan` | 运行期 | **完全不 import runtime**，按 trigger（command / provider / channel / route / capability）选出拥有该 surface 的插件，按需加载 |

即 provider / channel / tool 插件只在配置真正引用它时才加载，而非启动期全量加载。加载还有 signature 缓存（输入指纹命中则复用 predecessor 贡献，不重复 register）与多种注册模式（cli-metadata / setup-only / setup-runtime / tool-discovery / full / discovery）。

信任边界同样精细：untrusted 本地插件的 setup-only channel 导入被拦截；degraded 插件在 artifact 解析之前就隔离（「no top-level plugin code can execute this boot」）；memory 同刻仅一个插件生效（`plugins.slots.memory`）；不在 allow 白名单的插件告警。

插件的完整生命周期是一条事务链：**install 先持久化索引（durability 先于 activation）→ reload 走 prepare → drain → activate/publish → dispose 四个 phase，每次成功推进一代「Gateway generation」→ uninstall 先写 disable 热生效、drain 旧代际，再删目录与记录**。批量安装用一整个 lifecycle lease 串起，cleanup 可延迟到 lease 退出之后。

几处容易含混的精确化：

- **权威清单不是专表**：插件安装记录落在共享 state DB 的 `config_machine_state` 表下 `state_key='plugins.installedIndex'` 的**一行 JSON**里（legacy 瞬态副本在 `config.plugins.installs`），没有 `plugin_install_records` 表。
- **「Gateway generation」涉及三枚独立计数器**：运行时 registry 代际号 `activeVersion`（receipt 与广播使用）、hot-reload fence `nextGatewayReloadGeneration`、索引写跨进程回滚 fence `revision`（`Math.max(Date.now(), current+1)` 使同毫秒跨进程写可辨）；`reserve()` 铸的是 identity/claim **对象**而非数值。
- **安装分四种事务形态**：CLI/离线 install 只持久化、**刻意不动运行中 graph**（无代际变更）；Gateway install 先持久再热加载（+1 代际）；Claw 批安装用一整个 lease 串起、整批一次 reload（≤64 targets，重验 hash/digest）；uninstall 先热写 disable 再 drain 旧代际，删记录后再发布一次（**一次用户命令可推进两代际**）。
- 插件实例拿到的 `api` 句柄是 **Proxy**：每次访问都同步复校当前 registry 代际，epoch 轮换即抛「runtime no longer active」——句柄稳定，但每次重绑的是「当前」registry。

## Plugin State Persistence

`src/plugin-state/` 是插件与可信 core 的**持久化底座**，与前面讲的「加载插件代码」相对——这里落的是插件**数据**。全部落在共享 state SQLite，写经**专用 prepared SQLite worker actor** 做同步事务（呼应根 `AGENTS.md`「写事务同步、无 await」），读走 prepared-statement 缓存。

表只有两张：`plugin_state_entries(plugin_id, namespace, entry_key, value_json, created_at, expires_at)` STRICT + `plugin_blob_entries(...metadata_json, blob BLOB...)`。有个容易误判的点：**「journal」不是独立表**，而是 `plugin_state_entries` 上的序列 append 约定——cursor 行 + 零填充序列键（`<prefix><seq 16>`），一次事务内原子读 cursor、`sequence = max+1`、写 cursor upsert 与数据行。

core 与插件的边界就压在 `core:` 前缀上：`createCorePluginStateKeyedStore` 限 ownerId 为 `core:${string}`，而 `createPluginStateKeyedStore(pluginId)` **拒绝保留 `core:` 前缀**，公开 journal append 同样拒。值上限 1 MiB；blob 是独立同步径，单 entry 100 MiB、per-plugin 512 MiB、50k 条上限。并发靠 CAS：`comparison="1:<scope>:<image>"`（scope/image 是 DB-identity + 存储值 sha256），仅仍匹配才应用，否则返回 `{status:"conflict", current}`。

消费方里最值得一提的是 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的记忆事件流——它就是用 `registerPluginStateSequencedJournalEntry` 落的（namespace `memory-host.events`、cursor `memory-host.event-cursors`），provenance 则用 core 前缀 store。另有一条 API 演进提示：`createPluginStateSyncKeyedStore` 与 async store 的 `update` / `deleteIf` 回调成员**已 `@deprecated`**（阻塞主线程），前向契约是 data-only ops + `deleteIfEqual` + `compareAndApply`。

## Hooks

`src/hooks/` 是**事件驱动钩子框架**——注意它是「本地可信代码扩展点」，与插件系统平行但更轻：每个 hook 就是一个目录，含 `HOOK.md`（frontmatter 声明 `events` / `export` / `requires` / `os` / `install`）加一个 handler 文件。

四种来源有明确优先级（`HOOK_SOURCE_PRECEDENCE`）：`bundled(10) < plugin(20) < managed(30) < workspace(40)`，高优先级覆盖同名钩子，但 bundled / plugin 保留首个。**workspace 钩子默认禁用**，必须显式 `enabled: true`——防工作区代码静默执行；插件钩子默认启用。

加载有两道讲究：一是**边界检查**，handler 路径必须落在 hook root 内（`isPathInsideWithRealpath`），越界即拒，防逃逸执行；二是**原子加载**，整代 generation 同步 reset + register（globalThis singleton），保证事件看到的是「完整一代」而非半完成状态，`initial` 守卫防 deferred 启动覆盖 reload。

派发容错：同时调用 `type` 与 `type:action` 两组 handler，按注册序执行，**单个 handler 抛错只 catch + log，不阻断其余**。事件类型包括 `command:new`、`session:patch`、`gateway:startup`、`agent:bootstrap`、`message:received/sent/enriched/transcribed/preprocessed`，未知 core event 会告警提示 typo。

## Claws: Package Lifecycle

**Claw** 是「一个 agent 的版本化 setup」（experimental 面），补上「插件包从哪来」的半段：plan → consent → apply。

- **Plan**：产出 typed actions（agent / workspaceFile / package / mcpServer / cronJob / bootstrap）与 `planIntegrity = sha256(plan)`；agent-id 冲突是硬 blocker——**Claws never merge into existing agents**。
- **Consent**：apply 必须传 `--yes --plan-integrity <hash>` 且 hash 与当前 plan 一致，**consent 是唯一授权通道**。
- **安装**：每个成员包都要 `clawhub` 源 + version + sha256 pin；插件在 temp extensions dir 做隔离 dry-run probe，校验身份与摘要一致后才落盘；每个包一条 `state_leases` 生命周期租约防并发变更。
- **更新与回滚**：计划阶段全只读，diff 出 add / change / remove / release 动作与 capability 升级；workspace / MCP / cron / package 每 phase 都返回独立 `{ rollback }`，失败时按 cron → workspace → MCP → package → agent-config 反向级联；降级为「部分完成 + 交给 doctor 收敛」而非硬失败。
- **来源证明**：`claw_installs` + `claw_package_refs` 双表**叠加**在 installRecords 上（不替代），记录源路径、sha256、字节数、plan hash 与状态机。
- **工具面冻结**：plan 期把 Claw 携带的 tool profile 冻结成有界 allowlist（拒绝 unbounded `full`），执行期对 legacy / 不匹配 **fail-closed 阻止 agent run**，要求重新授权。
- **ClawHub 注册表**：架构文档基线时点，整-Claw 的 ClawHub 安装尚未上线（`docs/cli/claws.md`），安装源限本地目录；但注册表本身早已上线（clawhub.ai，`openclaw/clawhub` 仓库，托管 skills / code plugins / bundle plugins，并已 expose experimental whole-agent Claw packages 目录）。v2026.3.22 起 `openclaw plugins install` 对 npm-safe 名字**默认先解析 ClawHub 再回退 npm**（breaking change；`clawhub:` 前缀显式走注册表，`npm:` 强制走 npm）；skill 侧 `openclaw skills install` 装进活跃 workspace，`--global` 为全部本地 agent 共享。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md)
- [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [ClawHub 官方文档](https://docs.openclaw.ai/clawhub)
- [openclaw/clawhub 仓库](https://github.com/openclaw/clawhub)
