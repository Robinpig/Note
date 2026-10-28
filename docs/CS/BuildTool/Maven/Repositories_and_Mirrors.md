## Introduction

Maven 的配置分两个文件：**`settings.xml`**（机器级，配置仓库、镜像、凭据、代理）与 **`pom.xml`**（项目级，描述项目）。其中 `settings.xml` 是**唯一存放凭据的地方**——这是设计上就区分开的：POM 进版本库，凭据不进。

这一篇讲 `settings.xml` 的结构、镜像语义、profile 激活规则，以及那些"配置了却不生效"的经典陷阱。

## settings.xml

Maven 读取的 `settings.xml` 有两处，后者覆盖前者：

1. `${maven.home}/conf/settings.xml` —— 全局，Maven 安装目录；
2. `${user.home}/.m2/settings.xml` —— 用户级，**实际生效的那份**。

在 IDE 里（如 IntelliJ IDEA）还可以指定一份自定义路径。

骨架：

```xml
<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">

  <localRepository>${user.home}/.m2/repository</localRepository>

  <interactiveMode>false</interactiveMode>
  <offline>false</offline>
  <usePluginRegistry>false</usePluginRegistry>

  <mirrors>...</mirrors>
  <servers>...</servers>
  <proxies>...</proxies>
  <profiles>...</profiles>
  <activeProfiles>...</activeProfiles>
</settings>
```

`settings.xml` 的 namespace 版本随 Maven 演进：Maven 3 用 `1.0.0`，Maven 3.8+ 用 `1.1.0`，Maven 3.9+/4 用 `1.2.0`。**用旧版本号的 schema 声明在 Maven 3.10 下仍能解析，但新特性（如 `<aliases>`、`<repositoryOrigins>`）需要 1.2.0**。

### localRepository

本地仓库位置。CI 上常改成共享路径或 CI 缓存目录：

```xml
<localRepository>${env.M2_REPO}</localRepository>
```

注意 `-Dmaven.repo.local=...` 命令行参数优先级更高。

### Servers

`servers` 存放**仓库 id 对应的凭据**。关键规则是：**凭据的 `id` 必须与 `<repositories>` / `<pluginRepositories>` / `<mirrors>` 中声明的 `id` 精确匹配**。

```xml
<servers>
  <server>
    <id>nexus-releases</id>
    <username>${env.NEXUS_USER}</username>
    <password>${env.NEXUS_PASSWORD}</password>
  </server>
  <server>
    <id>nexus-snapshots</id>
    <username>${env.NEXUS_USER}</username>
    <password>${env.NEXUS_PASSWORD}</password>
  </server>
</servers>
```

> [!Warning]
>
> **绝不要把真实密码写进 `settings.xml` 并提交到版本库**。用环境变量引用（`${env.NEXUS_PASSWORD}`）或 Maven Encrypted Password（见 [Publishing and Signing](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md)）。IDE 里的 `settings.xml` 通常在 `~/Library/Application Support/JetBrains/<IDE>/options/maven/settings.xml`（macOS）。

> [!Note]
>
> **Maven 3.10.0 起，凭据按 origin（scheme + host + port）作用域化**，且 server id 精确匹配。这修掉了一个真实的安全问题：过去 `id="nexus"` 的凭据会被用于任何以 `nexus` 为前缀的 id（如 `nexus-163`、`nexus-snapshots`）对应的仓库——凭据可能泄漏给无关仓库。

**Maven 3.10.0 新增 `<aliases>`**，让一套凭据服务多个 server id：

```xml
<server>
  <id>central</id>
  <aliases>central-mirror,central-proxy</aliases>
  <username>${env.CENTRAL_USER}</username>
  <password>${env.CENTRAL_PASSWORD}</password>
</server>
```

同时新增 `<repositoryOrigins>`，显式声明这组凭据可用于哪些 origin：

```xml
<server>
  <id>internal</id>
  <repositoryOrigins>
    <repositoryOrigin>https://nexus.internal.corp</repositoryOrigin>
  </repositoryOrigins>
  <username>${env.NEXUS_USER}</username>
  <password>${env.NEXUS_PASSWORD}</password>
</server>
```

## Mirrors

Mirror 是仓库的**重定向层**。它不是"加速器"，而是"替换"——命中 mirror 的仓库请求全部改发到 mirror 指向的 URL。

```xml
<mirrors>
  <mirror>
    <id>aliyun-central</id>
    <name>Aliyun Public Mirror</name>
    <url>https://maven.aliyun.com/repository/public</url>
    <mirrorOf>central</mirrorOf>
  </mirror>
</mirrors>
```

### mirrorOf 语义

| `mirrorOf` 值 | 含义 |
| :--- | :--- |
| `central` | 只镜像 id 为 `central` 的仓库 |
| `*` | 镜像**所有**仓库（包括私有 Nexus） |
| `external:*` | 镜像所有不在 `localhost` / `127.0.0.1` 的仓库 |
| `external:http:*` | 镜像所有非本机的 http 仓库 |
| `repo1,repo2` | 镜像指定 id 的多个仓库 |
| `*,!repo1` | 镜像所有，但排除 `repo1` |
| `external:*,!internal` | 镜像所有外部仓库，排除 `internal` |

