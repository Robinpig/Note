## Introduction

MyBatis-Plus 的「增强」很大一部分落在实体注解 + 拦截器（或注入阶段）的组合上。这些特性大多不需要手写 SQL，只要标对注解、配好 `GlobalConfig` 即可。本篇按「主键 / 逻辑删除 / 自动填充 / 乐观锁 / 字段策略 / 类型处理器」归类。

## Primary Key

`@TableId` 标注主键，`type` 取 `IdType` 枚举（3.5.18 源码，5 个取值）：

| `IdType` | 值 | 行为 |
| :--- | :--- | :--- |
| `AUTO` | 0 | 数据库自增；保存前手动设 id 无效，插入成功后回写生成的 id |
| `NONE` | 1 | 未设置（注解里等于跟随全局，全局里约等于 `INPUT`） |
| `INPUT` | 2 | 用户手动输入 id；可配合自动填充插件填充 |
| `ASSIGN_ID` | 3 | 分配 id（number 或 string），**默认实现 `DefaultIdentifierGenerator` 即雪花算法**（since 3.3.0） |
| `ASSIGN_UUID` | 4 | 分配 UUID（string），默认 `UUID.replace("-","")` |

> [!WARNING]
> 老版本里的 `ID_WORKER` / `ID_WORKER_STR` / `UUID` 等枚举值在 3.x 已被 `ASSIGN_ID` / `ASSIGN_UUID` 取代。新项目用 `ASSIGN_ID`（雪花，long/string 通吃）即可，不要再写已删除的枚举名。`AUTO` 务必确认数据库列确实设了自增，否则插入会失败。

## Logic Delete

`@TableLogic` 标在逻辑删除字段上，配合 `TableInfo` 在注入阶段启用逻辑删除：删除变成 `UPDATE ... SET deleted=1 WHERE ... AND deleted=0`，查询自动追加 `AND deleted=0`。

```java
@TableLogic
private Integer deleted;
```

开关细节：
- 字段取值由 `@TableLogic` 的 `value`（未删值，默认 `0`）与 `delval`（已删值，默认 `1`）决定，可在 `GlobalConfig.DbConfig` 设全局默认列名与取值。
- **逻辑删除只在 `TableInfo` 探测到该字段时启用**；漏标或字段类型不对会退化为物理删除。
- 批量删除在逻辑删除下也会生成 `SET delete_user='xxx', deleted=1` 的填充变体（见 [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)）。

## Auto Fill

`@TableField(fill = FieldFill.INSERT / UPDATE / INSERT_UPDATE)` 标注需要自动填充的字段（如创建时间、更新时间、操作人），填充逻辑集中在 `MetaObjectHandler`：

```java
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {
    @Override
    public void insertFill(MetaObject metaObject) {
        strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
    }
    @Override
    public void updateFill(MetaObject metaObject) {
        strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
    }
}
```

接口方法（3.5.18 源码）：
- `void insertFill(MetaObject)` / `void updateFill(MetaObject)`：必须实现。
- `openInsertFill(MappedStatement)` / `openUpdateFill(MappedStatement)`：控制本次是否触发填充，**带 `MappedStatement` 参数是 3.5.x 新增的推荐覆盖点**（旧的 `openInsertFill()` 无参版本已标 `@Deprecated`）。

> [!WARNING]
> 自动填充**只在「按实体对象」的 insert / update 时触发**。`BaseMapper.update(Wrapper)`（只传 Wrapper、实体为 null）的源码注释明确写「此方法无法进行自动填充」——需要填充时必须用 `update(entity, wrapper)` 传入实体。这是由填充机制依赖实体字段决定的，不是配置问题。

## Optimistic Lock

`@Version` 标注乐观锁字段（通常是 `Integer` / `Long` / `LocalDateTime`），并挂载 `OptimisticLockerInnerInterceptor`（`mybatis-plus-extension`，非 jsqlparser）：

```java
@Version
private Integer version;
```

拦截器在 update 时：WHERE 追加 `AND version = ?`（当前值），SET 追加 `version = version + 1`。若受影响行数为 0，说明版本已被别人改过——`OptimisticLockerInnerInterceptor` 会抛异常（早期版本是返回 0，需确认具体版本行为）。**乐观锁只对 `updateById(entity)` / `update(entity, wrapper)` 这类带实体的更新生效**，纯 Wrapper 更新不走版本条件。

## Field Strategy

`@TableField` 的 `update` / `insert` 策略由 `FieldStrategy` 控制字段在为空时是否进入 SQL：常用 `NOT_NULL`（空则不进 SQL，默认行为之一）、`IGNORED`（空也进 SQL，值为 null）、`NEVER`（永远不进 SQL）。全局默认策略在 `GlobalConfig.DbConfig.fieldStrategy` 设置。**误用 `IGNORED` 会把 null 写进库**，是把「不想更新」的字段意外清空的高发原因。

## Type Handler

MP 自带几个常用 `TypeHandler`，免去手写：
- `JacksonTypeHandler` / `FastjsonTypeHandler`：把实体里的对象 / List 字段序列化成 JSON 存进单 varchar / text 列。
- `MybatisEnumTypeHandler`：枚举与数据库值互转（枚举实现 `IEnum` 或字段标 `@EnumValue`）。

这些 handler 在 `GlobalConfig` 里设 `defaultEnumTypeHandler` 或在字段上直接指定 `typeHandler` 即可生效。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)
- [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)
- [MyBatis TypeHandler](/docs/CS/Framework/MyBatis/binding.md)

## References

1. [MyBatis-Plus 注解文档](https://baomidou.com/pages/223848/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
