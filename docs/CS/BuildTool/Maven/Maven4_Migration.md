## Introduction

Maven 4 是十年来第一次对 Maven 核心做架构性重构。它的主线只有一条：**把"用来构建的 POM"和"给消费者用的 POM"拆开**。这一条改动连带引出了 Model 4.1.0、`<subprojects>`、`bom` packaging、Consumer POM 扁平化等一串新概念。

截至 2026-10-27，Maven 4 的最新版本是 **`4.0.0-rc-7`（2026-09-24）**，**尚未 GA**——官方明确标注 "NOT safe for production use"。同时 **Maven 3.10.0（2026-09-27）已 GA**，它是 3.x 线的收官版本，且**与 Maven 4 共用同一 Resolver 2.0 lineage**。

因此现实策略是：**生产用 3.10.0 + 显式锁插件版本；把 Maven 4 的准备工作做在代码库层面（Model 4.1.0 语法、CI-friendly 内置支持），等 GA 再切运行时**。

## Version Baseline

| 组件 | 版本 | 日期 | 运行要求 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| Maven 4 | `4.0.0-rc-7` | 2026-09-24 | JDK 17+ | RC |
| Maven 4 | `4.0.0-rc-6` | 2026-08-04 | JDK 17+ | RC |
| Maven 3 | `3.10.0` | 2026-09-27 | JDK 8+ | **GA** |
| Maven 3 | `3.9.16` | 2026-05-13 | JDK 8+ | GA（维护中） |
| Maven 3.8.9 及更早 | — | — | — | **已 EOL，不再支持** |
| Maven Daemon | `mvnd` 1.0.3 | — | — | GA；2.x 预览 |

官方维护策略：**只维护最近两个 GA 系列的最新版本**；插件的 Maven API 兼容下限为 `3.9.0`。

## Maven 3.10.0: The GA Baseline

3.10.0 是**生产环境应该待的版本**。它的定位是"与 Maven 4 对齐 Resolver，行为变化尽量少"。核心变更：

**新增能力**

- **Resolver 2.0.24** —— 与 Maven 4 同一 lineage，带来版本区间过滤、改进的远程仓库过滤、传递依赖管理器、用户自定义 relocation；
- **全局扩展** —— 支持 `~/.m2/extensions.xml`（用户级）与 `$MAVEN_HOME/conf/extensions.xml`（安装级），此前只有项目级 `.mvn/extensions.xml`；
- **`settings.xml` 完整插值** —— 支持非字符串值（如端口号）；`session.topDirectory` / `session.rootDirectory` / `project.rootDirectory` 提升为常规属性，可用于插值和 profile 激活；
- **Reproducible Builds 默认启用** —— Super POM 为 `project.build.outputTimestamp` 提供默认值；
- **细粒度更新策略** —— `-UA`（只更新制品）、`-UM`（只更新元数据）、`--artifacts-update-policy=` / `--metadata-update-policy=`；
- **`<server><aliases>`** —— 一套凭据服务多个 server id；
- **`<server><repositoryOrigins>`** —— 显式声明凭据可用于哪些 origin；
- **reactor summary 完整** —— 所有模块都列出（含跳过的），失败排在最后且为 error 级；
- **工具链错误不再静默回退** —— 插件请求的 toolchain 配错时直接失败；
- **`MAVEN_PROJECTBASEDIR` 可用于 `.mvn/jvm.config`**；
- **site 生命周期可禁用** —— `maven.site.lifecycle.disabled` 系统属性；
- **SLF4J 升到 2.x**，JAnsi 迁到 JLine；
- **核心用 JSR-330 注解**。

**安全强化**

- 凭据按 origin（scheme + host + port）作用域化，server id **精确匹配**——不再泄漏给 id 前缀相同的无关仓库；
- 从仓库解析到的模型（依赖、parent、导入的 BOM）对构建的贡献被收窄：受限插值、profile 激活限制为平台派生条件、仓库合并退居次要、**拒绝 system scope 依赖**；
- 请求或 session 提供的仓库优先于模型声明的仓库；
- 元数据坐标、relocation 坐标、遗留元数据文件名 token 在使用前被校验。

**破坏性变更（从 3.9 升级时）**

| 变更 | 影响 |
| :--- | :--- |
| **POM 校验提升到 3.1 级别并从 WARNING 变 ERROR** | 重复的 dependency / plugin 条目、非法版本字符、畸形 SNAPSHOT 版本、保留或畸形的 repository id —— 全部变成构建失败 |
| **parent 的 `relativePath` 开始校验** | 此前任何 Maven 3.x 都不校验，现在无效路径直接失败 |
| **classpath 顺序 pre-order → level-order** | 与 Maven 4 一致；旧行为用 `-Daether.system.dependencyVisitor=preOrder` 恢复 |
| **Super POM 移除废弃的 `release` profile** | 各项目需自备 release profile |
| **Super POM 移除默认 `pluginManagement`** | **必须显式锁定插件版本** |
| **Super POM 默认编码改为 UTF-8** | 编码问题自愈，但依赖旧默认值的构建需检查 |
| **`maven.resolver.validation` 新开关** | `default`（全量）/ `mild`（只查未插值占位符）/ `off`（回到 3.9 行为） |

