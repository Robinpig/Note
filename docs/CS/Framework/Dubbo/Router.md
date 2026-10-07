## Introduction

当服务目录（Directory）里躺着几十个 Provider 实例时，一个问题随之而来：是不是每一次调用都应该把全部实例纳入候选？答案是 No——灰色发布要把流量圈在一批机器上、机房隔离要让 Consumer 优先走同机房、接口级压测要把某个参数值的请求固定路由到指定实例。路由（Router）就是站在「全部 Invoker」和「参与负载均衡的 Invoker」之间的那道过滤闸门。

大多数人学 Dubbo 路由时背过的一套结论——「内置实现有 ConditionRouter、TagRouter、ScriptRouter、ServiceRouter，条件路由支持 `in`、`matches` 等运算符」——在 Dubbo 3.3 里已经整体失效：**内置路由实现全部改名为 `*StateRouter`，旧类名在整棵源码树中已不存在**；条件路由的表达式解析器也远比想象的「简陋」，只认 `&`、`=`、`!=`、`,` 四种分隔符，不存在任何 `in` / `not in` / `matches` / `any` 运算符。

本文版本基线：Apache Dubbo **3.3.6**，所有结论均逐文件核对自源码 tag `dubbo-3.3.6`。路由在集群容错链条中的位置与 Router/RouterChain 接口基座见 [cluster](/docs/CS/Framework/Dubbo/cluster.md)，本文聚焦**路由规则本身**：规则怎么配、怎么解析、怎么生效。

## Position of Routing in the Call Chain

一次 Cluster 调用中，Invokers 的流转顺序是：

```
RegistryDirectory (全量 Provider Invoker)
        │  notify → buildRouterChain
        ▼
RouterChain.route(...)  ── 依次执行 StateRouter 链 + legacy Router
        │
        ▼
过滤后的 BitList<Invoker>  ── 交给 LoadBalance 选择最终实例
```

RouterChain 在 Directory 订阅时构建，路由规则变更（配置中心推送）通过 `notify` 热更新到各 Router 实例。接口定义（`Router` / `RouterChain` / `Configurator`）的框架代码已在 [cluster](/docs/CS/Framework/Dubbo/cluster.md?id=routerchain) 梳理，不再重复。

### Registry of Built-in Routing Implementations

3.3.6 内置路由通过 **StateRouterFactory SPI** 注册，文件位于 `dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.router.state.StateRouterFactory`：

```properties
# dubbo-cluster/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.rpc.cluster.router.state.StateRouterFactory
mock=org.apache.dubbo.rpc.cluster.router.mock.MockStateRouterFactory
condition=org.apache.dubbo.rpc.cluster.router.condition.ConditionStateRouterFactory
service=org.apache.dubbo.rpc.cluster.router.condition.config.ServiceStateRouterFactory
app=org.apache.dubbo.rpc.cluster.router.condition.config.AppStateRouterFactory
provider-app=org.apache.dubbo.rpc.cluster.router.condition.config.ProviderAppStateRouterFactory
standard-mesh-rule=org.apache.dubbo.rpc.cluster.router.mesh.route.StandardMeshRuleRouterFactory
script-app=org.apache.dubbo.rpc.cluster.router.script.config.AppScriptRouterFactory
tag=org.apache.dubbo.rpc.cluster.router.tag.TagStateRouterFactory
```

源码树中 `dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/` 按实现分为 `affinity`、`condition`（含 `config`、`matcher`）、`file`、`mesh`、`mock`、`script`、`state`、`tag` 八个子包。

> [!WARNING]
> 两个容易踩坑的注册事实：
>
> 1. `script=` 与 `file=` 只在**测试资源**里注册，主 resources 的 StateRouterFactory 文件没有它们——不要在生产配置里指望 `script` 路由开箱即用。
> 2. legacy `RouterFactory` SPI 在 3.3.6 **已无任何注册文件**，旧的「RouterFactory 扩展名」玩法正式退场。

