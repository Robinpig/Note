## Introduction

Gradle 的报错信息比 Maven 详细，但也因此更长、更难定位。这一篇按**症状**组织，模仿真实排障路径：先确定问题属于哪一类，再照表处理。

## Triage by Symptom

| 症状 | 大概率原因 | 去读 |
| :--- | :--- | :--- |
| 任务每次都重跑 | 输入输出声明有问题 | [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md) |
| 配置缓存不生效 | 配置阶段有副作用 | [Performance](/docs/CS/BuildTool/Gradle/Performance.md) |
| `NoSuchMethodError` | 依赖版本被选成不兼容的 | [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md) |
| 找不到类但依赖明明有 | `implementation` 依赖对消费者不可见 | [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md) |
| 编译变慢 / 依赖漂移 | 版本未统一 | [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md) |
| 发布到 Central 失败 | 还在用 OSSRH 端点 | [Publishing and Security](/docs/CS/BuildTool/Gradle/Publishing_and_Security.md) |
| IDE 同步失败 | IDE 插件与配置缓存不兼容 | 本文「Configuration Cache」节 |
| 首次构建特别慢 | daemon 刚重启 / 换了 jvmargs | 本文「Performance Symptoms」节 |

## Build Failures

### Configuration Cache Problems

**症状**：开启配置缓存后构建失败，或大量 warning。

```shell
./gradlew build --configuration-cache-problems=warn
```

**排查顺序**：

1. 看 Gradle 列出的具体不兼容点；
2. 对照下表逐个修；
3. 修完再把 `warn` 改回 `fail`。

| 不兼容行为 | 原因 | 修法 |
| :--- | :--- | :--- |
| 配置阶段读文件 | 状态不可序列化 | 改成 `@Input` + 执行阶段读 |
| 配置阶段跑 `git` / 网络命令 | 同上 | 用 `Provider` 惰性化 |
| action 里引用 `project` | Project 不可序列化 | 提前取值或用 `Provider` |
| 任务间共享可变对象 | 序列化后失去引用同一性 | 改用不可变数据 |
| 依赖任务执行结果 | 配置阶段还没有结果 | 拆成两个任务 |
| 修改 `System.properties` | 进程级副作用 | 改用 Gradle 属性 |

**最后一个大坑**：

```kotlin
// ❌ Project 被闭包捕获
tasks.register("bad") {
    doLast { println(project.version) }
}

// ✅
val version = project.version.toString()
tasks.register("good") {
    doLast { println(version) }
}
```

### Deprecation Warnings

```shell
./gradlew help --warning-mode=all     # 全部警告
./gradlew help --scan                 # Build Scan 里看 deprecation 视图
```

**Gradle 9.0 移除的 API**（此前已弃用）：

| 移除项 | 替代 |
| :--- | --- |
| `Project#exec` / `Project#javaexec` | `ExecOperations` 注入 |
| `Script#exec` / `Script#javaexec` | 同上 |
| `WriteProperties.outputFile` | `destinationFile` |
| `jcenter()` | `mavenCentral()` |
| `-c` / `--settings-file` | 无（标准布局） |
| `-b` / `--build-file` | 无（标准布局） |
| `GradleBuild.buildFile` | 无 |
| `org.gradle.cache.cleanup` | init script |
| `buildCache.local.removeUnusedEntriesAfterDays` | Gradle User Home cache cleanup settings |
| `org.gradle.util.*` 成员 | 官方 API 替代 |
| Unix 模式权限（文件权限位） | 不再支持 |

**Gradle 9.0 的默认值变更**：

| 类别 | 新默认值 |
| :--- | :--- |
| Checkstyle | 10.24.0 |
| CodeNarc | 3.6.0 |
| PMD | 7.13.0 |
| JUnit Jupiter | 5.12.2 |
| TestNG | 7.11.0 |
| Spock | 2.3 |
| Eclipse JGit | 7.2.1（原 5.13.3） |

