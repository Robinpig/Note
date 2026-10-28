## Introduction

> Attach additional responsibilities to an object dynamically. Decorators provide a flexible alternative to subclassing for extending functionality.
> —— GoF

装饰器模式用组合代替继承来扩展行为：目标对象包一层装饰器，装饰器实现同一接口、持有一个被装饰者引用，在委托前后插入逻辑。多层装饰器可以叠加——`new BufferedInputStream(new FileInputStream(f))` 就是 JDK 里最经典的形态。

它和 [Proxy](/docs/CS/DesignPatterns/ProxyPattern.md)的代码结构几乎一样（都是"持有一个同类引用 + 实现同一接口"），差别在意图与所有权：**装饰器由客户端层层嵌套、强调增强且通常知道自己包的是什么；代理由自己决定何时创建真实对象、强调控制访问**。一个实用的判据：如果这层"壳"是调用方主动选择叠加的，是装饰器；如果它是框架替你插入、用来管生命周期或权限的，是代理。

## Decorators in the JDK IO

`java.io` 是装饰器模式的教科书应用，也教科书级地展示了它的代价：

```java
InputStream in = new BufferedInputStream(      // 装饰：加 8KB 缓冲
                  new GZIPInputStream(          // 装饰：加解压
                   new FileInputStream(f)));    // 被装饰：真实字节源
```

- `FileInputStream` 是被装饰者，负责真正的文件读取；
- `BufferedInputStream` 加缓冲，`GZIPInputStream` 加解压，`DataInputStream` 加类型化读取——每个装饰只关心一件事；
- 组合自由：要不要缓冲、要不要压缩，由客户端在构造时决定，类数量线性增长而非组合爆炸。

代价是**类型不可知**：装饰之后拿到的静态类型只有最外层，无法知道里面包了几层；以及 `close()` 的传染——每层装饰都要负责关闭被装饰者，JDK 7 起推荐 try-with-resources 规避。这也是 NIO.2 的 `Files.newInputStream()` 直接返回带选项流的原因：装饰链的拼装成本被 API 藏起来了。

## Framework Usage

- **Spring 事务**：`@Transactional` 方法实际执行的是"事务拦截器 → 目标方法"的链，事务切面就是包在 bean 外面的装饰器（由 CGLIB/JDK 代理实现，机制上更接近代理，语义上是装饰）；
- **Spring Cache**：`@Cacheable` 同理，查缓存 → 未命中调目标 → 回填，一层语义一个注解；
- **`HttpServletRequestWrapper`**：Servlet 规范提供的标准装饰器基类，改 header、包请求体（如 XSS 过滤、多方 body 复用）都继承它；
- **Netty `ChannelHandler`**：pipeline 里的 handler 层层叠加（出站/入站两个方向），编码、空闲检测、限流各占一层，见 [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)——这是装饰器思想在事件驱动框架里的彻底重构；
- **OkHttp Interceptor**：`addInterceptor(addHeader(...))` 逐层套，logging、重试、缓存各是一个装饰，与 [责任链](/docs/CS/DesignPatterns/ChainOfResponsibility.md)同构。

## Decorator vs Proxy vs Adapter

| | 装饰器 | 代理 | 适配器 |
|---|--------|------|--------|
| 接口 | 与**被装饰者相同** | 与**真实对象相同** | **不同**，转换成客户端的接口 |
| 谁组装 | 客户端层层嵌套 | 框架/创建方插入 | 客户端显式 new |
| 目的 | 叠加增强 | 控制访问（远程/懒加载/权限） | 接口不兼容的转接 |
| 数量 | 可多层 | 通常一层 | 一层 |

最不容易记混的一句话：装饰器和被装饰者是**同一类型**的兄弟，适配器两边**类型不同**。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Proxy](/docs/CS/DesignPatterns/ProxyPattern.md)
- [Adapter](/docs/CS/DesignPatterns/Adapter.md)
- [Chain of Responsibility](/docs/CS/DesignPatterns/ChainOfResponsibility.md)
- [AspectJ 与 Spring AOP](/docs/CS/Java/AspectJ.md)

## References

1. [Refactoring.Guru - Decorator](https://refactoring.guru/design-patterns/decorator)
2. [OODesign - Decorator Pattern](https://www.oodesign.com/decorator-pattern)
3. [JDK 8 BufferedInputStream 文档](https://docs.oracle.com/javase/8/docs/api/java/io/BufferedInputStream.html)
