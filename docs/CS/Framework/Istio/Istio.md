## Introduction



Istio 是一个开源服务网格，它透明地分层到现有的分布式应用程序上。Istio 强大的特性提供了一种统一和更有效的方式来保护、连接和监视服务。 Istio 是实现负载均衡、服务到服务身份验证和监视的路径——只需要很少或不需要更改服务代码。它强大的控制平面带来了重要的特点，包括：

使用 TLS 加密、强身份认证和授权的集群内服务到服务的安全通信
自动负载均衡的 HTTP、gRPC、WebSocket 和 TCP 流量
通过丰富的路由规则、重试、故障转移和故障注入对流量行为进行细粒度控制
一个可插入的策略层和配置 API，支持访问控制、速率限制和配额
对集群内的所有流量（包括集群入口和出口）进行自动度量、日志和跟踪



Istio 由两个部分组成：控制平面和数据平面。

数据平面是业务之间的通信平面。如果没有一个服务网格，网络就无法理解正在发送的流量，也无法根据它是哪种类型的流量， 或者它从谁那里来，到谁那里去做出任何决定。

服务网格使用代理拦截所有的网络流量，允许根据您设置的配置提供广泛的应用程序感知功能。

代理与您在集群中启动的每个服务一起部署，或者与运行在虚拟机上的服务一起运行。

控制平面获取您所需的配置和服务视图，并动态地对代理服务器进行编程，随着规则或环境的变化更新它们。







