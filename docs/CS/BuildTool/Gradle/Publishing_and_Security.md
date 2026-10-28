## Introduction

Gradle 的发布链路与 Maven 有个关键差异：**Gradle 内置的 `maven-publish` 插件不能直接对接 Maven Central Publisher Portal**——因为 Central 不暴露标准的 Maven 仓库上传端点。这是从 Maven 迁到 Gradle 时最常见的发布失败原因。

另一方面，Gradle 在**依赖校验（dependency verification）**上做得比 Maven 完整——它同时支持 checksum 与 signature，是供应链安全的强力工具。

## maven-publish

基础配置：

```kotlin
// build.gradle.kts
plugins {
    `maven-publish`
}

group = "com.example"
version = "1.0.0"

publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["java"])
            artifactId = "demo"
            pom {
                name.set("Demo")
                description.set("Demo library")
                url.set("https://github.com/example/demo")
                licenses {
                    license {
                        name.set("The Apache License, Version 2.0")
                        url.set("https://www.apache.org/licenses/LICENSE-2.0.txt")
                    }
                }
                developers {
                    developer {
                        id.set("alice")
                        name.set("Alice")
                        email.set("alice@example.com")
                    }
                }
                scm {
                    url.set("https://github.com/example/demo")
                    connection.set("scm:git:https://github.com/example/demo.git")
                }
            }
        }
    }
}
```

`from(components["java"])` 会自动产出 **main jar + sources jar**（需要 `withSourcesJar()`）与对应的 POM。

### Publication Variants

Gradle 的发布单位是 **variant**（变体），不是 Maven 那种固定的几个 scope。默认会有 `java`（main）和 `java-test-fixtures` 等。

```kotlin
publishing {
    publications {
        create<MavenPublication>("maven") {
            from(components["java"])
        }
    }
}
```

`components["java"]` 会自动映射 POM 里的 `compile` / `runtime` scope。

### Repositories

```kotlin
publishing {
    repositories {
        maven {
            name = "internal"
            url = uri("https://nexus.internal.corp/repository/maven-releases/")
            credentials {
                username = providers.gradleProperty("nexusUser").get()
                password = providers.gradleProperty("nexusPassword").get()
            }
        }
    }
}
```

> [!Warning]
>
> **绝不要把凭据写死在构建脚本里**。用 `providers.gradleProperty(...)` 从 `gradle.properties`（且该文件不进版本库）或环境变量读取。

`gradle.properties` 里引用环境变量：

```properties
nexusUser=${env.NEXUS_USER}
nexusPassword=${env.NEXUS_PASSWORD}
```

### Publication Tasks

```shell
./gradlew publishToMavenLocal          # 发布到 ~/.m2/repository
./gradlew publishMavenPublicationToInternalRepository
./gradlew publish                     # 发布到所有配置的仓库
./gradlew publishToMavenLocal --scan
```

> [!Note]
>
> Gradle 9.8 起，**`maven-publish` 插件参与了 up-to-date 检查**——不再重复生成未变化的 POM。这是 9.8.0 明确列出的改进之一。

## Publishing to Maven Central

### The Problem

**Central Portal（2025-06-30 取代 OSSRH）不暴露标准的 Maven 仓库上传端点**。所以：

- `gradle-nexus-publish-plugin`（面向旧的 Nexus Staging API）**不工作**——它打的 `s01.oss.sonatype.org` 端点已不存在；
- Gradle 内置的 `maven-publish` 也**不能直接** `maven { url = central.sonatype.com }`。

### The Solution

用支持 Central Portal API 的插件：**`com.vanniktech:gradle-maven-publish-plugin`（0.29.0+）**。

```kotlin
plugins {
    id("com.vanniktech.maven.publish") version "0.34.0"
}

mavenPublishing {
    publishToMavenCentral()
    signAllPublications()
    coordinates("com.example", "demo")
    pom { ... }
}
```

