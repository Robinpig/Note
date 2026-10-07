## Introduction

前面的路由与负载均衡解决的是「流量往哪走」，但一套生产可用的 RPC 框架还要回答另一类问题：进程怎么下线才不杀掉在途请求？新扩容的实例为什么不能一上来就承接满量流量？下游故障时 Consumer 怎么体面地降级？运维如何不重启就上下线一台机器？这些「保障服务可用」的机制——优雅停机、启动预热、Mock 降级、QoS、内置限流——构成了 Dubbo 的服务治理底座，也是本文的主题。

关于这些机制流传着三个几乎人人中招的直觉：优雅停机的 key 是 `dubbo.shutdown.wait`？错，真实 key 是 `dubbo.service.shutdown.wait`，且 `shutdown.wait`/`dubbo.shutdown.wait` 这两个 key 根本不存在；`delay` 配置默认值是 `-1`？错，默认是 `null`，即完全不延迟；限流 Filter 的扩展名是 `exec-limit`？错，是 `executelimit`。

本文版本基线：Apache Dubbo **3.3.6**，所有结论均逐文件核对自源码 tag `dubbo-3.3.6`。路由规则的细节见 [Router](/docs/CS/Framework/Dubbo/Router.md)，Filter 体系见 [Filter](/docs/CS/Framework/Dubbo/Filter.md)。

## Graceful Shutdown

### Actual Configuration key and Default Values

优雅停机相关的配置 key 只有三个是真实的：

| key | 含义 | 状态 |
|---|---|---|
| `dubbo.service.shutdown.wait` | 停机等待时长（毫秒） | 现行，`CommonConstants.java:310` `SHUTDOWN_WAIT_KEY` |
| `dubbo.service.shutdown.wait.seconds` | 停机等待时长（秒） | `@Deprecated`（`CommonConstants.java:308`） |
| `shutdown.wait` / `dubbo.shutdown.wait` | — | **不存在**，打了也不生效 |

默认值是 `DEFAULT_SERVER_SHUTDOWN_TIMEOUT = 10000`（毫秒，`CommonConstants.java:184`）。读取逻辑集中在 `ConfigurationUtils.getServerShutdownTimeout`（`ConfigurationUtils.java:121-151`），注意其中一段容易被忽视的短路逻辑：**如果实际停机已经超过预期时间，直接返回 1ms**——避免停机流程被一个已经超时的等待卡住。

### Hook Chain: DubboShutdownHook.doDestroy

