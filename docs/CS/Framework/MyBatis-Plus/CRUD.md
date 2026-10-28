## Introduction

MyBatis-Plus 把单表 CRUD 收敛到两层接口：**`BaseMapper<T>`**（DAO 层，贴近 SQL 一次操作一张表）和 **`IService<T>`**（业务层，在 `BaseMapper` 之上提供批量与事务封装）。`IService` 继承自 `IRepository`，后者承载了绝大多数 CRUD 默认实现，前者只额外加了 4 个带默认批次大小的批处理方法。

所有方法最终都路由到 `BaseMapper` 对应方法（见 [Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md) 的 statement id 映射）。

## BaseMapper

`BaseMapper<T>` 的方法按操作归类（3.5.18 源码，方法名即注入的 `SqlMethod` id）：

| 操作 | 方法 | 说明 |
| :--- | :--- | :--- |
| 插入 | `int insert(T entity)` | 选择非空字段插入 |
| 删除 | `int deleteById(Serializable / T)` | 按主键删 |
| 删除 | `int deleteByMap(Map)` / `int delete(Wrapper)` | 按 Map / 条件删 |
| 删除 | `int deleteByIds(Collection)` | 按 id 列表批量删（**3.5.7 起**，替代已弃用的 `deleteBatchIds`） |
| 修改 | `int updateById(T)` / `int update(T, Wrapper)` / `int update(Wrapper)` | 按 id 改 / 按条件改 / 仅 Wrapper 改（无自动填充） |
| 查询 | `T selectById(Serializable)` / `List<T> selectByIds(Collection)` | 按 id 查（**3.5.8 起** `selectByIds` 替代已弃用的 `selectBatchIds`） |
| 查询 | `List<T> selectList(Wrapper)` / `List<Map> selectMaps(Wrapper)` / `<E> List<E> selectObjs(Wrapper)` | 列表 / Map 列表 / 首列对象列表 |
| 查询 | `Long selectCount(Wrapper)` | 计数 |
| 查询 | `T selectOne(Wrapper)` / `boolean exists(Wrapper)` | 查一条 / 是否存在 |
| 分页 | `default <P extends IPage<T>> P selectPage(P, Wrapper)` / `selectMapsPage` | 分页（需配合 [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md) 的分页拦截器才生效） |
| 游标 | `Cursor<T> selectWithCursor(Wrapper)` | 流式查询，必须在事务内或手动管理 `SqlSession` |
| 批量 | `List<BatchResult> insert(Collection)` / `updateById(Collection)` / `insertOrUpdate(Collection)` | **3.5.7 起**，基于 `MybatisBatch`，不走 `IService` 的事务批处理 |

> [!WARNING]
> `selectOne` 的实现是 `selectList(wrapper, new RowBounds(0, 2))` 后判断 `size`：**结果多于 1 条且 `throwEx=true`（默认）会抛 `TooManyResultsException`**；`size=0` 返回 `null`。它不是数据库层面的 `LIMIT 1`，只是取前两行在内存里判断，需要严格单条时应自己 `wrapper.last("LIMIT 1")`。

## IService and IRepository

`IRepository<T>` 提供所有单条 / 列表 / 分页的默认实现，全部委托给 `getBaseMapper()`。`IService<T> extends IRepository<T>`，只补了 4 个批处理：

| 方法 | 默认批次大小 | 事务 | 说明 |
| :--- | :--- | :--- | :--- |
| `saveBatch(Collection)` | `DEFAULT_BATCH_SIZE` = **1000** | `@Transactional` | 批量插入，底层用 `SqlSession` BATCH 模式 |
| `saveOrUpdateBatch(Collection)` | 1000 | `@Transactional` | 逐条判断 id 是否存在 |
| `updateBatchById(Collection)` | 1000 | `@Transactional` | 批量按 id 改 |
| `removeBatchByIds(Collection)` | — | `@Transactional` | 默认直接转 `removeByIds` |

