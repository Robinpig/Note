## Introduction

**Promtail** 是 Grafana Labs 出品的日志采集 agent，职责单一：从宿主机上发现日志文件（或 systemd journal），读取、打标签、做轻量处理，然后推送给 [Loki](/docs/CS/Distributed/Tracing/Loki.md)。它是 Loki 生态早期的默认采集端，常以 DaemonSet 形式部署在 Kubernetes 每个节点上。

Promtail 的工作可以拆成三段：**发现**（去哪儿读）→ **打标签**（这条日志属于哪个流）→ **推送**（送到 Loki）。

> [!WARNING]
> **Promtail 已于 2026 年 3 月 2 日到达生命周期终点（EOL），不再维护，商业支持也已结束。** 后续所有功能开发都在 [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md) 上进行。仍在运行 Promtail 的实例必须规划迁移——本文档保留用于理解既有部署与迁移前的对照，新项目不应再选它。
>
> 一个例外：**`lambda-promtail`**（用于把 AWS CloudWatch 日志转发到 Loki 的 Lambda 客户端）不在本次弃用范围内。

## Architecture

Promtail 内部是一条三段式管道：

```
  发现（Service Discovery）
        │  基于 Kubernetes API / 静态配置 / 文件 glob 找到日志文件与容器 stdout
        ▼
  Scrape（Tailing）
        │  逐行读取，用 positions 文件记录已读偏移，重启后不重复、不丢失
        ▼
  Pipeline（处理管道）
        │  一系列 stage：解析、改写标签、过滤、多行合并、限流
        ▼
  Client（推送）
        │  POST /loki/api/v1/push，批量 + 压缩，失败按退避重试
        ▼
     Loki
```

三段各自的要点：

- **发现**：K8s 场景下 Promtail 通过 Kubernetes API 感知本节点的 Pod，读取 `/var/log/pods/...` 下的容器日志，并自动把 Pod 的 label/annotation 转成日志标签（`namespace`、`pod`、`container`、`app` 等）。非 K8s 场景用 `static_configs` 指定路径。
- **采集**：靠 `positions` 文件（默认 `/run/promtail/positions.yaml`）记录每个文件的读取偏移。这是「不重不漏」的关键，DaemonSet 部署时该文件必须落在宿主机的持久化路径上，否则重启会重放或丢日志。
- **推送**：批量攒够或超时即发送，失败按指数退避重试；Loki 不可达时内存中的批次会堆积，需要配合限流配置防止 OOM。

## Configuration

Promtail 的配置结构与 Prometheus 的 `scrape_configs` 刻意保持一致：

```yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /run/promtail/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: system
    static_configs:
      - targets: [localhost]
        labels:
          job: varlogs
          __path__: /var/log/*.log

  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        target_label: app
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
    pipeline_stages:
      - cri: {}                    # 解析 CRI 容器运行时格式
      - json:
          expressions:
            level: level
            msg: message
      - labels:
          level:                   # 只把 level 提升为标签（低基数）
      - output:
          source: msg
```

### Pipeline Stages

管道是 Promtail 真正有用的部分，常用 stage 如下：

| Stage | 作用 |
| --- | --- |
| `docker` / `cri` | 解析容器运行时的日志封装格式 |
| `regex` / `json` / `logfmt` | 从日志行里提取字段 |
| `labels` | 把提取出的字段提升为 Loki 标签（**只提升低基数字段**） |
| `structured_metadata` | 把字段作为结构化元数据附加（高基数字段的正确归宿） |
| `timestamp` | 用日志内部时间戳覆盖采集时间 |
| `multiline` | 合并多行日志（Java 堆栈、panic）为一条 |
| `match` / `drop` | 条件过滤，丢弃无用日志 |
| `output` | 重写最终发给 Loki 的日志行内容 |
| `metrics` | 从日志行里生成 Prometheus 指标（如统计错误数） |
| `limit` | 限流，防止日志风暴打满 Loki |

标签提升这一步最需要克制：每提升一个高基数字段，就等于把 [Loki](/docs/CS/Distributed/Tracing/Loki.md) 的流数量乘上去，直接推高索引与成本。

## Migration to Grafana Alloy

Grafana 提供了内置的配置转换能力，不必手工重写：

```bash
# 一次性转换：Promtail 配置 -> Alloy 配置
alloy convert --source-format=promtail \
  --output=/etc/alloy/config.alloy /etc/promtail/promtail.yaml

# 输出诊断报告（会列出无法自动迁移的项）
alloy convert --source-format=promtail \
  --report=report.txt --output=/etc/alloy/config.alloy /etc/promtail/promtail.yaml

# 过渡期：直接以 Promtail 格式运行，Alloy 内部即时转换
alloy run --config.format=promtail /etc/promtail/promtail.yaml
```

Promtail 到 Alloy 的组件映射关系：

| Promtail 概念 | Alloy 组件 |
| --- | --- |
| `scrape_configs` 中的文件发现 | `local.file_match` |
| 读取与 pipeline 处理 | `loki.source.file`（含 `loki.process` 做 stage 处理） |
| `clients` 推送目标 | `loki.write` |
| systemd journal 采集 | `loki.source.journal` |

转换时有两处已知的坑，官方诊断报告会明确提示：

- **tracing 配置无法自动迁移**，需要按 Alloy 的 tracing 文档重新配置。
- **Alloy 暴露的指标与 Promtail 不同**，依赖 Promtail 指标名的告警规则和仪表盘必须相应修改。

`--bypass-errors` 可以做尽力转换，但转换结果的行为可能与原配置不一致，上生产前必须充分测试。

迁移顺序上，建议按节点分批，先确保只有一方在读取并转发同一条流，再切换 positions/offset 的处理方式，并保留回滚方案——避免把整段历史日志重放一遍进生产存储。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)

## References

1. [Migrate from Promtail to Grafana Alloy](https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/)
2. [Promtail agent (Grafana Enterprise Logs)](https://grafana.com/docs/enterprise-logs/latest/send-data/promtail/)
3. [Promtail configuration](https://grafana.com/docs/loki/latest/send-data/promtail/configuration/)
4. [Grafana Loki clients](https://grafana.com/docs/loki/latest/send-data/)