> [!Tip]
>
> **常见推荐配置**：`<mirrorOf>external:*,!internal-nexus</mirrorOf>` —— 外部仓库走镜像加速，本地/内网 Nexus 直连。这比 `*` 更安全，因为 `*` 会把内网私有仓库也重定向到公共镜像，导致私有制品拉不到（404）或凭据被发往外部地址。

**镜像只作用于 remote repository，不影响本地仓库**。它也不会影响 `install`——`install` 永远写本地仓库。

### Mirror 与 Repository 的优先级

Maven 处理仓库请求的顺序：

1. 请求（或 session）提供的仓库优先；
2. POM 中声明的仓库；
3. Super POM 默认的 `central`。

**镜像在仓库确定之后生效**——一个仓库被镜像后，它的 id 变成 mirror 的 id，凭据也要配在 mirror 的 id 上。

## Repositories

仓库声明分两处，作用不同：

- **`settings.xml` 的 `<profiles>` 里** —— 对**当前机器的所有项目**生效，适合"公司统一的私有仓库"；
- **POM 的 `<repositories>` 里** —— 对**所有使用这个项目的人**生效。

> [!Warning]
>
> **POM 里不该写公司内网仓库地址**。POM 是公开的（尤其要发到 Central 的库），写进去等于把内部拓扑泄露给所有使用者，而且使用者会直接连不上你的内网。正确做法是内网仓库只配在 `settings.xml`，POM 里只放 `<distributionManagement>`（发布目标）。

仓库声明：

```xml
<repositories>
  <repository>
    <id>internal</id>
    <url>https://nexus.internal.corp/repository/maven-public/</url>
    <releases>
      <enabled>true</enabled>
      <updatePolicy>never</updatePolicy>
    </releases>
    <snapshots>
      <enabled>true</enabled>
      <updatePolicy>always</updatePolicy>
    </snapshots>
  </repository>
</repositories>

<pluginRepositories>
  <pluginRepository>
    <id>internal</id>
    <url>https://nexus.internal.corp/repository/maven-public/</url>
    <releases><enabled>true</enabled></releases>
    <snapshots><enabled>false</enabled></snapshots>
  </pluginRepository>
</pluginRepositories>
```

### updatePolicy

控制 Maven 多久去远端检查一次"有没有新版本"：

| 值 | 行为 |
| :--- | :--- |
| `always` | 每次都检查 |
| `daily` | 每天检查一次（**默认值**） |
| `interval:HH` | 每 HH 小时检查一次 |
| `never` | 从不检查，只用本地缓存 |

`snapshots` 与 `releases` 各有独立的 `updatePolicy`。

> [!Note]
>
> **默认 `daily` 意味着 SNAPSHOT 的更新有最多 24 小时延迟**——CI 上用 `-U` 强制检查更新，可以绕过这个延迟。这是"CI 构建到了旧快照"的常见原因。
>
> Maven 3.10.0 提供了更细粒度的控制：`-UA`（只强制更新制品）、`-UM`（只强制更新元数据），以及 `--artifacts-update-policy=` / `--metadata-update-policy=`。

### Snapshots

Maven 默认**不会**下载 SNAPSHOT 依赖——除非仓库声明里 `<snapshots><enabled>true</enabled></snapshots>`。

SNAPSHOT 在仓库里的物理形态是带时间戳的：

```
1.0.0-SNAPSHOT/
├── artifact-1.0.0-20260101.120000-1.jar   ← 带时间戳和构建号
├── artifact-1.0.0-20260101.120000-1.pom
└── maven-metadata.xml                      ← 指向"最新"的那份
```

**这带来一个 notorious 的问题**：用 `maven-jar-plugin` 的 `useUniqueVersions=false` 可以去掉时间戳，让 jar 名固定为 `artifact-1.0.0-SNAPSHOT.jar`。但如果它和 `maven-shade-plugin` / `maven-assembly-plugin` 一起用，或依赖 `MANIFEST.MF` 里的 jar 名匹配，就会出现 `ClassNotFoundException`。

**根本解法**：不要在生产构建里依赖 SNAPSHOT，也不要靠 `useUniqueVersions` 打补丁——用 CI-friendly 版本 + 明确的 release 版本。

## Profiles

Profile 是**条件化的配置块**，可以出现在 `settings.xml` 或 `pom.xml` 中，包含 `<properties>`、`<dependencies>`、`<repositories>`、`<build>` 等。

