## Introduction

XXL-JOB 的两端通讯是**双向 HTTP + JSON**，没有注册中心、没有长连接、没有消息队列。全部契约收敛为三个接口：

| 接口 | 提供方 | 消费方 | 方法 |
| :--- | :--- | :--- | :--- |
| `ExecutorBiz` | 执行器（Netty 端口） | 调度中心 | `/beat` `/idleBeat` `/trigger` `/kill` `/log` |
| `AdminBiz` | 调度中心（`/api/*`） | 执行器 | `callback` `registry` `registryRemove` |
| `AdminJobBiz` | 调度中心（`/api/*`） | 外部系统 | `addJob` `updateJob` `removeJob` `startJob` `stopJob` `triggerJob` |

两端都用 `xxl-tool` 的 `HttpTool.createClient().proxy(Xxx.class)` 生成动态代理客户端——**同一套机制、同一份 DTO、两个方向**。3.5.0 起自研 xxl-rpc 已完全退出，`ExecutorBizClient` 与 `ShardingUtil` 一起被移进 `com.xxl.job.core.util.deprecated` 包。

源码基线 tag `3.5.0`。触发链路怎么用这些接口见 [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)，注册见 [Registry And Discovery](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md)。

## Protocol

统一约定：

- **POST + JSON**（`Gson` 序列化），请求体非空校验；
- 两个必填 header：`XXL-JOB-ACCESS-TOKEN`、`XXL-JOB-APPNAME`；
- 响应统一包在 `Response<T>` 里（`code` / `msg` / `data`），**HTTP 状态码恒为 200**，业务失败体现在 `code`；
- 状态码沿用 HTTP 语义：`200` 成功、`500` 失败、`502` 超时 / 过载。

`Const` 里定义 header 名：

```java
public static final String XXL_JOB_ACCESS_TOKEN = "XXL-JOB-ACCESS-TOKEN";
public static final String XXL_JOB_APPNAME      = "XXL-JOB-APPNAME";
```

## Downstream: Admin to Executor

调度中心直连执行器的 Netty 端口，五个 URI（`EmbedServer.EmbedHttpServerHandler.dispatchRequest`）：

```java
// valid
if (HttpMethod.POST != httpMethod) {
    return Response.ofFail("invalid request, HttpMethod not support.");
}
if (uri == null || uri.trim().isEmpty()) { ... }

// valid access token
if (StringTool.isBlank(accessToken) || StringTool.isBlank(appname)) {
    return Response.ofFail("invalid request, accessToken or appname is empty.");
}
if (!(accessToken.equals(xxlJobExecutor.getAccessToken())
        && appname.equals(xxlJobExecutor.getAppname()))) {
    return Response.ofFail("invalid request, accessToken or appname invalid.");
}

switch (uri) {
    case "/beat":     return executorBiz.beat();
    case "/idleBeat": return executorBiz.idleBeat(...);
    case "/trigger":  return executorBiz.trigger(...);
    case "/kill":     return executorBiz.kill(...);
    case "/log":      return executorBiz.log(...);
    default:          return Response.ofFail("invalid request, uri-mapping(" + uri + ") not found.");
}
```

| URI | 请求体 | 用途 | 发起方 |
| :--- | :--- | :--- | :--- |
| `/beat` | 无 | 探活 | `FAILOVER` 路由 |
| `/idleBeat` | `{jobId}` | 探忙 | `BUSYOVER` 路由 |
| `/trigger` | `TriggerRequest` | 触发执行 | 触发链路 |
| `/kill` | `KillRequest` | 终止任务 | 管理后台"终止任务" |
| `/log` | `LogRequest` | 按行读日志 | 管理后台"查看执行日志" |

> [!NOTE]
>
> 3.5.0 把 `/run` 更名为 `/trigger`，对应的方法 `ExecutorBiz.run()` 也更名为 `trigger()`，DTO `TriggerParam` → `TriggerRequest`。这是 3.5.0 协议不兼容的改动之一，只升一端会直接 404 或反序列化失败。

### Client Cache

调度中心侧的执行器客户端按需构建并缓存：

