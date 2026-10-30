## Introduction

Config 层是十层架构里**仅有的两层 API 之一**（另一层是 Service 层），以 `ServiceConfig`（服务暴露）与 `ReferenceConfig`（服务引用）为中心。它承担的是「把用户的配置意图翻译成 `URL`」这件事——因为 Dubbo 全链路以 URL 为配置总线，Config 层实际上是整个框架的入口翻译器。

本文版本基线：Apache Dubbo **3.3.6**（源码 tag `dubbo-3.3.6`）。本文聚焦**配置对象模型本身**：类归属、ScopeModel 如何沿继承链传播、字段的真实默认值。

- 服务暴露与引用的**完整时序**（`doExportUrls` → `doExportUrlsFor1Protocol` → `RegistryProtocol` → `DubboProtocol#export` → `exportLocal`，以及消费侧 `createProxy`）见 [Start](/docs/CS/Framework/Dubbo/Start.md)。
- 配置来源优先级（七个 `Configuration` 实例）与配置中心启动链路见 [config](/docs/CS/Framework/Dubbo/config.md)。
- 配置对象所属的域模型见 [ScopeModel](/docs/CS/Framework/Dubbo/ScopeModel.md)。

> [!WARNING]
> **第一个必须纠正的定位错误**：`ServiceConfigBase` / `AbstractInterfaceConfig` / `AbstractServiceConfig` **不在 `dubbo-config-api`，而在 `dubbo-common`**（`dubbo-common/src/main/java/org/apache/dubbo/config/`）。`dubbo-config/dubbo-config-api` 下只有 `ServiceConfig`、`ReferenceConfig`、`ServiceListener` 等少数类。绝大多数「服务级」配置字段（version / group / delay / weight / executes / warmup / token …）声明在 `AbstractServiceConfig`，而不是 `ServiceConfig`。

## Config Class Hierarchy

| 类 | 文件位置 |
| :--- | :--- |
| `AbstractConfig` | `dubbo-common/.../config/AbstractConfig.java` |
| `AbstractMethodConfig` | `dubbo-common/.../config/AbstractMethodConfig.java` |
| `AbstractInterfaceConfig` | `dubbo-common/.../config/AbstractInterfaceConfig.java` |
| `AbstractServiceConfig` | `dubbo-common/.../config/AbstractServiceConfig.java` |
| `AbstractReferenceConfig` | `dubbo-common/.../config/AbstractReferenceConfig.java` |
| `ServiceConfigBase` | `dubbo-common/.../config/ServiceConfigBase.java` |
| `ReferenceConfigBase` | `dubbo-common/.../config/ReferenceConfigBase.java` |
| `ServiceConfig` | `dubbo-config/dubbo-config-api/.../config/ServiceConfig.java` |
| `ReferenceConfig` | `dubbo-config/dubbo-config-api/.../config/ReferenceConfig.java` |

`ServiceConfigBase` 的四个构造器**全都**重复同一段初始化（不只是无参构造）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/ServiceConfigBase.java:87-90
public ServiceConfigBase() {
    serviceMetadata = new ServiceMetadata();
    serviceMetadata.addAttribute("ORIGIN_CONFIG", this);
}
```

## ScopeModel Propagation

`setScopeModel` 是**唯一入口**，而且它是 `final`——**没有任何子类可以重写它**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/config/AbstractConfig.java:446-461
public final void setScopeModel(ScopeModel scopeModel) {
    if (scopeModel != null && this.scopeModel != scopeModel) {
        checkScopeModel(scopeModel);
        ScopeModel oldScopeModel = this.scopeModel;
        this.scopeModel = scopeModel;
        // reinitialize spi extension and change referenced config's scope model
        this.postProcessAfterScopeModelChanged(oldScopeModel, this.scopeModel);
    }
}

protected void checkScopeModel(ScopeModel scopeModel) {
    if (!(scopeModel instanceof ApplicationModel)) {
        throw new IllegalArgumentException(
                "Invalid scope model, expect to be a ApplicationModel but got: " + scopeModel);
    }
}
```

