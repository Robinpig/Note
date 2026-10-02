## Introduction

代理模式（Proxy Pattern）给某对象提供一个替身或占位符，由它控制对原对象的访问：客户端面向同一接口编程，但请求先经过代理。代理可以在不改目标类代码的前提下增加前置/后置逻辑——这正是 Spring AOP、RPC 客户端、缓存、权限控制的底层机制。

结构上有三种角色：**Subject**（抽象接口）、**RealSubject**（真实实现）、**Proxy**（持有 RealSubject 引用，实现同一接口）。

## 四种常见代理

| 类型 | 控制内容 | 例子 |
|------|---------|------|
| 远程代理（Remote） | 屏蔽网络细节，本地方法调用变网络请求 | Dubbo/Feign 引用、gRPC stub、[Retrofit](/docs/CS/Java/Retrofit.md) 动态代理 |
| 虚拟代理（Virtual） | 延迟创建开销大的对象 | 懒加载缩略图、Hibernate 懒加载实体 |
| 保护代理（Protection） | 访问前做鉴权/限流 | 服务端方法级权限 |
| 智能引用（Smart Reference） | 引用计数、日志、缓存、事务 | Spring AOP 通知链 |

注意与装饰器模式的区别：装饰器强调**增强**且通常由客户端组合传入；代理强调**控制访问**且代理自己决定真实对象的创建时机。

## 静态代理 vs 动态代理

- **静态代理**：为每个接口手写代理类，类数量爆炸、逻辑重复，工程上已很少用；
- **动态代理**：运行时生成代理类，一份增强逻辑适用于任意接口：
  - **JDK 动态代理**：`InvocationHandler`（写增强逻辑）+ `Proxy.newProxyInstance`（生成代理对象），**只能代理接口**；
  - **CGLIB**：`MethodInterceptor`（拦截逻辑）+ `Enhancer`（生成目标类的子类覆写方法），**不要求接口，但不能代理 final 类/方法**。

```java
// JDK 动态代理
Service proxy = (Service) Proxy.newProxyInstance(
        loader, new Class[]{Service.class},
        (obj, method, args) -> {
            before();
            Object r = method.invoke(real, args);   // 反射调用真实对象
            after();
            return r;
        });
```

## 在框架中的落地

Spring AOP 默认策略：目标类实现了接口用 JDK 代理，否则用 CGLIB（Boot 2.x 起默认统一 CGLIB）。调用链是"代理对象 → 拦截器链（advice/interceptor）→ 目标方法"。由此产生两个经典陷阱（见 [AspectJ](/docs/CS/Java/AspectJ.md)）：

1. **同类自调用失效**：`this.methodB()` 不经过代理，`@Transactional` 等注解在自调用时静默失效；
2. **final 方法无法被 CGLIB 增强**；构造器中调用可被覆盖的方法也会绕开代理语义。

JDK 代理生成的类名类似 `$Proxy0`，CGLIB 生成的是 `RealService$$EnhancerByCGLIB$$xxx`；动态代理也是 [Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)、MyBatis Mapper（接口无实现类）等"接口即客户端"技术的基础。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Strategy Pattern](/docs/CS/DesignPatterns/StrategyPattern.md)
- [AspectJ 与 Spring AOP](/docs/CS/Java/AspectJ.md)
- [Retrofit](/docs/CS/Java/Retrofit.md)
- [Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)

## References

1. [GoF - Design Patterns: Elements of Reusable Object-Oriented Software](https://en.wikipedia.org/wiki/Design_Patterns)
2. [JDK 动态代理文档（Proxy）](https://docs.oracle.com/javase/8/docs/api/java/lang/reflect/Proxy.html)
