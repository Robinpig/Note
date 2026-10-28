## Introduction

Quarkus 的扩展（extension）既是它的装配单元，也是 augmentation 的执行单元：你在 `pom.xml` 里加的每一个 `io.quarkus:quarkus-*` 依赖，都是一段"构建期逻辑 + 运行期逻辑"的打包。理解扩展模型就理解了 Quarkus 为什么能把工作前移到构建期，以及为什么改一个配置属性有时需要重新构建。前置概念见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md)，总览见 [Quarkus](/docs/CS/Java/Quarkus.md)。

## Anatomy of an Extension

一个扩展由两个 Maven 构件组成，版本号始终相同：

| 构件 | 阶段 | 内容 |
| :--- | :--- | :--- |
| `quarkus-<name>-deployment` | 构建期 | Build Step、条件判定、字节码录制，**不进运行产物** |
| `quarkus-<name>` | 运行期 | recorder、CDI bean、配置类，**不打进 deployment** |

部署构件只在构建期出现在 classpath 上，这是"运行时只加载真正用到的类"的组织保障。开发者日常依赖的是运行期构件，部署构件由 Quarkus 插件自动拉入。

## BuildItem: 构建期的消息总线

Build Step 之间不直接调用，而是通过 **BuildItem** 通信——producer 产出、consumer 消费，顺序由依赖关系推导。这带来两个工程后果：

- BuildItem 必须**不可变**，producer/consumer 模型无法为原地修改正确排序；
- 条件装配成为常态：某个 Build Step 只在"classpath 上存在某类"或"某配置项被设置"时才产出结果，这正是 Quarkus "零配置"的实现方式——不是运行时猜，是构建期确定。

字节码录制（recorder）负责把构建期决策翻译成运行期可执行的初始化代码，细节见 [Architecture](/docs/CS/Java/Quarkus/Architecture.md) 的 Bytecode Recording 一节。

## ArC: Build-Time CDI

Quarkus 的 CDI 实现叫 **ArC**，与 Weld 的根本差异是解析时机：bean 定义在 augmentation 阶段注册并完成验证，容器在 Static Init 阶段才启动。因此：

- 增强阶段**拿不到 bean 实例**（容器还没起），这是非法操作；
- `@Record(RUNTIME_INIT)` 的 Build Step 里可以安全假设 CDI 容器已完全初始化；
- 缺少 bean、歧义依赖这类错误在**构建期**暴露，而不是启动时；
- **Synthetic bean** 的属性由扩展指定而非从 Java 类派生，容器不控制其实例化，故不支持依赖注入与拦截器，需扩展自行提供服务。

ArC 也解释了为什么 Quarkus 应用的 bean 数量历史上会撞 class file 上限——3.31 重构了合成 bean 的生成方式，超大应用的 bean 数不再受此限制。

## Platform BOM and Pinned Components

应用通过 `io.quarkus.platform:quarkus-bom` 锁定整套组件版本，Quarkus 平台对成员做统一验证。下表是 **3.40.1 LTS 平台 BOM 的实际内容**（2026-10 从 Maven Central 的 POM 提取）：

| 组件 | 3.40.1 版本 |
| :--- | :--- |
| Hibernate ORM | 7.4.9.Final |
| Hibernate Reactive | 3.4.2.Final |
| Vert.x | 4.5.34 |
| Netty | 4.1.138.Final |
| Jackson | 2.21.7 |
| RESTEasy（Quarkus REST 底座） | 6.2.19.Final |

组件升级跟着平台走：3.31 带入 Hibernate ORM 7.2 / Reactive 3.2 / Search 8.2，3.37 带入 Hibernate ORM 7.4，Jackson 3 则留给 Quarkus 4。想单独验证某个平台成员的版本，直接查 BOM POM 比查文档可靠。

## Ecosystem Beyond the Core

平台成员之外还有两层生态：

- **Quarkiverse**：社区扩展的托管地，按需 `quarkus extension add` 安装；
- **Platform 成员组件**：3.40 LTS 平台附带 Camel Quarkus 3.40.0、Quarkus CXF 3.40.0、Quarkus LangChain4j 1.13.3、Quarkus MCP Server 2.0.1、Debezium 3.6.3.Final、Quarkus Operator SDK 7.8.0、Quarkus Vault 4.10.0 等——这些第三方项目各自发版，由平台负责兼容矩阵。

治理上，Quarkus 已从"Red Hat 单一厂商主导"迁入 **Commonhaus 基金会**，与 RESTEasy、Micronaut 同源；商业支持走 Red Hat build of Quarkus（RHBQ）与 IBM 渠道，3.33 LTS 起两家均在支持矩阵里。

## Extension-Based Modularity

3.37 引入的 **extension-based modularity** 把"按扩展裁切应用"做成了正式能力：扩展可以声明自己的模块边界，未使用的扩展代码连带其传递依赖从产物中剔除。它与 3.35 的 **JAR tree-shaking**（JVM 模式产物体积瘦身）是同一思路的两端——一个管模块边界，一个管产物裁剪，目标都是"运行时不加载用不到的类"。

## Tooling: CLI, Update, New Packaging

- **Quarkus CLI**：`quarkus create app`、`quarkus dev`、`quarkus extension add/list`、`quarkus update`。`quarkus update` 能处理 BOM 升级、破坏性改名（如 3.31 的 `quarkus-junit5` → `quarkus-junit`）等重活，跨大版本升级的第一站。
- **新 `quarkus` Maven packaging**（3.31 起，新项目默认）：取代默认 jar 生命周期，砍掉大多数场景用不到的 goal，构建显著加快；存量项目可选迁移，`quarkus update` 不会自动替你换。
- 3.31 起 Quarkus 项目要求 **Maven 3.9.0+**。

## Links

- [Architecture](/docs/CS/Java/Quarkus/Architecture.md)
- [Config](/docs/CS/Java/Quarkus/Config.md)
- [REST](/docs/CS/Java/Quarkus/REST.md)
- [Persistence](/docs/CS/Java/Quarkus/Persistence.md)
- [DevExperience](/docs/CS/Java/Quarkus/DevExperience.md)
- [Quarkus](/docs/CS/Java/Quarkus.md)

## References

- https://quarkus.io/guides/writing-extensions
- https://quarkus.io/blog/quarkus-3-40-released/
- https://quarkus.io/blog/quarkus-3-31-released/
- https://repo1.maven.org/maven2/io/quarkus/platform/quarkus-bom/3.40.1/quarkus-bom-3.40.1.pom
- https://github.com/quarkusio/quarkus/wiki/Migration-Guide-3.31
