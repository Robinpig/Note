## Introduction

Codex 的可观测性建立在一套 OpenTelemetry（OTel）栈之上，由 `otel` crate 统一封装**日志（logs）、追踪（traces）、指标（metrics）**三路导出。它的设计有三个鲜明特征：

- **三路独立开关**：`exporter` / `trace_exporter` / `metrics_exporter` 各自可配 `None` / `Statsig` / `OtlpGrpc` / `OtlpHttp`，互不影响。
- **一切导出都过网络策略（network_policy）**：底层 OTel exporter 被 `PolicyExporter` 包裹，受 `codex_http_client` 的出站策略（如沙箱网络代理）约束，避免插件或受管环境绕过网络管控。
- **可热重载、可优雅关闭**：provider 在账号切换/配置变更时重建，关闭走独立 detached 线程并带超时预算，绝不阻塞主流程。

本篇按「配置 → provider → 三路导出 → 事件/指标 → trace websocket 桥 → 热重载」展开。

## 配置模型：Config → OtelSettings

用户在 `Config.otel` 里声明导出方式（`OtelExporterKind`），`core/src/otel_init.rs::build_provider` 把它翻译成 `codex_otel` 的 `OtelSettings`：

```rust
let metrics_exporter = if matches!(config.otel.metrics_exporter, Kind::Statsig)
    && !config.analytics_enabled.unwrap_or(default_analytics_enabled)
{
    OtelExporter::None          // 分析同意（analytics consent）才放行内置 Statsig 导出
} else {
    to_otel_exporter(&config.otel.metrics_exporter)
};

OtelProvider::try_new(&OtelSettings {
    http_client_factory: config.http_client_factory(),
    service_name: service_name.to_string(),
    service_version: service_version.to_string(),
    codex_home: config.codex_home.to_path_buf(),
    environment: config.otel.environment.to_string(),
    exporter, trace_exporter, metrics_exporter,
    runtime_metrics: config.features.enabled(Feature::RuntimeMetrics),
    span_attributes: config.otel.span_attributes.clone(),
    tracestate: config.otel.tracestate.clone(),
})
```

`OtelExporter` 四态里，`Statsig` 是 Codex 内置的默认指标接收端（仅用于 metrics），在 release 下解析为 `https://ab.chatgpt.com/otlp/v1/metrics` 并带内建 api key；**debug 构建下 `resolve_exporter` 会把它降级成 `None`**，以免本地/测试产生真实的 OTEL 流量。`OtlpHttp` 支持 `Binary`（protobuf）与 `Json` 两种协议，并可选 `OtelTlsConfig`（CA / 客户端证书 / 私钥）做双向 TLS。

## OtelProvider：全局安装与导出过滤

`OtelProvider::try_new` 是入口，它一次性构建 logger、tracer_provider、tracer、metrics 四件，并：

1. 把 tracer_provider 装到进程全局（`install_global_tracer_provider` → `global::set_tracer_provider` + `TraceContextPropagator`），全关时则装 `NoopTracerProvider`。
2. 把 metrics 装成进程全局（`install_global` / `install_global_statsig_settings`）；无 metrics 时 `buffered::GLOBAL.disable()`。
3. 预备一个 detached 关闭工作线程（`prepare_shutdown_worker`），后续 `shutdown_with_timeout` 在该线程上 flush+shutdown，带超时预算。

它暴露三类 tracing layer，供上层 `tracing_subscriber` 注册：

- `logger_export_layer` / `logger_layer`：日志桥（`OpenTelemetryTracingBridge`）。
- `tracing_layer`：追踪桥（`tracing_opentelemetry::layer`）。
- `reloadable_tracing_layer`：用 `GlobalTracer` 永久跟随进程全局 tracer provider，即使启动关闭也保持安装，便于账号切换后再装上 trace 导出器。

关键在**导出过滤**——不是所有 `tracing` 记录都外发，靠 target 前缀判定：

```rust
pub fn log_export_filter(meta: &tracing::Metadata<'_>) -> bool {
    is_log_export_target(meta.target())          // 仅 codex_otel.log_only / codex_otel.network_proxy 等
}
pub fn trace_export_filter(meta: &tracing::Metadata<'_>) -> bool {
    if meta.is_span() {
        !matches!(target.split("::").next(), Some("h2" | "tokio" | "runtime"))  // 避免 SDK 自激导出
    } else {
        is_trace_safe_target(target)             // 仅 codex_otel.trace_safe*
    }
}
```

