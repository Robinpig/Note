## Introduction

Gradle 的性能优化分三个层次，收益依次递减但也依次更难：

| 层次 | 机制 | 省掉的是什么 | 实施成本 |
| :--- | :--- | :--- | :--- |
| 1 | **Daemon** | JVM 启动 + JIT 预热 | 零（默认开启） |
| 2 | **增量构建** | 未变任务的执行 | 声明输入输出 |
| 3 | **Configuration Cache** | 整个配置阶段 | 需要改造构建脚本 |
| 4 | **Build Cache** | 跨机器的任务执行 | 需要远程缓存服务 |

顺序很重要：**前一层没做好，后一层的收益会被掩盖**。比如配置阶段只要 2 秒，开配置缓存也就省 2 秒；但配置阶段要 3 分钟时，它就是决定性的。

## Daemon

Gradle 客户端把构建请求发给 daemon 进程执行。

```shell
./gradlew --status          # 看当前 daemon 状态
./gradlew --stop            # 停止所有 daemon
```

**daemon 的 JVM 参数是匹配键**。改 `gradle.properties` 里的 `org.gradle.jvmargs` 会导致匹配不上旧 daemon，需要新起一个——这解释了"为什么改了配置后第一次构建特别慢"。

常用调优项（`gradle.properties`）：

```properties
org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=1g
org.gradle.daemon=true
org.gradle.parallel=true
org.gradle.caching=true
org.gradle.configuration-cache=true
```

> [!Note]
>
> **CI 上通常用 `--no-daemon`**——CI 是一次性环境，daemon 的复用收益为零，反而留下垃圾进程。但 CI 应该**开启远程构建缓存**（见下文），那才是真正的收益来源。

## Incremental Build

任务声明输入输出后，Gradle 跳过未变任务。这是**投入产出比最高**的一层——只要把 `@Input` / `@Output` 声明对了，就自动获得。

```shell
./gradlew build
> Task :core:compileJava UP-TO-DATE
> Task :core:jar UP-TO-DATE
```

增量带来的额外好处是**下游不重编译**：Gradle 会分析 classpath 的 ABI 变化，只有公开签名真的变了才触发下游重编译。

`compileJava` 的增量编译会区分：

- **ABI 变化** —— 公开方法签名变了 → 下游必须重编译；
- **实现变化** —— 只改了方法体 → 下游不用重编译。

这是 Gradle 相对 Maven 编译缓存（`maven-compiler-plugin` 的 `useIncrementalCompilation`）精细得多的地方。

## Configuration Cache

把配置阶段的产物序列化到磁盘，下次直接读。

```properties
org.gradle.configuration-cache=true
```

```shell
./gradlew build --configuration-cache-problems=warn   # 不兼容时降级为警告
./gradlew build --configuration-cache-problems=fail    # 默认
```

**状态（2026-10）**：Gradle 9.0 起是"推荐模式"，`gradle init` 生成的项目默认开启；官方目标是 **Gradle 11** 默认开启（已从 Gradle 10 推迟）。

### What Breaks It

配置缓存要求配置阶段是**纯粹且可序列化**的。常见的破坏者：

| 破坏行为 | 为什么坏 |
| :--- | --- |
| 在配置阶段读文件/查网络 | 结果无法序列化，且每次重做 |
| 在配置阶段读 `System.getenv()` 之外的可变状态 | 同上 |
| 任务之间共享可变 Java 对象 | 序列化后丢失引用同一性 |
| 依赖任务执行顺序 | 配置阶段还没有执行结果 |
| `System.exit` / 修改 `System.properties` | 进程级副作用 |
| 引用 `Project` 对象到任务 action 里 | Project 不可序列化 |

**最后一个尤其常见**：

```kotlin
// ❌ 捕获了 Project
tasks.register("bad") {
    doLast {
        println("project dir: ${project.rootDir}")   // 引用了外层 Project
    }
}

// ✅ 用 Provider / 把值提前算好
val rootDir = layout.projectDirectory   // Provider，可序列化
tasks.register("good") {
    doLast {
        println("project dir: ${rootDir.asFile}")
    }
}
```

### Diagnosing

```shell
./gradlew build --configuration-cache --configuration-cache-problems=warn
```

Gradle 会列出所有不兼容点。**把警告当错误处理**——Gradle 团队的建议是：即便当前没开配置缓存，也应该把配置缓存报的问题当 deprecation 看待，因为这些问题在开启后必然变成错误。

配置缓存问题有专门的 HTML 报告，路径在构建输出里给出。

## Build Cache

任务输出按**输入哈希**缓存，可以跨机器、跨分支复用。

```properties
org.gradle.caching=true
```

缓存键由**所有影响输出的输入**构成：源文件内容、classpath、任务类型、参数、**JDK 版本**、编译器版本等。

```shell
./gradlew build --build-cache           # 启用
./gradlew build --build-cache --info    # 看缓存命中情况
```

