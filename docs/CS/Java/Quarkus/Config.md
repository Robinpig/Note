## Introduction

Quarkus 全站只有**一套配置系统**（实现是 SmallRye Config，MicroProfile Config 的超集）：`application.properties` 一个入口覆盖框架、扩展、应用自己的全部配置项，键名统一 `quarkus.<extension>.<property>` 前缀。它的特殊之处不在语法，而在与构建期的耦合——大量属性属于构建期配置，改了必须重新构建。总览见 [Quarkus](/docs/CS/Java/Quarkus.md)，阶段划分原理见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)。

## Sources and Profiles

配置源按优先级从高到低：系统属性 → 环境变量 → `.env` 文件 → `application.properties`（含 profile 专属文件）。环境变量名由键名转换而来：`quarkus.http.port` → `QUARKUS_HTTP_PORT`，容器化部署直接注入即可，无需模板渲染。

Profile 用 `%<profile>.` 前缀声明，`%prod.`、`%dev.`、`%test.` 是内置三档，自定义 profile 同样生效：

```properties
# 所有环境生效
quarkus.datasource.jdbc.url=jdbc:postgresql://localhost/db
# 仅 dev / test 生效
%dev.quarkus.datasource.jdbc.url=jdbc:h2:mem:test
%test.quarkus.datasource.jdbc.url=jdbc:h2:mem:test
```

值支持 `${...}` 表达式与环境变量引用，可写默认值 `${PORT:8080}`。

## Config Phases: Build Time vs Run Time

这是 Quarkus 配置最容易踩的坑：不是所有属性都能在运行期改。三类阶段（详见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)）：

| 阶段 | 运行期可否读取 | 改了要不要重新构建 |
| :--- | :--- | :--- |
| `BUILD_TIME` | 否 | 要 |
| `BUILD_AND_RUN_TIME_FIXED` | 是，但固定为构建时快照 | 要 |
| `RUN_TIME` | 是 | 不要 |

典型错法是给 `RUN_TIME` 阶段属性（如 `quarkus.http.port`）做运行期热更新预期，或反过来指望构建期属性（如数据源驱动选择）能在容器里用环境变量切换——后者必须重新构建。每个扩展的参考页都会标注其属性的阶段，这是查配置项的第一信息来源。

3.31 起还清理了一批遗留入口：`System.getProperty("quarkus.http.port")` 不再可用（改用 `ConfigProvider.getConfig().unwrap(SmallRyeConfig.class)` 或注入 `io.quarkus.vertx.http.HttpServer`），旧的 `quarkus.https.port` 系列键被 `quarkus.http.ssl-port` 取代。

## Typed Access: @ConfigProperty and @ConfigMapping

两种注入方式：

- `@ConfigProperty("quarkus.http.port") int port;`——单值，支持默认值与 `Optional<T>`；
- `@ConfigMapping(prefix = "greeting")` 接口方法——一组相关配置一个接口，**映射关系构建期校验**，拼错键名编译期就报错，且接口方法可带 `@WithDefault`。

配置类与扩展配置共用同一套阶段标注，所以 `@ConfigMapping` 接口也能声明自己是构建期配置。

## Security and TLS Defaults Worth Knowing

- **TLS 默认只开 v1.3**（3.31 起）：TLS registry 默认协议集改为仅 TLS 1.3，需要兼容旧客户端得显式配置；
- **TLS registry 的后量子密码**（3.39）：支持在 TLS registry 中启用后量子密钥交换算法，属"现在就该知道、将来必须迁移"的一类变更；
- OIDC 扩展 3.31 起支持 custom DPoP nonce provider、rich authorization requests 等 OAuth 2.1 相关能力，安全相关配置面在持续扩大。

## Links

- [Architecture](/docs/CS/Java/Quarkus/Architecture.md)
- [Extensions](/docs/CS/Java/Quarkus/Extensions.md)
- [Persistence](/docs/CS/Java/Quarkus/Persistence.md)
- [DevExperience](/docs/CS/Java/Quarkus/DevExperience.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)
- [Container](/docs/CS/Container/Container.md)

## References

- https://quarkus.io/guides/config-reference
- https://quarkus.io/guides/config
- https://github.com/quarkusio/quarkus/wiki/Migration-Guide-3.31
- https://quarkus.io/blog/quarkus-3-40-released/
