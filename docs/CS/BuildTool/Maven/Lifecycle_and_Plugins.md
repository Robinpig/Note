## Introduction

Maven 的执行模型只有两个概念：**Lifecycle（生命周期）** 和 **Phase（阶段）**。生命周期是容器，阶段是有序的步骤；**插件目标（goal）绑定到阶段上**，构建时按阶段顺序调用。

这套模型最反直觉的一点是：**你几乎从不直接调用 goal**。`mvn test` 调的是阶段，阶段触发一串 goal。反过来，`mvn dependency:tree` 这种写法是**直接调用 goal**——不经过生命周期，因此也不会触发任何前置阶段。

## Three Lifecycles

Maven 内置三条生命周期，分别服务于构建、测试报告和文档：

| 生命周期 | 阶段数 | 用途 |
| :--- | :--- | :--- |
| `default` | 23 | 编译、测试、打包、安装、部署——**日常唯一用到的** |
| `clean` | 3 | 清理 `target/` |
| `site` | 4 | 生成与发布项目站点文档 |

三条生命周期**互相独立**。`mvn clean install` 是先跑 clean 生命周期的 `clean` 阶段，再跑 default 生命周期的 `install` 阶段——不是"在 default 里插一步 clean"。

> [!Note]
>
> Maven 3.10.0 起，site 生命周期可以通过系统属性 `maven.site.lifecycle.disabled` 从默认生命周期中移除。对以发布文档为目的的现代项目，`site` 已被 Maven Site Plugin 与替代工具（DocFX、mkdocs、Antora）边缘化。

## Clean Lifecycle

| Phase | Description |
| :--- | :--- |
| `pre-clean` | 执行清理前的准备 |
| `clean` | 删除上一次构建生成的所有文件（默认 `target/`） |
| `post-clean` | 清理后的收尾 |

`clean` 默认绑定 `maven-clean-plugin:clean`，目标属性是 `${project.build.directory}`。

## Default Lifecycle

| Phase | Description | 典型绑定 |
| :--- | :--- | :--- |
| `validate` | 校验项目模型正确、信息齐备 | — |
| `initialize` | 初始化构建状态 | — |
| `generate-sources` | 生成源码 | — |
| `process-sources` | 处理源码（过滤、插值） | — |
| `generate-resources` | 生成资源 | — |
| `process-resources` | 复制并处理资源到输出目录 | `resources:resources` |
| `compile` | 编译主源码 | `compiler:compile` |
| `process-classes` | 后处理编译产物（字节码增强） | — |
| `generate-test-sources` | 生成测试源码 | — |
| `process-test-sources` | 处理测试源码 | — |
| `generate-test-resources` | 生成测试资源 | — |
| `process-test-resources` | 复制测试资源 | `resources:testResources` |
| `test-compile` | 编译测试源码 | `compiler:testCompile` |
| `process-test-classes` | 后处理测试字节码 | — |
| `test` | 运行单元测试 | `surefire:test` |
| `prepare-package` | 打包前准备 | — |
| `package` | 打包成可发布格式 | `jar:jar` / `war:war` |
| `pre-integration-test` | 集成测试前准备（启动容器等） | — |
| `integration-test` | 运行集成测试 | `failsafe:integration-test` |
| `post-integration-test` | 集成测试后清理环境 | `failsafe:verify` |
| `verify` | 校验产物是否满足质量标准 | — |
| `install` | 安装到本地仓库 | `install:install` |
| `deploy` | 部署到远程仓库 | `deploy:deploy` |

### Phase Boundaries

阶段分组是理解构建的关键：

- **`package` 之前** —— 只处理 `src/main`，产出物在 `target/classes`；
- **`package` 到 `verify` 之间** —— 集成测试阶段，产物已打包但尚未安装；
- **`install` / `deploy`** —— 产物离开项目目录，进入仓库。

`install` 与 `deploy` 的区别常被误解：两者都会把产物放进仓库，但目标不同——

| | `install` | `deploy` |
| :--- | :--- | :--- |
| 目标 | 本地仓库 `~/.m2/repository` | 远程仓库（Nexus / Central） |
| 用途 | 让本机其他项目能引用 | 分发给团队与外部 |
| 幂等性 | 可反复执行 | 远程 release 仓库通常拒绝覆盖已存在版本 |

