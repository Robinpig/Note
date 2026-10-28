## Introduction

Gradle 用**任务有向无环图**取代了 Maven 的固定生命周期。它不预设"构建要做哪几步"，而是让你声明"有哪些任务、谁依赖谁"，然后由 Gradle 自己算出执行顺序。这个自由度是它构建速度优势的来源，也是它学习曲线陡峭的根源。

要理解 Gradle，抓住三件事就够了：

**第一，它是两阶段执行模型。** configuration phase 决定"要做什么"，execution phase 真正"做"。两阶段之间由任务图连接。这个划分解释了大量行为——为什么配置阶段读文件是反模式、为什么配置缓存只缓存前半段、为什么任务注册必须惰性。

**第二，它的性能来自跳过而非加速。** 三层机制——增量构建（跳过未变任务）、Configuration Cache（跳过配置阶段）、Build Cache（跨机器复用输出）——都是"不做事"而非"做得更快"。这是与 Maven 那种"每次都完整重跑一遍"最本质的差别。

**第三，版本演进非常激进。** 每 6–8 周一个 minor，major 版本会同时动 JVM 基线、Kotlin 版本、Groovy 版本和工具默认版本。**大版本升级的主要风险往往不在 Gradle 本身，而在它顺带升级的那些工具**（Checkstyle、PMD、JUnit、JGit）。

这个子树按"架构 → 任务 → 依赖 → 版本目录 → 多项目 → 性能 → 发布安全 → 排障"的顺序展开。

## Reading Path

**第一次接触 Gradle**，按顺序读 [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md) → [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md) → [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)。这三篇构成 Gradle 的骨架：两阶段模型、任务与输入输出、配置与依赖。

**正在解决具体问题**，直接查对应分册：

| 症状 | 去读 |
| :--- | :--- |
| 任务每次都重跑 | [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md) |
| 配置缓存不生效 / 报不兼容 | [Performance](/docs/CS/BuildTool/Gradle/Performance.md) |
| `NoSuchMethodError` / 依赖版本不对 | [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md) |
| 版本号散落各处 | [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md) |
| 多项目配置复用 | [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md) |
| 发布到 Central 失败 | [Publishing and Security](/docs/CS/BuildTool/Gradle/Publishing_and_Security.md) |
| 任何报错 | [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md) |

## Core Concepts

- **两阶段执行** —— configuration（决定做什么）→ task graph → execution（照做）。配置阶段里的昂贵操作每次都会重做；
- **任务图** —— `dependsOn` 构成 DAG，Gradle 自动拓扑排序；`mustRunAfter` 只约束顺序不引入依赖；
- **输入输出声明** —— `@Input` / `@OutputFile` / `@Classpath` 等注解决定 up-to-date 判定与缓存键；
- **惰性注册** —— `tasks.register` + `configureEach` 是正确写法；`getByName` / `withType` 不带 `configureEach` 会破坏惰性（社区称 "Configuration Bomb"）；
- **Configuration Cache** —— 缓存配置阶段产物；Gradle 9 起是推荐模式，目标 Gradle 11 默认开启；
- **Build Cache** —— 按输入哈希缓存任务输出，可跨机器、跨分支复用；
- **daemon** —— 常驻 JVM 进程，缓存构建模型；**jvmargs 是匹配键**，改了会重启；
- **api vs implementation** —— `api` 出现在公开 API 签名里、传递给消费者；`implementation` 仅内部使用、消费者的编译 classpath 上没有；
- **仲裁选最高版本** —— 与 Maven 的"最近路径优先"完全相反，迁移时最容易翻车；
- **version catalog** —— `gradle/libs.versions.toml` 集中管理坐标与版本，类型安全访问器；
- **convention plugin** —— 现代多项目配置复用的推荐方式，替代 `subprojects {}`；
- **依赖校验** —— `gradle/verification-metadata.xml` 同时支持 checksum 与 signature，是 Gradle 相对 Maven 的明显优势。

## Version Baseline

| 组件 | 版本 | 日期 | 状态 |
| :--- | :--- | :--- | :--- |
| Gradle | `9.8.2` | 2026-10-19 | **当前版** |
| Gradle | `9.8.1` | 2026-10-13 | 修 3 个高危安全漏洞，**建议至少升到这个** |
| Gradle | `9.8.0` | 2026-09-24 | 支持 Java 27、Maven 镜像复用 |
| Gradle | `9.9.0-milestone-2` | 2026-09-18 | 下一版本线预发布 |
| Gradle 嵌入 Kotlin | 2.4.0（9.7.0 起） | | 语言版本 2.2 |
| Gradle 嵌入 Groovy | 4.0.33（9.8.0 起） | | 插件需用 Groovy 4.x |
| AGP（Android） | 9.0 – 9.5.0-alpha02 | | 测试范围 |

