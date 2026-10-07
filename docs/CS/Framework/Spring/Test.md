## Introduction

Spring Test 是 `spring-test` 模块提供的测试支持，核心是 **TestContext Framework**：它在 JUnit / TestNG 等底层测试框架之上，用一套可插拔的 `TestContextManager` + `TestExecutionListener` 机制，负责创建并管理测试期间的 Spring `ApplicationContext`、依赖注入、事务回滚、Mock Bean 等横切能力。

在 Spring Boot 中，`spring-boot-starter-test` 把 TestContext、JUnit 5、AssertJ、Hamcrest、Mockito、JSONassert 等打包在一起，并通过 `@SpringBootTest` 提供开箱即用的切片/全量装配。

> [!WARNING]
> Boot 4 的模块化同样拆分了测试依赖：单个 `spring-boot-starter-test` 不再覆盖各技术的测试支持，Web 层另需 `spring-boot-starter-webmvc-test`（响应式对应 `spring-boot-starter-webflux-test`）等。迁移期可先用 `spring-boot-starter-test-classic` 兜底。Boot 侧切片测试、模块化 test starter、`@MockitoBean`、`RestTestClient`、Testcontainers 见 [Spring Boot 测试](/docs/CS/Framework/Spring_Boot/Test.md)。

## Annotations

常用测试注解按"启动多大上下文"分层：

| 注解 | 启动范围 | 典型用途 |
| ---- | ---- | ---- |
| `@SpringBootTest` | 完整应用上下文（可起真实端口） | 端到端、集成测试 |
| `@WebMvcTest` | 仅 Spring MVC 层（Controller + MockMvc） | Web 切片，Service 被 Mock |
| `@DataJpaTest` | 仅 JPA 组件 + 内嵌数据库 | Repository 切片 |
| `@JsonTest` / `@RestClientTest` | 仅 JSON 序列化 / REST 客户端 | 窄切片 |
| `@TestConfiguration` | 测试专用额外 Bean | 在不污染主配置的前提下补充 mock/stub |

`@MockitoBean` 向上下文里注入一个 Mockito mock 替换真实 Bean；`@MockitoSpyBean` 则包装真实 Bean 做部分模拟。这两个注解由 Spring Framework 6.2 引入，用来取代 Boot 侧的 `@MockBean` / `@SpyBean`——后者在 Boot 3.4 弃用、Boot 4 已移除。

## Core Extension Point: TestExecutionListener

TestContext 的横切能力不是硬编码的，而是由一组**有序的 `TestExecutionListener`** 在测试生命周期的各个钩子（准备类、准备方法、before/after each、after 类）上协作完成。默认注册的有：

| Listener | 职责 |
| :--- | :--- |
| `ServletTestExecutionListener` | 把 `MockHttpServletRequest` 等绑定到 `RequestContextHolder`，让 `@Autowired HttpServletRequest` 在测试里可用 |
| `DependencyInjectionTestExecutionListener` | 执行 `@Autowired` / `@Resource` 注入 |
| `DirtiesContextTestExecutionListener` | 处理 `@DirtiesContext`（决定何时丢弃上下文缓存） |
| `TransactionalTestExecutionListener` | 管理 `@Transactional` 测试事务与回滚 |
| `SqlScriptsTestExecutionListener` | 执行 `@Sql` 脚本 |
| `WithSecurityContextTestExecutionListener` | Spring Security 的 `@WithMockUser` 等 |
| `ReactorContextTestExecutionListener` | 把 Reactor `Context` 注入响应式测试线程 |

自定义扩展用 `@TestExecutionListeners(listeners = …, mergeMode = MERGE_WITH_DEFAULTS)`，否则 `REPLACE_DEFAULTS` 会关掉所有默认 listener（最常见的"注入不生效"踩坑）。

## Context Caching

一旦 TestContext Framework 为某个测试加载了 `ApplicationContext`（或 `WebApplicationContext`），该上下文会被**缓存复用**，供同一个测试套件里所有声明了"相同上下文配置"的后续测试使用，而不是每个测试类都重启一次。

判断"是否同一个上下文"的依据是一组 `MergedContextConfiguration` 参数：配置类 / 配置文件位置、`locations`、profiles、property sources、contextInitializerClasses、contextCustomizer 等。只要这些完全一致，就命中同一个缓存条目；任意一项不同就会新建一个上下文。

因此测试实践上要注意：

