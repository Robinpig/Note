## Introduction

Filebeat 是 Elastic Stack 的**轻量日志采集器（log shipper）**：Go 编写、无 JVM 依赖、部署在每台产生日志的主机上，tail 日志文件并把事件发往 Logstash、Elasticsearch、Kafka 或 Redis。它是 [Beats](/docs/CS/Framework/ES/Beats.md) 家族中用量最大的一个，职责边界是"把日志可靠地搬出机器"——解析、富化、路由留给下游的 Logstash 或 ES ingest pipeline。

> [!IMPORTANT]
> **版本基线：Filebeat 9.5.5**（2026-10-06 发布）。本篇默认值均以 9.5.5 官方文档为准；8.x 前的旧默认（`log` input 为主、`file_identity.native`）已变化。

典型链路：应用写本地日志文件 → Filebeat 采集 → Kafka（缓冲削峰）→ Logstash（解析转换）→ Elasticsearch → Kibana。为什么不反过来让 Logstash 直接读文件、或让业务系统直连，见文末 Typical Ingest Architecture。

## Architecture

Filebeat 由三个组件构成：

| 组件 | 职责 |
| ---- | ---- |
| **input**（7.0 前称 prospector） | 管理 harvester 生命周期，按 glob 路径发现文件；每个 input 跑在独立 Go routine |
| **harvester** | 一个文件一个 harvester，逐行读取并发布事件；句柄在 harvester 存活期间保持打开 |
| **registry（注册表）** | 持久化每个文件的状态（唯一标识 + 已读偏移），重启后据此断点续传 |

**harvester 与文件句柄**：文件被删除或改名后，正在读取它的 harvester 仍会继续读到底——副作用是**磁盘空间要等 harvester 关闭才真正释放**（`df` 显示已删文件仍占空间，通常就是这个原因）。默认 `close.on_state_change.inactive: 5m`，文件 5 分钟没有新行才关闭句柄。

**registry 落盘位置**：默认 `${path.data}/registry`（deb/rpm 安装即 `/var/lib/filebeat/registry`），数据落在该目录 `filebeat/` 子目录下（`data.json` + `meta.json`）。`registry.flush` 默认 `1s`——未落盘的注册表更新超过该时长即触发写入，每批事件成功发布后也会更新。**正常关机必定落盘；异常关机后以最后一次落盘为准，未确认的事件会重发。**

### At-Least-Once Delivery

Filebeat 保证事件**至少一次（at-least-once）**投递且不丢数据：输出不可用时持续重试直到被 ACK。关机时默认**不等待**未确认事件（`shutdown_timeout` 可改），因此已发出未 ACK 的事件重启后会重发——**下游必须容忍重复**（消费端幂等，或用文档 `_id` 去重）。

官方声明的两个例外：

1. 日志轮转 + 删除旧文件的速度快于 Filebeat 处理速度，或输出不可用期间文件被删 → 可能丢数据；
2. Linux 上 inode 复用可能让 Filebeat 跳过行——9.x 默认的 fingerprint 文件身份（见下）正是为解决它而设计。

## Inputs

`type: log`（传统 input）与 `type: filestream`（9.x 推荐）。filestream 常用选项：

| 选项 | 默认值 | 说明 |
| ---- | ---- | ---- |
| `prospector.scanner.check_interval` | `10s` | 扫描 `paths` 下新文件的频率，不建议 <1s |
| `prospector.scanner.recursive_glob` | 启用 | `**` 递归匹配子目录 |
| `close.on_state_change.inactive` | `5m` | 文件多久没有新行就关闭 harvester |
| `close.on_state_change.removed` | Linux/macOS 默认关，Windows 默认开 | 文件被删时关闭 harvester |
| `close.on_state_change.renamed` | 关 | 文件被改名时关闭（默认保持打开继续读） |
| `clean_removed` | `true` | 磁盘上已不存在的文件状态从注册表清除 |
| `clean_inactive` | `-1`（禁用） | 不活跃超时后从注册表清除，需配合 `ignore_older` |
| `ignore_older` | `0`（禁用） | 忽略修改时间早于该时长的文件 |
| `backoff.init` / `backoff.max` | `2s` / `10s` | 读到 EOF 后重试的退避间隔 |
| `harvester_limit` | `0`（不限） | 单个 input 同时打开的 harvester 上限 |
| `message_max_bytes` | `10MB` | 单行长度上限 |

### file_identity

文件改名/移动后路径名不足以识别"同一个文件"，Filebeat 靠 `file_identity` 判定：

