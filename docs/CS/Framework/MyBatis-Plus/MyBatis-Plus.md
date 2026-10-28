## Introduction

MyBatis-Plus（简称 MP）是 baomidou 组织（作者 hubin）维护的**第三方增强工具包**，与 MyBatis 官方无关。它的定位是「在 MyBatis 之上做单表 CRUD 与通用能力的开箱即用」，而不是另起一套 ORM：**不改 MyBatis 任何源码**，通过两条路径注入能力——

1. **启动期注入 MappedStatement**：扫描实体类，按 `SqlMethod` 模板在 `Configuration` 里注册一批预生成 SQL（insert / delete / update / select…），让 `BaseMapper` 的接口方法直接有对应的 `namespace.id` 可执行。
2. **运行期插件拦截**：用 `MybatisPlusInterceptor` 挂一组 `InnerInterceptor`，在 Executor 执行前后改写 SQL（分页、多租户、逻辑删除条件、数据权限等）。

代价是它与 MyBatis 版本强绑定：`mybatis-plus-core` 3.5.18 编译依赖 `mybatis` **3.5.19**，因此升级到 MyBatis 3.6.0 前必须等 MP 发布兼容版本，不能单独抬升 MyBatis。

## Version Baseline

| 构件 | 基线版本 | 关键事实 |
| :--- | :--- | :--- |
| `com.baomidou:mybatis-plus`（BOM） | **3.5.18**（2026-10-21） | 聚合模块；实际能力分布在以下子模块 |
| `mybatis-plus-core` | 3.5.18 | 编译依赖 `mybatis` **3.5.19**、`mybatis-plus-annotation`、`mybatis-plus-jsqlparser-4.9`（jsqlparser **4.9**） |
| `mybatis-plus-extension` | 3.5.18 | `IRepository`、`MetaObjectHandler`、链式 `Wrapper`、乐观锁/动态表名/分片拦截器所在 |
| `mybatis-plus-spring` | 3.5.18 | `IService` 接口与 `ServiceImpl` 实际落在此模块（不是 core） |
| `mybatis-plus-jsqlparser-4.9` | 3.5.18 | 依赖 jsqlparser 4.9；分页、多租户、防全表删、数据权限等改写型拦截器在此 |
| `mybatis-plus-generator` | 3.5.18 | 代码生成器（`FastAutoGenerator`），可选 velocity / freemarker / beetl 模板引擎 |
| `mybatis-plus-spring-boot3-starter` | 3.5.18 | Spring Boot 3 自动装配 |
| `mybatis-plus-spring-boot4-starter` | 3.5.18 | Spring Boot 4 自动装配（2026 新增） |
| `mybatis-plus-boot-starter` | 3.5.18 | 老 starter（Spring Boot 2 兼容，已不推荐） |

> [!WARNING]
> `mybatis-plus-spring`（含 `IService` / `ServiceImpl`）与 `mybatis-plus-extension` 是**两个不同模块**：`IService` 接口的父接口 `IRepository`（承载绝大多数 CRUD 默认实现）和 `MetaObjectHandler` 都在 `mybatis-plus-extension`。按 Maven 坐标引入时，业务代码通常只依赖 `mybatis-plus-spring` 或 boot starter，二者会 transit 拉入 core / extension。

## Two Roads

[Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md) 讲清楚这两条路径是怎么接进 MyBatis 执行链的：启动期靠 `SqlInjector` + `TableInfoHelper` 把 SQL 注册进 `Configuration`，运行期靠 `MybatisPlusInterceptor` 挂到 MyBatis 的插件责任链上。两者正交——前者决定「能执行哪些预生成 SQL」，后者决定「执行时 SQL 被怎么改」。

## Modules

MP 拆成多个 Maven 模块，不是把所有东西塞进一个 jar：