仅存的保留旧命名的两个类是 `MeshRuleRouter` 与 `MockInvokersSelector`。

### Where Rules Come From: Directory Subscription and Hot Update

路由规则不是静态配置文件，而是**配置中心驱动的动态数据**。以应用级条件路由为例：

```text
配置中心（Nacos/Zookeeper 等）写入 key: {application}.condition-router
        │  规则变更推送
        ▼
AppRouterFactory / ServiceRouterFactory 创建并持有 ConditionStateRouter
        │  notify(invokers) 时同步规则 → 重新解析 conditions → 原子替换内部 matcher
        ▼
SingleRouterChain 持有 StateRouter 数组，下一次 simpleRoute 即按新规则过滤
```

`AppStateRouterFactory` / `ServiceStateRouterFactory` / `ProviderAppStateRouterFactory` 对应「应用级 Consumer 规则」「接口级规则」「应用级 Provider 规则」三种订阅 key 的拆分；`AppScriptRouterFactory` 同理为 script 规则提供应用级订阅。这种「规则解析结果热替换」的设计意味着：**规则变更不需要重启，也不重建 RouterChain，只影响下一次 route 的过滤结果**。

### Routing Snapshot: The Governance Value of buildSnapshot

StateRouter 的 `buildSnapshot()`（`StateRouter.java:97`）返回 `RouterSnapshotNode` 树，记录每个 StateRouter 过滤后各自保留了哪些实例。Dubbo Admin 的「路由分析」功能就是靠它在灰度排查时回答「为什么这个 Consumer 只调到了这几台机器」——`simpleRoute` 中 `needToPrintMessage` 与 `routeSnapshotNodeHolder` 参数（见上文 `SingleRouterChain.java:166` 代码）即为快照收集服务。

## StateRouter Interface and legacy Router

### StateRouter: An Interface Since 3.0

一个常见误传是「StateRouter 是 3.3 新引入的」。事实是：`StateRouter` 标注 **`@since 3.0`**，3.0 起就是路由体系的核心抽象。

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/StateRouter.java:37
@SPI
public interface StateRouter<T> {

    default void notify(BitList<Invoker<T>> invokers) {
        // default is nop
    }

    BitList<Invoker<T>> route(BitList<Invoker<T>> invokers, URL url, Invocation invocation,
                              boolean needToPrintMessage, Holder<RouterSnapshotNode<T>> nodeHolder);

    default List<RouterSnapshotNode<T>> buildSnapshot() {
        return null;
    }

    void setNextRouter(StateRouter<T> nextRouter);

    boolean isRuntime();

    boolean isForce();
}
```

签名要点（`StateRouter.java:58-64`）：

- 入参是 `BitList<Invoker<T>>`——3.x 为路由过滤专门设计的位图列表，过滤操作只翻转 bit，不做列表拷贝，这是 StateRouter 体系性能优化的基石。
- **返回值是 `BitList<Invoker<T>>`，而不是 `RouterResult`**。`RouterResult` 是 legacy `Router` 接口四参 `route()` 的返回类型（`Router.java:71-74`），别把两者的返回语义搞混。
- `notify(BitList)`（:90）接收规则/实例变更；`buildSnapshot()`（:97）导出路由快照用于治理控制台展示；`setNextRouter(...)`（:108）把多个 StateRouter 串成责任链。
- `isRuntime()`、`isForce()` 暴露规则的 runtime / force 语义。
- **没有 `getPriority()` 方法**；同样**不存在 `StateRouterChain` 这个类**，链的载体仍是 `RouterChain` / `SingleRouterChain`；也不存在 `isPool` / `getPool` 之类的方法（全仓库无匹配）。

### StateRouter Chain and Coexistence with legacy Router

运行时两条链串行执行，`SingleRouterChain.simpleRoute` 先跑 StateRouter 链，再跑 legacy Router：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/state/SingleRouterChain.java:166
private BitList<Invoker<T>> simpleRoute(BitList<Invoker<T>> invokers, URL url, Invocation invocation) {
    // (1) StateRouters first
    if (stateRouters != null && stateRouters.length > 0) {
        BitList<Invoker<T>> tmpInvokers = invokers;
        for (StateRouter<T> stateRouter : stateRouters) {
            tmpInvokers = stateRouter.route(tmpInvokers, url, invocation, needToPrintMessage, routeSnapshotNodeHolder);
        }
        invokers = tmpInvokers;
    }
    // (2) then legacy routers (Router.java:71-74 的四参 route，返回 RouterResult)
    for (Router router : builtinRouters) {
        RouterResult<Invoker<T>> routeResult = router.route(invokers, url, invocation);
        invokers = routeResult == null ? invokers : routeResult.getInvokers().clone();
        if (CollectionUtils.isEmpty(invokers)) {
            if (logger.isWarnEnabled()) {
                logger.warn("Some routers p...
```

