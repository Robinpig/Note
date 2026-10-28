## Introduction

MyBatis-Plus 自带反向代码生成器，从数据库表生成 `entity` / `mapper` / `service` / `controller` / `xml`。3.5.x 起统一为 **`FastAutoGenerator`**，取代老的 `AutoGenerator` + `Velocity` 模板变量的写法：`FastAutoGenerator` 用流式 Builder，表名、策略、包结构都在链上配置，不再需要单独的 `vm` 模板文件即可生成标准代码。

## FastAutoGenerator

入口是静态工厂 `create`，之后是一组 Builder 风格的配置方法（3.5.18 源码 `FastAutoGenerator`）：

| 方法 | 入参 | 作用 |
| :--- | :--- | :--- |
| `create(url, user, password)` | `String, String, String` | 用 JDBC 连接信息建生成器 |
| `create(DataSourceConfig.Builder)` | builder | 自定义数据源（连接池、schema 等） |
| `dataSourceConfig(Consumer<DataSourceConfig.Builder>)` | — | 数据源细节 |
| `globalConfig(Consumer<GlobalConfig.Builder>)` | — | 作者、输出目录、是否 swagger |
| `packageConfig(Consumer<PackageConfig.Builder>)` | — | 父包名、各层子包名 |
| `strategyConfig(Consumer<StrategyConfig.Builder>)` | — | 含哪些表、命名策略、lombok 等 |
| `injectionConfig(Consumer<InjectionConfig.Builder>)` | — | 自定义注入变量 |
| `templateConfig(Consumer<TemplateConfig.Builder>)` | — | 控制生成哪些文件 |
| `templateEngine(AbstractTemplateEngine)` | — | 指定模板引擎 |

## Template Engine

`mybatis-plus-generator` 的 POM 同时带 `velocity-engine-core`、`freemarker`、`beetl`、`enjoy` 四种模板引擎依赖，但都是可选的——`FastAutoGenerator` 默认使用 Velocity。`templateEngine(...)` 可切换：

```java
.templateEngine(new FreemarkerTemplateEngine())   // 或 Beetl / Enjoy
```

不调用 `templateEngine` 时用内置 Velocity 默认值；若项目排除了 Velocity 依赖又没显式指定引擎，会报 `ClassNotFound`。

## Example

```java
FastAutoGenerator.create("jdbc:mysql://localhost:3306/demo", "root", "pwd")
    .globalConfig(b -> b
        .author("robin")
        .outputDir("./src/main/java")
        .commentDate("yyyy-MM-dd")
        .enableSwagger()                  // 生成 swagger 注解（需引入 springfox，注意与 SB3 兼容）
    )
    .packageConfig(b -> b
        .parent("com.example.demo")
        .entity("entity")
        .mapper("mapper")
        .service("service")
        .serviceImpl("service.impl")
        .controller("controller")
        .xml("mapper.xml")
    )
    .strategyConfig(b -> b
        .addInclude("user", "order")      // 只生成这两张表
        .addTablePrefix("t_")             // 去掉表前缀后做类名
        .entityBuilder()
            .enableLombok()
            .enableTableFieldAnnotation()  // 字段上带 @TableField
            .logicDeleteColumnName("deleted")
        .controllerBuilder()
            .enableRestStyle()
        .mapperBuilder()
            .enableMapperAnnotation()
            .enableBaseResultMap()
    )
    .execute();
```

`strategyConfig` 内部再按 `entityBuilder()` / `controllerBuilder()` / `mapperBuilder()` / `serviceBuilder()` 分组细化；`addInclude` 指定表、`addTablePrefix` 去掉表前缀后推导类名。生成结果默认 `mapper` 接口继承 `BaseMapper<T>`，`service` 继承 `IService<T>`、`serviceImpl` 继承 `ServiceImpl<M, T>`——即生成的代码直接享受 [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md) 的所有能力。

> [!WARNING]
> 生成器只是「脚手架」：它生成的是**带 `@TableName` / `@TableId` 标注的实体和继承 `BaseMapper`/`IService` 的接口**，不会替你写业务逻辑，也不会替你决定主键策略（`IdType`）和逻辑删除字段——这些仍需在生成后按 [Features](/docs/CS/Framework/MyBatis-Plus/Features.md) 调整。

## Links

- [MyBatis-Plus](/docs/CS/Framework/MyBatis-Plus/MyBatis-Plus.md)
- [CRUD](/docs/CS/Framework/MyBatis-Plus/CRUD.md)
- [Features](/docs/CS/Framework/MyBatis-Plus/Features.md)

## References

1. [MyBatis-Plus 代码生成器文档](https://baomidou.com/pages/981406/)
2. [MyBatis-Plus Source (GitHub)](https://github.com/baomidou/mybatis-plus)
