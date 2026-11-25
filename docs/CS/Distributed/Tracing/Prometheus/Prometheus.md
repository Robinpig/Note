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

> 生产部署、双 Prometheus 与 Alertmanager 集群示例见 [Deploy](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)。

Prometheus 受启发于 Google 的 Borgmon 监控系统。Prometheus 基于 Golang 开发，可方便进行二进制部署，同时可方便地使用 Docker 或 Kubernetes 进行部署。除程序外，仅有单文件配置文件与存储数据，存储数据亦可使用第三方数据库。

### Binary Deployment

```bash
# 下载并解压（版本可按需调整）
wget https://github.com/prometheus/prometheus/releases/download/v3.16.0/prometheus-3.16.0.linux-amd64.tar.gz
tar -xzf prometheus-3.16.0.linux-amd64.tar.gz
cd prometheus-3.16.0.linux-amd64

# 启动
./prometheus --config.file=prometheus.yml
```

> [!NOTE]
> 版本基线截至 2026-11-24：本文以 **Prometheus 3.16.0**（2026-11-04）为准，tag `v3.16.0` 指向 commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`。官方当前 LTS 为 **3.13.5**，支持至 2027-07-31；新机制验证用 3.16.0，稳定生产可跟随 LTS。minor 版本约每 6 周一个周期，非 LTS 线只维护到下一个 minor 发布后不久，因此不要用 `latest` 标签替代明确的版本策略。

默认监听 `http://localhost:9090`。

### Docker Deployment

```bash
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus:v3.16.0
```

### Common Startup Parameters

| 参数                                   | 说明                         |
| ------------------------------------ | -------------------------- |
| `--config.file`                      | 配置文件路径，默认 `prometheus.yml` |
| `--storage.tsdb.path`                | 数据存储目录，默认 `data/`          |
| `--storage.tsdb.retention.time`      | 数据保留时长，默认 `15d`            |
| `--web.enable-lifecycle`             | 启用 `/-/reload` 等管理 API     |
| `--web.enable-remote-write-receiver` | 允许接收 Remote Write 数据       |

### Hot Reloading

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

### Pull and Push

Prometheus 采用 Pull 模型，优点：

- 目标只需暴露 `/metrics` HTTP 端点，无需感知监控系统
- 拉取失败即可感知目标下线（up 指标）
- 便于水平扩展与调试（直接 curl 查看数据）

Push 模型（通过 Pushgateway 或 Remote Write）适用于：

- 短生命周期任务（批处理作业结束就退出，来不及被抓取）
- 防火墙不允许反向访问的场景

### Internal Pipeline

Prometheus Server 不是“一个抓取线程 + 一个数据库”那么简单，而是由多个长期运行的 actor 通过 channel、context 和引用连接起来：

| 组件 | 源码落点 | 职责 |
| --- | --- | --- |
| 进程装配 | `cmd/prometheus/main.go` | 解析 flag、加载 YAML、创建并启动 discovery/scrape/storage/rules/web 等组件 |
| Discovery Manager | `discovery/manager.go` | 每种服务发现机制独立运行，持续发送 target group 更新 |
| Scrape Manager | `scrape/manager.go` | 每个 `scrape_config` 对应一个 scrape pool |
| Scrape Pool / Loop | `scrape/pool.go`、`scrape/scrape.go` | 每个 target 一个循环，错峰抓取、解析、relabel、写入 |
| Fanout Storage | `storage/fanout.go` | 写入复制到本地与远端，读取合并本地和远端结果 |
| Local TSDB | `tsdb/db.go` | 本地持久化、压缩、保留和查询 |
| PromQL Engine | `promql/engine.go` | 被 Web API 与 rule manager 当作库调用，不是独立存储服务 |
| Rule Manager | `rules/manager.go` | 周期性执行 recording/alerting rules |
| Notifier | `notifier/manager.go`、`notifier/sendloop.go` | 将 firing/resolved alerts 异步发送到 Alertmanager |
| Web / API | `web/web.go`、`web/api/v1/api.go` | UI、查询、target/rule/alert/status 管理接口 |

flag 配置与 YAML 配置的生命周期不同：`--config.file`、`--storage.tsdb.path` 等 flag 通常需要重启；YAML 中的 scrape、relabel、remote write、rule 等配置可以通过 `/-/reload` 或 `SIGHUP` 热更新。热更新失败时，旧配置继续生效。

### Scrape Lifecycle

单个 target 的抓取链路可概括为：

```text
service discovery
  -> target labels + relabel_configs
  -> hash offset
  -> HTTP GET /metrics
  -> Content-Type negotiation + decode
  -> metric_relabel_configs
  -> storage.Appender.Commit()
  -> local TSDB + remote write queues
```

scrape loop 不会让同一 target 的两次抓取重叠；`scrape_timeout` 被限制在 `scrape_interval` 内。目标标签与 URL 的 hash 决定它在周期内的起始相位，因此增加 target 不会让所有实例在同一秒一起请求。

每次抓取都会生成 `up`、`scrape_duration_seconds`、`scrape_samples_scraped`、`scrape_samples_post_metric_relabeling` 等自监控序列。`up=1` 表示这次抓取、解析和写入成功，不表示 exporter 背后的业务健康；`up=0` 还包括 HTTP 状态异常、响应读取失败、协议解析失败、样本超限或 append 失败。失败抓取会按空抓取处理，为已跟踪序列补写 stale marker；只有显式时间戳且未开启 `track_timestamps_staleness` 等未被跟踪的序列，才主要依赖 lookback delta 过期。

### Pull Does Not Mean One-Way

Pull 描述的是**抓取方向**，不是整个系统只能被动接收数据：

- Prometheus 仍可通过 Remote Write 把已抓取的数据异步推给中心存储。
- Prometheus 可开启 Remote Write receiver 或 OTLP receiver 接收推送数据。
- Pushgateway 是“给 Prometheus 继续拉”的暂存器，不是服务发现或分布式缓冲层。

因此架构选择应分别回答三个问题：谁发现 target、谁发起抓取、样本最终写到哪里。把这三个方向混为一谈，是设计 HA 与全局视图时最常见的误区。

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

### Defaults and Limits

| 配置 | 默认值 | 关键语义 |
| --- | --- | --- |
| `global.scrape_interval` | `1m` | job 未覆盖时的抓取周期 |
| `global.scrape_timeout` | `10s` | 不得大于 `scrape_interval` |
| `global.evaluation_interval` | `1m` | rule group 未覆盖时的评估周期 |
| `metrics_path` | `/metrics` | 抓取路径 |
| `scheme` | `http` | 目标协议 |
| `honor_labels` | `false` | 标签冲突时把目标自带标签改为 `exported_<name>` |
| `honor_timestamps` | `true` | 保留目标显式时间戳；关闭后使用抓取时间 |
| `track_timestamps_staleness` | `false` | 是否跟踪显式时间戳序列的消失 |
| `sample_limit` | `0` | metric relabel 后样本数上限；超限则整次抓取失败 |
| `label_limit` | `0` | 每个样本允许的标签数上限；超限则整次抓取失败 |
| `label_name_length_limit` / `label_value_length_limit` | `0` | 标签名/值字节长度上限；超限则整次抓取失败 |
| `body_size_limit` | `0` | 未压缩响应体上限；超限则整次抓取失败 |
| `scrape_native_histograms` | `false` | 开启后协议协商优先 `PrometheusProto` |

