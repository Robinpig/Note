## Introduction

Java 平台模块系统（JPMS，JEP 200/201/220，JDK 9 引入）把「可见性」从类型/包层面提升到**模块层面**：一个模块默认只能访问它显式 `requires` 的模块、以及对方**显式 `exports` 的包**。这既约束了编译期访问，也约束了运行期反射访问私有成员——这是 Java 9 之后大量 `java.lang.reflect` / 字节码库（Spring、Hibernate、Lombok、Mockito）在升级后报 `InaccessibleObjectException` 或 `module ... does not "opens ... to unnamed module` 的根本原因。

```shell
# 典型报错：被依赖模块未对未命名模块开放反射权限
module java.base does not "opens java.lang.reflect" to unnamed module
# 解决：让 java.base 在运行期对该包放开深度反射
--add-opens java.base/java.lang.reflect=ALL-UNNAMED
```

本页覆盖模块描述符语法、强封装与反射边界、`--add-*` 迁移开关、模块路径解析、`.jmod` / jimage 打包，以及 `ModuleLayer` 分层加载。版本口径以 **JDK 25** 为准。

## Module Declaration

模块由一个 `module-info.java` 描述符声明，编译后为 `module-info.class`。七类指令（`java.lang.module.ModuleDescriptor` 中有对应类型）：

```java
module com.example.app {
    // 1. requires：依赖，transitive 表示「传递可读」，static 表示编译期可选
    requires java.sql;
    requires transitive com.example.spi;
    requires static com.example.optional;

    // 2. exports：导出包的公共 API 可被编译/运行期访问；to 限定仅对指定模块可见
    exports com.example.app.api;
    exports com.example.app.internal to com.example.test;

    // 3. opens：开放包供运行期反射访问私有成员；to 限定目标模块
    opens com.example.app.reflect;
    opens com.example.app.dmz to com.fasterxml.jackson.databind;

    // 4. uses：声明本模块消费某个服务接口
    uses com.example.spi.Service;

    // 5. provides...with：提供服务的实现
    provides com.example.spi.Service with com.example.app.impl.ServiceImpl;
}
```

| 指令 | 影响阶段 | 作用 | 对应反射/访问 |
| :-- | :-- | :-- | :-- |
| `requires` | 编译+运行 | 建立模块可读性（readability） | 只有 `requires` 的模块才能访问其 `exports` 包 |
| `transitive` | 编译+运行 | 传递可读性 | 依赖者自动可读该模块 |
| `exports` | 编译+运行 | 公开包的公共类型 | 外部可 `import` / 访问公共成员 |
| `opens` | 仅运行 | 开放包给深度反射 | 外部可做 `setAccessible(true)` 访问私有成员 |
| `uses` / `provides` | 运行 | ServiceLoader 服务绑定 | `ServiceLoader.load(Service)` 找到实现 |

关键区分：**`exports` 管「能不能看见公共 API」，`opens` 管「能不能反射私有成员」**。只 `exports` 不 `opens` 的包，外部可以调用其公共方法，但 `setAccessible(true)` 仍抛 `InaccessibleObjectException`。

## Strong Encapsulation

JDK 9 之前的 classpath 是「全扁平、全可见」的：任何类都能反射任何类的私有成员。JPMS 之后，**非 `opens` 的包其私有成员默认不可被其他模块反射**，即使该模块已被 `requires`。

为兼容遗留代码，提供了粗粒度到细粒度的迁移开关（都在启动参数）：

- `--add-exports <module>/<pkg>=<target>`：让 `target` 模块能访问 `<module>/<pkg>` 的**公共 API**（编译期 + 运行期）。例如 `--add-exports java.base/sun.nio.ch=ALL-UNNAMED`。注意它只放权公共类型，反射私有仍需 `opens`。
- `--add-opens <module>/<pkg>=<target>`：让 `target` 模块在运行期对 `<module>/<pkg>` 拥有**深度反射**权限（`setAccessible(true)` 可用）。`=ALL-UNNAMED` 表示对所有未命名模块（classpath 上的类）开放。
- `--add-reads <module>=<target>`：强行让 `target` 读取 `module`，绕过可读性检查。
- `--add-modules <mod>`：显式把默认不解析的模块（如 `java.xml.bind` 已移除，或 `jdk.incubator.vector` 孵化器）加入根模块集合。

