## Introduction

GraalVM 是以 JVM 为基础、以 Graal 编译器为核心、目标是运行多语言并支持多种执行模式的一整套技术与组件集合，不只是「一个更快的 JIT」。

[JEP 243: Java-Level JVM Compiler Interface](https://openjdk.org/jeps/243)

## 版本基线

> [!WARNING]
> **GraalVM 与 Oracle JDK 是两条独立的发布线，不要按 JDK 版本推断 GraalVM 版本。**
>
> - 当前主线是 **GraalVM for JDK 25**（25.0.x 为 LTS 线，25.1+ 走月度创新节奏，季度 CPU 穿插其中）。它**与 JDK 25 不是一回事**——JDK 25 是 LTS 基线，而 GraalVM 25 是 Oracle 的独立产品线。
> - **JDK 21 / 17** 是较老的 LTS 线，21.x 与 17.x 仍在维护。
> - **GraalVM for JDK 24 是最后一版以「Oracle Java SE 产品的一部分」身份获得许可与支持的版本**；此后 GraalVM 脱离 Java SE 发布列车，成为独立产品线。
> - **macOS x64（Intel Mac）支持已终止**：GraalVM 25 只支持 Linux/Windows x64 与 Linux/macOS AArch64。Intel Mac 上的构建需迁到 Apple Silicon 或改用 Linux/Windows runner。
> - 授权已统一到 **GFTC（GraalVM Free Terms and Conditions）**，可用于生产；旧文的「Community Edition / Enterprise Edition」购买方案**已不存在**。
>
> 详见 [Oracle GraalVM 下载页](https://www.oracle.com/downloads/graalvm-downloads.html) 与 [endoflife.date/oracle-graalvm](https://endoflife.date/oracle-graalvm)。

## 它解决什么问题

标准 HotSpot 的执行模式是「**先解释、再 JIT**」：程序先跑解释器，热点方法被 C1/C2 编译成机器码。这意味着**启动期是慢的**——流量真正上来之前，一部分时间花在解释执行与编译上。

GraalVM 提供另一条路：

| 模式 | 何时编译 | 特点 |
| :-- | :-- | :-- |
| **解释执行 + JIT**（默认 HotSpot） | 运行时热点出现后 | 启动慢，峰值性能高 |
| **AOT 预编译（Native Image）** | 构建期 | 启动极快、内存占用低，峰值略低；受限于「闭世界」假设 |
| **JIT 编译器可替换（JVMCI）** | 运行时 | 把 C2 换成 Graal 等编译器，仍是运行时编译但优化策略不同 |

## JVMCI：把编译器接口开放出来

[JEP 243](https://openjdk.org/jeps/243)（Release 9）引入 **JVM Compiler Interface（JVMCI）**：把 HotSpot 的编译器从「内部私有」变成「可替换插件」。标准 JDK 内置的编译器是 C1（client）与 C2（server），JVMCI 允许第三方实现接入同一套编译管线。

```bash
# 启用 Graal 作为 JIT 编译器（内置于 GraalVM；标准 OpenJDK 也可用 jvmci 组件）
java -XX:+UnlockExperimentalVMOptions -XX:+UseJVMCICompiler
```

> [!NOTE]
> 用了 JVMCI 之后，**解释器仍然存在**——它负责尚未被编译的方法。JVMCI 替换的是「编译策略」，不是「把解释器也换掉」。

## Graal 的两种用法

Graal 这个项目实际有**两个方向**，容易混淆：

1. **作为 GraalVM 的 JIT 编译器**（经 JVMCI 接入）——本质是 C2 的替代品，做更激进的优化。
2. **作为语言实现框架 Truffle** —— 用 Java 写**自优化 AST 解释器**，Graal 编译器再用**部分求值（partial evaluation）**把解释器针对具体程序特化成机器码。GraalJS、GraalPy、TruffleRuby 都是这条路。

Truffle 的核心思想来自「第一费马投影」：**特化一个解释器就等于得到一个编译器**。你只需要写一个相对容易的 AST 解释器，Graal 编译器在运行时分析热点 AST、消除解释器自身的分派开销，产出接近手写编译器的机器码。节点通过 `@Specialization` 注解声明多种特化形式，运行时根据实际观测到的类型自我重写（self-optimizing），推测失效时回退并重新编译。

## Native Image 的闭世界假设

Native Image 把应用编译成独立可执行文件，代价是引入 **closed-world assumption**：编译期必须知道所有可能被执行到的代码。

因此以下情况需要额外处理（反射、动态代理、JNI、资源加载）：

- 反射：需显式注册 `reflect-config.json`；
- 动态代理：需 `proxy-config.json`；
- JNI、资源、`ServiceLoader`：都要相应配置。

这正是 Native Image 最大的工程成本：**可移植性换启动速度，代价是构建期复杂度**。上手可用 Quarkus、Micronaut、Spring AOT 等框架，它们把这些配置自动化了。

## GraalVM 生态速览

| 组件 | 用途 |
| :-- | :-- |
| **Native Image** | AOT 编译成独立二进制，启动快、内存省 |
| **Truffle / GraalJS / GraalPy / TruffleRuby** | 多语言互操作，一进程内跑 JS/Python/Ruby 等 |
| **LLVM Toolchain** | 基于 LLVM 的语言后端 |
| **Espresso** | 基于 Truffle 的 JVM 实现（实验性路线） |
| **Agent / JFR** | 观测能力，部分从 HotSpot 移植而来 |

## 什么时候不该用 Graal

- 只追求**峰值吞吐**且不在乎启动时间 —— HotSpot 的 C2 在长时间稳定运行后通常不输；
- 应用重度依赖动态特性（大量反射、动态类加载、动态代理）却不想付 Native Image 的配置成本；
- 团队没有为「闭世界」假设和构建期复杂度留出预算。

收益更明显的场景：**短生命周期的进程**（Serverless 函数、CLI 工具、容器中需要快速扩容的微服务）——启动时间与内存占用直接决定成本。

## Links

- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)
- [ExecutionEngine](/docs/CS/Java/JDK/JVM/ExecutionEngine.md)
- [ClassFile](/docs/CS/Java/JDK/JVM/ClassFile.md)
- [JMH](/docs/CS/Java/JDK/JVM/JMH.md)

## References

1. [Understanding How Graal Works - a Java JIT Compiler Written in Java](https://chrisseaton.com/truffleruby/jokerconf17/)
2. [Oracle GraalVM 下载页](https://www.oracle.com/downloads/graalvm-downloads.html)
3. [endoflife.date — Oracle GraalVM 支持周期](https://endoflife.date/oracle-graalvm)
