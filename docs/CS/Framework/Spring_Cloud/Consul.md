## Introduction

Consul 是一个服务网络解决方案，使团队能够管理跨服务和多云环境及运行时的安全网络连接。
Consul 提供服务发现、基于身份认证、L7 流量管理以及服务间加密。

```shell
consul agent -dev
```

## Architecture
Consul 提供了一个控制平面，使你能够注册、访问和保护部署在网络上的服务。
控制平面是网络基础设施的一部分，它维护一个中央注册中心来跟踪服务及其各自的 IP 地址。

当使用 Consul 的服务网格功能时，Consul 会动态配置请求路径中的 sidecar 和网关代理，使你能够授权服务到服务的连接、
将请求路由到健康的服务实例，以及在不修改服务代码的情况下强制执行 mTLS 加密。
这确保了通信的高性能和可靠性。

![](https://developer.hashicorp.com/_next/image?url=https%3A%2F%2Fcontent.hashicorp.com%2Fapi%2Fassets%3Fproduct%3Dconsul%26version%3Drefs%252Fheads%252Frelease%252F1.19.x%26asset%3Dwebsite%252Fpublic%252Fimg%252Fconsul-arch%252Fconsul-arch-overview-control-plane.svg%26width%3D960%26height%3D540&w=1920&q=75)

## Spring Cloud Consul

Spring Cloud Consul 特性：

- 服务发现：实例可以在 Consul agent 上注册，客户端可以使用 Spring 管理的 bean 发现这些实例
- 支持 Spring Cloud LoadBalancer——Spring Cloud 项目提供的客户端负载均衡器
- 支持 API Gateway——通过 Spring Cloud Gateway 实现的动态路由器和过滤器
- 分布式配置：使用 Consul 的 Key/Value 存储
- 控制总线：使用 Consul Events 的分布式控制事件




## Links


