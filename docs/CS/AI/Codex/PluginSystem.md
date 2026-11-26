## Introduction

Codex 的「插件」其实分两层正交的机制，理解它先要区分二者：

1. **代码插件（Codex Plugin，包级）** —— 由 `core-plugins` crate 管理的、从 marketplace 安装的**包**，对外暴露四类能力：**skills（技能）、MCP servers（工具）、hooks（钩子）、apps（连接器）**。这是普通用户 `codex plugin install` 装的东西，也是把第三方能力注入模型上下文的主通道。
2. **UI 插件宿主（plugin-host）** —— 一个用 V8 隔离环境跑**前端 JS 脚本**的专用子进程（`--codex-ui-plugin-process`），负责桌面 App 的自定义 UI 扩展。它与包级插件是两套独立 ABI，只是共用 "plugin" 这个名字。

本篇先讲包级插件的完整生命周期，再单独讲 UI 插件宿主的进程与线协议。

## 包级插件：数据模型

插件的核心是一份声明式清单 `PluginManifest<Resource>`。它用泛型 `Resource` 把「资源位置」参数化：在宿主本地加载时用绝对路径，解析成权威绑定（authority-bound）位置后再暴露给消费者。

```rust
pub struct PluginManifest<Resource> {
    pub name: String,
    pub version: Option<String>,
    pub description: Option<String>,
    pub keywords: Vec<String>,
    pub paths: PluginManifestPaths<Resource>,
    pub interface: Option<PluginManifestInterface<Resource>>,
}

pub struct PluginManifestPaths<Resource> {
    pub skills: Vec<Resource>,
    pub onboarding_skill: Option<Resource>,
    pub mcp_servers: Option<PluginManifestMcpServers<Resource>>,
    pub apps: Option<Resource>,
    pub hooks: Option<PluginManifestHooks<Resource>>,
}
```

`interface` 字段承载面向模型与 UI 的元数据（display_name、capabilities、logo、隐私政策链接等），`paths` 字段才是真正的能力载体。`try_map_resources` 会把清单里所有路径型资源统一做一次映射（如把相对路径包成 `PluginResourceLocator`）。

解析后的权威绑定描述叫 `ResolvedPlugin`，它的关键不变量是**资源不能逃出包根**：

```rust
fn environment_resource(
    environment_id: &str,
    root: &PathUri,
    path: PathUri,
) -> Result<PluginResourceLocator, ResolvedPluginError> {
    if !path.starts_with(root) {
        return Err(ResolvedPluginError::ResourceOutsideRoot { root: root.clone(), path });
    }
    Ok(PluginResourceLocator::Environment { environment_id: environment_id.to_string(), path })
}
```

宿主侧用 `PluginId`（来自 `core-plugin-common` 的 `plugin_id`）做稳定标识，CLI 里 `PluginId`、`PluginIdError`、`validate_plugin_segment` 负责校验分片名（避免路径穿越）。

## 加载流水线：从清单到能力视图

加载的编排中枢是 `PluginsManager`（`core-plugins`），它在 `codex-core` 里通过 `plugins_manager_for_config` 构造，并把插件技能加载委托给 `HostSkillsService`：

```rust
pub fn plugins_manager_for_config(config: &Config, auth_manager: Arc<AuthManager>) -> PluginsManager {
    let skill_root_loader = Arc::new(HostSkillsService::new(config.codex_home.clone(), false));
    PluginsManager::new(config.codex_home.to_path_buf(), auth_manager, skill_root_loader)
}
```

加载实现在 `loader` 模块：`load_plugins_from_layer_stack` 按配置层栈逐包解析清单、加载技能清单（skill inventory）、MCP server、hooks、apps，并并发（上限 `MAX_CONCURRENT_PLUGIN_LOADS = 8`）解析。加载结果产出 `PluginLoadOutcome<McpServerConfig>`：

```rust
pub struct LoadedPlugin<M> {
    pub config_name: String,
    pub plugin_namespace: Option<String>,
    pub root: AbsolutePathBuf,
    pub enabled: bool,
    pub skill_roots: Vec<AbsolutePathBuf>,
    pub skill_discovery_mode: SkillDiscoveryMode,
    pub mcp_servers: HashMap<String, M>,
    pub apps: Vec<AppDeclaration>,
    pub hook_sources: Vec<PluginHookSource>,
    pub error: Option<String>,
    // ...
}

pub struct PluginLoadOutcome<M> {
    plugins: Vec<LoadedPlugin<M>>,
    capability_summaries: Vec<PluginCapabilitySummary>,
}
```