- **不要在测试里随意修改会成为 context cache key 的东西**，否则会把上下文"撑"出很多份，拖慢整体测试。
- 用 `@TestPropertySource(properties=...)` / `@DynamicPropertySource` 注入动态配置（如 Testcontainers 暴露的端口）时，相同值的测试共享上下文。
- `@DirtiesContext` 会在该测试前后**移除并重建**上下文（`AFTER_TEST` / `BEFORE_CLASS` 等模式），只在确实污染了容器状态（改了 Bean 单例状态）时才用，代价很高。
- JVM 内缓存上限默认 32（`spring.test.context.cache.maxSize`），超出后按 LRU 关闭最久未用的上下文。
- `@ParameterizedTest`（JUnit Jupiter）的每个参数组合是独立的测试方法，但 **context cache key 由类级配置决定**，与方法级参数无关，因此同类的不同参数共用同一个上下文——这是参数化测试启动快的原因。

## Transactions

默认情况下，标注了 `@Transactional` 的测试方法结束后会**自动回滚**，从而保证每个测试对数据库的改动互不污染、可重复执行：

```java
@DataJpaTest
class UserRepositoryTest {

    @Autowired UserRepository repository;

    @Test
    @Transactional
    void shouldSaveUser() {
        repository.save(new User("alice"));
        // 方法结束默认 rollback，不会真正落库
        assertThat(repository.findByName("alice")).isPresent();
    }
}
```

- 改真实提交用 `@Commit`（或 `@Rollback(false)`）。
- 在事务内需要**手动**控制提交/回滚时，用静态 API：`TestTransaction.start()` / `TestTransaction.commit()` / `TestTransaction.rollback()` / `TestTransaction.flagForRollback()` / `TestTransaction.isActive()`。
- `@Sql` 注解可在测试前后执行指定脚本准备数据；`executionPhase` 控制 `BEFORE_TEST_METHOD` / `AFTER_TEST_METHOD`，`@SqlConfig` 配置分隔符、编码、`transactionMode`（是否并入测试事务）。

> [!WARNING]
> 在 `webEnvironment = RANDOM_PORT` 下 `@Transactional` **不回滚**：请求在 Tomcat 工作线程里处理并自行提交，测试线程的事务管不到服务端。只有 `MOCK` 环境（如 `@WebMvcTest`、`@DataJpaTest` 默认）才会加入测试事务。详见 [Spring Boot 测试](/docs/CS/Framework/Spring_Boot/Test.md) 的上下文缓存说明。

## Web Test

### MockMvc (Does Not Actually Start a Container)

`MockMvc` 提供不真正起 Servlet 容器的 HTTP 层测试，可对状态码、视图、JSON、Flash 属性做断言：

```java
@WebMvcTest(UserController.class)
class UserControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean UserService userService;

    @Test
    void getUser() throws Exception {
        when(userService.findById(1L)).thenReturn(new User(1L, "alice"));

        mvc.perform(get("/users/1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("alice"));
    }
}
```

> [!WARNING]
> `@WebMvcTest` 的组件扫描**不包括 `@Configuration`**，自定义的 `SecurityFilterChain` 不会生效，切片里跑的是 Boot 默认安全链——表现为本该公开的 GET 变 401、POST 变 403。要带上真实安全配置需 `@Import(SecurityConfig.class)`。

### End-to-End: WebTestClient and RestTestClient

需要真正监听端口做端到端调用时：

- **响应式（WebFlux）**：注入 `WebTestClient`（`@AutoConfigureWebTestClient`）。
- **Servlet（Boot 4 一代）**：用 `RestTestClient` 替代已迁移包的 `TestRestTemplate`——它基于 `RestClient`，API 更现代，原生支持同步与响应式两种模式，是 Boot 4 的新默认。

```java
@SpringBootTest(webEnvironment = RANDOM_PORT)
class UserApiTest {

    @Autowired RestTestClient rest;

    @Test
    void getUser() {
        rest.get().uri("/users/1").exchange()
            .expectStatus().isOk()
            .expectBody(User.class).isEqualTo(new User(1L, "alice"));
    }
}
```

## Integration with JUnit 5/6

Spring 7 起，`SpringExtension` 默认使用**测试方法作用域**的 `ExtensionContext`（`@Nested` 嵌套测试里注入行为更一致）。需要退回"整个测试类共享一个上下文"的旧行为时：

```java
@SpringExtensionConfig(useTestClassScopedExtensionContext = true)   // Spring 7 新增
class MyTest { … }
```

也可全局设 `spring.test.extension.context.scope=test_class`（Spring 7.0.7+）一次性切换。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Boot Testing](/docs/CS/Framework/Spring_Boot/Test.md)
- [IoC Container](/docs/CS/Framework/Spring/IoC.md)
- [Spring Web MVC](/docs/CS/Framework/Spring/MVC.md)
- [Spring JPA](/docs/CS/Framework/Spring/JPA.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)

## References

1. [Spring Framework Reference - Testing](https://docs.spring.io/spring-framework/reference/testing.html)
2. [Spring Boot Reference - Testing](https://docs.spring.io/spring-boot/reference/testing/index.html)
3. [JUnit 5 User Guide](https://junit.org/junit5/docs/current/user-guide/)
