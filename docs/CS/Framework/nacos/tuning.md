# Nacos Operations and Tuning

## Introduction

生产环境里 Nacos 最容易被打垮的不是功能，而是**不合理的使用方式**：高频读、热点写、单 client 重试、长连接耗尽。本页把 Nacos.md 内联的限流 / 黑名单 / 长连接 / 端口冲突等内容抽出来，集中讲生产面调优。限流主要在 **Nacos 前层的 Nginx** 做（Nacos 自身没有内置细粒度 QPS 限流），黑名单同理。

> [!NOTE]
> 本页以 **3.2.4** 为准做了核对：gRPC 原生端口 9848（client）/ 9849（server 间）、Raft 7848、HTTP 8848 未变；3.x 默认鉴权加强（3.3+ Docker 镜像默认开启 Client API 鉴权），运维接入注意 token，见 [Security](/docs/CS/Framework/nacos/security.md)。

### Rate Limiting



Tomcat限流 maxConnection



Nginx限流





限制qps



Nacos 每个接口执行的代价不尽相同， 般来说写操作代价比读操作大，与此同时还有高频操作和低频操作之分，SDK 调用的接口 般来说是高频接口，容易出现问题，所以在生产环境需要将这些接口区别对待，根据服务自身的实际情况采取合理的限流策略，以防错用方打垮 Nacos 服务。



限制单个接口的请求 QPS

limit get config 对读操作进行限流，正常使用 Nacos 获取动态配置 般就启动和运行时修改配置推送到 client，获取配置相对来说是低频操作，如果频繁获取配置肯定是 client 有错用或者应用不正常（比如数据平台任务 failover 重试任务）。



limit publish config 对写操作进行限流，可以有效防止热点写问题。对同 个数据的高频写会触发 mysql 的行锁，从而导致 mysql 的多线程任务因等待行锁排队，最终导致 mysql 所有操作都超时服务不可用。这里通过 nginx lua 模块获取 post 请求的参数，设置 limit key 。





限制单机访问 QPS

perclient 对单个 client 的所有请求限制低于 500QPS，可以有效防止单台 client 的重试攻击。







限制 Nacos 服务 QPS

perserver 限制整个 Nacos 服务的 QPS，Nacos 的服务部署在 nginx 之后，nginx 可以保证到达

Nacos 的流量不会打垮 Nacos。



限制并发连接数



/nacos/v1/cs/configs/listener 接口在 2.x 是长连接通道；3.x 主通道已改为 gRPC（9848）长连接，旧的 HTTP 长轮询监听已废弃。长连接， 般来说， 个 client 个长连接就可以满足生产需求。limit conn client 限制 client 的连接数不超过 10 个，limit conn server限制 Nacos 单机（8 核 16 G 内存）支撑最多 9000 个长连接，最多可以同时服务 9000 个应用节点。



黑名单

1、 P 黑名单

当生产环境发现有错用的 client 影响到 Nacos 服务，可以使用 nginx 黑名单限制 client 的访问。



读写黑名单分离

有时候通过 P 维度直接限制 client 访问所有 Nacos 接口粒度过大，会导致应用服务不可用，可以将读操作和写操作分开，禁止 client 写 Nacos，依然允许其进行读。

```shell
# 1 limit read, 0 no limit
map "$remote addr" $limit read {
#10.2.24.252 1;
default 0;
}
# 1 limit write, 0 no limit
map "$remote addr" $limit write {
#10.2.24.252 1;
default 0;
}
location /some url to write {
if ($limit write = 1) {
return 403;
}
}
```



应用黑名单

P 黑名单功能是 nginx 提供的基础能力，能够限制某些 P 的访问，但是 般 个应用会有很多台机器，当 个应用出问题的时候，会有很多 P 访问都有问题，通过 P 的维度来限制访问达不到预期，需要有应用的维度来限制。

namespace（命名空间）是 个可以区分不同应用的维度，不同的应用 般会使用不同的 namespace，这样可以在 namespace 维度对服务的访问进行限制。





Windows下阿里云盘的SyncAppServer.exe占用了端口9848导致启动失败

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Security（鉴权与 RBAC）](/docs/CS/Framework/nacos/security.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/nacos/troubleshooting.md)
- [etcd 横向对照](/docs/CS/Framework/etcd/compare.md)

## References

- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-cluster/>
- <https://nacos.io/docs/latest/manual/admin/monitor/>
