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

## Prometheus Service Discovery (reverse integration)

上面是「Prometheus 抓 Nacos 自己的指标」；3.2.4 还支持**反向**用法——**让 Prometheus 把 Nacos 当作服务发现源**，自动发现注册在 Nacos 里的业务实例并抓取它们。这件事由独立的 `prometheus` 模块（`PrometheusApp` + `PrometheusController`）承担，不是 Actuator：

| 端点 | 起始版本 | 返回 |
| :-- | :-- | :-- |
| `/prometheus` | 2.2.0 | 全命名空间全部实例 |
| `/prometheus/namespaceId/{namespaceId}` | 2.3.0 | 指定命名空间下的实例 |
| `/prometheus/namespaceId/{namespaceId}/service/{service}` | 2.3.0 | 指定服务下的实例 |

返回体是 Prometheus **HTTP SD** 格式的 JSON 数组（由 `PrometheusUtils.assembleArrayNodes` 组装 target 与 label），配置侧用 `http_sd_configs` 消费：

```yaml
scrape_configs:
  - job_name: nacos-sd
    http_sd_configs:
      - url: http://10.0.0.1:8848/prometheus/namespaceId/public
        refresh_interval: 30s
```

> [!NOTE]
> `prometheus` 模块是**独立应用**，自带 `PrometheusAuthFilter` 与 `PrometheusSecurityConfiguration`——开启鉴权后访问这些端点同样要过鉴权，不是在 Nacos 主端口上顺带开放的路径。它与上面 `/nacos/actuator/prometheus` 是两件事：**前者暴露「Nacos 里注册了谁」，后者暴露「Nacos 自己跑得怎么样」**。

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

**客户端侧**（3.2.4 `client/monitor/MetricsMonitor.java`，只有下面这几个）：

| 指标 | 含义 |
| :-- | :-- |
| `nacos_monitor{module="config",name="listenConfigCount"}` | 客户端监听的配置数 |
| `nacos_monitor{module="naming",name="serviceInfoMapSize"}` | 客户端缓存的服务数 |
| `nacos_client_request{module,method,url,code}` | 客户端请求直方图（config / naming） |
| `nacos_client_naming_request_failed_total{module,req_class,res_status,res_code,err_class}` | naming 请求失败计数 |

> [!WARNING]
> 早期文档里常见的客户端指标 **`configListenSize` / `subServiceCount` / `pubServiceCount` 在 3.2.4 全树 0 命中**
> ——正确写法分别是 `listenConfigCount`（配置监听数）与 `serviceInfoMapSize`（服务缓存数）。

> [!WARNING]
> 上表的 `longPolling` 指标字段虽然在 3.2.4 的 `MetricsMonitor` 里还在，但**实际恒为 0**——HTTP 长轮询在 3.x 已是死代码：
> 路由 `configs/listener` 全树 **0 命中**，`ConfigServletInner` **没有任何调用方**（只有它自己和单测引用 `LongPollingService`）。
> v3 的 `/listener` 是**管理员查询「哪些客户端在监听」的接口**（`ConfigControllerV3.getListeners`），不是长轮询端点。
> 所以这条指标不要拿来做告警，见 [config-push](/docs/CS/Framework/nacos/config-push.md)。

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
- **`longConnection` 逼近单机上限**（8C16G 约 9000）：长连接过多，需扩容或限流（[运维与调优](/docs/CS/Framework/nacos/tuning.md) 有 nginx 限流示例与黑名单配置）。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)
- [etcd 监控对照](/docs/CS/Framework/etcd/monitoring.md)

## References

- <https://nacos.io/docs/latest/manual/admin/monitor/>
- <https://nacos.io/zh-cn/docs/monitor-guide.html>
- <https://nacos-group.github.io/en/docs/next/manual/admin/monitor/>
