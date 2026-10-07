## Introduction

[AspectJ](https://eclipse.dev/aspectj/) 是 Java 最完整的**面向切面编程（AOP）**实现，也是 AOP 概念的发源地（Eclipse 基金会维护）。AOP 解决的是横切关注点（cross-cutting concerns）：日志、事务、权限、监控、重试这类散落在大量业务方法里的相同逻辑，传统写法会让它们与业务代码深度缠绕。AspectJ 把这些逻辑抽成独立的切面，在指定的"切点"处自动织入。

## Core Concept

| 概念 | 含义 |
|------|------|
| Aspect（切面） | 封装横切逻辑的模块（`@Aspect` 类） |
| Join Point（连接点） | 程序执行中可被切入的点：方法调用、方法执行、构造器、字段访问、异常处理 |
| Pointcut（切点） | 用表达式匹配一组连接点，如 `execution(* com.foo.service.*.*(..))` |
| Advice（通知） | 在切点处执行的动作及时机：`@Before/@After/@AfterReturning/@AfterThrowing/@Around` |
| Weaving（织入） | 把切面插入目标代码的过程 |
| Introduction（引介） | 给已有类动态增加接口/方法（inter-type declaration） |

`@Around` 最强大：拿到 `ProceedingJoinPoint`，可控制是否执行原方法、修改参数、捕获异常、包裹返回值，事务与重试都基于它实现：

```java
@Aspect
@Component
public class TimingAspect {
    @Around("@annotation(Timed)")
    public Object time(ProceedingJoinPoint pjp) throws Throwable {
        long start = System.nanoTime();
        try { return pjp.proceed(); }
        finally { log.info("{} cost {} ns", pjp.getSignature(), System.nanoTime() - start); }
    }
}
```

## Weaving Timing: Fundamental Difference Between AspectJ and Spring AOP

| 维度 | Spring AOP | AspectJ（完整） |
|------|-----------|-----------------|
| 织入方式 | **运行时**动态代理 | 编译期（CTW，ajc 编译器）或类加载期（LTW，javaagent） |
| 实现技术 | JDK 动态代理（接口）/ CGLIB（子类） | 字节码直接改写目标类 |
| 连接点 | 只支持 Spring Bean 的**方法执行** | 方法调用/执行、构造器、字段 get/set、static 初始化等全部 |
| 性能 | 代理调用链开销 | 织入后内联，运行期基本无额外开销 |
| 自调用 | 同类内部方法互调**不生效**（绕过代理） | 生效（字节码已改） |
| 使用成本 | 零额外配置，Spring Boot 自带 | 需 ajc 插件或 -javaagent 配置 |

正如 [Spring AOP](/docs/CS/Framework/Spring/AOP.md) 所述：Spring 借用了 AspectJ 的切点表达式语言和 `@AspectJ` 注解风格，但默认仍是运行时代理；需要拦截字段访问、构造器、final 类/方法（CGLIB 无法代理 final）或消除代理开销时，才启用真正的 AspectJ 织入。

## Pointcut Expression Quick Reference

- `execution(public * com.foo..*Service.*(..))`：匹配方法签名（最常用）；
- `within(com.foo.service..*)`：限定包/类型；
- `@annotation(rpc.Timed)`：带某注解的方法；`@within` / `@target`：类级注解；
- `bean(orderService)`：按 Spring bean 名（Spring AOP 扩展）；
- `args(.., java.lang.String)`：按参数类型匹配；
- 组合：`&&`（与）、`||`（或）、`!`（非）。

## Engineering Notes

- **同类自调用不生效**是 Spring AOP 第一大坑：`this.methodB()` 不走代理，`@Transactional` 静默失效。解法：拆类、注入自身代理（`AopContext.currentProxy()`）、或换 AspectJ 编译织入。
- 切面执行顺序用 `@Order` 控制（事务、日志、限流谁在外层直接影响异常与连接生命周期）。
- 切点表达式尽量收敛，过宽的 `execution(* ..*(..))` 会给大量 bean 创建代理，拖慢启动。
- LTW 在容器化环境要确认 javaagent 被正确挂载；CTW 要保证 Maven/Gradle 用 ajc 编译而非 javac。

## Links

- [Spring AOP](/docs/CS/Framework/Spring/AOP.md)
- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [代理模式](/docs/CS/DesignPatterns/ProxyPattern.md)
- [事务](/docs/CS/SE/Transaction.md)

## References

1. [The AspectJ Project](https://eclipse.dev/aspectj/)
2. [Spring Framework Reference - AOP](https://docs.spring.io/spring-framework/reference/core/aop.html)