> [!Warning]
>
> **远程 release 仓库通常不可覆盖**。往 release 仓库重复 deploy 同一版本会失败或被拒绝——这就是"release 版本必须不可变"的物理体现，也是为什么 `SNAPSHOT` 与 release 要严格区分。
>
> 反过来说，**本地 `install` 会覆盖本地仓库中的同版本制品**，且 Maven 不会重新校验它。这意味着本地构建过一次的 release 版本，可能与远端正式发布的同名版本**内容不同**——排查"本地能跑、远端不能跑"时，这是首要怀疑点。

## Site Lifecycle

| Phase | Description |
| :--- | :--- |
| `pre-site` | 生成站点前准备 |
| `site` | 生成站点文档 |
| `post-site` | 收尾并准备部署 |
| `site-deploy` | 部署到 Web 服务器 |

## Goals and Plugins

**Goal** 是插件提供的具体任务（如 `compiler:compile`、`dependency:tree`）。插件是 goal 的容器，一个插件通常提供若干 goal。

插件声明的核心标签：

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-compiler-plugin</artifactId>
  <version>3.15.0</version>
  <executions>
    <execution>
      <id>default-compile</id>
      <phase>compile</phase>
      <goals><goal>compile</goal></goals>
      <configuration>
        <release>17</release>
      </configuration>
    </execution>
  </executions>
</plugin>
```

三个执行元素各管一件事：

- **`<phase>`** —— 挂到哪个阶段；
- **`<goals>`** —— 执行哪些 goal；
- **`<configuration>`** —— 只作用于这个 execution 的配置。

### pluginManagement vs plugins

这是 Maven 配置里最高频的错误：

| | `<build><plugins>` | `<build><pluginManagement>` |
| :--- | :--- | :--- |
| 作用 | **真正引入并执行**该插件 | **只提供版本与默认配置** |
| 是否进入构建 | 是 | 否（除非被引用） |
| 典型用途 | 本项目要用的插件 | 统一锁插件版本，供子模块继承 |

正确姿势——在根 POM 的 `pluginManagement` 里锁版本，子模块在 `plugins` 里声明不带版本：

```xml
<!-- 根 pom.xml -->
<build>
  <pluginManagement>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.15.0</version>
        <configuration>
          <release>17</release>
          <parameters>true</parameters>
        </configuration>
      </plugin>
    </plugins>
  </pluginManagement>
</build>
```

```xml
<!-- 子模块 pom.xml -->
<build>
  <plugins>
    <plugin>
      <groupId>org.apache.maven.plugins</groupId>
      <artifactId>maven-compiler-plugin</artifactId>
    </plugin>
  </plugins>