它处理了：Portal API 调用、token 认证、自动 release。

### Manual Bundle Upload

另一条路是本地打包 + 上传：

```shell
./gradlew publishAllPublicationsToMavenRepository \
  -Pmaven.repo.local=build/staging
# 打包成 Central 要求的 bundle zip
# curl -u "$USER:$TOKEN" -H "Content-Type: application/octet-stream" \
#   -X POST --data-binary @bundle.zip \
#   https://central.sonatype.com/api/v1/publisher/upload
```

需要：命名空间已验证、全部产物 GPG 签名（含 POM）、sources + javadoc jar、POM 含 name/description/url/license/developers/scm。

**已发布版本不可变**——Central 有发布量限流（ASF 项目豁免）。

## Signing

```kotlin
signing {
    useInMemoryPgpKeys(System.getenv("SIGNING_KEY"), System.getenv("SIGNING_PASSWORD"))
    sign(publishing.publications)
}
```

或者用 keyring 文件：

```kotlin
signing {
    useGpgCmd()   // 走 gpg 命令行
    sign(publishing.publications)
}
```

`signAllPublications()` 是 vanniktech 插件的简写。

**CI 上的坑**：`gpg` 需要 pinentry 配置，否则会卡在密码输入。用 in-memory key 避开这个问题。

## Dependency Verification

这是 Gradle 相对 Maven 的**明显优势**。Gradle 支持两种互补机制：

| 机制 | 验证什么 | 弱点 |
| :--- | :--- | :--- |
| **Checksum** | 完整性（内容没被改） | 不保证来源真实 |
| **Signature** | 溯源（是谁发布的） | 可能用弱哈希算法 |

**两者都配才最强**。checksum 单独用只保证完整性；signature 单独用如果签名用了不安全哈希（哪怕 SHA-1），完整性评估就是错的。

### Enabling

文件位置固定：**`$PROJECT_ROOT/gradle/verification-metadata.xml`**。**文件一存在，验证就自动启用**，无需额外开关。

最小配置：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<verification-metadata>
  <configuration>
    <verify-checksums>true</verify-checksums>
    <verify-signatures>false</verify-signatures>
  </configuration>
</verification-metadata>
```

带签名：

```xml
<verification-metadata>
  <configuration>
    <verify-checksums>true</verify-checksums>
    <verify-signatures>true</verify-signatures>
  </configuration>
  <keyring format="armored">
    mQINBF...
  </keyring>
  <trusted-keys>
    <trusted-key id="6f538074ccebf35f28af9b066a0975f8b1127b83" group="org.apache.commons"/>
  </trusted-keys>
  <components>
    <component group="org.apache.commons" name="commons-lang3" version="3.17.0">
      <checksum value="..."/>
    </component>
  </components>
</verification-metadata>
```

**可信公钥 ID 必须是完整的 40 字符 fingerprint**——短 ID 和长 ID 都可以被碰撞。`ignored-keys` 元素例外（接受 fingerprint 或 64-bit 长 ID）。

公钥通常来自 keyserver：`https://keys.openpgp.org`、`https://keyserver.ubuntu.com`、`https://pgp.mit.edu`。

### Bootstrapping

```shell
./gradlew --write-verification-metadata sha256 help
./gradlew --write-verification-metadata pgp,sha256 --export-keys help
```

`--write-verification-metadata` 可带 checksum 类型列表（`sha256` 等）或 `pgp`（用于签名）。`--export-keys` 会额外生成 `gradle/verification-keyring.keys`（内置公钥）。

> [!Warning]
>
> **bootstrap 生成的元数据必须人工审查**。你的构建可能**已经**包含了被污染的依赖，Gradle 只是如实记录了现状。官方文档明确说："Whenever you bootstrap or update checksums and signatures, you should verify that you trust them."

两个文件都要提交进版本库：`gradle/verification-metadata.xml` + `gradle/verification-keyring.keys`。

### Scope

