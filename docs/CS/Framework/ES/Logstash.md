## Introduction

Logstash 是 Elastic Stack 中的**服务端数据处理管道（ETL / 采集转换引擎）**：JRuby 实现、跑在 JVM 上，从多种 input 接收数据，经过 filter 做解析、富化、转换，再通过 output 写到 Elasticsearch、Kafka 等目的地。它是 ELK 里唯一承担"重解析"的组件，插件生态覆盖几乎所有日志格式。

> [!IMPORTANT]
> **版本基线：Logstash 9.5.5**（2026-10-06 发布，与 Elastic Stack 同步发版）。升级路径与 ES 对齐：8.19 是通往 9.x 的最低起点。

与轻量、部署在每台主机的 [Filebeat](/docs/CS/Framework/ES/Filebeat.md) 分工明确：Filebeat 负责把日志可靠地搬出机器（至少一次投递、背压降速），Logstash 集中部署做复杂解析（grok 正则、GeoIP、富化、条件路由）。典型日志链路：

```
Filebeat -> Kafka(缓冲) -> Logstash(解析转换) -> Elasticsearch -> Kibana
```

业务系统一般不与 Logstash 直连：日志先落本地文件由 Filebeat 收集，可避免网络异常丢数据，也能用 Kafka 削峰。

## Map of This Section

| 专题 | 内容 |
| ---- | ---- |
| [Pipeline：执行模型与可靠性](/docs/CS/Framework/ES/Logstash_Pipeline.md) | input→queue→filter+output 三段模型、worker 与批处理默认值、内存队列 vs 持久化队列（PQ）、死信队列（DLQ）、多 pipeline、整链背压 |
| [Filters：filter 插件与事件模型](/docs/CS/Framework/ES/Logstash_Filters.md) | 事件字段与字段引用、grok/dissect/date/mutate/json/geoip/ruby、条件路由、ECS、filter 排序与性能 |
| [Config：配置、部署与调试](/docs/CS/Framework/ES/Logstash_Config.md) | logstash.yml 关键设置、目录布局、Docker 部署、JVM 堆、配置自检与 rubydebug 调试 |

## Where Logstash Fits

"解析该放在哪一层"是日志链路最常见的选型问题：

| 方案 | 适用场景 |
| ---- | ---- |
| Filebeat `parsers` / processors | 单文件场景的轻量处理：多行合并、JSON 解码、按行过滤，零额外进程 |
| Logstash filter | 跨来源汇聚、复杂 grok、GeoIP 富化、按内容路由到多个 output、对接 JDBC 等特殊 input |
| ES ingest pipeline | 已入 ES 的轻量加工（脚本、enrich processor），省掉一层 JVM 进程 |

经验法则：能在采集端或 ES 内完成的解析不要下沉到 Logstash；需要缓冲、跨源汇聚或多目的地分发时再上 Logstash。三者的容量画像：Filebeat 是 Go 进程（典型几十 MB 内存），Logstash 是 JVM 进程（默认堆 1GB 起），ES ingest pipeline 复用 ES 节点 CPU。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)

## References

1. [Logstash Reference](https://www.elastic.co/guide/en/logstash/current/index.html)
2. [Download Logstash（版本基线 9.5.5）](https://www.elastic.co/downloads/logstash)
