## Introduction

Spring Cloud provides tools for developers to quickly build some of the common patterns in distributed systems 
(e.g. configuration management, service discovery, circuit breakers, intelligent routing, micro-proxy, control bus, one-time tokens, global locks, leadership election, distributed sessions, cluster state).

## Spring Cloud Netflix

### Eureka

- [Eureka](/docs/CS/Java/Spring_Cloud/Eureka.md)
  
### Load Balance

- [Ribbon](/docs/CS/Java/Spring_Cloud/Ribbon.md)
- [Feign](/docs/CS/Java/Spring_Cloud/Feign.md)
- [Hystrix](/docs/CS/Java/Spring_Cloud/Hystrix.md)
- [Zipkin](/docs/CS/Java/Spring_Cloud/zipkin.md)
- [Gateway](/docs/CS/Java/Spring_Cloud/gateway.md)


## Spring Cloud Alibaba

Spring Cloud Alibaba provides a one-stop solution for distributed application development.
It contains all the components required to develop distributed applications, making it easy for you to develop your applications using Spring Cloud.

### Nacos

[Nacos](/docs/CS/Java/Spring_Cloud/nacos/Nacos.md) is an easy-to-use dynamic service discovery, configuration and service management platform for building cloud native applications.


**Nacos: Dynamic *Na*ming and *Co*nfiguration *S*ervice**

[registry](/docs/CS/Java/Spring_Cloud/nacos/registry.md)

### What does it do

Nacos (official site: [nacos.io](https://nacos.io)) is an easy-to-use platform designed for dynamic service discovery and configuration and service management. It helps you to build cloud native applications and microservices platform easily.

Service is a first-class citizen in Nacos. Nacos supports almost all type of services，for example，[Dubbo/gRPC service](https://nacos.io/en-us/docs/use-nacos-with-dubbo.html), [Spring Cloud RESTFul service](https://nacos.io/en-us/docs/use-nacos-with-springcloud.html) or [Kubernetes service](https://nacos.io/en-us/docs/use-nacos-with-kubernetes.html).

Nacos provides four major functions.

- **Service Discovery and Service Health Check**

  Nacos makes it simple for services to register themselves and to discover other services via a DNS or HTTP interface. Nacos also provides real-time health checks of services to prevent sending requests to unhealthy hosts or service instances.

- **Dynamic Configuration Management**

  Dynamic Configuration Service allows you to manage configurations of all services in a centralized and dynamic manner across all environments. Nacos eliminates the need to redeploy applications and services when configurations are updated, which makes configuration changes more efficient and agile.

- **Dynamic DNS Service**

  Nacos supports weighted routing, making it easier for you to implement mid-tier load balancing, flexible routing policies, flow control, and simple DNS resolution services in the production environment within your data center. It helps you to implement DNS-based service discovery easily and prevent applications from coupling to vendor-specific service discovery APIs.

- **Service and MetaData Management**

  Nacos provides an easy-to-use service dashboard to help you manage your services metadata, configuration, kubernetes DNS, service health and metrics statistics.



### Sentinel

[Sentinel](/docs/CS/Java/Spring_Cloud/Sentinel/Sentinel.md) is a powerful flow control component that takes "flow" as the breakthrough point and covers multiple fields including flow control, concurrency limiting, circuit breaking, and adaptive system protection to guarantee the reliability of microservices


### RocketMQ



### Seata




Alibaba Cloud OSS

Alibaba Cloud SchedulerX

Alibaba Cloud SMS


