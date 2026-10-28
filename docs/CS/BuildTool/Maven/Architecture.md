## Introduction

Maven 的核心不是"执行命令"，而是**把一个项目描述成一份可被机器读取的模型（Project Object Model, POM）**，然后由统一的生命周期驱动插件把这份模型变成产物。所有命令行为最终都可以回溯到三件事：**模型长什么样、生命周期有哪些阶段、插件绑定在哪些阶段上**。

这一篇先建立"坐标 → 仓库 → 制品"这条主干：Maven 用什么标识一个制品、用什么把它取回来、以及为什么"约定优于配置"（Convention over Configuration）能成立。后续分册在此之上分别展开依赖解析、生命周期、多模块、仓库配置、发布、性能排障与 Maven 4 迁移。

## Coordinates

一个制品由三段坐标唯一标识：

```
groupId:artifactId:version
```

- **groupId** —— 组织或领域标识，惯例是反向域名（`org.apache.maven`）或 `io.github.<user>`；
- **artifactId** —— 该组织内的模块名，jar 文件名默认取它；
- **version** —— 版本号。

坐标到文件路径的映射是机械的：`groupId` 中的点换成斜杠，`artifactId` 和 `version` 各成一个目录。例如 `org.apache.commons:commons-lang3:3.17.0` 落在：

```
~/.m2/repository/org/apache/commons/commons-lang3/3.17.0/
├── commons-lang3-3.17.0.jar
├── commons-lang3-3.17.0.pom
├── commons-lang3-3.17.0.jar.sha1
└── commons-lang3-3.17.0.jar.asc
```

这种"坐标即路径"的设计让本地仓库成为**无需数据库的扁平内容寻址缓存**：任何时候删掉整个 `~/.m2/repository` 都能从远端完整重建，代价只是重新下载。

> [!Note]
>
> 仓库里同时存 `.pom` 文件——它不是元数据附件，而是**同一制品的另一份产物**。Maven 读 POM 才能知道这个 jar 的传递依赖、parent 和 plugin 配置。这也解释了为什么拉一个 jar 常常会连带拉几十个 POM。

### Classifier

坐标三段不足以覆盖全部场景，因此还有第四个可选维度 **classifier**。它不是坐标的一部分，而是挂在坐标之下的一组附加产物：

- `sources` —— 源码 jar（`commons-lang3-3.17.0-sources.jar`）；
- `javadoc` —— API 文档 jar；
- `linux-x86_64` —— 平台相关的本地库（如 netty、snappy）。

classifier 的两个常见误区：

1. **它不是版本**。`1.0-linux-x86_64` 与 `1.0` 是两个不同制品，不是同一制品的两份文件；
2. **不能用它做条件依赖**。Maven 没有"按 OS/架构挑 classifier"的原生机制，需要 `os-maven-plugin` 之类的扩展提供 `${os.detected.classifier}` 这类属性。

## Repositories and Artifacts

Maven 的仓库模型只有三类实体，角色完全不同：

| 实体 | 是什么 | 典型位置 | 谁能写 |
| :--- | :--- | :--- | :--- |
| **Local Repository** | 本地缓存，一次下载后不再访问远端 | `~/.m2/repository` | 本地构建写入 |
| **Remote Repository** | 制品的权威来源，只读 | Maven Central、Nexus、Artifactory | 只有发布方能写 |
| **Repository Manager** | 代理 + 聚合 + 权限管控的服务端 | 团队内网 Nexus | 管理员写入 |

区分后两者很关键：**Remote Repository 是"源"，Repository Manager 是"缓存 + 代理 + 闸门"**。公司内 Nexus 之所以存在，通常不是因为制品放在那里，而是因为它同时承担了"代理 Maven Central 加速"、"聚合多个上游"、"统一鉴权"、"记录谁拉了什么"四件事。

仓库在 POM 里的声明分两级：

- `<repositories>` —— 拉**依赖**的仓库；
- `<pluginRepositories>` —— 拉**插件**的仓库。

两者是完全独立的通道。常见事故是只配了前者，导致依赖都走了镜像而插件仍去直连 Central，CI 上偶发超时。

## The Super POM

每个 POM 隐式继承一份内置的 **Super POM**（`maven-model-builder` 里的 `pom-4.0.0.xml`）。它定义了：

- 默认的仓库与插件仓库（即 Maven Central）；
- 默认的 `packaging`（`jar`）；
- 默认的源码/资源目录（`src/main/java`、`src/main/resources` 等）；
- 插件的默认版本绑定；
- 默认的构建目录（`${project.build.directory}` = `target`）。

