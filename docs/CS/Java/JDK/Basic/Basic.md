## Introduction

`Basic` 子树覆盖 **Java 语言基础与 JVM 运行时边界**：从对象与类型模型、语言语义，到反射/`Unsafe`/`JNI` 等底层互操作，再到 JDK 工具链与企业集成。它与 `Collection`/`Concurrency`/`JVM` 三个已实现子树互补——`JVM` 偏 HotSpot 实现，`Basic` 偏语言层事实与可观察行为。

## Object and Type Model

Java 的类型体系只有两族：**[primitive types](/docs/CS/Java/JDK/Basic/PrimitiveType.md)** 与 **[reference types](/docs/CS/Java/JDK/Basic/Ref.md)**，引用又细分为 class、interface、type variable、array 四类。所有对象的统一入口是 **[Object](/docs/CS/Java/JDK/Basic/Object.md)**（identity、header、clone、`equals`/`hashCode` 契约）；`String` 的不可变与字符串内联、`enum` 的编译器生成（`values()`/`valueOf()` 与单例安全性）、`record` 的透明载体语义（见 [New](/docs/CS/Java/JDK/New.md?id=record) 的 JDK 16 条目）都是对象模型的延伸。

## Language Semantics

声明式语言机制成体系展开：**[semantics](/docs/CS/Java/JDK/Basic/semantics.md)** 记录 Effective Java 中易被忽略的语义规则（求值顺序、`==` vs `equals`、异常屏蔽）；**[Generics](/docs/CS/Java/JDK/Basic/Generics.md)** 讲类型擦除、桥方法与 PECS；**[Annotation](/docs/CS/Java/JDK/Basic/Annotation.md)** 覆盖元注解、重复注解（JEP 120）与类型注解（JEP 104）；**[SPI](/docs/CS/Java/JDK/Basic/SPI.md)** 是 `ServiceLoader` 驱动的服务加载，与模块系统的 `provides`/`uses` 衔接。

## Runtime Boundary and Interop

突破语言层进入 JVM 边界的主题群：**[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)** 与 **[Ref](/docs/CS/Java/JDK/Basic/Ref.md)**（四种引用与 GC 交互）；**[unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)** 提供字段偏移与堆外内存（JEP 471 起弃用内存访问方法）；**[JNI](/docs/CS/Java/JDK/Basic/JNI.md)** 是 native 边界（其现代替代是 FFM API，见 [New](/docs/CS/Java/JDK/New.md) 的 JDK 22）；字节码增强链路 **[ASM](/docs/CS/Java/JDK/ASM.md)** → **[Agent](/docs/CS/Java/JDK/Agent.md)** → **[Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)**；JVM 内建函数见 **[Intrinsics](/docs/CS/Java/JDK/Basic/Intrinsics.md)**；模块化边界见 **[module](/docs/CS/Java/JDK/Basic/module.md)**；对象图持久化见 **[serialize](/docs/CS/Java/JDK/Basic/serialize.md)**。

## Tools and Operations

面向工程化：命令行工具链见 **[Tools](/docs/CS/Java/JDK/Basic/Tools.md)**（编译/诊断/JFR/jshell）；企业集成见 **[JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)** 与 **[JNDI](/docs/CS/Java/JDK/Basic/JNDI.md)**；版本迁移见 **[Upgrade](/docs/CS/Java/JDK/Upgrade.md)**；定时任务总览见 [sche](/docs/CS/Java/JDK/sche.md)；异常体系见 **[Throwable](/docs/CS/Java/JDK/Basic/Throwable.md)**。

## JVM Internals Sketch

`Basic` 也收纳少量 HotSpot 实现视角，作为通向 `JVM` 子树的入口。`java` launcher 启动分五步：取参 → 预置环境 → 加载 `libjvm` → 解析参数/路径 → 建线程创建 VM 并调 `main`。JVM 子系统可粗分为 Runtime（Thread/Arguments/Frame/VmThread/VmOperation）、Memory/GC、Compiler（C1/Opto）、Interpreter、Code、Oops，以及服务于 JMX 的 Management 层（MemoryService/MemoryPool/ThreadService 等）。这些更偏实现细节，深挖请转 [JVM](/docs/CS/Java/JDK/JVM/JVM.md)。

## This Directory Navigation

按「对象与类型 → 语言语义 → 运行时边界 → 工具」四组组织：

- 对象与类型：[Object](/docs/CS/Java/JDK/Basic/Object.md)、[PrimitiveType](/docs/CS/Java/JDK/Basic/PrimitiveType.md)、[String](/docs/CS/Java/JDK/Basic/String.md)、[enum](/docs/CS/Java/JDK/Basic/enum.md)、[Generics](/docs/CS/Java/JDK/Basic/Generics.md)、[Lambda](/docs/CS/Java/JDK/Basic/Lambda.md)、[Annotation](/docs/CS/Java/JDK/Basic/Annotation.md)
- 语言语义：[semantics](/docs/CS/Java/JDK/Basic/semantics.md)、[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)、[Ref](/docs/CS/Java/JDK/Basic/Ref.md)、[serialize](/docs/CS/Java/JDK/Basic/serialize.md)、[Throwable](/docs/CS/Java/JDK/Basic/Throwable.md)、[SPI](/docs/CS/Java/JDK/Basic/SPI.md)、[module](/docs/CS/Java/JDK/Basic/module.md)
- 运行时边界：[unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)、[JNI](/docs/CS/Java/JDK/Basic/JNI.md)、[JDBC](/docs/CS/Java/JDK/Basic/JDBC.md)、[JNDI](/docs/CS/Java/JDK/Basic/JNDI.md)、[Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md)、[Intrinsics](/docs/CS/Java/JDK/Basic/Intrinsics.md)、[Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)
- 工具与调度：[JDK 命令行工具](/docs/CS/Java/JDK/Basic/Tools.md)、[定时任务总览](/docs/CS/Java/JDK/sche.md)、[升级迁移](/docs/CS/Java/JDK/Upgrade.md)

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