`checkScopeModel` 全仓库只有 **3 处**重写：`AbstractConfig.java:456`（默认要求 `ApplicationModel`）、`AbstractMethodConfig.java:119`、`ModuleConfig.java:129-134`（要求 `ModuleModel`）。**`ServiceConfig` / `ServiceConfigBase` / `AbstractInterfaceConfig` 三个类里一处都没有**——常见误述是「三层各自重写了 setScopeModel 和 checkScopeModel」。

真正三层重写的是 `postProcessAfterScopeModelChanged`，且严格 `super.` 链式调用，从父类到子类依次执行：

```java
// AbstractInterfaceConfig.java:255-275 —— 把被引用配置统一改成 applicationModel
protected void postProcessAfterScopeModelChanged(ScopeModel oldScopeModel, ScopeModel newScopeModel) {
    super.postProcessAfterScopeModelChanged(oldScopeModel, newScopeModel);
    ApplicationModel applicationModel = ScopeModelUtil.getApplicationModel(getScopeModel());
    if (this.configCenter != null && this.configCenter.getScopeModel() != applicationModel) {
        this.configCenter.setScopeModel(applicationModel);
    }
    // metadataReportConfig / monitor / registries 同理
}
```

```java
// ServiceConfigBase.java:120-125 —— provider 跟随自身
protected void postProcessAfterScopeModelChanged(ScopeModel oldScopeModel, ScopeModel newScopeModel) {
    super.postProcessAfterScopeModelChanged(oldScopeModel, newScopeModel);
    if (this.provider != null && this.provider.getScopeModel() != getScopeModel()) {
        this.provider.setScopeModel(getScopeModel());
    }
}
```

```java
// ServiceConfig.java:181-185 —— 重新拿自适应扩展
protected void postProcessAfterScopeModelChanged(ScopeModel oldScopeModel, ScopeModel newScopeModel) {
    super.postProcessAfterScopeModelChanged(oldScopeModel, newScopeModel);
    protocolSPI = this.getExtensionLoader(Protocol.class).getAdaptiveExtension();
    proxyFactory = this.getExtensionLoader(ProxyFactory.class).getAdaptiveExtension();
}
```

最后一步很关键：**域模型一变，`Protocol` 与 `ProxyFactory` 的自适应扩展必须重新获取**，否则扩展实例仍挂在旧模型上。这也是「改了 ScopeModel 却没生效」的根因所在。

## Provider-Side Fields and Defaults

落在 `AbstractServiceConfig.java` 的字段：

| 字段 | 行号 | 默认值 |
| :--- | :--- | :--- |
| `version` | `:47` | 无 |
| `group` | `:52` | 无 |
| `deprecated` | `:57` | `false`（`checkDefault():172`） |
| `delay` | `:62` | **`null`**，即不延迟；`> 0` 才延迟 |
| `export` | `:67` | 逻辑默认 `true` |
| `weight` | `:72` | Config 无默认；生效默认 `100`（`dubbo-cluster/.../rpc/cluster/Constants.java:29 DEFAULT_WEIGHT`） |
| `dynamic` | `:83` | `true`（`checkDefault():175`） |
| `token` | `:88` | 无（`null`） |
| `accesslog` | `:93` | 无 |
| `protocolIds` | `:103` | `@Parameter(excluded = true)` |
| `executes` | `:108` | 无；filter 侧默认 `0`（不限制） |
| `register` | `:113` | 无；`null` 视为 `true` |
| `warmup` | `:118` | 无；生效默认 `10 * 60 * 1000`（`rpc/cluster/Constants.java:99 DEFAULT_WARMUP`） |
| `serialization` | `:123` | 无 |
| `preferSerialization` | `:136` | 空则回落为 `serialization`（`:181`） |
| `exportAsync` | `:144` | **已 `@Deprecated`**（`:143`），推荐 `ModuleConfig#exportAsync` |
| `useJavaPackageAsPath` | `:160` | `false`（`checkDefault():178`） |

```java
// AbstractServiceConfig.java:169-183
@Override
protected void checkDefault() {
    super.checkDefault();
    if (deprecated == null)            deprecated = false;
    if (dynamic == null)               dynamic = true;
    if (useJavaPackageAsPath == null)  useJavaPackageAsPath = false;
    if (StringUtils.isBlank(preferSerialization)) preferSerialization = serialization;
}
```

