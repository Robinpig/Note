## Introduction

Spring Boot 的自动配置建立在一套 SPI（Service Provider Interface）式机制之上：每个提供自动配置的模块，把自己要注册的自动配置类名写进约定路径的清单文件，框架启动时统一读出来、按条件筛选、最后导入容器。

这套机制的**清单文件在 Boot 3.0 发生过一次迁移**，是读旧资料最容易踩的坑：

| 时期 | 清单文件 | 读取方式 |
| :-- | :-- | :-- |
| Boot 2.x | `META-INF/spring.factories`（K/V 格式，键为 `org.springframework.boot.autoconfigure.EnableAutoConfiguration`） | `SpringFactoriesLoader` |
| Boot 3.x 起 | `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`（一行一个类的纯清单） | `ImportCandidates` + `AutoConfigurationImportSelector` |

新格式在 Boot 2.7 作为过渡被同时支持，**Boot 3.0 起 `spring.factories` 不再用于注册自动配置**。Boot 4.0 进一步把原本单一的 `spring-boot-autoconfigure` 拆成上百个模块，每个模块各自携带一份 `.imports` 文件，由 starter 按需聚合。

> [!NOTE]
> `spring.factories` 本身并没有被删除。它仍用于注册 `ApplicationContextInitializer`、`ApplicationListener`、`EnvironmentPostProcessor`、`FailureAnalyzer`、`PropertySourceLoader` 等扩展点——只是**不再承担自动配置的注册职责**。

## How to Write the Manifest File

```
META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
```

内容是一行一个全限定类名，可以用 `#` 写注释：

```
com.mycorp.libx.autoconfigure.LibXAutoConfiguration
com.mycorp.libx.autoconfigure.LibXWebAutoConfiguration
```

两条容易被忽略的规则：

- 若自动配置类是**内部类**，用 `$` 分隔（`com.example.Outer$NestedAutoConfiguration`）。
- 自动配置类**只能**通过 `.imports` 被加载：必须放在独立的包空间里，**永远不要**让它成为组件扫描的目标。Boot 的 `AutoConfigurationExcludeFilter` 会主动把自动配置类从 `@SpringBootApplication` 的扫描结果中剔除——它既检查 `@AutoConfiguration` 注解，也检查 `ImportCandidates` 读到的名单。

### Replacement Mapping After Renaming

自动配置类改包名时，旧类名可能仍出现在别人的 `before`/`after` 排序或 `exclude` 配置里。为此可以再放一个 K/V 文件声明替换关系：

```
# META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.replacements
com.mycorp.libx.autoconfigure.LibXAutoConfiguration=com.mycorp.libx.autoconfigure.core.LibXAutoConfiguration
```

`.imports` 文件本身也要更新为**只列新类**。

## Loading Pipeline

`@SpringBootApplication` 上的 `@EnableAutoConfiguration` 通过 `@Import` 引入 `AutoConfigurationImportSelector`。它实现 `DeferredImportSelector`，导入时机被推迟到用户自定义配置全部处理完之后，从而保证"用户显式声明的 Bean 优先于自动配置"。

```java
public class AutoConfigurationImportSelector implements DeferredImportSelector, BeanClassLoaderAware,
        ResourceLoaderAware, BeanFactoryAware, EnvironmentAware, Ordered {

    @Override
    public String[] selectImports(AnnotationMetadata annotationMetadata) {
        if (!isEnabled(annotationMetadata)) {
            return NO_IMPORTS;
        }
        AutoConfigurationEntry autoConfigurationEntry = getAutoConfigurationEntry(annotationMetadata);
        return StringUtils.toStringArray(autoConfigurationEntry.getConfigurations());
    }

    protected AutoConfigurationEntry getAutoConfigurationEntry(AnnotationMetadata annotationMetadata) {
        AnnotationAttributes attributes = getAttributes(annotationMetadata);
        List<String> configurations = getCandidateConfigurations(annotationMetadata, attributes);
        configurations = removeDuplicates(configurations);
        Set<String> exclusions = getExclusions(annotationMetadata, attributes);
        checkExcludedClasses(configurations, exclusions);
        configurations.removeAll(exclusions);
        configurations = getConfigurationClassFilter().filter(configurations);
        fireAutoConfigurationImportEvents(configurations, exclusions);
        return new AutoConfigurationEntry(configurations, exclusions);
    }

    protected List<String> getCandidateConfigurations(AnnotationMetadata metadata, AnnotationAttributes attributes) {
        List<String> configurations = ImportCandidates.load(AutoConfiguration.class, getBeanClassLoader())
                .getCandidates();
        Assert.notEmpty(configurations,
                "No auto configuration classes found in META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports");
        return configurations;
    }
}
```

管线上的每一步：

