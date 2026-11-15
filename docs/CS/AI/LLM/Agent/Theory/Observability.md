# Agent Harness Observability (可观测性)

## Introduction

在 Harness 八项共性里，可观测性是最晚成体系的一项：文件操作、规划、编排都有多年积累，而「怎么观测一个 Agent」至今没有公认的参照系——传统服务的可观测性（RED/USE、黄金指标）直接搬过来并不成立，因为 Agent 的执行主体是**非确定性的模型决策**，而不是确定性的请求处理。

> 本文是八项共性第 7 项的专页，定位在 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 的组件清单上。核心材料来自 Codex 的源码级实现——它的 `otel` crate 是目前最完整的生产级答案，实现细节（provider、导出过滤、指标字典、trace websocket 桥、热重载）见 [Codex 可观测性（源码级）](/docs/CS/AI/Codex/Observability.md)，本文只提炼可迁移的设计。权限与上下文压缩这两项的专页见 [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 与 [上下文压缩](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)。

四个反直觉的结论先行给出，正文逐条展开：

1. **观测的主数据结构不是 trace，是回放记录**——观测应建立在持久化之上，而不是与持久化并列再建一套
2. **「哪些数据允许外发」是在写代码时用前缀声明的**，不是事后在后端过滤
3. **遥测系统会被自己观测**——不设防会自激出无限循环
4. **观测面本身受权限模型约束**——能绕过网络策略的遥测通道，就是管控的后门

## Why Harness Observability Is Different

传统服务可观测性的默认假设在这里全部失效。四点根本差异：

| 差异 | 传统服务 | Agent Harness |
| :--- | :--- | :--- |
| 执行主体 | 确定性代码路径，失败可复现 | 模型决策，同样输入也可能走出不同轨迹 |
| 调试单元 | 一次请求（request） | 一次 turn / 一步采样 / 一次工具调用，粒度天然多层 |
| 数据敏感度 | 大多是脱敏后的业务指标 | prompt 与工具输出**就是**用户代码、密钥、私有仓库内容 |
| 观测者与被观测者 | 分离（APM 旁路采集） | 同一个进程、同一个 runtime——遥测管道自己也是被观测对象 |

第一条决定了记录策略：既然不能靠复现调试，就必须**完整记录 I/O**——模型看到了什么、说了什么、调了什么工具、工具返回了什么。这也解释了结论 1：这份完整记录本身恰恰就是崩溃恢复需要的东西（Codex 的 rollout JSONL），所以观测与恢复应该共用同一份记录。

## What to Observe: From Failure Modes to Signals

观测什么不能凭感觉列清单，应从 Harness 要解决的那四种失效模式反推——**每种失效模式都对应一组必须在观测面上看得见的信号**：

| 失效模式 | 必须观测的信号 | Codex 的对应物 |
| :--- | :--- | :--- |
| 上下文溢出 | 窗口占用水位、每次压缩的触发点与前后 token 数 | 每步 `capture_step_context` 快照、压缩事件、`codex.turn.token_usage` |
| 目标漂移 | 计划/goal 的生命周期（创建、完成、被预算截断）、step 链是否偏离计划 | `codex.goal.created` / `codex.goal.completed` / `codex.goal.budget_limited` |
| 失败级联 | 工具调用的错误率、重试链、错误之后模型是否在错误假设上继续 | `codex.tool.call`（带结果维度）、`codex.tool.call.duration_ms` |
| 越界执行 | 审批决策、沙箱拒绝、网络策略拦截——一条**不可变审计流** | 审批事件、`guardian_assessment`、`network_policy` 领域事件 |

反过来说，如果一个 Harness 的观测面上看不到这四组信号，它对四种失效模式就是盲的——观测做得好不好，不看面板花不花哨，看**失效发生时能不能从数据里重建因果链**。

## The Signal Model: Trace / Metric / Event

三类 OTel 信号在 Harness 里的分工要重新划定，不是照搬微服务的「trace 排查、metric 告警」：

- **Trace 承载因果链**。span 层级直接对齐 Harness 的四个上下文粒度（见 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 的 Codex 一节）：Thread → Turn → Step → Item。一次 turn 是一个 span，一步采样是其子 span，每次工具调用再往下一层。跨进程用 W3C `traceparent` 串联——Codex 把 turn 的 trace 一直连到模型 API 网关，上游延迟与本地决策可以拼成一条链。
- **Metric 承载聚合与成本**。Agent 的成本结构与传统服务完全不同：一次 turn 的延迟要看 TTFT/TTFM（首 token / 首 item），费用要看 token 用量与微美元成本。Codex 把指标名集中在一个字典文件里按子系统成组（`codex.tool.call` / `codex.turn.e2e_duration_ms` / `codex.turn.cost_microusd` / `codex.guardian.review` / `codex.hooks.run`……），高动态范围的值用对数直方图桶压缩。**指标字典集中管理**是个值得照抄的纪律：指标名散落各处是最常见的观测债。
- **Event 承载领域事实**。审批决策、Guardian 审查结论、网络策略判定、技能触发——这些是「为什么」层面的事实，不适合塞进 span 属性，也不适合聚合成指标，应该是带结构的独立事件。审计需求（谁批准了什么）全靠这一路。

## One Record, Two Uses: Replay First

这是 Codex 方案里最值得迁移的架构决策。多数实现会为调试单独铺一条 trace 采集路径，结果出现两份不完全一致的记录——崩溃后恢复用的历史与调试面板里看到的历史对不上。Codex 的做法：

```text
rollout JSONL（不可变主记录，逐 Item 追加）
   ├─→ 崩溃恢复：reconstruct_history_from_rollout 重放注水
   ├─→ 本地索引：SQLite 五库异步 backfill（可查询）
   └─→ 观测：metric / event 打点读同一份会话状态
```

**记录即回放**：观测建立在 record 之上而非并列。附带的好处是 trace 不必追求「采全」——span 丢了还有 rollout 兜底，观测面可以从容做采样与过滤。LangSmith 这类产品把 trace 做成独立产品路线，适合开发期调试；生产 Harness 的底线是先有自己可控的 record。

## Tiered Exports: Local First, Consent Gated

同一份数据要有三个出口，各自服务不同场景，而不是只有一个远端：

1. **本地可查**：`tracing_subscriber::fmt` 本地日志 + 结构化日志落 SQLite——出问题时第一现场永远在本地
2. **实时面板**：本地回环起一个 OTLP 接收端 + WebSocket 广播，桌面 App 的追踪面板实时看 trace 批次
3. **远端分析**：OTLP（gRPC / HTTP，可 mTLS）导出到后端做车队级聚合

出口分层的同时要配**同意门控**——这是 Agent 可观测性与传统服务最大的伦理差异：用户让 Agent 读的代码不该默默变成遥测数据。Codex 的做法是把「外发什么」做成两层约束：

- **数据侧**：只有显式标记为 `trace_safe` / `log_only` 前缀的记录才允许进入导出管线——允许外发是**写代码时声明**的，不是运行时事后过滤
- **用户侧**：内置指标导出器（Statsig）只在 `analytics_enabled` 同意后才放行；debug 构建直接降级为 `None`，本地开发不产生真实遥测流量

敏感内容（密钥、凭证）在进入记录前先 `redact`。观测数据一旦离开进程就不再受你控制，所以门控必须做在出口之前。

## The Self-Excitation Problem

遥测管道跑在被观测的同一个 Tokio runtime 里，会产生一个传统服务没有的故障模式：**自激**——导出请求本身产生 span，span 触发导出，无限循环直到打爆出口带宽。Codex 的防护：

```rust
pub fn trace_export_filter(meta: &tracing::Metadata<'_>) -> bool {
    if meta.is_span() {
        // 根 target 是 h2 / tokio / runtime 的 span 一律不导出——避免 SDK 自激
        !matches!(target.split("::").next(), Some("h2" | "tokio" | "runtime"))
    } else {
        is_trace_safe_target(target)   // 仅 trace_safe 前缀的事件才进 trace
    }
}
```

同时所有底层 exporter 都被 `PolicyExporter` 包裹——遥测出站也过网络策略。这引出结论 4：**观测面不能成为绕过管控的后门**。受管环境下 Agent 的网络全被代理管住，如果遥测通道可以直连任意外网，等于给被管控的执行面开了一条特权隧道。可观测性必须和工具执行接受同一套权限约束——它是 Harness 的一部分，不是旁路。

## Engineering Discipline

生命周期层面的纪律，琐碎但决定生产可用性：

- **热重载**：账号/配置变更时重建导出器而不重启进程——Agent 会话动辄数小时，观测不能绑定在进程生命周期上
- **优雅关闭带超时预算**：flush + shutdown 放在独立线程，带超时——观测系统慢不能拖垮主流程
- **失败静默降级**：远端导出不可达只丢数据不报错（实时桥的 broadcast 容量满即丢批次），观测永远「尽力而为」
- **观测不阻塞主循环**：导出走 batch 异步，主循环只做打点

## A Design Checklist

把上面收敛成一张可执行的检查单，给自建 Harness 用：

1. **span 层级对齐循环粒度**：Thread/Turn/Step/Item 四层，工具调用挂到 Step 之下
2. **记录即回放**：完整 I/O 落盘（append-only JSONL 或等价物），观测与恢复共用
3. **指标字典集中 + 成本一等公民**：TTFT/TTFM、token、cost、工具错误率进指标；命名集中管理
4. **审计流独立且不可变**：审批/沙箱/策略决策走结构化事件，与可变的业务状态分开
5. **外发显式声明 + 同意门控 + 脱敏**：`trace_safe` 式前缀在写代码时声明；analytics consent 把门；出口前 redact
6. **自激防护 + 遥测过权限**：过滤 runtime/h2 类自生 span；exporter 过网络策略
7. **三层出口**：本地日志/库、实时面板、远端分析，各自独立开关
8. **生命周期纪律**：热重载、超时关闭、失败降级、异步不阻塞

对应到 Harness.md 的成熟度判据——压缩策略、权限粒度、恢复语义之外，**观测面能不能在失效发生时重建因果链**，是第四项硬指标。

## Links

- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 八项共性的总纲，本文是第 7 项的展开
- [Codex 可观测性（源码级）](/docs/CS/AI/Codex/Observability.md) — 本文所有机制的实现出处
- [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md) / [上下文压缩](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) — 八项共性里另两个专页
- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)

## References

1. [openai/codex（v0.167.0）otel / otel-trace-websocket / core/src/otel_init.rs](https://github.com/openai/codex/tree/v0.167.0/codex-rs)
2. [OpenTelemetry 规范](https://opentelemetry.io/docs/specs/otel/)
3. [W3C Trace Context](https://www.w3.org/TR/trace-context/)
