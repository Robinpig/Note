## Introduction

Dubbo 没有直接使用 Java 原生的 [SPI](/docs/CS/Java/JDK/Basic/SPI.md)，而是把「加载扩展」重写了一遍，并且从 3.0 开始在这套机制之上压了一整层**域模型（ScopeModel）**。这一层是本篇最容易写错的地方，也是旧版资料几乎不提的地方。

先说清三个反直觉的事实，它们构成本篇的主线：

1. **`@SPI` 注解只有两个属性：`value` 和 `scope`。** 流传很广的「`@SPI(value, dependencies, scope, order)` 四属性」写法是错的——`dependencies` 从来不存在，`order` 属于 `@Activate` 而不是 `@SPI`（`Activate.java:93` 的默认值是 `0`）。3.3.6 的定义只有几行有效代码，见下文。
2. **`ExtensionLoader.getExtensionLoader(Class)` 已经 `@Deprecated`**，而且 `resetExtensionLoader(Class)` 是**空方法体**。原因不在「不推荐」，而在语义：没有 `ScopeModel` 参数时它只能返回「默认 ApplicationModel 的默认 ModuleModel」里的加载器，这在一个进程跑多个 Dubbo 应用时会拿错实例。带 `ScopeModel` 的新入口在 `ScopeModelUtil` 上，不在 `ExtensionLoader` 上。
3. **`ExtensionLoader` 里已经没有 `EXTENSION_LOADERS` / `EXTENSION_INSTANCES` 这两个静态 Map 了**。3.x 把「谁负责缓存某个类型的扩展加载器」这件事上移给了 `ExtensionDirector`，把「谁负责缓存某个类型的扩展实例」下放成了 `ExtensionLoader` 的**实例字段**。所以旧笔记里「`ExtensionLoader` 是静态单例容器」的整段描述在 3.3.6 里是错的。

那么「扩展实例属于哪个模型」这个问题由谁回答？答案是 `@SPI` 上的 `scope()` 属性。它决定了这个 SPI 的实现类实例会被挂到 `FrameworkModel` / `ApplicationModel` / `ModuleModel` 中的哪一层去，是全局一份、一个应用一份，还是一个服务模块一份。这是 Dubbo 3.x 最大的架构变化，也是本篇新增篇幅最多的部分。

本文版本基线：**Apache Dubbo 3.3.6**（tag `dubbo-3.3.6`）。所有代码块、SPI 文件内容、方法签名均逐文件核对自源码树，代码块首行注释给出文件路径与行号。本篇不重复 [ScopeModel](/docs/CS/Framework/Dubbo/ScopeModel.md) 中的模型树与生命周期叙述，只讲**它如何决定扩展加载与实例归属**；扩展点的实际用法见 [Filter](/docs/CS/Framework/Dubbo/Filter.md) 与 [cluster](/docs/CS/Framework/Dubbo/cluster.md)。

## Why Not Use Java SPI Directly

这一节的思想在 3.3.6 里没有变化，是理解 Dubbo 扩展设计的动机基础。Java SPI 的主要缺陷有五个：

- **一次性实例化所有扩展实现**。`ServiceLoader` 拿到 `Iterator` 后 Dubbo 若要遍历就会触发全部实现类的加载与初始化，实例化那些本次运行根本用不到的扩展点，浪费资源、拉长启动时间。
- **加载失败会连扩展名一起丢掉**。JDK 标准的 `ScriptEngine` 通过 `getName()` 暴露脚本类型名，但如果 `RubyScriptEngine` 因缺少 jruby.jar 而加载失败，这个异常会被吞掉，用户执行 ruby 脚本时只会得到「不支持 ruby」，看不到真正的失败原因。
- **不支持依赖注入**。扩展点里 `setXxx(依赖)` 无人处理。
- **获取实现的方式单一**，只能遍历，没有「按 key 取一个」。
- **没有 AOP**，无法自动给扩展套包装类。

Dubbo 的对应增强：按需加载（只加载类，首次 `getExtension` 才实例化）、IoC（setter 反射注入）、AOP（自动发现 Wrapper）、自适应扩展（`@Adaptive`，运行时按 URL 参数选实现）、自动激活（`@Activate`，按 group/value/order 筛选与排序）。

配置格式也从「一行一个类名」改成 key-value：

```properties
# META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol
dubbo=org.apache.dubbo.rpc.protocol.dubbo.DubboProtocol
tri=org.apache.dubbo.rpc.protocol.tri.TripleProtocol
```

理由与 `@SPI` 注解的 javadoc 一致：如果扩展实现的静态字段或方法引用了第三方库，第三方库缺失时类初始化就会失败。若用旧格式（只写类名），Dubbo 连扩展的 id 都拿不到，无法把异常映射回具体扩展；改成 key-value 后，至少能报出「加载 `xxx` 扩展失败」并附上真实原因。

## @SPI Annotation

3.3.6 的定义只有这么几行：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/SPI.java:53-67
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target({ElementType.TYPE})
public @interface SPI {
    /**
     * default extension name
     */
    String value() default "";

    /**
     * scope of SPI, default value is application scope.
     */
    ExtensionScope scope() default ExtensionScope.APPLICATION;
}
```

> [!WARNING]
> `@SPI` 上**没有** `dependencies`，也**没有** `order`。`order` / `before` / `after` / `onClass` 都在 `@Activate` 上（`Activate.java:45-99`）。看到把 `order` 写进 `@SPI` 的代码或文档，一律是错的。

标注在接口上，形如：

```java
// dubbo-rpc/dubbo-rpc-api/src/main/java/org/apache/dubbo/rpc/Protocol.java:58
@SPI(value = "dubbo", scope = ExtensionScope.FRAMEWORK)
public interface Protocol {
    @Adaptive({Constants.PROTOCOL_KEY})
    <T> Exporter<T> export(Invoker<T> invoker) throws RpcException;
}
```

不同扩展点选不同的 scope，这直接决定了实例的复用范围：

| 扩展点 | 3.3.6 注解 | 位置 |
| --- | --- | --- |
| `Protocol` | `@SPI(value = "dubbo", scope = FRAMEWORK)` | `Protocol.java:58` |
| `Compiler` | `@SPI(value = "javassist", scope = FRAMEWORK)` | `Compiler.java:25` |
| `Converter` / `MultiValueConverter` | `@SPI(scope = FRAMEWORK)` | `Converter.java:33`、`MultiValueConverter.java:36` |
| `ThreadPool` | `@SPI(value = "fixed", scope = FRAMEWORK)` | `ThreadPool.java:29` |
| `Filter` | `@SPI(scope = MODULE)` | `Filter.java:68` |
| `ModuleExt` / `ModuleDeployListener` | `@SPI(scope = MODULE)` | `ModuleExt.java:22` |
| `ApplicationExt` / `ApplicationInitListener` | `@SPI(scope = APPLICATION)` | `ApplicationExt.java:22` |
| `InfraAdapter` / `DataStore` / `StatusChecker` | `@SPI(scope = APPLICATION)` | `InfraAdapter.java:29` 等 |
| `ExtensionInjector` | `@SPI(scope = SELF)` | `ExtensionInjector.java:22` |

### Four Values of ExtensionScope

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionScope.java
public enum ExtensionScope {
    FRAMEWORK,    // 框架内共享，可拿到 FrameworkModel，拿不到 ApplicationModel / ModuleModel
    APPLICATION,  // 一个应用一份，应用内所有模块共享
    MODULE,       // 一个模块一份，可拿到三层模型
    SELF          // 每个作用域各创建一份，给特殊 SPI 用，例如 ExtensionInjector
}
```

这四条约束不是装饰性的注释，而是 `ExtensionDirector` 实际路由的依据，见下一节。

## The Other Three Core Annotations: @Activate, @Wrapper, @DisableInject

`@SPI` 决定「类型层面」的扩展点语义，而另三个注解作用在「实现类层面」，共同构成 Dubbo SPI 的完整契约：`@Activate`（自动激活）、`@Wrapper`（AOP 包装）、`@DisableInject`（禁用某 setter 的自动注入）。它们都位于 `org.apache.dubbo.common.extension`。

### @Activate

自动激活注解，贴在扩展实现类上，让 `getActivateExtension(url, values, group)` 按 `group` / `value` / `onClass` 自动筛选并排序。完整定义（`Activate.java:45-100`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/Activate.java:45-100
public @interface Activate {
    String[] group() default {};        // :53  URL 侧触发的分组, 如 CONSUMER / PROVIDER
    String[] value() default {};        // :66  URL 参数 key, 命中即激活 (支持 "k:v" 精确值)
    @Deprecated
    String[] before() default {};       // :75  排序: 排在某些扩展之前 (2.7.0 起废弃)
    @Deprecated
    String[] after() default {};        // :84  排序: 排在某些扩展之后 (2.7.0 起废弃)
    int order() default 0;              // :93  排序权重, 升序, 默认 0 (不是 -1)
    String[] onClass() default {};      // :99  类路径条件: 列出的类全部存在才加载该扩展
}
```

要点：

- **`order` 默认 `0`**，不是 `-1`。升序排列，值越小越靠前；`order` 相同再按类名 `getSimpleName()` 字典序兜底（`ActivateComparator.java:117-123`）。
- **`before` / `after` 已 `@Deprecated`**（自 2.7.0），但排序逻辑仍支持；若同时写了 `before/after` 与 `order`，**`before/after` 约束优先**（`ActivateComparator.java:72-111`）。新代码应只用 `order`。
- `group` 与 `value` 是激活的「开关」：`group` 不匹配直接忽略；`value` 是 URL 参数名（支持 `k:v` 精确值匹配）。二者都在加载阶段被预解析进 `cachedActivateGroups` / `cachedActivateValues`（`ExtensionLoader.java:906-941`），详见 [Activation and Sorting](/docs/CS/Framework/Dubbo/SPI.md?id=activation-and-sorting)。
- `onClass` 在 `loadClassIfActive`（`ExtensionLoader.java:1309-1333`）阶段做类存在性校验——指定的类**全部存在**才把这个扩展类加载进来，否则整类跳过。这是「类路径条件加载」的核心。

### @Wrapper

AOP 包装注解，贴在 wrapper 实现类上，控制它包裹哪些具体扩展。`@Wrapper` 本身没有 `@Target` 限定（默认可用于任意声明处），完整定义（`Wrapper.java:26-45`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/Wrapper.java:26-45
public @interface Wrapper {
    String[] matches() default {};     // :32  只包裹 name 在 matches 里的扩展
    String[] mismatches() default {};  // :37  永不包裹 name 在 mismatches 里的扩展
    int order() default 0;             // :44  包裹顺序, 默认 0
}
```

要点：

- wrapper 判定与 `@Wrapper` 本身无关——`isWrapperClass`（`ExtensionLoader.java:1410-1418`）只看「构造器有且仅有一个 `type` 类型参数」。`@Wrapper` 只是**选择性包裹**的开关：`matches` 为空表示全匹配，`mismatches` 永远排除（见 [AOP](/docs/CS/Framework/Dubbo/SPI.md?id=aop) 一节的包裹逻辑）。
- 多个 wrapper 按 `WrapperComparator` 排序（默认 `order` 升序）后反转，再逐层包裹。包裹后的实例同样会走一遍前后置处理与 IoC 注入。

### @DisableInject

