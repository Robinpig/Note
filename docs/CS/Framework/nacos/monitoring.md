# Nacos Monitoring

## Introduction

Nacos 的监控分两类：**Server 自身指标**（JVM / HTTP / gRPC / 配置 / 服务发现）与 **健康检查端点**（liveness / readiness）。指标通过 Spring Boot Actuator 暴露为 Prometheus 格式，Grafana 做可视化。

注意：默认 `application.properties` 里 Actuator 暴露是**注释状态**，需要显式开启；否则 `/actuator/prometheus` 404。

## Enable Metrics Exposure

每个 Nacos Server 节点在 `application.properties` 开启：

```properties
management.endpoints.web.exposure.include=prometheus
# 若已暴露其他端点，把 prometheus 加入列表即可；不要误写成 include=*
```

重启后访问：

```
http://{nacos-server-host}:8848/nacos/actuator/prometheus
```

`/nacos` 前缀来自默认 `nacos.server.contextPath`；若改了服务端上下文路径，URL 要同步调整。

## Prometheus Scraping

```yaml
scrape_configs:
  - job_name: nacos
    metrics_path: /nacos/actuator/prometheus
    static_configs:
      - targets:
          - 10.0.0.1:8848
          - 10.0.0.2:8848
          - 10.0.0.3:8848
```

端口 / 上下文路径变化就改 `targets` 与 `metrics_path`。Grafana 用 Prometheus 作数据源，社区维护的 Dashboard 模板（nacos-template）可直接导入，分核心监控、曲线、告警三个模块。

## Key Metrics

指标名带 Micrometer 类型后缀（timer 通常导出 `_seconds_count` / `_seconds_sum`），排障先搜基名再看 label。

**配置中心（module=config）**

| 指标 | 含义 |
| :-- | :-- |
| `nacos_monitor{module="config",name="getConfig"}` | 配置查询统计 |
| `nacos_monitor{module="config",name="publish"}` | 配置发布统计 |
| `nacos_monitor{module="config",name="longPolling"}` | 配置长轮询连接数 |
| `nacos_monitor{module="config",name="configCount"}` | 配置总数 |
| `nacos_monitor{module="config",name="notifyTask"}` | 配置通知任务堆积 |
| `nacos_monitor{module="config",name="notifyClientTask"}` | 客户端通知任务堆积 |
| `nacos_monitor{module="config",name="dumpTask"}` | 配置落盘任务堆积 |
| `nacos_timer{module="config",name="notifyRt"}` | 通知时延 |
| `nacos_timer{module="config",name="dumpRt"}` | 落盘时延 |

**服务发现（module=naming）**

| 指标 | 含义 |
| :-- | :-- |
| `nacos_monitor{module="naming",name="serviceCount"}` | 服务数 |
| `nacos_monitor{module="naming",name="ipCount"}` | 实例数 |
| `nacos_monitor{module="naming",name="subscriberCount"}` | 订阅数 |
| `nacos_monitor{module="naming",name="totalPush"}` | 推送总次数 |
| `nacos_monitor{module="naming",name="failedPush"}` | 推送失败数 |
| `nacos_monitor{module="naming",name="avgPushCost"}` | 平均推送时延 |
| `nacos_monitor{module="naming",name="maxPushCost"}` | 最大推送时延 |

**核心与异常**

| 指标 | 含义 |
| :-- | :-- |
| `nacos_monitor{module="core",name="longConnection"}` | 各模块 gRPC 长连接数 |
| `nacos_monitor_summary` | Raft read index / leader read / apply 汇总 |
| `nacos_exception{name="db"}` | 数据库异常 |
| `nacos_exception{name="configNotify"}` | 配置通知失败 |
| `nacos_exception{name="unhealth"}` | 节点间健康异常 |
| `nacos_exception{name="disk"}` | 命名写磁盘异常 |
| `nacos_exception{name="leaderSendBeatFailed"}` | Leader 发心跳失败 |

**请求与 JVM**：`http_server_requests_seconds`（HTTP 次数 / 时延）、`grpc_server_requests`（gRPC 时延，带 requestClass / success / errorCode / module）、`grpc_server_executor`（gRPC 线程池 active / pool / queued）、`system_cpu_usage` / `jvm_memory_used_bytes` / `jvm_gc_pause_seconds_*` / `jvm_threads_daemon`。

客户端侧：`nacos_monitor{name="configListenSize"}`、`subServiceCount` / `pubServiceCount`、`nacos_client_request_seconds_*`。

## 3.x Health Check Interface

适合给负载均衡、K8s 探针、巡检系统用：

| 端点 | 用途 |
| :-- | :-- |
| `/nacos/v3/admin/core/state` | Server 状态总览 |
| `/nacos/v3/admin/core/state/liveness` | 存活探针 |
| `/nacos/v3/admin/core/state/readiness` | 就绪探针 |
| `/v3/console/health/liveness` | 独立 Console 存活 |
| `/v3/console/health/readiness` | 独立 Console 就绪 |

改了 `nacos.server.contextPath` / `nacos.console.contextPath` 要相应调整 URL 前缀。

## Suggested Alert Items

从指标反推「Nacos 是不是要挂了」：

- **`notifyTask` / `dumpTask` 持续上涨**：配置变更堆积，DB 写慢或 dump 线程瓶颈 → 查 DB 与磁盘 IO。
- **`failedPush` 升高 / `avgPushCost` 变大**：服务发现推送跟不上，客户端连接多或网络差 → 看长连接数与 `grpc_server_executor` 队列。
- **`nacos_exception{name="db"}` 非零**：MySQL 异常（连接 / 慢 SQL / 锁）→ 查 MySQL 与连接池。
- **`leaderStatus` 频繁变**：CP 侧 Leader 切换，JRaft 端口 7848 不通或节点抖动 → 见 [JRaft](/docs/CS/Framework/nacos/jraft.md) 与 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)。
- **`longConnection` 逼近单机上限**（8C16G 约 9000）：长连接过多，需扩容或限流（[Nacos](/docs/CS/Framework/nacos/Nacos.md) 的 Tuning 段有 nginx 限流示例）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)
- [etcd 监控对照](/docs/CS/Framework/etcd/monitoring.md)

## References

- <https://nacos.io/docs/latest/manual/admin/monitor/>
- <https://nacos.io/zh-cn/docs/monitor-guide.html>
- <https://nacos-group.github.io/en/docs/next/manual/admin/monitor/>