`0` 在 limit 类配置中表示“不限制”，不是“禁止”。生产环境应优先设置 body/sample/label 上限：它们防止单个坏 target 拖垮抓取器，但也意味着超限时整个 target 的该次数据都会被丢弃。

### Relabeling Pipeline

一次抓取的数据变换顺序是固定的：

1. 服务发现生成 target group，加入 `job`、`instance` 等标签。
2. `relabel_configs` 对 target 标签做 `keep`、`drop`、`replace`、`hashmod`、`labelmap` 等操作，并生成 `__address__`、`__scheme__`、`__metrics_path__`、`__param_*`。
3. 对最终标签集和 URL 做 hash，在 scrape interval 内确定错峰偏移，避免所有 target 同时抓取。
4. 发起 HTTP 请求，按响应的 `Content-Type` 解码。
5. `metric_relabel_configs` 对每个样本的标签和指标名做变换，并删除不需要的序列。
6. 通过 `storage.Appender` 写入本地 TSDB，同时进入 remote write 队列。

`relabel_configs` 决定“抓谁、抓哪里”，`metric_relabel_configs` 决定“哪些样本以及以什么标签身份入库”；把昂贵的基数治理放在 metric relabel 阶段，通常比事后删除序列更有效。

### Scrape Protocol Negotiation

Prometheus 3.x 不再对缺失、无法识别或错误的 `Content-Type` 静默回退到文本协议，而是让抓取失败；确实需要兼容旧 exporter 时，显式配置 `fallback_scrape_protocol`。普通默认协议顺序如下：

- 默认：`OpenMetricsText1.0.0` → `OpenMetricsText0.0.1` → `PrometheusText1.0.0` → `PrometheusText0.0.4`
- `scrape_native_histograms: true`、`created-timestamp-zero-ingestion` 或 `st-storage` 会把 `PrometheusProto` 放到最前面；显式设置 `scrape_protocols` 时以配置为准

协议选择影响的不只是压缩和解析性能，还影响显式时间戳、原生直方图、exemplar 等能力是否可见。3.16.0 的 OpenMetrics 2.0 仍是 `openmetrics2` 实验 flag，不能把“支持 2.0 content type”当作稳定承诺。默认值与 feature flag 的相互作用见 `config/config.go:605-624`、`cmd/prometheus/main.go:277-310`。

## Data Model

Prometheus 从根本上将所有数据存储为时间序列（time series）：属于同一指标和同一组标签维度、带有时间戳的值流。除已存储的时间序列外，Prometheus 还可能生成临时的派生时间序列作为查询结果。

每条时间序列由**指标名称**和可选的被称为标签（label）的键值对唯一标识。

指标名称指定了被测量的系统特征（例如 `http_requests_total` 表示接收到的 HTTP 请求总数）。传统 ASCII 名称可以包含字母、数字、下划线和冒号，必须匹配正则 `[a-zA-Z_:][a-zA-Z0-9_:]*`；3.x 默认还允许 UTF-8 名称，详见下文。

> 注意：冒号是为用户定义的 recording rules 保留的，exporter 或直接插桩不应使用。

### Samples

时间序列中的每个点称为样本（sample），由值和时间戳两部分组成：

- 值：`float64` 或原生直方图（native histogram）
- 毫秒精度的时间戳

### Labels

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
| Summary   | 客户端侧预计算分位数；分位数不能跨实例聚合 | 请求耗时的分位数           |

- 对 Counter 做差值计算用 `rate()` / `increase()`；对 Gauge 直接取值
- Histogram 在服务端用 `histogram_quantile()` 计算分位数，可跨实例聚合；桶边界由客户端预先确定，不能事后重分桶，推荐优先于 Summary

Histogram 的命名约定：

```
<basename>_bucket{le="<upper inclusive bound>"}
<basename>_sum
<basename>_count
```

### Jobs and Instances

- Instance：可以抓取的目标端点（通常对应一个进程）
- Job：一组具有相同目的的 instances（例如为了可扩展性和可靠性而复制的进程组）

### Staleness and Lookback

Prometheus 用 stale marker 与 lookback delta 两种机制避免“旧数据被当成当前值”：

- **Stale marker**：目标被删除、成功抓取中序列消失，或抓取失败被当作空抓取时，Prometheus 会为已跟踪序列写入特殊 stale NaN，让它立即停止参与 instant selector。源码明确把 failed scrape 视为 empty scrape；解析或 append 失败时也会先 rollback，再用空输入补写 stale marker（`scrape/scrape.go:1611-1630`）。
- **Lookback delta**：instant vector selector 返回评估时刻之前最近的样本，但只接受距今不超过 lookback delta 的样本；默认是 `5m`。它是查询可见性窗口，不是数据保留时间，也不是抓取超时时间。未被 stale 机制覆盖的序列仍可能在这段时间里显示旧值。

因此 `up == 0` 表示最近一次抓取失败，不等于“业务一定不可用”；但通常情况下，该 target 被跟踪的业务序列会同时收到 stale marker，而不是继续在 instant query 里显示旧值。若样本携带显式时间戳，默认绕过 staleness 跟踪，需要设置 `track_timestamps_staleness: true`（`scrape/scrape.go:1965-1987`）。

### Native Histograms

经典 Histogram 把桶展开成多条 `_bucket{le="..."}` 序列，并附带 `_sum`、`_count`；原生直方图则把一个完整直方图作为**单个样本值**存储，包含 `sum`、`count` 和稀疏指数桶，并携带 counter/gauge 语义。

| 维度 | Classic Histogram | Native Histogram |
| --- | --- | --- |
| 样本形态 | 多条独立 float 序列 | 单个 histogram sample |
| 桶布局 | 抓取时固定的 `le` 边界 | schema + 稀疏 bucket index |
| 跨实例聚合 | 先对 `_bucket` 聚合，再算分位数 | 可直接对 histogram sample 聚合 |
| 协议要求 | text / protobuf 均可 | 需要 `PrometheusProto` 等支持方式 |
| 查询函数 | `histogram_quantile()` | 同样支持 `histogram_quantile()` |

原生直方图解决了经典桶边界“抓取后不能改”的问题，也降低了高基数桶的序列数量；但不同 schema/bucket layout 仍可能不兼容，无法协调时对应向量元素会被丢弃并给出 warning。Summary 的客户端分位数没有桶信息，不能像 Histogram 那样在服务端跨实例重新计算分位数。

