## Introduction

"发布一个 jar 到 Maven Central"这件事在 2025 年 6 月 30 日之后彻底变了：**OSSRH 已关停**，Central Publisher Portal 取而代之。这条变更让大量还在用 `nexus-staging-maven-plugin` + `oss.sonatype.org` 的 CI 脚本直接失败——很多项目是某天早上突然构建挂了才发现的。

这一篇覆盖当前的发布链路、签名要求、以及版本号推进的工程实践。

## The Publishing Path

发布的核心是 `deploy` 阶段，它把 `install` 的产物从本地仓库推到远程仓库。

```xml
<distributionManagement>
  <repository>
    <id>internal-releases</id>
    <url>https://nexus.internal.corp/repository/maven-releases/</url>
  </repository>
  <snapshotRepository>
    <id>internal-snapshots</id>
    <url>https://nexus.internal.corp/repository/maven-snapshots/</url>
  </snapshotRepository>
</distributionManagement>
```

关键规则：**Maven 根据当前版本号自动选择**——SNAPSHOT 结尾走 `snapshotRepository`，否则走 `repository`。这意味着**两套仓库必须同时配**，只配 release 会在 `mvn deploy` 时报 "repository element was not specified in the POM inside distributionManagement"。

对应的 `settings.xml` 里要有同名 id 的 `<server>` 提供凭据。

## Maven Central: OSSRH Is Dead

### What Changed

| | 旧 OSSRH | 新 Central Publisher Portal |
| :--- | :--- | :--- |
| 入口 | `oss.sonatype.org` | `central.sonatype.com` |
| 命名空间申请 | 提 JIRA 工单，人工审核 | 自助验证（DNS TXT / GitHub 仓库） |
| 暂存机制 | Nexus staging 仓库 + `close`/`release` | 上传 bundle → 自动校验 → UI 点 Publish |
| 凭据 | JIRA 用户名/密码 | Portal 生成的 User Token |
| API | Nexus Staging REST | Central Publisher API |
| 状态 | **2025-06-30 关停** | 现役 |

所有 OSSRH 命名空间已自动迁移到 Portal，登录 `central.sonatype.com` 用原账号即可看到。

### Three Ways to Publish

**方式一：Central Publishing Maven Plugin（推荐，Maven 生态首选）**

```xml
<plugin>
  <groupId>org.sonatype.central</groupId>
  <artifactId>central-publishing-maven-plugin</artifactId>
  <version>0.11.0</version>
  <extensions>true</extensions>
  <configuration>
    <publishingServerId>central</publishingServerId>
    <autoPublish>false</autoPublish>
  </configuration>
</plugin>
```

```shell
mvn deploy
```

插件自动完成：生成 bundle → 上传 → 等待校验 → 提交发布。`autoPublish=false` 时需要到 Portal UI 手动点 Publish（`USER_MANAGED` 模式，适合有审核流程的团队）。

**方式二：OSSRH Staging API 兼容层**

官方保留了兼容层，把部分 Nexus 2 API 翻译成 Portal API。改动最小：生成 Portal User Token，把插件的 URL 指到兼容服务。

```xml
<plugin>
  <groupId>org.sonatype.plugins</groupId>
  <artifactId>nexus-staging-maven-plugin</artifactId>
  <version>1.6.13</version>
  <extensions>true</extensions>
  <configuration>
    <serverId>ossrh</serverId>
    <nexusUrl>https://ossrh-staging-api.central.sonatype.com/</nexusUrl>
  </configuration>
</plugin>
```

**方式三：Bundle 上传 / 直接调 API**

先在本地生成 bundle zip，再用 `curl` 上传：

```shell
curl -u "$CENTRAL_USER:$CENTRAL_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -X POST --data-binary @central-bundle.zip \
  https://central.sonatype.com/api/v1/publisher/upload
```

**Gradle 注意**：`gradle-nexus-publish-plugin` 与 Gradle 内置 `maven-publish` 都不能直接对接 Portal（Central 不暴露标准 Maven 仓库上传端点）。需要用 `vanniktech/maven-publish`（0.29.0+）这类支持 Portal API 的插件。

## Central Requirements

发布到 Central 的每个版本必须满足：

**1. 命名空间已验证**

groupId 必须归属你。最常见的是自有域名（`com.example` → 在域名加 DNS TXT 记录）或 GitHub（`io.github.user` → 建一个临时同名公开仓库）。

**2. 所有产物 GPG 签名**

不只是 jar——**主 jar、sources jar、javadoc jar、POM 全部要签**。

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-gpg-plugin</artifactId>
  <version>3.2.8</version>
  <executions>
    <execution>
      <id>sign-artifacts</id>
      <phase>verify</phase>
      <goals><goal>sign</goal></goals>
    </execution>
  </executions>
  <configuration>
    <gpgArguments>
      <arg>--pinentry-mode</arg>
      <arg>loopback</arg>
    </gpgArguments>
  </configuration>
