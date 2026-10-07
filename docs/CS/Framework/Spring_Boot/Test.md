## Introduction

`spring-boot-starter-test` 在 Spring Test 的 TestContext 框架之上，提供 Boot 特有的**切片测试注解**与**测试期自动配置**。

通用内容——注解矩阵、TestContext 缓存机制、事务回滚、MockMvc 用法——见 [Spring Test](/docs/CS/Framework/Spring/Test.md)；本篇聚焦 Boot 侧。

> [!WARNING]
> **Boot 4 的测试基础设施有若干破坏性变更**：
>
> - `@MockBean` / `@SpyBean` 已**移除**，改用 `@MockitoBean` / `@MockitoSpyBean`（来自 `org.springframework.test.context.bean.override.mockito`）。新注解只能标注在测试类字段上，不能写在 `@Configuration` 类里。
> - `@SpringBootTest` **不再自动配置** `MockMvc` / `WebClient` / `TestRestTemplate`，需要显式加 `@AutoConfigureMockMvc` / `@AutoConfigureWebClient` / `@AutoConfigureTestRestTemplate`。
> - `TestRestTemplate` 移到 `org.springframework.boot.resttestclient` 包；并新增流式的 `RestTestClient` + `@AutoConfigureRestTestClient` 作为替代。
> - `@AutoConfigureMockMvc` 移到 `org.springframework.boot.webmvc.test.autoconfigure`。
> - 默认使用 **JUnit 6**，JUnit 4 已弃用。
> - 测试依赖按技术拆分：Web 层加 `spring-boot-starter-webmvc-test`，REST 客户端加 `spring-boot-starter-restclient-test`；迁移期可用 `spring-boot-starter-test-classic` 兜底。

## Test Dependencies: From "One starter" to "Split by Technology"

Boot 4 把单一的 `spring-boot-autoconfigure` 拆成上百个模块，测试支持也随之拆分。**一个 starter 对应一个 test starter**，用哪层就加哪个：

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-webmvc-test</artifactId>
  <scope>test</scope>
</dependency>
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-security-test</artifactId>
  <scope>test</scope>
</dependency>
```

| 用途 | 依赖 | 带来的能力 |
|---|---|---|
| Web MVC 层 | `spring-boot-starter-webmvc-test` | MockMvc、MockMvcTester、`@WebMvcTest` |
| WebFlux 层 | `spring-boot-starter-webflux-test` | `WebTestClient`、`@WebFluxTest` |
| REST 客户端 | `spring-boot-starter-restclient-test` | `RestTestClient`、`MockRestServiceServer` |
| JPA 层 | `spring-boot-starter-data-jpa-test` | `@DataJpaTest`、`TestEntityManager` |
| JDBC 层 | `spring-boot-starter-jdbc-test` | `@JdbcTest`、`@AutoConfigureTestDatabase` |
| 安全 | `spring-boot-starter-security-test` | `spring-security-test`、`@WithMockUser` |

迁移期不想一次性理清依赖，可以用 `spring-boot-starter-test-classic`——它把所有模块打进一个 POM（但不含第三方库），先跑起来再逐步收窄。踩过一次的典型症状是：`@AutoConfigureTestRestTemplate` 加了却报 `NoClassDefFoundError: RestTemplateBuilder`，根因是缺 `spring-boot-restclient` 模块。

## Slice Testing

切片（slice）测试只启动应用的一层，是"速度"与"可信度"之间的主要调节旋钮。Boot 4 把各切片的注解搬进了各自的模块，包名普遍变了：

| 注解 | Boot 3.x 包 | Boot 4 包 | 启动范围 |
|---|---|---|---|
| `@WebMvcTest` | `...test.autoconfigure.web.servlet` | `org.springframework.boot.webmvc.test.autoconfigure` | Controller、Advice、校验、转换器、Filter、Security（不启数据库） |
| `@AutoConfigureMockMvc` | `...test.autoconfigure.web.servlet` | `org.springframework.boot.webmvc.test.autoconfigure` | 同上 |
| `@DataJpaTest` | `...test.autoconfigure.orm.jpa` | `org.springframework.boot.data.jpa.test.autoconfigure` | JPA、Repository、嵌入式数据源 |
| `@AutoConfigureTestDatabase` | `...test.autoconfigure.jdbc` | `org.springframework.boot.jdbc.test.autoconfigure` | 数据源替换策略 |
| `TestEntityManager` | `...test.autoconfigure.orm.jpa` | `org.springframework.boot.jpa.test.autoconfigure` | 测试期 `EntityManager` 替身 |

完整切片清单与各自导入的自动配置类见官方附录 [Test Slices](https://docs.spring.io/spring-boot/appendix/test-auto-configuration/slices.html)（Boot 4 里是几十个 `spring-boot-*-test` 模块各贡献一行）。

```java
@WebMvcTest(OrderController.class)          // 只起 Web 层
class OrderControllerTest {