### Remote Build Cache

本地缓存只在本机有效。远程缓存（HTTP 或 S3 兼容存储）才能跨 CI 拿到收益。

```kotlin
// settings.gradle.kts
buildCache {
    remote(HttpBuildCache::class) {
        url = uri("https://build-cache.internal.corp/")
        isPush = true
        isReadOnly = false
    }
}
```

`isPush = false` 表示只读不写——适合**"预热"模式**：CI 主构建负责推送缓存，本地开发只读复用。

```kotlin
buildCache {
    local {
        directory = File(rootDir, ".gradle-cache")
        removeUnusedEntriesAfterDays = 30
    }
}
```

> [!Note]
>
> Gradle 9.0 起 **`buildCache.local.removeUnusedEntriesAfterDays` 不再可用**，缓存保留期改由 **Gradle User Home 的 cache cleanup settings** 管理；`org.gradle.cache.cleanup` 属性也已移除，改用 init script 配置。

**远程缓存的安全性**：缓存是按内容寻址的，理论上不存在投毒风险（哈希不匹配会直接失败）。但 Develocity 的 Universal Cache 引入了 "Trusted Artifact Isolation" 概念，额外隔离不可信来源的缓存条目。

## Parallel Execution

```shell
./gradlew build --parallel
./gradle.properties: org.gradle.parallel=true
```

Gradle 会在**没有依赖关系**的任务之间并行执行。项目间默认不并行（因为 Gradle 的项目是逐个配置的），`org.gradle.parallel=true` 允许**跨项目并行配置**。

**并行配置缓存**（8.11 引入）：

- 存储端可并行 —— 不同项目的 task graph 并行存入缓存；
- 加载端**默认并行** —— 恢复缓存天然更安全（隔离性更强）；
- 需要显式开启存储端并行（因为引入了原本单线程处的并发）。

官方数据：约 600 个项目的构建，配置时间 2m4s → 55s，缓存体积 700MB → 400MB。

## Isolated Projects

**预 Alpha** 特性，建立在配置缓存之上，目标是在 IDE 同步时进一步提速。

核心约束是**项目间不能跨边界直接访问**——每个项目只能通过声明式 API 交互。

Gradle 9.0 **不包含** Isolated Projects 的具体变更（优先级让给配置缓存的产品化），开发在后续 9.x 版本推进。

## Kotlin DSL Compilation

Kotlin DSL 的编译开销是 Gradle 最大的性能痛点之一。Gradle 9.0 借 **Kotlin 2 编译器**实现了"避免不必要的 `.kts` 重编译"。

官方示例：构建改动后执行 `:help`，提速 **2.5 倍**。

其它相关工作：8.10 引入字符串去重，显著减小缓存文件体积（Android X 团队报告体积减少 **3.75 倍**）。

## Profiling

```shell
./gradlew build --profile              # 生成 HTML 报告
./gradlew build --scan                 # 生成 Build Scan（需 Develocity）
```

`--profile` 生成 `build/reports/profile/profile-<timestamp>.html`，包含：

- 每个任务的耗时；
- **configuration phase 与 execution phase 的分界与各自耗时**；
- 哪些任务在等 I/O。

**看 profile 的第一件事是看配置阶段占了多少**。如果配置阶段占了一半以上，优化方向是配置缓存和任务惰性化，而不是任务本身。

```shell
./gradlew --stop     # profiling 后建议重启 daemon
```

## Benchmarking

Gradle 自身有 **gradle-performance** 项目提供基准测试套件，用于验证性能改动。

社区常用的自建基准方法：

```shell
# 冷启动
./gradlew --stop && ./gradlew build --profile
# 热启动（第二次）
./gradlew build --profile
# 增量
touch core/src/main/java/Foo.java && ./gradlew build --profile
```

## Tuning Checklist

按收益排序：

1. **声明正确的输入输出** —— 增量构建生效，最高性价比；
2. **用 `tasks.register` + `configureEach`** —— 保住惰性；
3. **开启 configuration cache** —— 大项目收益最大；
4. **配置远程 build cache** —— CI 场景核心收益；
5. **开 `org.gradle.parallel=true`** —— 模块多的项目有效；
6. **调 `org.gradle.jvmargs` 内存** —— 依赖图大的项目容易 OOM；
7. **用 Kotlin DSL** —— 编译期检查换来的重编译时间通常值得。

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md)
- [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)
- [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)

## References

1. [Gradle — Configuration Cache](https://docs.gradle.org/current/userguide/configuration_cache.html)
2. [Gradle — Build Cache](https://docs.gradle.org/current/userguide/build_cache.html)
3. [Gradle — Daemon](https://docs.gradle.org/current/userguide/daemon.html)
4. [Gradle — Incremental Builds](https://docs.gradle.org/current/userguide/incremental_build.html)
5. [Gradle — Profiling a Build](https://docs.gradle.org/current/userguide/profiling.html)
