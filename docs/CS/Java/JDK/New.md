## Introduction

自 JDK 9 起，Java 进入**每半年一个特性发布**的节奏（3 月 / 9 月），长期支持（LTS）版本为 **JDK 8 → 11 → 17 → 21 → 25**。新能力通过 **JEP（JDK Enhancement Proposal）** 引入：预览（Preview）特性需 `--enable-preview`，孵化器（Incubator）特性在独立模块中，二者都可能在后续版本调整或撤回。本页按版本梳理与已做实笔记对应的关键特性；专项机制请转对应子页。

## Java 8 (2014)

现代 Java 的起点：Lambda 表达式与 `java.util.stream`（函数式管道）、新的 `java.time` 日期时间 API、`default`/`static` 接口方法、Nashorn JavaScript 引擎、`PermGen` 被 `Metaspace` 取代。并发侧引入 `CompletableFuture` 与 `StampedLock`。

## Java 9 (2017)

- **JPMS 模块系统**（JSR 376）：最强的结构性变更，强封装与反射边界见 [module](/docs/CS/Java/JDK/Basic/module.md)。
- **jshell**（JEP 222）：REPL。
- **接口私有方法**（JEP 213）：支撑 `default` 方法复用。
- **G1 成为默认 GC**（JEP 248）。
- **VarHandle**（JEP 193）：类型安全、支持内存屏障的字段/数组访问，是 [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md) 内存访问的现代替代之一。
- **集合工厂方法** `List.of`/`Set.of`/`Map.of`（JEP 269）：不可变集合字面量。

## Java 10 (2018)

- **局部变量类型推断 `var`**（JEP 286）：仅限局部变量，编译期推断，非动态类型。

## Java 11 (2018, LTS)

- **标准 HTTP Client**（JEP 321，`java.net.http`）：支持 HTTP/1.1、HTTP/2、WebSocket，替代 `HttpURLConnection`。
- **Java Flight Recorder 开源**（JEP 328）：低开销事件型性能剖析。
- **ZGC 实验性引入**（JEP 333）、**TLS 1.3**（JEP 332）、**Epsilon 无操作 GC**（JEP 318）。
- 移除 Java EE 与 CORBA 模块（JEP 320）；`var` 可用于 lambda 参数（JEP 323）；单文件源码直接启动（JEP 330）。

## Java 12 – 13 (2018 – 2019)

- **Switch Expressions** 两轮预览（JEP 325 / JEP 354），引入 `case ->` 箭头语法与表达式形式。
- **Text Blocks** 预览（JEP 355，`"""` 多行字符串）。

## Java 14 (2020)

- **Switch Expressions 终版**（JEP 361）：`switch` 可作表达式，`yield` 产出值。
- **Helpful NullPointerExceptions**（JEP 358）：精确提示哪个变量为 `null`。
- **Records 预览**（JEP 359）、**Pattern Matching for `instanceof` 预览**（JEP 305）。
- 移除 CMS 收集器（JEP 363）。

## Java 15 (2020)

- **Text Blocks 终版**（JEP 378）。
- **ZGC / Shenandoah 脱离实验**（JEP 377 / JEP 379）。
- **Sealed Classes 预览**（JEP 360）、**Hidden Classes**（JEP 371，详见 [Valhalla](/docs/CS/Java/JDK/Valhalla.md)）。
- **Records 第二轮预览**（JEP 384）；移除 Nashorn（JEP 372）。

## Java 16 (2021)

### Record

Records 终版（JEP 395）：透明不可变数据载体，编译器自动生成 `equals`/`hashCode`/`toString` 与访问器，可与模式匹配、密封类组合。

```java
public record Demo(String username, String password) {}
```

- **Pattern Matching for `instanceof` 终版**（JEP 394）。
- **默认强封装 JDK 内部 API**（JEP 396）：`--illegal-access` 控制力进一步收紧（JDK 17 彻底移除该选项，见 [module](/docs/CS/Java/JDK/Basic/module.md)）。
- 打包工具 `jpackage` 终版（JEP 392）；Unix-Domain Socket Channels（JEP 380）。

## Java 17 (2021, LTS)

- **Sealed Classes 终版**（JEP 409）：`sealed`/`permits`/`non-sealed` 约束子类型，配合模式匹配实现穷尽处理。
- **强封装 JDK 内部 API**（JEP 403）：`--illegal-access` 选项被**移除**，仅能逐包 `--add-opens`。
- **上下文反序列化过滤**（JEP 415）：`jdk.serialFilterFactory` 按线程/调用栈动态选过滤，详见 [serialize](/docs/CS/Java/JDK/Basic/serialize.md)。
- **增强伪随机数发生器**（JEP 356）、**弃用 Security Manager 以待移除**（JEP 411）、弃用 Applet API（JEP 398）。

## Java 18 (2022)

