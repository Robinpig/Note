## Introduction

Sentinel 是面向分布式、多语言异构化服务架构的流量治理组件，主要以流量为切入点，从流量路由、流量控制、流量整形、熔断降级、系统自适应过载保护、热点流量防护等多个维度来帮助开发者保障微服务的稳定性。

- core
- dashboard
- adapter
- cluster
- transport
- extension



### Quick Start

1. Run [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)

2. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)

```xml
<dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-sentinel</artifactId>
    <version>x.y.z.RELEASE</version>
</dependency>
```

```properties


spring.cloud.sentinel.transport.dashboard = localhost:8080
```

3. Test using JMeter

- [How Sentinel works](/docs/CS/Java/Spring_Cloud/Sentinel)
- [CircuitBreaker](/docs/CS/Java/Spring_Cloud/Sentinel/CircuitBreaker.md)







## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)


## References

1. [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
2. [Quick Start](https://sentinelguard.io/en-us/docs/quick-start.html)
