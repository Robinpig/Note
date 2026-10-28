## Introduction

`Wrapper<T>` 是 MyBatis-Plus 的条件构造器，替代手写 `WHERE` 片段。它把「等于 / 大于 / 模糊 / 排序 / 分页尾巴」等操作抽象成链式方法，最终由 `SqlInjector` 拼进 `SqlMethod` 模板（见 [Architecture](/docs/CS/Framework/MyBatis-Plus/Architecture.md)）。

## Wrapper Family

| 类 | 列名写法 | 典型用途 |
| :--- | :--- | :--- |
| `QueryWrapper<T>` | 字符串（如 `"name"`） | 构造查询 / 删除条件 |
| `UpdateWrapper<T>` | 字符串 | 构造更新条件（可带 `set`，不依赖实体） |
| `LambdaQueryWrapper<T>` | 方法引用（`User::getName`） | 类型安全的查询条件 |
| `LambdaUpdateWrapper<T>` | 方法引用 | 类型安全的更新条件 |
| `AbstractWrapper<T>` | — | 上述四者的公共父类，承载比较 / 逻辑方法 |

非 lambda 版本用字符串写列名，重构实体字段时编译器不会报错；lambda 版本用方法引用，编译期就能发现列名写错，但**不支持 Kotlin**（Kotlin 用 `KtQueryWrapper`）。

## Wrappers Factories

静态工厂 `Wrappers`（3.5.18）提供一组便捷构造：

```java
Wrappers.query()                          // new QueryWrapper<>()
Wrappers.query(entity)                    // 以实体非空字段作初始 where
Wrappers.query(User.class)
Wrappers.lambdaQuery()                    // new LambdaQueryWrapper<>()
Wrappers.lambdaQuery(entity)
Wrappers.lambdaQuery(User.class)
Wrappers.update()                         // new UpdateWrapper<>()
Wrappers.update(entity)
Wrappers.lambdaUpdate()
Wrappers.lambdaUpdate(entity)
Wrappers.lambdaUpdate(User.class)
Wrappers.emptyWrapper()                   // 无条件占位（count() / list() 用）
```

`IRepository` 的链式查询（`query()` / `lambdaQuery()`）底层也是这些工厂的封装。

## Common Methods

`AbstractWrapper` 上的常用条件（均以 `condition` 为第一参数，可传 `false` 跳过该条件，便于动态拼接）：

| 方法 | 生成 SQL 片段 | 说明 |
| :--- | :--- | :--- |
| `eq / ne` | `col = ?` / `col <> ?` | 等于 / 不等于 |
| `gt / ge / lt / le` | `col > ?` 等 | 大小比较 |
| `between / notBetween` | `col BETWEEN ? AND ?` | 区间 |
| `like / notLike / likeLeft / likeRight` | `col LIKE ?` | 模糊（左右百分比位置不同） |
| `in / notIn` | `col IN (?,?)` | 集合 |
| `isNull / isNotNull` | `col IS NULL` | 空值 |
| `groupBy / having` | `GROUP BY ...` / `HAVING ...` | 分组 |
| `orderBy / orderByAsc / orderByDesc` | `ORDER BY ...` | 排序 |
| `and / or` | `AND` / `OR`（可嵌套 `Consumer`） | 逻辑连接 |
| `apply(applySql, values...)` | 直接拼接 SQL 片段 | **有注入风险** |
| `last(lastSql)` | 直接拼到 SQL 末尾 | **有注入风险** |
| `select(...)` | `SELECT col1, col2` | 指定查询列（非全部） |
| `set(col, val)`（UpdateWrapper） | `SET col = ?` | 更新赋值，不走实体 |

`apply` 与 `last` 的源码签名（`AbstractWrapper`）：

```java
public Children apply(boolean condition, String applySql, Object... values)
public Children last(boolean condition, String lastSql)
```

两者都允许插入**原生 SQL 片段**。`apply` 支持 `?` 占位（会走预编译参数绑定），但 `last` 是直接字符串拼接到 SQL 末尾。

## SQL Injection Risk

> [!WARNING]
> `last()` 和 `apply()` 是 MP 唯一允许「裸 SQL 片段」的口子，也是唯一可能引入 SQL 注入的地方。任何用户可控输入进入这两个方法都必须参数化：用 `apply("date_format(create_time,'%Y-%m-%d') = {0}", userInput)`（占位符绑定）而非 `apply("... = '" + userInput + "'")`。`last("LIMIT " + userInput)` 同理危险。其余 `eq` / `like` / `in` 等方法一律走 `#{}` 预编译，不存在注入。

这是 MyBatis-Plus 与「查询构造器自动防注入」框架（如 JPA Criteria）的本质区别：MP 把「是否安全」的开关暴露给了 `last` / `apply`，使用者要对拼接负责。

## Example

```java
// 非 lambda：列名是字符串
List<User> list = userMapper.selectList(
    Wrappers.<User>query()
        .eq("status", 1)
        .like("name", "robin")
        .between("age", 18, 30)
        .orderByDesc("create_time")
        .last("LIMIT 10"));          // 裸片段，必须确保 10 是可信值

// lambda：列名是方法引用，编译期校验
LambdaQueryWrapper<User> lw = Wrappers.lambdaQuery()
        .eq(User::getStatus, 1)
        .ge(User::getAge, 18);
List<User> safe = userService.list(lw);
```

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)
- [MyBatis binding](/docs/CS/Framework/MyBatis/binding.md)

## References

1. [MyBatis-Plus 条件构造器文档](https://baomidou.com/pages/10c804/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
