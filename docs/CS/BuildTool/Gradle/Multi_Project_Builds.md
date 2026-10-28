## Introduction

多项目构建（multi-project build）是 Gradle 相对 Maven 最有优势的场景——它靠**项目间依赖**（`project(":core")`）自动推导任务顺序，而不是靠 Maven 那套聚合器 + 依赖管理的间接机制。

但 Gradle 多项目的复杂度不在"怎么 include"，而在**配置的复用与隔离**：根项目 `subprojects {}` 块、`buildSrc`、`included build`、convention plugin——这四者能做什么、该用哪个，是最容易选错的地方。

## Settings File

`settings.gradle.kts` 是整个构建的**入口**，负责声明模块结构、仓库、插件管理。

```kotlin
rootProject.name = "platform"

include(":core")
include(":service")
include(":app")

// 带嵌套的模块路径
include(":libs:utils")

// 动态包含
include("modules:${listOf("a", "b", "c")}")
```

### Type-Safe Project Accessors

Gradle 7.0 起，`include` 声明的模块会生成类型安全访问器：

```kotlin
dependencies {
    implementation(projects.core)              // 而不是 project(":core")
    implementation(projects.libs.utils)          // 嵌套路径
}
```

比字符串写法好在：拼错了编译期就报错，IDE 能补全。

> [!Note]
>
> `settings.gradle.kts` 里还有几处职责，配置时容易漏：
>
> - `pluginManagement { repositories { ... } }` —— **插件从哪个仓库解析**。默认只有 `gradlePluginPortal()`，自建插件仓库必须在这里声明；
> - `dependencyResolutionManagement { repositories { ... } }` —— 依赖仓库的**集中声明**。设了 `repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)` 后，项目里再声明仓库会直接失败；
> - `versionCatalogs { ... }` —— 额外注册 catalog；
> - `buildCache { ... }` —— 远程构建缓存配置。

## Subprojects vs Allprojects

根项目里对所有子项目统一配置：

```kotlin
// ✅ 只对子项目生效（不含根项目）
subprojects {
    apply(plugin = "java")
    repositories { mavenCentral() }
}

// ⚠️ 包含根项目本身
allprojects {
    group = "com.example"
    version = "1.0.0"
}
```

**能用 `subprojects` 就别用 `allprojects`**——`allprojects` 会把 root project 也拽进来，而 root project 通常是纯容器（没有 `java` 插件），对它 `apply(plugin = "java")` 会得到一堆无意义的任务。

> [!Warning]
>
> `subprojects {}` 是**立即执行**的（在 configuration phase 里就作用于所有子项目），这会**破坏配置缓存的隔离性**，也会让所有子项目都被配置。Gradle 推荐用 **convention plugin** 替代（见下文）。

## buildSrc

`buildSrc` 是**自动包含的独立构建**，用来放项目自己的构建逻辑。

```
my-project/
├── buildSrc/
│   ├── build.gradle.kts
│   └── src/main/kotlin/
│       └── com/example/convention/
│           ├── java-convention.gradle.kts
│           └── kotlin-convention.gradle.kts
├── settings.gradle.kts
└── core/build.gradle.kts
```

特点：

- **自动包含**——不需要 `includeBuild`，Gradle 每次构建都会先构建它；
- **自动加入构建脚本的 classpath**——所以 `buildSrc` 里写的插件可以直接 `apply` 而不用声明依赖坐标；
- 优先级**高于**任何外部插件——`buildSrc` 里的类会遮蔽同名类。

```kotlin
// buildSrc/build.gradle.kts
plugins {
    `kotlin-dsl`
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.jetbrains.kotlin:kotlin-gradle-plugin:2.2.0")
}
```

```kotlin
// core/build.gradle.kts
plugins {
    id("com.example.java-convention")
}
```

### buildSrc vs included build

| | `buildSrc` | `includeBuild` |
| :--- | :--- | :--- |
| 包含方式 | **自动** | 需显式声明 |
| 能否发布给他人 | ❌ 只能本项目用 | ✅ 可独立发布 |
| 依赖其它项目的构建逻辑 | ❌ | ✅ |
| 适合 | 项目内部约定 | 跨项目共享的插件 |

**选择规则**：只是本项目要用的约定 → `buildSrc`；要发布给别的项目用、或需要依赖另一个项目的构建逻辑 → `includeBuild`。

## Included Builds

```kotlin
// settings.gradle.kts
includeBuild("build-logic")
includeBuild("../shared-plugins")
```

被包含的构建有自己的 `settings.gradle.kts`、自己的依赖、自己的插件。

**关键能力：替换依赖**。included build 可以**替换**主构建里的模块：

```kotlin
// build-logic/settings.gradle.kts
dependencySubstitution {
    substitute(module("com.example:core")).using(project(":core"))
}
```

这让"用本地源码替换已发布的构件"变得自然——开发时用本地版本，发布时用坐标。

