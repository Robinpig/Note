> [!NOTE]
> 源码事实基于 Netflix/eureka **v1.10.19**，资源类位于 `eureka-core/src/main/java/com/netflix/eureka/resources/`。路径中的 `{version}` 为接口版本段（`v1` / `v2`），部署前缀另行叠加：裸 war 通常为 `/`，Spring Cloud 部署默认为 `/eureka/`。

## Introduction

Eureka Server 本质是一个 Jersey 应用：对外只暴露一组 REST 端点，没有私有的二进制协议。这个「纯 HTTP + JSON/XML」的选择带来两个后果——注册中心可以被任意语言接入（也是 Steeltoe、Go client 存在的前提），但所有流式能力都要靠轮询模拟，推送能力天然缺失。

## Resource Classes

`resources/` 目录下的资源类：

| 资源类                     | 职责                                    |
| :---------------------- | :------------------------------------ |
| `ApplicationsResource`  | 全量注册表、`apps/delta` 增量、按 region 查询     |
| `ApplicationResource`   | 单应用视图、实例注册（POST）、多实例查询                |
| `InstanceResource`      | 单实例的续约、下线、状态覆盖、metadata 更新            |
| `InstancesResource`     | 按 instanceId 反查                       |
| `VIPResource` / `SecureVIPResource` / `AbstractVIPResource` | VIP / SVIP 视图查询   |
| `PeerReplicationResource` | 接收 peer 的批量复制请求                     |
| `ASGResource`           | AWS Auto Scaling Group 批量状态更新         |
| `StatusResource`        | Server 自身状态与 remote region 信息         |
| `ServerInfoResource`    | 状态覆盖快照（`/serverinfo/statusoverrides`） |
| `CurrentRequestVersion` | ThreadLocal，标识当前请求用的是 V1 还是 V2 形状      |

## Endpoint Table

| Verb   | Path                                              | 语义                                                     | 成功码       |
| :----- | :------------------------------------------------ | :----------------------------------------------------- | :-------- |
| GET    | `/{version}/apps`                                 | 全量注册表，支持 `?regions=`，支持 gzip                           | 200       |
| GET    | `/{version}/apps/delta`                           | 增量;`disableDelta` 或不允许访问时 403                          | 200 / 403 |
| POST   | `/{version}/apps/{appId}`                         | 注册实例，Consumes JSON/XML                                 | **204**   |
| GET    | `/{version}/apps/{appId}`                         | 单应用实例列表                                                | 200       |
| GET    | `/{version}/apps/{appId}/{id}`                    | 单实例详情                                                  | 200       |
| PUT    | `/{version}/apps/{appId}/{id}`                    | **续约**（renew），带 `status` / `lastDirtyTimestamp` / 可选 `overriddenstatus` | 200 / **404** |
| DELETE | `/{version}/apps/{appId}/{id}`                    | 下线（cancel）                                             | 200       |
| PUT    | `/{version}/apps/{appId}/{id}/status?value=`      | 状态覆盖（如 `OUT_OF_SERVICE`）                               | 200       |
| DELETE | `/{version}/apps/{appId}/{id}/status?value=&lastDirtyTimestamp=` | 删除状态覆盖                                       | 200       |
| PUT    | `/{version}/apps/{appId}/{id}/metadata`           | 更新 metadata                                            | 200       |
| GET    | `/{version}/instances/{id}`                       | 按 instanceId 反查                                        | 200       |
| GET    | `/{version}/vips/{vipAddress}`                    | VIP 视图                                                 | 200       |
| GET    | `/{version}/svips/{secureVipAddress}`             | SVIP 视图                                                | 200       |
| POST   | `/{version}/peerreplication/batch`                | 批量复制（`ReplicationList` → `ReplicationListResponse`）    | 200       |
| PUT    | `/{version}/asg/{asgName}/status`                 | ASG 批量状态更新                                             | 200       |
| GET    | `/{version}/status`                               | Server 状态                                              | 200       |
| GET    | `/serverinfo/statusoverrides`                     | 当前所有 override（仅 JSON）                                  | 200       |

注册返回 **204 No Content** 而不是 201，是源码里为了向后兼容刻意保留的（注释原文 `// 204 to be backwards compatible`）；客户端 `register()` 也只判定是否等于 204。

## Renew Endpoint

续约是最热的端点，也是唯一会返回「需要重注册」语义的接口：

```java
// resources/InstanceResource.java
@PUT
public Response renewLease(
        @HeaderParam(PeerEurekaNode.HEADER_REPLICATION) String isReplication,
        @QueryParam("overriddenstatus") String overriddenStatus,
        @QueryParam("status") String status,
        @QueryParam("lastDirtyTimestamp") String lastDirtyTimestamp) {
    boolean isFromReplicaNode = "true".equals(isReplication);
    boolean isSuccess = registry.renew(app.getName(), id, isFromReplicaNode);

    // Not found in the registry, immediately ask for a register
    if (!isSuccess) {
        logger.warn("Not Found (Renew): {} - {}", app.getName(), id);
        return Response.status(Status.NOT_FOUND).build();
    }
    if (lastDirtyTimestamp != null && serverConfig.shouldSyncWhenTimestampDiffers()) {
        Response response = this.validateDirtyTimestamp(Long.valueOf(lastDirtyTimestamp), isFromReplicaNode);
        if (response.getStatus() == Status.NOT_FOUND.getStatusCode()
                && (overriddenStatus != null)
                && !(InstanceStatus.UNKNOWN.name().equals(overriddenStatus))
                && isFromReplicaNode) {
            registry.storeOverriddenStatusIfRequired(app.getAppName(), id, InstanceStatus.valueOf(overriddenStatus));
        }
        return response;
    }
    return Response.ok().build();
}
```

