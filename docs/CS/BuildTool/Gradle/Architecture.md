## Introduction

Gradle 的核心命题只有一个：**让构建时间与改动的代码量成正比，而不是与项目总规模成正比**。为达成这个目标，它用三件事替换了 Maven 的三件事：

| Maven | Gradle | 换来什么 |
| :--- | :--- | :--- |
| 固定生命周期（phase 序列） | **任务有向无环图** | 任务可自由增删、按需执行 |
| 每次重新解析依赖 | **增量构建 + 输入输出快照** | 未变任务标 `UP-TO-DATE` 跳过 |
| 每次冷启 JVM | **常驻 daemon + 配置缓存** | 省掉启动与配置开销 |

代价是**学习曲线陡峭**与**构建脚本即代码**（可以用 Groovy/Kotlin 写任意逻辑）。这一篇先建立"两阶段执行模型"这个最关键的心智模型——**理解它，就理解了 Gradle 90% 的行为**。

## The Two-Phase Model

Gradle 的一次构建严格分成两个阶段，中间由**任务图（task graph）**连接：

```
┌──────────────────── Configuration Phase ────────────────────┐
│  执行 build 脚本（settings.gradle.kts + 各 build.gradle.kts）  │
│  → 创建所有 Project / Task 对象                              │
│  → 解析插件、应用 DSL、计算属性值                             │
│  → 决定「要执行哪些任务、谁先谁后」                          │
└──────────────────────────┬──────────────────────────────────┘
                           │  产出：task graph
                           ▼
┌────────────────────── Execution Phase ───────────────────────┐
│  按拓扑序执行任务                                            │
│  → 每个任务检查 up-to-date（输入快照 vs 上次快照）            │
│  → 需要执行则跑 action；不需要则标 UP-TO-DATE 跳过            │
└─────────────────────────────────────────────────────────────┘
```

**关键点：configuration phase 里不能做"业务事"**。它只负责"决定要做什么"。任何在配置阶段执行的昂贵操作（读大文件、跑 git、查网络）都会被**每次构建都重做一遍**，哪怕任务最后是 `UP-TO-DATE` 跳过的。

这也是 Gradle 与 Maven 最大的行为差异：Maven 的生命周期是**固定且线性的**，插件往哪个 phase 挂就得跟着那个 phase 走；Gradle 的任务是**图里的节点**，用 `dependsOn` 声明边，Gradle 自动做拓扑排序。

### Why It Matters

一个典型症状：

```kotlin
// ❌ 每次构建都执行，包括全 UP-TO-DATE 的构建
val currentBranch = providers.exec {
    commandLine("git", "rev-parse", "--abbrev-ref", "HEAD")
}.standardOutput.asText.get().trim()
```

正确做法是把昂贵计算推迟到执行阶段，或用 `Provider` 让它惰性求值。

## The Daemon

Gradle 客户端本身只是个启动器，真正的构建跑在 **daemon 进程**里。

```
./gradlew build
   │
   ├─ 启动器（native / JVM）
   │    └─ 连上已有 daemon（按 JDK 版本、内存参数、jvmargs 匹配）
   │         或新起一个
   └─ daemon 内执行 configuration + execution phase
```

daemon 复用带来的收益：

- JVM 启动 + JIT 预热被省掉（首次除外）；
- **构建模型被缓存**——daemon 里已经加载的插件、已解析的依赖、已编译的 Kotlin DSL 脚本都还在；
- 依赖下载的 HTTP 连接复用。

daemon 会按空闲超时自动退出（默认 3 小时），也可以 `./gradlew --stop` 主动停。

> [!Note]
>
> **daemon 的 JVM 参数是匹配键**。改了 `gradle.properties` 里的 `org.gradle.jvmargs`，就会匹配不上旧 daemon，需要新起一个。所以"第一次构建特别慢"往往是"刚改了 jvmargs"。

## Project and Task

**Project** 对应一个构建单元（一个目录 + 一份 `build.gradle.kts`）。**Task** 是最小的可执行工作单元。

`Project` 之间可以依赖（`project(":core")`），Gradle 据此推导任务间的隐式依赖。

`build.gradle.kts` 里的这段是 Gradle 一切工作的起点：

```kotlin
plugins {
    java
}

tasks.register("hello") {
    doLast {
        println("hello")
    }
}
```

`tasks.register` 是**惰性注册**——只登记名字和配置动作，不立刻创建对象。真正的创建推迟到"这个任务确实被需要"时。

> [!Warning]
>
> **惰性注册不是可选的优化，是 Gradle 9 的正确写法**。用 `tasks.getByName(...)`、`tasks.create(...)` 会立即实例化并**破坏惰性**——这会强制 Gradle 配置那些本不需要的模块，直接抵消配置缓存的收益。
>
> 社区里流传的 "Configuration Bomb" 现象就源于此：`tasks.withType` 不带 `.configureEach {}`、`tasks.map {}` 之类的 Kotlin 集合操作，都会静默地让惰性失效。

## Configuration Cache

配置缓存把 **configuration phase 的产物**（任务图 + 每个任务的配置）序列化到磁盘，下次构建直接反序列化，跳过整个配置阶段。

```
第一次构建:  执行 build 脚本 → 生成 task graph → 存入缓存
后续构建:    读取缓存 → 直接得到 task graph → 执行
```

