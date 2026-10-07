## Introduction

Spring Framework 为调用 REST 端点提供四种客户端，定位互补：

| 客户端 | 编程模型 | 阻塞模型 | 当前定位 |
|---|---|---|---|
| `RestClient` | fluent API（`get().uri(...).retrieve()`），支持函数式请求定制 | 同步阻塞 | **7.x 新代码首选**（6.1 引入） |
| `RestTemplate` | template method（`getForObject` / `postForEntity` / `exchange`） | 同步阻塞 | 维护模式；**7.1 弃用、8.0 移除** |
| `WebClient` | 函数式、流式 API（`WebClient.create().get().retrieve()`） | 非阻塞，基于 Reactor，支持背压 | 响应式 / 高并发场景 |
| HTTP Interface | 声明式 Java 接口 + 注解，由动态代理实现 | 底层可接 `WebClient`（响应式）或 `RestClient`（同步） | Spring 6 引入，7.0 起支持分组注册 |

四者都构建在同一个 `HttpMessageConverter` 体系之上，请求都由 `ClientHttpRequestFactory` 发出（默认 JDK `HttpURLConnection`，可切换 Apache HttpComponents、OkHttp、Netty）。

> [!WARNING]
> Framework 7.0 起 Jackson 3 成为默认 JSON 实现，消息转换器随之改名：`MappingJackson2HttpMessageConverter` → `JacksonJsonHttpMessageConverter`，`MappingJackson2XmlHttpMessageConverter` → `JacksonXmlHttpMessageConverter`，基类 `AbstractJackson2HttpMessageConverter` → `AbstractJacksonHttpMessageConverter`。旧类名仍在 `spring-web` 中但已标注 `forRemoval`。

## RestTemplate

`RestTemplate` 在底层 HTTP 客户端之上提供高层 API，一行代码即可完成 REST 调用。

### Method Groups

| 方法组 | 语义 |
|---|---|
| `getForObject` / `getForEntity` | GET，分别返回反序列化后的对象 / 完整 `ResponseEntity`（status + headers + body） |
| `headForHeaders` | HEAD，只取响应头 |
| `postForLocation` / `postForObject` / `postForEntity` | POST，分别取 Location 头 / body 对象 / 完整 ResponseEntity |
| `put` / `delete` | PUT 创建或更新 / DELETE 删除 |
| `patchForObject` | PATCH（JDK HttpURLConnection 不支持 PATCH，需换 Apache HttpComponents 等） |
| `optionsForAllow` | OPTIONS，返回资源允许的 HTTP 方法（`Allow` 头） |
| `exchange` | 最通用的固定版本：接受 `RequestEntity`（method + url + headers + body），返回 `ResponseEntity`，可用 `ParameterizedTypeReference` 表达泛型返回类型 |
| `execute` | 最底层：通过回调完全控制请求准备与响应提取 |

### URI Template and Encoding

URI 模板变量支持可变参数或 `Map<String,String>`，且默认自动编码：

```java
// /hotels/42/bookings/21
restTemplate.getForObject(
        "https://example.com/hotels/{hotel}/bookings/{booking}",
        String.class, "42", "21");

// 自动编码：hotel list -> hotel%20list
restTemplate.getForObject("https://example.com/hotel list", String.class);
```

编码策略可通过 `uriTemplateHandler` 自定义；传已构造好的 `java.net.URI` 则不再二次编码。

### Initialization and Switching the Underlying HTTP Library

```java
// 默认走 java.net.HttpURLConnection
RestTemplate template = new RestTemplate();

// 切换到 Apache HttpComponents（支持连接池、PATCH、更完善的错误状态处理）
RestTemplate template = new RestTemplate(new HttpComponentsClientHttpRequestFactory());
```

> 注意：JDK 的 HTTP 实现在遇到 401 等错误状态码时可能直接抛异常；若要正常拿到错误响应做处理，切换到其他 HTTP 客户端库。

### Message Conversion

出入参对象由 `HttpMessageConverter` 与原始报文互转，按类路径检查默认注册全部内置转换器：