> [!Warning]
>
> **升级到 3.10.0 的第一件事是显式锁定所有插件版本**。Super POM 不再提供默认 `pluginManagement` 意味着那些"靠默认版本"的写法会解析到各插件的最新版本——从 2024 年的 3.1.x 跳到 2026 年的 3.15.x，中间可能有 breaking change。
>
> 第二件事是**清理重复声明**。原先只是告警的重复 dependency / plugin 条目现在是硬错误。

## Maven 4: Model 4.1.0

新的 POM 模型：

```xml
<project xmlns="http://maven.apache.org/POM/4.1.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.1.0 https://maven.apache.org/xsd/maven-4.1.0.xsd">
```

### New Elements

**`<subprojects>` 取代 `<modules>`**

```xml
<subprojects>
  <subproject>common</subproject>
  <subproject>service</subproject>
</subprojects>
```

原因很实际：`<modules>` 与 Java Module System 的 `<module>` 概念撞名，容易混淆。旧的 `<modules>` 仍可用，但**已弃用**。

**自动发现子模块**

父项目使用 `pom` packaging、既无显式 `<subprojects>` 也无 `<modules>`，且**直接子目录含 `pom.xml`** 时，Maven 自动纳入构建。

**`<sources>` 声明多源码目录**

```xml
<build>
  <sources>
    <source>
      <scope>main</scope>
      <directory>src/main/java</directory>
    </source>
    <source>
      <scope>test</scope>
      <directory>src/test/java</directory>
    </source>
  </sources>
</build>
```

**parent 的 groupId/artifactId/version 可自动推断**

```xml
<parent>
  <relativePath>..</relativePath>
</parent>
```

甚至可以简写为 `<parent/>`。

**`<project root="...">` 属性** —— 显式指定项目根目录。

**新的 artifact 类型** —— 更精确地控制 jar 进 classpath 还是 module path：

`jar` / `classpath-jar` / `modular-jar` / `processor` / `classpath-processor` / `modular-processor`

**新的目录属性** —— `${project.rootDirectory}` / `${session.topDirectory}` / `${session.rootDirectory}`（Maven 3.10.0 也已把后两个提升为常规属性）。

## Build POM vs Consumer POM

这是 Maven 4 最重要的架构变化。

**问题**：传统上发布的 POM 里带着 `<parent>`、plugin 配置、properties。消费者拉这个 jar 时，Maven 必须**再拉一遍 parent POM**（可能还有 parent 的 parent，以及 BOM import 的那一串），才能算出完整的依赖。如果 parent 未发布到仓库或中间有依赖链断掉，消费者直接解析失败。

**解法**：发布时生成一份精简的 **Consumer POM**，扁平化掉所有继承结构。

Consumer POM 的处理规则：

- 去掉 `<parent>`，继承内容**直接展开**；
- BOM import 被**扁平化**到依赖列表；
- 只保留 `compile` 和 `runtime` scope 的传递依赖；
- `dependencyManagement` 只保留项目实际使用的部分；
- POM properties 与 plugin 配置**不进入** Consumer POM。

**版本隔离**：

| 内容 | Build POM | Consumer POM |
| :--- | :--- | :--- |
| Model 版本 | 4.1.0 | **4.0.0** |
| 第三方依赖信息 | 是 | 是 |
| POM properties | 是 | 否 |
| 插件配置 | 是 | 否 |
| 仓库信息 | 是 | 是 |
| 项目与环境配置 | 是 | 是 |
| 远程部署配置 | 是 | 是 |

含义：**源码库里放 4.1.0 的 Build POM，仓库里放 4.0.0 的 Consumer POM**。这保证 Maven 3 的生态兼容性——Maven 3 的项目能被 Maven 4 构建，Maven 3 消费 Maven 4 发布的库也没有障碍。

**默认关闭**，需显式启用：

```properties
# .mvn/maven-user.properties（reactor 根目录）
maven.consumer.pom.flatten=true
```

> [!Note]
>
> 极少数无法转换成 4.0.0 Consumer POM 的情况才发布 4.1.0，并会产生警告。

## Lifecycle Becomes a Tree

Maven 4 的生命周期从**线性列表**变成**树形结构**，增加了 `before:`、`after:`、`all`、`each` 等阶段修饰，支持更细粒度的并行。

这意味着"给某个 phase 加一个动作"有了更细的粒度控制，而不是只有"绑到某个 phase 的开头或结尾"。

## Other Maven 4 Changes

**Maven Resolver 2.0 全面接入** —— 150+ 项修复与改进；利用 JDK 17 的原生 HTTP Client；Resolver 被隐藏在新的 Maven API 之后，**插件不再直接使用 Resolver**，减少插件与内部实现的耦合。