### Metadata and Exemplars

`HELP`、`TYPE`、`UNIT` 是 metric family 元数据，不是时间序列身份的一部分；同一指标可以在不同 target 上携带不同元数据。Metadata WAL Records 功能开启后，元数据变化会按序列写入 WAL，Remote Write 2.0 也依赖它传递 metadata。

Exemplar 是挂在样本或直方图桶上的外部引用，最常见的是 `trace_id`。它用于从异常指标下钻到单条 trace，不是每个样本都要保存的标签。`exemplar-storage` 开启后，Prometheus 用固定大小的环形缓冲区保存 exemplar，并写入 WAL；环形缓冲被覆盖后旧 exemplar 不可追溯。

### UTF-8 Names

Prometheus 3.x 允许 metric name 和 label name 使用 UTF-8；默认 validation scheme 为 `utf8`，需要保持旧行为时可设置 `metric_name_validation_scheme: legacy`。非传统名称在 PromQL 中必须加引号：

```promql
{"http.server.request.duration", "service.name"="api"}
{__name__="温度", "場所"="東京"}
```

3.16.0 仍把“无引号的 Unicode 字母与点号”放在 `promql-unquoted-utf8-names` 实验 flag 后；不要因为服务端能摄入 UTF-8 名称，就假设所有 PromQL 客户端都能无引号解析它。

## PromQL

PromQL（Prometheus Query Language）是 Prometheus 的函数式查询语言。它直接操作时间序列，而不是 SQL 表；查询结果仍是带标签的向量、标量或字符串。

| 概念 | 含义 | 示例 |
| --- | --- | --- |
| instant vector | 每个时间序列在某个评估时刻最多一个样本 | `http_requests_total{job="api"}` |
| range vector | 每个时间序列在一段时间内的样本窗口 | `http_requests_total[5m]` |
| instant query | 在一个评估时刻执行表达式 | `/api/v1/query` |
| range query | 从 `start` 到 `end` 按固定 `step` 反复执行 | `/api/v1/query_range` |

`[5m]` 只是 range vector selector，不等于一次 range query；range vector 必须交给 `rate()`、`avg_over_time()` 等函数消费，不能作为最终结果直接返回。

### Execution Model

一次查询在 Prometheus 内部大致经历以下阶段：

1. **Parse**：词法/语法分析生成 AST，校验 selector、函数参数和运算符结构。
2. **Preprocess**：展开矩阵选择器、子查询与 `@` 等时间修饰信息，为执行阶段准备结构。
3. **Plan storage reads**：`FindMinMaxTime` 计算需要读取的时间范围，`populateSeries` 为 selector 生成 hints，并通过 `querier.Select()` 读取候选序列。
4. **Evaluate**：执行器递归计算 AST；range-vector 函数读取样本窗口，二元运算符执行向量匹配，聚合器按标签折叠序列。
5. **Return annotations**：把结果与 warnings/info 一起返回；例如混合直方图被忽略、非法积分策略回退都会以 annotation 表达。

这不是把 PromQL 字符串直接交给 TSDB 扫描：TSDB 只提供“按标签与时间取样本”的存储原语，表达式语义由 `promql` 包实现。Web API 与规则引擎共用同一个 Engine。主要源码落点为 `promql/parser/parse.go:66-100`、`promql/engine.go:779-871`、`promql/engine.go:1242-1383`、`promql/engine.go:1540-1643`。

| 进程级默认值 / 限制 | 默认值 | 作用 |
| --- | --- | --- |
| `--query.lookback-delta` | `5m` | instant selector 向前寻找最新样本的默认最大距离 |
| `--query.timeout` | `2m` | 单次查询默认超时与有效超时上限 |
| `--query.max-concurrency` | `20` | 同时执行的查询数 |
| `--query.max-samples` | `50000000` | 单次查询可加载到内存的样本上限 |

默认值见 `cmd/prometheus/main.go:646-656`。HTTP 请求的 `lookback_delta` 会覆盖进程默认值，可以大于或小于 `5m`；`timeout` 只能收紧有效超时上限，不能突破它。相关处理见 `web/api/v1/api.go:904-919`。

### Selectors and Time Ranges

```promql
# 指标名称 + 标签过滤
http_requests_total{job="api", method="POST"}

# 区间选择器：左开右闭 (t-5m, t]
http_requests_total{job="api"}[5m]

# Counter 变化率
rate(http_requests_total{job="api"}[5m])

# TopK
topk(10, rate(http_requests_total[5m]))

# 求和聚合
sum by (handler) (rate(http_requests_total[5m]))

# classic histogram 分位数：P99 延迟
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# 两个向量运算：错误率
rate(http_requests_total{status=~"5.."}[5m])
  / rate(http_requests_total[5m])
```

selector 必须至少包含一个非空 matcher；`job="api"` 或指标名本身都可以充当这个 matcher。`=~` 是**完全锚定**的正则匹配，不是子串搜索。未命中任何序列与命中后计算出 `0` 是两种不同结果，可用 `absent()` 区分“不存在”。

时间语义需要分开理解：

- **instant selector**：取评估时刻或之前最新的样本，但样本时间必须严格晚于 `eval_time - lookback_delta`；恰好早 5 分钟的样本在默认配置下会被排除。
- **range selector**：窗口是 `(t-range, t]`，包含右边界、排除左边界。
- **range query**：在 `start`、`start+step`、……、`end` 这些实际 step 上求值，`start` 与 `end` 都包含；子查询不会越过父查询最后实际 step。
- **lookback delta**：只决定 instant selector 能“借用”多久以前的样本，不是抓取间隔，也不是数据保留时间。

`offset` 把 selector 的求值时间整体移到过去，`@ <timestamp>` 固定到某个绝对时刻；二者修饰 selector，不是修饰任意聚合表达式。range query 的每个 step 都可以得到不同的匹配结果，因此“某个时刻没有数据”不代表整段窗口都没有数据。

### Subqueries

子查询先按固定 step 反复计算内层表达式，再把结果作为 range vector 交给外层函数：

```promql
# 最近一小时，每分钟计算一次 5m rate，再取最大值
max_over_time(rate(http_requests_total[5m])[1h:1m])
```

子查询不是新的抓取，也不会创造底层没有的采样精度；它只是对已有存储结果做时间序列化。窗口越长、step 越小，物化样本和执行成本越高，因此应优先使用 recording rule 复用稳定结果。子查询支持 `@`，但不支持 `anchored` / `smoothed` 扩展修饰符。

### Extended Range Selectors

3.16.0 将 `anchored` 与 `smoothed` 提升为稳定、默认启用的扩展 range selector，用来自定义窗口边界如何处理缺失或不规则样本：