> [!NOTE]
> legacy `Router` 接口**没有整体标注 `@Deprecated`**（`Router.java:35`），只有旧的三参 `route` default 方法单独标了 `@Deprecated`（:55）。也就是说四参 `route` + `RouterResult` 仍是受支持的 legacy 路径，MockInvokersSelector 就走这条路。

### BitList: A Data Structure Born for Routing

StateRouter 签名里反复出现的 `BitList<Invoker<T>>` 值得单独说一句。传统路由每过滤一次就 `new ArrayList` 拷贝一遍，规则一多开销叠加。BitList 用位图表达「哪些下标的 invoker 存活」，`route()` 过滤只是翻转 bit，`clone()` 是位拷贝而非对象拷贝；`removeAll`、集合运算都退化为位运算。这也是 StateRouter 链可以把七八个路由串起来跑而不明显拖慢调用的前提。理解这一点，才能理解为什么 3.x 坚持把返回类型从 `List` 换成 `BitList`。

### How the Chain of Responsibility Is Assembled

`setNextRouter(...)`（:108）把 StateRouter 串成单向链，`RouterChain` 构建时按扩展顺序（mock → condition → service/app → provider-app → standard-mesh-rule → script-app → tag）组装。过滤是**短路式**的：某个 StateRouter 把 BitList 清空后，后续路由拿到空列表，通常会直接透传。这就是 `force=true` 规则的底层含义——它敢于返回空结果，而 `force=false` 的实现会在返回空前尝试兜底回退（如 TagStateRouter 的 FAILOVER）。

## Conditional Routing Rule Syntax

条件路由是治理控制台上最常用的规则：一段 `conditions` YAML，每条形如 `when => then`。`ConditionStateRouter` 解析时的第一件事很直白——把前缀剪掉：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/condition/ConditionStateRouter.java:106
public ConditionStateRouter(URL url, String rule) {
    // ...
    this.whenRule = ...
    this.thenRule = ...
    // 先剥掉 consumer./provider. 前缀 (:106-125)
    whenRule = whenRule.replace("consumer.", "").replace("provider.", "");
    thenRule = thenRule.replace("consumer.", "").replace("provider.", "");
    // "true" => xxx 视为无条件匹配；xxx => "false" 视为过滤掉全部 (:100,285)
}
```

### Delimiters: Only Four Kinds

解析器用一个正则把表达式切成 token，**只识别 `&`、`=`、`!=`、`,` 四种分隔符**：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/condition/ConditionStateRouter.java:76
private static final Pattern CONDITION_PATTERN = Pattern.compile("([&!=,]*)\\s*([^&!=,\\s]+)");
// 解析主循环 :127-202：交替读出「分隔符 + 值」，按 when/then 分别落到两个 matcher 集合
```

