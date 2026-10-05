## Introduction

Spring Data 是 Spring 家族里负责**统一数据访问**的伞形项目（umbrella project，官方主页的族徽就是一把伞）。它的目标是在关系型数据库、NoSQL、Map-Reduce、云数据服务等各类底层存储之上，提供一套熟悉且一致的、基于 Spring 的编程模型，同时保留各数据存储自身的特性。

Spring Data 的价值有两层：

- 对上，用统一的 `Repository` 抽象屏蔽不同存储的 API 差异，业务代码面向接口编程；
- 对下，每个具体存储一个子模块（Spring Data JPA、JDBC、Redis、MongoDB、R2DBC、Cassandra、Elasticsearch、Neo4j、Key-Value、LDAP、Couchbase、REST 等），由它们适配各自的驱动与查询方式。

所有模块共享一个公共底座 **Spring Data Commons**，Repository 抽象、派生查询、分页、投影、审计等机制都定义在这里，再被各存储模块继承与特化。

> [!NOTE]
> 当前基线（2026-10 核实）为 **Spring Data 2025.1（代号，对应于 Boot 4 一代，patch 到 2025.1.7）**。Spring Data 采用**日历版本号**（2024.0、2024.1、2025.0、2025.1 …），没有 "7.x" 这种大版本号——不要与 Spring Framework 7 混淆。Boot 4 一代绑定的就是 2025.1。

## 模块家族

| 模块 | 存储形态 | 关键抽象 | 备注 |
| :--- | :--- | :--- | :--- |
| JPA | 关系型（ORM，Hibernate） | `JpaRepository` | 最常用，见 [Spring JPA](/docs/CS/Framework/Spring/JPA.md) |
| JDBC | 关系型（无 ORM） | `JdbcRepository` / `JdbcTemplate` | 比 JPA 轻，直接 SQL |
| Redis | 内存 KV | `RedisRepository` / `RedisTemplate` | 以 `@RedisHash` 映射对象 |
| MongoDB | 文档 | `MongoRepository` / `MongoTemplate` | Document 模型 |
| R2DBC | 关系型（响应式） | `R2dbcRepository` / `DatabaseClient` | 见下节 Reactive |
| Cassandra | 宽列 | `CassandraRepository` | |
| Elasticsearch | 搜索引擎 | `ElasticsearchRepository` | |
| Neo4j | 图 | `Neo4jRepository` | |
| Key-Value | 通用 KV | `KeyValueRepository` | 内存/简单存储 |
| REST | 远程仓库 | `RepositoryRestResource` | 把另一个仓库经 HTTP 暴露为本地仓库 |

## Repository Abstraction

核心是一组层层继承的标记接口，开发者只需定义自己的接口并继承它们，Spring 在启动时用动态代理（JDK 动态代理或 CGLIB，取决于是否只定义接口）生成实现：

- `Repository<T, ID>`：最顶层标记接口，仅用来触发组件扫描。
- `CrudRepository<T, ID>`：提供 `save` / `findById` / `findAll` / `existsById` / `count` / `deleteById` 等 CRUD 方法，返回 `Iterable`。
- `PagingAndSortingRepository<T, ID>`：在 CRUD 之上增加分页与排序（`Pageable` / `Sort`）。
- 各存储还有自己的扩展，如 JPA 的 `JpaRepository`、响应式的 `ReactiveCrudRepository`、Kotlin 协程的 `CoroutineCrudRepository`。

```java
public interface UserRepository extends JpaRepository<User, Long> {

    // 派生查询：方法名即查询，无需写 SQL
    List<User> findByStatusAndCreatedAtAfter(UserStatus status, Instant after);

    // 分页
    Page<User> findByCity(String city, Pageable pageable);
}
```

> [!WARNING]
> `CrudRepository` 的方法返回的是 `Iterable`，在流式处理时不够趁手。Spring Data Commons 3.0 起额外提供了 **`ListCrudRepository` / `ListPagingAndSortingRepository`**，把返回类型改为 `List` / `Page`，避免到处包一层 `Iterable`。新代码优先用这两个而非 `CrudRepository`。

查询方法的来源按优先级：方法名派生查询（query derivation）→ `@Query` 显式声明 → 存储特定注解（如 `@Aggregation`）。

## 派生查询细节

### 方法名关键字

派生查询的方法名由**主题关键字 + 条件属性 + 比较词**拼成。主题关键字决定动作：

- 查询：`findBy` / `readBy` / `queryBy` / `getBy`（语义等价）
- 计数：`countBy`
- 删除：`deleteBy` / `removeBy`（需 `@Transactional`，返回删除条数）
- 存在性：`existsBy`

