## Introduction

Nacos `/nɑ:kəʊs/` 是 Dynamic Naming and Configuration Service的首字母简称，一个更易于构建云原生应用的动态服务发现、配置管理和服务管理平台 

来源于阿里内部三个产品（Configserver 非持久注册中心， VIPServer 持久化注册中心， Diamond 配置中心 最早⼀个产品逐步演化成 3 个产品的）   

Nacos 支持将注册中心(Service Registry）与配置中心(Config Center) 在一个进程合并部署或者将2者分离部署的两种模式


服务（Service）是 Nacos 世界的一等公民。Nacos 支持几乎所有主流类型的“服务”的发现、配置和管理

Nacos 的关键特性包括:

- **Service Discovery And Service Health Check**
  Nacos supports both DNS-based and RPC-based (Dubbo/gRPC) [service discovery](/docs/CS/Java/Spring_Cloud/nacos/registry.md). 
  After a service provider registers a service with native, OpenAPI, or a dedicated agent, a consumer can discover the service with either DNS or HTTP.
  Nacos provides real-time health check to prevent services from sending requests to unhealthy hosts or service instances. 
  Nacos supports both transport layer (PING or TCP) health check and application layer (such as HTTP, Redis, MySQL, and user-defined protocol) health check. 
  For the health check of complex clouds and network topologies(such as VPC, Edge Service etc), Nacos provides both agent mode and server mode health check. 
  Nacos also provide a unity service health dashboard to help you manage the availability and traffic of services.
- **Dynamic configuration management**
  [Dynamic configuration](/docs/CS/Java/Spring_Cloud/nacos/config.md) service allows you to manage the configuration of all applications and services in a centralized, externalized and dynamic manner across all environments.
  Dynamic configuration eliminates the need to redeploy applications and services when configurations are updated.
  Centralized management of configuration makes it more convenient for you to achieve stateless services and elastic expansion of service instances on-demand.
  Nacos provides an easy-to-use UI (DEMO) to help you manage all of your application or services's configurations. 
  It provides some out-of-box features including configuration version tracking, canary/beta release, configuration rollback, and client configuration update status tracking to ensure the safety and control the risk of configuration change.

- **Dynamic DNS service**
  Dynamic DNS service which supports weighted routing makes it easier for you to implement mid-tier load balancing, flexible routing policies, traffic control, and simple DNS resolution services in your production environment within your data center. 
  Dynamic DNS service makes it easier for you to implement DNS-based Service discovery.
  Nacos provides some simple DNS APIs TODO for you to manage your DNS domain names and IPs.
- **Service governance and metadata management**
  Nacos allows you to manage all of your services and metadata from the perspective of a microservices platform builder. 
  This includes managing service description, life cycle, service static dependencies analysis, service health status, service traffic management，routing and security rules, service SLA, and first line metrics.



Run and Debug

```shell
git clone https://github.com/alibaba/nacos.git
cd nacos/
# -Drat.skip=true 
mvn -Prelease-nacos -Dmaven.test.skip=true clean install -U  
ls -al distribution/target/

// change the $version to your actual path
cd distribution/target/nacos-server-$version/nacos/bin
```

Run Nacos.java file in module nacos-console with VM options `-Dnacos.standalone=true`

> [!TIP]
>
> Windows下编译太困难 在protobuf上

## Architecture

整体架构分为用户层、 业务层、 内核层和插件， 用户层主要解决用户使用的易用性问题， 业务层主要解决服务发现和配置管理的功能问题， 内核层解决分布式系统⼀致性、 存储、 高可用等核心问题，插件解决扩展性问题。  

![](./img/Architecture.png)

采⽤了阿⾥巴巴内部⾃研的 Distro 协议来实现数据弱⼀致性同步。其中所有节点都将存储集群内所有服务元数据，因此都可以提供数据读取服务，但每个节点只负责⼀部分客户端的数据写服务



## Service Registry



 


## Config





## Consistency


### JRaft

A concrete implementation of CP protocol: JRaft.

```java
/**
 * <pre>
 *                                           ┌──────────────────────┐
 *            ┌──────────────────────┐       │                      ▼
 *            │   ProtocolManager    │       │        ┌───────────────────────────┐
 *            └──────────────────────┘       │        │for p in [LogProcessor4CP] │
 *                        │                  │        └───────────────────────────┘
 *                        ▼                  │                      │
 *      ┌──────────────────────────────────┐ │                      ▼
 *      │    discovery LogProcessor4CP     │ │             ┌─────────────────┐
 *      └──────────────────────────────────┘ │             │  get p.group()  │
 *                        │                  │             └─────────────────┘
 *                        ▼                  │                      │
 *                 ┌─────────────┐           │                      │
 *                 │ RaftConfig  │           │                      ▼
 *                 └─────────────┘           │      ┌──────────────────────────────┐
 *                        │                  │      │  create raft group service   │
 *                        ▼                  │      └──────────────────────────────┘
 *              ┌──────────────────┐         │
 *              │  JRaftProtocol   │         │
 *              └──────────────────┘         │
 *                        │                  │
 *                     init()                │
 *                        │                  │
 *                        ▼                  │
 *               ┌─────────────────┐         │
 *               │   JRaftServer   │         │
 *               └─────────────────┘         │
 *                        │                  │
 *                        │                  │
 *                        ▼                  │
 *             ┌────────────────────┐        │
 *             │JRaftServer.start() │        │
 *             └────────────────────┘        │
 *                        │                  │
 *                        └──────────────────┘
 * </pre>
 *
 */
```




## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)

## References
1. [Quick Start for Nacos Spring Boot Projects](https://nacos.io/en-us/docs/quick-start-spring-boot.html)