> [!WARNING]
> 打假：条件路由**不存在 `in` / `not in` / `matches` / `any` 运算符**。在 `condition/` 包内按词搜索，`matches`/`mismatches` 只是变量名，不是语法。多值集合用逗号分隔（`method=hello,hi`），语义是「任一命中即匹配」。网上教程里的 `host in (...)` 写法在 3.3.6 里只会把 `in` 当作待比较的字面值，匹配必然失败。

### key Matcher: Three Kinds of SPI

key（等式左边）由 `ConditionMatcherFactory` SPI 分发，共三种实现：

| Factory | 匹配对象 | 说明 |
|---|---|---|
| `attachment`（`AttachmentConditionMatcherFactory`） | Invocation attachment | `attachments` 硬编码（`AttachmentConditionMatcherFactory.java:26`） |
| `argument`（`ArgumentConditionMatcherFactory`） | 方法实参 | 见下文 `arguments[i]` 写法 |
| `param`（`UrlParamConditionMatcherFactory`） | URL 参数（兜底） | `shouldMatch` 恒为 true，`host`/`method`/`protocol`/`port`/`application` 等全部走这里（`UrlParamConditionMatcherFactory.java:28-30`） |

常量来源：`arguments` 的 key 常量 `Constants.ARGUMENTS = "arguments"`（`dubbo-cluster/.../cluster/Constants.java:129`）；其余任意 URL 参数名直接作 key。

`method` / `methods` 在 when 侧有特殊处理：不再查 URL 参数，而是取**用户实际调用的方法名**（`AbstractConditionMatcher.java:60-64`），所以 `method = find*` 匹配的是 invocation 的方法，而非 Provider URL 上的方法列表参数。

### Value Matcher: Two Kinds of SPI

等式右边（值）由 `pattern.ValuePattern` SPI 处理，只有两种：

- `range=`：区间匹配，用 `~` 表示范围（如 `port = 20880~20890`）。
- `wildcard=`：通配匹配，支持 `*`，同时是兜底实现（order = MAX）——普通字符串走等值比较。

`arguments` 的写法是 **`arguments[0]=1`**（下标方括号，正则 `arguments\[([0-9]+)\]`，`ArgumentConditionMatcher.java:43`），还支持按 `.` 深入对象属性：`arguments[0].inner`（:53）。

> [!WARNING]
> 打假：`arguments[0] = 'xxx'` 这种**带引号的写法不被任何特殊处理**，引号会作为字面字符参与通配比较（`WildcardValuePattern` 底层走 `UrlUtils.isMatchGlobPattern` 等值比较，`UrlUtils.java:476`），导致匹配失败。官方测试用例一律是无引号形式（`ConditionStateRouterTest.java:482`）。

### then-Side Boundaries

`=>` 后面（then 侧）只能写 **Provider URL 参数**（`host`、`port`、`protocol`、`application` 等）。原因很硬：`matchThen` 调用时传入的 `invocation` 是 `null`（`ConditionStateRouter.java:308-314`），Invocation 级别的 key（`method`、`arguments`、`attachments`）在 then 侧根本取不到值，写了也是无效规则。

### Rule Example

以下写法均可在 3.3.6 中实际生效：

```yaml
# 黑白名单：禁止指定 Consumer IP 调用
conditions:
  - host = 10.20.153.10 => host = 10.20.153.11   # host=10.20.153.10 的请求被路由到 10.20.153.11（host 不匹配则无实例，等效禁用）

# 读写分离：find 开头的方法不去指定机器
conditions:
  - method = find* => host != 10.20.153.11       # 通配 * 命中 findList / findUser 等

# 按参数路由：第一个参数为 a 的请求固定到指定实例（灰度/压测）
conditions:
  - arguments[0] = a => host = 10.20.153.10

# 多值任一命中：method=hello 或 hi 都不访问 10.20.153.11
conditions:
  - method = hello,hi => host != 10.20.153.11
```