> [!Note]
>
> **工具版本升级是 Gradle 大版本升级里最隐蔽的破坏源**。构建脚本没改，但 Checkstyle 升了两个大版本、PMD 换了规则集——原本通过的检查可能开始报错，**且报错信息与 Gradle 本身无关**。升级大版本前先把静态检查工具的版本显式锁住。

### Plugin Compatibility

Gradle 9.0 的其它破坏性变更：

| 变更 | 影响 |
| :--- | --- |
| Scala 插件不再创建不可解析的 configuration | Scala 项目 |
| 项目目录必须存在且可写 | 自定义项目布局 |
| Test 任务可能不再执行预期的测试 | 用了非标准 test 框架的 |
| build 目录外的过期输出不再被删除 | 依赖旧清理行为的脚本 |
| public API 类型的方法改为 final | 继承 Gradle API 的插件 |
| 注入的 getter 改为 abstract | 自定义注入 |
| `ConfigurationVariant.getDescription` 改为 `Property` | 变体相关插件 |
| Artifact Signing 改为匹配 OpenPGP Key Version | 签名配置 |
| Ear / War 插件：所有产物都参与 `assemble` | 打包相关脚本 |
| `jcenter()` 移除 | 依赖 JCenter 的老项目 |

**JCenter 已于 2024 年 8 月重定向到 Maven Central**——但重定向的是 HTTP 层面，Gradle 里 `jcenter()` 这个 API 本身在 9.0 被删了。改用 `mavenCentral()`。

### Dependency Resolution Failures

**症状**：`Could not resolve X` / `Could not find X`。

```shell
./gradlew :app:dependencies --configuration runtimeClasspath
./gradlew :app:dependencyInsight --dependency X
```

| 原因 | 排查 |
| :--- | :--- |
| 仓库没配 | 检查 `repositories` 与 `dependencyResolutionManagement` |
| 仓库被 `FAIL_ON_PROJECT_REPOS` 拦住 | 把仓库提到 settings |
| 插件仓库没配 | `pluginManagement { repositories { } }` |
| 版本冲突 | `dependencyInsight` 看选中理由 |
| strict 约束不满足 | 构建失败是**预期行为**——版本区间内无解 |
| Gradle 缓存与 Maven 缓存不通用 | 两者独立，Gradle 用 `~/.gradle/caches` |

### Task Execution Failures

| 症状 | 原因 |
| :--- | --- |
| `Cannot query the value of task output before task has completed` | 在配置阶段读任务输出 |
| `Task ... not found` | 任务名写错或任务没被创建（惰性） |
| `Execution failed for task ... > ... > AWT headless` | 任务需要 GUI 环境 |
| `Could not resolve all files for configuration` | 平台不匹配（如只在 x86 上发布的 native 库） |
| `Duplicate class` | 两个依赖带了同一类（常见于 uber-jar 被当普通依赖引入） |

## Performance Symptoms

### First Build Is Very Slow

**原因**：

1. daemon 刚启动（首次要下载依赖、预热 JIT）；
2. **改了 `org.gradle.jvmargs`** —— jvm 参数是 daemon 匹配键，改了就得起新的；
3. Kotlin DSL 首次需要编译 `.kts` 脚本。

**处理**：

```shell
./gradlew --status     # 看 daemon
./gradlew --stop       # 停掉后重启
```

### Configuration Phase Dominates

```shell
./gradlew build --profile
```

看 HTML 报告里配置阶段与执行阶段的分界。配置阶段占比高 → 优化方向是配置缓存 + 任务惰性化：

- 检查有没有 `subprojects {}` 大块；
- 检查有没有 `tasks.getByName` / `tasks.withType` 不带 `configureEach`；
- 检查有没有在配置阶段读文件、跑 git。

### Tasks Always Rerun

见 [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md) 的 "Why It Always Reruns"。最常见的是**把时间戳声明成了 `@Input`**。

### Build Cache Never Hits

```shell
./gradlew build --build-cache --info
```

看不到 "Stored" / "From cache" 就是没命中。检查：

- 缓存键里的某个输入每次都变（时间戳、绝对路径、随机值）；
- **JDK 版本不同** —— 缓存键包含编译器版本；
- 远程缓存没配或 `isPush = false` 但没先由 CI 推过。

