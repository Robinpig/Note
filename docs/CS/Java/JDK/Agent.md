## Introduction

Java Agent（Java 代理）是 JDK 1.5 引入、位于 `java.lang.instrument` 包下的字节码增强机制。它在 **JVM 启动前（`premain`）或启动后（`agentmain`）** 介入类加载/重定义过程，修改方法字节码——类似于 AOP，但发生在 JVM 层面、对应用代码完全无侵入。

一个 Agent 本质上是一个符合约定结构的 **jar 包**：包含 `premain`/`agentmain` 入口方法、一个 manifest 描述符，以及（通常）实现 `ClassFileTransformer` 的字节码转换器。运行时由 `Instrumentation` 实例驱动（详见 [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)）。

## Lifecycle

Agent 有两条加载时机，对应两套入口方法：

| 加载时机 | 入口方法 | 触发方式 | 约束 |
| --- | --- | --- | --- |
| **静态**（JVM 启动早期，`main` 之前） | `public static void premain(String args, Instrumentation inst)` | 命令行 `-javaagent:/path/to/agent.jar` | 启动即加载，可截获所有后续类加载 |
| **动态**（运行中 JVM） | `public static void agentmain(String args, Instrumentation inst)` | 通过 **Attach API** 向目标 JVM 注入 | 目标 JVM 需开启 `com.sun.management` 且支持 attach |

> `premain`/`agentmain` 的 **单参数重载**（`(String)`）也存在：当 manifest 未声明对应双参方法时 JVM 会回退调用单参版本。`premain` 必须在 `main` 之前返回，否则应用不会启动；`agentmain` 在 attach 线程中执行，失败仅记录异常、不影响目标 JVM。

同一个 agent jar **可以同时实现 `premain` 与 `agentmain`**（双入口），从而既支持启动加载也支持运行时注入。

## Manifest Attributes

Agent jar 的 `META-INF/MANIFEST.MF` 通过以下属性声明行为（`Instrumentation.md` 已逐条对应到 `Instrumentation` API）：

| 属性 | 含义 |
| --- | --- |
| `Premain-Class` | 含 `premain` 的类；声明了才可被 `-javaagent` 加载 |
| `Agent-Class` | 含 `agentmain` 的类；声明了才可被 Attach 注入 |
| `Can-Redefine-Classes` | 是否允许 `Instrumentation.redefineClasses`（默认 `false`） |
| `Can-Retransform-Classes` | 是否允许 `Instrumentation.retransformClasses`（默认 `false`） |
| `Can-Set-Native-Method-Prefix` | 是否允许 `setNativeMethodPrefix`（默认 `false`） |
| `Boot-Class-Path` | 追加到 Bootstrap 类加载器搜索路径的 jar/目录，用于增强 JDK 核心类 |
| `Launcher-AllPermissions` *(已废弃)* | 旧版授予 AllPermission，模块化后由 `--add-opens` 取代 |

> 增强 JDK 内部类（如 `java.lang.String`）必须 `Boot-Class-Path` + 对应 `--add-opens`，否则受 [module](/docs/CS/Java/JDK/Basic/module.md) 强封装拦截。

## Bytecode Modification Chain

```text
-javaagent / Attach
      │
      ▼
premain / agentmain(String, Instrumentation)
      │  inst.addTransformer(transformer, canRetransform)
      ▼
ClassFileTransformer.transform(...)  ← 每次类加载 / retransform 回调
      │  返回修改后的 byte[]（或 null 表示不修改）
      ▼
JVM 定义增强后的类
```

转换器通常会借助 **[ASM](/docs/CS/Java/JDK/ASM.md)**（或 Byte Buddy、Javassist）解析并改写 class 文件。基于这套链路，应用生态得以在不改业务源码的前提下注入监控、诊断与逻辑。

## Use Cases

| 场景 | 典型代表 | 说明 |
| --- | --- | --- |
| APM / 链路追踪 | SkyWalking、Pinpoint、Elastic APM | 在方法出入口插桩采集耗时与调用链 |
| 诊断 / 运行时观测 | **Arthas**、btrace | attach 后动态增强，打印参数、调用栈 |
| 字节码增强框架 | Byte Buddy、CGLIB、PowerMock | 运行时代理/子类化/Mock |
| 热更新 | JRebel、Spring Loaded | `redefineClasses` 替换方法体 |
| 安全 / 防护 | RASP | 在危险 API 前插入校验逻辑 |

## Relationship with Instrumentation

本篇聚焦 **Agent 的打包、生命周期与生态**；`Instrumentation` 实例的具体 API（`addTransformer`/`redefineClasses`/`retransformClasses`/`getObjectSize` 等）、JVM TI 对重定义的硬限制，以及模块化下的改写约束，集中在 [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)。两者是同一机制的两层：Agent 是「**如何被加载进 JVM**」，Instrumentation 是「**加载后能用它做什么**」。

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [ASM](/docs/CS/Java/JDK/ASM.md)
- [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)
- [Java Agent 示例](/docs/CS/Java/JDK/Extension/AgentDemoExample.md)
- [Project Loom](/docs/CS/Java/JDK/Loom.md)
- [Serviceability](/docs/CS/Java/JDK/JVM/Serviceability.md)

## References

1. [JEP 159: Enhanced Class Redefinition](https://openjdk.org/jeps/159)
2. [Package java.lang.instrument](https://docs.oracle.com/en/java/javase/25/docs/api/java.instrument/java/lang/instrument/package-summary.html)
3. [The Attach API (com.sun.tools.attach)](https://docs.oracle.com/en/java/javase/25/docs/api/jdk.attach/com/sun/tools/attach/package-summary.html)
