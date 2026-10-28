## Introduction

MyBatis-Plus 3.4.0 起把原先各自独立的插件（`PaginationInterceptor`、`TenantLineInterceptor` 等）收敛为一个统一的 `MybatisPlusInterceptor`。它本身是一个 MyBatis `Interceptor`，内部维护一个 `List<InnerInterceptor>`，按列表顺序对 SQL 做前置改写。所有内置能力——分页、多租户、防全表删、数据权限——都是 `InnerInterceptor` 的实现。

`InnerInterceptor` 接口（`mybatis-plus-extension`）提供一组 `default` 钩子，子类按需覆盖：

```java
default boolean willDoQuery(Executor, MappedStatement, parameter, RowBounds, ResultHandler)
default void beforeQuery(...)
default boolean willDoUpdate(Executor, MappedStatement, parameter)
default void beforeUpdate(...)
default void beforePrepare(StatementHandler, Connection, transactionTimeout)
default void beforeGetBoundSql(StatementHandler)
default void setProperties(Properties)
```

## Register

```java
@Configuration
public class MpConfig {
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new TenantLineInnerInterceptor(tenantHandler));
        interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

列表顺序即执行顺序。惯例是**把 `PaginationInnerInterceptor` 放在最后**：它需要在其他拦截器把最终 SQL 确定后，再追加 `LIMIT` / 改写 count，否则分页改写会作用在尚未定型的 SQL 上。

## Built-in Interceptors

MP 的内置 `InnerInterceptor` 分两类，取决于是否依赖 jsqlparser 做 SQL 解析：

| 拦截器 | 所在模块 | 作用 |
| :--- | :--- | :--- |
| `PaginationInnerInterceptor` | `mybatis-plus-jsqlparser-4.9` | 分页：追加 `LIMIT`、优化 count |
| `TenantLineInnerInterceptor` | `mybatis-plus-jsqlparser-4.9` | 多租户：自动追加租户列条件 |
| `BlockAttackInnerInterceptor` | `mybatis-plus-jsqlparser-4.9` | 防全表更新 / 删除（无 WHERE 直接拦截） |
| `IllegalSQLInnerInterceptor` | `mybatis-plus-jsqlparser-4.9` | 非法 SQL 检测（无 WHERE 的删改、危险片段等） |
| `DataPermissionInterceptor` | `mybatis-plus-jsqlparser-4.9` | 数据权限：按规则追加行级条件 |
| `DataChangeRecorderInnerInterceptor` | `mybatis-plus-jsqlparser-4.9` | 记录数据变更前后值 |
| `OptimisticLockerInnerInterceptor` | `mybatis-plus-extension` | 乐观锁：追加 `@Version` 条件 |
| `DynamicTableNameInnerInterceptor` | `mybatis-plus-extension` | 运行期动态表名 |
| `ShardingInnerInterceptor` | `mybatis-plus-extension` | 分片路由 |
| `ReplacePlaceholderInnerInterceptor` | `mybatis-plus-extension` | 占位符替换 |

> [!WARNING]
> **改写型拦截器（分页 / 租户 / 防全表删 / 数据权限）依赖 jsqlparser**，必须引入 `mybatis-plus-jsqlparser-4.9` 模块；只用乐观锁 / 动态表名则可只依赖 `mybatis-plus-extension`。boot starter 会自动聚合，但手动按坐标引入时要选对模块，否则 `NoClassDefFoundError: net.sf.jsqlparser...`。

## PaginationInnerInterceptor

分页拦截器是 MP 分页能力的核心。其字段默认值（3.5.18 源码）如下：

| 字段 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `overflow` | `boolean` | `false` | 溢出总页数后是否处理：为 `true` 时请求页 > 总页数会回退到第 1 页；为 `false` 直接按请求页查（可能空结果） |
| `maxLimit` | `Long` | `null` | 单页最大条数上限；**默认 `null` 表示不限制**。源码中不存在 `DEFAULT_MAX_LIMIT` 常量，所谓「默认 -1」是早期版本的误传 |
| `optimizeJoin` | `boolean` | `true` | 生成 countSql 时优化掉 join，**目前只支持 `LEFT JOIN`** |
| `dbType` | `DbType` | 自动探测 | 方言；不指定时按 `Executor` 的 `DataSource` 元数据推断 |
| `dialect` | `IDialect` | 按 `dbType` 选 | 分页方言实现 |

分页拦截器在执行分页查询时：`page.maxLimit() != null ? page.maxLimit() : maxLimit`——即**单页的 `maxLimit`（通过 `Page` 对象设置）会覆盖全局 `maxLimit`**。它还会对分页 count 做优化：`optimizeJoin=true` 时会把只用于 join 的表从 `COUNT` 语句里去掉，减少无意义的 join。

## TenantLineInnerInterceptor

多租户拦截器要求实现一个 `TenantLineHandler`：

```java
public interface TenantLineHandler {
    Expression getTenantId();              // 当前租户 id（注入为参数）
    String getTenantIdColumn();            // 租户列名
    boolean ignoreTable(String tableName); // 哪些表不受多租户约束
}
```

它在每张受影响表的 WHERE / JOIN ON 后自动追加 `tenant_id = ?`。`ignoreTable` 返回 `true` 的表（如字典表、公共配置表）会被跳过——**漏配 `ignoreTable` 导致对无租户列的表追加条件，是接入多租户最常见的报错来源**。

## BlockAttack and IllegalSQL

`BlockAttackInnerInterceptor` 专门拦截**全表更新 / 全表删除**：当 DELETE / UPDATE 语句没有 WHERE 条件时直接抛异常。它是「防误删」的最后一道闸，代价是会拒绝所有无条件的批量更新——这类操作需要显式带一个恒真条件（如 `1=1`）来绕过检查。

`IllegalSQLInnerInterceptor` 比 BlockAttack 更细：检测无 WHERE 的删改、危险的 `OR 1=1` 之类片段等。两者都基于 jsqlparser 解析抽象语法树后判断，比正则匹配可靠。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md)
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)
- [MyBatis Interceptor](/docs/CS/Framework/MyBatis/Interceptor.md)

## References

1. [MyBatis-Plus 插件文档](https://baomidou.com/pages/2976a3/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
