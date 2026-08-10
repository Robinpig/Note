## Introduction

[Prometheus](https://prometheus.io/) 是一个开源系统监控和告警工具包，最初由 SoundCloud  构建。自 2012 年成立以来，许多公司和组织都采用了 Prometheus，该项目拥有非常活跃的开发者和用户社区。它现在是一个独立的开源项目，不依赖于任何公司进行维护。为了强调这一点，并澄清该项目的治理结构，Prometheus 于 2016 年加入了 云原生计算基金会 ，作为继 Kubernetes  之后的第二个托管项目。



> Prometheus项目与 Kubernetes 项目一样，也来自于 Google 的 Borg 体系，它的原型系统，叫作BorgMon，是一个几乎与 Borg 同时诞生的内部监控系统


Prometheus 采集并将其指标存储为时间序列数据，即指标信息与记录时的时间戳一同存储，此外还可以伴随被称为标签（Label）的可选键值对。


Prometheus 的主要特性包括

多维 数据模型，其时间序列数据由指标名称和键/值对标识
PromQL，一种 灵活的查询语言，用以发挥这种多维度的优势
不依赖分布式存储；单个服务器节点是自治的
时间序列数据采集通过基于 HTTP 的拉取（Pull）模型进行
通过中间网关支持 推送时间序列数据
通过服务发现或静态配置来发现目标
支持多种图形和仪表板展示模式

## Installtion

> [部署Prometheus](https://monaive.gitbook.io/prometheus)

Prometheus受启发于Google的Brogmon监控系统
Prometheus基于Golang开发，可方便进行二进制部署，同时可方便地使用Docker或Kubernetes进行部署 除程序外，仅有单文件配置文件与存储数据，存储数据亦可使用第三方数据库



## Architecture

Prometheus 主要包含下面几个组件：
- Prometheus Server：用于拉取 metrics 信息并将数据存储在时间序列数据库。
- Jobs/exporters：用于暴露已有的第三方服务的 metrics 给 Prometheus Server，比如
- StatsD、Graphite 等，负责数据收集。
- Pushgateway：主要用于短期 jobs，由于这类 jobs 存在时间短，可能在 Prometheus
- Server 来拉取 metrics 信息之前就消失了，所以这类的 jobs 可以直接向 Prometheus
- Server 推送它们的 metrics 信息。
- Alertmanager：用于数据报警。
- Prometheus web UI：负责数据展示

此图展示了 Prometheus 的架构及其部分生态系统组件

![](https://prometheus.ac.cn/assets/docs/architecture.svg)

Prometheus 直接或通过中间 Pushgateway（用于短期任务）从已插桩的任务中抓取指标。它在本地存储所有抓取的样本，并对这些数据运行规则，以从现有数据中聚合和记录新的时间序列，或者生成告警。可以使用 Grafana  或其他 API 消费者来将收集到的数据可视化。





它的工作流程大致是：

- Prometheus Server 定期从配置好的 jobs 或者 exporters 中拉取 metrics 信息，或者
- 接收来自 Pushgateway 发过来的 metrics 信息。
- Prometheus Server 把收集到的 metrics 信息存储到时间序列数据库中，并运行已经定义好的 alert.rules，向 Alertmanager 推送警报。
- Alertmanager 根据配置文件，对接收的警报进行处理，发出告警。
- 通过 Prometheus web UI 进行可视化展示



## Data Model

Prometheus fundamentally stores all data as time series: streams of timestamped values belonging to the same metric and the same set of labeled dimensions.
Besides stored time series, Prometheus may generate temporary derived time series as the result of queries.

Every time series is uniquely identified by its metric name and optional key-value pairs called labels.

The metric name specifies the general feature of a system that is measured (e.g. http_requests_total - the total number of HTTP requests received). 
It may contain ASCII letters and digits, as well as underscores and colons. It must match the regex [a-zA-Z_:][a-zA-Z0-9_:]*.

Note: The colons are reserved for user defined recording rules. 
They should not be used by exporters or direct instrumentation.

## Grafana

Dashboard


| App   | exporter | grafana     |
| ----- | -------- | ----------- |
| MySQL |    prom/mysqld-exporter      | 14057-mysql |
| Redis |      oliver006/redis_exporter    | 11835       |


## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)

## References

1. [Apache HertzBeat](https://github.com/apache/hertzbeat)
2. [Prometheus Notes](https://erdong.site/prometheus-notes/)
