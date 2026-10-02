## Introduction

构建工具负责把源码变成可交付产物的全过程：依赖管理、编译、测试、打包、静态检查、发布。Java 生态经历了 **Make → Ant（过程式 XML，无依赖管理）→ Maven（约定优于配置 + 统一仓库坐标）→ Gradle（声明式任务图 + 灵活脚本）** 四代演进；其他语言有各自的对应物（npm/yarn、Go modules、Cargo、pip/poetry），核心问题始终相同：**可重复构建（reproducible build）与依赖地狱（dependency hell）**。

## 核心概念

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

## 典型流水线

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

## 与其他生态对照

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
