## Introduction

> Define a one-to-many dependency between objects so that when one object changes state, all its dependents are notified and updated automatically.
> —— GoF

观察者模式让"一件事发生后要通知多方"解耦：发布者只维护一份订阅列表，事件发生时逐个通知，不关心谁订阅了、订阅后做什么。它是事件驱动架构在单进程内的最小形态。

Java 一度把它做成了语言级设施——`Observable` 类与 `Observer` 接口，但 JDK 里这个实现有两个缺陷：`Observable` 是类不是接口（继承挤占唯一父类位）、且通知不保证顺序、事件对象没有泛型约束，因此 Java 9 起已**废弃**。现代实践转向框架级实现。

## Spring ApplicationEvent

Spring 的事件机制是观察者模式的标准工业实现：

```java
// 发布方：注入 ApplicationEventPublisher，只发事件，不知道谁在处理
publisher.publishEvent(new OrderPaidEvent(orderId));

// 订阅方：@EventListener，容器自动注册；@Async 可异步化
@EventListener
void onPaid(OrderPaidEvent e) { couponService.issue(e.getOrderId()); }
```

关键设计：**发布者与订阅者零直接依赖**，加一个"发券"订阅方不需要改订单服务的任何一行；`@TransactionalEventListener(phase = AFTER_COMMIT)` 还能让事件只在事务提交后触发，避免"事务回滚了但券已发"的经典事故，见 [Spring 事件](/docs/CS/Framework/Spring/Event.md)。订阅多、处理慢的场景则应该下沉到消息队列——见下文边界。

## Guava EventBus

Guava 的 `EventBus` 展示了观察者模式的另一种取舍：**按事件类型订阅**，`@Subscribe` 方法的唯一参数决定它收什么事件，无需实现任何接口，发布方连"事件类"都不用继承基类。它的代价是进程内同步派发（`AsyncEventBus` 才异步）、且没有 Spring 那样的生命周期与事务集成。适合轻量的进程内广播，大型系统里通常被 Spring 事件或 MQ 取代。

## Why Not Just Use MQ

单进程内用不用观察者、跨进程用不用 MQ，判据是**故障边界与投递语义**：

| | 进程内观察者 | 消息队列 |
|---|------------|---------|
| 可靠性 | 订阅方抛异常会影响发布方（可配异步/异常隔离） | broker 持久化，掉线重连可补 |
| 事务 | 同事务，需 `AFTER_COMMIT` 防回滚事故 | 最终一致，需幂等 + 对账 |
| 范围 | 本 JVM | 跨服务、跨语言 |
| 时序 | 单 JVM 内按注册序 | 分区/队列内有序，全局不保证 |

实践里两者常接力：进程内事件做**本地即时反馈**（缓存失效、日志），跨服务副作用走 [MQ](/docs/CS/MQ/MQ.md)。直接把业务主流程塞给进程内异步监听是常见误用——进程一崩全部丢失，且缺乏重试语义。

## Boundary with Similar Patterns

- **中介者（Mediator）**：观察者是"一对多广播"，订阅者互不知晓；中介者是"多对多协调"，同事对象之间不直接通信但都认识中介者——关注点是**谁**转发，不是**是否**转发；
- **责任链**：请求沿链传递直到某个节点处理；观察者是**每个**订阅者都收到；
- **发布订阅（MQ）**：架构同构，差别在 broker 与进程边界，见上文。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Spring 事件](/docs/CS/Framework/Spring/Event.md)
- [MQ](/docs/CS/MQ/MQ.md)
- [Template Method](/docs/CS/DesignPatterns/TemplateMethod.md)

## References

1. [Refactoring.Guru - Observer](https://refactoring.guru/design-patterns/observer)
2. [OODesign - Observer Pattern](https://www.oodesign.com/observer-pattern)
3. [JDK 8 Observer 文档（已废弃，了解历史用）](https://docs.oracle.com/javase/8/docs/api/java/util/Observer.html)
4. [Guava EventBus 文档](https://github.com/google/guava/wiki/EventBusExplained)
