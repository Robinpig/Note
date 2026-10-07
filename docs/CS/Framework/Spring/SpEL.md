## Introduction

SpEL（Spring Expression Language）是 Spring Framework 中的表达式语言，位于独立的 `spring-expression` 模块（核心 API 包 `org.springframework.expression`）。它**不依赖 Spring 容器，可单独使用**，在框架内的价值在于：让配置与注解具备运行时计算能力——`@Value("#{...}")`、`@Cacheable(key = "#user.id")`、`@PreAuthorize("hasRole('ADMIN')")` 全都由它求值。

它属于「运算层」而非「配置层」，这一点与属性占位符极易混淆，是第一个要分清的点。

### `#{ }` and `${ }` Are Two Separate Mechanisms

| 维度 | `#{ ... }` | `${ ... }` |
| :-- | :-- | :-- |
| 机制 | SpEL 表达式求值 | 属性占位符替换 |
| 处理者 | `SpelExpressionParser` + `EvaluationContext` | `PropertySourcesPlaceholderConfigurer` / `PropertyResolver` |
| 能力 | 运算、方法调用、类型引用、Bean 引用 | 只能按键取值 |
| 生效时机 | Bean 创建 / 运行时求值 | 更早，Bean 定义阶段替换文本 |

两者可以嵌套：`#{'${app.name}'}` 表示「先把 `${app.name}` 替换成字符串，再作为 SpEL 字面量」；反过来 `${#{...}}` 不成立，因为占位符解析发生得更早、看不到 SpEL 的结果。

## Core API

```java
ExpressionParser parser = new SpelExpressionParser();

Expression exp = parser.parseExpression("'Hello'.concat(' SpEL')");
String value = exp.getValue(String.class);          // Hello SpEL

// 带上下文：注册变量、Bean 解析器、方法解析器
StandardEvaluationContext context = new StandardEvaluationContext();
context.setVariable("user", new User(1L, "vito"));

Expression len = parser.parseExpression("#user.name.length()");
Integer nameLength = len.getValue(context, Integer.class);
```

- `ExpressionParser` / `SpelExpressionParser`：解析入口，线程安全且内部缓存已解析表达式。
- `Expression`：解析结果，提供 `getValue` / `getValueType` / `setValue` / `getValue(context, Class)`。
- `EvaluationContext`：求值环境，决定能不能用类型引用、Bean 引用、自定义变量与方法。
  - `StandardEvaluationContext`：功能全，允许 `T()` 类型引用与 `@bean` 引用。
  - `SimpleEvaluationContext`：**受限**，按需开启属性访问/方法调用，**不允许类型引用与 Bean 引用**——处理不可信输入时必须用它。

## Expression Syntax

| 类别 | 示例 |
| :-- | :-- |
| 字面量与运算 | `'text'`、`100`、`true`、`1 + 2 * 3`、`'a' == 'b'`、`&&`、`!` |
| 属性与方法 | `user.name`、`user.getName()`、`list[0]`、`map['key']` |
| 三元与 Elvis | `age > 18 ? 'adult' : 'minor'`、`name ?: '匿名'`（空则取默认） |
| 安全导航 | `user?.address?.city`（任一层为 null 即返回 null，不抛异常） |
| 类型引用 | `T(java.lang.Math).PI`、`T(java.time.LocalDate).now()` |
| Bean 引用 | `@orderService.count()`（按 Bean 名取容器内对象） |
| 构造对象 | `new java.util.Date()` |
| 集合操作 | `list.?[age > 18]`（选择）、`list.![name]`（投影）、`list.size()` |
| 正则匹配 | `email matches '[a-z]+@[a-z]+\\.com'` |
| 变量与根对象 | `#user`、`#root`、`#this` |

选择（`?[]`）与投影（`![]`）是 SpEL 对集合的声明式处理，等价于流式过滤与映射：

```java
parser.parseExpression("users.?[age > 18].![name]")
      .getValue(context, List.class);      // 取出成年用户的名字
```

模板解析用于「文本中嵌表达式」的场景，需显式指定 `TemplateParserContext`（默认只有纯表达式才认 `#{}`）：

```java
String template = "随机号码：#{T(java.util.UUID).randomUUID()}";
parser.parseExpression(template, new TemplateParserContext())
      .getValue(String.class);
```

## Action Points Across Spring

| 位置 | 典型写法 | 可见变量 |
| :-- | :-- | :-- |
| `@Value` | `@Value("#{systemProperties['user.timezone']}")` | `#root` 为 `Environment` 相关上下文 |
| 缓存 [Cache](/docs/CS/Framework/Spring/Cache.md) | `@Cacheable(key = "#user.id")`、`unless = "#result == null"` | `#result`（仅 `unless`）、`#p0`/`#a0`（按位置取参） |
| 缓存条件 | `@Cacheable(condition = "#id > 0")` | 方法参数名（需 `-parameters` 编译） |
| [Spring Security](/docs/CS/Framework/Spring/Security.md) | `@PreAuthorize("hasRole('ADMIN') or #userId == authentication.name")` | `authentication`、`principal`、方法参数 |
| 事件监听 | `@EventListener(condition = "#event.type == 'PAY'")` | 事件对象属性 |
| 条件装配 | `@ConditionalOnExpression("#{...}")` | 配置属性 |
| Spring Data JPA | `@Query("select u from #{#entityName} u")` | `#entityName` |