它解决的是"项目大、模块多时，光配置就要几十秒"的问题。官方数据：约 600 个项目的构建，配置时间从 2m4s 降到 55s，同时缓存体积从 700MB 降到 400MB（8.11 引入并行加载/存储后）。

**状态**（2026-10）：

- Gradle 9.0 起，Configuration Cache 是**推荐模式（preferred mode）**——Gradle 会在检测到构建可兼容时主动提示你开启；
- `gradle init` 生成的新项目**默认开启**；
- 目标是在 **Gradle 10** 默认开启，但已推迟到 **Gradle 11**；
- 9.0 起，即使第三方插件不完全兼容，也能**永久开启**而不构建失败——不兼容的插件会**优雅降级**（graceful downgrade）。

**还完全不兼容的**（截至 9.x）：

| 特性 | 状态 |
| :--- | :--- |
| Source dependencies（从 Git 仓库引入构建） | 计划在 9.x 时间线内支持 |
| Ant 集成 | 不支持，计划用功能更少的方案替代 |
| IDE 插件（IDEA / Eclipse 生成工程文件） | 项目文件生成将弃用移除；配置模型部分保留 |

配置缓存自 8.1 起**默认加密**——Gradle 自动生成机器相关的密钥存在 Gradle user home 下。

> [!Tip]
>
> 启用方式：`gradle.properties` 里 `org.gradle.configuration-cache=true`。
> 排查问题用 `--configuration-cache-problems=warn`（降级为警告）或 `fail`（默认，失败即报错）。
> 官方有专门的 Adoption Guide 处理常见不兼容点。

## Isolated Projects

Isolated Projects 是**预 Alpha** 的孵化特性，建立在配置缓存之上，目标是在 Android Studio / IntelliJ IDEA 同步时进一步提速。

它的核心约束是**项目间不能跨边界直接访问**——每个项目只能通过声明式的 API 与其它项目交互。Gradle 9.0 本身**不包含** Isolated Projects 相关的具体变更（优先级让给了配置缓存的产品化），相关开发在后续 9.x 版本推进。

## Kotlin DSL vs Groovy DSL

| 维度 | Kotlin DSL（`.kts`） | Groovy DSL（`.gradle`） |
| :--- | :--- | :--- |
| 类型安全 | 编译期检查 | 运行时才报错 |
| IDE 补全 | 好 | 一般 |
| 首次编译 | 慢（Kotlin 编译） | 快 |
| 语法 | Kotlin | Groovy |
| 当前地位 | **官方推荐** | 存量维护 |

Gradle 9.0 起嵌入 **Kotlin 2.2.0**（8.x 是 2.0.21），Kotlin DSL 与 Kotlin 插件统一使用 **Kotlin 语言版本 2.2**——这比 8.x 激进（8.11 起嵌 Kotlin 2.0 但仍用语言版本 1.8 以保兼容）。

好处是 **Kotlin 2 编译器让 Gradle 避免不必要的 `.kts` 重编译**，官方示例中 `:help` 任务在构建改动后提速 **2.5 倍**。

代价是 Kotlin 2.0/2.1 引入的破坏性语言变更会影响构建脚本。Gradle 9 里特别注意两处：

- **不能再用 `this@Build_gradle` 这类标签引用脚本实例**——改用 `project` / `settings` / `gradle`；
- **移除了对 Kotlin 语言版本 1.4–1.7 的支持**。

## Version Baseline

| 组件 | 版本 | 状态 |
| :--- | :--- | :--- |
| Gradle | `9.8.2` | **当前版**，2026-10-19 |
| Gradle | `9.8.1` | 2026-10-13，修 3 个高危安全漏洞 |
| Gradle | `9.8.0` | 2026-09-24，支持 Java 27 |
| Gradle | 9.9.0-milestone-2 | 2026-09-18，下一版本线预发布 |
| Gradle 嵌入 Kotlin | 2.4.0（9.7.0 起）/ 语言版本 2.2 | — |
| Gradle 嵌入 Groovy | 4.0.33（9.8.0 起） | 插件需用 Groovy 4.x |
| AGP（Android） | 9.0 – 9.5.0-alpha02 | 测试范围 |

**运行 Gradle 需要的 JVM 版本是 17–27**（JVM 28+ 尚不支持）。但：

- 编译可以用 JDK 6+，测试执行需要 JVM 8+；
- **Gradle wrapper、Gradle client、Tooling API client、TestKit client 兼容 JVM 8**——只是启动构建需要更新的 JVM。

支持的平台：Windows 10/11（AMD64、AArch64）、Ubuntu 22、macOS 13+、Alpine 3.20、CentOS Stream 9。

## Links

- [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md)
- [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)
- [Performance](/docs/CS/BuildTool/Gradle/Performance.md)
- [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)

## References

1. [Gradle User Manual](https://docs.gradle.org/current/userguide/userguide.html)
2. [Gradle — Compatibility Matrix](https://docs.gradle.org/current/userguide/compatibility.html)
3. [Gradle — What's new in Gradle 9.0.0](https://gradle.org/whats-new/gradle-9)
4. [Gradle — Upgrading to Gradle 9.0.0](https://docs.gradle.org/current/userguide/upgrading_major_version_9.html)
