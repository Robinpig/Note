## Introduction

gRPC 内核只解决"一次调用怎么走完"。真正让它在生产里可用的是外围那一圈可插拔组件：拦截器负责横切逻辑，命名解析与负载均衡负责寻址，健康检查与反射负责运维接入，网关转译负责协议互通。这些能力大多由 gRFC（gRFC = gRPC 的设计文档流程）规范化，因此跨语言行为基本一致。

## Interceptors

拦截器是 gRPC 的中间件机制，等价于服务端框架的 Filter 链。它分两侧：

- **Client interceptor**：包裹 `Invoke`（unary）与 `NewStream`（stream），在请求发出前注入 metadata、在响应返回后处理状态。
- **Server interceptor**：包裹 handler 执行，可做认证、日志、限流、panic 恢复。

典型注入点是认证凭据（把 token 写进 metadata 的 `authorization` 头）、链路追踪上下文传播，以及统一错误处理。链式写法下，拦截器按注册顺序嵌套，最外层最先执行。

> [!TIP]
>
> 认证凭据在 gRPC 里分两种实现层次：`credentials.PerRPCCredentials` 用于每次调用都携带的 token；TLS 通道则由 `credentials.TransportCredentials` 负责。两者可以叠加，不要混用概念。

## Name Resolution

命名解析把客户端给的目标字符串（如 `dns:///my-service:8080`）解析成一组后端地址。grpc-go 内置：

| Resolver | scheme | 说明 |
| :--- | :--- | :--- |
| DNS | `dns:` | 查询 SRV / A / AAAA 记录，生产最常用 |
| Passthrough | `passthrough:` | 原样传给 dialer，不做解析 |
| Unix | `unix:` | Unix domain socket |
| xDS | `xds:` | 从 xDS 控制面获取配置 |

解析结果不是"地址列表"这么简单——现代 gRPC 里 resolver 还负责产出 **service config**，其中包含负载均衡策略、重试、超时等参数。这也是为什么自定义 resolver 比想象中复杂。

## Load Balancing Policies

gRPC 的负载均衡默认在**客户端**完成，而不是靠代理。这是它与"Nginx/LB 转发"路线的根本差异：客户端自己知道后端列表，直接挑一个建连。

grpc-go v1.84.0 的 `balancer/` 下可见的策略实现：

| 策略 | 包路径 | 用途 |
| :--- | :--- | :--- |
| pick_first | `balancer/pickfirst` | 挑第一个可用后端并粘住，默认策略 |
| round_robin | `balancer/roundrobin` | 轮询，最通用的无状态分发 |
| grpclb | `balancer/grpclb` | 外部负载均衡器查询（早期方案） |
| weighted round robin | `balancer/weightedroundrobin` | 按后端上报的权重/负载加权轮询 |
| weighted target | `balancer/weightedtarget` | 多集群/多目标按比例分流 |
| least request | `balancer/leastrequest` | 挑活跃请求数最少的后端 |
| ring hash | `balancer/ringhash` | 一致性哈希，需要会话黏滞时用 |
| RLS | `balancer/rls` | 路由查找服务，按请求内容路由 |
| endpoint sharding | `balancer/endpointsharding` | 按 endpoint 分片 |

默认策略是 **pick_first**：它并不做真正的"均衡"，而是连上第一个成功解析到的地址就一直用，只有该连接失败才切换。多后端场景下想真正分摊负载，必须显式切到 `round_robin`。这是个高频踩坑点。

## xDS and Service Mesh

xDS 是 Envoy 的控制面协议族（LDS / RDS / CDS / EDS 等），gRPC 直接实现了它，从而可以**无 sidecar** 接入服务网格 —— 这就是所谓的 "proxyless" 服务网格。