`PluginLoadOutcome` 上的 `effective_*` 方法是关键的「能力提取」入口：`effective_mcp_servers()` 汇总所有启用插件的 MCP server、`effective_plugin_skill_roots()` 去重后产出技能根、`effective_plugin_hook_sources()` 汇总钩子、`effective_apps()` 汇总连接器 ID；`without_plugins(disabled_plugin_ids)` 则在不丢弃元数据的前提下，把指定插件标记为禁用。`PluginCapabilitySummary` 还会被裁成 prompt 安全的描述（`prompt_safe_plugin_description` 截断到 1024 字符并规整空白），注入给模型的能力摘要。

## Marketplace、Store 与远程插件

插件来源由 marketplace 体系管理，内建几个权威市场：`openai-curated`、`openai-api-curated`、`openai-bundled`（以及 alpha / primary-runtime 等内部市场）。此外支持：

- **远程市场**（remote）：如 `REMOTE_GLOBAL_MARKETPLACE_NAME`，带 `RemoteInstalledPlugin`、`RemotePluginCatalog`、`RemotePluginMaterialization`，并与登录态（`AuthManager`/`CodexAuth`）联动。
- **npm 源**（npm_source）：`materialize_npm_plugin_source` 把 npm 包物化成插件源。
- **启动同步**（startup_sync）：`sync_openai_plugins_repo` 拉取 `OPENAI_PLUGINS_GIT_URL` 的策展仓库到本地缓存，并读 `read_curated_plugins_sha` 做版本校验。
- **热安装/升级**：`marketplace_add` / `marketplace_upgrade`（`ConfigLayerReload`）/ `marketplace_remove` 负责在配置层栈上增删改，并带 `MarketplacePolicy` 做允许名单管控。

已安装插件落到 `PluginStore`（`store` 模块），与配置层栈（`ConfigLayerStack`）协同；`catalog` / `executor_catalog` 把快照编成目录，`installed_marketplaces` 从层栈推导已装市场根。

## 两类特殊插件：Agent 插件与可发现插件

`SkillDiscoveryMode` 区分了插件的技能发现方式：默认 `Recursive`（递归扫描 skills 目录），而 **Agent 插件**使用 `DirectChildren`——`LoadedPlugin::is_agent_plugin()` 即据此判断。`agent_plugin_mcp_overlay` 专门处理 Agent 插件的 MCP 覆盖层。

**可发现插件（tool_suggest）** 是一条独立的推荐/发现链路：`list_tool_suggest_discoverable_plugins` 依据一份硬编码的 `TOOL_SUGGEST_DISCOVERABLE_PLUGIN_ALLOWLIST`（如 `github@openai-curated`、`notion@openai-curated`、`slack@openai-curated`、`figma@openai-curated`、`chrome@openai-bundled`、`computer-use@openai-bundled` 等）给出可被工具推荐发现的插件。这使模型在合适场景主动建议安装对应插件，而不是默认全量加载。

## 注入 codex-core：钩子、MCP、技能、连接器

加载结果在会话构建阶段被消费。`core/src/session/mod.rs` 里：

```rust
let plugin_outcome = plugins_manager.plugins_for_config(&plugins_input).await
    .without_plugins(disabled_plugin_ids);
let plugin_hook_sources = plugin_outcome.effective_plugin_hook_sources();
// -> HooksConfig { plugin_hook_sources, plugin_hook_load_warnings, ... }
```

- **Hooks**：`plugin_hook_sources` 进入 `HooksConfig`，与 `codex-plugin` 的 `PluginHookSource`（含 plugin_root、source_path、HookEventsToml）合并，由 hooks 子系统在 turn 的各阶段触发。
- **MCP servers**：`effective_mcp_servers()` 汇入 `codex_mcp`，作为外部工具源。
- **Skills**：`effective_plugin_skill_roots()` 产出 `PluginSkillRoot`（带 plugin_identity、namespace、discovery_mode），喂给技能加载器，出现在模型可用的技能目录里。
- **Apps / 连接器**：`effective_apps()` 返回 `AppConnectorId`，经 `codex_connectors` 成为桌面 App 的连接器；`core/src/plugins` 下的 `mentions` 负责搜集用户显式 @ 的插件/连接器 ID，`injection` 把插件指令注入上下文，`render` 渲染显式插件说明，`metrics` 记录插件相关埋点。

