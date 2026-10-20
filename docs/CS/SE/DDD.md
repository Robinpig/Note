## Introduction

领域驱动设计（Domain-Driven Design，DDD）是一套**让代码结构贴合业务结构**的方法论：Eric Evans 在 2003 年的同名著作里提出，复杂系统的真正难点不在技术，而在于业务概念本身盘根错节，如果模型没建对，再好的框架也只是在错误的结构上加速。DDD 给出的对策是先把领域模型建准确，再用一整套模式（统一语言、限界上下文、聚合、领域事件）把模型固化到代码边界里。架构风格如何承接这套边界见 [Architecture](/docs/CS/SE/Architecture.md)。

## Ubiquitous Language

统一语言（Ubiquitous Language）要求在需求分析、设计讨论、代码命名、甚至数据库表名里使用**同一套词汇**，并且由领域专家与开发共同维护。一旦同一个概念在口头叫"订单"、代码里叫 `Order`、库表里叫 `trade_record`，模型就开始分裂，后续每次翻译都是一次失真与 bug 机会。统一语言是 DDD 里成本最低、收益最高的一条。

## Bounded Context

限界上下文（Bounded Context）是统一语言的**适用边界**：同一个词在不同上下文里含义不同（"商品"在商品中心指 SKU，在订单上下文里只是订单行上的一个快照），强行统一反而产生畸形模型。上下文之间靠防腐层（Anti-Corruption Layer）隔离外部模型、靠上下文映射（Context Map）标注协作关系（上下游、共享内核、客户方-供应方）。微服务边界通常就画在限界上下文上——这也是它与 [中台](/docs/CS/SE/中台.md) 这类"能力复用"思路的张力所在：复用要求统一，上下文要求边界清晰。

## Building Blocks

| 构造块 | 含义 | 要点 |
|--------|------|------|
| Entity | 有唯一标识（identity id），标识不变而属性可变 | 判等靠 id，不靠属性值 |
| Value Object | 没有自己的标识，靠属性值判等 | 不可变；如金额 + 币种、地址 |
| Aggregate / Aggregate Root | 一组必须保持一致的对象集合，根是唯一对外入口 | 一次事务只修改一个聚合，跨聚合用领域事件做最终一致 |
| Domain Event | 领域里已发生的事实（过去式命名） | 解耦上下文、驱动流程，见 [Workflow](/docs/CS/SE/Workflow.md) |
| Repository | 聚合的持久化抽象，接口在领域层、实现在基础设施层 | 让领域层不依赖具体存储 |
| Domain Service | 不属于任何单个实体的领域逻辑 | 无状态，命名来自动作而非"XXService" |

**Anemic Domain Object（贫血领域对象）**是这套模式的反面：对象只作数据载体，不拥有行为和动作，全部逻辑外泄到 Service 里。它其实是过程式代码穿着 OO 的外衣，业务规则散落各处、无法单测、随规模腐化最快。

## Persistence Objects

实践中还要区分领域对象与存储对象，二者不该混用：

- **PO（Persistent Object）**：与数据库表一一对应的持久化对象，属于基础设施层；
- **DAO（Data Access Object）**：封装表访问的对象；
- 领域层的 Entity / Value Object 通过 Repository 与 PO 互转，避免表的结构直接污染领域模型。

## Conway's Law

康威（Melvin Conway）定律：**任何组织在设计一套系统时，所交付的设计方案在结构上都会与该组织的沟通结构保持一致**。这不是比喻而是约束——组织结构不改，系统边界很难真的改过来。因此限界上下文的划分往往同时也是团队边界的划分。

## Links

- [Architecture](/docs/CS/SE/Architecture.md)
- [Workflow](/docs/CS/SE/Workflow.md)
- [中台](/docs/CS/SE/中台.md)
- [Clean Code](/docs/CS/SE/Clean_Code.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)

## References

1. [Domain-Driven Design — the official site](https://www.domaindrivendesign.org/)
2. [DomainDrivenDesign — Martin Fowler's bliki](https://martinfowler.com/bliki/DomainDrivenDesign.html)