落在 `AbstractInterfaceConfig.java` 的字段：`local:97`、`stub:102`、`proxy:112`（生效默认 `javassist`，`CommonConstants.java:99`）、`cluster:117`、`filter:122`、`listener:127`、`connections:137`。

> [!WARNING]
> **Provider 侧没有 `retries` 字段。** `retries` 只在 `AbstractMethodConfig.java:47`（方法级）。同理 **`actives` 只在方法级**（`AbstractMethodConfig.java:52`），且 `ActiveLimitFilter` 是 **Consumer 侧**（`@Activate(group = CONSUMER)`，异常文案明写 "in client-side"）——Provider 侧的并发限制是 `executes`（`ExecuteLimitFilter`）。把 `actives` 当成服务端并发控制是最常见的一处张冠李戴。

### Three Similar But Different Export Switches

| 配置 | 所在类 | 行号 | key |
| :--- | :--- | :--- | :--- |
| `export` | `AbstractServiceConfig` | `:67` | — |
| `exportAsync`（**已废弃**） | `AbstractServiceConfig` | `:143-144` | `export-async`（`CommonConstants.java:480`） |
| `exportAsync`（推荐） | `ModuleConfig` | `:89` | — |
| `exportThreadNum` | `ModuleConfig` `:94` / `ProviderConfig:164` | | — |
| `exportBackground` | **`ProviderConfig`** | `:172` | `export-background`（`CommonConstants.java:484`） |

逻辑默认值（不是字段默认值，但行为上必须知道）：

```java
// ServiceConfigBase.java:127-146
public boolean shouldExport() { Boolean export = getExport(); return export == null || export; }
public Boolean getExport()    { return (export == null && provider != null) ? provider.getExport() : export; }
public boolean shouldDelay()  { Integer delay = getDelay(); return delay != null && delay > 0; }
public Integer getDelay()     { return (delay == null && provider != null) ? provider.getDelay() : delay; }
```

即：**服务级没配就回落到 `ProviderConfig`**，且 `delay` 的语义是「`null` 或 `<= 0` 都不延迟」。

## export() Entry Point

```
ServiceConfigBase.export()                       ServiceConfigBase.java:430-432  → export(AUTO_REGISTER)
  └─ ServiceConfig.export(RegisterTypeEnum)      ServiceConfig.java:311-350
       ├─ deployer.prepare() / deployer.start()              :316-322
       ├─ if (!isRefreshed()) this.refresh();                :329-331
       │     └─ refresh() → postProcessRefresh()             :546-550
       │           └─ checkAndUpdateSubConfigs();            :549（定义 :471）
       ├─ if (shouldExport()) this.init();                   :332-333
       ├─ if (shouldDelay())  doDelayExport();               :335-337（定义 :377-395）
       ├─ else if (delay == -1 && DUBBO_MANUAL_REGISTER)     :338-342
       ├─ else doExport(registerType);                       :344（定义 :552-565）
       │     ├─ doExportUrls(registerType)                   :568-612
       │     │     ├─ repository.registerService(...)        :578/580
       │     │     ├─ new ProviderModel(...)                 :582-588
       │     │     ├─ ConfigValidationUtils.loadRegistries() :596-598
       │     │     └─ for each ProtocolConfig → doExportUrlsFor1Protocol(...)  :614
       │     │           ├─ buildAttributes / buildUrl       :616/623
       │     │           ├─ exportUrl(...)                   :861
       │     │           │     ├─ exportRemote(...)          :914
       │     │           │     └─ exportLocal(...)           :986
       │     │           └─ doExportUrl(...)                 :964
       │     └─ exported();                                  :564
       └─ deployer.registerServiceInstance();                :349
```

> [!NOTE]
> `checkAndUpdateSubConfigs()` **不是 `export()` 直接调用的**，而是挂在 `refresh()` 的 `postProcessRefresh()` 钩子上（`ServiceConfig.java:547-550`）；`ReferenceConfig` 同理（`:832-835`）。很多源码解读文章把它写成 `export()` 的第一步，属于流程表述错误。

`exported()` 除了置位，还负责两件容易被忽略的事：接口→应用名映射的异步上报，以及 ServiceListener 通知（`ServiceConfig.java:397-416`）：

