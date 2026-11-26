# Nacos Troubleshooting

## Introduction

Nacos 的故障大半集中在「端口 / 一致性 / 持久化边界」三个主题——理解 [JRaft](/docs/CS/Framework/nacos/jraft.md) 的 CP 分工与 [Storage](/docs/CS/Framework/nacos/storage.md) 的「AP 内存 vs CP 落库」边界，能直接定位大部分现象。每条按「症状 → 原因 → 修复」给出。

> 版本基线：Nacos 3.2.4（commit 2c587c0）。端口偏移、鉴权键、`/v3` 上下文、数据源属性均按该版本源码核对。

反直觉点：

- 「能调 OpenAPI 但 SDK 注册不了 / 收不到推送」几乎总是 **9848 gRPC 端口**问题，不是 8848。
- 节点重启后部分实例被摘除又回来，是**临时实例走 Distro 内存**的预期行为，不是 bug。
- 3.x 起大量 API 迁到 `/v3`，旧 `/v1` 脚本失效不是服务端坏了；同时建表脚本**已不在 `conf/`**，而在数据源插件 jar 里。

## Port Conflict / Connectivity

**症状**：单节点启动失败，或 SDK 能调 OpenAPI（8848）却注册不了 / 收不到监听推送。

**原因**：Nacos 从 `server.port`（默认 8848）派生一组端口——9848（gRPC 客户端）、9849（gRPC 集群间）、7848（JRaft）。Raft 端口由成员端口减偏移得出：

```java
private static final int DEFAULT_RAFT_OFFSET_PORT = 1000;

public static int calculateRaftPort(Member member) {
    return member.getPort() - DEFAULT_RAFT_OFFSET_PORT;
}
```

任一端口被占用或防火墙拦截都会「半身不遂」。典型踩坑：**Windows 阿里云盘的 `SyncAppServer.exe` 占用 9848** 导致启动失败。

**修复**：

- 检查 9848 / 9849 / 7848 是否被占，释放或改 `server.port`（三个偏移端口随之联动）。
- 防火墙 / 安全组放行 9848（SDK 长连接）与 9849（节点间 gRPC）；集群还要放行 7848（JRaft）。
- 容器 / K8s 部署要把三个端口都映射出来，漏 9848 是最常见的「能起来但客户端连不上」。

## Cluster Member List Inconsistency

**症状**：部分节点看不到新节点，或节点间数据对不上。

**原因**：成员靠 `cluster.conf`（FileConfigMemberLookup，默认）或地址服务器维护。手动改 `cluster.conf` 时若某节点改漏就出现列表分歧；且它必须与 Raft group 的 peers 一致，否则 CP 侧数据不一致。

**修复**：所有节点 `cluster.conf` 内容一致（改完由 `WatchFileCenter` 自动 reload）；规模大改用地址服务器统一管列表；扩缩容同时用运维接口 / `RaftServer` 改 Raft 成员。

## Derby Cannot Be Clustered

**症状**：多节点共用 Derby 启动报错 / 锁冲突（`load derby-schema.sql error` 或 lock）。

**原因**：Derby 是内嵌单文件库，**不支持多节点并发写**；集群必须用外部数据库。

**修复**：切 MySQL / PostgreSQL 等，导入官方建表脚本。

> [!WARNING]
> 两点在 3.x 已变：① 平台属性改为 **`spring.sql.init.platform`**（`spring.datasource.platform` 降级为兼容旧键，常量见 `PersistenceConstant`）；② **建表脚本不在 `conf/`**——3.2.4 的 `distribution/conf/` 已无 `mysql-schema.sql`，脚本随数据源插件分发（`nacos-datasource-plugin-mysql/.../META-INF/mysql-schema.sql`），详见 [Storage](/docs/CS/Framework/nacos/storage.md)。

## 403 invalid token

**症状**：开启鉴权后请求偶发 `403 invalid token`。

**原因**：各节点 `nacos.core.auth.plugin.nacos.token.secret.key` 不一致，或 `server.identity` 不一致，JWT 验签失败。

**修复**：所有节点用**完全相同**的 `token.secret.key`（Base64 解码 ≥ 32 字节）与 `server.identity`；改动 secret 时注意旧 token 有效期内平滑过渡（详见 [Security](/docs/CS/Framework/nacos/security.md)）。

## Config Push Failure / Accumulation