1. **候选收集**：`ImportCandidates.load()` 扫描类路径上所有 `.imports` 文件，汇总候选类名（底层就是 `classpath*:` 资源扫描，见 [Resource](/docs/CS/Framework/Spring/Resource.md)）。
2. **去重**：`removeDuplicates()` 处理同名类。
3. **排除**：`getExclusions()` 读取 `@EnableAutoConfiguration(exclude=...)` 与 `spring.autoconfigure.exclude` 配置，并校验被排除的类确实在候选里（否则启动时报错，避免"排了个寂寞"）。
4. **条件过滤**：`getConfigurationClassFilter().filter()` 依据 `@ConditionalOnClass` / `@ConditionalOnMissingBean` / `@ConditionalOnProperty` 等剔除不满足的配置类——这是"自动配置够不够聪明"的真正来源。
5. **排序**：先按类名排序保证确定性，再应用 `@AutoConfigureOrder`，最后按 `@AutoConfigureBefore` / `@AutoConfigureAfter` 做拓扑排序（有环会直接报错）。

条件评估在 Boot 4 是**两阶段**的：先用编译期生成的元数据与 `Class.forName` 做一次廉价过滤（不加载候选类的字节码），通过者才进入 `ConditionEvaluator` 的完整评估。这也是模块拆分带来的启动收益之一。

## Write an Auto-Configuration

```java
@AutoConfiguration(after = RedisAutoConfiguration.class)          // 顺序
@ConditionalOnClass(RedisConnectionFactory.class)                 // 依赖库存在
@ConditionalOnProperty(prefix = "libx", name = "enabled", matchIfMissing = true)
@EnableConfigurationProperties(LibXProperties.class)              // 绑定配置
public class LibXAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    LibXTemplate libXTemplate(RedisConnectionFactory factory, LibXProperties props) {
        return new LibXTemplate(factory, props.getTimeout());
    }
}
```

`@AutoConfiguration` 本身被 `@Configuration` 元注解标记，语义上等价于 `@Configuration(proxyBeanMethods = false)`，但额外表达了"这是自动配置、只能从 `.imports` 加载"。

### Quick Reference of Conditional Annotations

| 类别 | 注解 | 判定依据 |
|---|---|---|
| 类条件 | `@ConditionalOnClass` / `@ConditionalOnMissingClass` | 类路径上是否存在某个类（用 ASM 读注解元数据，不会真的加载该类，所以可以安全引用"可能不存在"的类） |
| Bean 条件 | `@ConditionalOnBean` / `@ConditionalOnMissingBean` / `@ConditionalOnSingleCandidate` | 容器中是否已有某类型 Bean |
| 属性条件 | `@ConditionalOnProperty` | 配置属性是否匹配（注意 `matchIfMissing` 决定"没配置时算不算匹配"） |
| 资源条件 | `@ConditionalOnResource` | 指定资源是否存在 |
| Web 条件 | `@ConditionalOnWebApplication` / `@ConditionalOnNotWebApplication` | 是否 web 应用及其类型 |
| 表达式 | `@ConditionalOnExpression` | SpEL 求值 |
| 环境 | `@ConditionalOnJava` / `@ConditionalOnCloudPlatform` / `@ConditionalOnWarDeployment` | JDK 版本 / 云平台 / 部署形态 |
| 组合 | `AnyNestedCondition` / `AllNestedConditions` / `NoneNestedConditions` | 把多个条件组合成"任一/全部/都不" |

> [!WARNING]
> `@ConditionalOnClass` 用在 **`@Bean` 方法**上不可靠：条件生效前 JVM 已经加载了方法返回类型，类不存在会直接抛 `NoClassDefFoundError` 而不是"跳过"。需要隔离时，把该 Bean 拆到一个独立的 `@Configuration` 类里，用类级条件去保护它。

另一个常见约定：自动配置类**不应开启组件扫描**去发现组件，需要额外组件就用显式 `@Import`。组件扫描会把用户不想引入的东西拉进容器，也破坏"自动配置可预测"这一前提。

## Troubleshooting: Conditional Evaluation Report

自动配置没生效时，不要靠猜，先看报告：

```bash
java -jar app.jar --debug        # 或 application.properties 里 debug=true
```

启动时打印的 `CONDITIONS EVALUATION REPORT` 分四段：**Positive matches**（已生效）、**Negative matches**（未生效，并写明是哪个条件失败）、**Exclusions**（被排除）、**Unconditional classes**（无条件自动配置）。

运行中的实例可以通过 Actuator 的 `conditions` 端点读同一份报告（默认不暴露，见 [Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)）。

典型的失败原因只有几类：starter 缺失或依赖被限定为 `test`/`provided` 作用域；版本冲突导致类不在类路径；用户自定义 Bean 让 `@ConditionalOnMissingBean` 主动退让（这是**预期行为**，不是 bug）；被 `spring.autoconfigure.exclude` 排除了；或配置属性未满足条件。

## Test Auto-Configuration

用 `ApplicationContextRunner`（Web 场景用 `WebApplicationContextRunner` / `ReactiveWebApplicationContextRunner`）构造受控上下文：

