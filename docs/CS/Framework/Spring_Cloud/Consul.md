## Introduction

Consul 是 HashiCorp 的服务网络方案，提供**服务发现、健康检查、KV 存储、多数据中心**与基于身份的服务网格能力（mTLS、意图授权）。Spring Cloud Consul 把这些能力包装成 Spring 风格的自动装配：服务注册用一个 `DiscoveryClient`、配置用一组 `PropertySource`、集群事件用 Control Bus，接入方式与 [Eureka](/docs/CS/Framework/eureka/Eureka.md)、[Nacos](/docs/CS/Framework/nacos/Nacos.md) 保持同一套抽象。

一句话定位：**Consul 是带强一致性（Raft）与健康检查的服务目录**，而不仅是注册中心。它的 agent 模型（每个节点跑一个 consul agent，由 agent 负责本机的健康检查与转发）决定了 Spring Cloud Consul 的很多行为细节。

> [!NOTE]
> Spring Cloud Consul 5.0（2025.1 Oakwood）把原先阻塞的 `ecwid-api` 换成了**非阻塞的 Interface Client**，第三方 Consul HTTP 客户端也一并被 Interface Client 取代——调用链更贴合 Framework 7 的声明式 HTTP 客户端模型。

```shell
consul agent -dev
```

## Architecture

Consul 分控制面与数据面：

- **Server 集群**：保存服务目录与健康状态，用 **Raft** 保证一致性，建议 3 或 5 个节点。所有写走 leader。
- **Client agent**：部署在**每个业务节点**上，本身不存数据。它转发请求给 server，并**在本机执行健康检查**——检查由离服务最近的 agent 执行，而不是 server 远程探测，这一设计让检查结果更贴近真实网络拓扑。
- **数据面（可选）**：sidecar proxy 组成服务网格，透明处理 mTLS 与流量治理。Spring Cloud 集成通常用不到这一层。

