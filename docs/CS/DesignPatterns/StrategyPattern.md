## Introduction

> Define a family of algorithms, encapsulate each one, and make them interchangeable. Strategy lets the algorithm vary independently from clients that use it.
> —— GoF

策略模式定义一族算法，把每个算法封装进独立的策略类、实现同一接口，使算法可以在运行时互相替换，而使用算法的客户端无需改变。它解决的是"**同一行为有多种实现、靠 if-else/switch 选择**"的坏味道：当分支随业务不断增加，调用方会被各种算法细节污染，开闭原则被破坏。

三种角色：**Strategy**（统一算法接口）、**ConcreteStrategy**（各具体实现）、**Context**（持有一个 Strategy 引用，委托它执行）。

## Typical Scenarios

支付方式选择（微信/支付宝/银行卡各一策略）、折扣计算（满减/折扣券/无门槛）、路由/负载均衡策略（轮询/加权/一致性哈希）、排序比较器（`Comparator` 就是最经典的 JDK 策略接口）、认证方式切换。

```java
interface PayStrategy { PayResult pay(Order o); }

class WeChatPay implements PayStrategy { ... }
class AliPay    implements PayStrategy { ... }

class OrderService {
    private PayStrategy strategy;                 // 注入策略
    public void pay(Order o) { strategy.pay(o); } // 客户端零分支
}
// 运行时选择：从 Map<String, PayStrategy> 按 payType 取，避免 if-else 链
```

Spring 中的惯用法：把所有实现注入 `Map<String, Strategy>`（key 为 bean 名）或 `List<Strategy>`，用类型/注解路由到具体实现，新增支付方式只要加一个 `@Component`，调用方代码不变。

## Why Not Use if-else Directly

| 维度 | if-else 堆叠 | 策略模式 |
|------|-------------|---------|
| 新增算法 | 改调用方，违反开闭原则 | 新增一个类即可 |
| 可测试性 | 分支耦合，难独立测试 | 每个策略可单测 |
| 复杂度 | 算法一多方法膨胀 | 分散到小类 |
| 代价 | 简单 | 策略类数量增加，客户端需要知道差异以便选择 |

判断标准：算法**确定且永不变**时 if-else 更直接；算法族会持续增加、或同一调用要在运行时按配置/用户选择切换，就值得抽策略。为两个分支引入一堆策略类同样是过度设计。

## Boundary with Similar Patterns

- **状态模式**：结构几乎一样，但状态会在对象生命周期中**自动迁移**（状态自己决定下一个状态）；策略由外部一次性选择、策略之间互不感知；
- **模板方法**：在父类固定流程骨架、子类只改其中某些步骤（继承）；策略是整个算法整体替换（组合）；
- **函数式简化**：策略接口只有一个方法时，Java 8+ 可直接用 lambda/方法引用代替一整个类（`Comparator.comparing(...)`），简单策略无需建类层级。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Proxy Pattern](/docs/CS/DesignPatterns/ProxyPattern.md)
- [架构与设计原则](/docs/CS/SE/Architecture.md)

## References

1. [GoF - Design Patterns](https://en.wikipedia.org/wiki/Design_Patterns)
2. [Refactoring.Guru - Strategy](https://refactoring.guru/design-patterns/strategy)