```xml
<profiles>
  <profile>
    <id>dev</id>
    <activation>
      <activeByDefault>true</activeByDefault>
    </activation>
    <properties>
      <spring.profiles.active>dev</spring.profiles.active>
      <app.artifact.version>2.0.0-SNAPSHOT</app.artifact.version>
    </properties>
  </profile>

  <profile>
    <id>prod</id>
    <activation>
      <property>
        <name>env</name>
        <value>prod</value>
      </property>
    </activation>
    <properties>
      <spring.profiles.active>prod</spring.profiles.active>
      <app.artifact.version>1.9.0</app.artifact.version>
    </properties>
  </profile>
</profiles>
```

### Activation Conditions

| 激活方式 | 配置 | 语义 |
| :--- | :--- | :--- |
| 显式激活 | `-P prod` | 命令行指定 |
| 默认激活 | `<activeByDefault>true</activeByDefault>` | 无其它 profile 被显式激活时生效 |
| JDK 版本 | `<jdk>1.8</jdk>` / `<jdk>[17,)</jdk>` | 运行 Maven 的 JDK 匹配 |
| 操作系统 | `<os><family>unix</family></os>` | 匹配操作系统 |
| 属性存在 | `<property><name>!debug</name></property>` | **属性不存在**时激活（`!` 前缀取反） |
| 属性匹配 | `<property><name>env</name><value>prod</value></property>` | 属性存在且值相等 |
| 文件存在 | `<file><exists>${basedir}/Dockerfile</exists></file>` | 文件存在 |

### Activation Rules

几个反直觉但重要的规则：

1. **`activeByDefault` 的 profile 会被其它任何激活方式"挤掉"** —— 一旦命令行 `-P` 或属性激活了某个 profile，所有 `activeByDefault` 的 profile 全部失效；
2. **同一个 `<activation>` 里多个条件是 AND 关系**，多个 `<activation>` 元素之间是 OR 关系；
3. **POM 中的 profile 不能被 `settings.xml` 的同名 profile 覆盖**——`settings.xml` 的 profile 优先，同 id 时 settings 的内容生效；
4. **profile 里的 `<repositories>` 与 POM 顶层的 `<repositories>` 会被合并**，不是替换。

> [!Tip]
>
> 排查 profile 是否生效，用 `mvn help:active-profiles` 和 `mvn help:all-profiles`，再看 `mvn help:effective-pom` 的最终结果。

### The Order Trap

一个真实的坑：**当同一个 profile 被多个地方激活时（例如 `settings.xml` 里显式激活 + POM 里的 `activeByDefault`），它们的合并顺序会影响结果**。Maven 中，**`settings.xml` 的 profile 先被激活，POM 的 profile 后被激活，后激活的同 id 内容会覆盖先激活的**。

具体表现：`settings.xml` 里有个 profile 定义了 `<repositories>`，POM 里同名 profile 定义了 `<properties>`——两者的 `<properties>` 会合并，`<repositories>` 也会合并而不是互相覆盖。同理，**profile 内部 `<repositories>` 的合并顺序按 profile 声明顺序**。

## Proxies

需要在代理后面访问外网时：

```xml
<proxies>
  <proxy>
    <id>corp-proxy</id>
    <active>true</active>
    <protocol>http</protocol>
    <host>proxy.corp.com</host>
    <port>3128</port>
    <username>${env.PROXY_USER}</username>
    <password>${env.PROXY_PASSWORD}</password>
    <nonProxyHosts>localhost|127.0.0.1|*.internal.corp</nonProxyHosts>
  </proxy>
</proxies>
```

`nonProxyHosts` 用 `|` 分隔，支持 `*` 通配。**内网地址必须列进去**，否则内网 Nexus 请求也被走代理，导致拉包极慢或失败。

## Effective Settings

配置不生效时，先看最终形态：

```shell
mvn help:effective-settings
mvn help:effective-settings -Doutput=eff-settings.xml
```

同时检查 `~/.m2/` 下是否有 `settings.xml` 与 `settings-security.xml` 混淆，以及 IDE 是否指定了另一份 settings。

## Best Practices

1. **凭据只用环境变量引用**，不落明文；
2. **镜像用 `external:*,!internal`**，不要用裸 `*`；
3. **POM 里不写内网仓库地址**，只写 `distributionManagement`；
4. **`settings.xml` 的 schema 用 1.2.0**，以便用 `<aliases>` / `<repositoryOrigins>`；
5. **插件仓库和依赖仓库都配**，否则插件会直连 Central；
6. **profile 的 `activeByDefault` 只留一个**，多个会互相挤掉；
7. **CI 上用 `-U`**，避免 daily 策略导致拿到旧快照。

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Publishing and Signing](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md)
- [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)

## References

1. [Maven — Introduction to Settings](https://maven.apache.org/settings.html)
2. [Maven — Introduction to Repositories](https://maven.apache.org/guides/introduction/introduction-to-repositories.html)
3. [Maven — Guide to Mirrors](https://maven.apache.org/guides/mini/guide-mirrors.html)
4. [Maven — Introduction to Profiles](https://maven.apache.org/guides/introduction/introduction-to-profiles.html)
5. [Central Portal — OSSRH Sunset](https://central.sonatype.org/pages/ossrh-eol/)
