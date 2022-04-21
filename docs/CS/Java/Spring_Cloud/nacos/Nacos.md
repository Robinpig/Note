## Introduction

Nacos is an easy-to-use dynamic service discovery, configuration and service management platform for building cloud native applications


Service is a first-class citizen in Nacos. Nacos supports discovering, configuring, and managing almost all types of services:


Key features of Nacos:

### Service Discovery And Service Health Check

Nacos supports both DNS-based and RPC-based (Dubbo/gRPC) [service discovery](/docs/CS/Java/Spring_Cloud/nacos/registry.md). 
After a service provider registers a service with native, OpenAPI, or a dedicated agent, a consumer can discover the service with either DNS or HTTP.

Nacos provides real-time health check to prevent services from sending requests to unhealthy hosts or service instances. 
Nacos supports both transport layer (PING or TCP) health check and application layer (such as HTTP, Redis, MySQL, and user-defined protocol) health check. 
For the health check of complex clouds and network topologies(such as VPC, Edge Service etc), Nacos provides both agent mode and server mode health check. 
Nacos also provide a unity service health dashboard to help you manage the availability and traffic of services.

### Dynamic configuration management

[Dynamic configuration](/docs/CS/Java/Spring_Cloud/nacos/config.md) service allows you to manage the configuration of all applications and services in a centralized, externalized and dynamic manner across all environments.

Dynamic configuration eliminates the need to redeploy applications and services when configurations are updated.

Centralized management of configuration makes it more convenient for you to achieve stateless services and elastic expansion of service instances on-demand.

Nacos provides an easy-to-use UI (DEMO) to help you manage all of your application or services's configurations. 
It provides some out-of-box features including configuration version tracking, canary/beta release, configuration rollback, and client configuration update status tracking to ensure the safety and control the risk of configuration change.

### Dynamic DNS service

Dynamic DNS service which supports weighted routing makes it easier for you to implement mid-tier load balancing, flexible routing policies, traffic control, and simple DNS resolution services in your production environment within your data center. 
Dynamic DNS service makes it easier for you to implement DNS-based Service discovery.

Nacos provides some simple DNS APIs TODO for you to manage your DNS domain names and IPs.

Service governance and metadata management

Nacos allows you to manage all of your services and metadata from the perspective of a microservices platform builder. 
This includes managing service description, life cycle, service static dependencies analysis, service health status, service traffic management，routing and security rules, service SLA, and first line metrics.


## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)

## References
1. [Quick Start for Nacos Spring Boot Projects](https://nacos.io/en-us/docs/quick-start-spring-boot.html)