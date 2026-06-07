## Introduction


## Context Management

### Cache Context

Spring Test 支持的一个不错特性是应用上下文会在测试之间缓存。
这样，如果测试用例中有多个方法或多个测试用例使用相同的配置，它们只需承担一次启动应用的开销。
你可以通过 @DirtiesContext 注解来控制缓存。



一旦 TestContext 框架为测试加载了 ApplicationContext（或 WebApplicationContext），该上下文就会被缓存，并重用于同一测试套件中声明相同唯一上下文配置的所有后续测试。要理解缓存的工作原理，理解"唯一"和"测试套件"的含义非常重要。

ApplicationContext 可以通过用于加载它的配置参数组合来唯一标识。因此，配置参数的唯一组合用于生成缓存上下文的键。TestContext 框架使用以下配置参数来构建上下文缓存键：

* `locations`（来自 `@ContextConfiguration`）
* `classes`（来自 `@ContextConfiguration`）
* `contextInitializerClasses`（来自 `@ContextConfiguration`）
* `contextCustomizers`（来自 `ContextCustomizerFactory`）——这包括 `@DynamicPropertySource` 和 `@MockBean`、`@SpyBean` 等方法以及 Spring Boot 测试支持的各种功能
* `contextLoader`（来自 `@ContextConfiguration`）
* `parent`（来自 `@ContextHierarchy`）
* `activeProfiles`（来自 `@ActiveProfiles`）
* `propertySourceLocations`（来自 `@TestPropertySource`）
* `propertySourceProperties`（来自 `@TestPropertySource`）
* `resourceBasePath`（来自 `@WebAppConfiguration``）



通常，你应该避免修改应用上下文中阻止其重用的任何全局状态。

确保始终清理资源，并在每次测试执行后保持 Spring 上下文的干净。

尽量在集成测试中保持相同的上下文配置。为此，你可以引入一个包含公共配置的抽象父类。

```java
@AutoConfigureMockMvc
@ContextConfiguration(initializers = CustomInitializer.class)
@SpringBootTest(webEnvironment = RANDOM_PORT)
public abstract class AbstractIntegrationTest {
 
  @BeforeAll
  public static void commonSetup() {
    // e.g. provide WireMock stubs
  }
}
```

## Transaction Management

使用 @Transactional 回滚更改

之前，在测试持久层时，我们看到 @DataJpaTest 默认使测试具有 @Transactional 行为。
然而，@SpringBootTest 不会这样做，所以如果我们希望在测试后回滚任何更改，必须自己添加 @Transactional 注解：

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