比较词涵盖 `And` / `Or` / `Between` / `LessThan` / `GreaterThan` / `Like` / `StartingWith` / `Containing` / `In` / `IgnoreCase` 等。

### 属性表达式与下划线消歧

嵌套属性可以直接写在方法名里：`findByAddressZipCode` 表示 `user.address.zipCode`。但当 `User` 同时拥有 `addressZipCode` 字段和 `address.zipCode` 路径时会产生**歧义**——此时用**下划线显式界定路径**：

```java
// 明确指 address.zipCode 路径，而非 addressZipCode 字段
List<User> findByAddress_ZipCode(String zip);
```

下划线因此是保留字，属性名本身含下划线时需转义（`_`）为 `__`。

### 分页：Page 与 Slice

`Pageable` 分页有两种返回：

- `Page<T>`：会**额外执行一条 count 查询**得到总条数（`totalElements` / `totalPages`），适合"跳页 + 显示总页数"的传统分页。
- `Slice<T>`：**不查总数**，只通过 `limit+1` 判断"是否还有下一页"（`hasNext()`）。适合"无限滚动 / 下拉加载更多"，省掉昂贵的 count。

### 限定结果与去重

```java
User findFirstByOrderByCreatedAtDesc();        // 取第一条
List<User> findTop10ByStatus(Status s);        // 取前 10 条
Stream<User> findDistinctByCity(String city);  // 去重（Distinct）
```

`Stream` 返回类型用法上需注意：它在遍历结束后要关闭底层游标，通常配合 try-with-resources。

### 更新 / 删除：@Modifying

派生查询默认只生成 SELECT。要写改/删语句，用 `@Query` + `@Modifying`：

```java
@Modifying
@Query("update User u set u.status = :s where u.createdAt < :before")
int deactivateInactive(@Param("s") Status s, @Param("before") Instant before);
```

`@Modifying` 会标记"这是写操作"，返回**受影响行数（int）**；方法默认需要事务（`@Transactional`），否则会抛 `TransactionRequiredException`。它还可配 `clearAutomatically=true` 在语句执行后清理一级缓存，避免后续读取拿到脏数据。

> [!TIP]
> `findById` 返回 `Optional`，未命中是**空 Optional 而非异常**；而用 `CrudRepository.getReferenceById`（延迟引用）或老式 `findOne` 时，未命中才可能抛 `EmptyResultDataAccessException`。派生 `List` 查询则永远返回空集合、不抛异常。

## Projection（投影）

只取实体的一部分字段时，用投影避免把整个聚合拖出来：

- **接口投影（闭式）**：定义一个只有 getter 的接口，Spring Data 用目标接口代理读取所需列。
  ```java
  interface UserName { String getName(); String getEmail(); }
  List<UserName> findByCity(String city);   // 只 SELECT name, email
  ```
- **接口投影（开式）**：接口里加默认方法或 `@Value("#{target.name + ' ' + target.email}")` 用 SpEL 组合，但 SpEL 投影会在运行期求值、难以 AOT 优化。
- **类投影（DTO 投影）**：配合 `@Query("select new com.x.UserDto(u.name, u.email) ...")` 构造函数表达式，或 MapStruct 之类映射，类型最安全、最适合跨层传输。
- **动态投影**：Repository 方法返回泛型 `T`，调用方传具体投影类型的 `Class` 决定取哪些列：
  ```java
  <T> List<T> findByCity(String city, Class<T> type);
  // repo.findByCity("BJ", UserName.class);
  ```

## Auditing（审计字段）

用注解自动填充创建/修改时间与人：

```java
@Entity
class Order {
    @CreatedDate  Instant createdAt;     // 创建时间
    @LastModifiedDate Instant updatedAt; // 最后修改时间
    @CreatedBy    String creator;        // 创建人
    @LastModifiedBy String modifier;     // 最后修改人
}
```

再在主配置上 `@EnableJpaAuditing`，并提供一个 `AuditorAware<T>` Bean 告诉框架"当前操作人是谁"（从 Security 上下文取）。时间字段也可标在 `@MappedSuperclass` 基类上让所有实体继承。

## 基础设施与 save 语义

`CrudRepository.save` 在 JPA 实现里等价于 `entityManager.merge`——即**按 ID 是否存在决定插入或更新**，区分不了"新对象"与"游离对象"，这点在 Hibernate 7 下更彻底（persist 路径被统一为 merge 语义，详见 [Spring JPA](/docs/CS/Framework/Spring/JPA.md)）。需要严格"新对象才 insert"的语义时，自己用 `Persistable` 接口暴露 `isNew()` 让 Spring Data 判断。