标记注解（无属性），贴在扩展类的某个 setter 方法上，告诉 `injectExtension` 不要对该属性做自动依赖注入（`DisableInject.java:25-28`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/DisableInject.java:25-28
@Documented
@Retention(RetentionPolicy.RUNTIME)
@Target({ElementType.TYPE, ElementType.METHOD})
public @interface DisableInject {}
```

典型用途：扩展类自己通过其他方式（如 `ExtensionAccessor`）拿依赖，不希望被反射 setter 注入覆盖。

## ScopeModel: Which Model an Extension Instance Belongs To

### Three-Layer Model

Dubbo 3.x 把「静态单例」拆成了一棵模型树，三个节点都继承 `ScopeModel`（`ScopeModel.java:41`）：

- `FrameworkModel`（`FrameworkModel.java:43`）——框架级，一个 JVM 内可以有多个实例，彼此不共享应用状态。持有全部 `ApplicationModel` 集合、`FrameworkServiceRepository`，以及默认实例 `FrameworkModel.defaultModel()`（`FrameworkModel.java:179`）。
- `ApplicationModel`（`ApplicationModel.java:53`）——一个「正在使用 Dubbo 的应用」，存 `ProviderModel` / `ConsumerModel` 等元数据，`ApplicationModel.defaultModel()` 实际是 `FrameworkModel.defaultModel().defaultApplication()`。
- `ModuleModel`（`ModuleModel.java:40`）——一个「服务模块」，对应老版本里 DubboBootstrap 的粒度，也是 `@SPI(scope = MODULE)` 扩展实例的最小隔离单位。

`ScopeModel` 自身持有父引用、作用域类型、一组累积的 ClassLoader、一个 `ExtensionDirector` 和一个 `ScopeBeanFactory`（`ScopeModel.java:62-77`）。`initialize()` 里创建 `ExtensionDirector` 并把 Dubbo 自己的 ClassLoader 加进去：

```java
// dubbo-common/src/main/java/org/apache/dubbo/rpc/model/ScopeModel.java:100-113
protected void initialize() {
    synchronized (instLock) {
        this.extensionDirector =
                new ExtensionDirector(parent != null ? parent.getExtensionDirector() : null, scope, this);
        this.extensionDirector.addExtensionPostProcessor(new ScopeModelAwareExtensionProcessor(this));
        this.beanFactory = new ScopeBeanFactory(parent != null ? parent.getBeanFactory() : null, extensionDirector);

        // Add Framework's ClassLoader by default
        ClassLoader dubboClassLoader = ScopeModel.class.getClassLoader();
        if (dubboClassLoader != null) {
            this.addClassLoader(dubboClassLoader);
        }
    }
}
```

> [!TIP]
> `addClassLoader` 会**递归加到所有父模型**（`ScopeModel.java:227-236`），也就是说子模型加的 ClassLoader 对父模型同样可见。这是子类加载器场景下扩展能被父层找到的原因。

### ExtensionDirector: The Actual Executor of scope

`ExtensionDirector` 逐层对应一个 `ScopeModel`，它实现的查找逻辑类似 ClassLoader 的双亲委派，但**第一道门是 scope 匹配**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionDirector.java:67-107
@Override
@SuppressWarnings("unchecked")
public <T> ExtensionLoader<T> getExtensionLoader(Class<T> type) {
    checkDestroyed();
    if (type == null) {
        throw new IllegalArgumentException("Extension type == null");
    }
    if (!type.isInterface()) {
        throw new IllegalArgumentException("Extension type (" + type + ") is not an interface!");
    }
    if (!withExtensionAnnotation(type)) {
        throw new IllegalArgumentException("Extension type (" + type
                + ") is not an extension, because it is NOT annotated with @" + SPI.class.getSimpleName() + "!");
    }

    // 1. find in local cache
    ExtensionLoader<T> loader = (ExtensionLoader<T>) extensionLoadersMap.get(type);

    ExtensionScope scope = extensionScopeMap.get(type);
    if (scope == null) {
        SPI annotation = type.getAnnotation(SPI.class);
        scope = annotation.scope();
        extensionScopeMap.put(type, scope);
    }

    if (loader == null && scope == ExtensionScope.SELF) {
        // create an instance in self scope
        loader = createExtensionLoader0(type);
    }

    // 2. find in parent
    if (loader == null) {
        if (this.parent != null) {
            loader = this.parent.getExtensionLoader(type);
        }
    }

    // 3. create it
    if (loader == null) {
        loader = createExtensionLoader(type);
    }

    return loader;
}
```

关键在第 3 步的 `createExtensionLoader`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionDirector.java:109-130
private <T> ExtensionLoader<T> createExtensionLoader(Class<T> type) {
    ExtensionLoader<T> loader = null;
    if (isScopeMatched(type)) {
        // if scope is matched, just create it
        loader = createExtensionLoader0(type);
    }
    return loader;
}

private boolean isScopeMatched(Class<?> type) {
    final SPI defaultAnnotation = type.getAnnotation(SPI.class);
    return defaultAnnotation.scope().equals(scope);
}
```

把三步合起来读，`@SPI(scope)` 的语义就完全确定了：

| scope | 行为 | 为什么 |
| --- | --- | --- |
| `FRAMEWORK` | 只有 `FrameworkModel` 的 Director 能 `isScopeMatched`，创建后 ApplicationModel 找不到就往上委派命中它 | 全进程一份，无状态最安全 |
| `APPLICATION` | `FrameworkModel` 层 `isScopeMatched` 为 false，委派到 `ApplicationModel` 才创建 | 不同应用要隔离数据，应用内模块共享 |
| `MODULE` | 前两层都不匹配，直到某个 `ModuleModel` 才创建 | 服务级隔离，每个模块一份 |
| `SELF` | 跳过第 2 步委派，第 1 步判空后直接 `createExtensionLoader0` | 每一层都必须有一份自己的，不能向上共享 |

> [!NOTE]
> `SELF` 只在 `loader == null` 时才创建，且不走父委派。这正是 `ExtensionInjector` 选 `SELF` 的原因：依赖注入器必须**每个模型一份**，否则 ModuleModel 想注入依赖时会拿到 ApplicationModel 或 FrameworkModel 的注入器，跨作用域泄漏。

### The Correct Way to Get ExtensionLoader

三个层次，从旧到新：

```java
// 1. 已废弃：拿到的是「默认 ApplicationModel 的默认 ModuleModel」的加载器
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:240-247
@Deprecated
public static <T> ExtensionLoader<T> getExtensionLoader(Class<T> type) {
    return ApplicationModel.defaultModel().getDefaultModule().getExtensionLoader(type);
}

@Deprecated
public static void resetExtensionLoader(Class type) {}
```

`resetExtensionLoader` 在 3.3.6 里是**完全空的方法体**，不是「实现被简化」——它只保留符号兼容，调用它什么都不做。

正确做法是从 `ScopeModel` 上取，因为 `ScopeModel implements ExtensionAccessor`，而 `ExtensionAccessor` 把 `getExtensionLoader` / `getExtension` / `getAdaptiveExtension` 都定义成了 default 方法（`ExtensionAccessor.java:28-52`）。`ScopeModelUtil` 则解决了「手上只有一个 `ScopeModel`，或者连 `ScopeModel` 都没有」这两种情况：

```java
// dubbo-common/src/main/java/org/apache/dubbo/rpc/model/ScopeModelUtil.java:100-118
public static <T> ExtensionLoader<T> getExtensionLoader(Class<T> type, ScopeModel scopeModel) {
    if (scopeModel != null) {
        return scopeModel.getExtensionLoader(type);
    } else {
        SPI spi = type.getAnnotation(SPI.class);
        if (spi == null) {
            throw new IllegalArgumentException("SPI annotation not found for class: " + type.getName());
        }
        switch (spi.scope()) {
            case FRAMEWORK:
                return FrameworkModel.defaultModel().getExtensionLoader(type);
            case APPLICATION:
                return ApplicationModel.defaultModel().getExtensionLoader(type);
            case MODULE:
                return ApplicationModel.defaultModel().getDefaultModule().getExtensionLoader(type);
            default:
                throw new IllegalArgumentException("Unable to get ExtensionLoader for type: " + type.getName());
        }
    }
}
```

`scopeModel == null` 时按 `spi.scope()` 退化到对应的默认模型——这就是 `@SPI(scope)` 的「自动路由」形态，也是 `AdaptiveClassCodeGenerator` 生成的代码里那条 `ScopeModel scopeModel = ScopeModelUtil.getOrDefault(url.getScopeModel(), Xxx.class);` 的由来（`AdaptiveClassCodeGenerator.java:74-79`）。

> [!TIP]
> `ScopeModelUtil.getExtensionLoader(Class, ScopeModel)` 这个签名**在 `ScopeModelUtil` 上，不在 `ExtensionLoader` 上**。`ExtensionLoader` 上那个只有单参版本，而且已废弃。

### Model Destruction

`ScopeModel.destroy()`（`ScopeModel.java:117-141`）按 `onDestroy → 逐个 removeClassLoader → beanFactory.destroy → extensionDirector.destroy()` 的顺序收尾；`ExtensionDirector.destroy()` 再逐个调 `ExtensionLoader.destroy()`，后者销毁自己缓存的 `Disposable` 扩展实例（`ExtensionLoader.java:249-278`）。销毁后 `ExtensionLoader` 的 `destroyed` 标志置位，所有取实例的入口都会先 `checkDestroyed()` 抛异常：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:281-285
private void checkDestroyed() {
    if (destroyed.get()) {
        throw new IllegalStateException("ExtensionLoader is destroyed: " + type);
    }
}
```

`ExtensionLoader.destroy()`（`ExtensionLoader.java:249-279`）的具体销毁逻辑：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:249-279 (节选)
public void destroy() {
    if (!destroyed.compareAndSet(false, true)) {
        return;                                            // 幂等: 已销毁直接返回
    }
    // 1. 原始扩展实例
    extensionInstances.forEach((type, instance) -> {
        if (instance instanceof Disposable) {
            try { ((Disposable) instance).destroy(); }
            catch (Exception e) { logger.error(...); }
        }
    });
    extensionInstances.clear();
    // 2. 包装后实例 (cachedInstances 里的 Holder)
    for (Holder<Object> holder : cachedInstances.values()) {
        Object wrapped = holder.get();
        if (wrapped instanceof Disposable) {
            try { ((Disposable) wrapped).destroy(); }
            catch (Exception e) { logger.error(...); }
        }
    }
    cachedInstances.clear();
}
```

要点：

- **销毁遍历两个缓存**：`extensionInstances`（裸实例）与 `cachedInstances`（经 wrapper 包裹后的实例 `Holder`）。3.3.6 **没有** `disposableInstances` 字段——旧笔记里的这个名字是错的。
- 只有 `instance instanceof Disposable` 才调 `destroy()`。`Disposable` 接口（`dubbo-common/.../common/resource/Disposable.java:22-25`）签名极简：`void destroy();`（**没有 `throws Exception`**，实现里抛异常会被 `catch` 吞掉并仅记 error 日志，不会中断后续销毁）。
- `destroy()` 用 `AtomicBoolean.compareAndSet` 保证幂等，`destroyed` 置位后所有 `getExtension` / `getAdaptiveExtension` / `getActivateExtension` 入口的 `checkDestroyed()` 都会抛 `IllegalStateException`。

#### Enumerating Extensions: getSupportedExtensions vs getLoadedExtensions

两个枚举 API 都返回 `Set<String>`（用 `TreeSet` 包成不可变集合，天然有序）：

| 方法 | 行号 | 数据来源 | 语义 |
| --- | --- | --- | --- |
| `getSupportedExtensions()` | `:614-618` | `getExtensionClasses()` → `cachedClasses` | 所有**已识别**的扩展名（SPI 文件里声明的，未必都实例化） |
| `getLoadedExtensions()` | `:532-534` | `cachedInstances.keySet()` | 当前**已创建实例**的扩展名 |

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:614-618
public Set<String> getSupportedExtensions() {
    checkDestroyed();
    Map<String, Class<?>> classes = getExtensionClasses();
    return Collections.unmodifiableSet(new TreeSet<>(classes.keySet()));
}
// :532-534
public Set<String> getLoadedExtensions() {
    return Collections.unmodifiableSet(new TreeSet<>(cachedInstances.keySet()));
}
```

