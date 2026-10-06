## Introduction

Spring 的校验能力分两层，先分清这两层是读懂全部校验代码的前提：

- **Spring 自有的 `Validator` 接口**（`org.springframework.validation.Validator`）：命令式校验 API，把失败项写进 `Errors` 对象，与数据绑定 `DataBinder` 深度耦合，不绑定具体校验技术。
- **Jakarta Validation（Bean Validation）**：声明式校验规范，用注解在模型上声明约束，参考实现是 Hibernate Validator。

日常开发绝大多数用第二种，而 Spring 把两者打通：`LocalValidatorFactoryBean` 同时实现 `jakarta.validation.Validator` 与 `org.springframework.validation.Validator`，用作后者时会把 `ConstraintViolation` 适配成 `FieldError` 再写入 `Errors`，因此上层无需感知用的是哪套 API。

### 版本基线

| 组件 | 当前基线 | 要点 |
| :-- | :-- | :-- |
| Spring Framework | 7.0 | Java 17 基线（推荐 21/25），Jakarta EE 11 |
| Jakarta Validation | 3.1 | 规范自 3.1 起由 "Jakarta Bean Validation" 更名为 "Jakarta Validation"，最低 Java 17 |
| Hibernate Validator | 9.x | 9.0 实现 Jakarta Validation 3.1；Boot 4.0 配 9.0、Boot 4.1 配 9.1 |
| Spring Boot | 4.0 | 依赖 `spring-boot-starter-validation` |

## 内置约束

| 约束 | 作用 |
| :-- | :-- |
| `@NotNull` / `@Null` | 非空 / 必须为空 |
| `@NotEmpty` | 非 null 且长度或集合大小 > 0 |
| `@NotBlank` | 字符串 trim 后非空（仅字符串） |
| `@Size(min, max)` | 字符串长度、集合/Map/数组大小 |
| `@Min` / `@Max` | 数值边界（含） |
| `@DecimalMin` / `@DecimalMax` | 支持 `inclusive=false` 的开区间 |
| `@Digits(integer, fraction)` | 整数位与小数位上限，金额字段常用 |
| `@Positive` / `@PositiveOrZero` / `@Negative` | 正负约束 |
| `@Email` / `@Pattern(regexp)` | 格式约束 |
| `@Past` / `@Future` / `@PastOrPresent` | 时间约束 |
| `@AssertTrue` / `@AssertFalse` | 布尔断言 |

```java
public record CreateOrderRequest(
        @NotNull @Positive Long userId,
        @NotBlank @Size(max = 64) String productName,
        @NotNull @Min(1) @Max(999) Integer quantity,
        @Digits(integer = 10, fraction = 2) BigDecimal amount) {
}
```

## 自定义约束

一个约束由两部分构成：`@Constraint` 注解声明元数据，`ConstraintValidator` 实现校验逻辑，再由 `@Constraint(validatedBy = ...)` 关联。

```java
@Target({ElementType.FIELD, ElementType.PARAMETER})
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = PhoneValidator.class)
public @interface Phone {

    String message() default "手机号格式不正确";

    Class<?>[] groups() default {};

    Class<? extends Payload>[] payload() default {};
}
```

```java
public class PhoneValidator implements ConstraintValidator<Phone, String> {

    @Autowired
    private RegionConfig regionConfig;   // 依赖注入可用

    @Override
    public boolean isValid(String value, ConstraintValidatorContext context) {
        if (value == null) {
            return true;                 // null 交给 @NotNull 管，避免职责重叠
        }
        return value.matches(regionConfig.phoneRegex());
    }
}
```

关键点：`isValid` 对 `null` 应直接返回 `true`，把空值判定留给 `@NotNull`；`LocalValidatorFactoryBean` 默认装配 `SpringConstraintValidatorFactory`，因此自定义校验器里的 `@Autowired` 生效。若需自定义错误信息，用 `context.disableDefaultConstraintViolation()` + `buildConstraintViolationWithTemplate(...)` 动态生成。

## 分组校验

约束默认属于 `Default` 组，`groups` 属性让同一模型在不同场景下按不同规则校验（如「新增必须填 id 为空、更新必须填 id」）。