`DubboShutdownHook`（`DubboShutdownHook.java:41`）注册为 JVM shutdown hook，核心逻辑在 `doDestroy()`（:86-144）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/bootstrap/DubboShutdownHook.java:86
private void doDestroy() {
    // 1. 先把所有模块置为只读，通知 GracefulShutdown 停止接新请求 (:91-95)
    applicationModel.getModuleModels().forEach(module -> module.getDeployer().preDestroy());
    applicationModel.getDeployer().preDestroy();

    // 2. 若模块由 Spring 托管，轮询等待 Spring 容器先关闭模块，直到 timeout (:105-139)
    //    通过 module.isLifeCycleManagedExternally() 判断是否等 Spring 接管
    // 3. 最后销毁应用模型，执行回调 (:140-143)
    applicationModel.destroy();
}
```

三个阶段的关键点：

1. **`readonly()` → `GracefulShutdown`**：先让 Protocol 暴露的 Server 进入只读状态、拒绝新请求，给在途请求留出完成窗口。
2. **等 Spring 接管**：模块若由 Spring 容器管理生命周期，Dubbo 不抢先销毁，而是轮询等待 `ContextClosedEvent` 触发的关闭流程，最多等到 timeout。这样 Bean 销毁顺序仍由 Spring 主导，避免「Dubbo 先关了、业务 Bean 还在发请求」。
3. **`applicationModel.destroy()`**：最终销毁注册中心、协议、代理等资源。

### Spring-Side Collaboration

两条监听器在 Spring 关闭时反向驱动 Dubbo：

- `DubboBootstrapApplicationListener.onContextClosedEvent`（:125-131）：收到 `ContextClosedEvent` 时调用 `deployer.stop()`。
- `DubboDeployApplicationListener.onContextClosedEvent`（:191-200）：未设置 `KEEP_RUNNING_ON_SPRING_CLOSED` 时调用 `moduleModel.destroy()`。

### Business Custom Shutdown Actions

从 `@since 2.7.5` 起（`dubbo-common/.../common/lang/ShutdownHookCallback.java:37`），可以通过 `ShutdownHookCallback`（配合 `ShutdownHookCallbacks`，:35）注册业务自己的停机回调，执行点在 `DefaultApplicationDeployer.postDestroy → executeShutdownCallbacks`（:1148、:1168-1172）。需要「停机时刷缓存、发通知」之类的动作，这是官方扩展点。

### GracefulShutdown: Cleanup of In-Flight Requests

钩子链路的第 1 步 `readonly()` 最终落到 Protocol 层的 `GracefulShutdown`。以 dubbo 协议为例：Server 先摘除注册（从注册中心注销或置只读地址），再停止接受新连接，然后等待「在途请求数归零」或超时。整个窗口的时长上限就是 `dubbo.service.shutdown.wait`。

配合 QoS 的 `offline` 命令可以做得更精细：发布前先 telnet 22222 执行 `offline`（从注册中心摘除该实例），等待流量自然排空后再 `kill`，此时优雅停机几乎不再有在途请求需要等待。这是滚动发布的标准姿势：

```text
1. qos offline —— 注册中心摘流（路由/订阅方感知，新请求不再进来）
2. 等待在途请求完成（观察 metrics）
3. kill（触发 DubboShutdownHook → readonly → 等 Spring → destroy）
```

### Common Misoperations Related to Shutdown

- **手动注册 DubboShutdownHook 与 Spring Boot 冲突**：Spring Boot 自身已管理关闭流程，重复注册 hook 会造成双重销毁；3.x 中 Dubbo 与 Spring 的生命周期靠 `isLifeCycleManagedExternally()` 与两条 `ContextClosedEvent` 监听器对齐，用户代码里再手动 `DubboShutdownHook.getDubboShutdownHook().register()` 属于画蛇添足。
- **`KEEP_RUNNING_ON_SPRING_CLOSED`**：设置后 Spring 关闭时 Dubbo 模块不随之 destroy（`DubboDeployApplicationListener.onContextClosedEvent` :191-200 的判断条件），用于「容器关闭但进程仍需存活」的特殊场景，常规部署不要开。

## Delayed Exposure and Startup Warmup

### The Default Value of delay Is null

打假：很多资料写「`delay` 默认 `-1`，表示不延迟」，但源码里 `AbstractServiceConfig` 的声明是：

```java
// dubbo-config-api/src/main/java/org/apache/dubbo/config/AbstractServiceConfig.java:59
@Parameter(required = false)
protected Integer delay;         // 没有初始化，默认 null
```

判定逻辑在 `ServiceConfigBase.shouldDelay()`（`ServiceConfigBase.java:138-141`）：只在 `delay != null && delay > 0` 时返回 true——所以**默认行为是完全不延迟，`-1` 并非默认值**。`-1` 只在手动注册场景有一个特殊分支（`ServiceConfig.java:338-342`）。

延迟暴露的典型用途：应用启动时有大量初始化任务（缓存预热、连接池建立），此时注册中心里服务已可见但实例还没准备好接流量。给 `delay=15000` 可以让 Provider 晚 15 秒再向注册中心注册。但注意：延迟暴露**不等于**延迟接流量后就有保护——真正防「冷实例被打爆」的是下面的预热权重。

### Complete Warmup Chain

预热权重生效需要三个条件同时成立：

1. Provider URL 带有 `timestamp` 参数（默认自动带上），Consumer 用 `now - timestamp` 算 uptime（`AbstractLoadBalance.java:58-61`）。
2. `uptime > 0 && uptime < warmup`（:91-94）——uptime 为 0 或已过预热期都不插值。
3. `weight > 0`——weight 配成负数或 0 时另有处理逻辑，预热不介入。

拿 `weight=100`、`warmup=600000` 算几个采样点：

| uptime | 计算过程 | 实际权重 |
|---|---|---|
| 6 秒（6000ms） | 6000 / (600000/100) = 1 | 1 |
| 3 分钟（180000ms） | 180000 / 6000 = 30 | 30 |
| 6 分钟（360000ms） | 360000 / 6000 = 60 | 60 |
| 10 分钟之后 | — | 100（满权重） |

### Warmup Weight Formula

服务启动预热通过负载均衡权重插值实现：`DEFAULT_WARMUP = 10 * 60 * 1000`，即 **600000ms / 10 分钟**（`dubbo-cluster/.../cluster/Constants.java:97-99`）。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/AbstractLoadBalance.java:46
static int calculateWarmupWeight(int uptime, int warmup, int weight) {
    int ww = (int) ( uptime / ((float) warmup / weight));
    return ww < 1 ? 1 : (Math.min(ww, weight));
}
```

