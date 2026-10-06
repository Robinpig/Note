## Introduction

单体（monolith）这个词常年带着贬义，但真正让大型系统难以维护的从来不是"部署在一起"，而是**边界的丧失**：

- 任何类都能 import 任何类，几个月后依赖图变成一张网；
- 一个模块的改动会波及看起来毫不相干的模块；
- 想拆出微服务时，发现根本拆不动——连边界在哪都不知道；
- 甚至同一次提交里，两个团队改了同一批类，冲突不断。

[Spring Modulith](https://spring.io/projects/spring-modulith) 的思路是：**既不急着拆服务，也不要无边界**。用 Spring Boot 的包结构表达模块边界，然后由工具来验证、可视化并部分强制这些边界，让单体保持"可拆而尚未拆"的状态。需要时抽出去做微服务，边界是现成的。

它不是一个运行时容器，也不是要替换 Spring——本质是**一组约定 + 与之配套的校验、事件与文档工具**。

### 版本基线

Spring Modulith **2.0**（2025-11-21 GA）把基线升到 Spring Boot 4 / Framework 7，同时迁移到 JSpecify 空安全。最大的改动是重做了 Event Publication Registry 的状态模型（下文详述），并移除了旧的 `@ApplicationEventListener` 注解。

## 应用模块

Modulith 的模块划分**不用新配置文件**，而是直接读包结构：约定 Spring Boot 主应用类所在包的**每个直接子包**就是一个应用模块。

```text
com.example.order
├── OrderApplication.java          ← 主应用类，定义了根包
├── inventory/                     ← 模块 inventory
│   ├── InventoryService.java
│   └── package-info.java
├── payment/                       ← 模块 payment
│   └── PaymentService.java
└── shared/                        ← 模块 shared
    └── Money.java
```

这样组织下来的好处是：**模块边界在代码里肉眼可见**。新增一个类时，放哪个目录就决定了它属于哪个模块、谁能用它。

## 可见性规则

这是 Modulith 最有型的一点：**`public` 不等于"别人可以用"**。

在 Java 里，只要类和方法标了 `public`，任何地方都能调用——因为 JVM 的可见性单位是包，而一个模块内部往往需要跨包的 `public`。Modulith 在此之上加了一层：

- 模块**根包以外**的类型默认**不可被其它模块访问**（因为那是实现细节）；
- 只有被显式声明为 **named interface** 的包才对外暴露；
- 模块内跨包可以自由使用 `public`。

命名接口在 `package-info.java` 里声明：

```java
@org.springframework.modulith.NamedInterface("api")
package com.example.order.inventory.api;
```

于是 `inventory` 模块的 `api` 子包成为它对外的一部分契约，其它模块可以依赖；而 `inventory.internal`、`inventory.repository` 这些包则完全隐蔽。没有声明命名接口时，模块对外甚至连自己的根包都不暴露。

> [!NOTE]
> 2.0 起，"命名接口的归属"会沿着方法传播：某个类型的签名（返回类型、参数类型）如果位于命名接口包内，方法本身也被视为该命名接口的一部分。这减少了到处标注解的噪音。

模块的描述信息可以直接写在 `package-info.java` 的 Javadoc 里，2.0 会抽取它作为该模块的说明，用于生成文档。

## 验证

约定不验证就只是君子协定。Modulith 提供两种校验时机：

```java
// 1. 测试里校验：最喜欢的方式，放在 CI 里跑
class ModularityTests {

    ApplicationModules modules = ApplicationModules.of(OrderApplication.class);

    @Test
    void verifiesStructure() {
        modules.verify();     // 违反可见性规则时测试失败
    }
}
```

```java
// 2. 启动时校验（2.0 起支持）
@Modulithic
class OrderApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderApplication.class, args);
    }
}
```

`ApplicationModules.of(...)` 会扫描包结构建立模块模型，`verify()` 逐条检查：模块间是否有循环依赖、是否访问了非命名接口的类型、是否有不该有的耦合。一旦有人跨
边界 import，CI 立刻红。这是这套方案真正能落地的原因——**违规在开发阶段就被拦住，而不是等到系统僵化之后**。

## 事件：模块解耦的主要手段

模块之间最健康的协作方式是**发事件而非直接调用**。Modulith 提供了专门的监听注解：

```java
@Service
class OrderService {

    private final ApplicationEventPublisher events;

    OrderService(ApplicationEventPublisher events) {
        this.events = events;
    }

    @Transactional
    void placeOrder(Cart cart) {
        Order order = cart.toOrder();
        orderRepository.save(order);
        events.publishEvent(new OrderPlaced(order.id(), cart.items()));
    }
}

@Component
class InventoryListener {

    @ApplicationModuleListener
    void on(OrderPlaced event) {
        inventoryService.reserve(event.items());
    }
}
```

`@ApplicationModuleListener` 是一个组合注解，等价于三件事：

| 组成 | 作用 |
| ---- | ---- |
| `@TransactionalEventListener` | 事务提交后才投递，避免读到未提交数据 |
| `@Transactional(propagation = REQUIRES_NEW)` | 监听在新的事务里跑，与主事务解耦 |
| `@Async` | 异步执行 |

> [!WARNING]
> 2.0 **移除了**已弃用的 `@ApplicationEventListener`，统一到 `@ApplicationModuleListener`。熟悉 [Spring Event](/docs/CS/Framework/Spring/Event.md) 的话会发现，这里的关键正是那篇讲到的 `@TransactionalEventListener`——只是 Modulith 把"事务提交后 + 新事务 + 异步"这个组合打包成了默认姿势。

## Event Publication Registry

这就到了 Modulith 最有价值的部分。

朴素做法有个致命问题：`publishEvent` 只把事件交给了本 JVM 的内存投递。业务事务提交了、但监听器还没来得及跑，进程崩了——事件就永久丢了。典型故障是订单落库了、库存却没扣。

Event Publication Registry 把它变成**可靠的**：

1. 发布事件时，在**同一个业务事务**里往一张事件出版物表写一条记录；
2. 业务事务提交后，由 Registry 逐条投递给监听器；
3. 投递成功则标记完成，失败则保留记录等待重投；
4. 应用重启时自动重投那些没完成的出版物。

于是微服务领域常说的「事务性发件箱」（transactional outbox）模式在单体里成了开箱能力，无需自己建表写轮询任务。

### 2.0 的新状态机

旧模型只有简单的"未完成/完成"，2.0 引入了明确状态：

```text
published → processing → completed
                      └→ failed → resubmitted
```

其价值在于区分"正在处理"与"已经失败"。旧模型无法区分这两者，导致重投逻辑与多实例部署都很难做（必须靠分布式锁抢）；新模型下，**多个实例可以同时处理而不需要分布式锁**。

配套还有一个**陈旧监控器（staleness monitor）**：卡在某个状态过久的出版物会被判定为失败并按策略处理，避免永久悬挂。相关配置在 `spring.modulith.events.staleness.*` 命名空间下。

> [!NOTE]
> 存储方面，虽然每种持久化技术都有对应实现（JPA、JDBC、MongoDB、Neo4j），官方在 2.0 明确推荐**优先用 JDBC 实现**：它的数据模型与业务表完全隔离，既能和业务同库又不要求 JPA 参与，反而更简单。升级时记得用迁移工具同步调整出版物表结构，详见 [数据库迁移](/docs/CS/Framework/Spring/Migration.md)（Modulith 2.0 还支持每个模块带自己的迁移脚本）。

## 事件外部化

模块内的事件在需要通知**其它系统**时不必专门写一套 MQ 发送代码——给事件类型加 `@Externalized`，Modulith 会自动把它发到 broker：

```java
@Externalized("orders.placed.v1")
public record OrderPlaced(Long orderId, List<Item> items) {
}
```

这样，模块的事件既是内部解耦手段，又是对外集成契约；将来把模块拆成微服务时，这套事件流可以原样保留。底层依赖 Kafka / RabbitMQ 等，见 [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md) 与 [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md)。2.0 还支持让外部化**串行执行**，保证同一聚合的事件顺序不被并发打乱。

## 文档与可视化

Modulith 从代码推导出架构文档：

- **`ApplicationModules` 自动生成 PlantUML 图**：每个模块一张组件图，或整体模块关系图，可输出 PNG/SVG 放进 Wiki；
- **Module Canvas（2.0）**：交互式文档，直接从代码生成模块的依赖、暴露的接口、发布的事件与监听关系的全景视图；
- 文档作为**构建产物**更新，因此不会像手写架构图那样过期。

这组能力的潜台词是：**架构如果不写在代码里，就没有人会维护它**。

## 什么时候不适合

Modulith 适合"单体，但有明确的领域边界"的场景。不太适合的：

- **规模很小的应用**：几个包的服务，引入额外约定徒增成本；
- **边界本来就模糊**：先把职责划清楚，再谈工具强化；
- **已经是微服务**：跨服务的边界要靠网络契约治理，不属于 Modulith 的范畴。

它也不是"不想做微服务"的托词——恰恰相反，它的价值在于让未来的拆分变得可行。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Event](/docs/CS/Framework/Spring/Event.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [数据库迁移](/docs/CS/Framework/Spring/Migration.md)
- [Spring AMQP](/docs/CS/Framework/Spring/AMQP.md)
- [Spring Kafka](/docs/CS/Framework/Spring/Kafka.md)

## References

1. [Spring Modulith 2.0 GA 发布公告](https://spring.io/blog/2025/11/21/spring-modulith-2-0-ga-1-4-5-and-1-3-11-released)
2. [Spring Modulith 2.0 M1 发布公告（Event Publication Registry 详解）](https://spring.io/blog/2025/07/26/spring-modulith-2-0-M1-released)
3. [Spring Modulith Reference](https://docs.spring.io/spring-modulith/reference/)