> [!NOTE]
> **`--illegal-access` 在 JDK 17 已被移除**（JEP 403 Strongly Encapsulate JDK Internals）。JDK 9–15 该选项默认 `permit`（仅警告），JDK 16 默认 `deny`，JDK 17 起选项本身不再存在——**强封装成为不可全局绕过的默认行为**，只能逐包用 `--add-opens` 放行。任何「JDK 还能用 `--illegal-access=permit` 放宽」的说法在 JDK 17+ 都不再成立。

对 `jdk.internal.*` 这类内部 API，JDK 25 仍**不导出**，要调用必须 `--add-exports`，且这些内部 API 没有兼容性承诺（可能随版本改名/删除）。

## Module Path and Resolution

模块不再从 classpath 平铺加载，而是从**模块路径**（`--module-path` / `-p`）按可读性图解析：

- 启动入口：`java --module-path libs -m com.example.app/com.example.app.Main`（简写 `-m`）。
- 根模块：默认包含 `java.se` 聚合模块 + 启动类所在模块；额外需要 `--add-modules`。
- **解析过程**：从根模块出发，沿 `requires`（含 `transitive`）传递闭包收集模块，再按 `uses`/`provides` 做服务绑定，形成**可读性图**。缺失依赖直接启动失败（`ModuleFinder` 找不到）。
- **未命名模块（unnamed module）**：classpath 上的所有类构成一个特殊「未命名模块」。它能读取所有命名模块、也被所有命名模块读取，但**命名模块不会主动向它 `exports`/`opens`**——所以即使放在 classpath，第三方库要反射 `java.base` 私有成员仍需 `--add-opens ...=ALL-UNNAMED`。
- **自动模块（automatic module）**：放在模块路径上的普通 JAR 会被当作一个模块，其名由 `Automatic-Module-Name` manifest 或 JAR 名推导，默认 `requires` 所有其他模块、导出所有包——是迁移到模块的过渡形态。

## JMOD and jimage

- **`.jmod` 格式**：JDK 9 起，模块以 `.jmod` 打包（位于 `$JAVA_HOME/jmods/`），内部不仅有 `.class`，还含原生代码、配置、头文件、资源与版本信息。`jmod list/describe/extract` 可检视。
- **`jimage` 格式**：运行时映像 `$JAVA_HOME/lib/modules` 是一个聚合的 `jimage` 文件，把 JDK 所有模块的类和资源拼成一个映像，启动更快、占用更小；它不是一堆 `.jmod`，不能直接当目录看。
- 自己构建时：`jmod create` 打包，`jlink` 基于模块图裁剪出最小运行时映像（`--add-modules` + `--output`），这正是容器化「jlink 瘦身」的基础。

## Module Layers

`ModuleLayer`（`java.lang.ModuleLayer`）是运行时的**分层模块加载器**：每个 `ModuleLayer` 由一组 `Configuration` + 一个父层 + 一组 `ClassLoader` 形成。典型用途是隔离多个版本/多个租户的同名模块（IDE、应用服务器、插件系统）。`ModuleLayer.boot()` 是 JVM 启动时的根层；应用可用 `ModuleLayer.defineModulesWithOneLoader` 等定义新层，实现「同一 JVM 内加载模块图的不同实例」而互不污染。

## Version Baseline

> [!NOTE]
> 本页内容以 **JDK 25** 为准。JPMS 核心语义自 JDK 9 定型，后续版本主要是边界收紧：
> 1. **JDK 16** 起 `--illegal-access` 默认 `deny`；**JDK 17**（JEP 403）移除该选项，强封装为硬默认。
> 2. **JDK 25** 的 `java --list-modules` 仍暴露约 70 个 `java.*` / `jdk.*` 模块；`jdk.internal.*` 内部 API 依旧不导出、无兼容性承诺。
> 3. 孵化器模块（如 `jdk.incubator.vector`）需 `--add-modules` 显式引入，且每个版本可能改名。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) — 强封装直接约束运行期反射
- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md) — 未命名模块 / 层与类加载器
- [Java Agent](/docs/CS/Java/JDK/Agent.md) — `-javaagent` 在模块边界下如何工作
- [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md) — 字节码转换与模块可见性

## References

1. [JEP 261: Module System](https://openjdk.org/jeps/261)
2. [JEP 403: Strongly Encapsulate JDK Internals](https://openjdk.org/jeps/403)
3. [The Java Language Specification, Chapter 7.7: Module Declarations](https://docs.oracle.com/javase/specs/jls/se25/html/jls-7.html#jls-7.7)
4. [Java 9，OSGi 以及模块化的未来](https://www.infoq.cn/article/java9-osgi-future-modularity)
5. [SOFAArk 介绍](https://www.sofastack.tech/projects/sofa-boot/sofa-ark-readme/)