- **core**：`BaseMapper`、`Wrapper`、`SqlMethod` 模板、`TableInfo` 元数据、`GlobalConfig`、`DefaultSqlInjector`。这是最小可用集。
- **annotation**：`@TableName` / `@TableId` / `@TableField` / `@TableLogic` / `@Version` 等实体注解。
- **extension**：`IRepository` / `IService` / `ServiceImpl`、链式 `Wrapper`（`QueryChainWrapper` 等）、`MetaObjectHandler`、以及不依赖 SQL 解析的拦截器（乐观锁、动态表名、分片）。
- **jsqlparser-4.9**：基于 jsqlparser 4.9 的改写型拦截器（分页、多租户、防全表删、非法 SQL 检测、数据权限）。
- **spring**：把 `IService` 接口独立出来，避免 core 反向依赖 Spring。
- **generator**：`FastAutoGenerator` 代码生成。

这种拆分意味着：**只用 `BaseMapper` + 分页** 的最小依赖是 core + jsqlparser-4.9；如果要用 `IService` / 自动填充，则需要 extension + spring；两者通过 boot starter 自动聚合。

## Compare with MyBatis

| 维度 | MyBatis | MyBatis-Plus |
| :--- | :--- | :--- |
| 单表 CRUD | 每个表都要手写 `mapper.xml` 或注解 SQL | `BaseMapper` / `IService` 开箱即用，启动期自动注入 |
| 分页 | 自己写 `LIMIT` 或手写 `PageHelper` 类插件 | `PaginationInnerInterceptor` 自动改写并优化 count |
| 逻辑删除 | 自己写 `WHERE deleted=0` | `@TableLogic` 自动在增删改查里追加条件 |
| 多租户 | 自己写拦截器 | `TenantLineInnerInterceptor` 自动追加租户列条件 |
| 代码生成 | 无官方方案 | `FastAutoGenerator` 反向生成 entity / mapper / service |
| 不变量 | 始终是「SQL 映射框架」 | 始终是「MyBatis 之上的增强层」，核心仍是 MyBatis |

## Design Patterns

| 模式 | 在 MP 中的体现 | 作用 |
| :--- | :--- | :--- |
| **Template Method** | `SqlMethod` 用 `SqlTemplate` 函数式接口定义每种 SQL 模板 | 18 种预生成 SQL 共用一套拼装骨架 |
| **Chain of Responsibility** | `MybatisPlusInterceptor` 串起多个 `InnerInterceptor` | 分页 / 租户 / 权限按顺序改写 SQL |
| **Factory / Builder** | `Wrappers.query()` / `FastAutoGenerator.create()` | 流式构造条件与生成器配置 |
| **Proxy** | 复用 MyBatis 的 `MapperProxy`（`MapperProxyMetadata` 透出 `SqlSession`） | `BaseMapper` 方法无实现类，靠代理路由到注入的 statement |
| **Strategy** | `IdType`、`FieldStrategy`、`DbType` 枚举 / 方言 | 主键生成、字段填充、分页方言可替换 |
| **Adapter** | `MetaObjectHandler` 统一自动填充入口 | 插入 / 更新填充逻辑收敛到一个接口 |

## Subpages

- [Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md)：两条接入路径与执行链路。
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)：`BaseMapper` / `IService` / `IRepository` API 与批量语义。
- [Wrapper](/docs/CS/Framework/MyBatis-Plus/Wrapper.md)：条件构造器与 SQL 注入风险。
- [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)：`MybatisPlusInterceptor` 与内置 `InnerInterceptor`。
- [Features](/docs/CS/Framework/MyBatis-Plus/Features.md)：主键、逻辑删除、自动填充、乐观锁、多租户。
- [CodeGenerator](/docs/CS/Framework/MyBatis-Plus/CodeGenerator.md)：`FastAutoGenerator` 代码生成。
- [SpringBoot](/docs/CS/Framework/MyBatis-Plus/SpringBoot.md)：starter 与自动装配配置。

## Links

- [MyBatis（被增强的底层框架）](/docs/CS/Framework/MyBatis/MyBatis.md)
- [Spring Framework](/docs/CS/Framework/Spring/Spring.md)
- [Hibernate（另一条持久层路线）](/docs/CS/Framework/Hibernate/Hibernate.md)
- [MyBatis 目录索引](/docs/CS/Framework/MyBatis/README.md)

## References

1. [MyBatis-Plus 官方文档](https://baomidou.com/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
3. [MyBatis-Plus Releases](https://github.com/baomidou/mybatis-plus/releases)
