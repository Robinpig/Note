# RuleDataSource

## Introduction

> 版本基线：Sentinel 1.8.10

Sentinel 的规则（flow / degrade / system / authority / param-flow 等）不是从配置文件直接读进内存，而是统一经过 **Property → Listener → RuleManager** 的热更新通道：任何来源调用 `SentinelProperty.updateValue()`，注册在其上的 listener 就会重新构建规则表并整体替换 `RuleManager` 容器。动态数据源（Nacos / ZK / Apollo / File）本质只是「另一个会调 `updateValue()` 的入口」——它们把外部配置的变更翻译成一次 property 更新。

本篇纠正几处与旧资料/直觉冲突的地方：1.8.10 **没有** `AbstractRuleManager` 基类；两个数据源接口是拆开的；重复加载同一份规则**不会**触发更新；Nacos 适配器没有 `onRuleChanged` / `getRules`；以及控制台到客户端默认根本不经过配置中心。所有片段取自 tag `1.8.10`（commit `cf97bba`）。

## No Common RuleManager Base Class

一个常见误解是存在 `AbstractRuleManager` 抽象基类统一封装 property + listener。1.8.10 全树并无此类；每个 `*RuleManager` 各自持有一个 `SentinelProperty`、一个私有的 `PropertyListener` 内部类和一个 `RuleManager<R>` 容器，彼此平行、各自实现。

`slots/block/flow/FlowRuleManager.java` 的三个核心字段：

```java
public class FlowRuleManager {

    private static volatile RuleManager<FlowRule> flowRules = new RuleManager<>();

    private static final FlowPropertyListener LISTENER = new FlowPropertyListener();
    private static SentinelProperty<List<FlowRule>> currentProperty = new DynamicSentinelProperty<List<FlowRule>>();
```

它的监听者是私有内部类 `FlowPropertyListener`——注意名字。`configUpdate` / `configLoad` 都经 `FlowRuleUtil.buildFlowRuleMap` 构建 map 后整表替换：

```java
    private static final class FlowPropertyListener implements PropertyListener<List<FlowRule>> {

        @Override
        public synchronized void configUpdate(List<FlowRule> value) {
            Map<String, List<FlowRule>> rules = FlowRuleUtil.buildFlowRuleMap(value);
            flowRules.updateRules(rules);
            RecordLog.info("[FlowRuleManager] Flow rules received: {}", rules);
        }

        @Override
        public synchronized void configLoad(List<FlowRule> conf) {
            Map<String, List<FlowRule>> rules = FlowRuleUtil.buildFlowRuleMap(conf);
            flowRules.updateRules(rules);
            RecordLog.info("[FlowRuleManager] Flow rules loaded: {}", rules);
        }
    }
```

而 `DegradeRuleManager` 用的是**另一个**私有内部类、名字叫 `RulePropertyListener`（不是 `FlowPropertyListener`），且同时维护 `circuitBreakers` 与 `ruleMap` 两个容器——名字和数量都不一样，谈不上共享基类：

```java
    private static volatile RuleManager<CircuitBreaker> circuitBreakers = new RuleManager<>(DegradeRuleManager::generateCbs, cb -> cb.getRule().isRegex());
    private static volatile RuleManager<DegradeRule> ruleMap = new RuleManager<>();

    private static final RulePropertyListener LISTENER = new RulePropertyListener();
```

## The Hot-Reload Chain

以流控为例，完整的更新链是：`FlowRuleManager.loadRules` → `currentProperty.updateValue(rules)` → `DynamicSentinelProperty.updateValue` → `listener.configUpdate` → `buildFlowRuleMap` → `ruleManager.updateRules` 整表替换。入口极薄：

```java
    public static void loadRules(List<FlowRule> rules) {
        currentProperty.updateValue(rules);
    }
```

真正决定「是否触发更新」的是 `property/DynamicSentinelProperty.java`。它先 `isEqual` 判等，相等就**直接 return false**，既不通知 listener 也不打日志——这就是「重复加载同一份规则看起来没生效」的根因：不是没生效，而是内容相同被视为无需更新。

```java
    @Override
    public boolean updateValue(T newValue) {
        if (isEqual(value, newValue)) {
            return false;
        }
        RecordLog.info("[DynamicSentinelProperty] Config will be updated to: {}", newValue);

        value = newValue;
        for (PropertyListener<T> listener : listeners) {
            listener.configUpdate(newValue);
        }
        return true;
    }

    private boolean isEqual(T oldValue, T newValue) {
        if (oldValue == null && newValue == null) {
            return true;
        }

        if (oldValue == null) {
            return false;
        }

        return oldValue.equals(newValue);
    }
```

另一个隐藏契约在 `addListener`：注册监听器时**立即回调** `listener.configLoad(value)`，而 `value` 初始常为 `null`。所以自定义 listener 的 `configLoad` 必须容忍 `null`（内置管理器通过 `buildFlowRuleMap(null)` 返回空 map 来兜底）。

```java
    @Override
    public void addListener(PropertyListener<T> listener) {
        listeners.add(listener);
        listener.configLoad(value);
    }
```

