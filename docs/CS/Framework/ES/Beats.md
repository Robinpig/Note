## Introduction

Beats 是 Elastic 推出的一系列**轻量级（Go 编写）、安装在被监控机器上的单一用途数据采集器（data shipper）**。它们资源占用小、部署简单，负责在边缘节点采集日志、指标、运行状态等，再把数据发往 [Logstash](/docs/CS/Framework/ES/Logstash.md)、[Elasticsearch](/docs/CS/Framework/ES/ES.md)、[Kafka](/docs/CS/MQ/Kafka/Kafka.md) 或 Redis（Libbeat output）。

Beats 是“采集端”，与负责解析转换的 Logstash、负责存储检索的 ES、负责可视化的 [Kibana](/docs/CS/Framework/ES/Kibana.md) 共同构成 Elastic Stack（ELK + Beats，也称 Elastic Stack 的 data shippers 层）。

## Beat Family

每个 Beat 只干一件事，可自由组合：

| Beat | 采集对象 |
| ---- | ---- |
| **Filebeat** | 日志文件（最常用），tail 文件、处理轮转、多行合并 |
| Metricbeat | 指标与运行状态（CPU/内存/磁盘，以及 MySQL、Nginx、K8s 等 module） |
| Packetbeat | 网络抓包，分析 HTTP/MySQL/DNS/Redis 等协议流量 |
| Heartbeat | 主动探测（uptime/可达性/延迟），黑盒监控 |
| Auditbeat | 审计日志、文件完整性监控（FIM） |
| Winlogbeat | Windows 事件日志 |
| Functionbeat | 部署为 serverless 函数采集云事件 |
| Journalbeat | systemd journal（现多并入 Filebeat/Elastic Agent） |

新版本中 Elastic 推 **Elastic Agent** + **Fleet** 统一管理各类 Beat（agent 内部以 beat 为底层），但 Filebeat 仍是日志采集主力。

## Filebeat

Filebeat 采集日志的内部模型：

- **Prospector / Input（harvester 的发现者）**：按配置的路径（glob）发现符合的日志文件。
- **Harvester**：每个被采集文件由一个 harvester 负责，逐行读取并发送；文件未读完时 harvester 保持文件句柄（即使文件被删除/重命名，磁盘空间也要等 harvester 关闭才释放）。
- **Registrar（registry）**：记录每个文件已读取的偏移量（offset）到本地注册文件，Filebeat 重启后据此断点续传，保证**至少一次（at-least-once）**投递。
- 内建处理：文件轮转（rotation）识别、多行合并（`multiline`，把 Java 堆栈合成一条事件）、JSON 解析、`include_lines/exclude_lines`、字段与标签。
- **Module**：Filebeat/Metricbeat 提供 Nginx、MySQL、Spring Boot 等预置模块，自带采集配置、ingest pipeline 解析规则与 Kibana 看板。

典型 `filebeat.yml`：

```yaml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/myapp/*.log
    multiline:
      pattern: '^\d{4}-\d{2}-\d{2}'
      negate: true
      match: after

output.kafka:
  hosts: ["kafka:9092"]
  topic: "app-logs"
```

## Backpressure

Filebeat 采用“**背压敏感协议（backpressure-sensitive）**”：当下游（Logstash/Kafka/ES）处理不过来、ACK 变慢时，Filebeat 会自动**降低读取文件的速率**并暂停发送，避免把下游压垮；未确认的事件缓存在内存队列（可溢出到磁盘 queue），下游恢复后再续传。这与主笔记中“Filebeat 会根据 Logstash 处理速率调整文件读取速度”的观察一致。

## Typical Ingest Architecture

高可用/大吞吐场景通常不让业务系统直连 Logstash，而是：

```
应用写本地日志文件 -> Filebeat 采集 -> Kafka(消息队列缓冲/削峰) -> Logstash 解析转换 -> Elasticsearch -> Kibana
```

这样设计的原因：

- 日志先落盘，无论到 Logstash 的通路是否顺畅都不会因网络异常丢失；
- Kafka 作为缓冲层解耦采集与处理，吸收流量洪峰，也方便多消费方复用数据；
- Filebeat 部署在每台主机做轻采集，重解析（grok、富化）集中在 Logstash 或 ES ingest pipeline。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [Beats Platform Reference](https://www.elastic.co/guide/en/beats/libbeat/current/beats-reference.html)
2. [Filebeat Overview](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-overview.html)
3. [Filebeat - How Filebeat works / Registry](https://www.elastic.co/guide/en/beats/filebeat/current/how-filebeat-works.html)
