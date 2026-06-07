## Introduction

[Serf](https://www.serf.io/) 依赖高效且轻量的 gossip 协议与节点通信。
Serf 代理定期相互交换消息，其方式与僵尸末日爆发类似：从一个僵尸开始，但很快感染所有人。
在实践中，gossip 协议非常快速且极其高效。

Serf 使用的 gossip 协议基于 [SWIM](https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf) 协议的修改版本。

Serf vs. Consul

Consul 是一个用于服务发现和配置的工具。
它提供服务发现、健康检查和键值存储等高级功能，并利用一组强一致的服务器来管理数据中心。

Serf 也可用于服务发现和编排，但它建立在最终一致的 gossip 模型之上，没有中心化服务器。
它提供了组成员管理、故障检测、事件广播和查询机制等功能。
然而，Serf 不提供 Consul 的任何高级功能。