</build>
```

**Maven 3.10.0 起 Super POM 移除了默认的 `pluginManagement`**——含义是升级后那些"靠 Super POM 拿到默认插件版本"的写法会开始解析到最新版本甚至失败。**升级 Maven 就应该顺手把所有插件版本显式锁死**。

### Configuring Plugin Goals from CLI

插件的 `<configuration>` 里任何字段都可以用 `-D` 覆盖，前提是**表达式形式**（`<release>${java.version}</release>`）或插件声明了对应的 `@Parameter(property = "...")`。

```shell
mvn -DskipTests package
mvn -Dmaven.test.skip=true package     # 连测试编译都跳过
mvn -Dmaven.compiler.release=17 package
```

`skipTests`（跳过执行测试）与 `maven.test.skip`（跳过编译与执行）不同，后者更快但会让 IDE 失去测试类的编译校验。

## Common Plugins

截至 2026 年 10 月，官方插件索引中的主要版本：

| 插件 | 版本 | 作用 |
| :--- | :--- | :--- |
| `maven-compiler-plugin` | 3.15.0 | Java 编译（`release` 优于 source/target） |
| `maven-surefire-plugin` | 3.5.5 | 单元测试（`test` 阶段） |
| `maven-failsafe-plugin` | 3.5.5 | 集成测试（`integration-test` / `verify` 阶段） |
| `maven-jar-plugin` | 3.5.0 | 打 jar |
| `maven-war-plugin` | 3.5.1 | 打 war |
| `maven-resources-plugin` | 3.5.0 | 资源过滤与复制 |
| `maven-clean-plugin` | 3.5.0 | 清理 |
| `maven-install-plugin` | 3.1.4 | 安装到本地仓库 |
| `maven-deploy-plugin` | 3.1.4 | 部署到远程仓库 |
| `maven-dependency-plugin` | 3.11.0 | 依赖树、拷贝、组装 |
| `maven-enforcer-plugin` | 3.6.3 | 构建规则约束 |
| `maven-shade-plugin` | 3.6.1 | uber-jar、依赖重定位 |
| `maven-assembly-plugin` | 3.8.0 | 归档分发包 |
| `maven-source-plugin` | 3.4.0 | 生成 sources jar |
| `maven-javadoc-plugin` | 3.12.0 | 生成 javadoc jar |
| `maven-gpg-plugin` | 3.2.8 | GPG 签名 |
| `maven-release-plugin` | 3.3.1 | 版本号自动化与发布 |
| `maven-toolchains-plugin` | 3.2.0 | 多 JDK 工具链 |
| `maven-checkstyle-plugin` | 3.6.0 | 代码风格检查 |
| `maven-pmd-plugin` | 3.28.0 | 静态分析 |
| `jacoco-maven-plugin` | 0.8.15 | 覆盖率 |
| `spotless-maven-plugin` | 3.7.0 | 格式化（Spotless） |
| `sonar-maven-plugin` | 5.7.0 | SonarQube 集成 |

> [!Note]
>
> 版本号随官方插件索引滚动，表中数值是 2026-10 的快照。**关键结论不是具体数字，而是"必须显式锁版本"这件事**——尤其是从 3.9 升到 3.10 之后。

### Shade vs Assembly vs Spring Boot

三者都解决"一个可执行产物"，但机制不同：

- **shade** —— 把依赖解包后**合并进**目标 jar，重定位（relocate）冲突的包名。适合做库（保留普通 jar 依赖）。
- **assembly** —— 按描述文件把 jar + 依赖 + 脚本**打包成 zip/tar.gz**。适合做分发包。
- **spring-boot-maven-plugin** —— 生成 **fat jar**，用嵌套 jar（`BOOT-INF/lib/`）而非解包合并；`repackage` 会替换原 jar，需 `classifier` 避免。

选错的典型症状：用 shade 合并后 `META-INF/services/` 的 SPI 文件被覆盖，Spring 的自动装配或 JDBC 驱动的 `DriverManager` 发现失效——shade 需要 `ServicesResourceTransformer` 才能正确合并。

## Common Commands

```shell
mvn clean package                    # 构建
mvn clean install -DskipTests        # 构建并装入本地仓库
mvn test                             # 只跑单元测试
mvn -T 4C clean package              # 并行构建（4 线程 × 核数）
mvn help:effective-pom               # 看合并后的 POM
mvn dependency:tree -Dverbose        # 依赖树
mvn dependency:analyze               # 依赖使用分析
mvn -o clean package                 # 离线模式
mvn -U clean package                 # 强制检查更新
mvn help:describe -Dplugin=...       # 看插件有哪些 goal
mvn -pl module-a -am clean install  # 构建 module-a 及其依赖
```

`mvn -o`（offline）在 CI 缓存场景很有用——依赖已在本地仓库时完全不走网络，但也因此**不会拉取 SNAPSHOT 的新版本**。

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Multi-Module Reactor](/docs/CS/BuildTool/Maven/Multi_Module_Reactor.md)
- [Publishing and Signing](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md)

## References

1. [Maven — Introduction to the Lifecycle](https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html)
2. [Maven — Introduction to the Plugin Lifecycle](https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html#lifecycle-phases)
3. [Maven — Introduction to Plugins](https://maven.apache.org/guides/introduction/introduction-to-plugins.html)
4. [Maven — Guide to the Plugin Management](https://maven.apache.org/guides/introduction/guide-to-plugin-management.html)
5. [Apache Maven Plugins](https://maven.apache.org/plugins/)