```java
private static final ConcurrentMap<String, ExecutorBiz> executorBizRepository = new ConcurrentHashMap<>();
private static final int EXECUTOR_BIZ_CACHE_MAX_SIZE = 1000;

public static ExecutorBiz getExecutorBiz(String address, XxlJobGroup xxlJobGroup) throws Exception {
    address = address.trim();
    String accessToken = xxlJobGroup.getAccessToken();
    String appname = xxlJobGroup.getAppname();

    // load-cache
    String cacheKey = address + "|" + accessToken + "|" + appname;
    ExecutorBiz executorBiz = executorBizRepository.get(cacheKey);
    if (executorBiz != null) { return executorBiz; }

    // new client
    executorBiz = HttpTool.createClient()
            .url(address)
            .connectTimeout(...getTimeout() * 1000)
            .readTimeout(...getTimeout() * 1000)
            .header(Const.XXL_JOB_ACCESS_TOKEN, accessToken)
            .header(Const.XXL_JOB_APPNAME, appname)
            .proxy(ExecutorBiz.class);
    executorBizRepository.put(cacheKey, executorBiz);

    // avoid unbounded growth
    if (executorBizRepository.size() > EXECUTOR_BIZ_CACHE_MAX_SIZE) {
        executorBizRepository.clear();
    }
    return executorBiz;
}
```

缓存 key 含 accessToken，所以**改了 accessToken 会自动建新客户端**；超限（1000）直接整体清空而非 LRU 淘汰——简单但会导致一次性的重建抖动。

## Upstream: Executor to Admin

执行器 POST 调度中心的 `/api/{uri}`，统一入口 `OpenApiController`：

```java
@RequestMapping("/api/{uri}")
@ResponseBody
@XxlSso(login = false)
public Object api(HttpServletRequest request,
                  @PathVariable("uri") String uri,
                  @RequestHeader(value = Const.XXL_JOB_ACCESS_TOKEN, required = false) String accessToken,
                  @RequestHeader(value = Const.XXL_JOB_APPNAME, required = false) String appname,
                  @RequestBody(required = false) String requestBody) {

    if (!"POST".equalsIgnoreCase(request.getMethod()))  { return Response.ofFail("invalid request, HttpMethod not support."); }
    if (StringTool.isBlank(uri))                        { return Response.ofFail("invalid request, uri-mapping empty."); }
    if (StringTool.isBlank(requestBody))                { return Response.ofFail("invalid request, requestBody empty."); }

    if (StringTool.isBlank(accessToken) || StringTool.isBlank(appname)) {
        return Response.ofFail("invalid request, accessToken or appname is empty.");
    }
    XxlJobGroup xxlJobGroup = ...getJobRegistryHelper().loadByAppName(appname);
    if (!(xxlJobGroup != null && accessToken.equals(xxlJobGroup.getAccessToken()))) {
        return Response.ofFail("invalid request, accessToken or appname invalid.");
    }

    switch (uri) {
        case "callback":       ...
        case "registry":       ...
        case "registryRemove": ...
        case "addJob":         ...
        case "updateJob":      ...
        case "removeJob":      ...
        case "startJob":       ...
        case "stopJob":        ...
        case "triggerJob":     ...
        default: return Response.ofFail("invalid request, uri-mapping("+ uri +") not found.");
    }
}
```

三点设计：

- `@XxlSso(login = false)`：OpenAPI **不走登录态**，靠双 header 鉴权；后台页面的接口仍走 xxl-sso。
- 鉴权查的是 `JobRegistryHelper.loadByAppName(appname)`——即 [Registry](/docs/CS/Framework/Job/xxl-job/Registry_And_Discovery.md) 里那份 30s 刷新的**本地缓存**，不查库。
- 执行器侧 URL 拼接规则：`adminAddresses` 每项 + `/api`（已以 `/` 结尾则直接拼 `api`）。

### AdminBiz

| action | 请求体 | 用途 |
| :--- | :--- | :--- |
| `callback` | `CallbackRequest`（`List<CallbackData>`） | 批量回传执行结果 |
| `registry` | `RegistryRequest` | 注册保活（30s） |
| `registryRemove` | `RegistryRequest` | 优雅下线时摘除 |

### AdminJobBiz

3.5.0 新增的任务管理 API，让外部系统（CI/CD、运维平台）可以编程式管理任务生命周期：