```java
public interface OnCreate {}
public interface OnUpdate {}

public class UserForm {
    @Null(groups = OnCreate.class, message = "新增时不能指定 id")
    @NotNull(groups = OnUpdate.class, message = "更新时必须指定 id")
    private Long id;
}
```

方法级使用时直接传组：

```java
// Spring 的 @Validated 支持指定分组；@Valid 不支持分组
@PostMapping
public void create(@Validated(OnCreate.class) @RequestBody UserForm form) { }
```

`@GroupSequence` 可定义组的执行顺序（前一组全部通过才校验后一组），常用于「前置粗校验 → 后置重校验」的成本优化。

## 级联校验

字段是另一个对象时，需要在字段上标 `@Valid` 才会级联进去；否则嵌套对象的约束不会触发。

```java
public class OrderForm {

    @Valid                    // 不标则 Address 内部的约束完全不生效
    @NotNull
    private Address address;

    @Valid                    // 集合元素级联校验也必须标在字段上
    private List<OrderItem> items;
}
```

容器元素约束（Bean Validation 2.0+ 的 type-use 写法）可省掉多余包装类：

```java
private List<@NotBlank String> tags;
private Map<@NotBlank String, @Positive Integer> scores;
```

## Spring Validator 接口

不依赖注解时（如跨字段校验、依赖外部数据的校验）直接实现接口：

```java
public class OrderValidator implements Validator {

    @Override
    public boolean supports(Class<?> clazz) {
        return OrderForm.class.isAssignableFrom(clazz);
    }

    @Override
    public void validate(Object target, Errors errors) {
        ValidationUtils.rejectIfEmptyOrWhitespace(errors, "productName", "field.required");
        OrderForm form = (OrderForm) target;
        if (form.getStartTime().isAfter(form.getEndTime())) {
            errors.rejectValue("endTime", "range.invalid", "结束时间必须晚于开始时间");
        }
    }
}
```

`Errors`（及其子接口 `BindingResult`）是校验结果的载体，MVC 中把 `BindingResult` 紧跟在被校验参数之后即可拿到结果而不抛异常。Spring 6.1 起还提供便利方法：

```java
Validator validator = new OrderValidator();
validator.validateObject(form).failOnError(IllegalArgumentException::new);
```

多个校验器可同时挂到一个 `DataBinder` 上（`addValidators` / `replaceValidators`），实现「全局 Bean Validation + 局部自定义规则」的组合。

## 方法校验

在 Service 方法上校验入参与返回值，靠 AOP 代理实现：

```java
@Configuration
public class ValidatorConfig {

    @Bean
    public static MethodValidationPostProcessor validationPostProcessor() {
        MethodValidationPostProcessor processor = new MethodValidationPostProcessor();
        processor.setAdaptConstraintViolations(true);   // 见下
        return processor;
    }
}
```

```java
@Service
@Validated                                  // 类级注解，才能被 AOP 织入
public class UserService {

    public void addStudent(@Valid Person person, @Max(2) int degrees) { }
}
```

默认抛 `jakarta.validation.ConstraintViolationException`；开启 `setAdaptConstraintViolations(true)` 后改为抛 `MethodValidationException`，其中每个 `ParameterValidationResult` 按方法参数聚合错误，`@Valid` 级联参数对应 `ParameterErrors`（实现了 `Errors`），错误可被 `MessageSource` 国际化——这是与统一错误响应整合的推荐姿势。

> [!WARNING]
> 方法校验依赖 AOP 代理，因此：类内自调用（`this.xxx()`）不走代理、失效；`private` / `final` 方法无法拦截；同类中必须走代理对象调用。这与 [Spring AOP](/docs/CS/Framework/Spring/AOP.md) 的代理限制是同一条规则。

## 在 Spring MVC 中的集成

MVC 对 `@RequestMapping` 方法的内建校验分两个层级，两者的异常不同，应用应同时处理：

| 层级 | 写法 | 触发异常 | 说明 |
| :-- | :-- | :-- | :-- |
| 单参数对象校验 | `@Valid` / `@Validated` 标在 `@ModelAttribute`、`@RequestBody`、`@RequestPart` 上 | `MethodArgumentNotValidException` | 针对**一个命令对象** |
| 方法校验 | `@Min`、`@NotBlank` 等**约束注解**直接标在方法参数或返回值上 | `HandlerMethodValidationException` | 针对**一组方法参数** |

