## Introduction

An intrinsic function is a function that has special handling by the compiler or interpreter for our programming language. More specifically, it's a special case where the compiler or interpreter can replace the function with an alternative implementation for various reasons.

The programming language typically handles this by understanding that a specific method call is special, and whenever we call this method, then the resulting behavior is different. This then allows our code to look no different from normal, but the programming language's implementation can intervene in special cases to give additional benefits.

The exact way that it works varies between programming languages and also between operating systems and hardware. However, because these are handled for us, we typically don't need to know any of these details.

Intrinsics can give various benefits. Replacing particular algorithms with native code can make them perform better or even leverage the operating system's specific features or underlying hardware.

The JVM implements intrinsics by replacing the exact method call on an exact class with an alternative version. The JVM handles this itself, so it will only work for core classes and particular architectures. It also allows only certain methods to be swapped out, rather than entire classes.

Exactly how this works will vary between JVMs. This includes not only different versions of the JVM — Java 8 vs. Java 11, for example. This also includes different JVM targets — Linux vs. Windows, for example — and especially JVM vendors — Oracle vs. IBM. In some cases, certain command-line flags passed to the JVM can affect them.

This variety means that there's no way to determine, based only on the application, which methods will be replaced with intrinsic and which won't. It'll be different based on the JVM running the application. But this can lead to surprising results in some cases — including significant performance benefits achieved simply by changing the JVM used.

## How It Works

In HotSpot, intrinsics are resolved at **JIT compile time** (C2 compiler), not at interpretation:

1. The bytecode parser emits a normal call node (`CallStaticJavaNode`) for a `java.*` method.
2. C2's ideal-graph matcher recognizes the `(class, name, signature)` against a built-in table (`vmSymbols` + `LibraryCallKit`).
3. Instead of emitting a call, it lowers the node to **platform-specific MachNodes** — either inline machine instructions (e.g. `fsqrt`, `lock cmpxchg`) or a call into a **StubRoutine** (hand-written assembly for complex cases like CRC32, AES/GHASH, `StringLatin1.indexOf`).
4. The surrounding code is then optimized *around* the intrinsic as one unit (e.g. loop unrolling over the inlined `sqrt`).

> The interpreter and C1 (client) generally do **not** intrinsify — they just call the real Java/native method. Intrinsics are principally a C2 (server compiler, tiered level 4) optimization. So they only appear after a method is hot enough to be compiled by C2.

## Catalog of Common Intrinsics

The set is JVM- and architecture-dependent, but the following are widely intrinsified in HotSpot on x64/aarch64:

| 区域 | 典型被 intrinsic 的方法 | 替换为 |
| --- | --- | --- |
| `java.lang.Math` | `sqrt`, `sin`, `cos`, `tan`, `abs`, `min`, `max`, `fma` | 对应 CPU 指令（`fsqrt`, `vfmadd...`） |
| `StringLatin1` / `StringUTF16` | `indexOf`, `equals`, `compareTo`, `getChars` | 向量化 / SSE/NEON 扫描 |
| `java.util.zip.CRC32(C)` | `update` | CRC 表驱动的汇编 StubRoutine |
| 加密 | AES (`com.sun.crypto`), `GHASH` | AES-NI / PCLMULQDQ 指令 |
| `sun.misc.Unsafe` / `VarHandle` | `compareAndSwapX`, `getAndAddX` | `lock cmpxchg` / `xadd` |
| `System` | `arraycopy` | 经 intrinsic 优化（有时委托 StubRoutine） |

> Do **not** rely on any specific method being intrinsified — it changes with JVM version, vendor, and CPU. The list above is illustrative, not contractual.

## @HotSpotIntrinsicCandidate

However, when using Hotspot JVM as of Java 9, the `@HotSpotIntrinsicCandidate` annotation is used on all methods that may be replaced.

```java
@HotSpotIntrinsicCandidate
public static double sqrt(double a) { return StrictMath.sqrt(a); }
```

Adding this annotation **doesn't automatically cause the method to be replaced** — that happens within the underlying JVM. Instead, JVM developers know that these methods are special and to be careful with them (e.g. a behavioral change could desync the intrinsic from its Java fallback).

## Intrinsics vs JNI / native

**What is the difference between Java intrinsic and native methods?**

- The [JIT](/docs/CS/Java/JDK/JVM/JIT.md) knows about intrinsics, so it can inline the relevant machine instruction into the code it's JITing, and optimize around it as part of a hot loop.
- A `JNI` function is a 100% black box for the compiler, with significant call/return overhead (especially if you use it for just a scalar).

## Diagnosing & Tuning

| Flag | 作用 |
| --- | --- |
| `-XX:+UnlockDiagnosticVMOptions -XX:+PrintIntrinsics` | 打印哪些方法被识别并替换为 intrinsic |
| `-XX:-UseMathIntrinsics` | 关闭 `Math.*` 的 intrinsic（退回 `StrictMath`） |
| `-XX:-UseStringIntrinsics` | 关闭 `String` 系列 intrinsic |
| `-XX:-UseAESIntrinsics` | 关闭 AES 硬件指令 intrinsic |
| `-XX:+UseSuperWord` | 控制向量化（superword）是否对字符串/数组 intrinsic 生效 |

Flags are best-effort: a disabled intrinsic silently falls back to the plain Java/native implementation — never a correctness bug, only a performance delta.

## Links

- [JNI](/docs/CS/Java/JDK/Basic/JNI.md)
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)

## References

1. [HotSpot Intrinsic Documentation (vmSymbols / LibraryCallKit)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/opto/library_call.cpp)
2. [JEP 280: Indify String Concatenation (uses invokedynamic, not classic intrinsics)](https://openjdk.org/jeps/280)
3. [Chapter: JVM intrinsics in "Pro Java 9 Performance"](https://www.apress.com/)