在 grpc-go 里，xDS 相关实现位于 `internal/xds/balancer/`（`cdsbalancer`、`clusterimpl`、`clustermanager`），依赖 `github.com/envoyproxy/go-control-plane` 与 `github.com/cncf/xds/go`。从 grpc-java v1.84.0 的 changelog 也能看到 xDS 仍在持续演进：注入自定义 LDS 资源名解析器、支持用 `SocketAddresses` 构造 `XdsServerBuilder`、RLS 的 `stale_header_data` 缓存传播、WRR 的自定义指标名预解析等。

需要留意的是，xDS 在 gRPC 里是**渐进特性**：不同语言、不同版本支持程度不同，生产接入前必须逐项核对 gRFC 的成熟度标记。

## Observability

可观测性有三层，建议按需求取舍：

- **channelz**：gRPC 内建的通道/子通道自省服务，能查到连接状态、调用计数、socket 信息。排障利器，但不适合做长期指标存储。
- **OpenTelemetry 集成**：grpc-go 直接依赖 `go.opentelemetry.io/otel`，把 trace/metric 接到标准生态。配合 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 等后端即可成型。
- **stats handler**：更底层的事件钩子，可以拿到每次调用的连接、延迟、消息字节数。

## Health Checking and Reflection

两个官方标准服务，属于运维基础设施：

- **`grpc.health.v1.Health`**：标准健康检查服务。Kubernetes 的 gRPC 探针、各类 LB 都认这个接口，不要自己另造一个 `/healthz`。
- **服务端反射**（`grpc.reflection.v1alpha.ServerReflection`）：让客户端在**没有 `.proto` 文件**的情况下也能探测服务有哪些方法、消息结构如何。典型用途是 `grpcurl` 之类的调试工具——这也是应对 HTTP/2 二进制帧不可读的主要手段。生产环境是否开启要权衡信息暴露风险。

## Transcoding and Gateway

gRPC 的一大现实问题是浏览器和普通 HTTP 客户端不能直接调。`grpc-gateway` 是主流解法：在 `.proto` 里用 `google.api.http` 注解声明 HTTP 映射，代码生成器产出一个反向代理，把 HTTP/JSON 请求转成 gRPC 调用。

```protobuf
service Messaging {
  rpc GetMessage(GetMessageRequest) returns (Message) {
    option (google.api.http) = {
      get: "/v1/messages/{message_id}"
    };
  }
}
```

这样一份实现同时对外提供 gRPC 与 RESTful 两种接口，避免了手写双份契约的同步成本。当前 grpc-gateway 版本线为 **v2.32.0**（2026-10），v2.29.0 起支持 Protobuf Edition 2024、v2.31.0 起支持 Edition 2026。

与此相对，[RESTful](/docs/CS/Distributed/RPC/RESTful.md) 是以资源为中心的另一种交互风格，两者并非同一抽象层——gRPC 是 RPC 实现，REST 是架构风格，转译只是让它们在接口层共存。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 框架总览与版本基线
- [gRPC Architecture](/docs/CS/Framework/gRPC/Architecture.md) — 帧映射与 codec
- [gRPC Streaming](/docs/CS/Framework/gRPC/Streaming.md) — 流模式与流控
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 链路追踪后端
- [RESTful](/docs/CS/Distributed/RPC/RESTful.md) — 网关转译的目标风格
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) — Java 生态的服务治理路线对照

## References

1. [gRFC: gRPC Load Balancing](https://github.com/grpc/grpc/blob/master/doc/load-balancing.md)
2. [gRFC: gRPC Name Resolution](https://github.com/grpc/grpc/blob/master/doc/naming.md)
3. [gRFC: Health Checking Protocol](https://github.com/grpc/grpc/blob/master/doc/health-checking.md)
4. [gRFC: Server Reflection Protocol](https://github.com/grpc/grpc/blob/master/doc/server-reflection.md)
5. [grpc-gateway](https://github.com/grpc-ecosystem/grpc-gateway)
6. [gRFC A24: Load Balancing Policy Configuration](https://github.com/grpc/grpc/blob/master/doc/service_config.md)
7. [gRPC-Java v1.84.0 Released](https://groups.google.com/g/grpc-io/c/tndfJa2o8xs)
