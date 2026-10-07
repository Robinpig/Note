## Introduction

[OpenAPI](https://www.openapis.org/)（前身 Swagger）是一种机器可读的 **HTTP API 契约描述格式**。它声明 API 有哪些路径、每个操作接受什么参数与请求体、返回哪些响应码、数据结构长什么样、如何鉴权。

这里要分清两个常被混为一谈的概念：

| | 是什么 | 类比 |
| ---- | ---- | ---- |
| **OpenAPI** | 规范本身，产出是一份 JSON / YAML | 接口源代码 |
| **Swagger UI** | 把规范渲染成可交互页面的工具 | 文档站点 |
| **springdoc-openapi** | Spring 生态里自动生成规范的工具 | 从代码生成文档的编译器 |

换句话说：**Swagger UI 不是规范，它只是规范的一层可视化界面**。真正有价值的是那份 `/v3/api-docs` JSON——它驱动着 Swagger UI、Postman 导入、前端代码生成、契约测试、网关 Schema 校验等一切下游工具。

### Why It Is Worth Building

手写 API 文档必然腐化：接口改了文档没改，最终没人敢信。springdoc 的做法是在应用运行时扫描 `@RestController`、方法签名、JSR-380 校验注解和 swagger 注解，自动推导 API 语义——**文档与代码同源，改了代码文档就跟着变**。

这份契约对以下角色都直接有用：前端/移动端据此生成请求代码、QA 据此构造用例、网关据此做参数校验、外部合作方据此对接。

### Version Correspondence

springdoc-openapi 的主版本号与 Spring Boot 主版本**同步递增**，选错版本是最常见的问题：

| Spring Boot | springdoc-openapi |
| ---- | ---- |
| 4.x.x | **3.x.x** |
| 3.5.x | 2.8.x |
| 3.4.x | 2.7.x – 2.8.x |
| 3.3.x | 2.6.x |
| 3.0.x | 2.0.x – 2.1.x |

> [!WARNING]
> **Boot 4 必须用 springdoc 3.x**。用 2.8.x 对接 Boot 4 会因为 Boot 4 的模块化改造（`spring-boot-autoconfigure` 拆分、自动配置包名变更）而失效——这与 Flyway/Liquibase 的遭遇是同一类问题。

## Quick Start

```xml
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
    <version>3.0.3</version>
</dependency>
```

零配置即可用，启动后得到：

| 端点 | 内容 |
| ---- | ---- |
| `/v3/api-docs` | OpenAPI JSON 契约 |
| `/v3/api-docs.yaml` | 同上，YAML 格式 |
| `/swagger-ui.html` | 交互式文档页面 |

只要 swagger-ui 不需要 UI 不想引入 UI 依赖，换成 `springdoc-openapi-starter-webmvc-api` 即可；WebFlux 项目对应 `-webflux-ui` / `-webflux-api` 后缀。

默认输出 OpenAPI 3.0，想要 3.1（完全对齐 JSON Schema 2020-12，`nullable` 用类型数组表达）：

```yaml
springdoc:
  api-docs:
    version: openapi_3_1
  swagger-ui:
    path: /swagger-ui.html
```

## Describe API

代码注入足够生成一份能用的契约，但要让它"好用"需要补业务语义。

### Global Metadata

```java
@Configuration
@OpenAPIDefinition(
    info = @Info(title = "订单 API", version = "1.0.0", description = "对外提供订单的创建与查询"),
    security = @SecurityRequirement(name = "bearerAuth"))
@SecurityScheme(
    name = "bearerAuth", type = SecuritySchemeType.HTTP, scheme = "bearer", bearerFormat = "JWT")
class OpenApiConfig {
}
```

### Operational Level

```java
@Tag(name = "Orders", description = "订单相关操作")
@RestController
@RequestMapping("/api/orders")
class OrderController {

    @Operation(summary = "创建订单", description = "为已存在的客户创建新订单")
    @ApiResponses({
        @ApiResponse(responseCode = "201", description = "订单创建成功"),
        @ApiResponse(responseCode = "400", description = "请求参数不合法"),
        @ApiResponse(responseCode = "404", description = "客户不存在")
    })
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    OrderResponse createOrder(@Valid @RequestBody CreateOrderRequest request) {
        return orderService.create(request);
    }
}
```

### Data Structure

```java
record CreateOrderRequest(
    @Schema(description = "客户标识", example = "CUST-42") @NotBlank String customerId,
    @Schema(description = "订购数量", example = "3", minimum = "1") @Min(1) int quantity) {
}
```

> [!TIP]
> springdoc 会自动读取 Jakarta Validation 的约束注解来标注字段的必填性与取值范围，因此通常**不必**为了文档再手写一遍 `required` / `minimum`。校验注解本身见 [Validation](/docs/CS/Framework/Spring/Validation.md)。

失败响应的文档尤其值得写：API 不只是返回 200，前端最关心的往往恰恰是 4xx 该怎么处理。ErrorCode 的统一结构建议与 [统一异常处理](/docs/CS/Framework/Spring/Exception.md) 中的 `ProblemDetail` 保持一致——springdoc 也会读取 `@ControllerAdvice` 里声明的异常映射，把通用错误响应自动补进契约。

## Grouping

对外 API 与内部 API、公开接口与管理员接口混在一页文档里很难用。`GroupedOpenApi` 可以按路径或包拆分：

```java
@Configuration
class OpenApiGroupsConfig {

    @Bean
    GroupedOpenApi publicApi() {
        return GroupedOpenApi.builder()
            .group("public")
            .pathsToMatch("/api/public/**")
            .build();
    }

    @Bean
    GroupedOpenApi adminApi() {
        return GroupedOpenApi.builder()
            .group("admin")
            .pathsToMatch("/api/admin/**")
            .build();
    }
}
```

分组后每组有独立的 `/v3/api-docs/{group}`，Swagger UI 右上角可切换。

## Interaction with Other Spring Capabilities

| 功能 | 表现 |
| ---- | ---- |
| [Spring Security](/docs/CS/Framework/Spring/Security.md) | 配了 `@SecurityScheme` 后 Swagger UI 可挂全局 token；注意 basic auth 下要放行文档端点 |
| Spring Data `Pageable` | 自动展开为 `page` / `size` / `sort` 查询参数 |
| `@JsonView` | 同一个 DTO 在不同接口上呈现不同字段，契约会跟随视图定义 |
| Spring HATEOAS | `_links` 结构会被渲染（需注意避免与 `allOf` 组合时的重复） |
| Actuator | 可选把 actuator 端点也纳入文档 |
| **MCP** | springdoc 3.x 支持把 REST API **同时暴露为 MCP 工具**，让 AI Agent 直接调用 |

最后一项是值得留意的新方向：既然 OpenAPI 已经完整描述了 API 的入参出参，它天然就是一份高质量的 tool definition。springdoc 3.0.3 起支持把 API 同时注册成 MCP 工具（含"安全/会修改数据"的分类标注与人工确认环节），相关背景见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)。