通常要「列出某 SPI 类型支持的全部扩展」用 `getSupportedExtensions()`；要「看哪些已经被实例化（含 wrapper 后的 key）」才用 `getLoadedExtensions()`。

## ExtensionLoader Core Fields and Lifecycle

### Fields

3.3.6 的字段列表与旧版差异极大。三个静态 Map 里的 `EXTENSION_LOADERS` / `EXTENSION_INSTANCES` **已删除**，`objectFactory` **已改名**为 `injector` 且类型从 `ExtensionFactory` 变成 `ExtensionInjector`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:115-160
private static final String SPECIAL_SPI_PROPERTIES = "special_spi.properties";

private final ConcurrentMap<Class<?>, Object> extensionInstances = new ConcurrentHashMap<>(64);

private final Class<?> type;

private final ExtensionInjector injector;

private final ConcurrentMap<Class<?>, String> cachedNames = new ConcurrentHashMap<>();

private final ReentrantLock loadExtensionClassesLock = new ReentrantLock();
private final Holder<Map<String, Class<?>>> cachedClasses = new Holder<>();

private final Map<String, Object> cachedActivates = Collections.synchronizedMap(new LinkedHashMap<>());
private final Map<String, Set<String>> cachedActivateGroups = Collections.synchronizedMap(new LinkedHashMap<>());
private final Map<String, String[][]> cachedActivateValues = Collections.synchronizedMap(new LinkedHashMap<>());
private final ConcurrentMap<String, Holder<Object>> cachedInstances = new ConcurrentHashMap<>();
// ... cachedAdaptiveInstance / cachedAdaptiveClass / cachedDefaultName 略

private static final Map<String, String> specialSPILoadingStrategyMap = getSpecialSPILoadingStrategyMap();

private final ExtensionDirector extensionDirector;
private final List<ExtensionPostProcessor> extensionPostProcessors;
private InstantiationStrategy instantiationStrategy;
private final ActivateComparator activateComparator;
private final ScopeModel scopeModel;
private final AtomicBoolean destroyed = new AtomicBoolean();
```

对照关系：

| 旧字段（2.7 / 旧笔记） | 3.3.6 归属 | 说明 |
| --- | --- | --- |
| `static EXTENSION_LOADERS` | `ExtensionDirector.extensionLoadersMap` | 缓存上移，按模型分桶 |
| `static EXTENSION_INSTANCES` | `ExtensionLoader.extensionInstances`（实例字段） | 缓存下移，按模型隔离 |
| `ExtensionFactory objectFactory` | `ExtensionInjector injector` | 接口换代，见 IoC 一节 |
| `synchronized (cachedClasses)` | `ReentrantLock loadExtensionClassesLock` | 显式锁 |
| `ActivateComparator.COMPARATOR`（静态） | `activateComparator`（实例） | 需要 `ExtensionDirector` 才能构造 |
| `findClassLoader()` | `scopeModel.getClassLoaders()` | 方法已删除 |

`extensionInstances` 从静态降为实例字段，是 3.x 里「同一进程多应用不串味」最直接的体现：两个 `ApplicationModel` 各自 `getExtension` 同一个 SPI 类型时，`Class<?>` 相同但 `ExtensionLoader` 不同，`putIfAbsent` 落在不同的 Map 里，不会互相覆盖。

构造器签名也变了，注入器自身是延迟取的：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:216-224
ExtensionLoader(Class<?> type, ExtensionDirector extensionDirector, ScopeModel scopeModel) {
    this.type = type;
    this.extensionDirector = extensionDirector;
    this.extensionPostProcessors = extensionDirector.getExtensionPostProcessors();
    initInstantiationStrategy();
    this.injector = (type == ExtensionInjector.class
            ? null
            : extensionDirector.getExtensionLoader(ExtensionInjector.class).getAdaptiveExtension());
    this.activateComparator = new ActivateComparator(extensionDirector);
    this.scopeModel = scopeModel;
}
```

`type == ExtensionInjector.class` 时注入器为 `null`，防止 `injectExtension` 递归注入自己。

### Five Steps to Obtain an Extension

