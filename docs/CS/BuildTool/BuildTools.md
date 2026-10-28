## Introduction

构建工具负责把源码变成可交付产物的全过程：依赖管理、编译、测试、打包、静态检查、发布。Java 生态经历了 **Make → Ant（过程式 XML，无依赖管理）→ Maven（约定优于配置 + 统一仓库坐标）→ Gradle（声明式任务图 + 灵活脚本）** 四代演进；其他语言有各自的对应物（npm/yarn、Go modules、Cargo、pip/poetry），核心问题始终相同：**可重复构建（reproducible build）与依赖地狱（dependency hell）**。

## Core Concepts

- **坐标（GAV）**：`groupId:artifactId:version` 唯一标识一个制品，制品发布到仓库（Nexus/Artifactory/Maven Central）；
- **传递依赖与仲裁**：A 依赖 B、B 依赖 C，则 C 自动引入。版本冲突时 Maven 按"最近路径优先"仲裁，Gradle 默认选最高版本；都可用 exclusions/dependency constraints 强制；
- **依赖范围**：compile / provided（容器提供，如 servlet-api）/ runtime（JDBC 驱动）/ test / runtimeOnly；
- **SNAPSHOT vs Release**：快照是可变的开发版本（CI 拉取最新），发布版必须不可变；
- **本地仓库缓存**：`~/.m2`（Maven）、`~/.gradle`，CI 缓存它们是加速流水线的关键。

## Maven vs Gradle

| 维度 | Maven | Gradle |
|------|-------|--------|
| 配置形式 | 声明式 XML（pom.xml） | Groovy/Kotlin DSL（build.gradle[.kts]） |
| 模型 | 固定生命周期（clean/compile/test/package/install/deploy） | **任务有向无环图（DAG）**，按需配置执行 |
| 增量构建 | 基本没有 | 输入/输出快照，UP-TO-DATE 跳过未变任务 |
| 构建缓存 | 无 | 本地/远程 build cache，同输入直接复用产物 |
| 守护进程 | 无 | Gradle Daemon（JVM 常驻，启动快） |
| 依赖管理 | GAV + 最近路径 | configurations、constraints、platform/BOM |
| 多模块 | reactor 聚合 | 同构支持更灵活 |
| 典型地盘 | 传统企业/后端 Spring Boot 主流 | Android、多模块大型项目、性能敏感 |

详见各自专文：[Maven](/docs/CS/BuildTool/Maven.md)、[Gradle](/docs/CS/BuildTool/Gradle.md)。

Maven 的展开较深，因为它的复杂度集中在依赖解析与生命周期模型上。入口页 [Maven](/docs/CS/BuildTool/Maven.md) 给出整体心智模型与阅读路径，随后按"模型 → 依赖 → 生命周期 → 多模块 → 仓库配置 → 发布 → 性能排障 → Maven 4 迁移"分册展开：坐标与 Super POM 见 [Architecture](/docs/CS/BuildTool/Maven/Architecture.md)，传递依赖与仲裁规则见 [Dependency Resolution](/docs/CS/BuildTool/Maven/Dependency_Resolution.md)，阶段与插件绑定见 [Lifecycle and Plugins](/docs/CS/BuildTool/Maven/Lifecycle_and_Plugins.md)，reactor 与 CI-friendly 版本见 [Multi-Module Reactor](/docs/CS/BuildTool/Maven/Multi_Module_Reactor.md)，settings.xml 与镜像见 [Repositories and Mirrors](/docs/CS/BuildTool/Maven/Repositories_and_Mirrors.md)，Central Portal 发布链路见 [Publishing and Signing](/docs/CS/BuildTool/Maven/Publishing_and_Signing.md)，构建加速与症状索引见 [Performance and Troubleshooting](/docs/CS/BuildTool/Maven/Performance_and_Troubleshooting.md)，3.10.0 与 4.0.0-rc 的差异见 [Maven 4 Migration](/docs/CS/BuildTool/Maven/Maven4_Migration.md)。

Gradle 的展开逻辑相同，但切入点不同——它的复杂度不在"有哪些命令"，而在"两阶段执行模型"这一处。入口页 [Gradle](/docs/CS/BuildTool/Gradle.md) 同样给出心智模型与症状索引表，随后按"架构 → 任务 → 依赖 → 版本目录 → 多项目 → 性能 → 发布安全 → 排障"分册展开：两阶段执行与 daemon、Configuration Cache 状态见 [Architecture](/docs/CS/BuildTool/Gradle/Architecture.md)，输入输出声明与 up-to-date 判定见 [Task Model](/docs/CS/BuildTool/Gradle/Task_Model.md)，configuration 与 api/implementation 语义、仲裁规则见 [Dependency Management](/docs/CS/BuildTool/Gradle/Dependency_Management.md)，`libs.versions.toml` 见 [Version Catalogs](/docs/CS/BuildTool/Gradle/Version_Catalogs.md)，buildSrc、included build 与 convention plugin 见 [Multi-Project Builds](/docs/CS/BuildTool/Gradle/Multi_Project_Builds.md)，三层加速机制见 [Performance](/docs/CS/BuildTool/Gradle/Performance.md)，Central Portal 发布与依赖校验见 [Publishing and Security](/docs/CS/BuildTool/Gradle/Publishing_and_Security.md)，症状索引与 9.0 移除项见 [Troubleshooting](/docs/CS/BuildTool/Gradle/Troubleshooting.md)。

## Typical Pipeline

```
拉代码 → 依赖解析（私有镜像加速） → 编译 → 单元测试 → 静态检查(SpotBugs/Checkstyle/dependency-check)
      → 打包(jar/war，含 Docker 镜像) → 推送制品库/镜像仓库 → 部署
```

常见工程实践：

- **Wapper 固化版本**：`mvnw`/`gradlew` 让项目自带构建工具版本，团队和 CI 无需预装；
- **BOM（Bill of Materials）**：用 `dependencyManagement`/`platform` 统一一组依赖版本（Spring Boot、Jackson BOM），避免逐个写版本号造成错配；
- **镜像与私服**：中央仓库慢/不可达时配置阿里云镜像或企业 Nexus，同时作为内部制品的发布目标；
- **可重复构建**：锁定插件与依赖版本（Maven Enforcer、Gradle version catalog + lockfile），禁止裸用 LATEST/RELEASE/SNAPSHOT 上生产；
- **依赖安全**：排查冲突用 `mvn dependency:tree`、`gradle dependencies`，已知 CVE 用 OWASP dependency-check。

## Comparison with Other Ecosystems

| 生态 | 构建/依赖工具 | 制品 |
|------|--------------|------|
| Java | Maven、Gradle | jar/war → Maven 仓库 |
| JS/TS | npm/pnpm/yarn + Vite/Webpack | npm registry |
| Go | go mod（原生于工具链） | module proxy |
| Rust | Cargo | crates.io |
| Python | pip + venv / Poetry / uv | PyPI |

趋势：语言工具链内建依赖管理（Go/Rust），传统独立构建工具的"胶水"角色在减弱；而 Maven/Gradle 因 JVM 生态的历史规模仍长期并存。

## Links

- [Maven](/docs/CS/BuildTool/Maven.md)
- [Gradle](/docs/CS/BuildTool/Gradle.md)
- [Test](/docs/CS/SE/Test.md)

## References

1. [Maven 官方文档](https://maven.apache.org/guides/)
2. [Gradle User Manual](https://docs.gradle.org/current/userguide/userguide.html)