这保证了：h2 / tokio / runtime 的根 span 不会逃逸成 OTLP 导出（否则会自激循环），只有 `trace_safe` 前缀的事件才进 trace、只有 `log_only` / `network_proxy` 等前缀才进日志。

## 三路导出与 TLS

`build_logger` 与 `build_tracer_provider`（均在 `provider.rs`）按 `OtelExporter` 构造底层 exporter，并统一用 `network_policy::PolicyExporter` 包裹：

```rust
builder = builder.with_batch_exporter(crate::network_policy::PolicyExporter {
    exporter,
    policy: factory.network_policy().clone(),
});
```

- **gRPC**：用 tonic，`assume_http2(true)` + 可选 mTLS（`build_grpc_tls_config`）。
- **HTTP**：binary/json 协议；当网络策略为受管（`is_managed()`）时换用 `build_async_http_client`，否则仅在配置了 tls 时用 `build_http_client`（见 `otlp.rs`）。
- **批处理**：traces 在多线程 Tokio 运行时下用 `TokioBatchSpanProcessor`，否则用标准 `BatchSpanProcessor`，均受 `PolicyExporter` 约束。
- **Span 属性**：配置的 `span_attributes` 通过 `SpanAttributesProcessor::on_start` 在每个 span 起点注入；资源级属性（`service.name` / `service.version` / `env`，logs 还带 `host.name`）由 `make_resource` 生成。

## W3C 追踪上下文

`trace_context` 模块处理跨进程传播：`current_span_trace_id`、`span_w3c_trace_context`、`inject_span_w3c_trace_headers` / `set_parent_from_w3c_trace_context` 实现 W3C `traceparent` / `tracestate` 的注入与提取；`validate_tracestate_entries` / `validate_tracestate_member` 在校验期就拦掉非法 tracestate，`traceparent_context_from_env` 支持从环境变量恢复父 span。这让 Codex 把一次用户 turn 的 trace 串联到上游服务（如 responses API 网关）。

## 指标：MetricsClient 与指标字典

指标由 `MetricsClient`（`otel/src/metrics/client.rs`）提供 `counter` / `histogram` / `record_duration` / `start_timer` 等 API，`MetricsConfig` 支持 `otlp`（带 runtime reader）与 `in_memory`（测试）两种后端。`install_global_metrics` 把某个 client 装成进程全局，供各子系统 `start_global_timer` 打点。

指标名集中在 `otel/src/metrics/names.rs`，按子系统成组，例如：

- **工具**：`codex.tool.call`、`codex.tool.call.duration_ms`、`codex.tool.unified_exec`
- **Turn 全链路**：`codex.turn.e2e_duration_ms`、`codex.turn.ttft.duration_ms`、`codex.turn.ttfm.duration_ms`、`codex.turn.token_usage`、`codex.turn.cost_microusd`
- **模型 API**：`codex.api_request`、`codex.api_request.duration_ms`、`codex.responses_api_engine_iapi_ttft.duration_ms`
- **Guardian 审查**：`codex.guardian.review`、`codex.guardian.review.duration_ms`、`codex.guardian.review.token_usage`
- **目标 / 预算**：`codex.goal.created` / `codex.goal.completed` / `codex.goal.budget_limited` / `codex.goal.usage_limited`
- **Hooks / 插件**：`codex.hooks.run`、`codex.plugins.install_suggestion`、`codex.plugins.startup_sync`
- **线程 / 技能 / 工具目录**：`codex.thread.started`、`codex.thread.skills.enabled_total`、`codex.thread.tools.namespaces_total`、`codex.tools.registered`

许多指标配套对数直方图桶（`context_log_buckets`），如 `THREAD_TOOLS_METRIC_BUCKETS`、`TOOL_SPEC_DESCRIPTION_BYTES_METRIC_BUCKETS`、`THREAD_SKILLS_DESCRIPTION_TRUNCATED_CHARS_BUCKETS`，用于压缩高动态范围的值。`runtime_metrics` 打开后还会采集进程级 runtime 指标（`RuntimeMetricsSummary` / `RuntimeMetricTotals`）。

