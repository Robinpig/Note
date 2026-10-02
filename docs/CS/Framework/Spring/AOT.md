## Introduction

AOT（Ahead-Of-Time，提前编译/处理）是相对于传统 Spring 应用在**运行时**靠反射、动态代理、classpath 扫描来装配 Bean 的方式而言的。
Spring Framework 6.0 / Spring Boot 3.0 引入了一等公民的 AOT 处理支持：在构建期分析应用的 `BeanFactory`，生成一份等价的、**直接使用代码而非反射**的 Bean 注册与初始化逻辑，从而降低运行时内存占用、缩短启动时间，并为 GraalVM Native Image 铺路。

引入 AOT 的核心动机来自 GraalVM 的 native-image：它在构建阶段做**封闭世界假设（closed-world assumption）**静态分析，要求所有反射、动态代理、资源加载、JNI 访问都必须提前显式声明，否则运行期会因为“看不到”这些元数据而失败。
传统 Spring 大量依赖运行时反射，无法直接通过这种静态分析，因此需要一个 AOT 阶段把运行时才确定的东西“烘焙（bake）”成构建期产物。

## AOT Processing

Spring AOT 处理发生在构建插件（Maven/Gradle）触发的一个特殊阶段，输入是应用启动后构建好的 `GenericApplicationContext` / `BeanFactory`，输出是 Java 源代码 + 资源文件 + 运行时提示。

典型的处理步骤：

1. 应用以 AOT 模式被触发（`spring-boot:process-aot`），正常执行一遍 `BeanFactory` 的创建，得到一个“refresh 过但不真正启动 Web 容器”的上下文。
2. `BeanFactoryInitializationAotContribution` / `BeanRegistrationAotContribution` 等贡献器遍历每个 BeanDefinition，生成直接 `new`、直接调用工厂方法、直接注册 BeanDefinition 的 Java 代码，替代运行时的反射扫描。
3. 为切面、配置类（`@Configuration` 的 CGLIB 代理）、`@Bean` 方法等生成显式的代理类与注册代码。
4. 收集反射 / 资源 / 序列化 / JNI / 动态代理所需的元数据，产出 `reflect-config.json`、`resource-config.json`、`proxy-config.json`、`serialization-config.json` 等 GraalVM 可达性配置。

构建产物默认输出到 `target/spring-aot/main/`（sources、classes、resource-config 等目录）。

### JIT vs AOT vs Native

| 维度 | JIT（传统 Spring） | Spring AOT（仍跑在 JVM） | GraalVM Native Image |
| ---- | ---- | ---- | ---- |
| Bean 装配时机 | 运行时反射扫描 | 构建期生成代码，运行时直接执行 | 同 AOT，且整体编译为本地可执行文件 |
| 启动速度 | 基线 | 略快（少了反射与扫描） | 毫秒级，显著最快 |
| 运行时内存 | 基线 | 更低 | 最低（无需保留 JIT/类加载热路径） |
| 峰值吞吐 | 高（JIT 持续优化） | 高 | 需 PGO 才能逼近 JIT |
| 反射 / 动态能力 | 完全开放 | 受限，需显式 hint | 严格封闭世界，动态加载几乎不可用 |
| 可移植性 | jar 跨平台 | jar 跨平台 | 平台相关二进制，需按 OS/arch 分别构建 |

AOT 是 Native Image 的**必要前置**，但 AOT 本身也可以只用于普通 JVM 部署来换取启动与内存收益，不必一定编译成 native。

## RuntimeHints

封闭世界分析无法自动推断的东西，需要通过 `RuntimeHints` 显式声明。常见三类：

- **Reflection hints**：哪些类/构造器/方法/字段需要反射可见（`RuntimeHints.reflection()`）。
- **Resource hints**：哪些 classpath 资源（配置文件、模板、`META-INF` 下文件）需要被打进二进制（`RuntimeHints.resources()`）。
- **Serialization / Proxy / JNI hints**：Java 序列化类、JDK 动态代理接口、JNI 访问等。

Spring 在自动配置、`@RegisterReflectionForBinding`、Jackson 数据绑定、Spring MVC 视图解析等处会自动贡献大量 hint；第三方库或自定义反射则需要自己补。

### RuntimeHintsRegistrar

当默认推断覆盖不到自定义反射时，实现 `RuntimeHintsRegistrar` 并通过 `@ImportRuntimeHints` 注册：

```java
public class MyHints implements RuntimeHintsRegistrar {

    @Override
    public void registerHints(RuntimeHints hints, ClassLoader classLoader) {
        // 声明某个 DTO 需要被反射实例化 / 读取方法（典型：被 Jackson、BeanUtils 反射使用）
        hints.reflection().registerType(
                TypeReference.of(com.example.MyDto.class),
                MemberCategory.INVOKE_DECLARED_CONSTRUCTORS,
                MemberCategory.INVOKE_PUBLIC_METHODS);

        // 声明需要打包进 native image 的资源
        hints.resources().registerPattern("my/config/*.json");
    }
}
```

```java
@Configuration
@ImportRuntimeHints(MyHints.class)
class MyConfiguration {
}
```

## Constraints

使用 AOT / Native 时需要接受的主要约束：

- **条件装配在构建期求值**：`@ConditionalOnClass`、`@ConditionalOnBean` 等按构建时 classpath 固化，运行时动态增删依赖不再生效。
- **Profile / 配置**：Bean 是否存在仍可由运行时 profile 决定（生成代码里保留条件分支），但类必须在构建期可见。
- **去掉运行时动态性**：运行时动态注册 Bean、配置热刷新、运行期临时生成新字节码的类库、动态脚本等可能不兼容。
- **延迟类加载消失**：native image 把所有代码在构建期链接，`ClassNotFoundException` 一类问题会提前暴露为构建失败——这反而是一种“左移”。

## Build

Spring Boot 构建插件一键触发 AOT 与 native 构建：

```xml
<plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
</plugin>
```

```shell
# 仅执行 AOT 处理（产物在 target/spring-aot），仍以普通 JVM 运行
mvn -Pnative process-aot

# 借助 GraalVM native-maven-plugin 生成本地可执行文件
mvn -Pnative native:compile

# 或构建原生容器镜像（内部完成 AOT + native-image）
mvn -Pnative spring-boot:build-image
```

Gradle 对应 `bootProcessAot` / `nativeCompile` 任务。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [IoC Container](/docs/CS/Framework/Spring/IoC.md)
- [Spring Test](/docs/CS/Framework/Spring/Test.md)

## References

1. [Spring Framework Reference - AOT](https://docs.spring.io/spring-framework/reference/core/aot.html)
2. [Spring Boot Reference - Native Image](https://docs.spring.io/spring-boot/reference/native-image/index.html)
3. [GraalVM Native Image](https://www.graalvm.org/latest/reference-manual/native-image/)