此外 `core-plugins/src/discoverable.rs` 还产出 `ToolSuggestDiscoverablePlugin`（含 id、remote_plugin_id、description、mcp_server_names、app_connector_ids），供「按需发现」使用。

## UI 插件宿主（plugin-host）

桌面 UI 插件运行在独立的 V8 子进程里，由 `plugin-host` crate 管理生命周期与帧协议。helper 通过 argv0/argv1 自检 re-exec 成 `--codex-ui-plugin-process`，启动后先发一段固定的 READY 握手：

```rust
pub const HELPER_ARGUMENT: &str = "--codex-ui-plugin-process";
pub const READY: &[u8] = b"codex-ui-plugin-process/3";
pub const MAX_INSTANCES: usize = 32;
```

`PluginProcess::spawn` 的关键工程细节：

- 程序路径必须绝对（`is_absolute` 校验），且 `env_clear()` 清空环境，避免继承宿主敏感变量。
- Unix 上用 `process_group(0)` 建独立进程组，Windows 上用 `JobObject` 容器；统一 `kill_on_drop(true)`，Drop 时 `terminate_group` 杀整组。
- 用 `LengthDelimitedCodec` 做长度定界帧（`framing::codec()`），输入 `set_backpressure_boundary(1)` 防止对方不读时内存膨胀。
- 后台 drain stderr，但**只保留最后 16 KiB**（`STDERR_TAIL_BYTES`），且 `PluginExit` 的 `Debug` 故意不含原始 stderr——因为子进程输出不可信。

宿主与子进程的窄 ABI 定义在 `protocol.rs`，刻意克制（子进程只提供 correlation id，绝不给 authority / thread id）：

```rust
pub enum HostMessage {
    Initialize { source: String },
    Dispatch { id: u64, export: String, return_mode: ReturnMode },
    Close,
}
pub enum RuntimeMessage {
    Initialized,
    Pending { id: u64 },
    Reply { id: u64, value: String },
    Error { code: ErrorCode, script_error: Option<PluginScriptError> },
    Closed,
}
```

约束常量体现「有界」原则：`MAX_SOURCE = 128*1024`、`MAX_RESULT = 64*1024`、`MAX_METHOD = 1024`、`MAX_PENDING_PROMISES = 1024`、`MAX_IN_FLIGHT_TURNS = 8`，并有 `assert!` 确保最坏情况下仍不超过 `MAX_FRAME`。`ReturnMode` 区分 `Sync` 与 `MaybeAsync`，超时为 `ExecutionTimedOut`、配额超为 `QuotaExceeded`。这套宿主在 `code-mode-runtime/src/ui` 的 workers/transport 里被驱动，也就是 UI 插件脚本实际跑在 code-mode 的 V8 UI worker 内。

## 遥测与可观测挂钩

插件系统自带埋点：`PluginTelemetryMetadata`（plugin_id / remote_plugin_id / capability_summary）随会话遥测上报；`plugin_metrics` 定义 `PluginMeasurementDefinition` 与 `PluginMetricsOperation`，`plugin_metrics_sidecar` 通过 `PLUGIN_METRICS_OUTPUT_ENV_VAR` 把指标旁路到 sidecar；`script_attribution`（`PluginCommandAttribution`、`TrustedPluginRoots`）做脚本归属与可信根校验，防止不受信插件脚本执行危险命令。

## Links

- [Codex 架构总览](/docs/CS/AI/Codex/Codex.md?id=architecture)
- [Codex 核心会话循环](/docs/CS/AI/Codex/SessionLoop.md)
- [Codex 工具系统](/docs/CS/AI/Codex/Tools.md)
- [Codex 多 Agent](/docs/CS/AI/Codex/MultiAgent.md)
- [Codex 可观测性](/docs/CS/AI/Codex/Observability.md)
- [AI 总纲](/docs/CS/AI/AI.md)

## References

1. [openai/codex（v0.167.0）plugin / plugin-host / core-plugins / core-plugin-common](https://github.com/openai/codex/tree/v0.167.0/codex-rs)
2. [Codex CLI 文档](https://developers.openai.com/codex/cli/)
