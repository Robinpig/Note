## Introduction

**ASM** 是 Java 生态最流行的**字节码操作与分析框架**（ObjectWeb ASM），以 visitor 模式读写 `.class` 文件，能在不加载类的情况下生成、修改、转换字节码。注意区分：笔记里的 *AsmTools* 是 OpenJDK 官方的 `.class` 生产与测试工具集，二者都围绕 JVM 字节码，但 ASM 定位为通用库，AsmTools 偏 JDK 内部测试。

ASM 提供三套 API：

- **Core（Visitor）**：`ClassReader` 解析字节码并回调 `ClassVisitor`/`MethodVisitor`/`FieldVisitor`，`ClassWriter` 把访问事件重新汇编成 `.class`；事件流模型高效且内存友好。
- **Tree（DOM）**：把类表示成 `ClassNode` 对象树，方便随机修改但更占内存，适合复杂变换。
- **Analysis**：控制流/数据流分析，支撑字节码校验与优化。

## 典型用途

- **AOP / 字节码增强**：Spring AOP（CGLIB 底层用 ASM）、动态代理、方法耗时/埋点、事务注解织入。
- **序列化 / 对象映射**：Kryo、各类 JSON/Proto 框架生成编解码器。
- **Mock / 测试框架**：Mock 子类/接口、Byte Buddy 等均以 ASM 为底座。
- **兼容性与体积**：通过 `ClassWriter` 的 `COMPUTE_MAXS` / `COMPUTE_FRAMES` 让 ASM 自动算栈帧与操作数栈，避免手写 `max_stack` 出错。

## 与 JVM 的关系

ASM 操作的是 [JVM](/docs/CS/Java/JDK/JVM/JVM.md) 规定的 `.class` 文件格式（u4 魔数 `CAFEBABE`、常量池、字段/方法表、Code 属性中的字节码指令）；理解 **class 文件结构**与**栈式指令集**是用好 ASM 的前提。AsmTools 则提供 `jasm`/`jcoder` 等把类文件当作文本来生产/反汇编，常用于构造「非法但故意为之」的类验证 JVM 健壮性。

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [JDK](/docs/CS/Java/JDK/JDK.md)
- [AspectJ](/docs/CS/Java/AspectJ.md)

## References

- [AsmTools (OpenJDK CodeTools)](https://wiki.openjdk.org/display/CodeTools/asmtools)
- [ASM - Java bytecode manipulation framework](https://asm.ow2.io/)