| action | 请求体 | 说明 |
| :--- | :--- | :--- |
| `addJob` | `JobAddRequest` | 新建任务 |
| `updateJob` | `JobUpdateRequest` | 更新任务配置 |
| `removeJob` | `JobOperateRequest`（`id`） | 删除任务 |
| `startJob` | `JobOperateRequest` | 启动 |
| `stopJob` | `JobOperateRequest` | 停止 |
| `triggerJob` | `JobTriggerRequest`（`id` / `executorParam` / `addressList`） | 手动触发一次 |

实现上有两处值得注意：

```java
/**
 * openapi login info
 */
private final LoginInfo OPENAPI_LOGIN_INFO = new LoginInfo(
        "0", "openapi", "OpenAPI", null, List.of(Consts.ADMIN_ROLE), null, -1L, null);

/**
 * token bucket, for rate limiting
 */
private final TokenBucket tokenBucket = TokenBucket.create(100, Duration.ofSeconds(30));

@Override
public Response<String> addJob(JobAddRequest request) {
    // rate limit
    if (!tokenBucket.tryAcquire(1, Duration.ofMillis(1000L))) {
        return Response.of(ResponseCode.CODE_502.getCode(), "Too many requests, please try again later.");
    }
    ...
    return xxlJobService.add(jobInfo, OPENAPI_LOGIN_INFO);
}
```

- **固定的系统级 LoginInfo**：OpenAPI 以内置管理员身份调用 `XxlJobService`，**绕过 `xxl_job_user.permission` 的数据权限控制**。也就是说，拿到任一执行器 accessToken 就能通过 OpenAPI 操作**所有**任务（不只是该执行器下的）。这是使用时必须知道的安全边界。
- **令牌桶限流**：30s 内 100 个令牌，每次尝试最多等 1s，超限返回 502。限流是 `AdminJobBizImpl` 实例级的，调度中心集群下每个节点各自 100/30s。

另外 `addJob` / `updateJob` 都硬编码 `setChildJobId(null)`——**OpenAPI 创建/更新任务不会带子任务配置**。

## AccessToken

3.5.0 的 breaking change：AccessToken 从全局配置改为**执行器维度**（`xxl_job_group.access_token`）。

| 版本 | 存储位置 | 校验内容 |
| :--- | :--- | :--- |
| ≤ 3.4.x | 调度中心与执行器各自的全局配置 | 只校验 token 相等 |
| ≥ 3.5.0 | `xxl_job_group.access_token`（每个 AppName 一个） | 校验 **token 与 appname 同时匹配** |

影响面：

1. 每个执行器可以有自己的 token，一个泄漏不影响其它 AppName；
2. 鉴权需要 appname，所以请求必须同时带两个 header；
3. **调度中心与执行器必须一并升级到 3.5.0**，否则一端只发 token、另一端要两个，全部请求会被拒；
4. 可在管理后台在线修改（发布说明里的"AccessToken 在线管理"），改完最多 30s 生效（缓存刷新周期）。

建表脚本预置 `default_token`，生产环境必须为每个执行器换掉。

> [!WARNING]
>
> 通讯是**明文 HTTP**，accessToken 只在请求头里裸传，没有签名、没有时间戳、没有 nonce。任何能抓到包的人都能重放。因此执行器端口与调度中心都应置于内网，或自行加 TLS 反向代理。

## Timeout

三处超时，互不相关：

| 位置 | 配置项 | 默认 | 作用 |
| :--- | :--- | :--- | :--- |
| 调度中心调执行器 | `xxl.job.timeout` | 3s | 连接 + 读超时，合法区间 1~10，越界回落 3 |
| 执行器回调调度中心 | `xxl.job.executor.timeout` | 3s | 同上，区间 1~10 |
| 任务本身 | 任务配置 `executor_timeout` | 0（不限） | 下发到执行器，由 `JobThread` 用 FutureTask 控制 |

注意区分：`xxl.job.timeout` 是**通讯**超时，`executor_timeout` 是**业务执行**超时。任务跑 10 分钟不会让触发请求超时（触发是异步的，入队即返回）。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)
- [Block Strategy](/docs/CS/Framework/Job/xxl-job/Block_Strategy.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
- [XXL-JOB v3.5.0 Release Note](https://github.com/xuxueli/xxl-job/releases/tag/3.5.0)