```java
protected void exported() {
    exported = true;
    List<URL> exportedURLs = this.getExportedUrls();
    exportedURLs.forEach(url -> {
        if (url.getParameter(SERVICE_NAME_MAPPING_KEY, false)) {
            ServiceNameMapping serviceNameMapping = ServiceNameMapping.getDefaultExtension(getScopeModel());
            ...
            mapServiceName(url, serviceNameMapping, scheduledExecutor);
        }
    });
    onExported();                                   // :411
    if (hasRegistrySpecified()) {
        getScopeModel().getDeployer().getApplicationDeployer().exportMetadataService();
    }
}

// :1026-1030
protected void onExported() {
    for (ServiceListener serviceListener : this.serviceListeners) {
        serviceListener.exported(this);
    }
}
```

映射上报的细节见 [Metadata](/docs/CS/Framework/Dubbo/Metadata.md)。

## URL Assembly and Warmup

### URL Assembly: registry:// vs dubbo://

服务 URL 的拼装发生在 `doExportUrlsFor1Protocol` → `buildUrl` → `exportUrl` → `exportRemote` / `exportLocal` 这条链上，最终喂给 `ProxyFactory.getInvoker(ref, interfaceClass, url)` 与 `Protocol.export(invoker)`（`ServiceConfig.java:974-978`）。

- **业务 URL（`dubbo://` / `tri://`）**：`buildUrl`（`ServiceConfig.java:821-859`）用 `ProtocolConfig.getName()`（缺省 `DUBBO`）作协议名，算出 host/port、拼接 `getContextPath() + path`，构造 `new ServiceConfigURL(name, null, null, host, port, path, params)`。这是真正暴露服务的 URL。
- **注册中心 URL（`registry://`）**：`doExportUrlsFor1Protocol` 用 `ConfigValidationUtils.loadRegistries(this, true)` 取得 `registryURLs`（`:596-597`）。每个注册中心 URL 的协议是 `RegistryConstants.REGISTRY_PROTOCOL = "registry"`（`RegistryConstants.java:27`），服务发现型注册中心则是 `SERVICE_REGISTRY_PROTOCOL = "service-discovery-registry"`（`:95`）。**业务 URL 并不直接作为注册 URL 的协议**，而是作为 `export` 属性嵌套进去：

```java
// dubbo-config/dubbo-config-api/.../ServiceConfig.java:947
doExportUrl(registryURL.putAttribute(EXPORT_KEY, url), true, registerType);
```

`RegistryProtocol` 后续从注册 URL 取出 `EXPORT_KEY` 指向的业务 URL 去注册（`export` 属性即「要注册的服务描述」）。所以一份注册中心 URL 形如：`registry://host:port/org.apache.dubbo.registry.RegistryService?export=dubbo%3A%2F%2F...`。

- **本地 URL（`injvm://`）**：`exportLocal`（`ServiceConfig.java:986-997`）把协议改成 `LOCAL_PROTOCOL`（`injvm`）、host 设 `LOCALHOST_VALUE`、port 设 `0`，同样走 `doExportUrl`。当 `scope != remote` 时本地暴露与远程暴露并存。

> [!TIP]
> `scope` 参数（`SCOPE_KEY`，值 `local` / `remote` / `none`）决定走 `exportLocal` 还是 `exportRemote`（`exportUrl` 的 `:862-909`）。`none` 则整个 `exportUrl` 不执行。`EXT_PROTOCOL` 还能在远程暴露基础上追加额外协议（如同一服务同时暴露 `dubbo` 与 `tri`，`:877-908`）。

### Warmup: Linear Weight Recovery

