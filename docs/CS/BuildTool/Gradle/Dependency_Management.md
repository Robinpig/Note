## Introduction

Gradle 的依赖管理与 Maven 的最大差异只有一条，但影响极深：**Gradle 默认选最高版本，Maven 默认选最近路径的版本**。同一次依赖冲突，两边给出的结果可能完全不同——这是从 Maven 迁到 Gradle 最常见的翻车点。

除此之外，Gradle 用 **configuration（配置）** 取代 Maven 的 scope 来表达"这个依赖在什么场景下可见"，并用 **api / implementation** 区分"是否暴露给下游"。

## Configurations

一个 configuration 是"一组依赖 + 解析规则"的容器。声明依赖时，选哪个 configuration 决定了三件事：**谁能看到它**、**它出现在哪条 classpath 上**、**它是否传递给下游**。

Java 插件提供的主要 configuration：

| Configuration | 编译期可见 | 运行期可见 | 传递给下游 | 典型用途 |
| :--- | :--- | :--- | :--- | :--- |
| `api` | ✅ | ✅ | ✅ | 本库 API 签名里出现的类型 |
| `implementation` | ✅ | ✅ | ❌ | 仅内部实现用的依赖 |
| `compileOnly` | ✅ | ❌ | ❌ | 容器/框架提供（servlet-api） |
| `compileOnlyApi` | ✅ | ❌ | ✅ | 既是 API 又由容器提供 |
| `runtimeOnly` | ❌ | ✅ | ❌ | JDBC 驱动、运行时实现 |
| `runtimeOnlyApi` | ❌ | ✅ | ✅ | — |
| `annotationProcessor` | — | — | ❌ | Lombok、MapStruct |
| `testImplementation` | ✅（测试） | ✅ | ❌ | JUnit |
| `testRuntimeOnly` | ❌ | ✅（测试） | ❌ | 测试运行时 |

派生 classpath：`compileClasspath` = `compileOnly` + `implementation` + `compileOnlyApi` + `api`；`runtimeClasspath` = `runtimeOnly` + `implementation` + `api`（+ `compileOnlyApi`）。

## api vs implementation

这是 Gradle 最有价值、也最容易被误解的设计。

```kotlin
// lib/build.gradle.kts
dependencies {
    api("com.google.guava:guava:33.0.0-jre")        // 出现在 lib 的公开 API 签名里
    implementation("org.slf4j:slf4j-api:2.0.17")   // 只是内部实现用
}
```

语义：

- **`api`** —— 依赖的**类型出现在本库对外暴露的 API 上**。消费者编译时需要它，所以它会出现在消费者的 classpath 上，并且消费者的消费者也能看到；
- **`implementation`** —— 依赖只用于本库内部实现。**消费者的编译 classpath 上没有它**，因此消费者**无法引用**这些类型。

这不是可选的风格问题，而是**编译期契约**。如果一个类型出现在你的 public 方法签名里，却声明为 `implementation`，那么消费者编译时会报 "cannot access class"。

### 传递性对比

```
consumer → lib → guava
```

| lib 中的声明 | consumer 能看到 guava 吗 |
| :--- | :--- |
| `api("guava")` | ✅（编译 + 运行） |
| `implementation("guava")` | ❌ 编译期不可见；运行期在（因为 runtimeClasspath 包含 implementation） |

Maven 那边没有这个区分——Maven 的 `compile` scope 相当于 Gradle 的 `api`。所以从 Maven 迁到 Gradle 时，**原先的 `compile` 依赖通常应该降级为 `implementation`**，除非它确实出现在公开 API 里。

> [!TIP]
>
> 迁移时的实用做法：先把所有 Maven `compile` 依赖都声明为 `api`，确保编译通过；再逐个检查哪些其实只用于内部，降级为 `implementation`。这样能立刻获得"增量编译更快"（implementation 依赖变化不触发下游重编译）的收益，而不会一上来就编译失败。

## Conflict Resolution

**Gradle 的默认策略是选最高版本。**