```promql
# 不插值：起点用 lookback 内最新样本，否则用窗口内首个样本；终点用末样本
increase(http_requests_total[5m] anchored)

# 在窗口两侧线性插值
rate(http_requests_total[step()] smoothed)
```

| 修饰符 | 边界行为 | 适用函数 | 关键限制 |
| --- | --- | --- | --- |
| `anchored` | 不插值、不外推，直接选择边界样本 | `resets`、`changes`、`rate`、`increase`、`delta` | 对缺失样本的结果可能与普通 `rate()` 明显不同 |
| `smoothed` | 利用边界前后样本线性插值 | `rate`、`increase`、`delta` | 需要评估窗口之后的样本，不能用于 subquery |

`smoothed` 直接用于 recording/alerting rule 时，未来样本通常尚不存在，容易低估；规则组应设置至少一个 scrape interval 的 `query_offset`，关键告警可使用更大的 offset 容忍漏抓。`smoothed` 也可修饰 instant selector，在评估点两侧插值；`anchored` 配合 `increase()` 处理 float 样本时返回整数。语法与语义见 `docs/querying/basics.md:410-444`、`promql/parser/parse.go:1099-1143`；边界插值实现见 `promql/functions.go:303-331`、`promql/functions.go:468-618`。

### Vector Matching

默认二元运算按两侧标签集做 one-to-one 匹配，但会排除指标名 `__name__`；启用 type/unit 标签时还会排除 `__type__`、`__unit__`。标签不完全一致时，需要使用 `on` / `ignoring` 指定匹配键：

```promql
# 左侧每个 job/instance 匹配右侧每个 job 的一条 build_info
requests_total / on (job) group_left (version) build_info
```

| 匹配方式 | 基数关系 | 约束 |
| --- | --- | --- |
| one-to-one | 左右一进一出 | 匹配签名必须唯一 |
| `group_left` | many-to-one，左侧可以是高基数 | 右侧匹配签名唯一，`include` 标签从右侧复制 |
| `group_right` | one-to-many，右侧可以是高基数 | 左侧匹配签名唯一，`include` 标签从左侧复制 |
| `and` / `or` / `unless` | 按标签集合操作 | 使用 many-to-many 集合语义，不使用二元算术匹配 |

普通算术与比较运算不允许隐式 many-to-many；`group_left/right` 后得到的完整结果 labelset 仍必须唯一，否则查询报错。`bool` 比较会保留参与匹配的样本并输出 `0/1`，同时丢弃指标名；不加 `bool` 时比较运算会过滤掉条件不成立的元素。源码落点为 `promql/engine.go:3848-3960`、`promql/engine.go:4029-4070`。

### Functions and Native Histograms

| 类别 | 常用函数 | 说明 |
| --- | --- | --- |
| Counter | `rate`、`irate`、`increase`、`resets` | `rate/increase` 处理 reset；`irate` 只看最后两个样本，抖动更大 |
| Gauge / 窗口 | `avg_over_time`、`max_over_time`、`min_over_time`、`delta`、`idelta` | 对窗口内 float 样本做统计或差分 |
| 趋势 | `deriv`、`predict_linear` | 线性拟合与预测，不适合强非线性数据 |
| 标签 | `label_replace`、`label_join` | 生成或拼接标签，可能改变序列身份 |
| 时间 | `timestamp`、`start_timestamp` | 返回样本时间或累计序列的起始时间 |
| classic histogram | `histogram_quantile`、`histogram_quantiles` | 对 bucket 序列估算分位数，通常应先 `rate` 再聚合 |
| native histogram | `histogram_avg`、`histogram_count`、`histogram_sum`、`histogram_stddev`、`histogram_stdvar` | 直接消费 histogram 样本，忽略 float 样本 |
| native/classic histogram | `histogram_fraction`、`histogram_quantile` | 计算区间比例或分位数；`histogram_quantiles` 仍为实验函数 |

native histogram 与 classic histogram 不是几根 `_bucket` 序列的简单文本差异：它在一个样本中携带完整桶结构。对 native histogram 应先做 `rate()` 等窗口计算，再按目标标签聚合；先聚合原始累计值再计算变化率可能丢掉 reset 信息。NaN observation 计入 Count 但不进入普通 bucket，会影响 fraction/quantile 的解释。相关实现见 `promql/parser/functions.go:178-218`、`promql/functions.go:2402-2591`、`promql/quantile.go:230-345`。

### Start Timestamps

普通样本 timestamp 表示“这次观测发生在何时”，Start Timestamp（ST）表示“这个累计序列从何时开始”。后者能帮助 PromQL 更准确识别 Counter / Histogram 的 reset，而不是仅依赖相邻值下降。

相关能力仍分阶段处于实验状态：

- `created-timestamp-zero-ingestion`：历史名称保留的 ingestion flag，通过注入零样本传递创建时间；支持 `PrometheusProto` 与 OpenMetrics 1.0.0。
- `st-storage`：在 WAL、TSDB 与 Remote Write 2.0 中按样本保留精确 ST；会启用能保存 ST 的 chunk 编码。
- `use-start-timestamps`：让 `rate()`、`irate()`、`increase()`、`start_timestamp()` 等使用 ST；3.16.0 也用它识别 extended selector 的 float counter reset。
- `st-synthesis`：在源端没有 ST 时合成起始时间，但只适用于有序抓取数据，会丢弃首个参考样本，不能替代真实 ST。

3.16.0 的 changelog 已明确支持 extended selector 使用 ST 检测 reset；`docs/feature_flags.md:129-133` 中“不能与 extended selectors 共用”的句子尚未同步，阅读时应以该 tag 的实现和 changelog 为准。API 还可通过 `X-Prometheus-Use-Start-Timestamps` 请求头覆盖单次查询的 ST 处理。

### Experimental Functions and Query Cost

`integral()` 需要 `--enable-feature=promql-experimental-functions`，对 range vector 的 float 样本做离散积分：

```promql
integral(temperature_celsius[1h])              # 默认梯形积分
integral(temperature_celsius[1h], 0)           # 左点矩形
integral(temperature_celsius[1h], 2)           # 梯形
```

它按实际样本间隔以秒累计，NaN 当作 0，不做窗口边界外推；纯 native histogram 没有结果，混合序列会忽略 histogram 并返回 info annotation。非法策略会告警并回退到梯形积分。实现见 `promql/functions.go:1862-2007`。

3.16.0 还引入实验性 `query-cost`。启用 `--enable-feature=query-cost` 后，可在 `global` 配置执行限额：

```yaml
global:
  query_max_series: 100000
  query_max_samples_read: 100000000
  query_max_duration: 90s
```

估算成本与 `cost=true` 只提供观测信息，不会拒绝查询；真正的执行限额在加载或求值阶段生效，series/samples 超限通常返回 HTTP 422 `cost_limit`，duration 超限通常表现为 503 `timeout`。配置 `query_max_duration` 后，它也替代规则查询的 `--query.timeout`。API 的 `max_series`、`max_samples_read`、`max_query_duration` 只能收紧 operator 配置的上限，不能单方面提高。细节见 `docs/feature_flags.md:397-439`、`docs/querying/api.md:413-452`。

