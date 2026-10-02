## Introduction

Spring Test 是 `spring-test` 模块提供的测试支持，核心是 **TestContext Framework**：它在 JUnit / TestNG 等底层测试框架之上，用一套可插拔的 `TestContextManager` + `TestExecutionListener` 机制，负责创建并管理测试期间的 Spring `ApplicationContext`、依赖注入、事务回滚、Mock Bean 等横切能力。

在 Spring Boot 中，`spring-boot-starter-test` 把 TestContext、JUnit 5、AssertJ、Hamcrest、Mockito、JSONassert 等打包在一起，并通过 `@SpringBootTest` 提供开箱即用的切片/全量装配。

## Annotations

常用测试注解按“启动多大上下文”分层：

| 注解 | 启动范围 | 典型用途 |
| ---- | ---- | ---- |
| `@SpringBootTest` | 完整应用上下文（可起真实端口） | 端到端、集成测试 |
| `@WebMvcTest` | 仅 Spring MVC 层（Controller + MockMvc） | Web 切片，Service 被 Mock |
| `@DataJpaTest` | 仅 JPA 组件 + 内嵌数据库 | Repository 切片 |
| `@JsonTest` / `@RestClientTest` | 仅 JSON 序列化 / REST 客户端 | 窄切片 |
| `@TestConfiguration` | 测试专用额外 Bean | 在不污染主配置的前提下补充 mock/stub |

`@MockBean`（Boot 3.4 起推荐改用 `@MockitoBean`）向上下文里注入一个 Mockito mock 替换真实 Bean；`@SpyBean` 则包装真实 Bean 做部分模拟。

## Context Caching

Once the TestContext framework loads an ApplicationContext (or WebApplicationContext) for a test, that context is cached and reused for all subsequent tests that declare the same unique context configuration within the same test suite.

也就是说，启动 Spring 容器是昂贵的，TestContext 会把同一个上下文**缓存复用**，而不是每个测试类都重启一次。判断“是否同一个上下文”的依据是一组 `MergedContextConfiguration` 参数：配置类 / 配置文件位置、`locations`、profiles、property sources、contextInitializerClasses、contextCustomizer 等。只要这些完全一致，就命中同一个缓存条目；任意一项不同就会新建一个上下文。

因此测试实践上要注意：

- **不要在测试里随意修改会成为 context cache key 的东西**，否则会把上下文“撑”出很多份，拖慢整体测试。
- 用 `@TestPropertySource(properties=...)` / `@DynamicPropertySource` 注入动态配置（如 Testcontainers 暴露的端口）时，相同值的测试共享上下文。
- `@DirtiesContext` 会在该测试前后**移除并重建**上下文（`AFTER_TEST` / `BEFORE_CLASS` 等模式），只在确实污染了容器状态（改了 Bean 单例状态）时才用，代价很高。
- JVM 内缓存上限默认 32（`spring.test.context.cache.maxSize`），超出后按 LRU 关闭最久未用的上下文。

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

用 `@Commit`（或 `@Rollback(false)`）可改为真实提交；`@Sql` 注解可在测试前后执行指定脚本准备数据。

## Web Test

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

需要真正监听端口做端到端调用时，用 `@SpringBootTest(webEnvironment = RANDOM_PORT)` 注入 `TestRestTemplate` 或 `WebTestClient`。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Boot Testing](/docs/CS/Framework/Spring_Boot/Test.md)
- [IoC Container](/docs/CS/Framework/Spring/IoC.md)
- [Spring Web MVC](/docs/CS/Framework/Spring/MVC.md)
- [Spring JPA](/docs/CS/Framework/Spring/JPA.md)

## References

1. [Spring Framework Reference - Testing](https://docs.spring.io/spring-framework/reference/testing.html)
2. [Spring Boot Reference - Testing](https://docs.spring.io/spring-boot/reference/testing/index.html)
