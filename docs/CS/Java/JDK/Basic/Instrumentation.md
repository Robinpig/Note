## Introduction

`java.lang.instrument.Instrumentation` 是 Java Agent 的能力入口：它提供「在类加载时或加载后修改字节码」「测量对象大小」「枚举已加载类」等 JVM 级操作。官方定义是——instrumentation 即向方法注入字节码以收集工具所需数据，由于改动是纯增量的，工具不改变应用状态或行为；典型场景是监控 agent、profiler、覆盖率、日志。其底层实现基于 **JVMTI 的 `RedefineClasses` → `redefine_single_class`**，即对已有类定义做整体替换。

获取 `Instrumentation` 实例只有两条路径，且都由 JVM 在固定时机注入：

1. **启动时（premain）**：JVM 以 `-javaagent:agent.jar` 启动，实例化 agent 类后把 `Instrumentation` 传给其静态 `premain(String agentArgs, Instrumentation inst)`。
2. **运行后（agentmain）**：JVM 启动后通过 **Attach API**（`com.sun.tools.attach`）把 agent 动态挂载，此时 `Instrumentation` 传给 agent 类的静态 `agentmain(String agentArgs, Instrumentation inst)`。

一旦 agent 拿到实例，即可在任意时刻调用其方法（详见 [Java Agent](/docs/CS/Java/JDK/Agent.md)）。

## Core API

`Instrumentation` 接口（JDK 25，`src/java.instrument/.../Instrumentation.java`）方法按用途分四类：

**(1) 字节码转换器管理**
- `addTransformer(ClassFileTransformer transformer, boolean canRetransform)`：注册转换器；`canRetransform=true` 时该转换器会参与后续 `retransformClasses`。
- `addTransformer(ClassFileTransformer transformer)`：等价于 `addTransformer(t, false)`。
- `removeTransformer(ClassFileTransformer transformer)`：注销转换器。

`ClassFileTransformer.transform(Module, ClassLoader, String className, Class<?> classBeingRedefined, ProtectionDomain, byte[] buffer)` 在每次类加载（或重转换）时被调用，返回修改后的字节码或 `null`（表示不修改）。JDK 9+ 该方法的第一个参数新增 `Module`，以适配模块系统。

**(2) 类重定义 / 重转换**
- `redefineClasses(ClassDefinition... definitions)`：用给定字节码**整体替换**类的当前定义，不经过转换器链。
- `retransformClasses(Class<?>... classes)`：触发已注册转换器链重新生成这些类的字节码。
- `isRedefineClassesSupported()` / `isRetransformClassesSupported()`：能力是否可用（依赖 manifest 声明）。

**(3) 内省**
- `getAllLoadedClasses()`：返回 JVM 中所有已加载的类。
- `getInitiatedClasses(ClassLoader loader)`：返回某加载器**发起**加载的类。
- `isModifiableClass(Class<?>)`：该类是否可被重定义/重转换。
- `getObjectSize(Object)`：返回该对象在堆上的「浅大小」（shallow size，不含其引用指向的对象），是排查内存占用的利器。

**(4) 类路径与符号增强**
- `appendToBootstrapClassLoaderSearch(JarFile)` / `appendToSystemClassLoaderSearch(JarFile)`：把 JAR 追加进 bootstrap / 系统加载器的搜索范围，使 agent 自己提供的类能被更高优先级的加载器看见（常用于改写 `java.*` 平台类）。
- `setNativeMethodPrefix(ClassFileTransformer, String)` / `isNativeMethodPrefixSupported()`：给原生方法加前缀以绕过「native 方法无法重定义」的限制（让 agent 把一个 native 方法改名后接管）。

## redefine vs retransform

| 维度 | `redefineClasses` | `retransformClasses` |
| :-- | :-- | :-- |
| 字节码来源 | 调用方直接提供的 `ClassDefinition` | 经过全部 `canRetransform=true` 的 `ClassFileTransformer` 链重新生成 |
| 是否走转换器 | 否 | 是 |
| 典型用途 | 回滚到某版本、一次性热修复 | agent 持续注入逻辑（诊断/监控） |
| 限制 | 同下 | 同下 |

两者共享 JVM TI 的硬限制——**都不能增删方法或字段、不能改变方法签名（参数/返回类型）、不能改变类的父类或实现的接口、不能改变 `final`/`static` 等结构性修饰符的语义**；静态字段的值保持不变（类不会被重新初始化）。`Lambda` / 匿名类、部分 VM 内部类属于 frozen 类，不可修改。

## Manifest Attributes

agent JAR 的 `META-INF/MANIFEST.MF` 通过属性声明能力与入口：

| 属性 | 含义 |
| :-- | :-- |
| `Premain-Class` | 启动时 agent 类（含 `premain`），缺省则 `-javaagent` 报错 |
| `Agent-Class` | 运行后 agent 类（含 `agentmain`），配合 Attach API |
| `Can-Redefine-Classes` | `true` 时 `redefineClasses` 才可用，否则抛 `UnsupportedOperationException` |
| `Can-Retransform-Classes` | `true` 时 `retransformClasses` 才可用 |
| `Can-Set-Native-Method-Prefix` | `true` 时 `setNativeMethodPrefix` 可用 |
| `Boot-Class-Path` | 追加到 bootstrap 加载器搜索路径，用于改写平台类 |
| `Launcher-Class` | 指定真正的主类，agent 先初始化再委托（agent 充当启动器时） |

> [!NOTE]
> JDK 9+ 模块化后，agent 改写**命名模块**中的类要服从模块图：要改 `java.base` 等平台类，通常需 `Boot-Class-Path` 把 agent 类放进 bootstrap 加载器，或用 `appendToBootstrapClassLoaderSearch`；对普通模块类的私有成员操作仍受该模块 `opens` 约束。

## Version Baseline

> [!NOTE]
> 本页以 **JDK 25** 为准。`java.lang.instrument` 自 JDK 5 引入、JDK 9 适配模块系统（新增 `Module` 参数与 `ModuleLayer` 相关语义）后接口基本稳定；`getObjectSize`、`redefineClasses` 等方法签名在 JDK 25 中仍然如上。能力是否生效取决于 manifest 的 `Can-*` 声明，与 JDK 版本无关。

## Links

- [Java Agent](/docs/CS/Java/JDK/Agent.md) — `premain` / `agentmain` 与转换器落地
- [ASM](/docs/CS/Java/JDK/ASM.md) — 在 `ClassFileTransformer` 里改写字节码
- [Module](/docs/CS/Java/JDK/Basic/module.md) — agent 改写受模块图约束
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md) — 与 `setAccessible` 互补的运行时侵入手段
- [Serviceability](/docs/CS/Java/JDK/JVM/Serviceability.md) — JVM 可观测性协同

## References

1. [Java SE 25 API: java.lang.instrument](https://docs.oracle.com/en/java/javase/25/docs/api/java.instrument/java/lang/instrument/Instrumentation.html)
2. [The JVM Tool Interface (JVMTI) — RedefineClasses](https://docs.oracle.com/en/java/javase/25/docs/specs/jvmti.html#RedefineClasses)
3. [Java Agent 机制与 Instrumentation 实践](https://www.baeldung.com/java-instrumentation)