## Production Environment

> [!WARNING]
> `/swagger-ui.html` 与 `/v3/api-docs` 会把**所有接口路径、参数结构、甚至内部字段名**暴露出去。这是对攻击者的免费地图。生产环境应当二选一：
>
> - 直接关闭：`springdoc.api-docs.enabled=false`、`springdoc.swagger-ui.enabled=false`；
> - 或者用 Spring Security 保护文档端点（要求登录或限定内网 IP）。
>
> 常见折中是：非生产环境全开，生产环境只允许内网/VPN 访问，或用网关做路径级鉴权。

另外，文档生成需要在运行时扫描反射元数据，若追求极致启动性能或用 GraalVM native image，需确认 springdoc 的 reachability metadata 版本与 GraalVM 版本兼容（历史上出现过 GraalVM 25 不兼容的问题，已在 3.0.2 修复）。

## Boot 4 / Framework 7 Notes

- **必须用 springdoc 3.x**（见版本对应表），且 webmvc 项目的 springdoc starter 名称不变，仍为 `springdoc-openapi-starter-webmvc-ui`——Boot 侧改的是自己的 starter（`spring-boot-starter-web` → `spring-boot-starter-webmvc`），二者互不影响，别混淆。
- **Jackson 3 影响**：Framework 7 默认 Jackson 3，日期默认输出 ISO-8601 字符串、属性排序策略变化。`example` 里的日期样例建议显式写字符串，避免文档与实际行为对不上。
- 若自定义了 `HttpMessageConverter` 而没有注册 `ByteArrayHttpMessageConverter`，`/v3/api-docs` 会无法正确输出——排查文档打不开时先看这里。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Web MVC](/docs/CS/Framework/Spring/MVC.md)
- [统一异常处理](/docs/CS/Framework/Spring/Exception.md)
- [Validation](/docs/CS/Framework/Spring/Validation.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [springdoc-openapi 官网](https://springdoc.org/)
2. [springdoc-openapi GitHub](https://github.com/springdoc/springdoc-openapi)
3. [OpenAPI Specification 3.1](https://spec.openapis.org/oas/v3.1.0)
4. [Swagger Annotations javadoc](https://javadoc.io/doc/io.swagger.core.v3/swagger-annotations-jakarta)
