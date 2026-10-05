## Introduction

Web 应用的异常处理要回答两个问题：**控制器内抛出的异常怎么变成 HTTP 响应**，以及**容器级异常（404、415 等根本没进控制器）由谁兜底**。Spring MVC 的答案是前者交给 `@ExceptionHandler` 体系，后者交给 Servlet 容器的错误页与 Boot 的 `/error` 端点。

统一处理的价值不只是少写 try-catch，更在于：错误响应结构一致（便于前端与调用方处理）、不泄露堆栈与实现细节、日志与错误码集中可控。

## @ControllerAdvice / @ExceptionHandler

`@ExceptionHandler` 可以写在控制器内部（只作用于该控制器），也可以集中写在 `@ControllerAdvice` / `@RestControllerAdvice` 中（全局生效）。写法后者优先，因为跨控制器复用。

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiError> handleBusiness(BusinessException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(new ApiError(ex.getCode(), ex.getMessage()));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ApiError handleIllegalArgument(IllegalArgumentException ex) {
        return new ApiError("INVALID_ARGUMENT", ex.getMessage());
    }
}
```

约束与要点：

- **匹配就近优先**：控制器内部的 `@ExceptionHandler` 优先于全局 advice；同类候选按异常类型的具体程度选择。
- **advice 的生效范围可限定**：`@ControllerAdvice(basePackages = "com.foo.web")`、`assignableTypes`、`annotations`，避免全局兜底误伤基础设施。
- **多个 advice 的优先级**用 `@Order` / `@Priority` 控制。
- **方法参数**可注入 `HttpServletRequest`、`HttpServletResponse`、`Exception`、`HandlerMethod`、`WebRequest`、`Locale`；**返回值**可以是 `ResponseEntity`、`ProblemDetail`、被 `@ResponseStatus` 标注的对象等。
- `@ControllerAdvice` **只能拦截进入控制器的异常**，404（无处理器）、415、请求体解析失败前的一些容器级错误不会流到这里——这是下一个话题。

## 声明 HTTP 状态的三种方式

| 方式 | 写法 | 适用场景 |
| :-- | :-- | :-- |
| `@ResponseStatus` | 标在异常类或 handler 方法上 | 状态固定、不关心响应体 |
| `ResponseStatusException` | `throw new ResponseStatusException(HttpStatus.NOT_FOUND, "订单不存在")` | 临时抛出，无需自定义异常类 |
| `ErrorResponseException` | 自定义异常继承它 | 需要同时携带状态、响应头与结构化 body |

## ProblemDetail（RFC 9457）

Spring 6 起正式支持「Problem Details for HTTP APIs」规范——注意现行版本是 **RFC 9457**（取代早期的 RFC 7807），核心抽象如下：

| 抽象 | 职责 |
| :-- | :-- |
| `ProblemDetail` | 规范字段 + 自定义字段的容器（`type` / `title` / `status` / `detail` / `instance`） |
| `ErrorResponse` | 契约：暴露 HTTP 状态、响应头与 RFC 9457 格式的 body。Spring MVC 的内建异常**全部**实现它 |
| `ErrorResponseException` | `ErrorResponse` 的通用基础实现，可作自定义异常父类 |
| `ResponseEntityExceptionHandler` | `@ControllerAdvice` 的便利基类，统一处理所有 Spring MVC 异常并渲染错误响应体 |

```java
@ExceptionHandler(OrderNotFoundException.class)
public ProblemDetail handleOrderNotFound(OrderNotFoundException ex) {
    ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, ex.getMessage());
    problem.setTitle("订单不存在");
    problem.setType(URI.create("https://api.example.com/problems/order-not-found"));
    problem.setProperty("orderId", ex.getOrderId());   // 自定义字段
    return problem;
}
```

渲染规则：`status` 决定 HTTP 状态码，`instance` 未设置时自动填当前 URL 路径，Jackson 以 `application/problem+json` 作为可产出的媒体类型，以便内容协商时优先命中。

**扩展非标准字段有两种方式**：往 `properties` Map 里塞（Spring 注册的 `ProblemDetailJacksonMixin` 会把它展开为顶层 JSON 字段），或继承 `ProblemDetail` 增加专属属性（其拷贝构造便于把已有实例转成子类）。

**在 Boot 中开启默认行为**：

```properties
spring.mvc.problemdetails.enabled=true
```

该属性会自动配置一个 `ResponseEntityExceptionHandler`，把内建异常渲染成 Problem Details，其 `@Order` 为 0。若要**接管某个特定内建异常**，应另建一个 `@ControllerAdvice` 并保证排在它前面，而不是继承它再整体覆盖。

**错误响应可国际化**：`ErrorResponse` 暴露 `type` / `title` / `detail` 三类的消息码，由 [MessageSource](/docs/CS/Framework/Spring/IoC.md) 解析后可被覆盖，默认规则为：

```
type   → problemDetail.type.[异常类全限定名]
title  → problemDetail.title.[异常类全限定名]
detail → problemDetail.[异常类全限定名][后缀]
```

生产环境建议自定义这些消息，避免把框架内部实现细节暴露给调用方。

## 校验失败的处理

校验异常有三类，来源不同，都建议统一映射为 400 并回传字段级错误列表：

| 异常 | 触发时机 |
| :-- | :-- |
| `MethodArgumentNotValidException` | `@Valid` / `@Validated` 校验 `@RequestBody`、`@ModelAttribute` 等单个命令对象失败 |
| `BindException` | 数据绑定 + 校验失败（`@ModelAttribute` 且方法签名中未收集 `Errors`） |
| `HandlerMethodValidationException` | 方法级校验失败（约束直接标在方法参数/返回值上，Spring 6.1+ 内建） |
| `ConstraintViolationException` | 走 AOP 的 `@Validated` 方法校验（非 MVC 内建路径） |

```java
@ExceptionHandler(MethodArgumentNotValidException.class)
public ProblemDetail handleValidation(MethodArgumentNotValidException ex) {
    ProblemDetail problem = ProblemDetail.forStatus(HttpStatus.BAD_REQUEST);
    problem.setTitle("参数校验失败");
    problem.setProperty("errors", ex.getBindingResult().getFieldErrors().stream()
            .map(fe -> Map.of("field", fe.getField(), "message", fe.getDefaultMessage()))
            .toList());
    return problem;
}
```

`HandlerMethodValidationException` 提供 `visitResults(Visitor)` 回调，可按参数类型（`RequestParam` / `PathVariable` / `RequestHeader` / `ModelAttribute`）分别取错，比手写遍历更清晰。校验细节与消息码推导见 [校验](/docs/CS/Framework/Spring/Validation.md)。

## 兜底路径：没进控制器的异常

`@ControllerAdvice` 拦不到 404、容器级解析失败等异常。Servlet 容器会把它们转到错误页，Boot 则统一转发到 `server.error.path`（默认 `/error`）由 `BasicErrorController` 渲染，数据来自 `ErrorAttributes`（即默认的 `timestamp` / `status` / `error` / `path` 结构）。

```properties
server.error.path=/error
server.error.include-message=always     # 默认 never，按需放开
```

自定义该行为的方式是定义 `ErrorController` 实现或 `ErrorAttributes`，而不是早期的 `AbstractErrorController`（已废弃）。MVC 侧的调度细节见 [Spring MVC](/docs/CS/Framework/Spring/MVC.md)。

## 客户端侧解析错误响应

调用方可以用同一套模型反序列化错误体，不必自己拼 JSON：

```java
try {
    restClient.get().uri("/orders/{id}", id).retrieve().body(Order.class);
} catch (RestClientResponseException ex) {
    ProblemDetail problem = ex.getResponseBodyAs(ProblemDetail.class);
}
```

`WebClient` 侧对应 `WebClientResponseException`，用法一致。客户端选型见 [Spring REST 客户端](/docs/CS/Framework/Spring/RestClient.md)。

## 实践建议

- 自定义业务异常继承 `ErrorResponseException`，让它自带状态与结构，避免在 advice 里写大量 `if-else` 映射。
- 区分「可预期业务错误」（4xx，body 给用户看）与「未预期系统错误」（5xx，body 只给追踪 ID，细节进日志）。
- 生产环境关闭 `server.error.include-stacktrace`，ProblemDetail 的 `detail` 不要回传内部类名与 SQL 片段。
- 校验类 400 与业务类 400 用不同 `type` URI 区分，便于前端分流处理。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Error Responses (RFC 9457)](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-ann-rest-exceptions.html)
2. [Controller Advice](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-advice.html)
3. [RFC 9457 — Problem Details for HTTP APIs](https://datatracker.ietf.org/doc/html/rfc9457)
