## Introduction

Version Catalog 是 Gradle 7.0 引入的实验特性，现在已是**多项目工程管理依赖版本的默认方案**。它把坐标、版本、插件版本集中到一份 TOML 文件，构建脚本里用**类型安全访问器**引用。

它解决的问题很具体：多模块项目里，版本号散落在十几个 `build.gradle.kts` 里，改一个版本要翻十几处；手写坐标字符串又容易打错。

## Basic Usage

默认位置是**根项目的 `gradle/libs.versions.toml`**，Gradle 自动加载并生成名为 `libs` 的访问器：

```toml
[versions]
groovy = "3.0.22"
jackson = "2.18.2"

[libraries]
groovy-core = { module = "org.code.groovy:groovy", version.ref = "groovy" }
groovy-json = { module = "org.code.groovy:groovy-json", version.ref = "groovy" }
jackson-databind = { module = "com.fasterxml.jackson.core:jackson-databind", version.ref = "jackson" }
commons-lang3 = { group = "org.apache.commons", name = "commons-lang3", version = "3.17.0" }

[bundles]
groovy = ["groovy-core", "groovy-json"]

[plugins]
versions = { id = "com.github.ben-manes.versions", version = "0.51.0" }
```

构建脚本里：

```kotlin
dependencies {
    implementation(libs.groovy.core)
    implementation(libs.jackson.databind)
    implementation(libs.commons.lang3)
    implementation(libs.bundles.groovy)
}

plugins {
    alias(libs.plugins.versions)
}
```

## The Four Sections

| Section | 作用 | 生成访问器 |
| :--- | :--- | :--- |
| `[versions]` | 版本标识符 | `libs.versions.<name>` |
| `[libraries]` | 别名 → GAV 坐标 | `libs.<alias>` |
| `[bundles]` | 依赖组合 | `libs.bundles.<name>` |
| `[plugins]` | 插件 id + 版本 | `libs.plugins.<name>` |

## Alias Rules

别名由**连字符 `-`、下划线 `_`、点 `.`** 分隔，生成访问器时统一规范化为点表示法：

| 别名 | 访问器 |
| :--- | :--- |
| `groovy-core` | `libs.groovy.core` |
| `groovy_core` | `libs.groovy.core` |
| `androidx.awesome.lib` | `libs.androidx.awesome.lib` |
| `groovyCore` | `libs.groovyCore`（camelCase，**不生成子组**） |

**建议用 camelCase** 避免子组访问器——因为带点的别名会生成子组结构，容易撞名。

### Reserved Names

以下关键词是保留字，不能用作别名：`extensions`、`class`、`convention`。另外 `bundles`、`versions`、`plugins` 不能作为依赖别名的**首个子组**——`versions-dependency` 非法，`versionsDependency` 或 `dependency-versions` 合法。

### Avoiding Subgroup Accessors

如果同时有 `jackson` 和 `jackson-databind` 两个别名，`libs.versions.jackson` 会**解析成子组访问器**（因为 `jackson-databind` 创造了 `jackson.databind` 子组），而不是版本本身。

取父版本要用 `asProvider()`：

```kotlin
val jacksonVersion = libs.versions.jackson.asProvider()
```

## Rich Versions

版本可以只写字符串（视为 `require`），也可以写成 rich version：

```toml
[versions]
other-lib = "5.5.0"                                    # require
my-lib = { strictly = "[1.0, 2.0[", prefer = "1.2" }  # rich
```

支持的成员：

| 成员 | 含义 |
| :--- | :--- |
| `require` | 要求的版本 |
| `strictly` | 严格版本（区间或精确值） |
| `prefer` | 偏好版本（在区间内优先选它） |
| `reject` | 拒绝的版本列表 |
| `rejectAll` | 布尔，拒绝所有版本 |

`strictly` 用 Maven 风格的区间语法：`"[1.0, 2.0["` 表示 `[1.0, 2.0)`——**左闭右开**。

组合示例：

```toml
[libraries]
commons-lang3 = { group = "org.apache.commons", name = "commons-lang3",
                  version = { strictly = "[3.8, 4.0[", prefer = "3.17.0" } }
```

含义：版本必须在 `[3.8, 4.0)` 区间内，且优先选 3.17.0。如果别的依赖要求 3.5.0（不在区间内），**构建失败**而不是静默降级。

## version.ref

引用 `[versions]` 里声明的版本：

