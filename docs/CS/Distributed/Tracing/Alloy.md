## Introduction

[Grafana Alloy](https://grafana.com/oss/alloy/) 是 Grafana Labs 的**统一遥测采集器**（telemetry collector），本质是一个 OpenTelemetry Collector 发行版，同时内置了 Prometheus 原生的采集管道。它用一个进程覆盖 metrics、logs、traces、profiles 四类信号的发现、处理与转发，是 [Promtail](/docs/CS/Distributed/Tracing/Promtail.md)（EOL）与 Grafana Agent 的继任者。

理解 Alloy 的切入点是：**它取代的是「采集层」，不是「存储层」**。数据的保留与查询仍然归后端——[Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) / Mimir、[Loki](/docs/CS/Distributed/Tracing/Loki.md)、[Tempo](/docs/CS/Distributed/Tracing/Tempo.md)、Pyroscope。Alloy 的配置决定的是「发现什么、怎么处理、发给谁」。

> [!NOTE]
> 版本事实截至 2026-10：Alloy 当前主线为 **1.x**，近期稳定版本 1.19.2（2026-08-26）与 1.20.0（2026-09-25）。许可证 Apache-2.0。发布节奏：minor 约每三周，patch 每一到两周，属 best-effort。仓库另有 `LICENSING.md` 说明各内置组件的许可差异，商用打包前建议单独读一遍。

## Why One Agent

在 Alloy 之前，一台宿主机上常常要跑好几个采集器：Promtail 收日志、Prometheus scrape 或 node_exporter 出指标、OTel Collector 收 trace。Alloy 把它们合并成一个进程：

- **一套配置语言**描述所有信号的管道。
- **一个可观测对象**：单一进程的健康、指标、日志。
- **内置 UI**（默认 `:12345`）渲染实时的组件依赖图，每个块的健康状态直接可见，比分别翻几个 agent 的日志高效得多。

它遵循 Grafana 的「big tent」路线：集成 Grafana 自家后端是一等公民，但并不锁定，也能发往其它厂商或开源数据库。

## Configuration Model

Alloy 用**组件式**配置：每个组件有输入与输出，通过引用连接成一张有向图。这与 OTel Collector 的 YAML（receiver → processor → exporter 三段式）是两种心智模型。

```alloy
// 发现目标
discovery.kubernetes "pods" {
  role = "pod"
}

// 抓取 Prometheus 指标
prometheus.scrape "default" {
  targets    = discovery.kubernetes.pods.targets
  forward_to = [prometheus.remote_write.mimir.receiver]
}

// 转发指标到 Mimir / Prometheus
prometheus.remote_write "mimir" {
  endpoint {
    url = "http://mimir:9009/api/v1/push"
  }
}

// 读取日志文件
local.file_match "logs" {
  path_targets = [{
    __path__ = "/var/log/*.log",
    job      = "varlogs",
  }]
}

// 处理并转发日志到 Loki
loki.source.file "logs" {
  targets    = local.file_match.logs.targets
  forward_to = [loki.process.logs.receiver]
}

loki.process "logs" {
  stage.json {
    expressions = { level = "level" }
  }
  stage.labels {
    values = { level = "" }
  }
  forward_to = [loki.write.default.receiver]
}

loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}

// 接收 OTLP 并转发 trace 到 Tempo
otelcol.receiver.otlp "default" {
  grpc {}
  output {
    traces = [otelcol.exporter.otlp.tempo.input]
  }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
  }
}
```

三层复用机制让配置不至于在大范围部署里失控：

- **Modules**：把一段管道封装成可复用的模块，团队间共享。
- **Clustering**：多个 Alloy 实例组成集群，自动分配工作负载，避免重复采集。
- **remotecfg**：从服务端拉取配置，适合集中管理。

## OpenTelemetry Engine

自 **v1.14.0** 起，Alloy 内置了一个实验性的 **OpenTelemetry engine**，用 `alloy otel` 子命令启动。开启后可以直接用上游 Collector 的 YAML 配置 Alloy：

- 两个 engine 可**并行运行**，通过 Alloy engine extension 在 Collector YAML 之外继续指定 Alloy 语法的管道。
- 这是一个 **opt-in** 特性：不启用就完全不影响既有部署。
- 适合已有大量上游 Collector YAML、不想重写成 Alloy 语法的团队。

术语上，Alloy 引入了 engine 的说法：默认 engine（Alloy 原生语法）与 OpenTelemetry engine（Collector YAML）。两个 engine 在 Fleet Management 等运维能力上的对齐仍在进行中，默认端口与日志格式也可能略有差异。

## Alloy vs. OTel Collector

| 维度 | Grafana Alloy | 上游 OTel Collector |
| --- | --- | --- |
| 配置语法 | Alloy 组件语法（表达式驱动）+ 可选 Collector YAML | Collector YAML |
| Prometheus 抓取 | 一等公民，`prometheus.scrape` 深度优化 | 需通过 prometheus receiver |
| Loki / Pyroscope | 原生组件（`loki.*`、`pyroscope.*`） | 需自配 exporter |
| 组件图 UI | 内置 `:12345` | 需额外扩展 |
| 模块化 / 集群 | modules、clustering 内置 | 生态方案拼装 |
| 发布节奏 | minor 约三周，变更较快 | 相对稳定 |
| 许可 | Apache-2.0（内置组件许可见 `LICENSING.md`） | Apache-2.0 |

选择上的判断依据：如果遥测数据本来就落在 Prometheus / Loki / Pyroscope，且希望一个二进制、配置即代码，Alloy 更省事；如果团队已有大量上游 Collector YAML 且不想引入新语言，留在上游（或用 Alloy 的 OTel engine）是合理的选择。无论选哪个，**存储侧的保留与成本策略都得自己定**，采集器不解决这个问题。

## Migration

- **从 Promtail 迁移**：Alloy 提供了 `alloy convert --source-format=promtail`，一键把 Promtail 配置转成 Alloy 配置，也可用 `--config.format=promtail` 过渡运行。详见 [Promtail](/docs/CS/Distributed/Tracing/Promtail.md)。
- **从 Grafana Agent 迁移**：Alloy 是 Grafana Agent 的继任者，官方提供对应转换路径。

迁移时要关心的不只是配置文件本身：日志的发现方式、标签、解析 stage、多行处理、租户头、凭据、**已保存的读取位点**都要逐一盘点。配置转换不等于输出等价——务必抽样比对真实事件，检查是否有丢行、重复行、时间戳变化或标签基数变化。

## Operations Notes

- **版本节奏快**：minor 约三周一次，生产环境应固定版本并读 changelog 再升级；配置表面在演进，存在 current 与 legacy 两套语法。
- **确认组件存在**：上生产前核对所需组件是否在官方组件参考列表中，尤其是用到较新的 processor/exporter 时。
- **UI 是主要排障入口**：`:12345` 的组件图能直接看出哪一段管道不健康，比翻日志快。
- **许可单独核对**：仓库根是 Apache-2.0，但内置组件来自多个生态，打包进产品前读 `LICENSING.md`。
- 采集层的上游标准化（API/SDK/协议）由 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 负责，Alloy 与之是协作而非替代关系。

## Links

- [Promtail](/docs/CS/Distributed/Tracing/Promtail.md)
- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)

## References

1. [Grafana Alloy documentation](https://grafana.com/docs/alloy/latest/)
2. [Migrate from Promtail to Alloy](https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/)
3. [Native OpenTelemetry inside Alloy](https://grafana.com/blog/native-opentelemetry-inside-alloy-now-you-can-get-the-best-of-both-worlds/)
4. [grafana/alloy Releases](https://github.com/grafana/alloy/releases)
