## Introduction

ZooKeeper 提供三层可观测面：**四字命令（Four-letter Words）**、**JMX MBean**、以及 3.6 起官方支持的 **MetricsProvider（Prometheus 等）**。生产上标准做法是把 `mntr` 指标或 Prometheus exporter 接进 Grafana + Alertmanager，对延迟、连接数、watch 数、quorum 状态做持续告警。

本篇列出最该盯的指标与告警规则；节点角色与选举状态来自 [Zab](/docs/CS/Framework/ZooKeeper/Zab.md)，磁盘与快照指标来自 [storage](/docs/CS/Framework/ZooKeeper/storage.md)，排障联动见 [troubleshooting](/docs/CS/Framework/ZooKeeper/troubleshooting.md)。

> [!NOTE]
> 版本基线：四字命令 `mntr` 自 3.4；MetricsProvider（含 Prometheus）自 3.6.0；当前主线 3.9.6。

## 四字命令

通过 `nc` / `telnet` / `socat` 向客户端端口（默认 2181）发一个单词触发：

| 命令 | 作用 |
| :--- | :--- |
| `stat` | 概览：角色、连接数、节点数、延迟、mode |
| `ruok` | 健康检查，正常返回 `imok`（**仅表示进程在，不代表能服务**） |
| `mntr` | 机器可读的详细指标（监控首选） |
| `conf` | 生效配置 |
| `srvr` | 单节点详情（同 stat 不含连接列表） |
| `cons` | 当前连接明细 |
| `wchs` / `wchc` / `wchp` | watch 总数 / 按路径 / 按会话 |
| `dump` | 未完成的会话与临时节点（Leader 专用） |
| `envi` | 环境变量与 JVM 信息 |
| `isro` | 返回 `ro`（只读）/ `rw`（读写） |

> [!WARNING]
> 四字命令在 3.6+ 受 `4lw.commands.whitelist` 控制，未列出的命令会被拒绝；`ruok` 只说明进程活着，**不能替代 quorum / 角色监控**——必须同时看 `mntr` 的 `zk_server_state` 与 `zk_synced_followers`。

## mntr 关键指标

`echo mntr | nc localhost 2181` 输出 `key\tvalue`，重点：

| 指标 | 含义 | 关注点 |
| :--- | :--- | :--- |
| `zk_server_state` | leader / follower / observer | 角色漂移即异常 |
| `zk_znode_count` | 内存节点总数 | 容量上限告警（GB 级内存） |
| `zk_watch_count` | 注册的 watch 总数 | 持续增长 → 客户端泄漏 |
| `zk_ephemerals_count` | 临时节点数 | — |
| `zk_approximate_data_size` | 数据近似大小（字节） | 逼近内存上限危险 |
| `zk_avg_latency` / `zk_max_latency` | 平均 / 最大延迟（ms） | 突增 → 磁盘 fsync / GC |
| `zk_min_latency` | 最小延迟 | — |
| `zk_packets_received` / `zk_packets_sent` | 累计包数 | 流量基线 |
| `zk_outstanding_requests` | 待处理请求数 | 持续 > 0 → 过载 |
| `zk_num_alive_connections` | 存活连接数 | 突增/突降 |
| `zk_open_file_descriptor_count` / `zk_max_file_descriptor_count` | fd 使用 | 逼近 max → 拒绝连接 |
| `zk_followers` / `zk_synced_followers` | Follower 数 / 已同步数 | 不等 → 分裂/落后 |
| `zk_pending_syncs` | 待同步 follower 数 | 高 → Leader 写瓶颈 |
| `zk_commit_count` | commit 次数 | 写吞吐 |
| `zk_heap_used` / `zk_heap_max` | JVM 堆 | GC 压力 |

## JMX

`org.apache.ZooKeeperService` 下暴露 MBean，按角色分：

- `name=StandaloneService` / `name=ReplicatedServer_idN` → `type=Server`：连接数、请求数、延迟。
- `type=Leader` / `type=Follower` / `type=Observer`：角色专属（如 Leader 的 proposal/commit 计数）。
- `type=Connection`：单连接明细。
- `type=DataTree`：`znodeCount`、`watchCount`、`ephemeralsCount`、`approximateDataSize`。

JMX 适合细粒度排查，但长期监控仍以 MetricsProvider 为主。

## MetricsProvider / Prometheus

3.6 起内置 `MetricsProvider` 抽象，官方提供 Prometheus 实现（`zookeeper-prometheus-metrics-provider`），暴露 `/metrics` 端点（默认 7000，或经 AdminServer）。Prometheus 抓取后做 Grafana 面板。

常用派生告警：

- `rate(zk_commit_count[5m])` 陡降 + `zk_outstanding_requests` 升 → 写入卡住。
- `zk_server_state` 在 leader/follower 间频繁切换 → leader 不稳定。
- `zk_synced_followers < zk_followers` → 有 follower 掉队或分裂。
- `zk_watch_count` 单调增长不回落 → 客户端未正常关闭 watch（泄漏）。
- `zk_open_file_descriptor_count / zk_max_file_descriptor_count > 0.85` → 即将拒绝连接。

## AdminServer

默认 `8080` 的 HTTP 管理接口（3.9 起支持快照流式 API 与命令），可经 `zookeeper.admin.serverPort` / `admin.serverInetAddress` 管控，监控外也可作为命令通道（如 `command=metrics`）。安全见 [security](/docs/CS/Framework/ZooKeeper/security.md)。

## 关键告警规则（建议）

| 告警 | 条件 | 可能原因 |
| :--- | :--- | :--- |
| 无 Leader | `zk_server_state` 非 leader/follower（全 observer/standalone 异常） | 选举失败 / quorum 丢失 |
| 高延迟 | `zk_max_latency > 1000ms` 持续 | 磁盘 fsync 慢 / GC / 网络 |
| 待处理堆积 | `zk_outstanding_requests > 阈值` | 过载 / Leader 瓶颈 |
| watch 泄漏 | `zk_watch_count` 持续增长 | 客户端未关闭 |
| fd 紧张 | fd 使用率 > 85% | 连接泄漏 / 上限过低 |
| 数据过大 | `zk_approximate_data_size` 逼近堆 | 超 ZooKeeper 容量（见 [storage](/docs/CS/Framework/ZooKeeper/storage.md)） |

## Links

- [ZooKeeper（架构与数据模型）](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Zab（共识与日志复制）](/docs/CS/Framework/ZooKeeper/Zab.md)
- [存储层 storage](/docs/CS/Framework/ZooKeeper/storage.md)
- [故障排查](/docs/CS/Framework/ZooKeeper/troubleshooting.md)
- [集群运维 cluster](/docs/CS/Framework/ZooKeeper/cluster.md)

## References

1. [ZooKeeper Administrator's Guide: Monitoring](https://zookeeper.apache.org/doc/current/zookeeperAdmin.html#sc_monitoring)
2. [ZooKeeper 3.6 MetricsProvider](https://zookeeper.apache.org/doc/r3.6.0/releaseNotes.html)
3. [Prometheus ZooKeeper Exporter](https://github.com/dabealu/zookeeper-exporter)
