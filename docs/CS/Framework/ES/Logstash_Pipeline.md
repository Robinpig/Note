## Introduction

Logstash 的处理核心是一条 pipeline：`input → queue → filter + output`。这条流水线的三个问题决定了它的全部表现：**事件在队列里等多久**（延迟）、**worker 怎么分批消费**（吞吐）、**消费失败去哪里**（可靠性）。输入输出插件的选型见枢纽页，filter 插件的细节见 [Logstash_Filters](/docs/CS/Framework/ES/Logstash_Filters.md)，本篇讲执行模型与可靠性机制。

> [!IMPORTANT]
> **版本基线：Logstash 9.5.5**（2026-10-06 发布）。以下默认值均以 9.5.5 官方文档为准。

## Execution Model

Logstash 的 pipeline 分三个阶段，input 与 filter+output 之间夹着一个队列：

```
input threads -> queue -> filter + output workers
```

- **input 线程**：各 input 插件在自己的线程里读数据，写入队列，成功后向数据源发 ACK（如 beats input 才确认收到）。
- **worker（filter+output stage）**：多个 worker 线程从队列按批取事件，先跑完该批所有 filter，再执行 output。`pipeline.workers` 默认取 `availableProcessors`（约等于 CPU 核数）。
- **批处理参数**：`pipeline.batch.size` 默认 **125**（一个批的最大事件数）；`pipeline.batch.delay` 默认 **50ms**（不满批时最多等多久）。常驻内存中的事件量约等于 `workers × batch.size`，这是堆内存估算的基线——1GB 默认堆在默认参数下放 8 核 × 125 = 1000 条事件很宽裕，但把 batch.size 调到 4000 就是另一回事了。
- **顺序保证**：`pipeline.ordered` 默认 `auto`——`pipeline.workers` 为 1 时自动保序，多 worker 时不保证事件顺序（换取并行吞吐）。
- **ECS 兼容模式**：`pipeline.ecs_compatibility` 默认 `disabled`（`v1`/`v8` 仍为 beta），供实现了 ECS 兼容模式的插件统一切换字段风格，见 [Logstash_Filters](/docs/CS/Framework/ES/Logstash_Filters.md)。
- **codec** 挂在 input/output 上做编解码（`json`、`plain`、`rubydebug`、`multiline` 等），调试最常用的组合是 `stdout { codec => rubydebug }`。

## Memory Queue and Persistent Queue

默认的**内存队列**是有界的：队列被未 ACK 事件填满时，Logstash 对各 input 施加背压，每个 input 独立响应（beats input 会停止接受新连接），直到 filter/output 消费并 ACK 后自动恢复。

**持久化队列（PQ）**把待处理事件落盘，`queue.type: persisted` 开启，用于重启不丢与更稳的削峰：

| 设置 | 默认值 | 说明 |
| ---- | ---- | ---- |
| `queue.type` | `memory` | 设 `persisted` 启用 PQ |
| `queue.page_capacity` | `64mb` | 单个 page 文件的最大字节，改动只对新页生效 |
| `queue.max_events` | `0`（不限） | 允许堆积的未被读取事件数（官方标注仅供内部测试） |
| `queue.checkpoint.writes` | `1024` | 写入这么多事件强制 checkpoint；设 `1` 换最大持久性，性能代价显著 |
| `queue.checkpoint.acks` | `1024` | ACK 数达阈值强制 checkpoint |
| `queue.checkpoint.interval` | `1000`（ms） | 周期性 checkpoint，**9.1+ 已废弃**，设 `0` 取消 |
| `queue.drain` | 开 | 正常关闭前排空队列再退出 |

PQ 的磁盘结构是 append-only 的 **page 文件序列**：唯一的 head page 追加写，写满后固化为 tail page 并新建 head page；checkpoint 文件记录页状态与 ACK 进度（对 head page `fsync` + 原子写状态文件）。page 内事件全部 ACK 后文件删除，因此含未处理事件的 page 会一直占用 `queue.max_bytes` 容量。

风险点：**被 kill 或硬件故障时，已缓冲但未 checkpoint 的数据会丢失**——PQ 降低丢失窗口，不等于零丢失。

## Dead Letter Queue

PQ 解决"还没处理"，DLQ 解决"永远处理不了"：当 Elasticsearch output 返回 **HTTP 400/404**（不可重试的文档错误）或条件语句求值出错时，事件带着失败元数据进 DLQ。注意 ES 不可达或 5xx 不会进 DLQ——elasticsearch output 会无限重试整个请求。

| 设置 | 默认值 |
| ---- | ---- |
| `dead_letter_queue.enable` | `false` |
| `dead_letter_queue.max_bytes` | `1024mb` |
| `dead_letter_queue.flush_interval` | `5000ms`（不可低于 1000ms） |
| `dead_letter_queue.flush_check_interval` | `1000ms` |

- 落盘位置 `path.data/dead_letter_queue/<pipeline.id>`，段文件顺序编号（`1.log`、`2.log`…）；每条记录含原始事件、失败原因与插件元数据（`plugin_id`/`plugin_type`/`entry_time`）。
- **只支持 Elasticsearch output 与条件语句求值**两类失败。
- 存储必须是本地文件系统，**不支持 NFS**；两个 Logstash 实例不能共用同一个 DLQ 路径。
- 善后：用 `dead_letter_queue` input 插件回读，但它只提交 offset、**不删除**事件；DLQ 不能在运行时清空，需停 pipeline 后删除对应目录。

## Multiple Pipelines

`pipelines.yml` 允许在一个进程里跑多条独立 pipeline，各自指定 `pipeline.id` 与 `path.config`，并可独立覆盖 `pipeline.workers`、`pipeline.batch.size`、`queue.type`：

```yaml
- pipeline.id: main
  path.config: "/etc/logstash/conf.d/*.conf"
- pipeline.id: metrics
  path.config: "/etc/logstash/pipelines/metrics.conf"
  pipeline.workers: 2
```

典型用法是隔离故障域与资源：一类日志的 grok 打满 CPU 时不会拖垮另一条管道。`config.reload.automatic` 默认 `false`，开启后按 `config.reload.interval`（默认 3s）检查并热加载；也可 `SIGHUP` 手动触发。

## Backpressure Across the Chain

从下游到上游，背压是逐级传导的：

```
Elasticsearch 变慢 -> Logstash 队列堆积 -> input 背压 -> beats input 停止接受新连接 -> Filebeat 降速/暂停读取
```

整条采集链按最慢环节运行，这是设计目标而非故障。定位瓶颈时看 Logstash 监控 API 的 `_node/stats/pipelines`（各阶段 events in/out 与队列深度），判断是 filter CPU 不足、output 下游拥塞，还是队列参数不合理。监控 API 默认端口 9600，需 `api.enabled: true`，用法见 [Logstash_Config](/docs/CS/Framework/ES/Logstash_Config.md)。

## Links

- [Logstash](/docs/CS/Framework/ES/Logstash.md)
- [Filebeat](/docs/CS/Framework/ES/Filebeat.md)
- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [Logstash Reference](https://www.elastic.co/guide/en/logstash/current/index.html)
2. [Persistent Queues](https://www.elastic.co/guide/en/logstash/current/persistent-queues.html)
3. [Dead Letter Queues](https://www.elastic.co/guide/en/logstash/current/dead-letter-queues.html)
4. [logstash.yml Settings](https://www.elastic.co/guide/en/logstash/current/logstash-settings-file.html)