**includeBuild 的代价**：它是一个**完全独立的构建**，有独立的 configuration phase 和缓存。这意味着**跨构建的 project 依赖无法共享配置缓存**，性能上有损失。

> [!Note]
>
> 这也是 `buildSrc` 存在的理由之一——`buildSrc` 虽然也是独立构建，但它被"内建"进主构建，共享一部分生命周期；`includeBuild` 则是真正隔离的。

## Convention Plugins

**Convention Plugin 是现代 Gradle 多项目的推荐做法**，用来替代 `subprojects {}`。

```kotlin
// buildSrc/src/main/kotlin/com/example/java-convention.gradle.kts
plugins {
    id("java-library")
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
    withSourcesJar()
}

tasks.withType<JavaCompile>().configureEach {
    options.encoding = "UTF-8"
    options.compilerArgs.add("-parameters")
}

dependencies {
    testImplementation(platform("org.junit:junit-bom:5.12.2"))
    testImplementation("org.junit.jupiter:junit-jupiter")
}
```

```kotlin
// core/build.gradle.kts
plugins {
    id("com.example.java-convention")
}

dependencies {
    implementation(libs.jackson.databind)
}
```

优势：

| | `subprojects {}` | Convention Plugin |
| :--- | :--- | :--- |
| 作用范围 | 作用于**所有**子项目 | 显式 `apply` 才生效 |
| 与配置缓存 | 破坏隔离 | 兼容 |
| 组合性 | 只能一份 | 可叠加多个约定插件 |
| 可测试性 | 差 | 独立、可单测 |
| 渐进迁移 | 难 | 逐模块迁移 |

**约定插件可以叠加**：

```kotlin
plugins {
    id("com.example.java-convention")
    id("com.example.spring-boot-convention")
    id("com.example.qa-convention")
}
```

这是它相对 `subprojects {}` 最大的优势——`subprojects {}` 里没法"叠加"多套约定。

### Precompiled Script Plugins

放在 `buildSrc/src/main/kotlin/` 下的 `.gradle.kts` 文件会被编译成插件，插件 id 就是**包名 + 文件名**：

```kotlin
// buildSrc/src/main/kotlin/com/example/java-convention.gradle.kts
```

→ 插件 id：`com.example.java-convention`

## Project Dependencies

```kotlin
dependencies {
    implementation(project(":core"))
    implementation(project(path = ":libs:utils"))
}
```

Gradle 会自动推导任务依赖：`:core` 的 `jar` 任务先跑，然后 `:app` 的 `compileJava` 才能跑。

**不需要显式声明任务顺序**——这是 Gradle 相对 Maven 的一处简化。

跨 included build 的依赖：

```kotlin
dependencies {
    implementation("com.example:core:1.0.0")   // 通常被 substitution 指向本地项目
}
```

## Task Ordering Across Projects

跨项目的任务顺序**只由依赖关系决定**，不靠约定。如果两个项目没有依赖关系但需要顺序，用：

```kotlin
tasks.named("check") {
    mustRunAfter(":core:check")
}
```

或者在根项目统一编排一个聚合任务：

```kotlin
tasks.register("checkAll") {
    dependsOn(subprojects.map { "${it.path}:check" })
}
```

> [!Note]
>
> `subprojects.map {}` 会**实例化所有子项目**，破坏惰性——这里因为是显式的聚合任务，影响有限；但如果只是为了设置一个属性，不该这么写。

## Gradle Version Catalog in Multi-Project

Version catalog 是**根项目级**的，所有子项目共享 `libs` 访问器。这正是它替代 Maven 根 POM `dependencyManagement` 的方式——都是"一处声明，全项目可见"。

需要按模块分组时，注册多个 catalog（见 [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)）。

## Common Structures

**共享库 + 多个应用**

```
platform/
├── buildSrc/              # convention plugins
├── libs/                  # 共享库
│   ├── common/
│   └── api/
├── services/
│   ├── user/
│   └── order/
└── apps/
    ├── web/
    └── worker/
```

**Gradle 官方推荐的分层**是：每层一个项目，`api` 项目定义稳定接口，`impl` 项目提供实现。跨层只依赖 `api`，不依赖 `impl`——这与 Gradle 的 `api` / `implementation` 配置天然对应。

## Links

- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)
- [Performance](/docs/CS/BuildTool/Gradle/Performance.md)
- [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)

## References

1. [Gradle — Multi-Project Builds](https://docs.gradle.org/current/userguide/multi_project_builds.html)
2. [Gradle — Structuring Projects](https://docs.gradle.org/current/userguide/structuring_projects.html)
3. [Gradle — Composite Builds](https://docs.gradle.org/current/userguide/composite_builds.html)
4. [Gradle — Convention Plugins](https://docs.gradle.org/current/userguide/build_logic.html)
5. [Gradle — Settings File](https://docs.gradle.org/current/userguide/settings_file.html)