这是一个**线性插值**公式：`uptime / warmup` 是启动进度（0 到 1），乘以目标 `weight` 即当前应有权重。刚启动时 `ww` 小于 1 会被压到 **1**——新实例至少分到一点流量用于验证健康，但不会被打爆；随 uptime 增长权重线性抬升，到 warmup（默认 10 分钟）恢复满权重。生效条件在 `getWeight` 中：`uptime > 0 && uptime < warmup`（`AbstractLoadBalance.java:91-94`），uptime 由 Provider URL 的 timestamp 参数推算。

> [!TIP]
> 容器化场景（K8s HPA、频繁滚动发布）建议显式调小 `warmup`（如 `warmup=60000`），否则每次发布后的 10 分钟里新实例都在低权重运行，流量会被旧实例硬扛。

## Mock (Service Degradation)

### Configuration Entry and Semantics

Mock 的配置 key 就是 `"mock"`（`dubbo-rpc-api/.../rpc/Constants.java:24`），注解侧 `@DubboReference` 与 `@DubboService` 都有 `String mock() default ""`（`DubboReference.java:239`、`DubboService.java:228`）。前缀常量：`RETURN_PREFIX="return "`、`THROW_PREFIX="throw"`、`FAIL_PREFIX="fail:"`、`FORCE_PREFIX="force:"`（`Constants.java:31,33,35,37`）。

语义判定发生在 `MockClusterInvoker.invoke`（:102-151）——**先于真实调用**：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/support/wrapper/MockClusterInvoker.java:102
public Result invoke(Invocation invocation) throws RpcException {
    // value = directory.getUrl().getMethodParameter(methodName, MOCK_KEY, ...)
    if (value.startsWith(FORCE_KEY)) {
        // force:return null 等：直接走 mock，【不发真实请求】(:102-112)
        ...
    } else {
        // fail-mock：先发真实请求 (:114-118)
        try {
            result = this.invoker.invoke(invocation);
            ...
        } catch (RpcException e) {
            // 只有【非业务】RpcException（如超时、网络）才降级 mock
            // 业务侧主动抛的 RpcException 不会被 mock 吞掉
        }
    }
}
```

即两种模式：`force:` 是**无条件 mock**（熔断演练、彻底屏蔽），`fail:`（不带前缀的 `mock=` 等价 fail 语义）是**失败降级**，且只针对非业务异常。

### mock Value Parsing

真正产出降级结果的是 `MockInvoker.invoke`（:104-138）：

- `return xxx` → 直接返回常量值（`return null` / `return empty` / JSON 值）。
- `throw xxx` → 实例化并抛出指定异常类（如 `java.lang.RuntimeException`）。
- 其他 → 视为**自定义实现类**（如 `mock=com.xxx.MockImpl`，需要实现与接口同参的方法）。

解析前 `normalizeMock` 会先剥离 `fail:`/`force:` 前缀，并把反引号 `` ` `` 替换为双引号（:233-265）——所以 `fail:throw` 里的异常参数想带字符串字面量时要用反引号。

### Comparison of Four Usage Patterns

| 写法 | 触发时机 | 效果 |
|---|---|---|
| `mock = force:return null` | 每次调用直接 mock，不发请求 | 返回 null，用于屏蔽下游 |
| `mock = fail:return null` | 非业务 RpcException 后 | 返回 null 兜底 |
| `mock = fail:throw java.lang.RuntimeException` | 非业务 RpcException 后 | 抛指定异常，让上层感知失败 |
| `mock = com.xxx.MockImpl` | 非业务 RpcException 后 | 执行自定义降级逻辑（复杂降级） |

### The Entire Trigger Chain of Mock

把 `mock=` 放到调用链里看，它其实横跨三层：

```text
Consumer 侧 Cluster 层
  └─ MockClusterInvoker            ← 语义判定（force/fail），见上文 :102-151
       └─ AbstractCluster$ClusterFilterInvoker（filter 链）
            └─ FailoverClusterInvoker 真实调用失败
                 └─ 失败路径回到 MockClusterInvoker 的 catch → MockInvoker.invoke (:104-138)
                      ├─ return null / return empty / return JSON → 常量结果
                      ├─ throw com.xxx.XxxException               → 抛异常实例
                      └─ com.xxx.MockImpl                          → 反射实例化自定义类并调用同名方法
```