| Converter | 处理的媒体类型 / 说明 |
|---|---|
| `StringHttpMessageConverter` | `text/*`，读写 String |
| `FormHttpMessageConverter` | `application/x-www-form-urlencoded`，以及 multipart 写入 |
| `ByteArrayHttpMessageConverter` | 字节数组，默认 `application/octet-stream` |
| `JacksonJsonHttpMessageConverter` | `application/json`，基于 Jackson 3 的 `JsonMapper`（7.0 起；旧名 `MappingJackson2HttpMessageConverter`） |
| `JacksonXmlHttpMessageConverter` | `application/xml`，基于 Jackson XML（旧名 `MappingJackson2XmlHttpMessageConverter`） |
| `KotlinSerializationJsonHttpMessageConverter` | `application/json`，基于 kotlinx.serialization |
| `MarshallingHttpMessageConverter` | 基于 Spring OXM `Marshaller`/`Unmarshaller` 的 XML |
| `BufferedImageHttpMessageConverter` | `java.awt.image.BufferedImage` |

POST 时通常无需手动设置 `Content-Type`，转换器会根据源对象类型选择；GET 时 `Accept` 头同理。需要精确控制时用 `exchange` + `RequestEntity`。

### Multipart

请求体传 `MultiValueMap<String, Object>`，value 可以是普通字段（String）、文件（`Resource`）、JSON 实体（Object）或带头的 `HttpEntity`：

```java
MultiValueMap<String, Object> parts = new LinkedMultiValueMap<>();
parts.add("fieldPart", "fieldValue");
parts.add("filePart", new FileSystemResource("...logo.png"));
parts.add("jsonPart", new Person("Jason"));
template.postForObject("https://example.com/upload", parts, Void.class);
```

只要 map 中存在非 String 的 value，`FormHttpMessageConverter` 就把 Content-Type 设为 `multipart/form-data`；全是 String 则默认 `application/x-www-form-urlencoded`。

### Jackson JSON Views

可用 `MappingJacksonValue` 指定只序列化对象属性的一个子集：

```java
MappingJacksonValue value = new MappingJacksonValue(new User("eric", "secret"));
value.setSerializationView(User.WithoutPasswordView.class);
RequestEntity<?> request = RequestEntity.post(URI.create("https://example.com/user")).body(value);
template.exchange(request, String.class);
```

## RestClient

`RestClient` 是 Spring 6.1 引入的同步客户端，把 `RestTemplate` 的模板方法与 `WebClient` 的 fluent API 结合——既保留同步阻塞的直观性，又提供链式、可组合的调用写法。7.x 中它是同步调用的标准选择：

```java
RestClient client = RestClient.builder()
        .baseUrl("https://api.example.com")
        .defaultHeader("Accept", "application/json")
        .build();

Person person = client.get()
        .uri("/people/{id}", 42)
        .retrieve()
        .body(Person.class);
```

- `retrieve()` 按状态码自动处理错误（默认 4xx / 5xx 抛 `RestClientResponseException`），`exchange()` 则把请求与响应完全交给回调。
- 底层复用与 `RestTemplate` 相同的 `ClientHttpRequestFactory` 与消息转换器，可由 `RestClient.create(restTemplate)` 从既有 `RestTemplate` 平滑迁移。

> [!NOTE]
> 7.0 起 `RestClientResponseException.getRawStatusCode()` 已移除，改用 `getStatusCode()` 直接与 `HttpStatusCode` 比较。

## WebClient

`WebClient` 是 5.0 引入的非阻塞响应式客户端，是 `RestTemplate` 的继任者：

- 非阻塞 I/O，遵循 Reactive Streams 背压；
- 高并发下占用硬件资源少；
- Java 8 lambda 的函数式流式 API；
- 同步（`block()`）、异步、流式收发都支持。

```java
WebClient client = WebClient.builder().baseUrl("https://api.example.com").build();

Mono<Person> person = client.get()
        .uri("/people/{id}", 42)
        .retrieve()
        .bodyToMono(Person.class);
```

详见 [webflux](/docs/CS/Framework/Spring/webflux.md) 中对响应式客户端的说明。

## HTTP Interface

Spring 6 允许把 HTTP 服务定义成带注解方法的 Java 接口，再由框架生成执行 HTTP exchange 的动态代理——把"拼装请求 + 发起调用 + 解析响应"的样板代码全部隐藏。