正是这个机制让数据源能无缝接入：`register2Property` 把 manager 的 listener 转挂到数据源自带的 property 上，此后数据源一 `updateValue` 就走通全链。

```java
    public static void register2Property(SentinelProperty<List<FlowRule>> property) {
        AssertUtil.notNull(property, "property cannot be null");
        synchronized (LISTENER) {
            RecordLog.info("[FlowRuleManager] Registering new property to flow rule manager");
            currentProperty.removeListener(LISTENER);
            property.addListener(LISTENER);
            currentProperty = property;
        }
    }
```

## Two Separate DataSource Interfaces

数据源接口是**拆分**的：`ReadableDataSource<S, T>` 与 `WritableDataSource<T>` 是两个独立接口，并没有一个统一叫 `DataSource` 的接口同时约束读写。`datasource/ReadableDataSource.java`：

```java
public interface ReadableDataSource<S, T> {

    /**
     * Load data data source as the target type.
     *
     * @return the target data.
     * @throws Exception IO or other error occurs
     */
    T loadConfig() throws Exception;

    /**
     * Read original data from the data source.
     *
     * @return the original data.
     * @throws Exception IO or other error occurs
     */
    S readSource() throws Exception;

    /**
     * Get {@link SentinelProperty} of the data source.
     *
     * @return the property.
     */
    SentinelProperty<T> getProperty();

    /**
     * Close the data source.
     *
     * @throws Exception IO or other error occurs
     */
    void close() throws Exception;
}
```

`datasource/WritableDataSource.java` 只有写与关闭两个方法：

```java
public interface WritableDataSource<T> {

    /**
     * Write the {@code value} to the data source.
     *
     * @param value value to write
     * @throws Exception IO or other error occurs
     */
    void write(T value) throws Exception;

    /**
     * Close the data source.
     *
     * @throws Exception IO or other error occurs
     */
    void close() throws Exception;
}
```

`AbstractDataSource` 只实现读侧（implements `ReadableDataSource`），在构造时同时持有 `parser` 与**新建的** `DynamicSentinelProperty`——这个 property 就是 `getProperty()` 暴露给 `register2Property` 的那一个；`loadConfig` 把原始源数据经 `parser.convert` 转成目标类型。

```java
public abstract class AbstractDataSource<S, T> implements ReadableDataSource<S, T> {

    protected final Converter<S, T> parser;
    protected final SentinelProperty<T> property;

    public AbstractDataSource(Converter<S, T> parser) {
        if (parser == null) {
            throw new IllegalArgumentException("parser can't be null");
        }
        this.parser = parser;
        this.property = new DynamicSentinelProperty<T>();
    }

    @Override
    public T loadConfig() throws Exception {
        return loadConfig(readSource());
    }

    public T loadConfig(S conf) throws Exception {
        T value = parser.convert(conf);
        return value;
    }

    @Override
    public SentinelProperty<T> getProperty() {
        return property;
    }
}
```

## NacosDataSource: No onRuleChanged/getRules

Nacos 适配器是 `sentinel-extension/sentinel-datasource-nacos` 模块里的 `NacosDataSource`（不在 core），它**没有** `onRuleChanged` / `getRules` 方法——那是别的配置中心适配器或旧版本的叫法。它的对应物是一个 Nacos `Listener`：配置变更时 `receiveConfigInfo()` 把字符串经 `parser.convert` 转成规则，再 `getProperty().updateValue(newValue)` 灌进更新链。

```java
        this.configListener = new Listener() {
            @Override
            public Executor getExecutor() {
                return pool;
            }

            @Override
            public void receiveConfigInfo(final String configInfo) {
                RecordLog.info("[NacosDataSource] New property value received for (properties: {}) (dataId: {}, groupId: {}): {}",
                    properties, dataId, groupId, configInfo);
                T newValue = NacosDataSource.this.parser.convert(configInfo);
                // Update the new value to the property.
                getProperty().updateValue(newValue);
            }
        };
```

首次加载走 `loadInitialConfig()`，它调 `loadConfig()`（即 `readSource()` + `parser.convert`）；`readSource()` 用 `configService.getConfig(dataId, groupId, 3000)` 拉一次，超时常量 `DEFAULT_TIMEOUT = 3000`。注意构造器顺序：**先 `initNacosListener()` 挂监听，再 `loadInitialConfig()` 拉首份配置**——这个顺序避免挂在监听之后、拉取之前发生的变更丢失。

```java
    private void loadInitialConfig() {
        try {
            T newValue = loadConfig();
            if (newValue == null) {
                RecordLog.warn("[NacosDataSource] WARN: initial config is null, you may have to check your data source");
            }
            getProperty().updateValue(newValue);
        } catch (Exception ex) {
            RecordLog.warn("[NacosDataSource] Error when loading initial config", ex);
        }
    }
```

```java
    @Override
    public String readSource() throws Exception {
        if (configService == null) {
            throw new IllegalStateException("Nacos config service has not been initialized or error occurred");
        }
        return configService.getConfig(dataId, groupId, DEFAULT_TIMEOUT);
    }
```

推送用的线程池是刻意设计的**单线程 + 容量 1 的队列 + `DiscardOldestPolicy`**：推送过快时主动丢弃最旧任务，只保留最新配置，不做积压回放。