    @Autowired MockMvc mockMvc;

    @MockitoBean OrderService orderService; // Boot 3 写的是 @MockBean

    @Test
    void returnsOrder() throws Exception {
        given(orderService.find("O-1")).willReturn(new OrderDto("O-1", "PENDING"));
        mockMvc.perform(get("/orders/O-1"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.status").value("PENDING"));
    }
}
```

**选择顺序**：能不启 Spring 就不启（纯 JUnit）；逻辑只在 Web 层 → `@WebMvcTest`；只验证查询 → `@DataJpaTest`；跨层流程、过滤器链、认证授权 → `@SpringBootTest`。

> [!NOTE]
> `@WebMvcTest` 的组件扫描只包含 Web 相关类型（Controller、Advice、Converter、Filter 等），**`@Configuration` 类不算 Web 组件**。因此自定义的 `SecurityFilterChain` 不会被扫进来，切片里跑的是 Boot 的默认安全链——表现为本该公开的 GET 返回 401、POST 返回 403。解决办法是 `@Import(SecurityConfig.class)` 把它和它依赖的 Bean 一起导入。

## Override Bean: @MockitoBean

```java
@SpringBootTest
class OrderServiceTest {

    @MockitoBean PaymentGateway gateway;      // 替换同类型 Bean；不存在时注册一个新的
    @MockitoSpyBean InventoryClient inventory; // 包一层 spy，未打桩的调用走真实逻辑

    @Autowired OrderService orderService;
    // ...
}
```

与旧 `@MockBean` 的差异：

- 包从 `org.springframework.boot.test.mock.mockito` 迁到 Spring Framework 的 `org.springframework.test.context.bean.override.mockito`。
- **只能标注测试类字段**（也可以标注在测试方法内的局部变量上），写在 `@Configuration` 里不再生效。
- 每个测试方法结束后自动 reset。
- `@MockitoBean` 会让上下文缓存 key 发生变化——不同的 mock 组合对应不同的上下文，直接影响测试套件耗时。

## Web Layer and REST Client Testing

三种客户端，按"启动成本"排序：

| 方式 | 启用注解 | 是否起服务器 | 适用 |
|---|---|---|---|
| `MockMvc` | `@AutoConfigureMockMvc` | 否 | MVC 请求全流程、过滤器链 |
| `RestTestClient` + MockMvc | `@AutoConfigureMockMvc` + `@AutoConfigureRestTestClient` | 否 | 想要流式断言但不起服务器 |
| `RestTestClient` / `TestRestTemplate` + 真实端口 | `@SpringBootTest(webEnvironment = RANDOM_PORT)` + 对应 `@AutoConfigureXxx` | 是 | 端到端、真实序列化与网络栈 |

```java
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureRestTestClient
class OrderApiTest {

    @Autowired RestTestClient client;

    @Test
    void createsOrder() {
        client.post().uri("/orders")
              .body(new CreateOrderRequest("p-1", 2))
              .exchange()
              .expectStatus().isCreated()
              .expectHeader().location("/orders/1");
    }
}
```

`RestTestClient` 是 Boot 4 新增的流式客户端，内置断言，比 `TestRestTemplate` 更好用；后者虽然保留了，但已迁包且不再自动装配。

> [!TIP]
> `MockMvcTester`（Spring Framework 6.2 引入，`org.springframework.test.web.servlet.assertj.MockMvcTester`）是 MockMvc 的 AssertJ 封装，写法是 `assertThat(mvc.get().uri("/orders")).hasStatusOk()`，比 `andExpect` 链更接近现代断言习惯，可以在 `@WebMvcTest` 里直接注入。

## Data Layer Testing

```java
@DataJpaTest                                                     // 事务 + 自动回滚
@AutoConfigureTestDatabase(replace = Replace.NONE)               // 用真实数据源，别替换成 H2
class OrderRepositoryTest {

    @Autowired TestEntityManager em;   // 替代 EntityManager，提供 persistAndFlush / persistAndGetId
    @Autowired OrderRepository repository;

    @Test
    void findsByPublicId() {
        em.persistAndFlush(new Order("O-1", PENDING));
        em.clear();                    // 清一级缓存，避免断言命中缓存而非数据库
        assertThat(repository.findByPublicId("O-1")).isPresent();
    }
}
```

两个默认值要心里有数：

- 切片**默认替换数据源**为嵌入式内存库。方便，但如果查询里用了数据库厂商特有语法（MySQL 函数、Postgres 的 `jsonb` 操作），跑在 H2 上等于什么都没验证。用 `replace = Replace.NONE` 保留真实配置，配合 Testcontainers 起真实实例。
- 切片**默认事务回滚**。`@SpringBootTest` 不自带，需要自己加 `@Transactional`。

```java
@SpringBootTest
@Transactional
class UserServiceIntegrationTest {

    @Autowired UserService userService;

    @Test
    void shouldCreateUser() {
        userService.register("alice");
        // 方法结束后回滚，不污染数据库
    }
}
```

> [!WARNING]
> **`RANDOM_PORT` 下 `@Transactional` 不回滚**。请求由 Tomcat 的工作线程处理，而事务绑定在创建它的线程上——服务端方法自己开事务、自己提交了，测试线程上的回滚管不着它。默认 `MOCK` 环境下请求跑在测试线程里，能加入测试事务并回滚；一旦切到 `RANDOM_PORT`，必须显式清理数据。
>
> 另外，事务回滚只覆盖数据库：写出去的文件、发出的邮件、投递的消息都不会回滚；而**延迟到提交时才触发的约束冲突**也不会暴露。

## External Dependency: Testcontainers

真实依赖（数据库、Kafka、Redis）用 `spring-boot-testcontainers` + `@ServiceConnection`，容器由 Testcontainers 管理，连接信息自动注入（Repository 与查询映射的基础见 [JPA](/docs/CS/Framework/Spring/JPA.md)）：

```java
@Testcontainers
@DataJpaTest
class OrderRepositoryIT {

    @Container
    @ServiceConnection
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:18");
    // 无需手写 url/username/password：@ServiceConnection 把容器信息喂给自动配置
}
```

需要自定义属性时用 `@DynamicPropertySource`：

```java
@DynamicPropertySource
static void props(DynamicPropertyRegistry registry) {
    registry.add("spring.datasource.url", postgres::getJdbcUrl);
}
```

注意 `@DynamicPropertySource` 方法会参与上下文缓存 key 的计算——写在不同的测试类里会导致不同的上下文。

## Context Cache

TestContext 框架加载完 `ApplicationContext` 后会缓存复用，**缓存 key 由一组配置参数唯一确定**：

- `locations` / `classes` / `contextInitializerClasses` / `contextLoader`（来自 `@ContextConfiguration`）
- `contextCustomizers`（来自 `ContextCustomizerFactory`——包含 `@DynamicPropertySource` 方法，以及 `@MockitoBean` 这类 Bean 覆盖）
- `parent`（来自 `@ContextHierarchy`）
- `activeProfiles`（来自 `@ActiveProfiles`）
- `propertySourceLocations` / `propertySourceProperties`（来自 `@TestPropertySource`）
- `resourceBasePath`（来自 `@WebAppConfiguration`）

含义很直接：**每一种注解、导入、profile、mock 的不同组合，都是一个需要新建并常驻的上下文**。想控制测试套件的耗时，就把通用配置收敛到一个抽象父类：

```java
@AutoConfigureMockMvc
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
public abstract class AbstractIntegrationTest {

    @BeforeAll
    static void commonSetup() {
        // 例如统一注册 WireMock 桩
    }
}
```

上下文被污染时用 `@DirtiesContext` 标记，让它下一次重建——代价是重建成本，别滥用。

## JUnit 6 and @Nested

Boot 4 默认 JUnit 6，Spring 7 的 `SpringExtension` 要求 JUnit Jupiter 6.0+；JUnit 4 支持（`SpringRunner`、`SpringClassRule` 等）在 7.0 起弃用。

Spring 7 还改了 `@Nested` 层次结构里的扩展上下文作用域：**默认改为测试方法作用域**（`ExtensionContextScope.TEST_METHOD`），这样嵌套类里的字段和构造参数注入能一致地从当前测试方法的上下文取值。第三方 `TestExecutionListener` 不兼容新语义时，可以退回旧行为：

```java
@SpringExtensionConfig(useTestClassScopedExtensionContext = true)  // since 7.0
@SpringBootTest
class OrderTest { /* @Nested ... */ }
```

也可以全局设置 `spring.test.extension.context.scope=test_class`（7.0.7+ 支持，可用 `-D` 传入）；`@SpringExtensionConfig` 的优先级高于该属性。若测试类用了 `@TestInstance(Lifecycle.PER_CLASS)`，则始终是类作用域，配置不生效。

## Testing of Auto-Configuration Itself

写 starter 或自动配置时，用 `ApplicationContextRunner`（及其 Web / Reactive 变体）断言条件装配结果，并用 `ImportCandidates` 断言类确实被登记进了 `.imports` 清单——这两件事的坑与做法见 [Spring Boot 自动配置 SPI](/docs/CS/Framework/Spring/SPI.md)。

## Common Pitfalls

| 陷阱 | 现象 | 处理 |
|---|---|---|
| 只加 `@AutoConfigureMockMvc` 却没加 test starter | 注解无法解析 / 缺少类 | 补 `spring-boot-starter-webmvc-test` |
| `@SpringBootTest` 里 `@Autowired MockMvc` 为 null | Boot 4 不再自动配置 | 显式加 `@AutoConfigureMockMvc` |
| `@WebMvcTest` 里自定义 SecurityFilterChain 不生效 | 401 / 403 | `@Import(SecurityConfig.class)` |
| `@DataJpaTest` 跑在 H2 上"通过"但生产库失败 | 厂商 SQL 差异 | `@AutoConfigureTestDatabase(replace = NONE)` + Testcontainers |
| `RANDOM_PORT` 下事务不回滚 | 数据残留 | 显式清理，或改回 `MOCK` |
| 断言读到的对象是缓存里的 | 查询结果"不对" | 先 `flush()` 再 `clear()` |
| 测试套件越来越慢 | 上下文数量膨胀 | 收敛配置到抽象父类，减少 profile / mock 组合 |
| `@Nested` 里注入行为异常 | 字段为 null 或取到旧值 | 加 `@SpringExtensionConfig(useTestClassScopedExtensionContext = true)` |

## Links

- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Boot 启动流程](/docs/CS/Framework/Spring_Boot/Start.md)

## References

1. [Spring Boot Reference - Testing](https://docs.spring.io/spring-boot/reference/testing/index.html)
2. [Spring Boot Appendix - Test Slices](https://docs.spring.io/spring-boot/appendix/test-auto-configuration/slices.html)
3. [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
4. [Modularizing Spring Boot](https://spring.io/blog/2025/10/28/modularizing-spring-boot)
5. [Spring Framework Reference - Spring JUnit Jupiter Testing Annotations](https://docs.spring.io/spring-framework/reference/testing/annotations/integration-junit-jupiter.html)