方法参数引用有约定：`#p0` / `#a0` 是位置索引（无需参数名），`#参数名` 需要编译时保留参数名（`javac -parameters`，Boot 的 Maven/Gradle 插件默认开启）。AOP 织入的表达式还能用 `#args` 取参数数组，见 [AOP](/docs/CS/Framework/Spring/AOP.md)。

## Performance and Security

**安全是首要问题**。`StandardEvaluationContext` 允许 `T(...)` 调用任意静态方法与构造任意对象，若表达式字符串来自用户输入（如自定义规则、报表公式、低代码平台），等于把反射与类加载能力交出去。处理不可信输入的正确做法：

```java
EvaluationContext safe = SimpleEvaluationContext
        .forReadOnlyDataBinding()        // 只读属性绑定，不允许方法调用与类型引用
        .build();

// 或按需开启
SimpleEvaluationContext.forPropertyAccessors(new DataBindingPropertyAccessor())
        .withMethodResolvers(...)
        .build();
```

性能方面：解析（parse）比求值（evaluate）贵得多，`SpelExpressionParser` 内部缓存已解析的 `Expression`，重复求值不会反复解析；求值默认走解释器，可开启编译模式（`SpelCompilerMode`）把热点表达式编译成字节码以降低长期开销。在 [AOT](/docs/CS/Framework/Spring/AOT.md) / native image 场景下，表达式涉及的反射需要在构建期可知，动态拼接的表达式尤其要注意。

## Compile Mode and Parsing Configuration

### SpelCompilerMode

默认 `SpelExpression` 走**解释执行**。对热点表达式（如被高频调用的 `@Cacheable` key 计算、循环内求值），可开启编译模式，把表达式编译成字节码以降低长期开销：

```java
SpelParserConfiguration config = new SpelParserConfiguration(
        SpelCompilerMode.MIXED,            // IMMEDIATE / MIXED / OFF
        this.getClass().getClassLoader());
ExpressionParser parser = new SpelExpressionParser(config);
```

- `OFF`：始终解释。
- `IMMEDIATE`：首次求值即编译，编译失败直接抛异常。
- `MIXED`（推荐）：先解释，当同一表达式被求值超过阈值（默认 100 次）后自动切换为编译态；编译失败回落到解释态，不会中断业务。

编译态要求表达式的返回类型在多次求值间稳定，且不支持解释态下的全部动态特性。

### Parsing Configuration Switch

`SpelParserConfiguration` 还能全局开启：

- **null 安全**：让 `null.foo` 不再抛 `NullPointerException` 而是返回 `null`（等价于 `?.` 但作用于整条表达式）。
- **集合/数组字面量**：允许 `{1,2,3}`、`new int[]{1,2,3}`。
- **自动数组增长**：对数组下标越界赋值时自动扩容。

### EvaluationContext Internal Resolution Chain

`StandardEvaluationContext` 在求值时依赖一组可替换的解析器，理解它们有助于排查"为什么取不到 / 调不了"：

- `TypeLocator`：`T()` 类型引用的解析器，默认 `StandardTypeLocator` 已自动导入 `java.lang.*`，引用其它包须写全限定名。
- `TypeConverter`：类型转换（包装 `ConversionService`），决定 `'123'` 能否赋给 `Integer` 参数。
- `BeanResolver`：`@beanName` 引用的解析器，默认**未注册**——要在 SpEL 里引用容器内 Bean，必须自己 `setBeanResolver`。
- `OperatorOverloader`：自定义运算符重载（默认无）。
- `PropertyAccessor` / `MethodResolver`：属性与方法的分派。

### Performance Trap: Reuse Instead of Repeated Creation

- `ExpressionParser` 线程安全且内部缓存已解析的 `Expression`，**应全局单例复用**，不要每次求值都 `new`。
- `StandardEvaluationContext` 构建较重（收集类型信息、方法缓存），**不要在热路径里反复 new**，把它作为常量或缓存起来；`SimpleEvaluationContext` 更轻，处理不可信输入优先用它。
- 动态拼接的表达式（如 `parser.parseExpression("list.?[name=='" + userInput + "']")`）无法在 [AOT](/docs/CS/Framework/Spring/AOT.md) / native image 构建期确定反射元数据，运行在 native 镜像里会因缺失 hint 而失败——这类场景要么提前声明反射 hint，要么改用静态表达式 + 参数绑定（`#userInput` 变量）。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [AOP](/docs/CS/Framework/Spring/AOP.md)
- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md)
- [AOT](/docs/CS/Framework/Spring/AOT.md)

## References

1. [Spring Expression Language (SpEL)](https://docs.spring.io/spring-framework/reference/core/expressions.html)
2. [SpEL API — org.springframework.expression](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/expression/package-summary.html)
3. [SpEL 常见操作符与用法](https://docs.spring.io/spring-framework/reference/core/expressions/expressions.html)