## Storage

### Write Path

抓取、Remote Write receiver 或 OTLP receiver 得到的样本先进入 `storage.Appender` / `AppenderV2` 批量缓存。Commit 时的关键顺序是：

1. 将样本、metadata、exemplar 等记录写入 WAL；WAL 写失败会让 Commit 失败并 rollback。
2. in-order 样本进入 Head 的 chunks；out-of-order 样本进入 OOO Head，并写 write-behind log（WBL）。
3. Head compaction 把内存中的 chunk 物化成 persistent block，成功后才推进 WAL truncation。
4. WAL watcher 读取已提交记录，交给 remote-write 的 sharded queue；HTTP 发送不是 Appender 同步完成的。

源码落点为 `storage/interface.go:443-475`、`tsdb/head_append.go:1118-1205`、`storage/remote/write.go:84-243`。需要注意，Appender 的 batch 不是跨并发写入的强事务：Commit 会再次校验样本时间，batch 内部分样本可能被丢弃；Rollback 也不保证撤销已经创建的 series 及其 WAL 记录。

### Local Storage

Prometheus 的本地 TSDB 把数据拆成 Head、WAL、persistent blocks 和索引：

| 部件 | 作用 | 关键默认值 |
| --- | --- | --- |
| Head | 接收最新样本，维护 series 与内存 chunk | 每 chunk 约 120 samples |
| WAL | 崩溃恢复尚未物化的数据 | segment 128 MiB，至少保留 3 个文件 |
| WBL | 持久化 out-of-order 写入 | 仅在 OOO 路径使用 |
| Block | 不可变的时间窗口数据 | 最小 block duration 2h |
| Index | metric/labels 到 series 与 chunk 的映射 | 每个 block 一个 `index` |
| Tombstones | 记录删除区间，延迟物理回收 | 不会立即改写 chunk segment |

“2h block”容易误导：2h 是 Head 的最小 block duration，实际 Head compaction 通常要等时间跨度超过约 `1.5 × chunkRange`，默认约 3h。最终 compaction block 的最大跨度是 `min(31d, retention/10)`；默认 15d retention 下是 36h，而不是固定 2h。chunk segment 默认最大 512 MiB，服务器模式默认启用 WAL Snappy 压缩。相关常量见 `tsdb/head.go:249-271`、`tsdb/wlog/wlog.go:41-42`、`tsdb/chunks/chunks.go:302-303`、`cmd/prometheus/main.go:509-560`。

Block 目录包含 `chunks/`、`index`、`meta.json`，删除序列时还会有 `tombstones/`。后台 compaction 把多个小 block 合并为更大的 block；源 block 与新 block 会短暂共存，因此磁盘峰值可以超过 `retention.size`。

### Query Path

查询不是“按 metric name 扫全部样本”，而是先缩小 series 范围：

1. `DB.Querier(mint, maxt)` 选择与时间范围重叠的 Head、OOO Head 和 persistent blocks。
2. label matchers 通过倒排索引求 postings，得到候选 series。
3. 读取 series metadata 与 chunk iterator，应用 tombstone 删除区间。
4. 对 Head、block、远端结果做按标签和时间的 merge，再交给 PromQL 执行。

源码落点为 `tsdb/db.go:2622-2701`、`tsdb/querier.go:165-223`、`tsdb/head_read.go:635-675`。Head 查询使用 querier 建立时的 append watermark，避免读到查询开始后提交的样本；如果本地与远端或重叠 block 在同一 series/时间戳上给出不同值，merge 不保证确定性地选择某一个，因此 HA 场景仍要避免把不同来源的冲突数据无差别合并。

### Out-of-Order and Stale Series

`--storage.tsdb.out-of-order-time-window` 默认 `0`，即默认拒绝乱序样本；开启后，窗口内的 OOO 样本进入 OOO Head 与 WBL，查询时再与 in-order 数据合并。过旧样本会得到 `ErrTooOldSample`，窗口外乱序会得到 `ErrOutOfBounds` 或 `ErrOutOfOrderSample`。Start Timestamp 的零样本目前不允许乱序。

Stale NaN 与 tombstone 是两回事：

- stale NaN 是写入时间序列的特殊样本标记，float 的 bit pattern 为 `0x7ff0000000000002`；native histogram 通过 typed stale marker 表达。
- tombstone 是 block 级删除记录，用于 API 删除整段 series 数据，并在后续 compaction 中物理回收。

因此“序列消失”不等于“数据被删除”，而“删除序列”也不等于“立刻释放 chunk 空间”。

### Retention and Backup

默认 `--storage.tsdb.retention.time=15d`；时间与大小保留策略同时配置时，谁先触发就采用谁。大小保留实际会考虑 WAL、WBL 和 Head chunk mapper，官方建议把 `retention.size` 设为磁盘容量的 80–85%，给 compaction 留 15–20% 峰值余量。过期 block 的后台清理可能延迟约 2h。

本地 TSDB 不支持 NFS/EFS 等共享文件系统，也不自带复制或集群共识。备份应优先使用 `POST /api/v1/admin/tsdb/snapshot`；直接复制正在写入的 `data/` 可能得到不一致状态。排除 `chunks_head/`、`wal/`、`wbl/` 能得到较一致的旧 block 备份，但会丢掉最近尚未物化的数据。

> 本地存储适合单机近期数据，不提供 HA 或任意长期保留。长期存储与全局查询应交给 Remote Storage、Thanos、Mimir、VictoriaMetrics 等外部系统。

### Remote Write

Remote Write 是**异步扇出**：Appender 提交后，WAL watcher 把记录送入 queue，queue 动态分片并批量发送。它不阻塞本地 TSDB 的正常写入，也不提供 exactly-once 投递；网络超时后重试可能产生重复样本，中心端必须按 series + timestamp 去重。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `remote_timeout` | `30s` | 单次 HTTP 请求超时 |
| `protobuf_message` | v1 `prometheus.WriteRequest` | 2.0 使用 `io.prometheus.write.v2.Request` |
| `queue_config.shards` | `1`，动态上限 `50` | 并发 shard 数 |
| `queue_config.capacity` | `10000` | 每 shard 可排队样本数 |
| `queue_config.max_samples_per_send` | `2000` | 每批最大样本数 |
| `queue_config.batch_send_deadline` | `5s` | 未满批时的最大等待时间 |
| `queue_config.min_backoff` / `max_backoff` | `30ms` / `5s` | 可恢复错误的指数退避范围 |

