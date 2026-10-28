## Introduction

Gradle 的任务模型是它全部性能优势的来源。核心只有一句话：**任务声明输入与输出，Gradle 据此决定要不要执行它**。

这一篇讲清任务类型、输入输出声明、up-to-date 判定、增量构建与缓存键的构成，以及那些"任务总是重跑"的常见原因。

## Task Types

Gradle 有两类任务，区别在于**谁来声明输入输出**。

### Built-in Tasks

由 Gradle 内置或插件提供的任务，**已经声明好了输入输出**。`compileJava` 的输入是源文件 + classpath，输出是 `.class` 文件。这是绝大多数情况。

### Custom Tasks

自己写的任务，**必须显式声明输入输出**，否则 Gradle 无法判断它能不能跳过：

```kotlin
abstract class GenerateDocsTask : DefaultTask() {

    @get:Input
    abstract val sourceDir: DirectoryProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @TaskAction
    fun generate() {
        // ...
    }
}
```

`DefaultTask` 是所有自定义任务的基类。

## Declaring Inputs and Outputs

注解是声明式的方式，每个注解对应一类"Gradle 如何追踪这个属性"的策略：

| 注解 | 含义 | 追踪方式 |
| :--- | :--- | :--- |
| `@Input` | 单个输入值 | 值的哈希 |
| `@InputFile` | 单个输入文件 | 文件内容哈希 |
| `@InputFiles` | 多个输入文件 | 每个文件内容哈希的集合 |
| `@InputDirectory` | 输入目录 | 目录下所有文件内容哈希 |
| `@OutputFile` | 输出文件 | 输出路径 + 内容 |
| `@OutputFiles` | 多个输出文件 | 同上 |
| `@OutputDirectory` | 输出目录 | 同上 |
| `@Classpath` | classpath 输入 | 类文件内容的规范化哈希（忽略顺序等） |
| `@CompileClasspath` | 编译 classpath | 同上，更严格 |
| `@PathSensitive` | 配合 `@InputFiles`，控制路径敏感度 | 见下文 |
| `@Optional` | 该输入可能不存在 | 存在时才计入 |
| `@IgnoreEmptyDirectories` | 忽略空目录 | 目录结构敏感 |
| `@Internal` | 明确排除在追踪之外 | 不参与 |
| `@LocalState` | 本地状态，**不参与缓存键** | 见下文 |
| `@ServiceReference` | 服务引用 | 传递性追踪 |

### Path Sensitivity

`@InputFiles` 默认对路径**敏感**（`PathSensitivity.RELATIVE`）——文件移动位置会改变缓存键。这对"内容没变但路径变了"的场景是浪费。

```kotlin
@get:InputFiles
@get:PathSensitive(PathSensitivity.NONE)
abstract val generatedSources: FileCollection
```

三种取值：

| 值 | 含义 | 适用 |
| :--- | :--- | :--- |
| `RELATIVE` | 相对路径参与哈希（默认） | 路径本身有意义 |
| `ABSOLUTE` | 绝对路径参与哈希 | 极少用 |
| `NONE` | 只看内容，忽略路径 | 内容相同即可复用 |

### Local State

`@LocalState` 标记的属性**不参与缓存键**——它不影响输出，但会影响任务内部行为。典型用途：下载进度、临时目录、日志。

```kotlin
@get:LocalState
abstract val workDir: DirectoryProperty
```

`@LocalState` 与 `@Internal` 的区别：前者仍会被 Gradle 追踪（做清理管理等），只是不进缓存键；后者完全不被追踪。

## Up-to-Date Checks

执行任务前，Gradle 做三件事：

1. **计算输入快照** —— 把所有 `@Input*` 属性序列化、哈希；
2. **对比上次快照** —— 存在历史执行记录且哈希一致？
3. **检查输出存在性** —— 输出文件是否还在、是否被改过。

三者都满足 → 任务标记为 `UP-TO-DATE`，**不执行**。

```shell
./gradlew build
> Task :core:compileJava UP-TO-DATE
> Task :core:processResources UP-TO-DATE
```

### Why It Always Reruns

任务反复重跑的常见原因，按出现频率排序：

| 原因 | 说明 | 排查 |
| :--- | :--- | :--- |
| **输出被删了** | `clean` 之后必然全量 | 正常 |
| **输出被外部改了** | IDE 重新格式化、代码生成器覆盖 | 检查输出的 hash |
| **输入里有非确定性内容** | 时间戳、随机数、`System.currentTimeMillis()`、环境变量 | 审查 `@Input` 列表 |
| **classpath 变了** | 依赖版本变了 → `compileJava` 输入变化 | `dependencyInsight` |
| **任务没声明输入** | 自定义任务漏了 `@Input` | 补注解 |
| **用了 `@Internal` 掩盖了真实输入** | 输入被排除 → 变化检测不到 | 检查 `@Internal` 用得对不对 |
| **输出未声明** | Gradle 认为任务无输出 → 无法跳过 | 补 `@Output*` |

**最隐蔽的一种**：把时间戳之类的非确定性值声明成了 `@Input`。这会让任务永远"有变化"，而开发者会以为是别的问题。

## Task Ordering

Gradle 用四种机制表达任务间的顺序关系：

