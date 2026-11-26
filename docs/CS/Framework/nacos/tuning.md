# Nacos Operations and Tuning

## Introduction

生产环境里 Nacos 最容易被打垮的不是功能，而是**不合理的使用方式**：高频读、热点写、单 client 重试、长连接耗尽。本页集中讲生产面调优。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。端口 8848 / 9848 / 9849 / 7848 未变；3.x 默认鉴权加强（3.3+ Docker 镜像默认开启 Client API 鉴权），接入注意 token，见 [Security](/docs/CS/Framework/nacos/security.md)。

反直觉点：

- **Nacos 自身没有内置细粒度 QPS 限流**：限流与黑名单都在前置 Nginx 做，配在 Nacos 上基本无效。
- 写操作代价比读大得多：同一个配置高频写会触发 MySQL **行锁排队**，最终拖垮整个实例，所以「限制发布配置」比「限制读配置」更关键。
- 长连接上限是**运维经验值**（8C16G 约 9000），不是源码常量；不要当成硬编码阈值。

## Rate Limiting

Nacos 每个接口的代价不同：写 > 读，SDK 调用（高频）> 运维操作（低频）。生产要区别对待，防止错用方打垮服务。

**限制单个接口的 QPS**：`get config` 是低频操作——正常使用只在启动和变更推送时拉取，频繁获取说明 client 错用（如数据平台 failover 重试）。`publish config` 更要限——高频写同一 dataId 会打满 MySQL 行锁。

```nginx
http {
    limit_req_zone $binary_remote_addr zone=perclient:10m rate=10r/s;
    limit_conn_zone $binary_remote_addr zone=perclient_conn:10m;

    server {
        # 单个 client 的所有请求限制在 500 QPS 以内，防重试风暴
        location /nacos/v1/cs/configs {
            limit_req zone=perclient burst=20 nodelay;
        }

        # 写操作单独收紧，并用 lua 取 POST 参数做 limit key
        location /nacos/v1/cs/configs/publish {
            access_by_lua_block {
                ngx.var.limit_key = ngx.var.remote_addr .. ":"
                    .. (ngx.var.arg_dataId or "")
            }
            limit_req zone=perclient burst=5 nodelay;
        }
    }
}
```

**限制 Nacos 服务总 QPS**：Nacos 部署在 Nginx 之后，由 Nginx 兜住进入 Nacos 的流量。

**限制并发连接数**：2.x 起配置监听改走 gRPC（9848）长连接，v1 的 `/cs/configs/listener` HTTP 长轮询在 3.x 已废弃。一般一个 client 一条长连接就够生产用：

- `limit_conn client`：单 client 连接数 ≤ 10。
- `limit_conn server`：单机（8 核 16G）最多约 9000 个长连接（经验值），即可同时服务约 9000 个应用节点。

## Blacklist

**IP 黑名单**：发现错用的 client 影响服务时，用 Nginx 直接限制其访问。按读写分离更精细——只禁写、仍允许读，避免整个应用不可用：

```nginx
# 1 限制，0 不限制
map "$remote_addr" $limit_read {
    #10.2.24.252 1;
    default 0;
}
map "$remote_addr" $limit_write {
    #10.2.24.252 1;
    default 0;
}

server {
    location /nacos/v1/cs/configs/publish {
        if ($limit_write = 1) {
            return 403;
        }
    }
}
```

**应用黑名单**：一个应用通常有多台机器，按 IP 粒度不够。namespace 是区分不同应用的天然维度，可在 namespace 维度做访问限制；配合鉴权插件的权限模型，能直接对应用身份禁用写操作。

## Long Connections and Capacity

- 每个 client 保持**一条** gRPC 长连接即可满足生产，多余连接纯属浪费。
- 单机容量按 8C16G ≈ 9000 条连接规划（经验值，需用真实压测校准）；接近上限时优先扩容节点，而非放泛滥连。
- 监控 `nacos_monitor{module="core",name="longConnection"}` 与 `grpc_server_executor` 的 active / queued，提前预警（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）。
- 节点内存涨 / GC 频繁 / OOM 时，先查连接数，再查配置与服务数据量是否超出单机容量。

## Port Conflict on Windows

Windows 上阿里云盘的 `SyncAppServer.exe` 会占用 9848，导致 Nacos 启动失败。用 `netstat -ano | findstr 9848` 确认后释放端口或调整 `server.port`（偏移端口随之联动）。完整排查见 [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)。

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [Security](/docs/CS/Framework/nacos/security.md)
- [Monitoring](/docs/CS/Framework/nacos/monitoring.md)
- [Troubleshooting](/docs/CS/Framework/nacos/troubleshooting.md)

## References

- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-cluster/>
- <https://nacos.io/docs/latest/manual/admin/monitor/>