第一步，声明接口：

```java
interface RepositoryService {

    @GetExchange("/repos/{owner}/{repo}")
    Repository getRepository(@PathVariable String owner, @PathVariable String repo);

    @PatchExchange(contentType = MediaType.APPLICATION_FORM_URLENCODED_VALUE)
    void updateRepository(@PathVariable String owner, @PathVariable String repo,
                          @RequestParam String name, @RequestParam String description);
}
```

类型级别可用 `@HttpExchange(url = "...", accept = "application/vnd.github.v3+json")` 声明公共属性，方法级别用 `@GetExchange` / `@PostExchange` / `@PutExchange` / `@DeleteExchange` / `@PatchExchange` 覆盖。

第二步，生成代理：

```java
WebClient client = WebClient.builder().baseUrl("https://api.github.com/").build();
HttpServiceProxyFactory factory = HttpServiceProxyFactory
        .builder(WebClientAdapter.forClient(client)).build();
RepositoryService service = factory.createClient(RepositoryService.class);
```

### Grouped Registration (7.0)

当 HTTP 接口多到几十上百个时，逐个手工构造 `HttpServiceProxyFactory` 会很啰嗦。7.0 引入 `@ImportHttpServices` 按"组"批量注册：框架自动创建代理并注册为 Bean，同一组共享一个客户端配置。

```java
@Configuration(proxyBeanMethods = false)
@ImportHttpServices(group = "weather", types = {FreeWeather.class, CommercialWeather.class})
static class HttpServicesConfiguration extends AbstractHttpServiceRegistrar {

    @Bean
    RestClientHttpServiceGroupConfigurer groupConfigurer() {
        return groups -> groups.filterByName("weather")
                .configureClient((group, builder) -> builder.defaultHeader("User-Agent", "My-Application"));
    }
}
```

`HttpServiceProxyRegistry` 在此之上提供按类型或组查询代理的统一入口。

### Supported Method Parameters

| 参数 | 作用 |
|---|---|
| `URI` / `HttpMethod` | 动态覆盖注解里的 url / method |
| `@RequestHeader` | 请求头，可为 `Map` / `MultiValueMap` / 单值，非 String 走类型转换 |
| `@PathVariable` | 展开 URL 占位符 |
| `@RequestBody` | 请求体对象，或 `Mono`/`Flux` 等响应式类型 |
| `@RequestParam` | 查询参数；当 content-type 为 form-urlencoded 时编码进请求体 |
| `@RequestPart` | multipart 片段：String / `Resource` / 实体 / `HttpEntity` |
| `@CookieValue` | Cookie |

### Supported Return Values

`void` / `Mono<Void>`（不取内容）、`HttpHeaders` / `Mono<HttpHeaders>`（只取头）、具体类型或 `Mono<T>`（解码 body）、`Flux<T>`（流式解码）、以及对应 `ResponseEntity<T>` 包装（带 status + headers）。

### Exception Handling

默认对 4xx / 5xx 抛 `WebClientResponseException`，可在底层 `WebClient` 上注册全局状态处理器：

```java
WebClient webClient = WebClient.builder()
        .defaultStatusHandler(HttpStatusCode::isError, resp -> { /* 自定义 */ })
        .build();
```

## Load Balancing

在 Spring Cloud 中，给 `RestTemplate` bean 或 `WebClient.Builder` bean 加 `@LoadBalanced` 限定符，即可把请求 URL 中的逻辑服务名解析为物理地址（详见 [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)）：

```java
@Bean
@LoadBalanced
RestTemplate restTemplate() {
    return new RestTemplate();
}

// http://stores 是虚拟主机名（服务名），由负载均衡器选择实例
restTemplate.getForObject("http://stores/stores", String.class);
```

## Links

- [Spring MVC](/docs/CS/Framework/Spring/MVC.md)
- [webflux](/docs/CS/Framework/Spring/webflux.md)
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)

## References

- [Spring Framework Reference - REST Clients](https://docs.spring.io/spring-framework/reference/integration/rest-clients.html)
- [HTTP Interface](https://docs.spring.io/spring-framework/reference/integration/rest-clients.html#rest-http-interface)
