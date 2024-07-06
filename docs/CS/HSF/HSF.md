## Introduction
高速服务框架HSF（High-speed Service Framework），是在阿里巴巴广泛使用的分布式RPC服务框架

HSF连通不同的业务系统，解耦系统间的实现依赖。HSF从分布式应用的层面，统一了服务的发布与调用方式，从而帮助用户更加方便、快速地开发分布式应用，以及提供或使用公共功能模块。HSF为用户屏蔽了分布式领域中的各种复杂技术细节，如远程通讯、序列化实现、性能损耗、同步与异步调用方式的实现等。

> HSF3内核为Dubbo3.

## Architecture


HSF作为一个纯客户端架构的RPC框架，没有服务端集群，所有HSF服务调用均是通过服务消费方（Consumer）与服务提供方（Provider）点对点进行。为了实现整套分布式服务体系，HSF还需要依赖以下外部系统。


![](./img/Architecture.png)





- Provider
服务提供方绑定了12200端口，用于接收请求并提供服务，同时将地址信息发布到地址注册中心。
服务消费方
服务消费者通过地址注册中心订阅服务，根据订阅到的地址信息发起调用，地址注册中心不参与调用。
- ConfigServer
HSF依赖注册中心进行服务发现，如果没有注册中心，HSF只能完成简单的点对点调用。
服务提供端无法将服务信息对外暴露，服务消费端可能已经明确了待调用的服务，但是无法获取该服务。因此注册中心是服务信息的中介，为服务提供了注册与发现的功能。
EDAS持久化配置中心
持久化的配置中心用于存储HSF服务的各种治理规则，HSF客户端在启动的过程中向持久化配置中心订阅服务治理规则，如路由规则、归组规则、权重规则等，从而根据规则对调用过程的选址逻辑进行干预。
EDAS元数据存储中心
元数据指HSF服务对应的方法列表以及参数结构等信息。元数据对HSF的调用过程不会产生影响，因此元数据存储中心是可选的。由于服务运维的便捷性，HSF客户端在启动时会将元数据上报到元数据存储中心，方便服务运维。
EDAS控制台
EDAS控制台打通了服务地址注册中心、持久化配置中心、元数据存储中心等，为用户提供了服务运维功能，包括服务查询、服务治理规则管理等，提高HSF服务研发的效率、运维的便捷性。




Dubbo 3.0实现了和HSF框架的技术统一。在EDAS中，可以便捷地将HSF应用升级为Dubbo 3.0应用。升级之后，HSF应用可沿用原有的开发方式，还可以使用EDAS为Dubbo应用提供的更加完善的服务治理功能。





同步调用
HSF客户端默认以同步调用的方式消费服务，客户端代码需要同步等待返回结果。



泛化调用
对于一般的HSF调用来说，HSF客户端需要依赖服务的二方包，通过依赖二方包中的API进行编程调用，获取返回结果。但是泛化调用不需要依赖服务的二方包，可以发起HSF调用，获取返回结果。在平台型的产品中，泛化调用的方式可以有效减少平台型产品的二方包依赖，实现系统的轻量级运行。
调用链路Filter扩展
HSF内部设计了调用过滤器，能够主动发现用户的调用过滤器扩展点，将其集成到HSF调用链路中，便于扩展方对HSF的请求进行扩展处理





## Links

- [Dubbo](/docs/CS/Java/Dubbo/Dubbo.md)


## References

1. [HSF](https://juejin.cn/post/7381375087205777419)