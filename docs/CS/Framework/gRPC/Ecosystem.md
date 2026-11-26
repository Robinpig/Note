# gRPC Java Ecosystem: Interceptors, Discovery, Observability

## Introduction

gRPC 内核只解决"一次调用怎么走完"。真正让它在生产可用的是外围那圈可插拔组件：拦截器负责横切逻辑，命名解析与负载均衡负责寻址，健康检查与反射负责运维接入，网关转译负责协议互通。这些能力大多由 gRFC 规范化，跨语言行为基本一致，但**具体实现与目标字符串格式因语言而异**。本页以 grpc-java 1.75.0 为主。

> 版本基线：grpc-java 1.75.0（commit 3abc0e6）。以下结论均按该 tag 源码核实。

两个反直觉点：

- **服务端 interceptor 越晚注册越靠内**：for 循环逐层包裹，最后注册的 interceptor 最接近业务 handler——与客户端拦截器方向相反。
- **xDS 是"无 sidecar"网格**：gRPC 直接实现 Envoy 控制面协议，proxyless 接入，不需要 sidecar；但它是渐进特性，逐项核对成熟度。

## Interceptors

拦截器是 gRPC 的中间件机制，等价于服务端框架的 Filter 链，分两侧：

- **Client interceptor**：`ClientInterceptors.intercept(channel, interceptors)` 生成 `InterceptorChannel`，包裹 `newCall` 与 `start` / `sendMessage`，注入 metadata、处理状态。
- **Server interceptor**：在 `ServerImpl.wrapMethod` 里逐层包裹 `ServerCallHandler`：

```java
// core/src/main/java/io/grpc/internal/ServerImpl.java
ServerCallHandler<ReqT, RespT> handler = methodDef.getServerCallHandler();
for (ServerInterceptor interceptor : interceptors) {
  handler = InternalServerInterceptors.interceptCallHandlerCreate(interceptor, handler);
}
ServerMethodDefinition<ReqT, RespT> interceptedDef = methodDef.withServerCallHandler(handler);
```

每轮用上一轮的 handler 包当前 interceptor，所以**最后注册的最内层**。典型注入点：认证 token、trace 上下文传播、限流、panic 恢复。

> [!TIP]
> 认证凭据分两层：`CallCredentials`（每次调用携带 token，如 JWT / OAuth）与 TLS `ChannelCredentials`（传输层）。两者可叠加，不要混用概念。Java 侧 `credentials` 包提供 `CallCredentials` / `ChannelCredentials` 抽象类。

## Name Resolution

命名解析把 target 字符串（如 `dns:///my-service:8080`）解析成后端地址 + service config。grpc-java 的 `NameResolverRegistry` 按 scheme 选 `NameResolverProvider`，内置常见实现：`dns`（DNS SRV/A/AAAA）、`unix`（Unix domain socket）、`passthrough`（原样透传）、`xds`（xDS 控制面）。

解析结果 `ResolutionResult` 不只是地址列表——还带 service config（LB 策略、重试、超时参数）。这就是自定义 resolver 比想象中复杂的原因；完整链路见 [LoadBalancing](/docs/CS/Framework/gRPC/LoadBalancing.md)。

## Load Balancing Policies

gRPC 的负载均衡默认在**客户端**完成，与 Nginx/LB 转发路线的根本差异。Java 实现分模块：

| 策略 | 实现位置 | 用途 |
| :--- | :--- | :--- |
| pick_first | core `PickFirstLoadBalancer` | 默认；单 subchannel 顺序尝试全部地址 |
| round_robin | util `RoundRobinLoadBalancer` | 轮询，随机起点 |
| xds / ring_hash / grpclb 等 | gRPC Extensions / xds 模块 | 服务网格、一致性哈希、外部 LB |

默认 `pick_first` 不做真正"均衡"——连上第一个可用后端就一直用；多后端要显式切 `round_robin`。详见 [LoadBalancing](/docs/CS/Framework/gRPC/LoadBalancing.md)。

## xDS and Service Mesh

xDS 是 Envoy 的控制面协议族（LDS / RDS / CDS / EDS 等）。gRPC 直接实现它，从而**无 sidecar** 接入服务网格（"proxyless"）。guava-java 侧相关实现位于 `xds/` 模块，依赖 envoy / cncf 的 xDS proto。xDS 是**渐进特性**：不同语言、版本支持程度不同，生产接入前逐项核对 gRFC 成熟度。

## Observability

可观测性三层：

- **channelz**：gRPC 内建的 channel / subchannel 自省服务，查连接状态、调用计数、socket 信息。排障利器，不适合长期指标存储。
- **OpenTelemetry / census**：Java 侧通过 `census` / OpenCensus 适配层接入 trace / metric，配合 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 等后端。
- **stats handler**：底层事件钩子，拿每次调用的连接、延迟、消息字节数。

## Health Checking and Reflection

两个官方标准服务，属于运维基础设施：

- **`grpc.health.v1.Health`**：标准健康检查服务。Kubernetes gRPC 探针、各类 LB 都认这个接口，不要自己另造 `/healthz`。
- **服务端反射**：`grpc.reflection.v1alpha.ServerReflection`，让客户端在**没有 `.proto` 文件**时探测服务有哪些方法、消息结构。典型用途是 `grpcurl` 调试——应对 HTTP/2 二进制帧不可读的主要手段。生产是否开启要权衡信息暴露风险。

## Transcoding and Gateway

gRPC 的现实问题：浏览器和普通 HTTP 客户端不能直接调。`grpc-gateway` 是主流解法——在 `.proto` 里用 `google.api.http` 注解声明 HTTP 映射，生成反向代理把 HTTP/JSON 转成 gRPC：

```protobuf
service Messaging {
  rpc GetMessage(GetMessageRequest) returns (Message) {
    option (google.api.http) = {
      get: "/v1/messages/{message_id}"
    };
  }
}
```

一份实现同时提供 gRPC 与 RESTful 两种接口。注意 [RESTful](/docs/CS/Distributed/RPC/RESTful.md) 是架构风格、gRPC 是 RPC 实现，两者不在同一抽象层——转译只是让它们在接口层共存。

## Links

- [gRPC](/docs/CS/Framework/gRPC/gRPC.md) — 枢纽：架构与纠偏
- [LoadBalancing](/docs/CS/Framework/gRPC/LoadBalancing.md) — Resolver 与 LB 策略
- [ManagedChannel](/docs/CS/Framework/gRPC/ManagedChannel.md) — Channel 状态机
- [ServerCallChain](/docs/CS/Framework/gRPC/ServerCallChain.md) — 服务端 interceptor 包裹顺序
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 链路追踪后端
- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md) — Java 生态服务治理对照

## References

- [grpc-java v1.75.0 ServerImpl.java](https://github.com/grpc/grpc-java/blob/v1.75.0/core/src/main/java/io/grpc/internal/ServerImpl.java)
- [gRFC: gRPC Load Balancing](https://github.com/grpc/grpc/blob/master/doc/load-balancing.md)
- [gRFC: Health Checking Protocol](https://github.com/grpc/grpc/blob/master/doc/health-checking.md)
- [gRFC: Server Reflection Protocol](https://github.com/grpc/grpc/blob/master/doc/server-reflection.md)
- [grpc-gateway](https://github.com/grpc-ecosystem/grpc-gateway)
- [gRFC A24: Load Balancing Policy Configuration](https://github.com/grpc/grpc/blob/master/doc/service_config.md)