单参数对象校验要生效，需同时满足：是命令对象（非 `Map` / `Collection` 等容器）、参数后没有紧跟 `Errors` / `BindingResult`、且没有触发方法校验。

```java
@RestController
public class UserController {

    // 层级一：校验 RequestBody 对象
    @PostMapping("/users")
    public User create(@Valid @RequestBody UserForm form) { return service.create(form); }

    // 层级一 + 收错误不抛异常
    @PostMapping("/users/legacy")
    public String createLegacy(@Valid @ModelAttribute UserForm form, BindingResult result) {
        return result.hasErrors() ? "invalid" : "ok";
    }

    // 层级二：参数级约束（Spring 6.1+ 内建方法校验，无需 AOP）
    @GetMapping("/users")
    public List<User> list(@RequestParam @Min(0) int page,
                           @PathVariable @Pattern(regexp = "\\d+") String id) {
        return service.list(page);
    }
}
```

> [!WARNING]
> 控制器类上若标了 `@Validated`，方法校验会退化为 AOP 代理实现，此时 MVC 的**内建**方法校验（Spring 6.1 引入）不生效。要用内建能力就必须**去掉类级 `@Validated`**；仅当需要**分组校验**时才保留它并接受 AOP 方式。

校验器的配置入口有两处：全局（`WebMvcConfigurer#getValidator`）与局部（`@InitBinder` 方法，可标在 `@Controller` 或 `@ControllerAdvice` 上）。注意 `@Valid` 本身不是约束注解，它只表示「级联」；单独一个 `@Valid` 参数不会触发方法校验——必须同时存在真正的约束（如 `@NotNull`）才会。

校验失败如何转成 HTTP 响应，见 [统一异常处理与 Problem Details](/docs/CS/Framework/Spring/Exception.md)。

## 校验消息与国际化

1. 取注解 `message` 属性（默认值，写死在注解上）。
2. 覆盖：在 classpath 提供 `ValidationMessages.properties`（Hibernate Validator 约定的默认 bundle），可写 `ValidationMessages_zh_CN.properties` 做本地化。
3. Spring 集成下，`ConstraintViolation` 被适配为 `MessageSourceResolvable`，错误码按以下顺序推导，可用 [MessageSource](/docs/CS/Framework/Spring/IoC.md) 资源包任意一条覆盖。

以 `Person.name` 上的 `@Size(min = 1, max = 10)` 为例：

```
错误码：Size.person.name → Size.name → Size.java.lang.String → Size
消息参数："name"、10、1（字段名 + 约束属性）
默认消息：size must be between 1 and 10
```

```properties
Size.person.name=请提供一个长度在 {2} 到 {1} 之间的 {0}
person.name=用户名
```

消息参数中的字段名本身也是可解析的 `MessageSourceResolvable`，所以能把 `name` 翻译成「用户名」。方法参数级约束的错误码形如 `Max.myService#addStudent.degrees`。

## 常见坑

- `@Valid` 不加在任何字段上时，嵌套对象/集合元素完全不校验。
- `@Valid` 与 `@Validated` 的区别：前者是 Jakarta 注解、不支持分组；后者是 Spring 注解、支持分组，可用于类级触发 AOP 方法校验。
- 集合字段内的元素校验必须把 `@Valid` 标在**字段**上，标在 `List` 前面无效。
- record 的约束要标在**组件**上，Hibernate Validator 早已支持但规范到 3.1 才明确。
- Boot 下若消息文件缺失，`MessageSource` 可能根本没被自动配置，导致国际化静默失效。
- 校验只发生在进入方法时，`@Valid` 无法校验方法内部产生的数据。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [AOP](/docs/CS/Framework/Spring/AOP.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Validation, Data Binding, and Type Conversion](https://docs.spring.io/spring-framework/reference/core/validation.html)
2. [Jakarta Bean Validation](https://docs.spring.io/spring-framework/reference/core/validation/beanvalidation.html)
3. [Spring MVC Validation](https://docs.spring.io/spring-framework/reference/web/webmvc/mvc-controller/ann-validation.html)
4. [Hibernate Validator Documentation](https://hibernate.org/validator/documentation/)
5. [Jakarta Validation Specification](https://beanvalidation.org/)
