## Introduction

Beats 是 Elastic Stack 的**轻量数据采集器家族**：Go 编写、基于 libbeat 框架、部署在被监控/产生日志的机器上，资源占用小、无 JVM 依赖，负责把日志、指标、网络流量、审计事件发往 Logstash、Elasticsearch、[Kafka](/docs/CS/MQ/Kafka/Kafka.md) 或 Redis。

它是 Elastic Stack 的"采集端（data shippers）"：与负责解析转换的 Logstash、负责存储检索的 ES、负责可视化的 Kibana 分工协作。其中**日志文件采集**（Filebeat）已独立成篇，见 [Filebeat](/docs/CS/Framework/ES/Filebeat.md)。

> [!IMPORTANT]
> **版本基线：Beats 9.5.5**（2026-10-06 发布，随 Elastic Stack 同步发版）。8.x 仍受支持，但新装建议直接 9.x。

## Beat Family

每个 Beat 只干一件事，按需组合：

| Beat | 采集对象 |
| ---- | ---- |
| [Filebeat](/docs/CS/Framework/ES/Filebeat.md) | 日志文件（最常用）：tail 文件、处理轮转、多行合并 |
| Metricbeat | 指标与运行状态（CPU/内存/磁盘，以及 MySQL、Nginx、K8s 等 module） |
| Packetbeat | 网络抓包，分析 HTTP/MySQL/DNS/Redis 等协议流量 |
| Heartbeat | 主动探测（uptime/可达性/延迟），黑盒监控 |
| Auditbeat | 审计日志、文件完整性监控（FIM） |
| Winlogbeat | Windows 事件日志 |
| Functionbeat | 部署为 serverless 函数采集云事件 |
| Journalbeat | systemd journal（功能多已并入 Filebeat / Elastic Agent） |

## Elastic Agent and Fleet

Elastic 现在主推 **Elastic Agent + Fleet**：单一 agent 统一安装、升级与策略下发，内部仍以各 Beat 为采集底层，并可在管道里做数据加工。选型上，需要策略集中管理、与 Kibana 深度联动的场景用 Elastic Agent；只要轻量 tail 日志、不想引入 Fleet 与策略索引的运维复杂度，独立 Filebeat 仍是更简单的答案。

## Data Shipping and Backpressure

所有 Beat 共享 libbeat 的发布链路：input/harvester 产出事件 → 内部队列 → output 批量发送。libbeat 的 output 是**背压敏感协议（backpressure-sensitive）**：下游（Logstash/ES/Kafka）处理不过来、ACK 变慢时，Beat 自动降低采集/读取速率并暂停发送，未确认事件留在队列中，下游恢复后续传——整条采集链按最慢环节运行，不会把下游压垮。内存队列与磁盘队列的默认值见 [Filebeat](/docs/CS/Framework/ES/Filebeat.md)。

## Typical Ingest Architecture

高可用/大吞吐场景不让业务系统直连 Logstash，而是日志先落本地文件：

```
应用写本地日志文件 -> Filebeat 采集 -> Kafka(消息队列缓冲/削峰) -> Logstash 解析转换 -> Elasticsearch -> Kibana
```

- 日志先落盘，无论到 Logstash 的通路是否顺畅都不会因网络异常丢失；
- Kafka 作为缓冲层解耦采集与处理，吸收流量洪峰，也方便多消费方复用数据；
- Filebeat 部署在每台主机做轻采集，重解析（grok、富化）集中在 Logstash 或 ES ingest pipeline。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)

## References

1. [Beats Platform Reference](https://www.elastic.co/guide/en/beats/libbeat/current/beats-reference.html)
2. [Filebeat Overview](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-overview.html)
3. [Fleet and Elastic Agent Guide](https://www.elastic.co/guide/en/fleet/current/fleet-overview.html)