```java
    /**
     * Single-thread pool. Once the thread pool is blocked, we throw up the old task.
     */
    private final ExecutorService pool = new ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
        new ArrayBlockingQueue<Runnable>(1), new NamedThreadFactory("sentinel-nacos-ds-update", true),
        new ThreadPoolExecutor.DiscardOldestPolicy());
```

## Wiring Is Explicit, Not Automatic

最重要的一条纠偏：**core 不会自动把数据源挂到 RuleManager 上**。创建了 `NacosDataSource` 之后，必须显式调用 `FlowRuleManager.register2Property(ds.getProperty())` 才会生效。官方 demo `sentinel-demo-nacos-datasource` 的 `NacosDataSourceDemo` 就是这么写的：

```java
    private static void loadRules() {
        ReadableDataSource<String, List<FlowRule>> flowRuleDataSource = new NacosDataSource<>(remoteAddress, groupId, dataId,
                source -> JSON.parseObject(source, new TypeReference<List<FlowRule>>() {
                }));
        FlowRuleManager.register2Property(flowRuleDataSource.getProperty());
    }
```

少了最后一行，数据源照常连 Nacos、照常收变更，但规则永远进不了内存——这是接入动态数据源最常见的「配了没反应」。

## The Dashboard Boundary: Direct Push, Not Config Center

另一个常被想当然的点：「控制台改规则 → 写配置中心 → 数据源推送到客户端」。1.8.10 的默认链路**不是**这样。dashboard 的 `controller/v2/FlowControllerV2` 默认注入的是 `flowRuleDefaultProvider` / `flowRuleDefaultPublisher`：

```java
    @Autowired
    @Qualifier("flowRuleDefaultProvider")
    private DynamicRuleProvider<List<FlowRuleEntity>> ruleProvider;
    @Autowired
    @Qualifier("flowRuleDefaultPublisher")
    private DynamicRulePublisher<List<FlowRuleEntity>> rulePublisher;
```

`flowRuleDefaultPublisher` 对应的实现是 `rule/FlowRuleApiPublisher.java`，它用 `SentinelApiClient` 通过 HTTP **直推客户端**——遍历该 app 的健康机器，逐台调 `setFlowRuleOfMachine`，全程绕过 Nacos / ZK 等配置中心：

```java
@Component("flowRuleDefaultPublisher")
public class FlowRuleApiPublisher implements DynamicRulePublisher<List<FlowRuleEntity>> {

    @Autowired
    private SentinelApiClient sentinelApiClient;
    @Autowired
    private AppManagement appManagement;

    @Override
    public void publish(String app, List<FlowRuleEntity> rules) throws Exception {
        if (StringUtil.isBlank(app)) {
            return;
        }
        if (rules == null) {
            return;
        }
        Set<MachineInfo> set = appManagement.getDetailApp(app).getMachines();

        for (MachineInfo machine : set) {
            if (!machine.isHealthy()) {
                continue;
            }
            // TODO: parse the results
            sentinelApiClient.setFlowRuleOfMachine(app, machine.getIp(), machine.getPort(), rules);
        }
    }
}
```

真正的「控制台 → Nacos → 客户端」组件 `FlowRuleNacosPublisher` / `FlowRuleNacosProvider` 位于 **`sentinel-dashboard/src/test/.../rule/nacos/`**——是测试目录下的示例，不参与默认装配。要改成经 Nacos 中转，必须自己实现这两个 Bean 并替换掉 `FlowControllerV2` 里 `@Qualifier` 指定的默认实现，同时让客户端侧接上 `NacosDataSource` 并 `register2Property`。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [集群流控 ClusterFlow](/docs/CS/Framework/Sentinel/ClusterFlow.md)

## References

- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/property/DynamicSentinelProperty.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/property/SentinelProperty.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/flow/FlowRuleManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/degrade/DegradeRuleManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-extension/sentinel-datasource-extension/src/main/java/com/alibaba/csp/sentinel/datasource/ReadableDataSource.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-extension/sentinel-datasource-extension/src/main/java/com/alibaba/csp/sentinel/datasource/WritableDataSource.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-extension/sentinel-datasource-extension/src/main/java/com/alibaba/csp/sentinel/datasource/AbstractDataSource.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-extension/sentinel-datasource-nacos/src/main/java/com/alibaba/csp/sentinel/datasource/nacos/NacosDataSource.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-demo/sentinel-demo-nacos-datasource/src/main/java/com/alibaba/csp/sentinel/demo/datasource/nacos/NacosDataSourceDemo.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-dashboard/src/main/java/com/alibaba/csp/sentinel/dashboard/controller/v2/FlowControllerV2.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-dashboard/src/main/java/com/alibaba/csp/sentinel/dashboard/rule/FlowRuleApiPublisher.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-dashboard/src/test/java/com/alibaba/csp/sentinel/dashboard/rule/nacos/FlowRuleNacosPublisher.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-dashboard/src/test/java/com/alibaba/csp/sentinel/dashboard/rule/nacos/FlowRuleNacosProvider.java>