UTF-8 成为默认字符集（JEP 400）；简易 Web 服务器（JEP 408）；Javadoc 代码片段（JEP 413）；**用 Method Handles 重实现 Core Reflection**（JEP 416，呼应 [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)）；弃用 Finalization（JEP 421）。

## Java 19 (2022)

- **虚拟线程首轮预览**（JEP 425）：轻量线程，由 JVM 而非 OS 调度，终结版见 JDK 21，机制见 [Loom](/docs/CS/Java/JDK/Loom.md) 与 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)。
- **Structured Concurrency 孵化器**（JEP 428）、**Scoped Values 预览**（JEP 429）。
- **Record Patterns 预览**（JEP 405）、**FFM API 预览**（JEP 424）、Linux/RISC-V 移植（JEP 422）。

## Java 21 (2023, LTS)

- **虚拟线程终版**（JEP 444）：高吞吐并发的范式转变。
- **Sequenced Collections**（JEP 431）：引入 `SequencedCollection`/`SequencedSet`/`SequencedMap`，统一首尾访问与反向视图，详见 [Collection](/docs/CS/Java/JDK/Collection/Collection.md)。
- **分代 ZGC**（JEP 439）、**Record Patterns 终版**（JEP 440）、**Pattern Matching for `switch` 终版**（JEP 441）。
- **KEM API**（JEP 452）；Scoped Values / Structured Concurrency / String Templates 预览（JEP 446 / 453 / 430）；Unnamed Classes 与实例主方法预览（JEP 445）。
- **准备禁止动态加载 Agent**（JEP 451）：与 [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md) / [Agent](/docs/CS/Java/JDK/Agent.md) 的运行时增强路径相关。

## Java 22 (2024)

- **FFM API 终版**（JEP 454）：安全调用 native 函数与访问堆外内存，是 [JNI](/docs/CS/Java/JDK/Basic/JNI.md) 的现代替代，经 `Linker`/`MemorySegment`/`Arena` 暴露。
- **未命名变量与模式终版**（JEP 456，`_` 占位）、**G1 Region Pinning**（JEP 423，缓解 JNI 临界区 GC 停顿）、多文件源码启动（JEP 458）。
- **Class-File API 预览**（JEP 457，与 [ASM](/docs/CS/Java/JDK/ASM.md) 同领域）、**Stream Gatherers 预览**（JEP 461）、Scoped Values / Structured Concurrency 第二轮预览。

## Java 23 (2024)

- **模式中的基本类型预览**（JEP 455）、**模块导入声明预览**（JEP 476）、**Markdown 文档注释**（JEP 467）。
- **ZGC 默认分代模式**（JEP 474）；**终止式弃用 `sun.misc.Unsafe` 内存访问方法**（JEP 471，详见 [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)）。
- Stream Gatherers / Structured Concurrency / Scoped Values 继续预览（JEP 473 / 480 / 481）。

## Java 24 (2025)

- **永久禁用 Security Manager**（JEP 486，自 JDK 17 弃用后彻底移除）。
- **使用 `Unsafe` 内存访问方法时发出警告**（JEP 498）：配合 `--sun-misc-unsafe-memory-access`，推动迁移到 VarHandle / MemorySegment。
- **`jnativescan` 工具**（JEP 472，限制 JNI 使用）；**Class-File API 终版**（JEP 484）、**Stream Gatherers 终版**（JEP 485）。
- **紧凑对象头实验性**（JEP 450，对象头缩至 64 位，呼应 [Object](/docs/CS/Java/JDK/Basic/Object.md) 头布局）；**分代 Shenandoah 实验性**（JEP 404）；**虚拟线程同步不再 pinning**（JEP 491，见 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)）；AOT 类加载与链接（JEP 483）。

## Java 25 (2025, LTS)

- **Scoped Values 终版**（JEP 506）：线程内与子线程间共享不可变数据，替代 ThreadLocal，详见 [ScopedValues](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)。
- **Structured Concurrency 第五轮预览**（JEP 505）：将相关任务组视为单一工作单元，详见 [StructuredTaskScope](/docs/CS/Java/JDK/Concurrency/StructuredTaskScope.md)。
- **模块导入声明终版**（JEP 511）、**紧凑源文件与实例主方法终版**（JEP 512）、**灵活构造器体终版**（JEP 513）。
- **稳定值预览**（JEP 502）、**紧凑对象头终版**（JEP 519）、**分代 Shenandoah 终版**（JEP 521）、**移除 32 位 x86 端口**（JEP 503）；PEM 编码与 KDF API 交付（JEP 470 / 510）；Vector API 第十轮孵化（JEP 508）。

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [OpenJDK JEP Index](https://openjdk.org/jeps/0)

## References

1. [OpenJDK JDK 17 JEPs since JDK 11](https://openjdk.org/projects/jdk/17/jeps-since-jdk-11)
2. [OpenJDK JDK 21 JEPs since JDK 17](https://openjdk.org/projects/jdk/21/jeps-since-jdk-17)
3. [Java Version Almanac](https://javaalmanac.io/jdk/)