## 事件：会话遥测与领域事件

`otel/src/events` 定义结构化事件：`SessionTelemetry` / `SessionTelemetryMetadata` / `AuthEnvTelemetryMetadata` 承载一次会话的遥测；`agent_response`（AgentResponseLogger）、`skill_invocation`（SkillInvocationEvent）、`tool_result`、`network_policy`、`guardian_assessment` 则是领域事件模块，把模型回复、技能调用、工具结果、网络策略决策、Guardian 审查结果转成 OTel 事件或指标。这让「一次 turn 为什么被这样审查」「哪个技能被触发」都可在后端追溯。

## Trace WebSocket 桥（otel-trace-websocket）

`TraceWebSocket` 把进程内产生的 OTLP trace 批次转发到一个 WebSocket 监听端，用于**实时 trace 浏览**（如桌面 App 的追踪面板）：

```rust
let otlp_listener = TcpListener::bind("127.0.0.1:0").await?;   // loopback OTLP 接收
let websocket_listener = TcpListener::bind(bind_address).await?;
// POST /v1/traces -> broadcast::Sender<Vec<u8>>
// GET / -> WebSocket，把广播的批次以 binary frame 推给客户端
```

要点：

- **仅本机**：OTLP 接收绑定 `127.0.0.1`，WebSocket 端 `reject_requests_with_origin_header` 拒绝带 `Origin` 头的请求，防 CSRF/跨站。
- **尽力而为**：`broadcast` 容量 1024，客户端掉线或 lag 直接丢批次（`RecvError::Lagged`），`max_frame_size` 4 MiB。
- 注释明确：丢弃 bridge 会 abort 监听器而不 drain 队列，调用方须在 drop 前 flush trace provider。

## 热重载：账号/配置变更不重启

app-server 通过 `otel_reloader` 在**不重启进程**的前提下重建导出器。启动时 `layers()` 用 `reload::Layer` 把 logger 导出层包成可热替换的 handle，并始终保持 `reloadable_tracing_layer`（全局 tracer 桥常驻）。`spawn` 监听 `auth_manager.auth_change_receiver`：账号切换后 sleep 50ms 等账户 handler 装好新的云 loader，再 `config_manager.load_latest_config` → `build_provider` 重建 provider，用 `logger_reload_handle.reload(...)` 换上新的 logger 层，旧 provider 在 `spawn_blocking` 里 `shutdown()`。`trace_exporter` 因为是全局 tracer 桥，无需 reload 即可被后续调用命中。

## CLI / TUI 侧的本地日志

除了 OTel 远端导出，CLI / TUI 还用 `tracing_subscriber::fmt` 做本地可读日志：`app-server` 的 `LogFormat::Json` / `LogFormat::Default` 切换 JSON 与默认格式，并带 `FmtSpan` 渲染 span；`feedback` crate 把用户反馈流也接进同一套 subscriber。`state/src/log_db.rs` 则把结构化日志落进本地 SQLite（`log_db`），作为 OTel 之外的本地可查存档。

## Links

- [Agent Harness 可观测性（理论框架）](/docs/CS/AI/LLM/Agent/Theory/Observability.md) — 本文机制的通用化提炼与设计检查单
- [Codex 架构总览](/docs/CS/AI/Codex/Architecture.md)
- [Codex 核心会话循环](/docs/CS/AI/Codex/SessionLoop.md)
- [Codex 工具系统](/docs/CS/AI/Codex/Tools.md)
- [Codex 插件系统](/docs/CS/AI/Codex/PluginSystem.md)
- [Codex 记忆与上下文管理](/docs/CS/AI/Codex/MemoryContext.md)
- [AI 总纲](/docs/CS/AI/AI.md)

## References

1. [openai/codex（v0.167.0）otel / otel-trace-websocket / core/src/otel_init.rs](https://github.com/openai/codex/tree/v0.167.0/codex-rs)
2. [OpenTelemetry 规范](https://opentelemetry.io/docs/specs/otel/)
3. [W3C Trace Context](https://www.w3.org/TR/trace-context/)