</plugin>
```

`--pinentry-mode loopback` 是关键——CI 环境没有 TTY，缺少它 GPG 会卡在密码输入。

**3. 完整的 POM 元数据**

必须包含：`name`、`description`、`url`、`license`、`developers`、`scm`。

```xml
<licenses>
  <license>
    <name>Apache License, Version 2.0</name>
    <url>https://www.apache.org/licenses/LICENSE-2.0.txt</url>
    <distribution>repo</distribution>
  </license>
</licenses>

<developers>
  <developer>
    <id>alice</id>
    <name>Alice</name>
    <email>alice@example.com</email>
  </developer>
</developers>

<scm>
  <connection>scm:git:https://github.com/example/demo.git</connection>
  <developerConnection>scm:git:https://github.com/example/demo.git</developerConnection>
  <url>https://github.com/example/demo</url>
</scm>
```

**4. 三个 jar 齐全**

主 jar + `-sources.jar` + `-javadoc.jar`。

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-source-plugin</artifactId>
  <version>3.4.0</version>
  <executions>
    <execution>
      <id>attach-sources</id>
      <goals><goal>jar-no-fork</goal></goals>
    </execution>
  </executions>
</plugin>

<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-javadoc-plugin</artifactId>
  <version>3.12.0</version>
  <executions>
    <execution>
      <id>attach-javadocs</id>
      <goals><goal>jar</goal></goals>
    </execution>
  </executions>
</plugin>
```

用 `jar-no-fork` 而不是 `jar`，避免 fork 出新的生命周期导致签名顺序错乱。

### Immutability

**已发布的版本不能被删除、修改或覆盖。** 修错了只能发新版本。这是"release 版本必须不可变"的强制机制，也是为什么不该用 SNAPSHOT 版本号发布正式版。

### Rate Limiting

Central 对发布量做了限流，并提供付费的 Pro 档位提高上限。**Apache 基金会的孵化器与顶级项目不受此限**。国内一些社区项目（如 Dromara 统一使用的 `org.dromara` groupId）可能需要迁到个人命名空间下以避免发布中断。

## Version Bumping

`maven-release-plugin` 自动化版本推进：

```shell
mvn release:prepare          # 改版本号、打 tag、推 tag
mvn release:perform          # 构建并 deploy
```

`release:prepare` 会：把 `${revision}` 替换为 release 版本、更新依赖引用、提交、打 tag、推送。

配合 CI-friendly 版本：

```xml
<version>${revision}</version>
<properties>
  <revision>1.0.0-SNAPSHOT</revision>
</properties>
```

```shell
mvn release:prepare -Drevision=1.1.0
```

release plugin 会问几个交互问题，CI 上要用 `-Darguments=...` 或 `batchMode` 配置。

## Maven Encrypted Password

Maven 3.10.0 的新特性之一是**基于 `mvnenc` 的加密系统**，用于加密 `settings.xml` 中的密码，支持外部 Vault。

```shell
mvn --encrypt-password
mvn --encrypt-master-password
```

工作方式：生成 master password → 加密目标密码 → 密文写进 `settings.xml` → `settings-security.xml` 存 master password。

```xml
<server>
  <id>internal</id>
  <password>{encrypted-value}</password>
</server>
```

master password 本身也要保护——CI 上通常用 Vault 或 KMS 注入，或用 `maven-encryption` 的 Vault 后端。

## Reproducible Artifacts

发布物应当可重复构建：同样的源码 + 同样的依赖 = 同样的字节。Maven 3.10.0 起 Reproducible Builds 默认启用（Super POM 给 `project.build.outputTimestamp` 提供了默认值）。

显式设置更好：

```xml
<properties>
  <project.build.outputTimestamp>2026-01-01T00:00:00Z</project.build.outputTimestamp>
</properties>
```

CI 上用 `SOURCE_DATE_EPOCH` 覆盖即可。

## Release Checklist

发布前逐项确认：

- [ ] 命名空间已验证（DNS TXT / GitHub 仓库）
- [ ] GPG 密钥已上传到 `keys.openpgp.org` 并被 Central 确认
- [ ] 主 jar / sources jar / javadoc jar 三件套齐全
- [ ] 全部产物已签名（`mvn verify` 后检查 `target/*.asc`）
- [ ] POM 含 name / description / url / license / developers / scm
- [ ] 版本号不是 SNAPSHOT
- [ ] `dependencyManagement` 里没有动态版本
- [ ] `mvn dependency:analyze` 无 "Used undeclared"
- [ ] 本地 `mvn clean install` 全绿

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Repositories and Mirrors](/docs/CS/BuildTool/Maven/Repositories_and_Mirrors.md)
- [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)

## References

1. [Central Portal — OSSRH Sunset](https://central.sonatype.org/pages/ossrh-eol/)
2. [Central Portal — Publishing to the Central Portal](https://central.sonatype.org/publish/publish-portal-guide/)
3. [Central Portal — Requirements](https://central.sonatype.org/publish/requirements/)
4. [central-publishing-maven-plugin](https://central.sonatype.org/publish/publish-portal-maven/)
5. [maven-gpg-plugin](https://maven.apache.org/plugins/maven-gpg-plugin/)
6. [maven-release-plugin](https://maven.apache.org/plugins/maven-release-plugin/)