![](https://developer.hashicorp.com/_next/image?url=https%3A%2F%2Fcontent.hashicorp.com%2Fapi%2Fassets%3Fproduct%3Dconsul%26version%3Drefs%252Fheads%252Frelease%252F1.19.x%26asset%3Dwebsite%252Fpublic%2Fimg%252Fconsul-arch%252Fconsul-arch-overview-control-plane.svg%26width%3D960%26height%3D540&w=1920&q=75)

## Service Discovery

### Registration

引入 starter 后，`ConsulAutoServiceRegistration` 监听 `WebServerInitializedEvent`，在端口就绪的时刻向本机 agent 注册一个服务实例：

```yaml
spring:
  application:
    name: order-service
  cloud:
    consul:
      host: localhost
      port: 8500
      discovery:
        register: true                # 只想调用不想注册时置 false
        instance-id: ${spring.application.name}:${random.value}
        service-name: ${spring.application.name}
        prefer-ip-address: true       # 容器环境下别用 hostname
        health-check-path: /actuator/health
        health-check-interval: 10s
        tags:
          - version=2.0
          - zone=cn-north
```

要点：

- **服务名默认是 `spring.application.name`**，注册项的大小写敏感，Consul 内部一律小写。
- `instance-id` 必须唯一。同一服务多实例若 id 冲突会互相覆盖，表现为"服务列表里时有时无"——这是最常见的注册类故障。
- `tags` 是做流量分层的载体，Spring Cloud [LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md) 的元数据路由与 Gateway 的 predicate 都能消费它。

### Health Check

注册时同时注册一个健康检查。三种模式各有适用面：

| 模式 | 配置 | 适用 |
| :-- | :-- | :-- |
| **HTTP check** | `health-check-path` + interval | 默认且推荐，由 agent 周期性 GET `/actuator/health` |
| **TTL check** | `heartbeat.enabled: true` | 服务每隔一段时间主动上报存活，适合 NAT 后、agent 无法反向访问服务的场景 |
| **Script / TCP** | Consul 侧配置 | 非 HTTP 服务 |

> [!WARNING]
> TTL 模式下 Spring 会启动 `ttlScheduler` 定时上报。**务必保证心跳周期短于 Consul 的 TTL**（框架自动计算，通常取 TTL 的 2/3），一旦心跳线程被业务阻塞超时，服务会被判定 critical 并从健康列表中摘除——表现为偶发的"No instances available"。

健康检查失败时实例会被标记 `critical`，但**不会立刻注销**：Consul 保留一段时间（`DeregisterCriticalServiceAfter`），便于运维观察而非直接丢流量。

### Discovery

消费方拿到的是 `DiscoveryClient` 的实现 `ConsulDiscoveryClient`。真正发起调用时，`DiscoveryClientServiceInstanceListSupplier` 负责拉取实例列表，交给 [LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md) 选出一个实例。

> [!TIP]
> 这一步默认是**每次请求都查一次 agent**（agent 本地有缓存，实际开销很小）。若想进一步减少调用，可以启用缓存 supplier。代价是一致性窗口变大——服务刚下线还会被继续调用一小段时间。这是典型的可用性 vs 一致性权衡，不要盲目开。

## Distributed Configuration

Consul 的 KV 存储可充当配置中心。现代的接入方式是 `spring.config.import`，已取代旧的 bootstrap 上下文：

```yaml
spring:
  config:
    import: "optional:consul:config/application/,consul:config/order-service/"
  cloud:
    consul:
      config:
        format: YAML          # KEY_VALUE / YAML / PROPERTIES / FILES
        prefix: config
        watch:
          enabled: true       # 长轮询监听变更
        profile-separator: '::'
```

行为要点：

- **路径约定**：`config/<应用名>,<profile>/`，同一 key 存在多份时**后面的覆盖前面的**，与 Spring Boot 配置文件的覆盖规则一致。
- **`optional:` 前缀必须有**。不带 optional 时 Consul 不可用会直接导致应用启动失败——生产上大部分场景希望"配置中心挂了仍能用本地兜底配置起来"，属于典型的静默陷阱。
- **Watch 用阻塞查询（blocking query）**实现：请求带上 Consul 的 index，agent 挂起连接直到数据变化或超时，因此没有轮询风暴。
- 变更监听发布 `RefreshEvent`，配合 `@RefreshScope` 或 `ConfigurationPropertiesRebinder` 生效（详见 [Spring Cloud Config](/docs/CS/Framework/Spring_Cloud/Config.md)）。

## Control Bus

`spring-cloud-consul-bus` 用 Consul Event 做分布式控制事件。`/actuator/busrefresh` 向总线发事件，所有节点收到后各自刷新配置，从而**免去逐个调用 refresh 端点**。

注意 Control Bus 只负责"通知发生了某件事"，**不保证业务幂等**——每个节点独立处理，失败节点不会重放事件。要求严格一致的场景应改用 MQ 或 KV 版本号去驱动。

## Multi-Datacenter

Consul 原生支持多数据中心：各 DC 各自一组 server，通过 WAN gossip 互联，**数据不共享**（一个 DC 的 KV 不会复制到另一个）。跨 DC 查询要显式指定 `-datacenter`。

Spring Cloud Consul 默认只连本机 DC。若要跨 DC 调用，通常有两种做法：一是 Gateway 层按 DC 隔离，各 DC 内部自己治理；二是注册时把 DC 信息写进 tags，由 LoadBalancer 的元数据路由优先选同 AZ/DC 实例——后者是延迟更优的常见选择。

## Consul vs Eureka vs Nacos

三者都能做注册发现，选型关键在于**一致性模型与运维配套**：

| 维度 | Consul | Eureka | Nacos |
| :-- | :-- | :-- | :-- |
| 一致性 | **CP**，Raft 强一致 | **AP**，客户端缓存可继续服务 | 支持 AP / CP 切换（Distro / Raft） |
| 健康检查 | agent 本地检查，类型丰富 | 客户端心跳续约 | 心跳 + 主动探测 |
| 配置中心 | 有（KV + watch） | 无，需配合 Config Server | 有，一等公民 |
| 服务体感 | 独立二进制，部署较重 | 纯 Java，轻量 | Java，中等 |
| 适合 | 多语言栈、已有 Consul 基建 | 纯 Java、追求部署简单 | 国产生态、需配置中心一站式 |

> [!NOTE]
> CP 模型的实际含义：leader 选举期间 Consul **不可写**，服务注册会短暂失败。若应用在这期间启动且没有重试机制，会出现"启动时没注册上、之后也不再注册"的故障。生产环境应确保 `spring.cloud.consul.discovery.register` 侧有重试、或用容器平台的重启策略兜底。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring Cloud LoadBalancer](/docs/CS/Framework/Spring_Cloud/LoadBalancer.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Spring Cloud Config](/docs/CS/Framework/Spring_Cloud/Config.md)

## References

1. [Spring Cloud Consul Reference](https://docs.spring.io/spring-cloud-consul/reference/)
2. [HashiCorp Consul Documentation](https://developer.hashicorp.com/consul/docs)
3. [Consul - Consistency Protocol](https://developer.hashicorp.com/consul/docs/architecture/consensus)