```
项目直接依赖 guava 30.0-jre
传递依赖需要 guava 32.0-jre
→ 选 32.0-jre
```

对比 Maven 的 nearest-wins：Maven 会选 30.0-jre（最近路径）。

**结论**：Gradle 通常给你"更新的"版本，这符合直觉，但也意味着**你可能在不知情的情况下用了传递依赖要求的新版本**，而那个版本可能与你的直接依赖不兼容。

Gradle 的冲突解决流程：

1. 收集所有请求的版本；
2. 选最高版本作为候选；
3. 逐个检查其它约束（strictly / prefer / reject）是否允许该版本；
4. 若最高版本不满足某个约束，选择满足所有约束的最高版本。

### Diagnosing

```shell
# 某个依赖被哪些路径引入、为什么选了它
./gradlew :app:dependencyInsight --dependency guava --configuration runtimeClasspath

# 完整依赖树
./gradlew :app:dependencies --configuration runtimeClasspath

# 只看被强制改写为某版本的
./gradlew :app:dependencyInsight --dependency jackson-databind --configuration compileClasspath
```

`dependencyInsight` 的输出会明确写出选中理由：

```
com.google.guava:guava:30.0-jre is selected because constraint (by constraint) ...
```

### Forcing Versions

**方式一：dependency constraints（推荐）**

```kotlin
dependencies {
    constraints {
        implementation("com.google.guava:guava:33.0.0-jre") {
            because("CVE-2023-2976 修复要求")
        }
    }
}
```

constraint 不引入依赖，只声明"如果这个依赖出现在图里，版本必须是 X"。

**方式二：resolutionStrategy（强制覆盖）**

```kotlin
configurations.all {
    resolutionStrategy {
        force("com.google.guava:guava:33.0.0-jre")
        failOnVersionConflict()
        eachDependency {
            if (requested.group == "com.google.guava") {
                useVersion("33.0.0-jre")
            }
        }
    }
}
```

`failOnVersionConflict()` 会在出现无法调解的冲突时**让构建失败**而不是静默选一个——适合在 CI 上强制暴露问题。

**方式三：强制平台（enforced platform）**

```kotlin
dependencies {
    implementation(enforcedPlatform("com.fasterxml.jackson:jackson-bom:2.18.2"))
}
```

`enforcedPlatform` 与普通 `platform` 的区别很关键：

| | `platform` | `enforcedPlatform` |
| :--- | :--- | :--- |
| 提供版本建议 | ✅ | ✅ |
| 覆盖其它地方声明的版本 | ❌ | ✅ **强制** |
| 用途 | 统一"建议版本" | 强制统一"实际版本" |

Maven 的 `import` scope 行为接近 `platform`（提供建议，不强制）。要用 Gradle 达到 Maven `dependencyManagement` 里"锁死传递依赖版本"的效果，**必须用 `enforcedPlatform`**。

> [!Note]
>
> 这是一个很容易踩的坑：从 Maven 迁过来，把 BOM 用 `platform()` 引入，结果发现传递依赖的版本没被覆盖——因为别的依赖声明的更高版本赢了。改用 `enforcedPlatform()` 才生效。

## Dependency Locking

锁定模式把**当前解析出的所有版本**写进 `gradle.lockfile`，之后构建严格按锁定文件解析：

```shell
./gradlew dependencies --write-locks
./gradlew dependencies            # 之后按 lockfile 解析
```

```properties
# gradle.properties
dependencyLocking { lockAllConfigurations() }
```

用途：

- **可重复构建** —— 保证不同机器、不同时间解析出完全相同的依赖图；
- **防止依赖漂移** —— 传递依赖的版本变化会被立即暴露，而不是悄悄生效。

启用锁定后升级依赖需要显式执行 `--write-locks`，这是刻意的摩擦——它让依赖变更成为**有意的、可评审的动作**。

## Dependency Types

三类依赖：