| 模式 | 状态 |
| ---- | ---- |
| `fingerprint`（文件头 1024 字节哈希） | **9.x 默认**；不依赖文件系统，能识别 copytruncate 轮转，规避 inode 复用导致的重复/跳行 |
| `native`（inode + device ID） | 9.0 之前的默认；LVM 等场景 device ID 会变 |
| `path` | 仅用于文件从不轮转或轮转到 input 范围之外的场景，否则重复采集 |
| `inode_marker` | device ID 频繁变化时用，不支持 Windows |

只支持 `native`/`path` → `fingerprint` 的自动状态迁移，其他变更路径可能造成重复采集；修改 fingerprint 的 offset/length 会触发**全量重新采集**。

### take_over

从 `log` input 或另一个 filestream input 平滑迁移状态，避免换 input 类型或改 ID 后从头重读。9.1+ 语法 `take_over.enabled: true`；接管另一个 filestream 用 `from_ids`。约束：源 input 必须已停止活动；只迁移 input 启动时已存在的文件状态。

## Parsers and Multiline

filestream 用 `parsers` 数组做行级预处理，**顺序可配置**（相比 log input 的改进）：`ndjson`、`multiline`、`syslog`、`container`、`include_message`、`auditd`。

Java 堆栈多行合并示例：

```yaml
filebeat.inputs:
  - type: filestream
    id: my-app-logs
    paths:
      - /var/log/myapp/*.log
    parsers:
      - multiline:
          type: pattern
          pattern: '^\d{4}-\d{2}-\d{2}'
          negate: true
          match: after
```

## Modules

Module 是"采集配置 + 解析规则 + 看板"的一等公民打包：一个 module 由一个或多个 fileset 组成，每个 fileset 自带 Filebeat input 配置（默认路径、多行规则）、Elasticsearch ingest pipeline 定义、字段定义与 Kibana 看板；Filebeat 按环境自动调整并加载到 ES/Kibana。

常用命令：`filebeat modules list` / `enable nginx` / `disable nginx`。注意：修改 module 后 ingest pipeline **不会自动重载**，需要 `filebeat.overwrite_pipelines: true` 并手动重新 setup。代表模块：nginx（access/error）、mysql、system、spring boot（社区）。

## Outputs and Internal Queue

所有 output 共享 libbeat 内部队列，一次只能配一种队列类型：

| 队列 | 关键默认值 |
| ---- | ---- |
| 内存队列 `queue.mem` | `events: 3200`；`flush.min_events: 1600`（legacy，新配置改用 output 的 `bulk_max_size` 控制批量）；`flush.timeout: 10s` |
| 磁盘队列 `queue.disk` | `max_size: 10GB`（必填）；`path: ${path.data}/diskqueue`；segment 大小 = max/10；`read_ahead: 512`；`write_ahead: 2048`；写错误重试 `1s` 起、指数退避至 `30s` |

内存队列满则阻塞插入，直到 output ACK 释放空间；磁盘队列满时按 input 配置**暂停输入或丢弃事件**。下游拥塞时 Filebeat 通过背压敏感协议降速，而不是无限缓冲——这就是"Filebeat 会根据 Logstash 处理速率调整文件读取速度"的机制出处，链路细节见 [Logstash_Pipeline](/docs/CS/Framework/ES/Logstash_Pipeline.md)。

## Typical Ingest Architecture

高可用/大吞吐场景不让业务系统直连 Logstash，而是日志先落本地文件：

```
应用写本地日志文件 -> Filebeat 采集 -> Kafka(消息队列缓冲/削峰) -> Logstash 解析转换 -> Elasticsearch -> Kibana
```

- 日志先落盘：到 Logstash/ES 的通路中断时数据仍在本地，恢复后续传，不因网络抖动丢日志；
- Kafka 解耦采集与处理，吸收流量洪峰，并支持多消费方复用同一份日志；
- Filebeat 每主机轻量采集（Go 进程，内存占用远低于 JVM 上的 Logstash），重解析集中在 Logstash 或 ES ingest pipeline，采集层故障域最小。

## Links

- [Elasticsearch](/docs/CS/Framework/ES/ES.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Kibana](/docs/CS/Framework/ES/Kibana.md)

## References

1. [Filebeat Overview](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-overview.html)
2. [How Filebeat works](https://www.elastic.co/guide/en/beats/filebeat/current/how-filebeat-works.html)
3. [filestream input](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-input-filestream.html)
4. [Configure the internal queue](https://www.elastic.co/guide/en/beats/filebeat/current/configuring-internal-queue.html)
5. [Configure general settings（registry.path / registry.flush）](https://www.elastic.co/guide/en/beats/filebeat/current/configuration-general-options.html)
6. [Filebeat modules](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-modules-overview.html)