### rule Field: force / runtime / enabled

每条路由规则（`AbstractRouterRule`）有三个控制字段：

| 字段 | 默认 | 含义 | 源码 |
|---|---|---|---|
| `force` | `false` | true 时路由失败（过滤后为空）也强制返回空列表，不做兜底回退 | `AbstractRouterRule.java:38`、`ConditionStateRouter.java:97` |
| `runtime` | `false` | true 时每次调用重新解析规则（配合动态参数），false 时仅订阅变更时解析 | `AbstractRouterRule.java`、`ConditionStateRouter.java:100` |
| `enabled` | `true` | false 时该条规则整体停用 | `ConditionStateRouter.java:285` |

### Details of the Parsing Process

`ConditionStateRouter` 的解析主循环（:127-202）把 `whenRule`/`thenRule` 分别交给 `parseRule`：正则交替捕获「分隔符 token + 值 token」，遇到 `&` 之前累积的键值对归入同一条件组（组内全部命中才算命中），`&` 开启新组（组间任一命中即通过）——即条件路由表达式本身就是 **DNF（析取范式）** 语义。解析结果不是字符串而是预编译好的 matcher 列表，存进 `whenCondition` / `thenCondition`，调用期只做匹配、不做解析。

`matchThen`（`ConditionStateRouter.java:308-314`）把 Provider URL 逐个交给 then matcher，命中的保留。整条规则对一次调用的作用可概括为：

```text
invocation + consumerUrl ──when 匹配──> 不命中：本条规则对该调用不生效，invokers 原样返回
                          └─命中──> 取 Provider URL 集合 ──then 过滤──> 仅保留 then 命中的实例
```

### tag-router and condition-router Rule Locations

动态规则在配置中心的位置约定（3.x 应用级服务发现模式）：

- 应用级条件规则：`{appName}.condition-router`，内容 YAML 的 `conditions` 列表。
- 标签规则：`{providerAppName}.tag-router`，内容 YAML 的 `force` 与 `tags`（`key: tag值`、`enable: true`）。
- 接口级条件规则：`{interfaceName}:{version}:{group}.condition-router`（对应 `ServiceStateRouterFactory` 的订阅维度）。

规则内容第一行通常是 `scope: application`（或 `service`）与 `key: 应用名/服务名`，RouterFactory 构造时用它决定规则归属，scope 不匹配的规则会被丢弃。

## Tag Routing

标签路由是**应用级**规则：动态规则以 `providerApplication + ".tag-router"` 为 key 存储（`TagStateRouter.java:284-325` 的 `notify()` 按 Provider 应用订阅），而不是接口级。实现类是 `TagStateRouter`（`tag/TagStateRouter.java:52`）。

### Where Tags Come From

