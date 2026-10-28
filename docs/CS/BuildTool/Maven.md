## Introduction

Maven 是 Java 生态事实上的标准构建工具。它的名字来自意第绪语，意为"知识的累积器"——这个双关很贴切：Maven 的目标不是跑得快，而是让任何一个接手的人**在最短时间内理解一个项目的完整状态**。

要理解 Maven，抓住三件事就够了：

**第一，它是一份模型，不是一串脚本。** 所有行为都从 POM（Project Object Model）推导出来。POM 描述"我是什么、依赖什么、怎么构建"，Maven 据此决定"该做什么"。写 Maven 的技艺，本质是**写好一份能被机器正确理解的模型**。

**第二，它的核心是依赖管理。** Maven 最有价值的贡献不是"能编译"，而是"依赖地狱"这个问题被解决了一大半——传递依赖自动引入、冲突按规则仲裁、版本由 `dependencyManagement` 统一。这套机制理解了，依赖相关的诡异报错就都能自己推演。

**第三，它靠约定而非配置驱动。** Super POM 提供了默认的目录结构、仓库和插件绑定，因此"什么都不配也能构建"。但这个约定会随版本演进变化——**Maven 3.10.0 移除了 Super POM 里的默认 `pluginManagement`，等于明确要求：插件版本必须自己锁**。

这个子树按"模型 → 依赖 → 生命周期 → 模块 → 仓库 → 发布 → 性能 → 迁移"的顺序展开，是一条从"为什么"到"怎么做"再到"未来会怎样"的路径。

## Reading Path

**第一次接触 Maven**，按顺序读 [Architecture](/docs/CS/BuildTool/Maven/Architecture.md) → [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md) → [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)。这三篇构成 Maven 的骨架：坐标与模型、依赖图、阶段与插件。

**正在解决具体问题**，直接查对应分册：

| 症状 | 去读 |
| :--- | :--- |
| `NoSuchMethodError` / `ClassNotFoundException` | [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md) |
| 改上游模块后下游还是旧行为 | [Multi-Module Reactor](/docs/CS/BuildTool/Maven/Multi_Module_Reactor.md) |
| 依赖下载慢 / 走错仓库 / 凭据不生效 | [Repositories and Mirrors](/docs/CS/BuildTool/Maven/Repositories_and_Mirrors.md) |
| 发布到 Central 失败 | [Publishing and Signing](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md) |
| 构建太慢 | [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md) |
| 升级 Maven 报错 | [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md) |

## Core Concepts

- **坐标（GAV）** —— `groupId:artifactId:version` 唯一标识一个制品，映射到本地仓库的目录结构；`classifier` 是挂在坐标下的第四维（sources / javadoc / 平台相关）；
- **POM 与 Super POM** —— 每个 POM 隐式继承一份内置模型，提供默认目录、仓库与插件绑定；这是"约定优于配置"的物理载体；
- **传递依赖与仲裁** —— 依赖自动传递，冲突取"最近路径"的版本而非最新版本，同深度时先声明者胜；
- **依赖范围（scope）** —— compile / provided / runtime / test / system / import，同时决定传递性与 classpath 归属；
- **dependencyManagement 与 BOM** —— 只声明版本不引入依赖；`import` 引入 BOM 让一组依赖版本保持互相兼容；
- **生命周期与阶段** —— clean / default / site 三条生命周期；执行的是阶段，阶段触发插件 goal；`mvn dependency:tree` 这类直接调用 goal 的写法不触发任何前置阶段；
- **Reactor** —— 一次构建内的所有项目构成 reactor，按依赖关系拓扑排序；reactor 内的依赖解析到当前构建产物，而非仓库里的旧版本；
- **本地仓库即缓存** —— `~/.m2/repository` 是无需数据库的扁平缓存，删掉可完整重建；
- **可重复构建** —— 禁用 LATEST / RELEASE / 版本区间 / 生产用 SNAPSHOT；Maven 3.10.0 起 Reproducible Builds 默认启用。

## Version Baseline

