## Introduction

Serverless（无服务器计算）是一种云原生的**事件驱动执行模型**：开发者只写函数/业务代码，算力、扩缩容、容错、计费都由平台接管，按实际调用（请求数 / 执行时长 / 内存）计费，而非按预留实例。它常拆为两层：

- **FaaS（Function as a Service）**：函数粒度执行（AWS Lambda、阿里云 FC、Cloudflare Workers），每条事件触发一次冷/热实例。
- **BaaS（Backend as a Service）**：托管化的有状态后端（对象存储、数据库、消息队列、鉴权），函数通过 SDK 直接消费，无需自建服务。

## 核心特征

- **弹性到零**：无流量时实例缩到 0，有请求再拉起；与之相对，容器/虚拟机需常驻。
- **冷启动（Cold Start）**：首次或闲置后调用需下载代码、建运行时（如 JVM/容器）、建连接，延迟显著高于热实例。优化手段：预置并发（provisioned concurrency）、轻量运行时（V8 isolate / WASM）、连接池外置。
- **事件源驱动**：HTTP 网关、消息队列、对象存储上传、定时触发器都是常见 event source，平台负责把事件投递给函数。
- **无状态 + 外部存储**：函数实例不保证持久，状态必须外置到 BaaS（DB / 对象存储 / KV）。

## 与容器 / Kubernetes 的关系

| 维度 | Serverless (FaaS) | 容器 / Kubernetes |
|---|---|---|
| 扩容粒度 | 函数（请求级） | Pod（实例级） |
| 闲置成本 | 缩到 0 | 需常驻 |
| 冷启动 | 明显，需优化 | 镜像拉取也有启动成本 |
| 长任务 | 受超时限制（分钟级） | 任意时长 |
| 运维 | 平台全托管 | 需管集群/节点 |

实践中两者融合：**Knative** 在 Kubernetes 上提供 Serverless 能力（缩到零 + 按请求扩容 + 冷启动优化），既保留 K8s 生态又获得 FaaS 体验。

## 适用与不适

- **适合**：突发流量、事件处理、API 后端、定时任务、边缘轻逻辑。
- **不适合**：超长任务、强状态会话、极低延迟且零抖动、需精细控制运行时的场景（这类用容器/裸金属更稳）。

## Links

- [Cloud](/docs/CS/Cloud/Cloud.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [Distributed](/docs/CS/Distributed/Distributed.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

- [Migrating from Monolithic to Serverless: A FinTech Case Study](https://www.researchgate.net/publication/340681076_Migrating_from_Monolithic_to_Serverless_A_FinTech_Case_Study)
- [The Architecture of Open Source Applications](https://aosabook.org/en)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/)