请求侧标签的取值顺序：先取 invocation attachment，再退回 URL 参数，key 统一为 `dubbo.tag`（`CommonConstants.java:348`）：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/tag/TagStateRouter.java:118
String tag = invocation.getAttachment(TAG_KEY);   // 先看 invocation attachment
if (StringUtils.isEmpty(tag)) {
    tag = consumerUrl.getParameter(TAG_KEY);      // 再退 URL 参数（:205-207 亦有同逻辑）
}
```

### force Semantics and Degradation

标签规则的 `force` 默认是 `false`（`AbstractRouterRule.java:38`）；另一开关 `isForceUseTag` 读 `dubbo.force.tag`，默认 `"false"`（`TagStateRouter.java:235-238`），源码注释明确写着 "force.tag is set by default to false"（:143-144）。

当没有匹配标签的实例时，`force=false` 的降级行为是 **FAILOVER——回退到全部无标签实例**，而不是直接报无可用 Provider：

```java
// dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router/tag/TagStateRouter.java:152
if (filterUsingTag(invokers, tag) == null/empty ...) {
    if (force) {
        return BitList.emptyList();          // force=true：宁可报错也不放行
    }
    // force=false：FAILOVER，回退到全部「无标签」实例 (:152-161)
    result = invokers.clone();
    result.removeAll(filteredInvokers);      // 静态标签兜底 :137-142；filterUsingStaticTag :202-222
}
```

也就是说：给某批实例打了 `tag=gray` 后，只有带 `dubbo.tag=gray` 的请求会命中它们；其他请求落到无标签实例上。若想让「请求带了一个不存在的标签」直接失败（测试环境拦截错误流量），才需要 `force: true`。

静态标签（Provider 侧 `-Ddubbo.application.tag=xxx` 启动参数打的标签）是另一条腿：动态规则里某个 tag 标记 `enable: false` 时，请求可以降级匹配**静态标签相同的实例**（`filterUsingStaticTag` :202-222；:137-142 的兜底顺序）。完整匹配优先级：

```text
1. invocation attachment dubbo.tag == 动态规则中的 tag（enable 的）
2. 静态标签 == 动态规则中该 tag 的静态匹配
3. force=false：回退到全部无标签实例
4. force=true：空列表（宁可报错）
```

> [!TIP]
> 灰度发布的常见组合：新版本实例打 `tag=gray`（静态），网关/灰度 Consumer 请求 attachment 带 `dubbo.tag=gray`，标签路由自动把灰度流量圈在新实例上；灰度结束后删除规则即可，无需改任何实例配置。

## Mesh Rule Routing

`mesh/route/MeshRuleRouter.java:60` 是抽象类，配套 `StandardMeshRuleRouter` 与 `StandardMeshRuleRouterFactory`（SPI 名 `standard-mesh-rule`）。它的规则格式是 mesh 特有的 YAML/JSON 结构（`mesh/rule` 包），面向 xDS / Dubbo Mesh 场景——由控制面下发规则、数据面解析生效。

不需要把它当成第三种「语法体系」去学：MeshRuleRouter 与条件路由**共用 StateRouter 体系**（同样实现 `StateRouter`、同样挂在 StateRouter 链上、同样跑在 `simpleRoute` 的第一段），差异只在规则来源与格式。裸部署 Dubbo 3.3.6（无 Mesh 控制面）时不会触发该路由。

`StandardMeshRuleRouterFactory` 在 SPI 文件里的名字是 `standard-mesh-rule`，规则体通过 `mesh/rule` 包的模型解析为统一的 `MeshRule` 抽象，再按 `MeshRoute` 维度匹配实例。它的定位是「Dubbo 迁往 Mesh 架构后，K8s/Istio 控制面的流量规则落到 Dubbo 数据面的适配层」——如果你没有在用 Dubbo Mesh 或 xDS 下发，可以整节跳过。

## Current Status of Script and File Routing

`script/` 与 `file/` 子包在 3.3.6 源码树中依然存在：`ScriptStateRouter`（`script/config/AppScriptRouterFactory` 提供应用级订阅，SPI 名 `script-app`）支持 Groovy 脚本规则——脚本里写一段返回 `BitList` 过滤逻辑的代码；`file/` 子包则支持把路由规则放在本地文件。但如前所述，`script=`（除 `script-app` 外）与 `file=` **没有出现在主 resources 的 StateRouterFactory SPI 文件里**，仅在测试资源注册。结论：脚本路由理论上可用（`script-app` 已注册），file 路由则属于遗留能力，生产上不要依赖。

## Comparison of Three Rule Types

| 维度 | 条件路由 | 标签路由 | Mesh 规则 |
|---|---|---|---|
| SPI 扩展名 | `condition` | `tag` | `standard-mesh-rule` |
| 规则粒度 | 接口级 / 应用级 | 应用级（按 Provider 应用订阅） | Mesh 控制面下发 |
| 格式 | `when => then` 表达式 | YAML，`force` + `tags` 列表 | YAML/JSON（mesh 专有） |
| 典型用途 | 黑白名单、参数路由、读写分离 | 灰度发布、流量打标 | xDS 流量治理 |
| 请求侧打标方式 | 规则内 `arguments`/`attachments` | attachment / URL 参数 `dubbo.tag` | 控制面定义 |

## Default Value Summary

| 配置/字段 | 默认值 | 源码位置 |
|---|---|---|
| `AbstractRouterRule.force` | `false` | `AbstractRouterRule.java:38` |
| 规则 `runtime` | `false` | `AbstractRouterRule.java`（`ConditionStateRouter.java:100` 读取） |
| 规则 `enabled` | `true` | `AbstractRouterRule.java`（`ConditionStateRouter.java:285` 读取） |
| `dubbo.force.tag`（isForceUseTag） | `"false"` | `TagStateRouter.java:235-238` |
| 标签 key `dubbo.tag` | —（常量 `TAG_KEY`） | `CommonConstants.java:348` |
| mock 路由（`MockInvokersSelector`） | 常驻内置 | legacy 链，见 cluster.md |
| legacy `Router` 四参 route | 未废弃 | `Router.java:35,71-74` |

## Pitfall List

1. **类名全是旧版记忆**：`ConditionRouter`、`TagRouter`、`ScriptRouter`、`ServiceRouter` 在 3.3.6 整棵源码树中**已不存在**，实际是 `ConditionStateRouter`、`TagStateRouter`、`ScriptStateRouter`，以及语义拆分后的 `AppStateRouter` + `ServiceStateRouter`。照旧类名搜源码会一无所获。
2. **「StateRouter 是 3.3 新增」是错的**：接口 `@since 3.0`。
3. **返回值搞混**：StateRouter 返回 `BitList<Invoker>`；`RouterResult` 是 legacy 四参 `route()` 的返回类型。
4. **不存在的类与方法**：没有 `StateRouterChain`、没有 `StateRouter#getPriority()`、没有 `isPool`/`getPool`。
5. **条件路由运算符极其克制**：只有 `&`、`=`、`!=`、`,`。`in`/`not in`/`matches`/`any` 都不是语法，逗号分隔的多值即「in」语义。
6. **值不要带引号**：`arguments[0] = 'xxx'` 的引号参与字面比较，永远匹配不上；官方用例全部无引号。
7. **then 侧只能写 URL 参数**：`matchThen` 传 `invocation = null`，then 侧写 `method`/`arguments`/`attachments` 无效。
8. **`consumer.`/`provider.` 前缀是摆设**：解析前先被 `replace` 剥掉，写不写都一样，但写了会让人误以为有 Provider 侧独立语义。
9. **`script`/`file` 路由没在主 SPI 注册**：只在测试资源里出现；legacy `RouterFactory` 更是已无任何 SPI 注册文件。
10. **标签路由的降级不是容错**：`force=false` 时找不到标签实例会回退到**无标签实例**（FAILOVER），别误以为它会 failover 到「同标签的其他实例」——标签实例之间没有二次降级。
11. **`dubbo.force.tag` ≠ 规则 `force`**：前者是 Consumer 侧「强制使用标签」开关，后者是规则自身的「空结果不兜底」开关，两者独立。

## Links

- [Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)
- [cluster](/docs/CS/Framework/Dubbo/cluster.md)
- [LoadBalance](/docs/CS/Framework/Dubbo/LoadBalance.md)
- [Governance](/docs/CS/Framework/Dubbo/Governance.md)
- [registry](/docs/CS/Framework/Dubbo/registry.md)

## References

1. [dubbo-cluster router 源码](https://github.com/apache/dubbo/tree/3.3/dubbo-cluster/src/main/java/org/apache/dubbo/rpc/cluster/router)
2. [Dubbo 流量管控官方文档](https://cn.dubbo.apache.org/zh-cn/overview/core-features/traffic/)