**运行 Gradle 需要 JVM 17–27**（28+ 尚不支持）。但编译可用 JDK 6+、测试执行需 JVM 8+；**wrapper / client / Tooling API / TestKit 兼容 JVM 8**。

## Gradle 9.8.1 安全修复

**这是升级 Gradle 的硬理由**。9.8.1 修了三个高危漏洞：

| 漏洞 | 影响 |
| :--- | :--- |
| 未认证的 worker-to-daemon 通道反序列化不可信 Java 对象 | 远程代码执行风险 |
| 客户端-daemon 通信在认证完成前就反序列化不可信对象 | 认证绕过 |
| SSL 连接失败的仓库未被禁用，构建可能暴露于恶意制品 | 供应链投毒 |

对应通告：`GHSA-mvvg-497x-hmj8`、`GHSA-xwqc-3h47-hg64`、`GHSA-j5m7-59rp-24f5`。

## Common Misconceptions

| 误解 | 事实 |
| :--- | :--- |
| "Gradle 就是 Maven 的快捷版" | 两阶段执行模型 + 任务图是本质差异，不是包装 |
| "依赖冲突 Gradle 也选最近版本" | **选最高版本**，与 Maven 相反 |
| "`implementation` 和 `api` 差不多" | `implementation` 的依赖在**消费者的编译 classpath 上不可见**；公开 API 里的类型必须用 `api` |
| "`platform()` 能锁死传递依赖版本" | 不能，`platform` 只提供**建议**；要强制必须用 `enforcedPlatform()` |
| "BOM 的行为和 Maven import scope 一样" | Maven import 也不强制；Gradle 对应物是 `enforcedPlatform` |
| "加了 configuration cache 就快了" | 必须先消除配置阶段的副作用，否则会**报不兼容**而不是变快 |
| "版本目录里的版本就是最终版本" | 目录只影响**声明**；传递依赖要求更高版本时仍会被选中 |
| "Gradle 4 早就不用 JCenter 了" | `jcenter()` API 在 **Gradle 9.0 被移除**（JCenter 本身 2024-08 已重定向到 Central） |
| "Maven Central 用 `mavenCentral()` 就能发" | **不能**——Central Portal 不暴露标准 Maven 上传端点，Gradle 必须用 vanniktech 插件或手工 bundle 上传 |
| "升级 Gradle 大版本主要是改 API" | 更常见的是**工具默认版本被顺带升级**（Checkstyle 10.24.0、PMD 7.13.0、JUnit 5.12.2、JGit 7.2.1）导致检查规则变化 |

## Comparison with Maven

| 维度 | Maven | Gradle |
| :--- | :--- | :--- |
| 配置形式 | 声明式 XML（pom.xml） | Groovy / Kotlin DSL |
| 模型 | 固定生命周期（phase 序列） | **任务有向无环图（DAG）** |
| 增量构建 | 基本没有 | 输入/输出快照，未变任务跳过 |
| 构建缓存 | 无 | 本地/远程 build cache，同输入直接复用 |
| 守护进程 | 无（有独立的 `mvnd`） | Gradle Daemon（JVM 常驻） |
| 依赖仲裁 | 最近路径优先 | **默认选最高版本** |
| 依赖可见性 | compile scope 一种 | `api` / `implementation` 区分是否传递给下游 |
| 版本管理 | 根 POM `dependencyManagement` + BOM import | version catalog（TOML）+ constraints + enforced platform |
| 多模块 | aggregator + parent + reactor | `include` + 项目依赖 + convention plugin |
| 依赖校验 | 无内建 | **checksum + signature 双机制** |
| 典型地盘 | 传统企业/后端 Spring Boot 主流 | Android、多模块大型项目、性能敏感 |

两者不是"谁更先进"的竞争关系，而是**两种权衡**：Maven 牺牲构建速度换取了确定性与低学习成本，Gradle 用更高的复杂度换取增量与缓存能力。同一团队两者并用是常态。详见 [Build Tools](/docs/CS/BuildTool/BuildTools.md)。

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md)
- [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)
- [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)
- [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)
- [Performance](/docs/CS/BuildTool/Gradle/Performance.md)

## References

1. [Gradle User Manual](https://docs.gradle.org/current/userguide/userguide.html)
2. [Gradle — Compatibility Matrix](https://docs.gradle.org/current/userguide/compatibility.html)
3. [Gradle — What's new in Gradle 9.0.0](https://gradle.org/whats-new/gradle-9)
4. [Gradle — Upgrading to Gradle 9.0.0](https://docs.gradle.org/current/userguide/upgrading_major_version_9.html)
5. [Gradle Release Notes](https://docs.gradle.org/current/release-notes.html)
