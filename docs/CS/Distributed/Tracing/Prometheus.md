## Introduction

[Prometheus](https://prometheus.io/) is an open-source systems monitoring and alerting toolkit originally built at SoundCloud.
It is now a standalone open source project and maintained independently of any company.
To emphasize this, and to clarify the project's governance structure, Prometheus joined the Cloud Native Computing Foundation in 2016 as the second hosted project, after Kubernetes.

Prometheus collects and stores its metrics as time series data, i.e. metrics information is stored with the timestamp at which it was recorded, alongside optional key-value pairs called labels.

Prometheus's main features are:

* a multi-dimensional data model with time series data identified by metric name and key/value pairs
* PromQL, a flexible query language to leverage this dimensionality
* no reliance on distributed storage; single server nodes are autonomous
* **time series collection happens via a pull model over HTTP**
* pushing time series is supported via an intermediary gateway
* targets are discovered via service discovery or static configuration
* multiple modes of graphing and dashboarding support


> [部署Prometheus](https://monaive.gitbook.io/prometheus)

Prometheus受启发于Google的Brogmon监控系统
Prometheus基于Golang开发，可方便进行二进制部署，同时可方便地使用Docker或Kubernetes进行部署 除程序外，仅有单文件配置文件与存储数据，存储数据亦可使用第三方数据库

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