`MockInvoker` 内部（:104-138）按 `normalizeMock` 清洗后的值分发到 `ReturnValueMockInvoker` / `ThrowExceptionMockInvoker` / 自定义类路径。自定义 MockImpl 的要求：与接口**同名 + Mock 后缀**（或 `mock=` 直接指定类名），并实现接口方法——`mock=true` 的便捷写法就等价于 `mock=接口全限定名 + "Mock"`。

方法级配置同样支持：`@DubboReference(methods = {@Method(name = "findUser", mock = "fail:return null")})`，方法级优先于接口级。

再补两种常被问到的写法：

```yaml
# 即要求工程里存在 org.apache.dubbo.demo.api.DemoServiceMock implements DemoService
# Requires the Project to Have org.apache.dubbo.demo.api.DemoServiceMock implements DemoService
mock: true

# 全局默认降级值：consumer 侧 cluster 配置 mock 默认行为
dubbo:
  consumer:
    check: false        # 启动时不校验 Provider 可用性，配合 mock 做启动容错
```

`mock=true` 与自定义 MockImpl 的区别只在于类名约定：前者按「接口名 + Mock」自动寻找实现类，后者在 `mock=` 里显式指定全限定类名，二者最终都落到 `MockInvoker` 的自定义类分支。

### Difference from MockInvokersSelector

`mock=` 配置之外还有一个**独立的路由实现** `MockInvokersSelector`（扩展名 `mock`，走 legacy Router 链，保留原名未改名）。它依据 invocation attachment `invocation.need.mock`（`INVOCATION_NEED_MOCK`，`dubbo-cluster/.../cluster/Constants.java:80`）在 mock invoker 与 normal invoker 之间选择（`MockInvokersSelector.java:73-84`）——即「把调用定向到 MockProtocol 暴露的 invoker」的机制，与「调用失败后返回假数据」的 `mock=` 配置是两套东西，不要混为一谈。

## QoS

3.3.6 仍内置 QoS（Quality of Service）运维端口，代码位于 `dubbo-plugin/dubbo-qos` 与 `dubbo-plugin/dubbo-qos-api`，通过 `QosProtocolWrapper` 以 Protocol wrapper `qos` 挂入。

| 配置 | 默认值 | 源码 |
|---|---|---|
| `qos.enable` | **true（默认开启）** | `QosProtocolWrapper.java:107` |
| `qos.port` | **22222** | `QosConstants.java:21`、`QosProtocolWrapper.java:116` |
| `qos.check` | `false` | `QosProtocolWrapper.java:100` |
| `qos.accept.foreign.ip` | `false`（只接受本机连接） | `QosProtocolWrapper.java:117` |

常用命令（telnet 22222 后交互）：

- `ls`：列出可用命令与已注册服务。
- `online` / `offline`：临时上下线指定服务（配合发布窗口摘流量，不用重启进程）。
- `metrics`：导出指标，是 **Prometheus 接入 Dubbo 指标的实际通道**，详见 [Metrics](/docs/CS/Framework/Dubbo/Metrics.md)。
- `version` / `help`：版本与帮助。

一个典型会话：

```text
$ telnet 127.0.0.1 22222
dubbo>ls
As Provider side:
- org.apache.dubbo.demo.DemoService:1.0.0:dubbo

dubbo>offline org.apache.dubbo.demo.DemoService
OK

dubbo>online org.apache.dubbo.demo.DemoService
OK
```

`online`/`offline` 改变的是 Provider 在本进程内的暴露状态与注册中心里的地址可见性，进程不退出、JVM 不重启，是发布窗口手工摘流的最快手段。`metrics` 命令的输出默认是文本格式，配合 Prometheus exporter 模式（`dubbo.metrics.protocol=prometheus`）后可直接被 `prometheus.yml` 的 scrape 配置抓取。

### Interaction with Startup Sequence

`qos.check` 默认 `false`：QoS Server 启动失败（如端口被占）不会阻断应用启动。若把 QoS 当作运维强依赖（发布脚本依赖 offline/online），建议设 `qos.check=true`，让端口冲突尽早暴露。

> [!WARNING]
> `qos.accept.foreign.ip=false` 是默认的安全防线（仅本机可连）。一旦把它打开且 22222 端口暴露到公网/办公网，任何人都能 `offline` 你的服务——务必配合网络隔离。

## Built-in Rate Limiting and Concurrency Control

