## Introduction

Logstash 是 Elastic Stack 中的**服务端数据处理管道（ETL/采集转换引擎，JRuby 实现、跑在 JVM 上）**。它从多种 input 接收数据，经过 filter 做解析、富化、转换，再通过 output 写到 ES、Kafka 等目的地。

与轻量、部署在每台主机的 [Beats](/docs/CS/Framework/ES/Beats.md) 不同，Logstash 功能强但更重，通常**集中部署**承担复杂解析（grok 正则、GeoIP、富化、条件路由）。典型日志链路是：

```
Filebeat -> Kafka(缓冲) -> Logstash(解析转换) -> Elasticsearch -> Kibana
```

业务系统一般不与 Logstash 直连：日志先落本地文件由 Filebeat 收集，可避免网络异常丢数据，也能用 Kafka 削峰。

## Pipeline

Logstash 的核心是一条 pipeline，由三段插件组成：

- **input**：数据来源，如 `beats`（接收 Filebeat）、`kafka`、`file`、`http`、`tcp`、`syslog`。
- **filter**：逐条事件处理，是 Logstash 的重心。
- **output**：目的地，如 `elasticsearch`、`kafka`、`file`、`stdout`（调试）。

```ruby
input {
  beats { port => 5044 }
}

filter {
  grok { match => { "message" => "%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level} %{GREEDYDATA:msg}" } }
  date { match => ["ts", "ISO8601"]; target => "@timestamp" }
  mutate { remove_field => ["message", "ecs", "agent"] }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "app-logs-%{+YYYY.MM.dd}"
  }
}
```

### Common Filters

| 插件 | 作用 |
| ---- | ---- |
| `grok` | 用预设正则模式把非结构化文本拆成字段（日志解析核心，出错可用 Kibana Grok Debugger） |
| `date` | 把字符串时间解析为事件 `@timestamp`（否则默认是 Logstash 收到的时间） |
| `mutate` | 重命名、类型转换、增删字段、gsub、split |
| `json` | 解析 JSON 日志行 |
| `dissect` | 用分隔符做比 grok 更轻量的切分（性能更好） |
| `geoip` | 根据 IP 补地理位置字段 |
| `ruby` | 内嵌 Ruby 做复杂自定义逻辑（慎用，性能/稳定性代价） |
| `if/else` | 按条件走不同分支 |

事件是一个类哈希对象，含 `@timestamp`、`@version`、`tags`、`type` 以及解析出的字段；解析失败常往 `tags` 里加 `_grokparsefailure`，可据此分流到死信。

## Persistence and Backpressure

- Logstash pipeline 内部有有界队列，默认在内存；可开启 **persistent queue（PQ）** 把待处理事件落盘，重启不丢、削峰更稳。
- 当 output（如 ES）变慢时，队列堆积反压到 input，Logstash 会降低拉取速率（与 Filebeat 的背压机制配合，整条链路按最慢环节运行）。
- 高吞吐下可用多个 pipeline 实例/worker（`pipeline.workers`，默认约等于 CPU 核数）、调整 `batch.size` 与 `flush_size`，并把重解析尽量下沉到 ES ingest pipeline 或 Filebeat module。

## Install

参考官方 [Running Logstash on Docker](https://www.elastic.co/guide/en/logstash/current/docker.html)。

Docker 运行时有一个关键点：`logstash.conf` 里 ES 的地址**不能用 `localhost`**——容器内的 localhost 指向 Logstash 容器自身，而不是宿主机或 ES 容器。应使用同一 docker 网络中的**容器名/服务名**（如 `http://elasticsearch:9200`），通过 `--net` 让它们互通：

```shell
docker run --rm -it --net elastic \
  -v /Users/robin/Projects/elk/logstash/config/logstash.yml:/usr/share/logstash/config/logstash.yml \
  -v /Users/robin/Projects/elk/logstash/config/logstash.conf:/usr/share/logstash/pipeline/logstash.conf \
  docker.elastic.co/logstash/logstash:8.15.3
```

> 上面把原命令里的全角破折号修正成了标准的 `--rm` / `--net`。版本建议与 ES/Kibana 大版本对齐（这里 8.15.3）。

调试小技巧：开发期把 output 暂时设为 `stdout { codec => rubydebug }`，可在控制台看到每条事件解析后的完整字段，快速验证 grok 是否正确。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Beats](/docs/CS/Framework/ES/Beats.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [Logstash Reference](https://www.elastic.co/guide/en/logstash/current/index.html)
2. [Logstash - Persistent Queues](https://www.elastic.co/guide/en/logstash/current/persistent-queues.html)
3. [Running Logstash on Docker](https://www.elastic.co/guide/en/logstash/current/docker.html)
4. [Grok filter plugin](https://www.elastic.co/guide/en/logstash/current/plugins-filters-grok.html)