验证配置是**全局的**——一份文件管整个构建，包括所有子项目和 `buildSrc`。

用 included build 时，**当前构建的验证配置生效**，被包含构建自己的配置被忽略。这意味着引入一个新的 included build 类似于升级一个依赖——可能需要更新验证元数据。

### What Is Not Verified

- **SNAPSHOT 依赖** —— 内容本来就在变；
- **本地产出的制品**（如构建过程中生成的 jar）。

### Troubleshooting

验证失败时 Gradle 会生成 HTML 报告。CI 上不方便看报告时可以开 verbose 控制台输出：

```properties
org.gradle.dependency.verification.console=verbose
```

常见的"误报"：IDE 在 import 时自动下载 sources/javadoc，这些也会被验证。可以信任它们：

```xml
<verification-metadata>
  <components>
    <component group="com.example" name="demo">
      <trusting file-names=".*-sources.jar|.*-javadoc.jar"/>
    </component>
  </components>
</verification-metadata>
```

> [!Note]
>
> 信任 sources/javadoc 意味着它们**可能被篡改而不被发现**——这是明确的安全降级，只在确实被 IDE 阻塞时使用。

### Disabling for Specific Configurations

某些插件会解析你尚不知道版本的依赖（检查更新），这时验证不合理：

```kotlin
configurations.create("myConfiguration") {
    resolutionStrategy {
        disableDependencyVerification()
    }
}
```

Gradle 会对每个被禁用的 configuration 打印警告。

**关掉验证会降低安全性**——被篡改的元数据文件可能引入恶意的传递依赖。

## Gradle Security Subscription

2026-09 推出的付费订阅，在开源 EOL 策略之上提供：

- **SLA 保障的修复** —— critical 漏洞 7 天内、high 30 天内；
- **扩展安全维护** —— CVSS ≥ 7 的修复会 backport 到你当前用的版本（过去 12 个月内的 minor，或最多两个 major 之前）；
- **禁运披露** —— 公开披露前提前保密通知。

适合有合规要求、或生产系统锁在较老 Gradle 版本的团队。

## Dependency Locking

锁定依赖解析结果：

```properties
dependencyLocking { lockAllConfigurations() }
```

```shell
./gradlew dependencies --write-locks
```

这是**可重复构建**的关键手段——保证不同机器、不同时间解析出完全相同的依赖图。详见 [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)。

## Plugin Publish

发布 Gradle 插件到 Plugin Portal：

```kotlin
plugins {
    id("com.gradle.plugin-publish") version "1.3.0"
}

gradlePlugin {
    website = "https://github.com/example/plugin"
    vcsUrl = "https://github.com/example/plugin.git"
    plugins {
        create("demoPlugin") {
            id = "com.example.demo"
            implementationClass = "com.example.DemoPlugin"
            displayName = "Demo Plugin"
            description = "A demo"
            tags.set(listOf("demo"))
        }
    }
}
```

Gradle 9.8 起，Plugin Publish Plugin 支持在 `compatibility { features { ... } }` 块里声明 **Isolated Projects 与 Configuration Cache 支持**。声明后能在 Plugin Portal 获得徽章并提升搜索排名。

**注意**：`[plugins]` 版本约束只作用于 marker artifact，不锁实现模块的版本——详见 [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)。

## Links

- [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)
- [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)
- [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)
- [Maven](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md)

## References

1. [Gradle — Publishing Maven Publications](https://docs.gradle.org/current/userguide/publishing_maven.html)
2. [Gradle — Verifying Dependencies](https://docs.gradle.org/current/userguide/dependency_verification.html)
3. [Gradle — Signing Plugins](https://docs.gradle.org/current/userguide/signing.html)
4. [Central Portal — OSSRH Sunset](https://central.sonatype.org/pages/ossrh-eol/)
5. [Gradle — Publishing Plugins](https://docs.gradle.org/current/userguide/publishing_plugins.html)