**症状**：客户端收不到配置变更；监控里 `failedPush`、`notifyTask`、`dumpTask` 上涨。

**原因**：

- `notifyTask` 堆积 → 配置变更通知跟不上，常是 DB 慢 / 磁盘 IO 瓶颈。
- `dumpTask` 堆积 → 配置落盘线程瓶颈。
- `failedPush` 升高 → 大量客户端长连接、网络抖动，或单机长连接逼近上限（8C16G 约 9000，运维经验值）。

**修复**：查 MySQL 慢 SQL / 连接池与磁盘 IO；扩 Nacos 节点分摊长连接；前置 Nginx 限流 + 黑名单控制异常 client 的 QPS / 连接数（见 [Tuning](/docs/CS/Framework/nacos/tuning.md)）；必要时限制单 client 连接数（≤10）。

## Distro Loses Instances on Restart

**症状**：重启一台 Nacos，部分服务实例被短暂摘除，随后又回来。

**原因**：**临时实例（ephemeral）走 Distro（AP），只存在内存、不落库**。节点重启内存清空，靠客户端心跳 / 重连重新注册补回——预期行为，不是 bug。

**修复**：滚动重启避免同时下线多节点；若实例「绝不能因重启丢失」，改用**持久实例**（`ephemeral=false`，走 JRaft 落库，写代价更高）；客户端开本地缓存兜底。

## Long-Connection Limit / OOM

**症状**：节点内存涨、GC 频繁，甚至 OOM。

**原因**：gRPC 长连接数过多（每个 client 一条长连接即可满足生产），或没设连接上限。Nacos 自身**没有内置细粒度 QPS 限流**。

**修复**：单机（8C16G）长连接上限约 9000（经验值非源码常量），按客户端规模规划节点数；Nginx 限制单 client 连接数（≤10）与单机总连接；监控 `nacos_monitor{module="core",name="longConnection"}` 提前预警。

## Client / Server Version Mismatch

**症状**：启动报协议错、监听失效、注册异常。

**原因**：客户端与服务端**大版本必须匹配**（2.x 客户端连 2.x/3.x；1.x 客户端连 1.x）。3.x 起 API 上下文迁到 `/v3`。

**修复**：升级服务端时同步核对 Spring Cloud Alibaba 与 Spring Boot 版本矩阵（2025.1.0.0 内置 Nacos Client 3.1.1，且已移除 bootstrap.yml）；全集群服务端版本尽量一致。

## 3.x Context Path Changes

**症状**：原调用 `/nacos/v1/...` 的脚本 / 旧客户端在 3.x 失效。

**原因**：3.x 把大量 API 迁到 `/nacos/v3/...`（如 `/v3/auth/*`、`/v3/admin/core/state`），旧路径逐步废弃。

**修复**：脚本 / 客户端升级到 `/v3`；健康检查改用 `/v3/admin/core/state{/liveness,/readiness}`（见 [Monitoring](/docs/CS/Framework/nacos/monitoring.md)）。

## Quick Reference

| 现象 | 先查 |
| :-- | :-- |
| 启动失败 | 9848/9849/7848 端口占用、防火墙、Derby（集群需切外部库） |
| SDK 连不上但 OpenAPI 通 | 9848 gRPC 端口未映射 / 被拦 |
| 403 invalid token | 各节点 `token.secret.key` / `server.identity` 是否一致 |
| 配置收不到推送 | `notifyTask`/`dumpTask` 堆积、MySQL、长连接上限 |
| 重启丢实例 | 临时实例走 Distro 内存（预期），需持久实例才落库 |
| Leader 频繁切换 | 7848 JRaft 端口不通、节点抖动、磁盘 IO |
| 内存涨 / OOM | 长连接数逼近单机上限，限流 + 扩容 |
| 老脚本失效 | 3.x 已迁移 `/v3` 上下文 |

## Links

- [Nacos](/docs/CS/Framework/nacos/Nacos.md)
- [JRaft](/docs/CS/Framework/nacos/jraft.md)
- [Storage](/docs/CS/Framework/nacos/storage.md)
- [Security](/docs/CS/Framework/nacos/security.md)
- [Monitoring](/docs/CS/Framework/nacos/monitoring.md)

## References

- <https://nacos.io/docs/latest/manual/admin/monitor/>
- <https://nacos.io/docs/latest/manual/admin/deployment/deployment-best-practices>