`JpaRepository` 还提供 `flush()`、`saveAndFlush()`、`getById` 等 JPA 专属方法；底层通过 `JpaEntityInformation` 抽象出 ID 与 `isNew` 判定，与具体 JPA 提供方解耦。

### 构建期查询编译

Spring Data 2025.1（Boot 4 一代）会把符合条件的 repository 派生查询在**构建期**编译成实现，而不是等到运行期再用 `PartTree` 解析方法名、拼装查询。收益是启动更快，并把查询语法错误提前到编译阶段暴露；对 [AOT](/docs/CS/Framework/Spring/AOT.md) / native image 尤其重要，因为构建期产物不再依赖运行期的反射解析。

## 各存储模块简述

### JDBC

`spring-boot-starter-data-jdbc` 提供比 JPA 轻的 ORM：无代理、无一级/二级缓存、对象直接映射行，适合不想引入完整 Hibernate 的场景。`JdbcTemplate` 负责连接获取/归还、参数绑定、`ResultSet` 映射与异常翻译，是更底层的工具，见上文 DataSource。

### Redis

`@RedisHash("users")` 标在实体上，`RedisRepository` 自动以 KV 形式存对象；更精细的控制走 `RedisTemplate`（序列化器需显式配置，否则默认 JDK 序列化）。注意 Redis 做缓存时应走 [Spring Boot 缓存](/docs/CS/Framework/Spring_Boot/cache.md) 抽象，而非直接拿 `RedisTemplate` 当缓存用。

### MongoDB

文档模型，`MongoRepository` + `MongoTemplate` 双 API；聚合管道用 `Aggregation` API。`@Document` / `@Field` 映射 BSON。

### R2DBC

对应阻塞式的 JDBC/JPA，Spring Data 提供响应式数据访问：`DatabaseClient`、`R2dbcRepository` 返回 `Mono` / `Flux`，与 [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md) / [Reactor](/docs/CS/Framework/reactor/Reactor.md) 端到端打通。注意 JDBC 本身是阻塞规范，因此不存在"响应式 JDBC"，这正是 R2DBC 另起炉灶的原因。

### Spring Data REST

加 `spring-boot-starter-data-rest` 后，任意 `Repository` 会被自动暴露为 HATEOAS 风格的 REST 端点（`/users`、`/users/1`），`@RepositoryRestResource` 可定制路径与暴露字段。它省掉手写 Controller，但生产环境需配好安全与字段投影，避免把内部模型直接外泄。

## Exception Translation

Spring 数据访问的另一条主线是**异常体系转换**。原生 JDBC / JPA / 各驱动抛出的异常各不相同且多为受检异常，Spring 统一转译为 `DataAccessException` 体系下的非受检（runtime）异常，例如：

- `DataIntegrityViolationException`：唯一约束、外键冲突等完整性违反；
- `OptimisticLockingFailureException`：乐观锁版本冲突；
- `DataRetrievalFailureException`：查询结果不符合预期（如 `EmptyResultDataAccessException`）。

JDBC 侧的转换由 `SQLExceptionTranslator` 完成，默认实现 `SQLErrorCodeSQLExceptionTranslator` 依据数据库厂商的错误码判定异常类型。错误码到异常的映射表存放在 classpath 的 `org/springframework/jdbc/support/sql-error-codes.xml`，里面按数据库产品（MySQL、PostgreSQL、Oracle、H2 等）分别列出 `badSqlGrammarCodes`、`duplicateKeyCodes`、`dataIntegrityViolationCodes` 等，因此同一条 SQL 在不同库上都能被翻译成语义一致的 Spring 异常。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring JPA](/docs/CS/Framework/Spring/JPA.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring WebFlux](/docs/CS/Framework/Spring/webflux.md)
- [Reactor](/docs/CS/Framework/reactor/Reactor.md)
- [Hibernate](/docs/CS/Framework/Hibernate/Hibernate.md)
- [Spring Boot 缓存](/docs/CS/Framework/Spring_Boot/cache.md)
- [AOT](/docs/CS/Framework/Spring/AOT.md)

## References

1. [Spring Data Reference](https://docs.spring.io/spring-data/commons/reference/repositories/core-concepts.html)
2. [Spring Data project list](https://spring.io/projects/spring-data)
3. [Spring Framework - DAO Support](https://docs.spring.io/spring-framework/reference/data-access/dao.html)
4. [Spring Data REST Reference](https://docs.spring.io/spring-data/rest/reference/)
