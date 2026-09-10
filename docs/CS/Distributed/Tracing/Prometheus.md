## Introduction

[Prometheus](https://prometheus.io/) 是一个开源系统监控和告警工具包，最初由 SoundCloud 构建。自 2012 年成立以来，许多公司和组织都采用了 Prometheus，该项目拥有非常活跃的开发者和用户社区。它现在是一个独立的开源项目，不依赖于任何公司进行维护。为了强调这一点，并澄清该项目的治理结构，Prometheus 于 2016 年加入了云原生计算基金会（CNCF），作为继 Kubernetes 之后的第二个托管项目。

> Prometheus 项目与 Kubernetes 项目一样，也来自于 Google 的 Borg 体系，它的原型系统，叫作 BorgMon，是一个几乎与 Borg 同时诞生的内部监控系统。

Prometheus 采集并将其指标存储为时间序列数据，即指标信息与记录时的时间戳一同存储，此外还可以伴随被称为标签（Label）的可选键值对。

Prometheus 的主要特性包括：

- 多维数据模型，其时间序列数据由指标名称和键/值对标识
- PromQL，一种灵活的查询语言，用以发挥这种多维度的优势
- 不依赖分布式存储；单个服务器节点是自治的
- 时间序列数据采集通过基于 HTTP 的拉取（Pull）模型进行
- 通过中间网关（Pushgateway）支持推送时间序列数据
- 通过服务发现或静态配置来发现目标
- 支持多种图形和仪表板展示模式（Grafana、Prometheus Web UI 等）

## Installation

> [部署Prometheus](https://monaive.gitbook.io/prometheus)

Prometheus 受启发于 Google 的 Borgmon 监控系统。Prometheus 基于 Golang 开发，可方便进行二进制部署，同时可方便地使用 Docker 或 Kubernetes 进行部署。除程序外，仅有单文件配置文件与存储数据，存储数据亦可使用第三方数据库。

### 二进制部署

```bash
# 下载并解压（版本可按需调整）
wget https://github.com/prometheus/prometheus/releases/download/v2.53.0/prometheus-2.53.0.linux-amd64.tar.gz
tar -xzf prometheus-2.53.0.linux-amd64.tar.gz
cd prometheus-2.53.0.linux-amd64

# 启动
./prometheus --config.file=prometheus.yml
```

默认监听 `http://localhost:9090`。

### Docker 部署

```bash
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```

### 常用启动参数

| 参数                                   | 说明                         |
| ------------------------------------ | -------------------------- |
| `--config.file`                      | 配置文件路径，默认 `prometheus.yml` |
| `--storage.tsdb.path`                | 数据存储目录，默认 `data/`          |
| `--storage.tsdb.retention.time`      | 数据保留时长，默认 `15d`            |
| `--web.enable-lifecycle`             | 启用 `/-/reload` 等管理 API     |
| `--web.enable-remote-write-receiver` | 允许接收 Remote Write 数据       |

### 热加载

启动时需开启 `--web.enable-lifecycle`：

```bash
curl -X POST http://localhost:9090/-/reload
```

## Architecture

Prometheus 主要包含下面几个组件：

- Prometheus Server：用于拉取 metrics 信息并将数据存储在时间序列数据库
- Jobs/Exporters：用于暴露已有第三方服务的 metrics 给 Prometheus Server，比如 StatsD、Graphite 等，负责数据收集
- Pushgateway：主要用于短期 jobs。由于这类 jobs 存在时间短，可能在 Prometheus Server 来拉取 metrics 信息之前就消失了，所以这类 jobs 可以直接向 Pushgateway 推送它们的 metrics 信息，再由 Prometheus Server 统一拉取
- Alertmanager：用于数据报警，负责告警的去重、分组、路由与静默
- Prometheus Web UI：负责数据展示

此图展示了 Prometheus 的架构及其部分生态系统组件

![](https://prometheus.ac.cn/assets/docs/architecture.svg)

Prometheus 直接或通过中间 Pushgateway（用于短期任务）从已插桩的任务中抓取指标。它在本地存储所有抓取的样本，并对这些数据运行规则，以从现有数据中聚合和记录新的时间序列，或者生成告警。可以使用 Grafana 或其他 API 消费者来将收集到的数据可视化。

它的工作流程大致是：

- Prometheus Server 定期从配置好的 jobs 或者 exporters 中拉取 metrics 信息，或者接收来自 Pushgateway 的 metrics 信息
- Prometheus Server 把收集到的 metrics 信息存储到时间序列数据库中，并运行已经定义好的 recording rules / alerting rules，向 Alertmanager 推送警报
- Alertmanager 根据配置文件，对接收的警报进行处理（去重、分组、路由），发出告警
- 通过 Prometheus Web UI 或 Grafana 进行可视化展示

### Pull vs Push

Prometheus 采用 Pull 模型，优点：

- 目标只需暴露 `/metrics` HTTP 端点，无需感知监控系统
- 拉取失败即可感知目标下线（up 指标）
- 便于水平扩展与调试（直接 curl 查看数据）

Push 模型（通过 Pushgateway 或 Remote Write）适用于：

- 短生命周期任务（批处理作业结束就退出，来不及被抓取）
- 防火墙不允许反向访问的场景

## Configuration

Prometheus 使用 YAML 配置，核心结构：

```yaml
global:
  scrape_interval: 15s      # 抓取间隔
  evaluation_interval: 15s  # 规则评估间隔

# 告警规则文件
rule_files:
  - "rules/*.yml"

# 告警推送目标
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["localhost:9093"]

scrape_configs:
  # 监控 Prometheus 自身
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # 静态配置目标
  - job_name: "node"
    static_configs:
      - targets: ["192.168.1.10:9100", "192.168.1.11:9100"]
        labels:
          env: prod

  # 基于文件的服务发现
  - job_name: "file-sd"
    file_sd_configs:
      - files: ["sd/*.json"]
        refresh_interval: 5m
```

### Service Discovery

生产环境中目标通常不是固定的，Prometheus 支持多种服务发现机制：

- `static_configs`：静态配置
- `file_sd_configs`：基于文件（JSON/YAML），适合脚本动态生成
- `kubernetes_sd_configs`：从 Kubernetes API 发现 Pod/Service/Node/Endpoint
- `consul_sd_configs`：Consul 服务发现
- `dns_sd_configs`：DNS SRV 记录发现

服务发现产出的标签可通过 relabeling（`relabel_configs`）在抓取前进行过滤、改写，`metric_relabel_configs` 则在入库前对样本标签进行处理。

## Data Model

Prometheus 从根本上将所有数据存储为时间序列（time series）：属于同一指标和同一组标签维度、带有时间戳的值流。除已存储的时间序列外，Prometheus 还可能生成临时的派生时间序列作为查询结果。

每条时间序列由**指标名称**和可选的被称为标签（label）的键值对唯一标识。

指标名称指定了被测量的系统特征（例如 `http_requests_total` 表示接收到的 HTTP 请求总数），可以包含 ASCII 字母、数字、下划线和冒号，必须匹配正则 `[a-zA-Z_:][a-zA-Z0-9_:]*`。

> 注意：冒号是为用户定义的 recording rules 保留的，exporter 或直接插桩不应使用。

### Sample

时间序列中的每个点称为样本（sample），由三部分组成：

- float64 类型的值
- 毫秒精度的时间戳

### Label

标签为同一指标名建立不同的维度（如 `method="GET"`、`handler="/api"`）。标签值的任意组合都对应一条独立的时间序列，因此标签组合总数（基数）直接决定存储量。

给定指标名称和一组标签，通常使用如下记法标识一条时间序列：

```
<metric name>{<label name>=<label value>, ...}

# 例如
http_requests_total{method="POST", handler="/messages"}
```

### Metric Types

Prometheus 客户端库提供四种指标类型：

| 类型        | 含义                         | 典型用途               |
| --------- | -------------------------- | ------------------ |
| Counter   | 单调递增计数器，只能增加或在重启时归零        | 请求数、错误数、完成任务数      |
| Gauge     | 可任意上下变化的瞬时值                | 当前内存占用、并发数、队列长度、温度 |
| Histogram | 采样并统计到观测桶（bucket）中，提供分位数估计 | 请求耗时、响应大小          |
| Summary   | 客户端侧预计算分位数（不支持聚合）          | 请求耗时的分位数           |

- 对 Counter 做差值计算用 `rate()` / `increase()`；对 Gauge 直接取值
- Histogram 在服务端用 `histogram_quantile()` 计算分位数，可跨实例聚合，且支持事后调整桶的划分，推荐优先于 Summary

Histogram 的命名约定：

```
<basename>_bucket{le="<upper inclusive bound>"}
<basename>_sum
<basename>_count
```

### Jobs and Instances

- Instance：可以抓取的目标端点（通常对应一个进程）
- Job：一组具有相同目的的 instances（例如为了可扩展性和可靠性而复制的进程组）

## PromQL

PromQL（Prometheus Query Language）是 Prometheus 的函数式查询语言，支持瞬时查询（instant query）与区间查询（range query，带 `[duration]`）。

```promql
# 指标名称 + 标签过滤
http_requests_total{job="api", method="POST"}

# 区间查询：最近 5 分钟的样本
http_requests_total[5m]

# 对 Counter 求 QPS
rate(http_requests_total{job="api"}[5m])

# TopK
topk(10, rate(http_requests_total[5m]))

# 求和聚合
sum by (handler) (rate(http_requests_total[5m]))

# 直方图分位数：P99 延迟
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# 两个指标运算：错误率
rate(http_requests_total{status=~"5.."}[5m])
  / rate(http_requests_total[5m])
```

### 常用操作符与函数

- 聚合：`sum`、`avg`、`min`、`max`、`count`、`topk`、`bottomk`，可用 `by` / `without` 分组
- 算术/比较/逻辑：`+ - * / % == != > < =~ !~`，`and or unless`
- Counter 类：`rate`、`irate`、`increase`、`resets`
- Gauge 类：`avg_over_time`、`max_over_time`、`min_over_time`、`delta`、`idelta`
- 变化趋势：`deriv`、`predict_linear`
- 标签处理：`label_replace`、`label_join`
- 时间对齐：`offset`、`@`（绝对时间戳修饰符）

### Recording Rules

将常用且计算量大的查询预先物化为新序列，既加快仪表板加载，也为告警提供稳定的命名约定（如 `level:metric:operations`，例如 `instance_path:requests:rate5m`）：

```yaml
groups:
  - name: example
    rules:
      - record: job:http_requests:rate5m
        expr: sum by (job) (rate(http_requests_total[5m]))
```

## Storage

### Local Storage

Prometheus 的本地时序数据库（TSDB）以一种自定义且极其高效的格式将数据存储在本地存储中。

摄入的样本按两小时分为一个块（Block）。每个块由一个目录组成，该目录包含一个 chunks 子目录（包含该时间窗口内的所有时序样本）、一个元数据文件（metadata）和一个索引文件（index，用于将指标名称和标签映射到 chunks 目录中的时序）。chunks 目录中的样本被组织成一个或多个段（segment）文件，默认情况下每个文件最大为 512 MB。当通过 API 删除序列（series）时，删除记录将存储在独立的 tombstone 文件中，而不是立即从 chunk 段中移除。

旧块会定期被压缩合并成更大的块。默认保留 15 天（`--storage.tsdb.retention.time=15d`），到期后自动删除；也可按磁盘占用大小保留（`retention.size`）。

当前接收样本的块保存在内存中，并未完全持久化。为了防止崩溃，它通过预写日志（WAL）进行保护，该日志可以在 Prometheus 服务器重启时重新播放。预写日志文件存储在 wal 目录中，每个段为 128MB。这些文件包含尚未经过压缩合并的原始数据，因此它们通常比普通块文件大得多。Prometheus 将至少保留三个预写日志文件。高流量的服务器可能会保留三个以上的 WAL 文件，以便保存至少两个小时的原始数据。

> 本地存储不适合长期保存。长期存储推荐使用 Remote Storage（如 Thanos、Mimir、VictoriaMetrics），或对象存储方案。

### Remote Storage

Prometheus 通过两个接口与远端存储集成：

- Remote Read：查询时将部分读请求下推到远端
- Remote Write：将样本实时转发到远端系统

`remote_write` 常用于将数据汇总到全局视图层（如 Thanos Receive / Mimir），实现跨集群查询与长期存储：

```yaml
remote_write:
  - url: "http://thanos-receive:19291/api/v1/receive"
```

### Federation

联邦（Federation）允许一个 Prometheus 从另一个 Prometheus 拉取选定的时序，用于构建全局视角的"树干"服务器：

```
GET /federate?match[]={__name__=~"job:.*"}
```

## Exporter

### node_exporter

Node Exporter 主要用于监控"机器本身"的健康状态，而不是运行在机器上的具体应用程序。它采集的核心指标包括：

- CPU：使用率、各个核心的负载、上下文切换次数等
- 内存（Memory）：总内存、已用内存、可用内存、Swap（交换分区）使用情况等
- 磁盘（Disk）：磁盘空间使用率、磁盘 I/O 读写速率、I/O 延迟等
- 网络（Network）：网卡的流量（收发字节数）、丢包率、网络错误数等
- 文件系统（Filesystem）：各个挂载点的使用情况、inode 使用情况
- 系统状态：系统启动时间、系统负载（Load Average）、进程状态等

默认端口 `9100`，常用 PromQL 示例：

```promql
# CPU 使用率（非 idle 时间占比）
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# 内存可用率
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes

# 磁盘使用率
100 - (node_filesystem_avail_bytes{mountpoint="/"}
  / node_filesystem_size_bytes{mountpoint="/"}) * 100
```

部署

```plaintext
tar -xzf node_exporter-1.11.1.linux-amd64.tar.gz
mv node_exporter-1.11.1.linux-amd64 node_exporter
rm -f node_exporter-1.11.1.linux-amd64.tar.gz
cd node exporter
nohup /node_exporter --web.listen-address=":9100" >>nohup.out &
```

### cAdvisor

[cAdvisor](https://github.com/google/cadvisor)（Container Advisor）由 Google 开源，用于采集运行中容器的资源指标：CPU、内存、网络、文件系统 I/O 等。Kubernetes 内置的 `kubelet` 自带 cAdvisor 端点（`/metrics/cadvisor`），因此 k8s 场景通常无需单独部署。

```promql
# 容器内存使用量（排除 k8s 基础设施容器）
container_memory_working_set_bytes{container!="", image!=""}
```

### blackbox_exporter

Blackbox Exporter 进行"黑盒"探测，从外部视角监控：

- HTTP(S) 探测：状态码、响应耗时、TLS 证书有效期
- ICMP Ping：延迟、丢包
- TCP：端口连通性
- DNS：解析结果与耗时

```yaml
scrape_configs:
  - job_name: "blackbox-http"
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ["https://example.com"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```

### Pushgateway

Pushgateway 用于接收短期任务推送的指标并暂存，等待 Prometheus 拉取。适用于批处理作业等无法被主动抓取的场景。

```bash
# 推送示例
cat <<EOF | curl --data-binary @- http://pushgateway:9091/metrics/job/batch_job/instance/worker1
# TYPE batch_records_total counter
batch_records_total 12345
EOF
```

注意事项：

- Pushgateway 中的数据不会过期，任务失败后旧数据会一直存在，需要主动 DELETE 或在指标中附带时间戳
- 多实例任务推送同一组标签会互相覆盖，应确保标签能区分实例
- 不适合替代常规服务（长期运行的服务应暴露 /metrics 被抓取）

## Alerting

### Alerting Rules

告警规则在 Prometheus 中评估，触发后推送给 Alertmanager：

```yaml
groups:
  - name: example
    rules:
      - alert: HighErrorRate
        expr: |
          rate(http_requests_total{status=~"5.."}[5m])
            / rate(http_requests_total[5m]) > 0.05
        for: 10m                # 持续满足条件 10 分钟才触发
        labels:
          severity: warning
        annotations:
          summary: "高错误率 {{ $labels.instance }}"
          description: "错误率已达 {{ $value | humanizePercentage }}"
```

- `expr`：触发条件
- `for`：条件需持续满足的时长（Pending → Firing）
- `labels`：附加标签，可用于 Alertmanager 路由
- `annotations`：描述信息，模板变量如 `$labels.*`、`$value`

### Alertmanager


Alertmanager 负责告警的去重（deduplication）、分组（grouping）、路由（routing）与静默（silencing），并支持抑制（inhibition）。支持的通知渠道包括邮件、Webhook、Slack、企业微信、PagerDuty 等。

```yaml
route:
  receiver: default
  group_by: ["alertname", "cluster"]
  group_wait: 30s       # 组内首条告警的等待时间
  group_interval: 5m    # 同组新告警的通知间隔
  repeat_interval: 4h   # 重复通知间隔
  routes:
    - matchers: [severity="critical"]
      receiver: oncall

receivers:
  - name: default
    webhook_configs:
      - url: "http://webhook:8080/alert"
  - name: oncall
    webhook_configs:
      - url: "http://oncall:8080/critical"
```

## Best Practices

- 指标命名：`namespace_metricname_units`（如 `http_request_duration_seconds`），Counter 以 `_total` 结尾，使用基本单位（seconds、bytes）而非毫秒/KB
- 控制基数（cardinality）：避免无上界的标签（如 user_id、request_id），每个标签组合都是一条独立序列；经验上单实例序列数超过百万即需警惕
- 优先 Histogram 而非 Summary（可聚合）
- 仪表板用 Recording Rules 预聚合，告警规则给足 `for` 时间避免抖动
- 不要把 Prometheus 当作通用 TSDB 或事件存储使用

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)

## References

1. [Prometheus 官方文档](https://prometheus.io/docs/introduction/overview/)
2. [Prometheus 中文文档](https://prometheus.ac.cn/)
3. [部署 Prometheus](https://monaive.gitbook.io/prometheus)
4. [Apache HertzBeat](https://github.com/apache/hertzbeat)
5. [Prometheus Notes](https://erdong.site/prometheus-notes/)
6. [Google SRE: Borgmon 的起源](https://sre.google/sre-book/monitoring-distributed-systems/)