dubbo-rpc-api 的 `META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter` 中与限流相关的真实扩展名：

```properties
# dubbo-rpc-api/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.Filter（节选）
accesslog=org.apache.dubbo.rpc.filter.AccessLogFilter
executelimit=org.apache.dubbo.rpc.filter.ExecuteLimitFilter
tps=org.apache.dubbo.rpc.filter.TpsLimitFilter
active-limit=org.apache.dubbo.rpc.filter.ActiveLimitFilter
```

> [!WARNING]
> 打假：并发控制 Filter 的扩展名是 **`executelimit`**，不是 `exec-limit`。引用扩展点时用错名字会直接 `IllegalStateException: No such extension`。

三个 Filter 的激活条件与语义：

| Filter | `@Activate` | key | 语义 |
|---|---|---|---|
| `ExecuteLimitFilter` | `group=PROVIDER, value=EXECUTES_KEY`（:40-41） | `executes`（`Constants.java:61`） | **按并发数限流**：Provider 侧同一时刻最多 N 个在途请求 |
| `TpsLimitFilter` | `group=PROVIDER, value=TPS_LIMIT_RATE_KEY`（:45） | `tps`（:45 引用 `TPS_LIMIT_RATE_KEY`） | **按 TPS 限流**：固定窗口计数，超限抛 RpcException |
| `AccessLogFilter` | `group=PROVIDER` 恒激活 | `accesslog` | 未配置 `accesslog` 时 `invoke` 直接放行（:109-115），配置后异步记访问日志 |

此外 `active-limit`（`ActiveLimitFilter`）作用于 Consumer 侧，控制单个客户端对同一方法的最大并发（`actives` 参数）。

### ExecuteLimitFilter Implementation Notes

`ExecuteLimitFilter` 的并发控制是一个按「方法级 URL 参数」划分的 `RpcStatus` 计数器：请求进入时 `beginCount`，若超过 `executes` 直接抛 `RpcException`；请求结束（无论成功失败）`endCount`。注意它是 **Provider 单实例维度**——三台机器各配 `executes=100`，集群总并发上限是 300 而不是 100，且没有任何跨实例协调。`ActiveLimitFilter` 同理是 Consumer 单实例维度。

### TpsLimitFilter Implementation Notes

`TpsLimitFilter` 用 `RateLimiter`（Dubbo 自实现的固定窗口计数）实现：`tps` 配置每秒允许的请求数，超限抛 `RpcException("Failed to invoke service ...")`。固定窗口的通病它都有——窗口边界处可能放过 2 倍突发流量。两个 Filter 都没有熔断（半开探测）、没有降级回调，失败就是直接抛异常给上层，因此「限流」而不「兜底」。

> [!NOTE]
> 这些内置能力都很「朴素」：单机维度、无平滑、无分布式配额，生产上的限流/熔断通常改用 Sentinel 集成（`dubbo-sentinel-support`），见 [Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)。

## Collaboration Sequence of Each Mechanism

这些治理机制不是孤立开关，把它们放到一次「发布 → 运行 → 故障 → 下线」的生命周期里看：

```text
【启动】delay 控制注册时机 → 注册中心可见 → warmup 让权重从 1 线性爬升（默认 10 分钟）
【运行】QoS 22222 端口提供 online/offline/metrics 运维面
        ExecuteLimitFilter/TpsLimitFilter 做粗粒度闸门（可选）
【故障】下游异常 → RpcException（非业务）→ MockClusterInvoker 触发 fail-mock → MockInvoker 返回兜底值
【下线】qos offline 摘流 → kill → DubboShutdownHook：readonly → 等 Spring → destroy → ShutdownHookCallback
```

几个组合上的注意点：

- **delay 与 warmup 解决的是两个问题**：delay 管「什么时候对外可见」，warmup 管「可见后多久给满流量」。只配 delay 不配 warmup，实例一注册就是全量权重。
- **mock 与限流的先后**：Filter 链在 Cluster Invoker 之内，`TpsLimitFilter` 抛出的 `RpcException` 对 MockClusterInvoker 而言就是「非业务异常」——被限流的请求会**额外触发 fail-mock**。这意味着「限流 + mock」组合的降级路径是连通的，演练时要考虑到。
- **优雅停机与 QoS 互为补充**：offline 是「注册中心层面摘流」，优雅停机是「进程层面的善后」，顺序执行才能保证在途请求平滑归零。

## Default Value Summary