| 组件 | 版本 | 状态 | 运行要求 |
| :--- | :--- | :--- | :--- |
| Maven 4 | `4.0.0-rc-7`（2026-09-24） | RC，官方标注不适合生产 | JDK 17+ |
| Maven 3 | `3.10.0`（2026-09-27） | **GA，生产首选** | JDK 8+ |
| Maven 3 | `3.9.16`（2026-05-13） | GA，维护中 | JDK 8+ |
| Maven 3.8.9 及更早 | — | **已 EOL** | — |
| Maven Daemon | `mvnd` 1.0.3 | GA；2.x 预览 | — |
| Maven Resolver | `2.0.24` | 3.10 与 4 共用 lineage | — |

官方维护策略：**只维护最近两个 GA 系列的最新版本**；插件的 Maven API 兼容下限为 `3.9.0`。

## Maven 3.10.0 值得单独记住

3.10.0 是当前生产环境的落点，也是通向 Maven 4 的跳板。它做了一件容易被忽略但影响极深的事：**把 Maven 3 的内部实现向 Maven 4 对齐**——共用 Resolver 2.0、classpath 顺序改为 level-order、Super POM 移除默认 `pluginManagement`、默认编码改 UTF-8。

两个必须知道的破坏性变更：

1. **POM 校验从 WARNING 提升为 ERROR** —— 重复的 dependency / plugin 条目、非法版本字符、畸形 SNAPSHOT 版本现在直接让构建失败；
2. **parent 的 `relativePath` 开始校验** —— 此前任何 Maven 3.x 都不校验。

**结论**：升级到 3.10.0 的第一步是把所有插件版本显式锁死，第二步是清理重复声明。

## Common Misconceptions

| 误解 | 事实 |
| :--- | :--- |
| "Maven 4 已经 GA 了" | 截至 2026-10-27 最新是 `4.0.0-rc-7`，官方明确写 NOT safe for production |
| "依赖冲突 Maven 选最高版本" | 选**最近路径**的版本（nearest wins），与 Gradle 相反 |
| "`dependencyManagement` 会引入依赖" | 只声明版本，不引入 |
| "配了 `pluginManagement` 插件就会执行" | `pluginManagement` 只提供版本与配置；执行需要写在 `plugins` 里 |
| "release 仓库可以覆盖重发" | 通常拒绝；已发布版本不可变，只能发新版本 |
| "OSSRH 还能用" | **2025-06-30 已关停**，现在是 Central Publisher Portal |
| "`mvn test` 会跑集成测试" | `test` 只跑单元测试；集成测试在 `verify` 阶段（failsafe） |
| "改了上游模块，下游自动用新的" | 仅在同一次 reactor 内成立；单模块构建会去仓库拿旧版本（用 `-am`） |

## Comparison with Gradle

| 维度 | Maven | Gradle |
| :--- | :--- | :--- |
| 配置形式 | 声明式 XML（pom.xml） | Groovy/Kotlin DSL |
| 模型 | 固定生命周期 | 任务有向无环图（DAG） |
| 增量构建 | 基本没有 | 输入/输出快照，未变任务跳过 |
| 构建缓存 | 无 | 本地/远程 build cache |
| 守护进程 | 无（有独立的 `mvnd`） | Gradle Daemon |
| 依赖仲裁 | 最近路径优先 | 默认选最高版本 |
| 多模块 | reactor 聚合 | 同构支持更灵活 |
| 典型地盘 | 传统企业/后端 Spring Boot 主流 | Android、多模块大型项目 |

两者不是"谁更先进"的竞争关系，而是**两种权衡**：Maven 牺牲构建速度换取了确定性与低学习成本，Gradle 用更高的复杂度换取增量与缓存能力。同一团队两者并用是常态。详见 [Build Tools](/docs/CS/BuildTool/BuildTools.md)。

## Links

- [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)
- [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)
- [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)
- [Multi-Module Reactor](/docs/CS/BuildTool/Maven/Multi_Module_Reactor.md)
- [Repositories and Mirrors](/docs/CS/BuildTool/Maven/Repositories_and_Mirrors.md)
- [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)

## References

1. [Maven — Official Site](https://maven.apache.org/)
2. [Maven — Guides](https://maven.apache.org/guides/)
3. [Maven Releases History](https://maven.apache.org/docs/history.html)
4. [Maven 3.10.0 Release Notes](https://maven.apache.org/docs/3.10.0/release-notes.html)
5. [Maven — What's new in Maven 4](https://maven.apache.org/whatsnewinmaven4.html)
6. [Central Portal — OSSRH Sunset](https://central.sonatype.org/pages/ossrh-eol/)