Super POM 是"约定优于配置"的物理载体：**没有任何配置的项目也能构建**，因为目录结构、生命周期绑定、仓库都已经是约定好的。

两个必须知道的变化：

- **Maven 3.10.0 起 Super POM 默认 `project.build.sourceEncoding` 与 `project.reporting.outputEncoding` 为 UTF-8**，并**移除了默认的 `pluginManagement` 和废弃的 `release` profile**。含义是：升级到 3.10 后编码问题自愈，但依赖 Super POM 默认插件版本的写法会失效——**必须显式锁定插件版本**；
- **Maven 4 引入 Model 4.1.0 与 Build/Consumer POM 分离**，Super POM 的作用被进一步弱化，见 [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)。

## POM Anatomy

一份典型 POM 的骨架：

```xml
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>

  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.outputTimestamp>2026-01-01T00:00:00Z</project.build.outputTimestamp>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>2.0.17</version>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.15.0</version>
      </plugin>
    </plugins>
  </build>
</project>
```

各段的职责边界：

- **`<properties>`** —— POM 内唯一的变量定义处，可被引用；也可以由命令行 `-Dkey=value` 覆盖。CI-friendly 版本方案（`${revision}` / `${changelist}`）正是靠这一段实现。
- **`<dependencyManagement>`** —— 只声明版本，不引入依赖本身；它才是多模块项目统一版本的正确位置，详见 [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)。
- **`<build>`** —— 打包期配置（插件、目录、资源过滤）；`<build><pluginManagement>` 与 `<plugins>` 的区别是本页最常见的错误来源。
- **`<profiles>`** —— 条件化配置；同一段 XML 可以有多个候选分支，但激活逻辑有严格优先级，见 [Repositories and Mirrors](/docs/CS/BuildTool/Maven/Repositories_and_Mirrors.md)。

### Packaging

`<packaging>` 决定用哪套插件去处理产物，也是"该用什么生命周期"的选择器：

| packaging | 产物 | 生命周期绑定要点 |
| :--- | :--- | :--- |
| `jar` | `.jar` | 默认值，`compile` + `test` + `package` |
| `war` | `.war` | 增加 `webapp` 目录约定 |
| `pom` | 仅 POM 文件 | 只跑 `install` / `deploy`，不编译不打包 |
| `maven-plugin` | jar + 插件描述符 | 额外跑 `plugin` 生命周期，生成 `plugin.xml` |
| `bundle` | OSGi bundle | 需 `maven-bundle-plugin` |
| `ejb` / `ear` | 企业级产物 | 遗留场景，基本被 Spring Boot 取代 |

`pom` packaging 是**聚合器与 parent 的标准形态**：它既是 `<modules>` 所在的项目（aggregator），也常是 `<parent>` 所在的项目，但这两个角色可以分开——一个纯 parent 不必同时聚合模块。

## Effective POM

写 POM 时经常"不知道最终生效的值是什么"。`mvn help:effective-pom` 把继承、插值、profile 激活、Super POM 全部合并后打印出来，是排查"我明明配了却没生效"的唯一可靠手段：

```shell
mvn help:effective-pom > effective.xml
mvn help:effective-settings        # 看 settings.xml 最终形态
mvn help:evaluate -Dexpression=project.version -q -DforceStdout
```

`help:evaluate` 的 `-DforceStdout` 很关键——不加它会把结果混进 Maven 的日志噪声里。

## Version Baseline

| 组件 | 版本 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| Maven 4 | `4.0.0-rc-7` | RC，2026-09-24 | 需 JDK 17+ 运行；Model 4.1.0、Consumer POM |
| Maven 3 | `3.10.0` | GA，2026-09-27 | 需 JDK 8+ 运行；与 Maven 4 共用 Resolver 2.0 |
| Maven 3 | `3.9.16` | GA，2026-05-13 | 3.9 系列末版 |
| Maven Daemon | `mvnd` 1.0.3 | GA | 独立进程守护加速；2.x 为预览 |
| Maven Resolver | `2.0.24` | 随 3.10.0 引入 | 3.10 与 4 共用同一 lineage |

官方维护策略是**只维护最近两个 GA 系列的最新版本**；插件提供的 Maven API 兼容下限为 `3.9.0`。

## Links

- [Maven](/docs/CS/BuildTool/Maven.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)

## References

1. [Maven — Introduction to the POM](https://maven.apache.org/guides/introduction/introduction-to-the-pom.html)
2. [Maven — Introduction to Repositories](https://maven.apache.org/guides/introduction/introduction-to-repositories.html)
3. [Maven — The Super POM](https://maven.apache.org/maven-model-builder/super-pom.html)
4. [Maven Releases History](https://maven.apache.org/docs/history.html)
