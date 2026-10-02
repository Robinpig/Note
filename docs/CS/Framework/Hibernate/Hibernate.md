## Introduction

Hibernate 是 Java 生态最主流的 **ORM（Object-Relational Mapping，对象关系映射）框架**，也是 **JPA（Jakarta Persistence API）规范的参考实现**。它在 Java 对象与关系数据库表之间建立映射，让开发者主要操作实体对象，由框架自动生成并执行 SQL，从而减少手写 JDBC 的样板代码。

原笔记概括的几个核心特点依然成立：

- **对象与数据库表映射**：实体类（`@Entity`）映射表、字段映射列、关联关系（`@OneToMany` 等）映射外键/关联表。
- **屏蔽底层数据库差异、增强可移植性**：通过方言（Dialect）为不同数据库生成对应的 SQL（分页、类型、DDL），切换数据库时代码基本不动。
- **API 无侵入性（POJO）**：实体是普通 Java 对象，不强制继承框架类/实现接口（早期 Hibernate 用 XML，现代标准用法是 JPA 注解）。
- **延迟加载（Lazy Loading）**：关联对象/集合默认按需查询，避免一次性拉取过多数据。

## JPA vs Hibernate

需要区分规范与实现：

- **JPA / Jakarta Persistence** 是一套**接口与注解规范**（`EntityManager`、`@Entity`、`@Table`、JPQL），本身不含实现。
- **Hibernate ORM** 是 JPA 的具体实现，并在规范之外提供 Hibernate 原生能力（HQL 扩展、二级缓存、`@Fetch`、拦截器、Envers 审计等）。
- [Spring Data JPA](/docs/CS/Framework/Spring/JPA.md) 则在 JPA/Hibernate 之上再封一层 Repository 抽象，自动实现常见查询；其底层默认仍是 Hibernate。

## Core Concepts

### Session / EntityManager

Hibernate 原生用 `Session`，JPA 标准用 `EntityManager`（`Session` 扩展了 `EntityManager`）。它是持久化操作的入口，提供 `persist / find / merge / remove / flush`，并维护一个**持久化上下文（Persistence Context）**，即一级缓存。

### Entity States

对象在 Hibernate 中有四种状态：

- **Transient（瞬时态）**：刚 new 出来、未被 Session 管理、数据库无记录。
- **Persistent（持久态）**：被 Session 管理、在一级缓存中，对它的修改在 flush 时自动同步到库（dirty checking）。
- **Detached（游离态）**：Session 关闭后脱离管理，仍有对应数据库记录，可用 `merge` 重新关联。
- **Removed**：标记删除，flush 时执行 DELETE。

### Dirty Checking and Flush

持久态实体的变更由 Hibernate 自动检测（dirty checking），在事务提交或 `flush()` 时批量生成 UPDATE，开发者无需手写。flush 只是把 SQL 发到数据库，真正提交仍由事务控制。

### First and Second Level Cache

- **一级缓存**：Session/持久化上下文级别，天然开启，同 Session 内相同主键只查一次。
- **二级缓存**：SessionFactory 级别、跨 Session，需显式开启并接缓存实现（Ehcache、Infinispan 等），适合变化少、读取多的数据。
- **查询缓存**：缓存查询结果集（存主键），常与二级缓存配合，命中率不高时不建议开。

### N+1 Problem

ORM 最经典的性能坑：查 N 条主实体后，访问每个实体的延迟关联又触发 N 条 SQL（1 条主查询 + N 条关联查询）。常见解法：

- 抓取策略：`join fetch` / `@EntityGraph` 用一条 join SQL 取数；批量抓取 `@BatchSize`；
- 把关联设为 `FetchType.SUBSELECT` 或在查询中显式 `fetch join`；
- 投影只查需要的字段（DTO/构造表达式），避免加载整个实体图。

## Lazy Loading

`@ManyToOne` 默认 EAGER、`@OneToMany` 默认 LAZY（实践中常显式把多对一也设为 LAZY，按需 fetch）。延迟加载依赖**会话仍然打开**：一旦 Session 关闭（如在 Controller/序列化阶段才访问关联），会抛 `LazyInitializationException`。
应对：在事务内把需要的数据 fetch 完、用 fetch join / EntityGraph、用 DTO 投影，或 Open Session in View（不推荐，会拉长会话、掩盖问题）。

## Mapping Boundaries

正如原笔记指出的：Hibernate 能很好映射常规的表、列、关联与继承，但**并非所有数据库特性都能优雅映射**，例如：

- 复杂的**索引**（全文索引、部分索引、表达式索引）、物化视图；
- 数据库**函数 / 存储过程**、触发器、特定方言的高级 SQL；
- 超复杂报表查询、多表动态 join、性能极致调优的 SQL。

这些场景通常绕过自动生成 SQL，直接使用原生 SQL（`createNativeQuery`）、JDBC、或干脆用对 SQL 控制更直接的 [MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)。

## Hibernate vs MyBatis

| 维度 | Hibernate（JPA） | MyBatis |
| ---- | ---- | ---- |
| 模型 | 全自动化 ORM，面向对象/实体 | SQL Mapper，SQL 与接口方法映射 |
| SQL 控制 | 框架生成，可控性弱（可用 JPQL/native 补强） | 完全手写 SQL，可控性强、易调优 |
| 映射 | 实体↔表、关联、继承自动处理 | 结果集↔对象手工/半自动映射 |
| 可移植性 | 方言屏蔽差异，跨库好 | SQL 与具体库耦合，迁移成本高 |
| 学习成本 | 状态管理/缓存/N+1 等概念门槛高 | 门槛低，会 SQL 即可 |
| 适合 | 领域模型清晰、CRUD 为主、跨库 | 复杂报表/查询、SQL 主导、遗留库 |

二者都由 [Spring Data](/docs/CS/Framework/Spring/Data.md) 提供统一的异常转译与模板支持，事务也统一由 Spring 的事务管理器管理（见 [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)）。

## Links

- [Spring Data](/docs/CS/Framework/Spring/Data.md)
- [Spring JPA](/docs/CS/Framework/Spring/JPA.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)

## References

1. [Hibernate ORM User Guide](https://hibernate.org/orm/documentation/)
2. [Jakarta Persistence (JPA) Specification](https://jakarta.ee/specifications/persistence/)
3. [Hibernate Performance / Fetching](https://docs.jboss.org/hibernate/orm/current/userguide/html_single/Hibernate_User_Guide.html#fetching)