两个要点：

1. **404 是一种协议指令**：它告诉客户端「我这儿没有你，请重新注册」。[Client](/docs/CS/Framework/eureka/Client.md?id=续约与重注册) 收到后立刻 `setIsDirtyWithTime()` + `register()`。
2. **`validateDirtyTimestamp` 是冲突仲裁**：Server 侧实例的 `lastDirtyTimestamp` 比请求携带的更旧时，返回 404 迫使对方更新；复制流量（peer 传来）同时会把 `overriddenstatus` 一并落库，从而让 override 状态也能在集群内扩散。

## Client Abstraction

客户端侧把上面这些端点收敛成 `EurekaHttpClient` 接口，运维上排查时可以据此把日志里的路径直接对应到语义：

| 接口方法                          | 实际请求                                                       |
| :---------------------------- | :--------------------------------------------------------- |
| `register(InstanceInfo)`      | POST `apps/{appName}`                                      |
| `cancel(appName, id)`         | DELETE `apps/{appName}/{id}`                               |
| `sendHeartBeat(...)`          | PUT `apps/{appName}/{id}?status=&lastDirtyTimestamp=[&overriddenstatus=]` |
| `statusUpdate(...)`           | PUT `apps/{appName}/{id}/status?value=&lastDirtyTimestamp=` |
| `deleteStatusOverride(...)`   | DELETE `apps/{appName}/{id}/status?lastDirtyTimestamp=`     |
| `getApplications(regions)`    | GET `apps/`                                                |
| `getDelta(regions)`           | GET `apps/delta`                                           |
| `getVip(vip, regions)`        | GET `vips/{vipAddress}`                                    |
| `getSecureVip(svip, regions)` | GET `svips/{secureVipAddress}`                             |
| `getApplication(appName)`     | GET `apps/{appName}`                                       |
| `getInstance(id)`             | GET `instances/{id}`                                       |

传输层的重试、隔离与 fail over 行为见 [Transport](/docs/CS/Framework/eureka/transport.md)。

## Filters and Codecs

裸 war 部署时（`eureka-server/src/main/webapp/WEB-INF/web.xml`）挂在 Servlet 容器上的 Filter：

| Filter                        | 映射                | 作用                                        |
| :---------------------------- | :---------------- | :---------------------------------------- |
| `statusFilter`（`StatusFilter`） | `/*`              | Server 自身未处于 `UP` 时返回 **307**，避免未就绪就对外服务 |
| `requestAuthFilter`（`ServerRequestAuthFilter`） | `/*`  | 基本鉴权钩子                                    |
| `rateLimitingFilter`（`RateLimitingFilter`） | `/v2/apps`、`/v2/apps/*`（**默认注释掉**） | 基于 Bloom filter 的客户端限流 |
| `gzipEncodingEnforcingFilter`（`GZIPContentEncodingFilter`） | `/v2/apps`、`/v2/apps/*` | 强制在响应里手工 gzip（client 不声明 `Accept-Encoding` 也压） |
| `jersey`（Jersey `ServletContainer`） | `/*`      | 分发到各资源类                                   |

序列化由 `ServerCodecs` / `DefaultServerCodecs` 决定：

| 维度     | full            | compact           |
| :----- | :-------------- | :---------------- |
| JSON   | `LegacyJacksonJson` | `JacksonJsonMini` |
| XML    | `XStreamXml`    | `JacksonXmlMini`  |

`compact` 用于给新客户端、「二次压缩」后的小报文，`full` 给 Server 间复制与老客户端；两者都可以通过 `eureka.server.json-codec-name` / `xml-codec-name` 覆盖。[缓存层](/docs/CS/Framework/eureka/cache.md)为「格式 × 视图 × 版本 × accept」的每个组合单独缓存一份字节。

> [!WARNING]
> `XStreamXml` 依赖 XStream 做反序列化，历史上多次出现反序列化相关的 CVE（如 CVE-2021-391xx 系列）。升级时务必同时检查 `xstream` 版本——这一点在 Spring Cloud 侧由依赖管理负责，自行引入 `eureka-core` 时应显式核对。

## Links

- [Eureka](/docs/CS/Framework/eureka/Eureka.md)
- [Client](/docs/CS/Framework/eureka/Client.md)
- [Transport](/docs/CS/Framework/eureka/transport.md)
- [Replication](/docs/CS/Framework/eureka/replication.md)
- [Config](/docs/CS/Framework/eureka/config.md)

## References

1. [Netflix/eureka · resources](https://github.com/Netflix/eureka/tree/v1.10.19/eureka-core/src/main/java/com/netflix/eureka/resources)
2. [Eureka REST operations](https://github.com/Netflix/eureka/wiki/Eureka-REST-operations)