| 配置 | 默认值 | 源码位置 |
|---|---|---|
| `dubbo.service.shutdown.wait` | `10000` ms（`DEFAULT_SERVER_SHUTDOWN_TIMEOUT`） | `CommonConstants.java:184`、`ConfigurationUtils.java:121-151` |
| `delay` | `null`（不延迟，非 -1） | `AbstractServiceConfig.java:59-62`、`ServiceConfigBase.java:138-141` |
| `warmup` | `600000` ms（10 分钟） | `dubbo-cluster/.../cluster/Constants.java:97-99` |
| `weight` | `DEFAULT_WEIGHT = 5`（预热插值目标） | `AbstractLoadBalance.java:91-94` |
| `mock` | `""`（不启用） | `DubboReference.java:239`、`DubboService.java:228` |
| `qos.enable` | `true` | `QosProtocolWrapper.java:107` |
| `qos.port` | `22222` | `QosConstants.java:21` |
| `qos.check` | `false` | `QosProtocolWrapper.java:100` |
| `qos.accept.foreign.ip` | `false`（仅本机） | `QosProtocolWrapper.java:117` |
| `executes` / `tps` / `actives` | 未配置则不启用对应 Filter | `dubbo-rpc-api` Filter SPI |

## Pitfall List

1. **优雅停机 key 记错不生效**：真实 key 是 `dubbo.service.shutdown.wait`（毫秒）；`shutdown.wait`、`dubbo.shutdown.wait` 均不存在；`...seconds` 结尾的旧 key 已 `@Deprecated` 且单位是秒——毫秒/秒混写会让等待时间差 1000 倍。
2. **`getServerShutdownTimeout` 的 1ms 短路**：停机已超时（如 JVM 已被 SIGKILL 倒计时）时返回 1ms，不要误以为 1 是什么特殊配置值。
3. **`delay` 默认是 `null` 不是 `-1`**：`shouldDelay()` 判 `delay != null && delay > 0`；`-1` 只在手动注册分支有含义（`ServiceConfig.java:338-342`）。
4. **预热权重公式是线性插值**：`ww = uptime / (warmup / weight)`，下限 1、上限 weight；误写成「启动即全量权重」会在线上打出雪崩。
5. **fail-mock 只降级非业务 RpcException**：业务代码主动抛的 RpcException 不会触发 mock，别指望 mock 吞掉业务异常。
6. **`force:` 与 `fail:` 的区别是「发不发请求」**：`force:` 直接返回 mock 值，连一次真实调用都没有——用它演练降级时注意它测不到下游。
7. **反引号语法**：`throw`/`return` 参数中的字符串字面量用反引号包裹（`normalizeMock` 会替换成双引号），直接写双引号反而会破坏解析。
8. **`MockInvokersSelector` ≠ `mock=` 配置**：前者是按 attachment `invocation.need.mock` 选 mock invoker 的路由，后者是失败降级配置，两套机制独立运作。
9. **QoS 默认开着且端口 22222**：容器/内网环境常被忽略；如果需要改 `qos.accept.foreign.ip=true`，必须确认端口做了网络隔离。
10. **限流扩展名是 `executelimit`**：写成 `exec-limit` 会找不到扩展。
11. **内置限流不建议上生产**：单机、无平滑、无分布式配额，生产限流熔断优先 Sentinel 等方案。
12. **被限流的请求也会触发 fail-mock**：`TpsLimitFilter` 抛出的 RpcException 会进入 MockClusterInvoker 的降级分支，「mock + 限流」不是互斥组合，压测时要分开验证。
13. **集群总量 ≠ 单机配额**：`executes`/`actives`/`tps` 全是单机语义，扩容会等比例放大集群上限，容量规划按实例数乘。
14. **优雅停机不是万能的**：`dubbo.service.shutdown.wait` 只控制「等在途请求/等 Spring」的上限，kill -9 会直接跳过整个钩子链路；编排系统给进程的 SIGTERM 宽限期必须大于该值。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Router](/docs/CS/Framework/Dubbo/Router.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [Start](/docs/CS/Framework/Dubbo/Start.md)
- [Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md)
- [Auth](/docs/CS/Framework/Dubbo/Auth.md)

## References

1. [Dubbo QoS 官方文档](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/qos/overview/)
2. [Dubbo 配置项参考](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config/properties/)
3. [Dubbo 服务降级（Mock）官方文档](https://cn.dubbo.apache.org/zh-cn/overview/core-features/traffic/mock/)