**ModelParser SPI** —— 允许通过 Core Extension 实现**自定义或替代的 POM 语法**（不再局限于 XML）。已有示例：Apache Maven Hocon Extension。这让 Build POM 可以继续演进，同时保持 4.0.0 Consumer POM 的格式固定。

**CI-friendly 变量完整内置** —— 不再需要 flatten-maven-plugin，版本可以用任意变量（如 `${revision}`），不再局限于只能在 `<version>` 上用。

**`deployAtEnd` 默认改为 `true`** —— 多项目构建只有在**所有子项目都成功后**才统一部署，避免"部分已发布、部分失败"的半成品状态。

**构建恢复** —— `mvn --resume` / `mvn -r`，从上次失败的子项目继续。

**新的加密系统** —— 基于 `mvnenc`，增加解密功能并支持外部 Vault。

**Maven Shell `mvnsh`** —— 保持 shell 打开期间复用 Maven 进程（Maven 内置工具）。

**插件模型不可变 + 新 Maven 4 Plugin API** —— 但该 API 在 4.0.0 中仍是实验性质，不建议普通用户采用。

**插件兼容性收紧** —— 依赖旧 Plexus 注入或 Maven 2 API 的老插件需要升级到 JSR-330。

**新工具 `mvnval`** —— 只校验 POM 文件并报告所有问题，不跑构建（Maven 4.1.0 内置）。

## The Upgrade Tool: mvnup

Maven 官方提供 **Maven Upgrade Tool（`mvnup`）** 辅助从 Maven 3 迁移到 Maven 4：

```shell
mvnup check     # 分析项目、检查 Maven 4 兼容性
mvnup apply     # 执行修改
```

它能：分析现有项目、检查兼容性、识别弃用功能并给出替代方案、把 POM 更新到 Model 4.1.0、迁移过时的插件配置、验证项目是否已就绪。

`mvnup` 是 **Maven 4 内置工具**（随 4.x 分发），不是独立的第三方工具。

## Migration Checklist

从 Maven 3 迁到 Maven 4 的推荐顺序：

1. **先升到 Maven 3.10.0** —— 它已经把 Resolver、classpath 顺序、Super POM 调到与 4 对齐，先做完这个"预热"，把破坏性变更一次性消化掉；
2. **显式锁定所有插件版本** —— Super POM 不再兜底；
3. **清理重复的 dependency / plugin 条目** —— 3.10.0 已把它们变成硬错误；
4. **验证 parent 的 `relativePath`** —— 3.10.0 开始校验；
5. **检查工具链配置** —— 配错的 toolchain 现在会让构建失败；
6. **跑 `mvnup check`** —— 看官方工具怎么说；
7. **用 JDK 17+ 运行 Maven 4**，但**项目仍可编译到更旧的 Java 版本**（用 `maven-compiler-plugin` 的 `release`，或用 toolchains 切到旧 JDK）；
8. **启用 Consumer POM 前先验证** —— 依赖列表、BOM 导入、exclusions 的结果都要核对；
9. **检查老插件** —— 是否依赖 Plexus 注入、Maven 2 API 或已弃用的 POM 配置。

**不需要做的事**：如果不需要新特性，**不必急着把 Build POM 升到 Model 4.1.0**。Maven 4 能正常构建 Model 4.0.0 的项目。

## Maven 4 vs Maven 3.10

| 维度 | Maven 3.10.0 | Maven 4 |
| :--- | :--- | :--- |
| 运行 JDK | 8+ | **17+** |
| POM Model | 4.0.0 | 4.1.0（可选升级） |
| Resolver | 2.0.24 | 2.0.x |
| CI-friendly 变量 | 需 flatten 插件 | **内置** |
| Consumer POM | 无 | 有（默认关闭） |
| 生命周期结构 | 线性 | **树形** |
| 构建恢复 | `-rf`（手动指定） | `--resume`（自动） |
| 部署策略 | 逐个 deploy | `deployAtEnd` 默认 true |
| POM 语法可扩展 | 无 | **ModelParser SPI** |
| 加密 | 新增 mvnenc | 增强 + Vault |
| 成熟度 | **GA** | RC，官方标注不适合生产 |

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Multi-Module Reactor](/docs/CS/BuildTool/Maven/Multi_Module_Reactor.md)
- [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)

## References

1. [Maven — What’s new in Maven 4](https://maven.apache.org/whatsnewinmaven4.html)
2. [Maven — Starting with Maven 4 (Migration Guide)](https://maven.apache.org/guides/mini/guide-migration-to-mvn4.html)
3. [Maven 3.10.0 Release Notes](https://maven.apache.org/docs/3.10.0/release-notes.html)
4. [Maven Releases History](https://maven.apache.org/docs/history.html)
5. [Maven Upgrade Tool (mvnup)](https://maven.apache.org/tools/mvnup.html)
6. [Maven Tools Index](https://maven.apache.org/tools/index.html)
