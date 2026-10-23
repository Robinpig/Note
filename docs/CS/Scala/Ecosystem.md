## Introduction

Scala 生态的最大特点不是库多，而是**分阵营**：同一件事通常有两套互不兼容的实现，一套属于 Typelevel 体系（cats 为基础），一套属于 ZIO 体系（自带运行时），再往外才是 Akka/Pekko 这套 actor 世界。选了一个阵营之后，HTTP、JSON、数据库、流、测试基本就得跟着选同一套——跨阵营要用互操作库，而这层互操作是有成本的。

本篇按职能分层给出选型地图，并明确写出三条现实判断：**选阵营的代价**、**Akka 许可变更带来的分叉**、以及**库作者的发布基线选哪条线**。并发与效应的抽象在 [函数式效应系统](/docs/CS/Scala/Effects.md)，actor 模型在 [并发](/docs/CS/Scala/Concurrency.md)，构建与发布工具在 [工具链](/docs/CS/Scala/Tooling.md)。

## Two Camps and One Actor World

| 阵营 | 核心 | 风格 | 代表库 |
| :--- | :--- | :--- | :--- |
| **Typelevel** | cats + cats-effect | 类型类驱动，库小而专 | fs2、http4s、doobie、circe、munit |
| **ZIO** | ZIO 运行时 | 电池全含 | zio-streams、zio-http、zio-json、zio-config、zio-test |
| **Akka / Pekko** | actor + streams | 面向对象 + 消息驱动 | akka-actor-typed、Akka Streams、Akka HTTP、Alpakka |
| **Play** | MVC web 框架 | 传统 Web 框架 | Play Framework（可运行在 Akka/Pekko 之上） |

选阵营的判据很实际：

- 团队是否愿意接受 monad 与类型类的学习成本？不愿意就选 ZIO（API 更集中）或 Play（更传统）；
- 是否需要"一套库覆盖所有需求"（配置、日志、测试、指标）？需要就选 ZIO；
- 是否要与其他 Typelevel 项目深度互操作？需要就选 cats-effect；
- 是否需要有状态分布式（集群分片、事件溯源）？这类需求 Akka/Pekko 目前仍是完成度最高的答案。

跨阵营的桥是 `zio-interop-cats`（ZIO ↔ cats-effect 类型类），它让同一份代码可以在两种 `F[_]` 上工作，代价是要同时理解两套语义。

## The Akka License Fork

这是 Scala 生态近年最重要的事件，任何选型都必须先查许可：

- **Akka 自 2022-10 起改用 BSL 1.1**（Business Source License）。开发与测试免费，**生产使用需要 Lightbend 的商业授权**；每个版本在发布满三年后自动转为 Apache-2.0（转换日期写在该版本的 LICENSE 文件里，因此不同补丁版本的转换时间不同）。
- **Apache Pekko** 是从 Akka 2.6.x（许可变更之前）分叉出来的 Apache-2.0 项目，是最接近的开源替代，包名从 `akka.*` 换成 `org.apache.pekko.*`。

实际影响：新项目要么接受 Akka 的商业条款，要么用 Pekko；已经用了 Akka 的项目要检查自己用的版本落在哪个许可窗口内。这条判断与技术实现无关，但往往是决定性的。

## Libraries by Function

| 职能 | Typelevel 侧 | ZIO 侧 | 其他 |
| :--- | :--- | :--- | :--- |
| JSON | circe（编译期派生） | zio-json | upickle、jsoniter-scala（性能向） |
| HTTP 服务端 | http4s | zio-http | Play、Akka HTTP / Pekko HTTP |
| HTTP 客户端 | http4s-client | zio-http | **sttp**（跨效应系统的客户端，支持 ZIO/cats/Future 多种后端） |
| 数据库 | doobie（JDBC 之上的函数式封装）、skunk（Postgres） | zio-sql | Slick、Quill（编译期 SQL） |
| 流 | fs2 | zio-streams | Akka Streams / Pekko Streams |
| API 契约 | **tapir**（从类型生成 OpenAPI 与服务端/客户端代码，后端可选 http4s/ZIO/Akka） | — | — |
| Kafka | fs2-kafka | zio-kafka | Alpakka / Pekko connectors |
| 配置 | pureconfig | zio-config | — |
| 日志 | log4cats（cats-effect 上的门面） | zio-logging | slf4j 直接用 |

**tapir** 值得单独提：它把"API 的契约"与"用什么后端跑"解耦——同一份 endpoint 定义可以生成 OpenAPI 文档、服务端路由与客户端函数，分别绑定到 http4s、ZIO HTTP 或 Akka HTTP。这是 Scala 类型系统能做到而其他语言通常靠代码生成来做的事。

**sttp** 同理：一个客户端定义，后端可以是 `Future`、`IO`、ZIO 或者纯同步。

## Data Infrastructure

Scala 在大数据领域的存在感主要来自历史：

- **Apache Spark** 用 Scala 编写，其 RDD/DataFrame API 的原生形态就是 Scala；如今 Java 与 Python API 使用更广，但内核仍是 JVM 上的 Scala 代码，见 [Spark](/docs/CS/Framework/Spark/Spark.md)；
- **Apache Flink** 同样主要用 Java/Scala；
- **Apache Kafka** 早期核心代码用 Scala 编写（现主要 Java），见 [Kafka](/docs/CS/MQ/Kafka/Kafka.md)；
- 在这一类框架里写 Scala 作业时，**要留意框架自带的 Scala 版本**——Spark 通常固定在一个 Scala 2.12/2.13 上，跨版本要找对应 artifact。

这条约束很实际：大数据生态往往是"最后一个还在用 Scala 2"的地方，而应用代码已经在 Scala 3 上，两者不能混。

## Publishing Baseline

如果你发布库，版本选择有明确答案：

- **构建基线用 Scala LTS（3.9）**——官方明确推荐给库作者，因为它的兼容窗口最长，且消费者无论用 3.9 还是更新的 Next 版本都能用；
- **应用可以用 Scala Next（3.10）**——拿到最新特性与修复；
- **3.3 LTS 只在消费者被卡住时才用**——它在 3.9.0 之后继续维护一年，但后续 backport 会变少；事实层面，在 3.9 发布时仍有约 56% 的 Scala 3 库用 3.3 LTS 发布，所以短期内不可能完全放弃它。

发布前跑 [MiMa](/docs/CS/Scala/Tooling.md) 做二进制兼容检查，并且给仓库加一个针对 nightly/RC 的 CI 任务。

## Links

- [Scala](/docs/CS/Scala/Scala.md)
- [函数式效应系统](/docs/CS/Scala/Effects.md)
- [并发](/docs/CS/Scala/Concurrency.md)
- [工具链](/docs/CS/Scala/Tooling.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

- [Scaladex — Scala library index](https://index.scala-lang.org/)
- [Typelevel projects](https://typelevel.org/projects/)
- [ZIO ecosystem](https://zio.dev/ecosystem/)
- [Apache Pekko](https://pekko.apache.org/)
- [Akka license FAQ](https://akka.io/bsl-license-faq)
- [Scala Toolkit](https://docs.scala-lang.org/scala3/book/toolkit.html)