`getExtension(name, wrap)` 的双检锁结构与旧版一致，但入口多了两道校验（`ExtensionLoader.java:557-566`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:557-566
public T getExtension(String name, boolean wrap) {
    checkDestroyed();
    if (StringUtils.isEmpty(name)) {
        throw new IllegalArgumentException("Extension name == null");
    }
    if ("true".equals(name)) {
        return getDefaultExtension();
    }
    String cacheKey = name;
    if (!wrap) {
        cacheKey += "_origin";
    }
    final Holder<Object> holder = getOrCreateHolder(cacheKey);
```

注意 `cacheKey`：`wrap` 与否会缓存成两个不同的 key，所以 `getOriginalInstance` 与 `getExtension` 不会互相污染。

流程仍是五步：解析配置文件 → 加载实现类 → 实例化 → 依赖注入 → 包装类处理并返回。

### Default Extension Name Resolution

「默认扩展」由 `@SPI(value = "...")` 决定。`loadExtensionClasses()` 在扫描类之前先调 `cacheDefaultExtensionName()`（`ExtensionLoader.java:989` → `:1026-1043`），它读接口上的 `@SPI.value()`，按 `NAME_SEPARATOR`（`=`,`,`,`;` 等）切分：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1026-1043
private void cacheDefaultExtensionName() {
    final SPI defaultAnnotation = type.getAnnotation(SPI.class);
    if (defaultAnnotation == null) {
        return;
    }
    String value = defaultAnnotation.value();
    if ((value = value.trim()).length() > 0) {
        String[] names = NAME_SEPARATOR.split(value);
        if (names.length > 1) {
            throw new IllegalStateException("More than 1 default extension name on extension " + type.getName());
        }
        if (names.length == 1) {
            cachedDefaultName = names[0];   // 存入缓存
        }
    }
}
```

注意：**`@SPI` 的 `value` 只能写一个默认名**，写多个会直接抛 `IllegalStateException`（不是选第一个）。`getDefaultExtension()`（`ExtensionLoader.java:597-603`）就是先触发类加载、再用 `cachedDefaultName` 取实例：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:597-603
public T getDefaultExtension() {
    getExtensionClasses();                              // 触发 loadExtensionClasses -> cacheDefaultExtensionName
    if (StringUtils.isBlank(cachedDefaultName) || "true".equals(cachedDefaultName)) {
        return null;                                    // 接口没标 @SPI.value 时返回 null
    }
    return getExtension(cachedDefaultName);
}
```

`getExtension("true")` 也会回落到默认扩展（`getExtension` 在 `:359` 判断 `"true".equals(name)` 直接 `getDefaultExtension()`），这是 Dubbo 内部用 `"true"` 表达「取默认」的约定。

### End-to-End: From getExtension(name) to a Returned Instance

把前面碎片拼成一条完整链路——用户调用 `extensionLoader.getExtension("dubbo")`（或 `getExtension("dubbo", true)`）到拿到实例：

```text
getExtension(name, wrap=true)                 // :557  checkDestroyed + 空/true 判定 + cacheKey(含 _origin 区分 wrap)
  └─ getOrCreateHolder(cacheKey)              // 取/建 Holder<Object>
       └─ createExtension(name, wrap)         // :773  (cachedClasses 命中才进; 否则 findException)
            ├─ getExtensionClasses()          // :955  DCL + ReentrantLock -> loadExtensionClasses
            │    └─ loadExtensionClasses()    // :987  cacheDefaultExtensionName + 遍历 strategies
            │         └─ loadDirectory / loadResource / loadClass   // 见 Loading Process
            ├─ extensionInstances.get(clazz)  // :664  实例级缓存 (putIfAbsent)
            ├─ createExtensionInstance(clazz) // :825  -> InstantiationStrategy.instantiate
            ├─ postProcessBeforeInitialization// :668  各 ExtensionPostProcessor.before
            ├─ injectExtension(instance)      // :669  setter 反射注入 (ExtensionInjector)
            ├─ postProcessAfterInitialization // :672  含 ScopeModelAware / ExtensionAccessorAware 注入
            ├─ if (wrap) { ... wrapper 逐层包裹 ... }   // :684-707
            └─ initExtension(instance)        // :711  Lifecycle.initialize() 钩子
```

几个关键细节：

- **返回的是「最外层 wrapper」还是「裸实例」取决于 `wrap` 参数**。`getExtension(name)`（单参）默认 `wrap = true`，所以消费侧拿到的 `Protocol` / `Filter` 是已被所有匹配 wrapper 包裹过的对象；`getExtension(name, false)` 拿裸实例（内部 `cacheKey += "_origin"`，`:363-365`）。
- **普通扩展名与 wrapper 不混在同一 Map**：`getExtensionClasses()` 返回的是 `cachedClasses`（仅普通扩展），wrapper 存在独立的 `cachedWrapperClasses`（`loadClass` 在 `:1287-1288` 分流）。没有公开的 `getWrapperClasses()` API——wrapper 完全由框架在 `createExtension` 的 `wrap` 分支自动套用。
- 实例创建后**只做一次** `postProcess + inject + init`：因为 `extensionInstances` 用 `putIfAbsent`，并发取同一个扩展只会初始化一次。

### findException: Backtrace the Loading Failure

当用户 `getExtension("xxx")` 但该类在加载阶段就失败（例如第三方库缺失、`NoClassDefFoundError`），`createExtension` 在 `:774` 取不到 class 会调 `findException(name)`（`ExtensionLoader.java:748-770`）抛错。加载阶段每个失败的行都会被 `loadResource` 捕获并记入 `exceptions` Map（`:1173-1178`，key 是配置文件那一行的内容，value 是**带原始 cause `t`** 的 `IllegalStateException`）。

`findException` 把这些记录拼进最终异常的消息文本：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:748-770 (节选)
StringBuilder buf = new StringBuilder("No such extension " + type.getName() + " by name " + name);
for (Map.Entry<String, IllegalStateException> entry : exceptions.entrySet()) {
    if (entry.getKey().toLowerCase().startsWith(name.toLowerCase())) {
        buf.append(", possible causes: \r\n(").append(i++).append(") ")
           .append(entry.getKey()).append(":\r\n")
           .append(StringUtils.toString(entry.getValue()));   // 原始异常(含 cause) 拼进消息
    }
}
return new IllegalStateException(buf.toString());             // :769  注意: 外层未设 cause
```

> [!WARNING]
> 最终抛出的 `IllegalStateException` **本身没有 `cause`**（`:769` 只传 message），但真实根因（`NoClassDefFoundError` / 第三方库缺失等）出现在消息的 "possible causes" 段落里，可见可追溯。不要只 catch 外层就放弃——要读异常消息文本才能看到根因。这与 2.x 把 cause 直接挂在外层的做法不同。

## Loading Process

四个加载方法的签名在 3.3.6 全部变了，且中间插入了 `LoadingStrategy` 对象与 `special_spi.properties` 机制。

### getExtensionClasses: Lock Changed

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:955-981
private Map<String, Class<?>> getExtensionClasses() {
    Map<String, Class<?>> classes = cachedClasses.get();
    if (classes == null) {
        loadExtensionClassesLock.lock();
        try {
            classes = cachedClasses.get();
            if (classes == null) {
                try {
                    classes = loadExtensionClasses();
                } catch (InterruptedException e) {
                    throw new IllegalStateException(
                            "Exception occurred when loading extension class (interface: " + type + ")", e);
                }
                cachedClasses.set(classes);
            }
        } finally {
            loadExtensionClassesLock.unlock();
        }
    }
    return classes;
}
```

与旧版的 `synchronized (cachedClasses)` 相比只是换成了显式 `ReentrantLock`（配合 `try/finally`），但注意 `loadExtensionClasses()` 现在**抛 `InterruptedException`**，所以整个方法体被 try 包裹并转成 `IllegalStateException`。

### loadExtensionClasses: Pass strategy Object

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:987-1003
private Map<String, Class<?>> loadExtensionClasses() throws InterruptedException {
    checkDestroyed();
    cacheDefaultExtensionName();

    Map<String, Class<?>> extensionClasses = new HashMap<>();

    for (LoadingStrategy strategy : strategies) {
        loadDirectory(extensionClasses, strategy, type.getName());

        // compatible with old ExtensionFactory
        if (this.type == ExtensionInjector.class) {
            loadDirectory(extensionClasses, strategy, ExtensionFactory.class.getName());
        }
    }

    return extensionClasses;
}
```

两处与旧版不同：

1. 第二行不再把 `type.getName().replace("org.apache", "com.alibaba")` 传给 `loadDirectory`，兼容加载挪进了 `loadDirectory` 内部（见下）。
2. 多了一次针对 `ExtensionFactory` 旧 SPI 文件的补加载——`loadExtensionClasses` 时若当前类型是 `ExtensionInjector`，会额外按 `org.apache.dubbo.common.extension.ExtensionFactory` 这个名字再扫一遍，保证老代码里写在旧文件里的扩展也能被读到。

`LoadingStrategy` 在 3.x 是一组可插拔策略（`DubboLoadingStrategy` 用 `META-INF/dubbo/internal/` 且 `overridden() == true`），比旧版的四个散装参数多了 `includedPackages` / `onlyExtensionClassLoaderPackages` 等过滤维度。

### loadDirectory: Signature Fully Changed + special_spi

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1005-1021
private void loadDirectory(Map<String, Class<?>> extensionClasses, LoadingStrategy strategy, String type)
        throws InterruptedException {
    loadDirectoryInternal(extensionClasses, strategy, type);
    if (Dubbo2CompactUtils.isEnabled()) {
        try {
            String oldType = type.replace("org.apache", "com.alibaba");
            if (oldType.equals(type)) {
                return;
            }
            // if class not found,skip try to load resources
            ClassUtils.forName(oldType);
            loadDirectoryInternal(extensionClasses, strategy, oldType);
        } catch (ClassNotFoundException classNotFoundException) {

        }
    }
}
```

与旧版签名 `(Map, String dir, String type, boolean, boolean, String...)` 相比：**不再逐个传目录/开关/排除包，而是整个 `LoadingStrategy` 传进来**；`com.alibaba` 兼容分支从 `loadExtensionClasses` 移到这里，并且加了 `ClassUtils.forName(oldType)` 存在性检查——老包名完全不存在时直接跳过，不再白扫一遍文件系统。

真正的逻辑在 `loadDirectoryInternal`，其中最值得注意的是 `special_spi.properties` 分支：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1045-1069
private void loadDirectoryInternal(
        Map<String, Class<?>> extensionClasses, LoadingStrategy loadingStrategy, String type)
        throws InterruptedException {
    String fileName = loadingStrategy.directory() + type;
    try {
        List<ClassLoader> classLoadersToLoad = new LinkedList<>();

        // try to load from ExtensionLoader's ClassLoader first
        if (loadingStrategy.preferExtensionClassLoader()) {
            ClassLoader extensionLoaderClassLoader = ExtensionLoader.class.getClassLoader();
            if (ClassLoader.getSystemClassLoader() != extensionLoaderClassLoader) {
                classLoadersToLoad.add(extensionLoaderClassLoader);
            }
        }

        if (specialSPILoadingStrategyMap.containsKey(type)) {
            String internalDirectoryType = specialSPILoadingStrategyMap.get(type);
            // skip to load spi when name don't match
            if (!LoadingStrategy.ALL.equals(internalDirectoryType)
                    && !internalDirectoryType.equals(loadingStrategy.getName())) {
                return;
            }
            classLoadersToLoad.clear();
            classLoadersToLoad.add(ExtensionLoader.class.getClassLoader());
        } else {
            // load from scope model
            Set<ClassLoader> classLoaders = scopeModel.getClassLoaders();
            // ... 把 scopeModel 的 ClassLoader 逐个加入 classLoadersToLoad
        }
```

`special_spi.properties` 是一份「key = 扩展接口全限定名，value = 允许加载它的 LoadingStrategy 名或 `ALL`」的配置文件（常量在 `ExtensionLoader.java:115`，内容解析在 `:186`）。命中它的 SPI **只从 Dubbo 自己的 ClassLoader 加载**，跳过其他所有 ClassLoader——目的是加速启动，因为这类扩展必然来自 Dubbo 自身 jar，没必要去用户 ClassLoader 里一遍遍找。

注意这里的 `scopeModel.getClassLoaders()`——这就是替代旧 `findClassLoader()` 的东西。`findClassLoader()` 在 3.3.6 里已经被删除，`ExtensionLoader` 中搜不到该方法；`ScopeModel.getClassLoaders()` 返回的是该模型及其所有父模型累积的 ClassLoader 集合（`ScopeModel.java:252-254`）。

### loadResource: Three Filtering Dimensions

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1139-1189
private void loadResource(
        Map<String, Class<?>> extensionClasses,
        ClassLoader classLoader,
        java.net.URL resourceURL,
        boolean overridden,
        String[] includedPackages,
        String[] excludedPackages,
        String[] onlyExtensionClassLoaderPackages) {
    try {
        List<String> newContentList = getResourceContent(resourceURL);
        String clazz;
        for (String line : newContentList) {
            try {
                String name = null;
                int i = line.indexOf('=');
                if (i > 0) {
                    name = line.substring(0, i).trim();
                    clazz = line.substring(i + 1).trim();
                } else {
                    clazz = line;
                }
                if (StringUtils.isNotEmpty(clazz)
                        && !isExcluded(clazz, excludedPackages)
                        && isIncluded(clazz, includedPackages)
                        && !isExcludedByClassLoader(clazz, classLoader, onlyExtensionClassLoaderPackages)) {
                    loadClass(classLoader, extensionClasses, resourceURL,
                            Class.forName(clazz, true, classLoader), name, overridden);
                }
            } catch (Throwable t) {
                exceptions.put(line, new IllegalStateException(
                        "Failed to load extension class (interface: " + type + ", class line: " + line + ") in "
                                + resourceURL + ", cause: " + t.getMessage(), t));
            }
        }
    } catch (Throwable t) {
        logger.error(COMMON_ERROR_LOAD_EXTENSION, "", "",
                "Exception occurred when loading extension class (interface: " + type + ", class file: "
                        + resourceURL + ") in " + resourceURL, t);
    }
}
```

三个变化：

1. **参数多了两个**：`includedPackages`（白名单）与 `onlyExtensionClassLoaderPackages`（限定只能由 Dubbo ClassLoader 加载的包）。
2. **过滤条件从一个变三个**：`!isExcluded && isIncluded && !isExcludedByClassLoader`。
3. **不再直接 `new BufferedReader` 读流**，改为 `getResourceContent(resourceURL)`（`:1191-1224`）——它用一个 `SoftReference<ConcurrentHashMap<URL, List<String>>>` 缓存每个资源 URL 的行列表，多 ClassLoader 扫同一个文件时不会重复读盘。

`#` 注释与空行裁剪仍然在 `getResourceContent` 里做，语义没变。

### loadClass: First Arg Is ClassLoader + onClass Conditional Loading

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1266-1307
private void loadClass(
        ClassLoader classLoader,
        Map<String, Class<?>> extensionClasses,
        java.net.URL resourceURL,
        Class<?> clazz,
        String name,
        boolean overridden) {
    if (!type.isAssignableFrom(clazz)) {
        throw new IllegalStateException(
                "Error occurred when loading extension class (interface: " + type + ", class line: "
                        + clazz.getName() + "), class " + clazz.getName() + " is not subtype of interface.");
    }

    if (!loadClassIfActive(classLoader, clazz)) {
        return;
    }

    if (clazz.isAnnotationPresent(Adaptive.class)) {
        cacheAdaptiveClass(clazz, overridden);
    } else if (isWrapperClass(clazz)) {
        cacheWrapperClass(clazz);
    } else {
        if (StringUtils.isEmpty(name)) {
            name = findAnnotationName(clazz);
            if (name.length() == 0) {
                throw new IllegalStateException("No such extension name for the class " + clazz.getName()
                        + " in the config " + resourceURL);
            }
        }

        String[] names = NAME_SEPARATOR.split(name);
        if (ArrayUtils.isNotEmpty(names)) {
            cacheActivateClass(clazz, names[0]);
            for (String n : names) {
                cacheName(clazz, n);
                saveInExtensionClass(extensionClasses, clazz, n, overridden);
            }
        }
    }
}
```

首参从无到有——`classLoader` 现在显式传进来（多 ClassLoader 场景下必须知道这条记录来自哪个加载器）。`loadClassIfActive` 是新增的：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1309-1333
private boolean loadClassIfActive(ClassLoader classLoader, Class<?> clazz) {
    Activate activate = clazz.getAnnotation(Activate.class);

    if (activate == null) {
        return true;
    }
    String[] onClass = null;

    if (activate instanceof Activate) {
        onClass = ((Activate) activate).onClass();
    } else if (Dubbo2CompactUtils.isEnabled()
            && Dubbo2ActivateUtils.isActivateLoaded()
            && Dubbo2ActivateUtils.getActivateClass().isAssignableFrom(activate.getClass())) {
        onClass = Dubbo2ActivateUtils.getOnClass(activate);
    }

    boolean isActive = true;

    if (null != onClass && onClass.length > 0) {
        isActive = Arrays.stream(onClass)
                .filter(StringUtils::isNotBlank)
                .allMatch(className -> ClassUtils.isPresent(className, classLoader));
    }
    return isActive;
}
```

`@Activate(onClass = "...")` 指定的类**全部存在**才加载这个扩展，类路径校验前移到加载阶段。旧版里 `loadClass` 用 `clazz.getConstructor()`（探测有无无参构造）来试探，现在这一步被 `loadClassIfActive` 的早退取代。

其余三个 cache 方法的语义与旧版一致：`cacheAdaptiveClass` 保证至多一个 `@Adaptive` 实现、`cacheWrapperClass` 按 `isWrapperClass`（唯一构造参数就是 `type`）收集、`cacheActivateClass` 记录 `@Activate` 注解对象。`saveInExtensionClass` 里遇到同名重复实现会记入 `unacceptableExceptions` 并抛异常：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1347-1366
private void saveInExtensionClass(Map<String, Class<?>> extensionClasses, Class<?> clazz, String name, boolean overridden) {
    Class<?> c = extensionClasses.get(name);
    if (c == null || overridden) {
        extensionClasses.put(name, clazz);
    } else if (c != clazz) {
        // duplicate implementation is unacceptable
        unacceptableExceptions.add(name);
        String duplicateMsg =
                "Duplicate extension " + type.getName() + " name " + name + " on " + c.getName() + " and " + clazz.getName();
        logger.error(duplicateMsg);
        throw new IllegalStateException(duplicateMsg);
    }
}
```

### createExtension: Three Steps of postProcess

`createExtension` 的骨架（AOP 包装 + 注入 + 初始化）没变，但实例创建与前后置处理都改了：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:773-788
private T createExtension(String name, boolean wrap) {
    Class<?> clazz = getExtensionClasses().get(name);
    if (clazz == null || unacceptableExceptions.contains(name)) {
        throw findException(name);
    }
    try {
        T instance = (T) extensionInstances.get(clazz);
        if (instance == null) {
            extensionInstances.putIfAbsent(clazz, createExtensionInstance(clazz));
            instance = (T) extensionInstances.get(clazz);
            instance = postProcessBeforeInitialization(instance, name);
            injectExtension(instance);
            instance = postProcessAfterInitialization(instance, name);
        }
```

三处关键变化：

1. **实例化不再用 `clazz.getDeclaredConstructor().newInstance()`**，改为 `createExtensionInstance(clazz)` → `instantiationStrategy.instantiate(type)`（`ExtensionLoader.java:825-827`）。`InstantiationStrategy`（`dubbo-common/.../common/beans/support/InstantiationStrategy.java:46-95`）**优先匹配「全部参数为 `ScopeModel` 子类型」的构造，退化才用无参构造**——这样扩展若声明了 `Xxx(ApplicationModel model)` 这类构造，就能在创建时直接拿到所属模型。
2. **新增 `postProcessBeforeInitialization` / `postProcessAfterInitialization`**，遍历 `extensionPostProcessors`。默认注册的 `ScopeModelAwareExtensionProcessor` 靠 **`postProcessAfterInitialization`（后置）** 把 `ScopeModel` 注入给实现了 `ScopeModelAware` 的扩展——注意是**后置**不是前置；而 `ExtensionAccessorAware` 的注入在 `ExtensionLoader.postProcessAfterInitialization` 中直接完成（`ExtensionLoader.java:842`）。
3. **异常路径变了**：类找不到或名字被标记为不可接受时，抛 `findException(name)` 而不是简单返回 null——它会把之前 `loadResource` 里记录的原始异常带上，异常信息可追溯。

#### InstantiationStrategy: Dual-Constructor Probe

`ExtensionLoader` 自身不直接 `new` 实例，而是委托 `InstantiationStrategy.instantiate(type)`（`InstantiationStrategy.java:46-95`）。它的构造匹配逻辑与「先无参再 ScopeModel」的直觉相反：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/beans/support/InstantiationStrategy.java:46-95 (节选)
public <T> T instantiate(Class<T> type) throws ReflectiveOperationException {
    // 1. 取无参构造 (若无则 null)
    Constructor<T> defaultConstructor = null;
    try { defaultConstructor = type.getConstructor(); } catch (NoSuchMethodException e) { /* ignore */ }

    // 2. 收集「全部参数为 ScopeModel 子类型」的构造
    List<Constructor<?>> matchedConstructors = new ArrayList<>();
    for (Constructor<?> constructor : type.getConstructors()) {
        if (isMatched(constructor)) {  // isMatched: 每个参数类型都是 ScopeModel|FrameworkModel|ApplicationModel|ModuleModel
            matchedConstructors.add(constructor);
        }
    }
    matchedConstructors.remove(defaultConstructor);

    Constructor<?> target;
    if (matchedConstructors.size() == 1) {
        target = matchedConstructors.get(0);          // 优先: 带 ScopeModel 型参数的构造
    } else if (defaultConstructor != null) {
        target = defaultConstructor;                  // 退化: 无参构造
    } else {
        throw new IllegalArgumentException("None matched constructor was found for type: " + type.getName());
    }
    // 对 ScopeModel 型参数, 按参数类型从 ScopeModelAccessor 取对应模型视图
    Object[] args = ...;  // getArgumentValueForType(paramType) -> scopeModelAccessor.getScopeModel()
    return (T) target.newInstance(args);
}
```

选择优先级：**恰好一个 ScopeModel 型构造就用它 → 否则退化无参 → 两者皆无才抛异常**。所以「给扩展注入模型」有两种并存方式：构造期（声明 `Xxx(Model)` 单参构造）与注入期（实现 `ScopeModelAware` 接口）。`ExtensionLoader` 的 `instantiationStrategy` 在构造期经 `initInstantiationStrategy()` 初始化——若某个 `ExtensionPostProcessor` 是 `ScopeModelAccessor`（即 `ScopeModelAwareExtensionProcessor`），就以它作为 accessor 包装，否则用无参版本。

#### ScopeModelAware and ExtensionAccessorAware Injection

模型注入发生在创建之后，由 `ExtensionPostProcessor` 在**后置**阶段完成，而非前置：

```java
// dubbo-common/src/main/java/org/apache/dubbo/rpc/model/ScopeModelAwareExtensionProcessor.java:54-68
@Override
public Object postProcessAfterInitialization(Object instance, String name) throws Exception {
    if (instance instanceof ScopeModelAware) {
        ScopeModelAware modelAware = (ScopeModelAware) instance;
        modelAware.setScopeModel(scopeModel);
        if (this.moduleModel != null)     { modelAware.setModuleModel(this.moduleModel); }
        if (this.applicationModel != null){ modelAware.setApplicationModel(this.applicationModel); }
        if (this.frameworkModel != null)  { modelAware.setFrameworkModel(this.frameworkModel); }
    }
    return instance;
}
```

`ScopeModelAwareExtensionProcessor` 在 `ScopeModel.initialize()` 时就被注册（`ScopeModel.java:119` 的 `extensionDirector.addExtensionPostProcessor(new ScopeModelAwareExtensionProcessor(this))`），因此每个扩展实例都能拿到所属模型的完整三层视图（`ScopeModel` / `ModuleModel` / `ApplicationModel` / `FrameworkModel`）。

`ExtensionAccessorAware` 不走这个 processor，而是在 `ExtensionLoader.postProcessAfterInitialization` 里直接注入：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:840-843
instance = postProcessAfterInitialization(instance, name);   // 先跑所有 post processors (含上面那个)
if (instance instanceof ExtensionAccessorAware) {
    ((ExtensionAccessorAware) instance).setExtensionAccessor(extensionDirector);
}
```

> [!WARNING]
> 旧笔记常说「`ScopeModelAware` 由前置处理器注入」，在 3.3.6 里这是错的——`ScopeModelAwareExtensionProcessor` 只重写了 **`postProcessAfterInitialization`**，前置阶段（`postProcessBeforeInitialization`）什么都做（`ExtensionPostProcessor` 接口默认空实现）。同时 `ScopeModelAware` 与 `ExtensionAccessorAware` 的 `setXxx` 是对象类型 setter，`injectExtension` 会误判为普通依赖去注入，因此 `ExtensionLoader.injectExtension` 里有专门的跳过分支（见下方「IoC：ExtensionInjector」一节中 `ScopeModelAware` / `ExtensionAccessorAware` 跳过逻辑）。

包装类逻辑不变：`cachedWrapperClasses` 按 `WrapperComparator` 排序后反转，`@Wrapper(matches/mismatches)` 决定是否包裹，包裹后**同样要走一遍前后置处理和注入**。

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:790-812
            if (wrap) {
                List<Class<?>> wrapperClassesList = new ArrayList<>();
                if (cachedWrapperClasses != null) {
                    wrapperClassesList.addAll(cachedWrapperClasses);
                    wrapperClassesList.sort(WrapperComparator.COMPARATOR);
                    Collections.reverse(wrapperClassesList);
                }

                if (CollectionUtils.isNotEmpty(wrapperClassesList)) {
                    for (Class<?> wrapperClass : wrapperClassesList) {
                        Wrapper wrapper = wrapperClass.getAnnotation(Wrapper.class);
                        boolean match = (wrapper == null)
                                || ((ArrayUtils.isEmpty(wrapper.matches())
                                                || ArrayUtils.contains(wrapper.matches(), name))
                                        && !ArrayUtils.contains(wrapper.mismatches(), name));
                        if (match) {
                            instance = (T) wrapperClass.getConstructor(type).newInstance(instance);
                            instance = postProcessBeforeInitialization(instance, name);
                            injectExtension(instance);
                            instance = postProcessAfterInitialization(instance, name);
                        }
                    }
                }
            }

            // Warning: After an instance of Lifecycle is wrapped by cachedWrapperClasses, it may not still be Lifecycle
            // instance, this application may not invoke the lifecycle.initialize hook.
            initExtension(instance);
```

注意匹配条件比旧版更完整：旧版是 `wrapper == null || (contains(matches, name) && !contains(mismatches, name))`，3.3.6 补了 `ArrayUtils.isEmpty(wrapper.matches())` 分支，即**`matches` 为空表示匹配全部**。这一点与 `@Wrapper` 的 javadoc 一致，但旧代码里会漏判。

## LoadingStrategy and SPI Directory Layout

Dubbo 把「去哪个目录扫 SPI 文件」抽象成 `LoadingStrategy`（`dubbo-common/.../extension/LoadingStrategy.java`，extends `Prioritized`）。三个内置实现**本身也是通过 JDK `ServiceLoader` 注册的**——`ExtensionLoader.loadLoadingStrategies()` 直接 `stream(load(LoadingStrategy.class)...).sorted()`（`ExtensionLoader.java:174-176`），而 `load(LoadingStrategy.class)` 就是 `java.util.ServiceLoader.load`；注册文件在 `dubbo-common/src/main/resources/META-INF/services/org.apache.dubbo.common.extension.LoadingStrategy`，列出三个全限定名。也就是说 Dubbo 用来加载自己扩展的「策略表」反而借用了 JDK SPI，但扩展实现本体仍走 Dubbo 的三目录体系。

| 实现类 | `directory()` | `getPriority()`（Prioritized） | `overridden()` | `getName()` |
| :--- | :--- | :--- | :--- | :--- |
| `DubboInternalLoadingStrategy` | `META-INF/dubbo/internal/` | `MAX_PRIORITY` | `false`（默认） | `DUBBO_INTERNAL` |
| `DubboLoadingStrategy` | `META-INF/dubbo/` | `NORMAL_PRIORITY` | `true` | `DUBBO` |
| `ServicesLoadingStrategy` | `META-INF/services/` | `MIN_PRIORITY` | `true` | `SERVICES` |

关键决策点：

1. **扫描顺序由 `Prioritized.getPriority()` 决定**，`DubboInternalLoadingStrategy` 优先级最高、`ServicesLoadingStrategy` 最低；`loadExtensionClasses()` 按 `strategies` 顺序逐个 `loadDirectory`（`ExtensionLoader.java:416-417`）。`META-INF/dubbo/internal/` 是 Dubbo 内部扩展的专属目录（如 `ExtensionInjector`、`Compiler`），`META-INF/dubbo/` 给用户自定义扩展，`META-INF/services/` 用于兼容 JDK SPI 风格的文件。
2. **`overridden()` 控制同名覆盖方向**。只有 `DubboInternalLoadingStrategy` 返回 `false`，另两个返回 `true`。`overridden == true` 的目录里扫到的同名扩展可以覆盖 `overridden == false` 目录里的实现——含义是「用户/`services` 目录的扩展能覆盖 Dubbo 内置实现」，内置目录不做反向覆盖。这个布尔最终透传到 `loadResource(..., boolean overridden, ...)` 与 `saveInExtensionClass` 的 `overridden` 形参（同名时 `c == null || overridden` 才允许写入，`ExtensionLoader.java:637-649`）。
3. **`special_spi.properties` 让特定接口只从 Dubbo ClassLoader 加载**。`getSpecialSPILoadingStrategyMap()`（`ExtensionLoader.java:184-189`）按 `special_spi.properties` 建立「接口全限定名 → 允许加载它的 `LoadingStrategy` 名 / `ALL`」映射；命中后 `loadDirectoryInternal` 清空 `classLoadersToLoad` 并只加 `ExtensionLoader.class.getClassLoader()`（`ExtensionLoader.java:480-488`），跳过 scopeModel 的 ClassLoader 集合以加速启动。

> [!NOTE]
> `ExtensionLoader.setLoadingStrategies(LoadingStrategy...)`（`ExtensionLoader.java:163-168`）允许外部整个替换策略表——这是 Dubbo 给框架集成方留的逃生舱，但正常启动路径用的是 `loadLoadingStrategies()` 扫描出来的默认三件套。另见 [AOP](/docs/CS/Framework/Dubbo/SPI.md?id=aop) 对 wrapper 目录约定的说明。

## Adaptive Extension Generation

### getAdaptiveExtension

入口结构与旧版一致（DCL + 缓存），多了 `checkDestroyed()`，并且 `createAdaptiveInstanceError` 也会缓存住首次失败：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:721-724
public T getAdaptiveExtension() {
    checkDestroyed();
    Object instance = cachedAdaptiveInstance.get();
    if (instance == null) {
        if (createAdaptiveInstanceError != null) {
            throw new IllegalStateException("Failed to create adaptive instance: "
                    + createAdaptiveInstanceError.toString(), createAdaptiveInstanceError);
        }
```

`createAdaptiveExtension` 多了前后置处理三步：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1435-1447
private T createAdaptiveExtension() {
    try {
        T instance = (T) getAdaptiveExtensionClass().newInstance();
        instance = postProcessBeforeInitialization(instance, null);
        injectExtension(instance);
        instance = postProcessAfterInitialization(instance, null);
        initExtension(instance);
        return instance;
    } catch (Exception e) {
        throw new IllegalStateException(
                "Can't create adaptive extension " + type + ", cause: " + e.getMessage(), e);
    }
}
```

> [!NOTE]
> 自适应实例的 `name` 参数传的是 `null`（不是具体扩展名），所以写 `ExtensionPostProcessor` 时不要假设 `name` 一定有值。

### createAdaptiveExtensionClass

改动最彻底的一处，三点变化：ClassLoader 来源改了、加了 GraalVM 原生镜像分支、`compile` 变三参。

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1457-1472
private Class<?> createAdaptiveExtensionClass() {
    // Adaptive Classes' ClassLoader should be the same with Real SPI interface classes' ClassLoader
    ClassLoader classLoader = type.getClassLoader();
    try {
        if (NativeDetector.inNativeImage()) {
            return classLoader.loadClass(type.getName() + "$Adaptive");
        }
    } catch (Throwable ignore) {

    }
    String code = new AdaptiveClassCodeGenerator(type, cachedDefaultName).generate();
    org.apache.dubbo.common.compiler.Compiler compiler = extensionDirector
            .getExtensionLoader(org.apache.dubbo.common.compiler.Compiler.class)
            .getAdaptiveExtension();
    return compiler.compile(type, code, classLoader);
}
```

- ClassLoader 从旧版的 `findClassLoader()`（即 `ExtensionLoader.class` 的 CL）改成 **`type.getClassLoader()`**。理由写在注释里：自适应类必须跟真实 SPI 接口用同一个 ClassLoader，否则生成的类 `instanceof` 不上目标接口。
- `NativeDetector.inNativeImage()` 为真（GraalVM native-image）时不做生成，直接 `loadClass(type.getName() + "$Adaptive")`——原生镜像里所有自适应类必须在构建期预先生成好（`dubbo-native` 插件负责这件事），运行期没有 `javassist`/`jdk` 编译器可用。
- 编译器改从 `extensionDirector` 取而不是 `ExtensionLoader.getExtensionLoader(Compiler.class)`，因为 `Compiler` 是 `FRAMEWORK` 作用域，必须由框架层的 Director 提供。
- `compile` 变三参，见 Compiler 一节。

### Two Forms of @Adaptive

`@Adaptive` 有两种落点，二者在 `getAdaptiveExtensionClass()` 里被显式分支（`ExtensionLoader.java:1449-1454`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:1449-1454
private Class<?> getAdaptiveExtensionClass() {
    getExtensionClasses();
    if (cachedAdaptiveClass != null) {
        return cachedAdaptiveClass;          // 形式一：注解在类上，直接返回，不生成代码
    }
    return cachedAdaptiveClass = createAdaptiveExtensionClass();  // 形式二：注解在方法上，运行时生成
}
```

- **形式一：注解在类上**。`loadClass` 发现 `clazz.isAnnotationPresent(Adaptive.class)` 就 `cacheAdaptiveClass(clazz)`（`ExtensionLoader.java:575-576`），`cachedAdaptiveClass` 被置位。典型例子是 `AdaptiveCompiler`、`AdaptiveExtensionInjector`——它们都是手写好的完整实现，直接作为自适应类返回，**不经过 `AdaptiveClassCodeGenerator`**。约束：`cacheAdaptiveClass` 保证至多一个 `@Adaptive` 实现，出现第二个会抛 "More than 1 adaptive class found"（`ExtensionLoader.java:1387-1389`）。
- **形式二：注解在方法上**。`cachedAdaptiveClass == null` 时走 `createAdaptiveExtensionClass()`：先用 `AdaptiveClassCodeGenerator(type, cachedDefaultName).generate()` 拼出代理源码，再经 `Compiler` 编译成 `Xxx$Adaptive`（`ExtensionLoader.java:1457-1472`）。生成类里每个 `@Adaptive` 方法按 `URL.getMethodParameter` / `URL.getParameter` 解析扩展名并 `scopeModel.getExtensionLoader(type).getExtension(extName)` 加载具体实现（见 `AdaptiveClassCodeGenerator` 的 `CODE_EXTENSION_ASSIGNMENT`）。

> [!TIP]
> 判定一个扩展点是哪种：翻它的 SPI 实现类——若某个实现类头上直接标了 `@Adaptive` 就是形式一（编译期已定型，启动不生成）；若接口方法上有 `@Adaptive` 而实现类都没有，就是形式二（运行时按需生成代理）。`Protocol.export` / `refer` 属于形式二，所以 `Protocol$Adaptive` 是运行时生成的。

### AdaptiveClassCodeGenerator

包路径变了：3.3.6 在 `org.apache.dubbo.common.extension` 下，**`extension.support` 里没有这个类**。

`generate()` 变成了委托给 `generate(boolean sort)` 的薄方法（`AdaptiveClassCodeGenerator.java:98-131`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/AdaptiveClassCodeGenerator.java:98-126
public String generate() {
    return this.generate(false);
}

/**
 * generate and return class code
 * @param sort - whether sort methods
 */
public String generate(boolean sort) {
    // no need to generate adaptive class since there's no adaptive method found.
    if (!hasAdaptiveMethod()) {
        throw new IllegalStateException("No adaptive method exist on extension " + type.getName()
                + ", refuse to create the adaptive class!");
    }

    StringBuilder code = new StringBuilder();
    code.append(generatePackageInfo());
    code.append(generateImports());
    code.append(generateClassDeclaration());

    Method[] methods = type.getMethods();
    if (sort) {
        Arrays.sort(methods, Comparator.comparing(Method::toString));
    }
    for (Method method : methods) {
        code.append(generateMethod(method));
    }
    code.append('}');

    if (logger.isDebugEnabled()) {
        logger.debug(code.toString());
    }
    return code.toString();
}
```

`generate(boolean sort)` 让方法顺序可控——排序后生成的类每次构建结果一致，便于 GraalVM 原生镜像做闭世界分析。

最能体现 ScopeModel 侵入程度的是 `generateImports()`：它**固定注入 `ScopeModel` 与 `ScopeModelUtil` 两个 import**（`:143-148`），因为每个自适应方法都要用到它们：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/AdaptiveClassCodeGenerator.java:72-79
private static final String CODE_SCOPE_MODEL_ASSIGNMENT =
        "ScopeModel scopeModel = ScopeModelUtil.getOrDefault(url.getScopeModel(), %s.class);\n";
private static final String CODE_EXTENSION_ASSIGNMENT =
        "%s extension = (%<s)scopeModel.getExtensionLoader(%s.class).getExtension(extName);\n";
```

生成的代码形如：

```java
ScopeModel scopeModel = ScopeModelUtil.getOrDefault(url.getScopeModel(), Protocol.class);
Protocol extension = (Protocol) scopeModel.getExtensionLoader(Protocol.class).getExtension(extName);
```

也就是说 3.x 的自适应扩展**在运行时按 URL 携带的 `ScopeModel` 决定用哪个加载器**，这正是「同一个 `Protocol` 接口在多个应用里各自持有自己的 `Protocol` 实例」能成立的机制基础。旧版的生成代码是 `ExtensionLoader.getExtensionLoader(Protocol.class)`——写死了全局静态容器。

## Activation and Sorting

### getActivateExtension Override

3.3.6 的实现与旧版差异集中在三点：**两级缓存**、**`containsExtension` 取代 `loadedNames` 去重**、**`DEFAULT_KEY` 分支重写**。

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:344-403
public List<T> getActivateExtension(URL url, String[] values, String group) {
    checkDestroyed();
    // solve the bug of using @SPI's wrapper method to report a null pointer exception.
    Map<Class<?>, T> activateExtensionsMap = new TreeMap<>(activateComparator);
    List<String> names = values == null
            ? new ArrayList<>(0)
            : Arrays.stream(values).map(StringUtils::trim).collect(Collectors.toList());
    Set<String> namesSet = new HashSet<>(names);
    if (!namesSet.contains(REMOVE_VALUE_PREFIX + DEFAULT_KEY)) {
        if (cachedActivateGroups.size() == 0) {
            synchronized (cachedActivateGroups) {
                // cache all extensions
                if (cachedActivateGroups.size() == 0) {
                    getExtensionClasses();
                    for (Map.Entry<String, Object> entry : cachedActivates.entrySet()) {
                        String name = entry.getKey();
                        Object activate = entry.getValue();

                        String[] activateGroup, activateValue;

                        if (activate instanceof Activate) {
                            activateGroup = ((Activate) activate).group();
                            activateValue = ((Activate) activate).value();
                        } else if (Dubbo2CompactUtils.isEnabled()
                                && Dubbo2ActivateUtils.isActivateLoaded()
                                && Dubbo2ActivateUtils.getActivateClass().isAssignableFrom(activate.getClass())) {
                            activateGroup = Dubbo2ActivateUtils.getGroup((Annotation) activate);
                            activateValue = Dubbo2ActivateUtils.getValue((Annotation) activate);
                        } else {
                            continue;
                        }
                        cachedActivateGroups.put(name, new HashSet<>(Arrays.asList(activateGroup)));
                        // 把 "k1:v1, k2" 一次性解析成 [[k1, v1], [k2, null]]
                        String[][] keyPairs = new String[activateValue.length][];
                        for (int i = 0; i < activateValue.length; i++) {
                            keyPairs[i] = activateValue[i].contains(":")
                                    ? activateValue[i].split(":")
                                    : new String[] {activateValue[i]};
                        }
                        cachedActivateValues.put(name, keyPairs);
                    }
                }
            }
        }
```

这一段做了三件事：

1. **把 `@Activate` 的 `group` / `value` 提前解析成两个新缓存**：`cachedActivateGroups`（`String → Set<String>`）与 `cachedActivateValues`（`String → String[][]`）。旧版每次调用都要重新读注解对象、重新 split。
2. **`"key:value"` 语法在此处一次性解析成 keyPairs**。`@Activate(value = "tps:5")` 里的冒号在旧版是每次遍历重新 `split`，现在只做一次。
3. **加了 `Dubbo2CompactUtils.isEnabled()` 分支**，支持 `com.alibaba.dubbo` 的老 `@Activate` 注解——但要额外判断 `Dubbo2ActivateUtils.isActivateLoaded()`，因为紧凑模式下那个类可能根本没被加载进来。

遍历缓存的阶段也简化了：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:394-401
            // traverse all cached extensions
            cachedActivateGroups.forEach((name, activateGroup) -> {
                if (isMatchGroup(group, activateGroup)
                        && !namesSet.contains(name)
                        && !namesSet.contains(REMOVE_VALUE_PREFIX + name)
                        && isActive(cachedActivateValues.get(name), url)) {

                    activateExtensionsMap.put(getExtensionClass(name), getExtension(name));
                }
            });
```

去重不再靠 `loadedNames` 集合，而是靠 `TreeMap<Class<?>, T>` 以 `Class` 为 key 天然去重。`DEFAULT_KEY` 分支（`ext1,default,ext2` 这种写法）也重写成显式的 `extensionsResult` 累加——`default` 之前后显式列出的扩展会插到自动激活的那批之前/之后，而不带 `default` 时全部按 `order` 统一排序（`:404-435`）。

`containsExtension(name)` 就是 `getExtensionClasses().containsKey(name)`（`:852-854`）。旧版里「名字不存在会 NPE」以及「重复 filter 打 warn 日志」的处理，现在由这个方法兜住——名字不存在时直接跳过，不抛异常也不打日志。

`isActive` 的签名也变了，从吃 `String[] activateValue` 变成吃预解析好的 `String[][] keyPairs`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:471-497
private boolean isActive(String[][] keyPairs, URL url) {
    if (keyPairs.length == 0) {
        return true;
    }
    for (String[] keyPair : keyPairs) {
        // @Active(value="key1:value1, key2:value2")
        String key;
        String keyValue = null;
        if (keyPair.length > 1) {
            key = keyPair[0];
            keyValue = keyPair[1];
        } else {
            key = keyPair[0];
        }

        String realValue = url.getParameter(key);
        if (StringUtils.isEmpty(realValue)) {
            realValue = url.getAnyMethodParameter(key);
        }
        if ((keyValue != null && keyValue.equals(realValue))
                || (keyValue == null && ConfigUtils.isNotEmpty(realValue))) {
            return true;
        }
    }
    return false;
}
```

`key:v` 精确匹配值，`key` 只要非空即命中；任一 key 命中就激活。

### Sorting: ActivateComparator

旧笔记写的 `ActivateComparator.COMPARATOR` 静态常量**已不存在**。3.3.6 是实例字段，通过构造入参拿 `ExtensionDirector`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/support/ActivateComparator.java:37-51
public class ActivateComparator implements Comparator<Class<?>> {

    private final List<ExtensionDirector> extensionDirectors;
    private final Map<Class<?>, ActivateInfo> activateInfoMap = new ConcurrentHashMap<>();

    public ActivateComparator(ExtensionDirector extensionDirector) {
        extensionDirectors = new ArrayList<>();
        extensionDirectors.add(extensionDirector);
    }

    public ActivateComparator(List<ExtensionDirector> extensionDirectors) {
        this.extensionDirectors = extensionDirectors;
    }
```

为什么需要 `ExtensionDirector`？因为排序过程要能反向查到扩展所属模型上的注解与配置，`ActivateInfo` 的解析不再依赖任何静态上下文。排序规则本身（`@Activate.order` 升序、`before`/`after`）未变，`order` 默认 `0`。

> [!TIP]
> `TreeMap<Class<?>, T>` 用 `Class` 当 key，而 `Class` 本身不可比较，实际顺序完全由 `activateComparator` 提供，类名这一层不会干扰结果。

#### compare: before/after beats order

`ActivateComparator.compare(Class, Class)`（`ActivateComparator.java:52-124`）的完整判定优先级：

1. **空值 / 同类型** 直接返回（`:56-60`）。
2. **`before` / `after` 约束优先于 `order`**：仅当某一侧 `applicableToCompare()`（即 `before` 或 `after` 至少有一个非空）且能找到公共 SPI 接口 `inf` 时，才进入约束分支（`:72`）。`before = {x}` 表示本类应在 `x` 之前（`isLess(x)` → 返回更小），`after = {x}` 表示应在 `x` 之后（`isMore(x)` → 返回更大，`:126-186` 的 `ActivateInfo`）。
3. **约束不构成直接前后关系时退回 `order`**：单侧有 `before/after` 但彼此不相关（`isLess/isMore` 都为 false）时，用 `a1.order > a2.order ? 1 : -1` 兜底（`:111`）。
4. **双方都无 `before/after` 约束**：直接走末尾 `order` 比较；`order` 相同再按 `getSimpleName()` 字典序（`:117-123`）。

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/support/ActivateComparator.java:117-123
if (a1.order > a2.order) return 1;
else if (a1.order == a2.order)
    return o1.getSimpleName().compareTo(o2.getSimpleName()) > 0 ? 1 : -1;
else return -1;
```

> [!WARNING]
> `before` / `after` 在 `@Activate` 上已 `@Deprecated`（2.7.0 起），新扩展**只用 `order`** 控制排序。但排序器仍兼容旧注解，所以老代码里 `before/after` 依然生效且优先级高于 `order`。

## IoC：ExtensionInjector

### ExtensionFactory Is Deprecated

3.3.6 里 `ExtensionFactory` 还在，但标了 `@Deprecated`，Javadoc 直接写「use `ExtensionInjector` instead」，并且 `@SPI` 是 `FRAMEWORK` 作用域：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionFactory.java:19-40
/**
 * ExtensionFactory
 * @deprecated use {@link ExtensionInjector} instead
 */
@Deprecated
@SPI(scope = ExtensionScope.FRAMEWORK)
public interface ExtensionFactory extends ExtensionInjector {

    @Override
    default <T> T getInstance(Class<T> type, String name) {
        return getExtension(type, name);
    }

    /**
     * Get extension.
     */
    <T> T getExtension(Class<T> type, String name);
}
```

真正的主接口是 `ExtensionInjector`，注意它的 scope 是 **`SELF`**：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionInjector.java:22-36
/**
 * An injector to provide resources for SPI extension.
 */
@SPI(scope = ExtensionScope.SELF)
public interface ExtensionInjector extends ExtensionAccessorAware {

    /**
     * Get instance of specify type and name.
     */
    <T> T getInstance(final Class<T> type, final String name);

    @Override
    default void setExtensionAccessor(final ExtensionAccessor extensionAccessor) {}
}
```

方法名从 `getExtension` 变成了 `getInstance`，实现类全部改名 `*ExtensionInjector`。

### Three Implementations and SPI Files

`ExtensionFactory` 的 SPI 文件**不存在**（已核实），只有 `ExtensionInjector` 的，三行：

```properties
# dubbo-common/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.extension.ExtensionInjector
adaptive=org.apache.dubbo.common.extension.inject.AdaptiveExtensionInjector
spi=org.apache.dubbo.common.extension.inject.SpiExtensionInjector
scopeBean=org.apache.dubbo.common.beans.ScopeBeanExtensionInjector
```

对照旧笔记的三个类名：

| 旧类名 | 3.3.6 | 位置 |
| --- | --- | --- |
| `AdaptiveExtensionFactory` | `AdaptiveExtensionInjector` | `common/extension/inject/` |
| `SpiExtensionFactory` | `SpiExtensionInjector` | `common/extension/inject/` |
| `SpringExtensionFactory` | `SpringExtensionInjector` | **不在 `dubbo-common`**，在 `dubbo-config-spring` 的 `config/spring/extension/` |
| （无） | `ScopeBeanExtensionInjector` | `common/beans/`，3.x 新增，走 `ScopeBeanFactory` 取 Bean |

`AdaptiveExtensionInjector` 的实现思路是「遍历所有注入器，取第一个返回非 null 的」（`AdaptiveExtensionInjector.java:31-56`）：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/inject/AdaptiveExtensionInjector.java:43-56
    @Override
    public void initialize() throws IllegalStateException {
        ExtensionLoader<ExtensionInjector> loader = extensionAccessor.getExtensionLoader(ExtensionInjector.class);
        injectors = loader.getSupportedExtensions().stream()
                .map(loader::getExtension)
                .collect(Collectors.collectingAndThen(Collectors.toList(), Collections::unmodifiableList));
    }

    @Override
    public <T> T getInstance(final Class<T> type, final String name) {
        return injectors.stream()
                .map(injector -> injector.getInstance(type, name))
                .filter(Objects::nonNull)
                .findFirst()
```

它 `implements Lifecycle`——所有依赖注入都发生在 `initialize()` 之后，所以自依赖注入器的场景不会死循环。

> [!NOTE]
> 旧笔记说「所有依赖注入都通过 `AdaptiveExtensionFactory` 获取」这句话在 3.3.6 依然成立，只是名字换成了 `AdaptiveExtensionInjector`。另外 SPI 文件里 `scopeBean` 这一项是 3.x 新增的：它优先于 `spi` 返回 `ScopeBeanFactory` 里注册的 Bean，让用户 `@Bean` 定义的扩展能覆盖 SPI 文件里的同名实现。

### injectExtension

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/extension/ExtensionLoader.java:856-895
private T injectExtension(T instance) {
    if (injector == null) {
        return instance;
    }

    try {
        for (Method method : instance.getClass().getMethods()) {
            if (!isSetter(method)) {
                continue;
            }
            /**
             * Check {@link DisableInject} to see if we need auto-injection for this property
             */
            if (method.isAnnotationPresent(DisableInject.class)) {
                continue;
            }

            // When spiXXX implements ScopeModelAware, ExtensionAccessorAware,
            // the setXXX of ScopeModelAware and ExtensionAccessorAware does not need to be injected
            if (method.getDeclaringClass() == ScopeModelAware.class) {
                continue;
            }
            if (instance instanceof ScopeModelAware || instance instanceof ExtensionAccessorAware) {
                if (ignoredInjectMethodsDesc.contains(ReflectUtils.getDesc(method))) {
                    continue;
                }
            }

            Class<?> pt = method.getParameterTypes()[0];
            if (ReflectUtils.isPrimitives(pt)) {
                continue;
            }

            try {
                String property = getSetterProperty(method);
```

与旧笔记的三处差异：

1. **`injector == null` 早退**（旧版没有）。`type == ExtensionInjector.class` 时注入器是 null（见构造器），不加这个判断会 NPE。
2. **`method.getAnnotation(DisableInject.class)` 换成 `method.isAnnotationPresent(DisableInject.class)`**。
3. **新增 `ScopeModelAware` / `ExtensionAccessorAware` 的跳过逻辑**。这两个接口的 `setScopeModel` / `setExtensionAccessor` 形参也是对象，签名上完全符合 setter 特征，若不跳过就会被 `injectExtension` 当普通依赖去注入——而它们恰恰是由 `postProcess` / `ExtensionAccessorAware` 机制注入的。`ignoredInjectMethodsDesc` 是在类初始化时把这两个接口所有方法的描述符预先算好的（`ExtensionLoader.java:204-213`）。

`initExtension` 不变，仍是「若是 `Lifecycle` 就调 `initialize()`」。

## Compiler

![Compiler](img/Compiler.png)

### Interface: Compatibility Period of Dual Signatures

3.3.6 的 `Compiler` 是**两个 default 方法互相委托**的结构，旧的两参签名标了 `@Deprecated`：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/compiler/Compiler.java:22-53
/**
 * Compiler. (SPI, Singleton, ThreadSafe)
 */
@SPI(value = "javassist", scope = ExtensionScope.FRAMEWORK)
public interface Compiler {

    /**
     * Compile java source code.
     * @deprecated use {@link Compiler#compile(Class, String, ClassLoader)} to support JDK 16
     */
    @Deprecated
    default Class<?> compile(String code, ClassLoader classLoader) {
        return compile(null, code, classLoader);
    }

    /**
     * Compile java source code.
     * @param neighbor    A class belonging to the same package that this
     *                    class belongs to.  It is used to load the class. (For JDK 16 and above)
     */
    default Class<?> compile(Class<?> neighbor, String code, ClassLoader classLoader) {
        return compile(code, classLoader);
    }
}
```

新增的 `neighbor` 参数是**为支持 JDK 16+ 必需的**：JDK 9+ 的模块系统要求定义类与目标类同包，`javassist` 的 `toClass()` 在 JDK 16 之后不再支持传入任意 ClassLoader 去定义类，必须借助一个同包的「邻居类」作为定义锚点。`ExtensionLoader` 传的就是 `type`（那个 SPI 接口）本身。

注意这两个 default 方法是**互相委托**的，如果第三方实现类两个都不覆写就会无限递归（`StackOverflowError`）。自定义 `Compiler` 必须覆写至少一个。

SPI 文件三行：

```properties
# dubbo-common/src/main/resources/META-INF/dubbo/internal/org.apache.dubbo.common.compiler.Compiler
adaptive=org.apache.dubbo.common.compiler.support.AdaptiveCompiler
jdk=org.apache.dubbo.common.compiler.support.JdkCompiler
javassist=org.apache.dubbo.common.compiler.support.JavassistCompiler
```

`AdaptiveCompiler` 通过 `DEFAULT_COMPILER`（由 `ApplicationConfig#setCompiler()` 设置）决定用哪个实现，未设置则用 `@SPI("javassist")` 声明的默认值。

### JavassistCompiler and JdkCompiler

这两个类**仍在 `dubbo-common` 的 `org.apache.dubbo.common.compiler.support` 包**，类名、`NAME` 常量、结构都没有变化。`JavassistCompiler` 依然是「正则解析源码 → `CtClassBuilder` → `toClass`」这条路：

```java
// dubbo-common/src/main/java/org/apache/dubbo/common/compiler/support/JavassistCompiler.java:32-59
public class JavassistCompiler extends AbstractCompiler {

    public static final String NAME = "javassist";

    private static final Pattern IMPORT_PATTERN = Pattern.compile("import\\s+([\\w\\.\\*]+);\n");

    private static final Pattern EXTENDS_PATTERN = Pattern.compile("\\s+extends\\s+([\\w\\.]+)[^\\{]*\\{\n");

    private static final Pattern IMPLEMENTS_PATTERN = Pattern.compile("\\s+implements\\s+([\\w\\.]+)\\s*\\{\n");

    private static final Pattern METHODS_PATTERN = Pattern.compile("\n(private|public|protected)\\s+");

    private static final Pattern FIELD_PATTERN = Pattern.compile("[^\n]+=[^\n]+;");

    @Override
    public Class<?> doCompile(String name, String source) throws Throwable {
        CtClassBuilder builder = new CtClassBuilder();
        builder.setClassName(name);

        // process imported classes
        Matcher matcher = IMPORT_PATTERN.matcher(source);
        while (matcher.find()) {
            builder.addImports(matcher.group(1).trim());
        }
        // ... 处理 extends / implements / 成员
```

`JdkCompiler` 同样保留 `ToolProvider.getSystemJavaCompiler()` + `ClassLoaderImpl` + `JavaFileManagerImpl` 那套 `DEFAULT_JAVA_VERSION = "1.8"` 的字段结构，靠 JDK 内置编译器 + 内存文件管理器工作。

> [!NOTE]
> 旧的 `findClassLoader()` 在这两个类里也没有出现。`JavassistCompiler` 取 CL 用的是 `ClassUtils.getCallerClassLoader(getClass())`——按调用栈回溯拿到 Dubbo 自己的 ClassLoader，而不是取 SPI 接口的 CL。所以**自定义 `Compiler` 时要自己决定 `classLoader` 参数怎么用**，别假设它一定是接口的 ClassLoader。

## AOP

Dubbo AOP 用 wrapper 模式实现，一个类要成为 AOP wrapper 必须同时满足：

- 实现该 SPI 接口；
- 构造器**有且仅有一个**参数，类型就是该 SPI 接口（判定逻辑在 `ExtensionLoader.java:1412-1420` 的 `isWrapperClass`）；
- 和普通扩展一样写进 `META-INF/dubbo/internal/org.apache.dubbo.rpc.Protocol` 等配置文件。

排序由 `@Wrapper(order = ...)` 控制，默认 `0`；`matches` 为空表示全匹配，`mismatches` 永远排除。加载后 `cachedWrapperClasses` 按 `WrapperComparator` 排序并反转，再逐层包裹。

## Quick Reference of Key Mechanisms

| 机制 | 3.3.6 位置 | 要点 |
| --- | --- | --- |
| `@SPI` | `SPI.java:53-67` | 只有 `value` + `scope`（默认 `APPLICATION`） |
| `ExtensionScope` | `ExtensionScope.java` | `FRAMEWORK` / `APPLICATION` / `MODULE` / `SELF` |
| 扩展加载器归属 | `ExtensionDirector.java:67-107` | scope 匹配 → 父委派 → 创建 |
| 实例缓存 | `ExtensionLoader.java:117` | `extensionInstances` 是**实例**字段，非静态 |
| 注入器 | `ExtensionLoader.java:121` | `ExtensionInjector injector`，`ExtensionFactory` 已废弃 |
| 取加载器 | `ExtensionAccessor.java:31`、`ScopeModelUtil.java:100` | 静态单参版 `@Deprecated` |
| 类加载器 | `ScopeModel.java:252` | `scopeModel.getClassLoaders()`，`findClassLoader()` 已删除 |
| 类加载锁 | `ExtensionLoader.java:125` | `ReentrantLock` |
| 特殊加载策略 | `ExtensionLoader.java:115`、`:143` | `special_spi.properties` |
| 包过滤 | `LoadingStrategy.java` | `excludedPackages` / `includedPackages` / `onlyExtensionClassLoaderPackages` |
| 条件加载 | `ExtensionLoader.java:1309-1333` | `@Activate.onClass` 全部命中才加载 |
| 激活缓存 | `ExtensionLoader.java:129-130` | `cachedActivateGroups` + `cachedActivateValues` |
| 排序 | `ActivateComparator.java:43` | 实例字段，构造入参 `ExtensionDirector` |
| 前后置处理 | `ExtensionPostProcessor.java:22` | 默认注册 `ScopeModelAwareExtensionProcessor` |
| 实例化策略 | `InstantiationStrategy.java:33` | 先无参构造，再试带 `ScopeModel` 的构造 |
| 代码生成 | `AdaptiveClassCodeGenerator.java:98` | 在 `common.extension` 包，**不在 `support`** |
| 编译器接口 | `Compiler.java:25-53` | 三参为主，两参 `@Deprecated` |
| 生命周期 | `ExtensionLoader.java:249-285` | `destroy()` / `checkDestroyed()` |

## Pitfall List

1. **`@SPI` 没有 `dependencies`，也没有 `order`。** 排序看 `@Activate(order = ...)`，默认 `0`（`Activate.java:93`），升序排列，值越小越靠前。
2. **`ExtensionLoader.getExtensionLoader(Class)` 已 `@Deprecated`**，且 `resetExtensionLoader(Class)` 是空方法体（`ExtensionLoader.java:241-247`）。新入口是 `scopeModel.getExtensionLoader(type)` 或 `ScopeModelUtil.getExtensionLoader(type, scopeModel)`。`getExtensionLoader(Class, ScopeModel)` 这个签名在 `ScopeModelUtil` 上，**不在 `ExtensionLoader` 上**。
3. **`EXTENSION_LOADERS` / `EXTENSION_INSTANCES` 两个静态 Map 不存在了。** 前者搬到 `ExtensionDirector.extensionLoadersMap`，后者变成 `ExtensionLoader` 的实例字段 `extensionInstances`。
4. **`objectFactory` 叫 `injector` 了**，类型是 `ExtensionInjector`。
5. **`findClassLoader()` 已删除。** 改用 `scopeModel.getClassLoaders()`。
6. **没有 `META-INF/dubbo/internal/org.apache.dubbo.common.extension.ExtensionFactory` 这个文件。** 只有 `ExtensionInjector`（3 行），且 `SpringExtensionInjector` 在 `dubbo-config-spring` 而非 `dubbo-common`。
7. **`AdaptiveClassCodeGenerator` 在 `org.apache.dubbo.common.extension`，不在 `extension.support`。**
8. **`Compiler.compile(String, ClassLoader)` 已 `@Deprecated`。** 主签名是 `compile(Class<?> neighbor, String code, ClassLoader)`；两个 default 互相委托，自定义实现必须覆写至少一个。
9. **`@Activate(order)` 默认是 `0`，不是 `-1`。** 「自定义扩展排在内置之后」这个结论偶然成立，真实规则是按 `order` 数值升序，与「内置/自定义」身份无关。
10. **`@SPI(scope = ...)` 决定实例归属哪一层模型。** `FRAMEWORK` 只有框架层能创建，`APPLICATION` 每个应用一份，`MODULE` 每个服务模块一份，`SELF` 每层一份且不走父委派（`ExtensionInjector` 就是 `SELF`）。
11. **自适应扩展的 ClassLoader 是 `type.getClassLoader()`，不是 Dubbo 自己的。** 因为生成类必须和 SPI 接口同 ClassLoader，否则 `instanceof` 不成立。
12. **GraalVM native-image 下不做代码生成**，直接加载构建期预生成的 `Xxx$Adaptive`。
13. **`loadResource` 的过滤是三重的**：`!isExcluded && isIncluded && !isExcludedByClassLoader`。只判 `excludedPackages` 的时代已经过去。
14. **`activateExtensionsMap` 以 `Class` 为 key**，不是 `String`。所以同名冲突在 `saveInExtensionClass` 阶段就会被拦下并记入 `unacceptableExceptions`，`getExtension` 时抛 `findException(name)` 带出原始加载异常。
15. **写 `ExtensionPostProcessor` 时不要假设 `name` 非空**——自适应扩展走 `postProcessBeforeInitialization(instance, null)`。
16. **`ScopeModelAware` 由 `postProcessAfterInitialization`（后置）注入，不是前置。** `ScopeModelAwareExtensionProcessor` 只重写了 `postProcessAfterInitialization`（`ScopeModelAwareExtensionProcessor.java:54`），前置阶段什么都不做；`ExtensionAccessorAware` 则在 `ExtensionLoader.postProcessAfterInitialization`（`:842`）直接注入。
17. **`ExtensionLoader.destroy()` 没有 `disposableInstances` 字段。** 它遍历 `extensionInstances`（裸实例）与 `cachedInstances`（包装实例）两个缓存，凡 `instance instanceof Disposable` 即调 `destroy()`；`Disposable.destroy()` 签名是 `void destroy();`（无 `throws Exception`）。
18. **`findException` 抛出的外层 `IllegalStateException` 没有 `cause`**——真实根因（如 `NoClassDefFoundError`）只出现在消息的 "possible causes" 段落文本里，catch 时要读消息而非只看 `getCause()`。

## Links

- [ScopeModel](/docs/CS/Framework/Dubbo/ScopeModel.md)
- [cluster](/docs/CS/Framework/Dubbo/cluster.md)
- [Filter](/docs/CS/Framework/Dubbo/Filter.md)
- [Protocol](/docs/CS/Framework/Dubbo/Protocol.md)
- [ThreadPool](/docs/CS/Framework/Dubbo/ThreadPool.md)
- [Serialization](/docs/CS/Framework/Dubbo/Serialization.md)

## References

- [扩展点开发指南](https://cn.dubbo.apache.org/zh-cn/overview/mannual/java-sdk/reference-manual/architecture/dubbo-spi/)
- [Extension Mechanism (Apache Dubbo 3.3.6 source)](https://github.com/apache/dubbo/tree/dubbo-3.3.6/dubbo-common/src/main/java/org/apache/dubbo/common/extension)