`warmup` 字段声明在 `AbstractServiceConfig:118`，本身无默认值；生效缺省是 `DEFAULT_WARMUP = 10 * 60 * 1000`（10 分钟，`rpc/cluster/Constants.java:99`）。它的作用不在 Provider 启动逻辑里，而在**消费侧负载均衡**：实例上线后权重按已运行时长线性爬升到配置权重，避免冷启动瞬间被打满。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/loadbalance/AbstractLoadBalance.java:46-48
static int calculateWarmupWeight(int uptime, int warmup, int weight) {
    int ww = (int) (uptime / ((float) warmup / weight));
    return ww < 1 ? 1 : (ww > weight ? weight : ww);
}
```

公式等价于 `ww = uptime * weight / warmup`，即「已运行时间占 warmup 的比例 × 目标权重」。启动瞬间 `uptime≈0` 权重趋近于 1，跑到 `uptime == warmup` 时恢复到满权重 `weight`。`AbstractLoadBalance.getWeight` 在 `uptime < warmup` 时调用它（`AbstractLoadBalance.java:91`）。

> [!NOTE]
> 这跟 `delay`（延迟暴露，`null` 不延迟）是两件独立的事：`delay` 决定「何时开始 export」，`warmup` 决定「export 后权重如何从 1 线性恢复到 `weight`」。两者都在 `AbstractServiceConfig`，但作用阶段不同。更多治理语义见 [Governance](/docs/CS/Framework/Dubbo/Governance.md)。

## ReferenceConfig in Contrast

```java
// dubbo-config/dubbo-config-api/.../ReferenceConfig.java:230-248
public T get(boolean check) {
    if (destroyed) throw new IllegalStateException(...);
    if (ref == null) {
        if (getScopeModel().isLifeCycleManagedExternally()) getScopeModel().getDeployer().prepare();
        else getScopeModel().getDeployer().start();
        init(check);
    }
    return ref;
}
```

`init(boolean)` 的关键步骤：`refresh()`（`:339-341`）→ 识别 native stub proxy（`:343-346`）→ `initServiceMetadata(consumer)`（`:349`）→ `appendConfig()`（`:355`）→ `repository.registerService`（`:364`）→ `new ConsumerModel(...)`（`:366-373`）→ `createProxy(referenceParameters)`（`:383`）→ `checkInvokerAvailable(0)`（`:392-394`，仅当 check）。

无参 `get()` 定义在 **`ReferenceConfigBase.java:398-400`**（`public final T get() { return get(true); }`），不在 `ReferenceConfig` 里。

| 项 | 默认值 | 证据 |
| :--- | :--- | :--- |
| `check` | **`true`** | `ReferenceConfigBase.java:116` |
| `init` | **`true`** | `ReferenceConfigBase.java:129`（注释 `// default is true`） |
| `injvm` | 存在，`Boolean` | `AbstractReferenceConfig.java:65` |
| `lazyConnect` | **不存在这个名字**，字段叫 **`lazy`** | `AbstractReferenceConfig.java:70` |
| `initReferenceConfig()` | **全仓库不存在此方法** | — |

`AbstractReferenceConfig` 其余字段：`check:50`、`init:55`、`generic:60`、`injvm:65`、`lazy:70`、`reconnect:72`、`sticky:74`、`stubevent:80`、`providedBy:85`、`providerPort:93`、`providerNamespace:99`、`router:101`、`referAsync:110`、`client:115`、`protocol:120`。

## Pitfall List

- **以为配置字段都在 `ServiceConfig`**——绝大多数在 `dubbo-common` 的 `AbstractServiceConfig` / `AbstractInterfaceConfig`。
- **以为 `setScopeModel` 可以重写**——它是 `final`，唯一的扩展点是 `checkScopeModel` 与 `postProcessAfterScopeModelChanged`。
- **把 `actives` 当服务端并发控制**——它是方法级且作用在 Consumer 侧；服务端用 `executes`。
- **以为 Provider 侧有 `retries`**——没有，重试是消费侧 Cluster 的行为。
- **把 `exportAsync` 当成推荐配置**——`AbstractServiceConfig` 上的那个已 `@Deprecated`，推荐 `ModuleConfig#exportAsync`；`exportBackground` 在 `ProviderConfig` 上。
- **把 `checkAndUpdateSubConfigs()` 说成 `export()` 的第一步**——它在 `refresh()` 的钩子链里。
- **写 `lazyConnect`**——正确字段名是 `lazy`。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [Start](/docs/CS/Framework/Dubbo/Start.md)
- [config](/docs/CS/Framework/Dubbo/config.md)
- [ScopeModel](/docs/CS/Framework/Dubbo/ScopeModel.md)
- [Provider](/docs/CS/Framework/Dubbo/Provider.md)

## References

- <https://github.com/apache/dubbo/tree/dubbo-3.3.6>
- <https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/config/>
