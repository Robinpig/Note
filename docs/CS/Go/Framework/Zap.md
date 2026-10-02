## Introduction

[Zap](https://github.com/uber-go/zap) 是 Uber 开源的 Go 结构化日志库，主打**高性能、零或极低分配（allocation-free）**。
它通过区分「需要极致性能的强类型 API」与「好用的 Sugar API」，在热路径上避免反射与 `interface{}` 装箱，是 Go 服务端（尤其云原生项目，如 etcd、不少 K8s 周边组件）常用的日志方案。

## Logger vs SugaredLogger

Zap 提供两种 logger：

- **Logger（强类型）**：每个字段用类型化方法，无反射、几乎零分配，用在最热的路径：

```go
logger.Info("failed to fetch URL",
    zap.String("url", u),
    zap.Int("attempt", 3),
    zap.Duration("backoff", time.Second),
    zap.Error(err),
)
```

- **SugaredLogger（松散类型）**：支持 `Infof` 格式化与 `key, value` 交替的松散写法，易用但有少量反射开销，适合非热路径：

```go
sugar.Infow("failed to fetch URL", "url", u, "attempt", 3, "error", err)
sugar.Infof("failed to fetch %s", u)
```

二者可用 `logger.Sugar()` 与 `sugar.Desugar()` 互转，可在同一项目里按需混用。

## Structured Logging

- 日志输出是结构化的键值对（生产用 JSON，开发用 Console 人类可读），便于被 [ELK](/docs/CS/Framework/ES/Kibana.md)、Loki 等系统检索、聚合、按字段过滤，而不是 grep 非结构化文本。
- 字段以强类型 `zap.Field` 表示（String/Int/Duration/Time/Error/Any...），这正是它比「`map[string]interface{}` + 反射 marshaling」快的原因。
- 通过 `zap.NewProduction()`/`NewDevelopment()`/`NewExample()` 获得预设（级别、编码、采样、调用者信息），也可用 `zap.New(core, options...)` 自定义 Core。

## Core, Sampling and Context

- **Core**：zap 的核心抽象，组合「编码格式（Encoder）+ 写入目标（WriteSyncer）+ 最低级别」。可以挂多个 Core 实现分流（错误级别额外写一份到告警通道）。
- **采样（Sampling）**：生产 preset 默认开启，同一位置同一级别在单位时间内超过阈值的日志被按比例丢弃，防止错误风暴打爆磁盘/网络——与分布式追踪里「采样」思想相通。
- **调用者与堆栈**：`AddCaller()` 记录产生日志的文件:行，错误级别可 `AddStacktrace()` 附带调用栈。
- **Context 关联**：实践中常把 `trace_id`/`request_id` 通过字段或自定义 Core 注入，使日志能与[分布式追踪](/docs/CS/Distributed/Tracing/Tracing.md)按请求串起来。

## Zap vs log vs slog

| 维度 | Zap | 标准库 log | slog（Go 1.21+） |
| --- | --- | --- | --- |
| 结构化 | 强类型字段，极快 | 否，纯文本 | 结构化，LogValuer |
| 性能 | 零/低分配，业界第一梯队 | 高但无结构 | 良好，handler 决定 |
| 级别 | 丰富且可动态调 | 无级别 | Debug/Info/Warn/Error |
| 生态 | 云原生广泛采用 | 内置 | 标准库新方向，可接 zap handler |

新项目若只想要标准结构化日志，Go 1.21+ 的 `log/slog` 已能满足；需要极致零分配、丰富采样与成熟生态时 Zap 仍是首选。

## Links

- [Golang](/docs/CS/Go/Go.md)
- [Kibana/ELK](/docs/CS/Framework/ES/Kibana.md) — 结构化日志的检索分析侧
- [分布式追踪](/docs/CS/Distributed/Tracing/Tracing.md)

## References

1. [uber-go/zap (GitHub)](https://github.com/uber-go/zap)
2. [Zap FAQ / benchmarks](https://github.com/uber-go/zap/blob/master/FAQ.md)
