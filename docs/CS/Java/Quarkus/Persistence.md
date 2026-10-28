## Introduction

Quarkus 的数据访问主力是 **Hibernate ORM with Panache**：底层 Hibernate ORM 7.4（3.40.1 平台锁 7.4.9.Final），上层 Panache 用构建期字节码生成把样板代码压到最少。反应式一侧是 Hibernate Reactive 3.4.2.Final。下一代统一 API「Panache Next」已在 3.31 落地（experimental）并更名为 **Quarkus Data Hibernate**。总览见 [Quarkus](/docs/CS/Java/Quarkus.md)，扩展装配机制见 [Extensions](/docs/CS/Java/Quarkus/Extensions.md)。

## Classic Panache: Two Shapes

Panache 实体编译期自动补齐缺失的 getter/setter，并把字段访问重写为访问器调用，所以实体可以用 public 字段。两种组织方式：

| 模式 | 写法 | 适用 |
| :--- | :--- | :--- |
| Active Record | 实体继承 `PanacheEntity`，查询作为静态方法挂在实体上 | 简单 CRUD，实体即门面 |
| Repository | 实体保持标准 JPA 写法，实现 `PanacheRepository<T>` 注入使用 | 复杂查询、领域分层 |

查询支持省略 `from` 前缀的 HQL 简写：`Person.find("name", "stef")` 即 `from Person where name = ?1`。事务用标准 `@Transactional`——注意它在 Panache 静态方法上是**实例级注解驱动的持久化上下文**，离开事务边界的方法查出来的实体是游离态。

## Hibernate Reactive

Hibernate Reactive 用非阻塞驱动（PostgreSQL/MySQL 的 reactive 客户端）替代 JDBC，API 返回 `Uni`/`Multi`，与 [REST](/docs/CS/Java/Quarkus/REST.md) 的反应式端点天然衔接。3.35 之前它缺少 `@Transactional` 的等价物，3.35 补上了 **Hibernate Reactive 的 `@Transactional` 支持**，此后反应式事务写法向阻塞侧对齐。

## Panache Next → Quarkus Data Hibernate

2025 年 12 月合入主线的 **Panache Next**（3.31 正式发布，**experimental**）解决经典 Panache 的结构性债务，后更名为 **Quarkus Data Hibernate**：

- **统一双轴**：阻塞/反应式 × 有状态会话（managed session）/无状态会话（`StatelessSession`）自由组合，不再有"选了 `PanacheEntity` 就锁死阻塞"的问题；
- **Jakarta Data 1.0**：`@Find`、`@HQL` 等注解定义类型安全查询，由注解处理器在**构建期**校验——HQL 字符串拼错从运行期 500 提前到构建失败；
- **仓储内嵌实体**：repository 作为嵌套接口定义在实体内，兼顾 active record 的贴近感与 repository 的分层；不注入也能用生成的 `Cat_.repo()` 元模型访问器；
- 经典 Panache 代码不受影响，迁移 opt-in。

需要注意它仍是实验特性：扩展名、包名（可能从 `io.quarkus.hibernate.panache` 迁到 `io.quarkus.data.hibernate`）、类名（`PanacheEntity` 可能改为 `ManagedEntity` 等）甚至 API 都可能再变，3.31 之后团队还在就分页 API（Jakarta Data `Page`/`PageRequest`、游标分页）征集反馈。生产选型请按实验特性对待。

## REST Data with Panache

`quarkus-rest-data-panache` 把 repository 直接暴露成 REST 资源，CRUD 端点零代码生成；3.31 起支持 `@PermissionsAllowed` 注解做端点级权限。适合内部管理端快速起步，不适合需要精细控制响应契约的公开 API。

## Schema and Cache

- **Flyway / Liquibase** 扩展管理 schema 版本；Dev Services 起容器时自动执行迁移可在 dev 模式验证。
- **二级缓存**默认 Caffeine；3.38 引入**基于权重的驱逐策略**，替代纯条目数限制，更适合缓存实体大小悬殊的场景。

## Version Timeline

| Quarkus | 数据访问相关变更 |
| :--- | :--- |
| 3.31 | Hibernate ORM 7.2 / Reactive 3.2 / Search 8.2；Panache Next 引入；`@PermissionsAllowed` on REST Data |
| 3.35 | Hibernate Reactive 支持 `@Transactional` |
| 3.37 | Hibernate ORM 7.4 |
| 3.38 | 二级缓存权重驱逐 |
| 3.40.1 | 平台锁定 Hibernate ORM 7.4.9.Final / Reactive 3.4.2.Final |

## Links

- [REST](/docs/CS/Java/Quarkus/REST.md)
- [Extensions](/docs/CS/Java/Quarkus/Extensions.md)
- [Config](/docs/CS/Java/Quarkus/Config.md)
- [DB](/docs/CS/DB/DB.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)
- [Java](/docs/CS/Java/Java.md)

## References

- https://quarkus.io/guides/hibernate-orm-panache
- https://quarkus.io/blog/hibernate-panache-next/
- https://quarkus.io/blog/panache-next-renamed-to-quarkus-data
- https://quarkus.io/blog/quarkus-3-31-released/
- https://quarkus.io/blog/quarkus-3-40-released/