```toml
[versions]
common = "1.4"

[libraries]
my-lib = { group = "com.mycompany", name = "mylib", version.ref = "common" }
```

## Bundles

把常用组合打包成一个别名：

```toml
[versions]
groovy = "3.0.22"

[libraries]
groovy-core = { group = "org.code.groovy", name = "groovy", version.ref = "groovy" }
groovy-json = { group = "org.code.groovy", name = "groovy-json", version.ref = "groovy" }
groovy-nio = { group = "org.code.groovy", name = "groovy-nio", version.ref = "groovy" }

[bundles]
groovy = ["groovy-core", "groovy-json", "groovy-nio"]
```

```kotlin
dependencies {
    implementation(libs.bundles.groovy)
}
```

## Plugins Section

```toml
[plugins]
versions = { id = "com.github.ben-manes.versions", version = "0.51.0" }
spotless = { id = "com.diffplug.spotless", version = "3.7.0" }
```

```kotlin
plugins {
    alias(libs.plugins.versions)
    alias(libs.plugins.spotless)
}
```

> [!Warning]
>
> **不能在 `settings.gradle.kts` 或 settings 插件里使用 version catalog 里的插件**。只能在项目的 `build.gradle.kts` 的 `plugins {}` 块里用 `alias()`。

### A Real Limitation

`[plugins]` 条目上的版本约束**只约束插件的 marker artifact 坐标**（`plugin.id:plugin.id.gradle.plugin`），**不约束真正实现插件的那个模块**。

因为 marker 自身对实现模块的依赖不受该约束影响，**另一个插件传递引入的同一实现模块的不同版本可能仍然赢得冲突解决**。

要真正锁定实现模块的版本，需要**直接在 buildscript classpath 上对实现模块的坐标加约束**（或 enforced platform），而不是依赖 catalog 的插件版本。

## Multiple Catalogs

默认的 `libs` 之外可以注册多个 catalog：

```kotlin
// settings.gradle.kts
versionCatalogs {
    create("tools") {
        from(files("gradle/tools.versions.toml"))
    }
    create("testLibs") {
        from(files("gradle/test.versions.toml"))
    }
}
```

```kotlin
dependencies {
    implementation(libs.guava)
    implementation(tools.errorprone.annotations)
    testImplementation(testLibs.junit.api)
}
```

**但每个 catalog 只能调用一次 `from()`**：

```kotlin
versionCatalogs {
    create("libs") {
        from(files("gradle/base.versions.toml"))
        from(files("gradle/extras.versions.toml"))   // ❌ Error!
    }
}
```

需要合并多个文件时，在 TOML 层面合并，或用一个目录 + 符号链接。

**命名建议**：用唯一名字避免冲突，实践中以 `Libs` 结尾是个好习惯（如 `testLibs`）。每个 catalog 会生成一个**应用到所有项目**的 extension，名字冲突会出问题。

## Programmatic Catalogs

除了 TOML，也可以在 `settings.gradle.kts` 里用方法调用构建：

```kotlin
versionCatalogs {
    create("libs") {
        version("groovy", "3.0.22")
        library("groovy-core", "org.code.groovy", "groovy").versionRef("groovy")
    }
}
```

TOML 是推荐方式——IDE 支持更好、可读性更强。

## TOML Format Limitations

TOML 目录格式**不支持**以下属性：

- `classifier` 属性；
- `type = "aar"` 或 `ext = "zip"` 这类 artifact type；
- `exclude` 规则；
- capabilities 与 requirements。

这些的变通办法：

| 需求 | 变通 |
| :--- | :--- |
| classifier | 在构建脚本里用标准依赖 DSL 声明 |
| artifact type | 同上 |
| exclude / capabilities | 在声明依赖的地方用标准 DSL |

## Verification

```shell
./gradlew dependencies          # 看解析结果
./gradlew buildEnvironment      # 看 buildscript 依赖
```

**目录只影响声明，不影响解析**。catalog 里写的版本，解析出来的可能更高——如果某个传递依赖要求更高版本，Gradle 会选高的。这一点与 Maven 的 `dependencyManagement` 类似。

## Links

- [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)
- [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)
- [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)
- [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)

## References

1. [Gradle — Version Catalogs](https://docs.gradle.org/current/userguide/version_catalogs.html)
2. [Gradle — Sharing Dependencies Between Projects](https://docs.gradle.org/current/userguide/platforms.html)
