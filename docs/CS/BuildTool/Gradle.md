## Introduction

Gradle 是一个基于 **任务有向无环图（Task DAG）** 的构建工具，用 Groovy 或 Kotlin DSL 描述构建（当前推荐 Kotlin DSL，`build.gradle.kts` 类型安全、IDE 补全好）。它结合了 Ant 的灵活性与 Maven 的约定和依赖管理，并通过增量构建、构建缓存、常驻守护进程大幅提升大型工程的构建速度，是 Android 与大型多模块 JVM 项目的事实标准。

## Task Model

构建被建模为一组 Task：每个任务声明**输入与输出**（注解或 DSL），Gradle 据此做 up-to-date 检查——输入未变且输出存在，任务直接标 `UP-TO-DATE` 跳过。任务之间用 `dependsOn` 构成 DAG，Gradle 配置阶段先确定执行图，再按拓扑序执行。

```groovy
tasks.register('hello') {
    doLast { println 'hello' }
}
// build 时 Gradle 自动组装：compileJava → processResources → classes → jar → assemble
```

插件提供现成任务与约定：`java`、`application`、`org.springframework.boot`、`com.google.cloud.tools.jib`（直接构建/推送镜像免 Dockerfile）等。

## Common Commands

```shell
./gradlew tasks                       # 查看可用任务
./gradlew build                       # 编译+测试+检查+打包
./gradlew clean test --info           # 清理后跑测试，输出详细日志
./gradlew test --rerun-tasks          # 忽略增量/缓存强制重跑（--rerun 简写）
./gradlew bootRun --args='--spring.profiles.active=dev'
./gradlew dependencies --configuration runtimeClasspath   # 依赖树
./gradlew --stop                      # 停止 daemon
```

`--rerun-tasks` 忽略所有 up-to-date 与 build cache；只重跑某任务可用 `--rerun-tasks` 或 clean 单个输出目录。CI 上通常 `--no-daemon`（流水线环境常驻无收益），但开启远程构建缓存。

## Test

```groovy
test {
    useJUnitPlatform {
        includeTags 'fast'
        excludeTags 'slow'
    }
    testLogging {
        events 'passed', 'skipped', 'failed'
    }
}
```

配合 JUnit 5 的 `@Tag` 做测试分层（单测/集成测试分离），CI 只默认跑 fast 组。`--tests` 可过滤单个类/方法：`./gradlew test --tests '*OrderServiceTest.create'`。测试默认也是增量的（输入变化才重跑），强制刷新用 `--rerun-tasks` 或 cleanTest。

## Dependency Management

```kotlin
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web") // 编译+运行，不泄露给上游
    api("com.google.guava:guava:33.0.0-jre")                           // 同时作为消费者的编译依赖暴露
    testImplementation("org.junit.jupiter:junit-jupiter")
    runtimeOnly("com.mysql:mysql-connector-j")
    annotationProcessor("org.projectlombok:lombok")                    // 注解处理器
}
```

- 配置项选择是高频面试点：`implementation` 不把依赖暴露给依赖方（加快增量编译），`api` 才会传递；
- 版本统一：BOM 用 `platform("...:dependencies")`；多模块用 version catalog（`gradle/libs.versions.toml`）集中声明；
- 排查冲突：`dependencyInsight --dependency xxx`，强制版本用 constraints 或 resolutionStrategy。

## Performance Mechanism

- **Daemon**：常驻 JVM，缓存已解析的构建模型，消除启动开销（本地开发默认开启）；
- **Configuration on demand / 配置缓存**：只配置相关模块、把配置结果序列化复用，进一步降低配置阶段耗时；
- **Build Cache**：任务输出按输入哈希缓存，本地目录或 HTTP 远程共享——不同机器/分支只要输入相同即复用（含代码、资源、JDK 版本等作为 key）；
- **并行执行**：`--parallel` 让互不相关的多模块任务并行。

## Wrapper and Multi-module

- **Wrapper**（`gradlew` + `gradle/wrapper/`）固化 Gradle 版本，任何人/CI 执行 `./gradlew` 自动下载声明版本，是项目应提交进版本库的基础设施；
- `settings.gradle(.kts)` 里 `include(":module-a")` 声明模块，`rootProject` + `subprojects` 可统一公共配置，模块间用 `project(":module-a")` 依赖，应保持依赖方向无环。

## Links

- [Build Tools](/docs/CS/BuildTool/BuildTools.md)
- [Maven](/docs/CS/BuildTool/Maven.md)
- [Test](/docs/CS/SE/Test.md)

## References

1. [Gradle User Manual](https://docs.gradle.org/current/userguide/userguide.html)
2. [Building Java & JVM projects](https://docs.gradle.org/current/userguide/building_java_projects.html)
