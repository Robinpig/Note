## Introduction

OpenJDK 自 JDK 9 起固定 **6 个月一个特性版**的发布节奏，并每三年选一个 LTS（Long-Term Support）版本（JDK 11/17/21/25…）。升级迁移因此成为周期性工程：既有项目往往不是「升一个大版本」，而是跨多个特性版、且要兼顾 LTS 之间的行为差异。升级动因通常包括：追上已 GA 的语言特性（如虚拟线程 [JEP 444](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)）、拿到新的 GC/性能优化、满足安全合规、以及第三方库（Spring Boot 等）的最低 JDK 要求。

## What to Check

| 关注点 | 典型风险 | 对应 JDK 变化 |
| --- | --- | --- |
| 移除 / 废弃 API | 编译失败或运行时 `NoSuchMethodError` | 每个特性版都会移除旧 API（如 `finalize` 在 [JEP 398](https://openjdk.org/jeps/398) 被弃用） |
| 模块系统强封装 | 反射访问 JDK 内部包抛 `InaccessibleObjectException` | [JEP 403](/docs/CS/Java/JDK/Basic/module.md)（JDK 17 移除 `--illegal-access`） |
| class 文件版本 | 旧工具（ASM/旧编译器）无法读新版本 | 每特性版 major version +1，需升级 ASM 等依赖 |
| GC 变化 | 默认 GC、行为、参数名变化 | ZGC/Shenandoah 默认开启与调优参数演进 |
| 默认行为变化 | 看似无害的语义漂移 | TLS、Locale、随机数源、序列化过滤默认值 |
| 安全 / 加密 | 算法/协议被禁用或默认关闭 | 弱算法下线、后量子 KEM（[JEP 510](https://openjdk.org/jeps/510)） |
| 平台支持 | 硬件架构被砍 | 32 位 x86 在 [JEP 503](https://openjdk.org/jeps/503)（JDK 25）移除 |

## Typical Migration Pitfalls

**Spring Boot 2.7 → 3.x 自动装配方式变化**：从 2.7 起引入新的自动装配声明 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`；2.7.x 同时兼容旧 `spring.factories` 方式（两者共存不重复装配），但 **3.x 彻底废弃 `spring.factories`**——没有新文件的 starter 不会自动装配，项目里大部分 starter 可能因此失效。

**`javax.*` → `jakarta.*` 命名空间迁移**：Jakarta EE 9 起将 `javax.persistence` / `javax.servlet` / `javax.annotation` 等整体迁到 `jakarta.*`。Spring Boot 3.x 强制要求 Jakarta EE 9+，所有 import 与依赖坐标都要改；这是 2.x → 3.x 升级中工作量最大的一块。

**JDK 17 强封装**：JDK 内部包（`sun.*` / `jdk.internal.*`）不再可反射访问，曾经的 `--illegal-access=permit` 放宽开关在 JDK 17 已被移除。依赖内部 API 的库（旧版 Byte Buddy、CGLIB、某些序列化框架）必须升级，否则只能在启动参数逐项 `--add-opens`。

**JDK 25 平台收窄**：[JEP 503](https://openjdk.org/jeps/503) 移除 32 位 x86 端口；[JEP 411](https://openjdk.org/jeps/411) 在 JDK 17 弃用、后续逐步移除安全管理器（`SecurityManager` 默认 `disallow`）。升级老项目时这些「静默消失」的特性最容易在边缘路径爆雷。

## Compatibility Verification Flow

1. **静态扫描**：`jdeprscan`（JDK 9+ 自带）扫描对废弃/即将移除 API 的使用；`javac -Xlint:deprecation,removal` 在编译期暴露废弃调用。
2. **依赖分析**：`jdeps` 分析 jar 的包级依赖，定位对 JDK 内部 API 的非法引用；结合 `jdeps --jdk-internals` 可列出需要 `--add-opens` 的包。
3. **第三方兼容性矩阵**：查证 Spring Boot / 框架 / 中间件对目标 JDK 的最低支持版本（如 Spring Boot 3.2+ 才官方支持 JDK 21）。
4. **逐级推进**：不要跨太多 LTS 一步到位（如 8 → 21）；建议 8 → 11 → 17 → 21 逐级，每级先过编译与单测，再上集成。
5. **运行时回归**：关注 GC 日志、JFR、启动耗时；AOT/Leyden 等新能力按需评估。

## Tooling

- `jdeprscan`：扫描对 deprecated-for-removal API 的依赖，给出迁移提示。
- `jdeps`：依赖与模块分析，识别对 JDK 内部 API 的耦合。
- `jlink`：仅含所需模块的自定义运行时，缩小镜像（配合升级后的模块化裁剪）。
- 构建侧：用 `maven-source-plugin`  maintain 原有打包版本，使二方包 JDK 版本可单独维护，避免一刀切升级拖垮下游。

## Local Build and Runtime

升级后通常要同步调整构建与运行环境：

- 修改 Dockerfile：把 `WORKDIR` 设为日志目录以提升排障效率，并增加常用命令别名；基础镜像 JDK 版本与新运行时一致。
- 本地编译运行：确认 `JAVA_HOME`、构建工具（Maven/Gradle）的 toolchain 指向目标 JDK；CI 矩阵补上目标 LTS 版本。

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [module](/docs/CS/Java/JDK/Basic/module.md) — 强封装与 `--add-opens`/`--add-exports` 迁移开关
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) — JDK 21 起可借力的新并发模型

## References

1. [JEP 403: Strongly Encapsulate JDK Internals](https://openjdk.org/jeps/403)
2. [JEP 411: Deprecate the Security Manager for Removal](https://openjdk.org/jeps/411)
3. [JEP 503: Remove the 32-bit x86 Port](https://openjdk.org/jeps/503)
4. [Jakarta EE 9 Release Notes (javax → jakarta)](https://jakarta.ee/release/9/)
5. [Spring Boot 3.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide)