默认见 `config/config.go:228-269`、`config/config.go:1670-1673`。网络错误和 5xx 等可恢复错误会持续重试，429 是否重试由配置决定，其它 4xx 通常不重试。不可恢复错误或硬关闭会丢弃对应批次，并从 pending 计数中扣除；重启会从 WAL checkpoint 之后重放，但不保证恢复已经被 WAL watcher 消费、却尚未成功发送的数据。相关边界见 `storage/remote/queue_manager.go:1927-1944`、`storage/remote/queue_manager.go:2027-2065`。

Remote Write 1.0 是稳定规范，2.0 仍是实验规范。2.0 引入 symbol interning、start timestamp、metadata/exemplar/histogram 的显式模式与写入结果响应头；启用 metadata WAL 才能完整发送按序列 metadata。3.16.0 新增实验性 `convert_nhcb_to_classic`，用于把 native histogram custom buckets 转成不支持 NHCB 的外部系统。

```yaml
remote_write:
  - url: "http://thanos-receive:19291/api/v1/receive"
    queue_config:
      capacity: 20000
      max_shards: 32
```

### Remote Read and Receiver

Remote Read 只把匹配 label selector 与时间范围的**原始样本/chunk**取回 Prometheus，PromQL 仍在本地执行；它没有把整个 PromQL 计算下推到远端，因此不是分布式查询引擎。协议使用 Snappy 压缩 protobuf，目前不属于稳定 API，默认 timeout 1m。

Prometheus 本身也可以作为接收端：

- `--web.enable-remote-write-receiver` 开启 `/api/v1/write`，同时接受 Remote Write 1.0/2.0。
- `--web.enable-otlp-receiver` 开启 `/api/v1/otlp/v1/metrics`。
- `/api/v1/read` 对外提供 Remote Read，受 remote read 配置与并发 gate 限制。

receiver 的 v2 路径允许 4xx/非法样本部分提交，但 5xx 或 retryable error 必须 rollback，避免“客户端认为可重试、服务端却已部分成功”的歧义（`storage/remote/write_handler.go:318-471`）。

### Prometheus Agent Mode

`--agent` 复用同一套抓取、服务发现和 relabel 配置，但把本地存储替换为专用 WAL：

- 不做本地 PromQL 查询。
- 不执行 recording rules 或 alerting rules。
- 成功 remote write 后按 checkpoint/truncation 回收 WAL；默认最小保留 `5m`、最大保留 `4h`，truncate frequency 为 `2h`（`tsdb/agent/db.go:55-60`）。
- 适合中心化存储前的轻量采集层，不适合需要本地排障或本地告警的独立 Prometheus。

Agent 仍然是 Pull 采集器，只是“采完后只 remote write”，不是 Pushgateway 的替代品。3.16.0 起 Agent 也支持 `metadata-wal-records`，但该能力仍由默认关闭的实验 feature flag 控制。

### Federation

Federation 让一个 Prometheus 通过 `/federate` 抓取另一个 Prometheus 的**选定当前序列**，常用于层级聚合或跨服务共享指标：

```yaml
scrape_configs:
  - job_name: federate
    honor_labels: true
    metrics_path: /federate
    params:
      match[]:
        - '{job="prometheus"}'
        - '{__name__=~"job:.*"}'
    static_configs:
      - targets: ["source-prometheus:9090"]
```

`honor_labels: true` 必须保留源端标签，否则目标会按自己的 `job`/`instance` 覆盖源身份。联邦传的是当前值而不是完整历史，因此适合“树干”聚合，不适合备份或全局历史查询。通过联邦传 native histogram 时，抓取端还需 `scrape_native_histograms: true` 以协商 protobuf。

### High Availability

单个 Prometheus 的本地 TSDB 没有复制、共识或自动 failover。运行两个同时抓取同一 target 的 Prometheus 只会得到两份独立数据，不会自动合并查询或避免重复告警。常见模式是：

- 两个 Prometheus 都抓取，Grafana/查询层或 Alertmanager 前做高可用。
- 为副本添加稳定的 `replica`/`cluster` 标签，使告警身份可区分；若希望 Alertmanager 去重，则副本必须产生相同告警标签。
- Alertmanager 自身以 gossip 集群运行，负责跨副本去重、分组、静默和抑制。
- 跨集群全局视图与长期存储使用 Thanos、Mimir、Cortex、VictoriaMetrics 等，而不是把 Federation 当作 HA 协议。

`external_labels` 只在 Remote Write/Read 等对外协议中补充身份标签，不会神奇地把本地 TSDB 变成复制集群。

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

部署方式：

```plaintext
tar -xzf node_exporter-1.11.1.linux-amd64.tar.gz
mv node_exporter-1.11.1.linux-amd64 node_exporter
rm -f node_exporter-1.11.1.linux-amd64.tar.gz
cd node_exporter
nohup ./node_exporter --web.listen-address=":9100" >>nohup.out &
```

### cAdvisor

