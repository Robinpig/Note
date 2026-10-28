## Introduction

MyBatis-Plus 不 fork MyBatis，而是「寄生」在 MyBatis 已有的两个扩展点上：

- **MyBatis 的 Mapper 动态代理**：`BaseMapper` 没有实现类，方法调用由 MyBatis 的 `MapperProxy` 翻译成 `namespace.id` 的 SQL 调用。MP 要做的只是「让这些 `id` 在 `Configuration` 里真实存在」。
- **MyBatis 的 `Interceptor` 插件链**：MP 把 `MybatisPlusInterceptor` 注册成 MyBatis 插件，在 Executor 执行前后改写 SQL。

这两条路径正交，下面分别展开。

## Startup Injection

### SqlMethod and Statement Id

`BaseMapper` 的每个方法最终都拼出一个 MyBatis statement id 并交给 `SqlSession` 执行。以 `deleteById` 为例（3.5.18 源码）：

```java
MapperProxyMetadata mapperProxyMetadata = MybatisUtils.getMapperProxy(this);
SqlSession sqlSession = mapperProxyMetadata.getSqlSession();
return sqlSession.delete(
    mapperProxyMetadata.getMapperInterface().getName() + Constants.DOT + SqlMethod.DELETE_BY_ID.getMethod(),
    obj);
```

也就是说，**statement 的命名空间 = Mapper 接口的全限定名，id = `SqlMethod` 的枚举名**（如 `com.example.UserMapper.deleteById`）。这要求这些 statement 必须在启动期被注册进 `Configuration`，否则 `SqlSession` 找不到会报错——这就是 `SqlInjector` 的任务。

### DefaultSqlInjector

`DefaultSqlInjector` 注入的模板方法（实例来自 3.5.18 源码 `getMethodList`）：

| 注入器 | 对应 `SqlMethod` | 说明 |
| :--- | :--- | :--- |
| `Insert` | `INSERT_ONE` / `UPSERT_ONE` | 选择字段插入；Phoenix 走 upsert |
| `Delete` | `DELETE` | 按 Wrapper 删 |
| `Update` | `UPDATE` | 按 id 或 Wrapper 改 |
| `SelectCount` / `SelectMaps` / `SelectObjs` / `SelectList` | 同名 | 四类查询 |
| `SelectWithCursor` | — | 游标查询 |
| `DeleteById` / `DeleteByIds` | `DELETE_BY_ID` / `DELETE_BY_IDS` | 按 id 删 |
| `UpdateById` | `UPDATE_BY_ID` | 按 id 改 |
| `SelectById` / `SelectByIds` | `SELECT_BY_ID` / `SELECT_BY_IDS` | 按 id 查 |

共 13 个注入器。若实体标注了 `@TableLogic`，注入器会改用 `LOGIC_*` 系列 SQL 模板（逻辑删除不真正删行，而是 `UPDATE ... SET deleted=1`）。

### TableInfo

每个实体类都会被 `TableInfoHelper` 解析成一份 `TableInfo`：表名、主键字段、所有可映射字段、是否带逻辑删除字段、是否带 `@Version`、字段填充策略等。`SqlMethod` 拼 SQL 时从 `TableInfo` 取表名与列名，**实体字段名 ↔ 列名的映射规则与 MyBatis 自身的 `Reflector` / 自动映射一致**（见 [MyBatis ResultSetHandler](/docs/CS/Framework/MyBatis/ResultSetHandler.md)）。

## Runtime Interception

### MybatisPlusInterceptor

MP 3.4.0 起把原先各自独立的插件（`PaginationInterceptor` 等）统一收敛为一个 `MybatisPlusInterceptor`，它本身就是一个 MyBatis `Interceptor`，内部维护一个 `List<InnerInterceptor>`。MyBatis 在创建四大对象（`Executor` / `StatementHandler` / `ParameterHandler` / `ResultSetHandler`）时按插件链包装，MP 在 `Executor` 层用 `InnerInterceptor` 接口做 `beforeQuery` / `beforeUpdate` / `beforePrepare` 等钩子。

### InnerInterceptor

`InnerInterceptor` 接口提供一组 `default` 方法，子类按需覆盖：

```java
default boolean willDoQuery(...)      // 是否要介入 query
default void beforeQuery(...)         // query 前改写 SQL / 参数
default boolean willDoUpdate(...)
default void beforeUpdate(...)
default void beforePrepare(...)       // 改写 boundSql / 拼分页参数
default void beforeGetBoundSql(...)
```

MP 的内置 `InnerInterceptor` 实现分两类（见 [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)）：

- **改写型**（依赖 jsqlparser，在 `mybatis-plus-jsqlparser-4.9`）：`PaginationInnerInterceptor`、`TenantLineInnerInterceptor`、`BlockAttackInnerInterceptor`、`IllegalSQLInnerInterceptor`、`DataPermissionInterceptor`、`DataChangeRecorderInnerInterceptor`。
- **轻量型**（在 `mybatis-plus-extension`，不依赖 SQL 解析）：`OptimisticLockerInnerInterceptor`、`DynamicTableNameInnerInterceptor`、`ShardingInnerInterceptor`、`ReplacePlaceholderInnerInterceptor`。

## How They Compose

```
启动期                                  运行期
------                                  ------
Mapper接口 ─┐
实体类   ─┼─▶ TableInfoHelper ─▶ TableInfo ─┐
GlobalConfig ─▶ DefaultSqlInjector ─▶ Configuration 里注册 MappedStatement
                                           │
                                           ▼
                                  SqlSession 执行 namespace.id
                                           │
                                           ▼
                                  MybatisPlusInterceptor (插件链)
                                           │
                  ┌────────────────────────┼────────────────────────┐
                  ▼                        ▼                        ▼
         PaginationInnerInterceptor  TenantLineInnerInterceptor  BlockAttackInnerInterceptor
                  │                        │                        │
                  └────────────────────────┼────────────────────────┘
                                           ▼
                                    JDBC (改写后的真实 SQL)
```

两条路径的边界：**`SqlInjector` 决定「有哪些预生成 SQL 可用」**，**`InnerInterceptor` 决定「这些 SQL 在真正发给 JDBC 前被怎么改」**。例如逻辑删除的条件追加发生在 `SqlInjector` 阶段（直接写进 SQL 模板），而分页的 `LIMIT` 追加和租户列条件追加发生在 `InnerInterceptor` 阶段（运行期解析并改写 boundSql）。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [MyBatis](/docs/CS/Framework/MyBatis/MyBatis.md)
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)
- [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)

## References

1. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
2. [MyBatis Interceptors 官方文档](https://mybatis.org/mybatis-3/configuration.html#plugins)
