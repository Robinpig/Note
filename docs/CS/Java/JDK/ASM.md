## Introduction

**ASM** 是 Java 生态最流行的**字节码操作与分析框架**（ObjectWeb ASM），以 visitor 模式读写 `.class` 文件，能在不加载类的情况下生成、修改、转换字节码。注意区分：笔记里的 *AsmTools* 是 OpenJDK 官方的 `.class` 生产与测试工具集，二者都围绕 JVM 字节码，但 ASM 定位为通用库，AsmTools 偏 JDK 内部测试。

ASM 提供三套 API：

- **Core（Visitor）**：`ClassReader` 解析字节码并回调 `ClassVisitor`/`MethodVisitor`/`FieldVisitor`，`ClassWriter` 把访问事件重新汇编成 `.class`；事件流模型高效且内存友好，是绝大多数库（CGLIB、Byte Buddy、SkyWalking、Arthas）的底座。
- **Tree（DOM）**：把类表示成 `ClassNode` 对象树，方便随机修改但更占内存，适合复杂变换。
- **Analysis**：控制流/数据流分析（`Analyzer`/`Frame`/`Interpreter`），支撑字节码校验与优化，也是 FindBugs/SpotBugs 类工具的基础。

## Core API Event Flow

一次典型的「读 → 转换 → 写」管线：

```java
ClassReader cr = new ClassReader(bytes);          // 输入原始 .class 字节
ClassWriter cw = new ClassWriter(cr, 0);           // 输出汇编器
ClassVisitor cv = new MyClassVisitor(cw);          // 自定义变换逻辑
cr.accept(cv, 0);                                  // 触发事件流：visit / visitMethod / visitEnd ...
byte[] out = cw.toByteArray();                     // 拿到改写后的 .class
```

事件流是单向顺序的：`ClassReader` 按 class 文件结构顺序回调——`visit` → `visitSource` → `visitField*` → `visitMethod*` → `visitEnd`。`MethodVisitor` 的方法体指令通过 `visitInsn`/`visitVarInsn`/`visitMethodInsn` 等逐一回放，改写时通常继承 `MethodVisitor` 并重写关心的 `visitXxx`，其余 `super.visitXxx` 透传给下游 `ClassWriter`。

## Key Classes

| 类 | 角色 |
| --- | --- |
| `ClassReader` | 解析 `.class`，驱动事件流 |
| `ClassWriter` | 把访问事件汇编回字节；`toByteArray()` 产出 `.class` |
| `ClassVisitor` | 类级回调入口（`visit`/`visitField`/`visitMethod`/`visitEnd`） |
| `MethodVisitor` | 方法级回调（指令、异常表、局部变量表） |
| `FieldVisitor` | 字段级回调 |
| `Opcodes` | 全部 JVM  opcode 常量与 ASM API 版本号（`ASM9`） |
| `Type` | 描述符 ↔ 类型互转、方法签名解析 |
| `AdviceAdapter` | `MethodVisitor` 子类，提供 `onMethodEnter`/`onMethodExit` 钩子，便于织入 |
| `Analyzer` / `Frame` / `Interpreter` | Analysis 包，做控制流/数据流分析 |

## COMPUTE_FRAMES and COMPUTE_MAXS

`ClassWriter` 的构造标志决定是否让 ASM 自动计算结构信息，避免手写出错：

- `COMPUTE_MAXS`：ASM 自动算每个方法的 `max_stack`（操作数栈上限）与 `max_locals`（局部变量槽数）。
- `COMPUTE_FRAMES`：在 `COMPUTE_MAXS` 基础上，ASM 还自动计算并插入栈帧（`StackMapTable`）。**这是 JDK 6+ 验证器强制要求的属性**，手写极容易出错，几乎总是应该开启。

注意：`COMPUTE_FRAMES` 在合并两个类的公共父类时会调用 `getCommonSuperClass`，其默认实现会用 `ClassLoader` 实际加载类。在**未加载目标类的场景**（如离线改写、agent 预处理）必须重写该方法，否则抛 `ClassNotFoundException`。常见做法是用 `ClassReader` 自身做类型层级分析，或缓存已解析的类型。

## Version and JDK Class File Support

ASM 的 API 版本（`ASM9`）与 Java class 文件主版本号（major version）一一对应；每出一个新 JDK，ASM 需要发新版以支持新 opcode / 新属性（如 `record` 的 `Record` 属性、`sealed` 的 `PermittedSubclasses` 属性）。经验法则：ASM 大版本号 ≈ 它能正确处理的最高 JDK class 版本。升级 JDK 后若遇到 `IllegalArgumentException: Unsupported class file major version`，多半是 ASM 依赖过旧，需要升级 `org.ow2.asm:asm` 到匹配的 9.x。

## Typical Uses

- **AOP / 字节码增强**：Spring AOP（CGLIB 底层用 ASM）、动态代理、方法耗时/埋点、事务注解织入。
- **序列化 / 对象映射**：Kryo、各类 JSON/Proto 框架生成编解码器。
- **Mock / 测试框架**：Mock 子类/接口、Byte Buddy 等均以 ASM 为底座。
- **兼容性与体积**：通过 `ClassWriter` 的 `COMPUTE_MAXS` / `COMPUTE_FRAMES` 让 ASM 自动算栈帧与操作数栈，避免手写 `max_stack` 出错。

## Relationship with Agent and Instrumentation

ASM 是 **Java Agent 字节码增强**的实现底座，与 [Agent](/docs/CS/Java/JDK/Agent.md) / [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md) 构成完整链路：

1. JVM 启动（`-javaagent`）或运行时（Attach API + `agentmain`）加载 Agent；
2. Agent 注册 `ClassFileTransformer`，在类加载/重定义时拿到原始字节；
3. 用 ASM（或 Byte Buddy 等封装）解析、改写、重新汇编字节；
4. 把结果交回 JVM——`premain` 路径由类加载器直接采用，`agentmain` 路径通过 `Instrumentation.redefineClasses`/`retransformClasses` 落地。

理解 **class 文件结构**与**栈式指令集**是用好 ASM 的前提；ASM 操作的就是 [JVM](/docs/CS/Java/JDK/JVM/JVM.md) 规定的 `.class` 格式（u4 魔数 `CAFEBABE`、常量池、字段/方法表、Code 属性中的字节码指令）。AsmTools 则提供 `jasm`/`jcoder` 把类文件当作文本来生产/反汇编，常用于构造「非法但故意为之」的类验证 JVM 健壮性。

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)
- [Agent](/docs/CS/Java/JDK/Agent.md) — 字节码增强的加载入口（生命周期/打包）
- [Instrumentation](/docs/CS/Java/JDK/Basic/Instrumentation.md) — 运行时改写 API（redefine/retransform）
- [AspectJ](/docs/CS/Java/AspectJ.md)

## References

- [ASM - Java bytecode manipulation framework](https://asm.ow2.io/)
- [ASM User Guide](https://asm.ow2.io/asm4-guide.pdf)
- [AsmTools (OpenJDK CodeTools)](https://wiki.openjdk.org/display/CodeTools/asmtools)