[cAdvisor](https://github.com/google/cadvisor)（Container Advisor）由 Google 开源，用于采集运行中容器的资源指标：CPU、内存、网络、文件系统 I/O 等。Kubernetes 内置的 `kubelet` 自带 cAdvisor 端点（`/metrics/cadvisor`），因此 k8s 场景通常无需单独部署。

```promql
# 容器内存使用量（排除 k8s 基础设施容器）
container_memory_working_set_bytes{container!="", image!=""}
```
启动方式：

```shell
docker run -it \
  --volume=/:/rootfs:ro \
  --volume=/var/run:/var/run:ro \
  --volume=/sys:/sys:ro \
  --volume=/var/lib/docker:/var/lib/docker:ro \
  --volume=/dev/disk/:/dev/disk:ro \
  --publish=9080:8080 \
  --detach=true \
  --name=cadvisor \
  --privileged \
  --device=/dev/kmsg \
  ghcr.io/google/cadvisor:v0.60.5
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

## Alerts

Prometheus 的告警分成两个独立阶段：规则引擎判断“哪些条件成立”，Alertmanager 判断“哪些通知应该发给谁”。前者依赖 PromQL 与时间状态，后者负责跨实例去重、分组、路由、静默和抑制。

### Rule Groups and Recording Rules

规则按 group 调度。一个 group 有唯一名称，并共享评估周期、标签和可选的 `query_offset`：

```yaml
groups:
  - name: http-api
    interval: 15s
    query_offset: 15s
    rules:
      - record: job:http_requests:rate5m
        expr: sum by (job) (rate(http_requests_total[5m]))
      - alert: HighErrorRate
        expr: |
          sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
            / sum by (job) (rate(http_requests_total[5m])) > 0.05
        for: 10m
        keep_firing_for: 5m
        labels:
          severity: warning
        annotations:
          summary: "高错误率 {{ $labels.job }}"
          description: "错误率已达 {{ $value | humanizePercentage }}"
```

| 字段 | 语义 |
| --- | --- |
| `interval` | group 的评估周期，默认继承 `global.evaluation_interval` |
| `limit` | 单条规则最多产生的告警数或 recording series 数，`0` 表示不限 |
| `query_offset` | 把查询的数据窗口移到过去，不改变 group 的调度时刻 |
| `labels` | group 级标签，规则级同名标签优先覆盖 |
| `record` | recording rule 输出的指标名 |
| `alert` | alerting rule 的告警名，最终进入 `alertname` 标签 |

默认情况下，不同 group 并行执行，**同一 group 内按声明顺序串行执行**，因此后面的 recording rule 可以使用前面规则的输出。启用实验性 `concurrent-rule-eval` 后，无依赖关系的规则可以并发，全局并发上限默认 4；有依赖的规则仍分批串行。源码见 `rules/manager.go:202-207`、`rules/manager.go:308-319`、`rules/group.go:659-703`。

调度不是无限补跑：如果本轮未完成，下一轮会跳过；慢 group 会持续丢评估，直到当前轮结束或超时。`rule_group_iterations_missed_total` 记录跳过次数，recording series 会出现空档。`limit` 超限则更严格：该规则的**全部**输出被丢弃，已有 pending/firing 状态被清空，而且不会补写 stale marker（`docs/configuration/recording_rules.md:146-160`）。

`query_offset` 移动的是 PromQL 求值时间，例如 15s offset 会让 `[5m]` 窗口覆盖 `t-15s-5m` 到 `t-15s`；告警 `ActiveAt` 仍使用未偏移的计划时刻 `t`。它常用于等待 scrape / remote write 数据落库，也是安全使用 `smoothed` 的必要条件。相关时间处理见 `rules/alerting.go:387-389`、`rules/alerting.go:539-541`。

Recording rule 只是把查询结果作为普通新序列写入 TSDB。它不会让原查询自动变快，除非仪表板和其他规则确实复用了输出；规则输出消失时，规则组会为旧输出补 stale marker，避免旧值永久保留。

### Alert State Machine

告警状态是按 **alerting rule + 完整 labelset** 维护的，不是一条规则只有一个全局状态：

| 状态 | 条件 | 是否通知 Alertmanager | 合成序列 |
| --- | --- | --- | --- |
| inactive | 表达式没有产生该元素 | 否；曾 firing 时发送 resolved | 无 |
| pending | 条件成立，但 `for` 尚未满足 | 否 | `ALERTS{alertstate="pending"} = 1` |
| firing | 条件成立且 `for` 已满足，或处于 `keep_firing_for` | 是 | `ALERTS{alertstate="firing"} = 1` |

`for` 从首次观察到该 labelset 满足条件开始计时；只要后续评估中元素消失，pending 立即删除。`keep_firing_for` 只延长已经 firing 的告警，不能让 pending 跳过 `for`。条件重新消失后，Firing 先转 Inactive，再按通知配置发送 resolved；resolved 记录默认在内存保留 15 分钟，便于后续恢复与去重。

Prometheus 还会生成：

- `ALERTS`：pending/firing 时值为 `1`，带 `alertstate`；不再活跃时补 stale marker。
- `ALERTS_FOR_STATE`：值为该告警 `ActiveAt` 的 Unix 秒数，不带 `alertstate`，可用来判断已持续多久。

状态转换与合成样本见 `rules/alerting.go:237-275`、`rules/alerting.go:470-550`。重启不会保存完整告警状态机：Prometheus 会结合 `--rules.alert.for-outage-tolerance`（默认 `1h`）与 `--rules.alert.for-grace-period`（默认 `10m`）恢复仍活跃告警的 `ActiveAt`，但不恢复 `LastSentAt` 或通知队列，因此重启后的首次通知行为不能假设与重启前完全相同。

### Notification Path

默认通过 Alertmanager v2 HTTP API 发送 JSON：

```text
rule Eval
  -> sendAlerts（先进入 notifier 队列）
  -> append ALERTS / ALERTS_FOR_STATE
  -> TSDB commit
```

这个顺序意味着通知已经入队后，即使规则结果写库失败，也不会回滚通知。规则组实现见 `rules/group.go:538-599`。

| Notifier 行为 | 默认值 / 语义 |
| --- | --- |
| API | v2，`POST <prefix>/api/v2/alerts`，`Content-Type: application/json` |
| 超时 | `10s` |
| 成功 | 任意 2xx |
| 失败 | 当前批次计入 dropped；notifier 自身不重试 |
| 重发节奏 | 后续规则求值按 `--rules.alert.resend-delay`，默认 `1m` |
| 发送范围 | 每个配置的 Alertmanager endpoint 集合都会收到；endpoint URL 去重不等于告警内容去重 |

实现见 `config/config.go:215-220`、`notifier/manager.go:257-277`、`notifier/sendloop.go:176-272`。因此“Prometheus 发过一次失败就自动重试到成功”是错误预期；持续 firing 的告警会在后续求值再次发送，短暂 resolved 或进程重启则可能留下通知空档。

### Alertmanager

Alertmanager 根据告警的**完整 labelset**识别和去重实例，annotations 不参与身份；Prometheus 本地并不执行跨副本去重。两个 Prometheus 副本若生成相同告警标签，可由同一 Alertmanager 集群去重；若副本标签不同，则会被视为不同告警。

Alertmanager 的核心配置如下：

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

- `group_by` 决定哪些告警合并成一个通知；分组键的基数会直接影响通知数量。
- `group_wait` 等待同组告警积累，减少碎片通知；`group_interval` 控制同组后续更新节奏。
- `repeat_interval` 控制仍在 firing 的告警多久重复通知。
- silence 按时间与 matcher 静默通知，inhibit 根据另一条告警抑制通知；二者都不删除 Prometheus 中的原始时间序列或告警状态。

`keep_firing_for` 是 Prometheus 侧的状态保持，`repeat_interval` 是 Alertmanager 侧的通知节流，二者不能互相替代。Alertmanager 集群的 gossip 只协调通知状态，不会复制 Prometheus TSDB。

## v3.16.0 Mechanisms

### v3.16.0 Changes

| 变化 | 状态 | 对使用方式的影响 | 证据 |
| --- | --- | --- | --- |
| `anchored` / `smoothed` 稳定且始终启用 | Stable | 可直接用于支持这些修饰符的函数；`smoothed` 规则仍需 `query_offset` | `CHANGELOG.md:16` |
| extended selector 使用 ST 检测 float counter reset | Experimental | 启用 `use-start-timestamps` 后，边界插值与 reset 判断可使用 Start Timestamp | `CHANGELOG.md:17` |
| 可按查询覆盖 ST 处理 | Experimental | `X-Prometheus-Use-Start-Timestamps` 请求头为单次查询提供开关 | `CHANGELOG.md:12` |
| Agent 支持 `metadata-wal-records` | Experimental | Agent 的专用 WAL 也能保留 metadata 相关记录，但仍需默认关闭的 feature flag | `CHANGELOG.md:13` |
| PromQL 二进制运算透明处理 `__type__` / `__unit__` | Stable | 这两个 metadata 标签不再像普通业务标签一样影响匹配结果 | `CHANGELOG.md:56-58` |
| 修复 Head chunk seek 的查询隔离 | Stable | 查询不再读到建立 querier 之后才提交的样本 | `CHANGELOG.md:36` |
| Remote Write 2.0 移除废弃 metadata 指标 | Compatibility | 旧 dashboard 若依赖这些指标，需要迁移到新的 queue 指标；RW 2.0 协议本身仍是实验规范 | `CHANGELOG.md:9` |

### Experimental Features

以下能力在该版本仍不应按稳定 API 依赖：

| 能力 | 边界 |
| --- | --- |
| `integral()` | 需要 `promql-experimental-functions`，函数名、语法与语义仍可能变化 |
| query cost | 需要 `query-cost`；估算值与执行限额是两套机制 |
| OpenMetrics 2.0 | 解析与性能持续演进，仍需 `openmetrics2` 实验开关 |
| Remote Write 2.0 | 协议与接收端行为仍是实验规范 |
| Start Timestamp storage / use / synthesis | 分别涉及 WAL/chunk 格式、PromQL 与源数据假设，不能只开一个 flag 就认为完整可用 |
| `metadata-wal-records` | server 与 Agent 都支持，但仍是默认关闭的实验 feature flag |
| `convert_nhcb_to_classic` | 转换功能仍为实验；NHCB 本身已稳定，跨系统兼容仍取决于接收端能力 |
| unquoted Unicode metric/label names | 解析器支持受 feature flag 控制；引号写法仍是兼容性更强的选择 |
| `concurrent-rule-eval` | 只并发无依赖规则，依赖检测与调度仍可能变化 |

### Counterintuitive Facts

1. `up=0` 不等于“目标不可达”，协议解析失败、样本超限或 append 失败也会让它变成 0。
2. 失败抓取通常等价于空抓取，会为已跟踪序列补 stale marker，而不是让旧值一直留到 lookback 到期。
3. lookback delta 是查询寻找 instant 样本的窗口，不是 scrape interval，也不是 retention。
4. TSDB 的最小 block duration `2h` 不是固定的出块周期；默认 Head compaction 往往约 3h 才触发。
5. `smoothed` 需要窗口之后的样本，直接在规则中使用通常会低估。
6. Pushgateway 不会让暂存指标自动过期；批处理失败后旧值仍可能被继续抓取。
7. 两个同时抓取同一 target 的 Prometheus 是两份独立数据，不会自动组成复制集群。
8. Remote Read 取回原始样本/chunk，PromQL 仍在本地执行，不是分布式查询下推。
9. Appender batch 不是跨并发 Commit 的强事务，Rollback 也不保证撤销已经创建的 series 与 WAL 记录。
10. Alertmanager 去重解决的是通知身份，不会同步或修复 Prometheus 本地 TSDB 的数据分歧。

## Best Practices

- 指标命名：`namespace_metricname_units`（如 `http_request_duration_seconds`），Counter 以 `_total` 结尾，使用基本单位（seconds、bytes）而非毫秒/KB
- 控制基数（cardinality）：避免无上界的标签（如 user_id、request_id），每个标签组合都是一条独立序列；经验上单实例序列数超过百万即需警惕
- 需要跨实例计算分位数时优先 classic histogram；Summary 的分位数由客户端预计算，不能跨实例可靠聚合
- 仪表板用 Recording Rules 预聚合，告警规则给足 `for` 时间避免抖动；使用 `smoothed` 时同时配置 `query_offset`
- 不要把 Prometheus 当作通用 TSDB 或事件存储使用

### Failure Checklist

| 现象 | 可能的机制 | 优先检查 |
| --- | --- | --- |
| `up=0` | 网络/HTTP 失败、解析失败、样本或标签超限、append 失败 | target 的 last error、响应 `Content-Type`、body/sample/label limits |
| 查询突然无数据 | 指标被 relabel 丢弃、超出 lookback、stale marker、规则输出消失 | `/api/v1/targets`、`/api/v1/status/rules`、原始 selector 与 `up` |
| 告警一直 pending | `for` 未满足、评估不连续、序列 labelset 变化 | `ALERTS_FOR_STATE`、group missed evaluations、模板标签是否稳定 |
| 告警重复通知 | 多副本生成不同 labelset、Alertmanager 分组或集群配置不正确 | `replica`/`cluster` 标签、route、AM 集群成员 |
| 通知丢失 | notifier 批次发送失败、队列丢弃、短暂 resolved 或重启 | `prometheus_notifications_dropped_total`、`prometheus_notifications_queue_length` |
| Recording rule 有空档 | group 执行超时被跳过、规则超限、查询失败 | `prometheus_rule_group_iterations_missed_total`、规则 error、`limit` |
| Remote Write 积压 | 远端不可用、429/5xx、队列或 shard 不足 | `prometheus_remote_storage_samples_pending`、retry/failed 指标、WAL 可回收进度 |
| 写入被拒绝 | 乱序、过旧、未来时间过远、同名标签重复 | OOO window、样本时间戳、label 规范化与 duplicate labels |
| 磁盘持续增长 | Head 尚未物化、compaction 失败、retention 未触发 | `prometheus_tsdb_compactions_failed_total`、block 时间分布、WAL/WBL 大小 |

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)
- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md)
- [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)

## References

1. [Prometheus Overview](https://prometheus.io/docs/introduction/overview/)
2. [Prometheus Release Cycle](https://prometheus.io/docs/introduction/release-cycle/)
3. [Prometheus v3.16.0 Source](https://github.com/prometheus/prometheus/tree/v3.16.0)
4. [Prometheus v3.16.0 Changelog](https://github.com/prometheus/prometheus/blob/v3.16.0/CHANGELOG.md)
5. [Configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
6. [Querying Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)
7. [Query Operators](https://prometheus.io/docs/prometheus/latest/querying/operators/)
8. [Query Functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
9. [HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
10. [Storage](https://prometheus.io/docs/prometheus/latest/storage/)
11. [Recording Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/)
12. [Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
13. [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)
14. [Alert Notifier Implementation](https://github.com/prometheus/prometheus/blob/v3.16.0/notifier/sendloop.go)
15. [Remote Write Specification](https://prometheus.io/docs/specs/remote_write_spec/)
16. [Remote Write 2.0 Specification](https://prometheus.io/docs/specs/remote_write_spec_2_0/)
17. [Native Histograms](https://prometheus.io/docs/specs/native_histograms/)
18. [Feature Flags](https://prometheus.io/docs/prometheus/latest/feature_flags/)
19. [Prometheus Agent Mode](https://prometheus.io/docs/prometheus/latest/prometheus_agent/)
20. [Federation](https://prometheus.io/docs/prometheus/latest/federation/)
21. [Google SRE: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)