`DEFAULT_BATCH_SIZE` 定义在 `IRepository` 里，值等于 `Constants.DEFAULT_BATCH_SIZE = 1000`（源码常量，非配置项）。`saveBatch` 的「批量」是 **JDBC batch**（同一个 `SqlSession` 反复 `addBatch` 再 `flush`），不是一次 `INSERT ... VALUES (...),(...)` 的多值插入——这意味着它减少的是网络往返，SQL 仍是单条 prepare。

### saveOrUpdate

`IRepository.saveOrUpdate(T)` 的逻辑：取 `TableInfo` 主键属性值，若为空或 `selectById` 查不到则 `insert`，否则 `updateById`。`BaseMapper.insertOrUpdate(Collection)` 则基于 `MybatisBatch` 在批处理内做同样的判断（3.5.7 起），适合大批量 upsert 且不想为每批开事务的场景。

### Chain Wrapper

`IRepository` 还提供链式调用，避免反复 `new QueryWrapper<>()`：

```java
// 等价 query().eq("status", 1).list()
list(Wrappers.<User>query().eq("status", 1).getWrapper());

// 链式：query().eq("age", 18).one()
User u = query().eq("name", "robin").one();
// lambda 链式：lambdaQuery().eq(User::getAge, 18).list()
List<User> list = lambdaQuery().eq(User::getAge, 18).list();
```

普通 `query()` 返回 `QueryChainWrapper`，lambda 版返回 `LambdaQueryChainWrapper`（注意 lambda 版不支持 Kotlin）；另有 `ktQuery()` / `ktUpdate()` 供 Kotlin 使用。

## Logic Delete in SQL

开启 `@TableLogic` 后，同一个 `deleteById` 在注入阶段就换成逻辑删除模板。源码里给出的实际生成 SQL：

```
普通删除:   DELETE FROM user WHERE id IN ( ? , ? )
逻辑删除:   UPDATE user SET deleted=1 WHERE id IN ( ? , ? ) AND deleted=0
逻辑删除(填充): UPDATE user SET delete_user = 'xxx', deleted=1 WHERE id IN ( ? , ? ) AND deleted=0
```

查询时 MP 会自动在 WHERE 后追加 `AND deleted=0`，所以逻辑删除字段的取值（0/1 或自定义）由 `@TableLogic` 的 `value` / `delval` 决定，且**必须在 `TableInfo` 里探测到该字段才会启用**（漏标注解则退化为物理删除）。

## Deprecation Migration

3.5.7 / 3.5.8 做了一批命名收敛，旧方法标 `@Deprecated` 但仍在，只是转发到新方法：

| 旧（弃用） | 新 | 变化点 |
| :--- | :--- | :--- |
| `deleteBatchIds` | `deleteByIds` | 同时支持 id 与实体列表，新增 `useFill` 参数控制逻辑删除填充 |
| `selectBatchIds` | `selectByIds` | 同上，且新增 `selectByIds(Collection, ResultHandler)` 流式重载 |
| `selectPage` / `selectMapsPage`（MappedStatement 模板） | 改为 `BaseMapper` 的 `default` 方法 | `selectPage` 不再作为注入 statement，而是 `default` 调 `selectList(page, wrapper)` |
| `SqlMethod.SELECT_ONE` / `SELECT_PAGE` / `SELECT_MAPS_PAGE` | — | 标 `@Deprecated`，查询统一走 `SELECT_LIST` 模板 + 内存分页/截断 |

> [!WARNING]
> `selectPage` 在 3.5.x 已不是独立注入的 `MappedStatement`，而是 `BaseMapper` 的 `default` 方法，内部调 `selectList(IPage, Wrapper)`。**分页是否真正改写 SQL 完全取决于分页拦截器是否挂载**——裸用 `selectPage` 而不挂 `PaginationInnerInterceptor` 只会拿到未分页的全量 + 内存截断，等价于 `RowBounds` 内存分页。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md)
- [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)
- [Wrapper](/docs/CS/Framework/MyBatis-Plus/Wrapper.md)
- [MyBatis Executor](/docs/CS/Framework/MyBatis/Executor.md)

## References

1. [MyBatis-Plus CRUD 接口文档](https://baomidou.com/pages/49cc81/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