```kotlin
tasks.register("compileFirst") { }
tasks.register("compileSecond") { }

// 1. dependsOn —— 有向边，A 必须在 B 之前
tasks.named("compileSecond") { dependsOn("compileFirst") }

// 2. mustRunAfter —— 顺序约束，但无依赖关系
tasks.named("compileSecond") { mustRunAfter("compileFirst") }

// 3. shouldRunAfter —— 顺序约束，仅在两者都被调度时生效，优先级最低
tasks.named("compileSecond") { shouldRunAfter("compileFirst") }

// 4. finalizedBy —— A 结束后必须执行 B（无论 A 成功与否）
tasks.named("compileFirst") { finalizedBy("cleanup") }
```

`dependsOn` vs `mustRunAfter` 的区别很实际：`dependsOn` 会**把 A 拉进任务图**（即使你只请求了 B），`mustRunAfter` 只在 A 已经在图里时才约束顺序。

## Do Not Track State

有些任务"每次都必须跑，但产出可以缓存"——比如上传、通知、推送指标。这类任务用 `outputs.upToDateWhen { false }` 禁用 up-to-date 检查：

```kotlin
tasks.register("notify") {
    outputs.upToDateWhen { false }
    doLast { /* 总是执行 */ }
}
```

`doNotTrackState()` 是更彻底的版本——声明这个任务完全不可追踪，Gradle 不会给它算缓存键。

## Task Configuration Avoidance

任务注册要**惰性**，配置要**按需**。这是配置缓存能否生效的前提。

```kotlin
// ✅ 推荐
tasks.register<JavaCompile>("compileCustom") {
    source(sourceDir)
    destinationDirectory = outputDir
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
}

// ❌ 破坏惰性
tasks.getByName("compileJava").options.encoding = "UTF-8"
tasks.create("foo") { }
tasks.withType<JavaCompile> { options.encoding = "UTF-8" }   // 无 configureEach
```

**区别**：

- `tasks.withType<T>()` —— 返回**所有**匹配任务（不管是否已创建），是 eager 的；`.configureEach {}` 才是惰性的；
- `tasks.named<T>("name") {}` —— 只配置已注册的任务，惰性；
- `tasks.register<T>("name") {}` —— 注册 + 惰性配置。

在 Kotlin DSL 里，`tasks.map {}`、`tasks.filter {}` 这类集合操作会**遍历并实例化**所有任务，破坏惰性。Gradle 社区称之为 "Configuration Bomb"。

## Common Task Types

| 任务 | 来源 | 说明 |
| :--- | :--- | :--- |
| `compileJava` / `compileKotlin` | `java` / `kotlin` 插件 | 编译 |
| `processResources` | `java` | 处理资源 |
| `jar` | `java` | 打 jar |
| `test` | `java` | 单元测试 |
| `check` | `java` / `base` | 校验（聚合 test + 静态检查） |
| `build` | `base` / `java` | 聚合 `assemble` + `check` |
| `assemble` | `base` | 聚合所有产物任务 |
| `publishToMavenLocal` | `maven-publish` | 发布到本地仓库 |
| `dependencies` | 内置 | 打印依赖树 |
| `buildEnvironment` | 内置 | 打印 buildscript 依赖 |

`build` 的构成值得记住：`build` = `assemble` + `check`，`check` = `test` + 静态检查。所以 `./gradlew build` 会跑测试。

## Custom Task Example

一个完整的、带输入输出声明的自定义任务：

```kotlin
abstract class TemplateRenderTask : DefaultTask() {

    @get:InputFile
    abstract val template: RegularFileProperty

    @get:Input
    abstract val targetEnv: Property<String>

    @get:OutputFile
    abstract val outputFile: RegularFileProperty

    @TaskAction
    fun render() {
        val text = template.asFile.readText()
            .replace("{{env}}", targetEnv.get())
        outputFile.asFile.writeText(text)
    }
}

tasks.register<TemplateRenderTask>("renderTemplate") {
    template.set(layout.projectDirectory.file("templates/app.tpl"))
    targetEnv.set(providers.gradleProperty("targetEnv").orElse("dev"))
    outputFile.set(layout.buildDirectory.file("generated/app.txt"))
}
```

`providers.gradleProperty(...)` 是 **Provider API** 的用法——它返回一个惰性的值，在真正被读取时才求值，且能被 Gradle 追踪为输入。

## Task Inputs and Outputs Inspection

```shell
./gradlew :core:compileJava --info        # 看任务输入输出详情
./gradlew :core:properties                # 看任务的属性（含 inputs/outputs）
./gradlew help --task :core:compileJava    # 看任务说明
./gradlew tasks --all                      # 看所有任务
./gradlew :core:compileJava --dry-run      # 只看执行计划，不真跑
```

`--dry-run` 是排查"为什么这个任务被执行了"的利器——它会打印完整的执行计划，你能看到是哪条 `dependsOn` 把任务拉进图的。

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Performance](/docs/CS/BuildTool/Gradle/Performance.md)
- [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)
- [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)

## References

1. [Gradle — Implementing Custom Tasks](https://docs.gradle.org/current/userguide/custom_tasks.html)
2. [Gradle — Tasks](https://docs.gradle.org/current/userguide/tasks.html)
3. [Gradle — Incremental Builds](https://docs.gradle.org/current/userguide/incremental_build.html)
4. [Gradle — Task Inputs and Outputs](https://docs.gradle.org/current/userguide/task_inputs_outputs.html)
