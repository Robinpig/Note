## Introduction

> Convert the interface of a class into another interface clients expect. Adapter lets classes work together that couldn't otherwise because of incompatible interfaces.
> —— GoF

适配器模式把已有的东西包一层，让它的接口变成客户端期待的样子。它处理的不是"设计得不好"，而是**接口不兼容的既成事实**：老系统的 SDK、第三方库、上游定义的接口，你改不动，只能在边界上转接。

名字"Adapter"来自现实世界的电源转换头——220V 的插座与 110V 的电器之间加个转接器，两边都不用改。

## Two Forms

**对象适配器（组合，主流）**：适配器持有被适配者引用，实现目标接口，方法内委托过去。因为用组合，可以同时包多个被适配者。

```java
// 目标接口（客户端期待的）
interface UserPort { String idOf(String email); }

// 被适配者（第三方 SDK，接口改不动）
class LegacyUserClient { public Long fetchId(String mail) { ... } }

class UserAdapter implements UserPort {
    private final LegacyUserClient legacy;
    public String idOf(String email) {
        return String.valueOf(legacy.fetchId(email));  // 类型转接 + 委托
    }
}
```

**类适配器（继承）**：多继承语言里的写法，Java 因单继承 + 无多继承基本不用，仅见于"同时适配接口与基类"的老代码。

## Where It Lives in Real Systems

- **Spring MVC `HandlerAdapter`**：这是最值得研究的工业级适配器。`DispatcherServlet` 只认 `HandlerAdapter`，而 handler 有 `HttpRequestHandler`、`Controller`（注解方法）、`HandlerFunction`（函数式）等多种形态——每种形态一个适配器（`RequestMappingHandlerAdapter`、`HttpRequestHandlerAdapter`、`SimpleControllerHandlerAdapter`），dispatcher 用一套统一流程调度所有 handler。想支持新编程模型，加一个适配器即可，核心派发逻辑不动；
- **Retrofit**：把 HTTP API 的声明式接口转成 OkHttp 调用，动态代理 + 适配器的合体，见 [Retrofit](/docs/CS/Java/Retrofit.md)；[Feign](/docs/CS/Framework/Spring_Cloud/Feign.md) 同理；
- **`Arrays.asList(T... a)` / `Collections.list(Enumeration)`**：JDK 小工具即适配器，数组↔List、遗留枚举↔集合；
- **`InputStreamReader`**：字节流到字符流的经典适配（附带编码转换）；
- **MyBatis / JPA**：把 `ResultSet`（表格式、按列取）适配成领域对象（按属性取），ORM 框架整体就是一个巨大的结果集适配层。

## Adapter vs Facade vs Decorator

| | 适配器 | 门面 | 装饰器 |
|---|--------|------|--------|
| 接口 | **改变**成目标接口 | **简化**出新接口 | **保持**原接口 |
| 方向 | 适配一个既有类 | 简化一整个子系统 | 叠加增强 |
| 典型数量 | 一对一 | 一对多（内部协作多个类） | 可多层 |

一句话：接口不兼容要**转接**用适配器；子系统太复杂要**简化**用门面；接口已经合适只是要**加料**用装饰器。三者的代码结构有时相似，区分的唯一依据是**意图**——这也是"看结构猜模式"必然失败的原因。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Decorator](/docs/CS/DesignPatterns/Decorator.md)
- [Proxy](/docs/CS/DesignPatterns/ProxyPattern.md)
- [Retrofit](/docs/CS/Java/Retrofit.md)
- [Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)

## References

1. [Refactoring.Guru - Adapter](https://refactoring.guru/design-patterns/adapter)
2. [OODesign - Adapter Pattern](https://www.oodesign.com/adapter-pattern)
3. [JDK 8 Enumeration 文档（被 asList 前的时代遗产）](https://docs.oracle.com/javase/8/docs/api/java/util/Enumeration.html)