```java
class LibXAutoConfigurationTests {

    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(LibXAutoConfiguration.class));

    @Test
    void backsOffWhenUserBeanPresent() {
        runner.withUserConfiguration(UserConfig.class)
              .run(context -> assertThat(context).hasSingleBean(LibXTemplate.class));
    }

    @Test
    void disabledByProperty() {
        runner.withPropertyValues("libx.enabled=false")
              .run(context -> assertThat(context).doesNotHaveBean(LibXTemplate.class));
    }

    @Test
    void skippedWhenLibraryMissing() {
        runner.withClassLoader(new FilteredClassLoader(RedisConnectionFactory.class))
              .run(context -> assertThat(context).doesNotHaveBean(LibXTemplate.class));
    }

    @Configuration(proxyBeanMethods = false)
    static class UserConfig {
        @Bean LibXTemplate myTemplate() { return new LibXTemplate(null, 0); }
    }
}
```

`AutoConfigurations.of(...)` 是关键：它按 Boot 真实的排序规则注册这些类，而不是绕过排序。

> [!WARNING]
> **Runner 通过 ≠ 自动配置能被发现**。Runner 是"你指名道姓告诉它测哪个类"，它无法证明 Boot 会找到这个类。真正的漏网之鱼是：类写好了、注解齐全、Runner 测试全绿，但**忘了写进 `.imports` 文件**——此时消费方应用里它完全不生效，而作者自己的应用因为组件扫描反而可能"看起来能用"（如果把类错标成了普通 `@Configuration`，作者能扫到、别人扫不到，更隐蔽）。
>
> 补一个直接读清单文件的测试即可堵住：
>
> ```java
> @Test
> void registeredInImportsFile() {
>     assertThat(ImportCandidates.load(AutoConfiguration.class, getClass().getClassLoader())
>             .getCandidates()).contains(LibXAutoConfiguration.class.getName());
> }
> ```

需要打印条件报告时，加一个 `ConditionEvaluationReportLoggingListener.forLogLevel(LogLevel.INFO)` 初始化器。

## AOT and Auto-Configuration

AOT（预编译）模式下，条件评估被提前到**构建期**完成，能静态判定的分支直接固化，运行时不再扫描 `.imports`、不再做类路径探测。这对启动时间和原生镜像体积收益明显，代价是"运行时才出现的类路径变化"不再被感知。详见 [AOT](/docs/CS/Framework/Spring/AOT.md)。

## Differences from JDK SPI

| 维度 | JDK SPI（`ServiceLoader`） | Spring Boot 自动配置 |
| :-- | :-- | :-- |
| 清单位置 | `META-INF/services/<接口全限定名>` | `META-INF/spring/...AutoConfiguration.imports`（旧版 `spring.factories`） |
| 格式 | 一行一个实现类 | 一行一个自动配置类 |
| 筛选能力 | 无，全部加载 | 条件注解按需装配 |
| 排序能力 | 无 | `Ordered` / `@AutoConfigureOrder` / before-after 拓扑排序 |
| 失败行为 | 单个实现报错影响整体 | 可随条件跳过，缺失依赖不报错 |
| 可见性 | 全类路径遍历 | 由 starter 决定引入哪些模块 |

JDK SPI 的用法见 [JDK SPI](/docs/CS/Java/JDK/Basic/SPI.md)。

## Common Pitfalls

| 陷阱 | 现象 | 处理 |
|---|---|---|
| 照抄旧教程写 `spring.factories` | Boot 3+ 自动配置完全不生效，且无任何报错 | 改用 `.imports` 文件 |
| 类没写进 `.imports` | 自己跑得通、别人跑不通；Runner 测试却全绿 | 加一个断言清单文件内容的测试 |
| 自动配置类被组件扫描到 | 行为不可控、条件失效 | 放独立包，用 `@AutoConfiguration` 而非 `@Configuration` |
| `@ConditionalOnClass` 标在 `@Bean` 方法上 | 类缺失时报 `NoClassDefFoundError` 而非跳过 | 拆到独立配置类做类级条件 |
| 忘记 `matchIfMissing` | 默认关闭导致"什么都不配就不生效" | 显式声明 `matchIfMissing = true` 表示默认开启 |
| before/after 声明成环 | 启动报循环依赖错误 | 用 `@AutoConfigureOrder` 解耦，而非互相声明 |
| 改了自动配置类的包名 | 使用方 `exclude` 失效 | 补 `.replacements` 文件 |

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Boot 启动流程](/docs/CS/Framework/Spring_Boot/Start.md)
- [Spring Boot 测试](/docs/CS/Framework/Spring_Boot/Test.md)
- [IoC Container](/docs/CS/Framework/Spring/IoC.md)

## References

1. [Spring Boot Reference - Creating Your Own Auto-configuration](https://docs.spring.io/spring-boot/reference/features/developing-auto-configuration.html)
2. [Spring Boot 3.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide)
3. [Modularizing Spring Boot](https://spring.io/blog/2025/10/28/modularizing-spring-boot)
