## Introduction

> Define an interface for creating an object, but let subclasses decide which class to instantiate. Factory Method lets a class defer instantiation to subclasses.
> —— GoF

工厂方法模式把"创建哪个类"的决定从调用方手里拿走：调用方面向产品接口编程，具体实例化哪个实现由 Creator 的子类（或注册表、或容器）决定。它要消灭的是代码里散落的 `new ConcreteXxx()`——那让高层模块直接依赖低层实现，替换实现时要满世界改调用点。

注意 GoF 定义里的 "let subclasses decide" 是 1995 年的手段；今天更常见的形态是**注册表 + 函数式工厂**，以及 Spring 这样的容器接管创建权，模式的内核没变——**创建权与使用权分离**。

## Structure and Boundary

| | 工厂方法 | 抽象工厂 | 直接 new |
|---|---------|---------|---------|
| 产品 | 一个产品接口 | 一族相关产品 | 一个具体类 |
| 决策方 | Creator 子类 | 工厂接口实现 | 调用方自己 |
| 扩展方式 | 加一个子类 | 加一个工厂实现 | 改调用点 |
| 典型数量 | 一个 Creator 对应一个产品 | 一个工厂产出多个配套产品 | — |

判断标准：只有一类产品、产品未来会增加多种实现 → 工厂方法；产品之间必须配套成组（如 Windows 风格一套控件、MySQL/Oracle 各一套 DAO）→ 抽象工厂。两者可以共存：抽象工厂的每个创建方法本身就是工厂方法。

## Factory Method in the JDK

JDK 自己大量使用这个模式，`getInstance` 几乎就是它的签名：

- `Calendar.getInstance()` / `NumberFormat.getInstance()`：按 Locale 返回不同子类，调用方只见抽象类型；
- `KeyFactory.getInstance("RSA")`：按算法名查 Provider，JCA 的安全提供者体系是整个 Java 安全 API 的工厂骨干；
- `Charset.forName("UTF-8")`：名字到实现的两级映射（名字→charset 提供者）。

共同点：返回抽象类型，屏蔽"选哪个实现"和"怎么构造"。

## The Spring Form

Spring 把工厂方法从"继承"翻转成"注入"，这是同一模式的控制反转版本：

- **`FactoryBean<T>`**：容器发现某个 bean 实现了 `FactoryBean`，`getBean("x")` 返回的是 `getObject()` 的产物而不是工厂本身；要拿工厂自己得写 `&x`。MyBatis 的 `MapperFactoryBean`、Feign 的 `FeignClientFactoryBean` 都是这个套路——用工厂包装一个无法直接 new 的产物（动态代理接口）；
- **`BeanFactory` / `ApplicationContext`**：本质是超级工厂注册表，`getBean(Class)` 把"按名字找实现"标准化；
- **`ObjectProvider<T>`**：解决原型bean 注入、循环依赖延迟解析，比直接注入 `T` 更工厂化。

于是业务代码里不再有工厂类层级，只有接口 + `@Service` 实现，选择权在 [IoC 容器](/docs/CS/Framework/Spring/IoC.md)的启动期完成。

## Modern Shape: Registry Over Hierarchy

继承式工厂方法有个长期成本：每加一个产品就要多一个 Creator 子类，类数量翻倍。函数式之后常见写法是用一个 map 当注册表：

```java
Map<String, Supplier<Payment>> registry = Map.of(
    "wechat", WeChatPay::new,
    "alipay", AliPay::new);
Payment pay = registry.get(payType).get();   // 新增支付方式只需注册
```

这与 [Strategy](/docs/CS/DesignPatterns/StrategyPattern.md)的 `Map<String, Strategy>` 注入殊途同归——两者在这里重合：工厂负责"造出可互换的对象"，策略负责"用哪个对象"。若策略本身无状态，Spring 里直接注入 `Map<String, Strategy>` 更省一层工厂。

Java 9 的 `ServiceLoader` 则把注册表标准化为 SPI：接口方定义服务接口，实现方在 `META-INF/services` 登记，启动时按名字加载——JDBC 驱动、SLF4J 绑定都走这条路，Dubbo 的 SPI 机制也是它的增强版。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Singleton](/docs/CS/DesignPatterns/Singleton.md)
- [Builder](/docs/CS/DesignPatterns/Builder.md)
- [Strategy](/docs/CS/DesignPatterns/StrategyPattern.md)
- [IoC 容器](/docs/CS/Framework/Spring/IoC.md)

## References

1. [Refactoring.Guru - Factory Method](https://refactoring.guru/design-patterns/factory-method)
2. [OODesign - Factory Method Pattern](https://www.oodesign.com/factory-method-pattern)
3. [Spring Framework Javadoc - FactoryBean](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/beans/factory/FactoryBean.html)
4. [Java 9 ServiceLoader 文档](https://docs.oracle.com/javase/9/docs/api/java/util/ServiceLoader.html)