## IDE Integration

### Sync Fails with Configuration Cache

IDE 插件（IDEA / Eclipse）生成工程文件的功能**与配置缓存不完全兼容**。现代 IDE 已经能直接导入 Gradle 项目而不需要 Gradle 生成工程文件，所以这个特性将被弃用移除；但"配置项目与底层工具模型"（比如标记源码目录为测试目录）会保留并改成兼容实现。

**处理**：先在命令行验证构建本身没问题（`./gradlew build`），再在 IDE 里同步；IDE 同步失败但命令行正常，通常就是 IDE 插件的问题。

### IDE Cannot Resolve a Dependency

如果依赖声明为 `implementation` 却要在 IDE 里直接引用它的类型——这是设计如此，不是 bug。IDE 的类路径模型与 Gradle 的 `api` / `implementation` 语义一致。

## Multi-Project Symptoms

### Included Build Cannot See Main Build's Plugins

`includeBuild` 是**完全独立的构建**，不共享插件 classpath。需要在 included build 自己的 `build.gradle.kts` 里声明插件依赖。

### Plugin Not Found in Included Build

`pluginManagement { repositories { } }` 不会从主构建继承。每个 included build 需要自己的插件仓库配置。

### Circular Dependency Between Projects

Gradle 会直接报循环。项目间依赖必须无环——这与 Maven 一样。

### Project Not Included

`include(":module")` 里的路径是相对**根项目目录**的。检查 `settings.gradle.kts` 的实际位置。

## Diagnostics Toolkit

```shell
./gradlew --status                          # daemon 状态
./gradlew --version                         # Gradle / JVM / OS 版本
./gradlew tasks --all                       # 所有任务
./gradlew help --task :core:compileJava     # 任务说明
./gradlew :core:properties                  # 任务属性（含 inputs/outputs）
./gradlew build --dry-run                   # 只看执行计划
./gradlew build --info                     # 详细日志
./gradlew build --stacktrace                # 完整异常栈
./gradlew build --profile                   # 性能报告
./gradlew build --scan                      # Build Scan（需 Develocity）
./gradlew build --configuration-cache-problems=warn
./gradlew :app:dependencies --configuration runtimeClasspath
./gradlew :app:dependencyInsight --dependency X
./gradlew buildEnvironment                  # buildscript 依赖
./gradlew projects                          # 项目结构
./gradlew properties                        # 所有属性
```

`--dry-run` 是最被低估的命令——**它打印完整执行计划但不执行**，能直接回答"这个任务为什么被跑了"。

## Environment

| 环境变量 / 属性 | 作用 |
| :--- | :--- |
| `GRADLE_USER_HOME` | Gradle 用户目录（缓存、daemon、wrapper） |
| `JAVA_HOME` | 运行 Gradle 用的 JDK（需 17–27） |
| `org.gradle.jvmargs` | daemon JVM 参数（**匹配键**） |
| `org.gradle.daemon` | 是否启用 daemon（CI 用 false） |
| `org.gradle.parallel` | 跨项目并行配置 |
| `org.gradle.caching` | 启用构建缓存 |
| `org.gradle.configuration-cache` | 启用配置缓存 |
| `org.gradle.debug` | 开启 daemon 的 JVM 调试端口 |

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md)
- [Performance](/docs/CS/BuildTool/Gradle/Performance.md)
- [Publishing and Security](/docs/CS/BuildTool/Gradle/Publishing_and_Security.md)

## References

1. [Gradle — Troubleshooting](https://docs.gradle.org/current/userguide/troubleshooting.html)
2. [Gradle — Upgrading to Gradle 9.0.0](https://docs.gradle.org/current/userguide/upgrading_major_version_9.html)
3. [Gradle — Configuration Cache Problems](https://docs.gradle.org/current/userguide/configuration_cache.html#config_cache:config_cache_problems)
4. [Gradle — Command Line Interface](https://docs.gradle.org/current/userguide/command_line_interface.html)
