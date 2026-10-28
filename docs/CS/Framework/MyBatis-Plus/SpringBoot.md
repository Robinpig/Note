## Introduction

MyBatis-Plus 通过 Spring Boot starter 做自动装配：自动创建 `SqlSessionFactory`（用 MP 自己的 `MybatisSqlSessionFactoryBuilder`）、扫描 Mapper、并把容器里的 `MybatisPlusInterceptor` Bean 挂到插件链上。业务侧只需要在配置里声明数据源和 Mapper 位置，再写实体与 Mapper 接口即可。

## Starters

MP 3.5.18 同时发布三个 starter，按 Spring Boot 大版本选：

| starter | 适用 Spring Boot | 说明 |
| :--- | :--- | :--- |
| `mybatis-plus-boot-starter` | Spring Boot **2** | 老 starter，已不推荐新项目使用 |
| `mybatis-plus-spring-boot3-starter` | Spring Boot **3** | 当前主流 |
| `mybatis-plus-spring-boot4-starter` | Spring Boot **4** | 2026 新增；底层 `mybatis-plus-spring` 依赖 `mybatis-spring` **4.1.0**（Java 17、Spring Framework 7.0.8） |

> [!WARNING]
> **不要同时引入 `mybatis-plus-*-starter` 和 `mybatis-spring-boot-starter`**：两者都会尝试装配 `SqlSessionFactory`，版本不一致时会冲突。MP starter 自身 transit 拉入 `mybatis-spring` 与 `mybatis`，让它统一管理依赖版本即可。同理，升级 MyBatis 到 3.6.0 前要先确认 MP 是否发布了兼容版本（见 [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md) 的版本基线）——MP 编译锁定的是 `mybatis` 3.5.19。

## Auto Configuration

starter 的核心自动配置类是 `MybatisPlusAutoConfiguration`（SB3 / SB4 走 `AutoConfiguration` 注册机制，SB2 走 `spring.factories`）。它做的事情：

1. 用 `MybatisSqlSessionFactoryBuilder` 构建 `SqlSessionFactory`，把 `mybatis-plus.configuration.*` 与 `mybatis-plus.global-config.*` 灌进 `Configuration` / `GlobalConfig`。
2. 注册 `SqlSessionTemplate`。3. 扫描 `mapperLocations` 下的 xml，并把标注 `@Mapper` 或 `@MapperScan` 覆盖的接口注入容器。
4. 若容器里存在 `MybatisPlusInterceptor` Bean，自动加入 `Configuration` 的插件链——所以[Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md) 里的拦截器只要声明成 `@Bean` 就会被启用，无需手动挂。

## Common Properties

配置前缀是 `mybatis-plus`（不是 MyBatis 原生的 `mybatis`）：

```yaml
mybatis-plus:
  mapper-locations: classpath*:/mapper/**/*.xml
  type-aliases-package: com.example.demo.entity
  type-handlers-package: com.example.demo.handler
  configuration:
    map-underscore-to-camel-case: true     # MyBatis Configuration 设置
    cache-enabled: false
  global-config:
    banner: false                          # 关闭启动 banner
    db-config:
      id-type: assign_id                   # 全局主键策略（IdType 名，小写）
      table-prefix: t_                     # 全局表前缀
      logic-delete-field: deleted          # 全局逻辑删除字段名（3.3.0+，表里有统一字段时省去逐表 @TableLogic）
      logic-not-delete-value: 0
      logic-delete-value: 1
```

关键点：
- `global-config.db-config.logic-delete-field` 是**全局逻辑删除字段名**（since 3.3.0）：设了之后，所有实体里叫 `deleted` 的字段自动按逻辑删除处理，不必每张表都标 `@TableLogic`。
- `global-config.db-config.id-type` 设全局主键策略；实体上 `@TableId(type=...)` 可逐表覆盖。
- `configuration.map-underscore-to-camel-case` 透传给 MyBatis `Configuration`，行为见 [MyBatis ResultSetHandler](/docs/CS/Framework/MyBatis/ResultSetHandler.md)。

## Mapper Scan

```java
@MapperScan("com.example.demo.mapper")   // 放在启动类或配置类上
@SpringBootApplication
public class DemoApplication {}
```

或用 `@Mapper` 标在每个 Mapper 接口上。`@MapperScan` 覆盖的接口会被 MyBatis 动态代理，且因为继承了 `BaseMapper<T>`，自动拥有 [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md) 全部能力。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [Interceptor](/docs/CS/Framework/MyBatis-Plus/Interceptor.md)
- [Features](/docs/CS/Framework/MyBatis-Plus/Features.md)
- [MyBatis-Spring](/docs/CS/Framework/MyBatis/MyBatis-Spring.md)

## References

1. [MyBatis-Plus Spring Boot 快速开始](https://baomidou.com/pages/226c21/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
