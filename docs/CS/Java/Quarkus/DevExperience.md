## Introduction

Quarkus 把"开发者喜悦"做成了产品特性而非口号：dev 模式改代码即时生效、写测试时数据库容器自动拉起、编码同时测试持续在后台跑。这一页覆盖开发闭环的三个组件——dev mode / Dev UI、Dev Services、测试栈，以及 Quarkus CLI。总览见 [Quarkus](/docs/CS/Java/Quarkus.md)，构建期机制见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)。

## Dev Mode and Live Coding

```shell
./mvnw quarkus:dev        # 或 quarkus dev / ./gradlew quarkusDev
```

dev 模式常驻一个增强后的应用，源码变更触发增量重增强，多数改动**不重启进程**即生效——包括改配置（按 [Config](/docs/CS/Java/Quarkus/Config.md) 的阶段规则，构建期属性变更仍会重新构建）。HTTP 端点旁挂两个内置控制台：

- **Dev UI**（`/q/dev-ui`）：扩展自带的管理界面，3.31 起支持国际化；查看配置、CDI bean、持续测试结果；
- **Dev Services 面板**：当前自动拉起的容器列表及其状态。

## Dev Services

零配置的测试基础设施：classpath 上出现数据源/Kafka/Redis 等扩展而**没有配置连接信息**时，Quarkus 自动用 Testcontainers 拉起对应容器，应用启动时直接连上，测试结束回收。生产构建不带 Dev Services，dev/test profile 外不生效。

3.31 起 Dev Services 底座升级到 **Testcontainers 2**——部分构件坐标与包名变更，直接依赖 Testcontainers 的代码要跟着 `quarkus update` 迁移。常见用法：H2/PostgreSQL 数据库、Kafka（Redpanda）、Keycloak、Mongo、Elasticsearch 等都有对应 Dev Services 实现。

## Continuous Testing

dev 模式下测试不是手动触发的步骤，而是**持续在后台运行**：保存源码即重跑受影响的测试，结果实时显示在控制台和 Dev UI 里。终端里按 `r` 键可在"只跑失败的测试"与"全量重跑"间切换。这个特性自 Quarkus 2.0 引入，配合 [Architecture](/docs/CS/Java/Quarkus/Architecture.md) 的快速重增强，构成 Quarkus 反馈闭环的核心。

## Testing Stack

| 注解 | 语义 |
| :--- | :--- |
| `@QuarkusTest` | JVM 模式下启完整应用（含 Dev Services），支持 `@InjectMock` 做依赖替换 |
| `@QuarkusIntegrationTest` | 对**打好的包**黑盒验证，`-Dnative` 时跑 native 二进制 |
| `@QuarkusMainTest` | 测 `main` 方法入口与 CLI 参数 |

3.31 起测试栈发生两处破坏性变更：**JUnit 5 → JUnit 6**，所有测试工件改名（`quarkus-junit5` → `quarkus-junit`、`quarkus-junit5-component` → `quarkus-junit-component`、`quarkus-junit5-mockito` → `quarkus-junit-mockito`、`io.quarkus.junit5:junit5-virtual-threads` → `io.quarkus.junit:junit-virtual-threads` 等），旧坐标有 relocation 过渡；**Testcontainers 2** 的坐标与包名同步调整。`quarkus update` 能自动处理坐标改名，但 JUnit 6 自身的包名/API 变更（import 语句）不在自动处理范围，需要手动过一遍。

同一版本起 Quarkus 项目要求 **Maven 3.9.0+**，新项目默认使用 `quarkus` 打包类型（替代默认 jar 生命周期，见 [Extensions](/docs/CS/Java/Quarkus/Extensions.md)）。

## Quarkus CLI

```shell
quarkus create app com.example:demo --extension='rest-jackson,hibernate-orm-panache,jdbc-postgresql' --maven
quarkus dev                          # 启动 dev 模式
quarkus extension add smallrye-health
quarkus extension list --installable
quarkus update                       # 升级，含破坏性改名处理
```

不用 CLI 也能走 Maven 插件：`mvn io.quarkus.platform:quarkus-maven-plugin:<version>:create`（注意 groupId 是 `io.quarkus.platform`，老教程里的裸 `io.quarkus:quarkus-maven-plugin` 且版本停在 1.x 的写法已作废），或 code.quarkus.io 生成后解压。`quarkus.platform.version` 决定拉取哪个平台流，新项目默认跟随当前 LTS。

## Links

- [Config](/docs/CS/Java/Quarkus/Config.md)
- [NativeImage](/docs/CS/Java/Quarkus/NativeImage.md)
- [Extensions](/docs/CS/Java/Quarkus/Extensions.md)
- [JUnit](/docs/CS/Java/JUnit.md)
- [Tools](/docs/CS/Java/Tools/Tools.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)

## References

- https://quarkus.io/guides/continuous-testing
- https://quarkus.io/guides/dev-services
- https://github.com/quarkusio/quarkus/wiki/Migration-Guide-3.31
- https://quarkus.io/blog/quarkus-3-31-released/