| 类型 | 声明方式 | 说明 |
| :--- | :--- | :--- |
| **Module dependency** | `"group:name:version"` | 仓库里的模块，最常用 |
| **Project dependency** | `project(":core")` | 同一构建内的其它项目 |
| **File dependency** | `files("libs/a.jar")` | 本地文件，**无任何元数据**（无传递依赖、无来源信息） |

**尽量避免 file dependency**。它绕过了依赖元数据——没有传递依赖、没有来源验证，天然不适合可重复构建。官方也明确建议用 project 或 module dependency 替代。

## Dependency Caching and Repositories

Gradle 有自己的依赖缓存（`~/.gradle/caches/modules-2`），**不共用 Maven 的 `~/.m2/repository`**。两个工具并用时依赖会被下载两次。

仓库声明：

```kotlin
repositories {
    mavenCentral()
    maven { url = uri("https://nexus.internal.corp/repository/maven-public/") }
}
```

Gradle 9.8 起新增了**复用 Maven 镜像配置**的能力——对同时用 Maven 和 Gradle 的团队很实用：

```properties
# gradle.properties
org.gradle.mirror.maven.settings=true
```

启用后，Gradle 会**读取 Maven 的 `settings.xml` 里的 mirror 配置**，把匹配的仓库 URL 替换掉。适用范围：

- ✅ 所有 HTTP/HTTPS 的 Maven 仓库——包括 `gradlePluginPortal()`、settings 里声明的、项目里声明的；
- ❌ Ivy 仓库、Maven local、flat directory 仓库、通过 S3 / GCS 提供的 Maven 仓库**不支持**镜像。

> [!Note]
>
> 这是 9.8.0 的新特性，**默认关闭**。它解决的是"公司有内网镜像，Maven 配了 Gradle 也要再配一遍"的运维负担。

## Exclusions and Capabilities

排除传递依赖：

```kotlin
dependencies {
    implementation("com.google.guava:guava:33.0.0-jre") {
        exclude(group = "com.google.code.findbugs", module = "jsr305")
    }
}
```

`exclude` 接受 `group` + `module`、或只用 `module` 排除整个 group。

**能力（capabilities）** —— 声明"这个依赖必须提供某项能力"，比 classifier 更灵活：

```kotlin
dependencies {
    implementation("org.apache.pdfbox:pdfbox:3.0.3") {
        capabilities { requireCapability("org.apache.pdfbox:pdfbox:3") }
    }
}
```

## Variant Aware Resolution

Gradle 的依赖解析是**变体感知（variant aware）**的——同一个模块的不同变体（`api` / `runtime` / 带 classifier 的）会分别解析。这是 Gradle 处理 Android（`aar` vs `jar`）和 Java module path 的基础。

实践含义：依赖树里同一个模块可能出现多次（不同 configuration 视角），这是正常的。

## Dependency Analysis

```shell
./gradlew :app:dependencies                    # 依赖树
./gradlew :app:dependencyInsight --dependency X  # 单个依赖的来源与选中理由
./gradlew buildHealth                          # 官方插件：发现不必要/缺失的依赖
```

`buildHealth` 插件能报告两类问题：

- **不必要依赖** —— 声明了但没用到；
- **缺失依赖** —— 用到了但没声明（用了传递依赖里的类，很危险——上游一改就崩）。

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)
- [Publishing and Security](/docs/CS/BuildTool/Gradle/Publishing_and_Security.md)
- [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)

## References

1. [Gradle — Declaring Dependencies](https://docs.gradle.org/current/userguide/declaring_dependencies.html)
2. [Gradle — Dependency Configurations](https://docs.gradle.org/current/userguide/declaring_dependencies.html#sub:dependency-types)
3. [Gradle — Resolving Conflicts Between Dependencies](https://docs.gradle.org/current/userguide/resolving_conflicts.html)
4. [Gradle — Locking Dependencies](https://docs.gradle.org/current/userguide/dependency_locking.html)
5. [Gradle — Centralizing Repositories](https://docs.gradle.org/current/userguide/declaring_repositories_basics.html)
