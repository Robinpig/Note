## Introduction

[Project Valhalla](https://openjdk.org/projects/valhalla/) plans to augment the Java object model with **value objects** and **user-defined primitives**, combining the abstractions of object-oriented programming with the performance characteristics of simple primitives. These features are complemented with changes to Java's generics to preserve performance gains through generic APIs.

The anticipated Valhalla features will **not be delivered all at once**, but through a steady stream of enhancements across multiple JDK releases. There are **five distinct feature sets** under development:

1. **Value Classes and Objects** — objects without identity, optimized encodings
2. **Null Checking** — compile- and run-time null flow management
3. **Array Enhancements** — immutability, safe initialization, primitive/reference interop
4. **Unifying Primitives and Classes** — better boxing for invocations & generics
5. **Parametric JVM** — runtime specialization of generic parameterizations

> ⚠️ **版本状态（截至 JDK 25）**：Valhalla 的核心 **Value Classes（JEP 401）在 JDK 25 仍是预览（preview），尚未 GA**，不是标准 JDK 25 特性。已交付的相关子项见下方「已交付的 Valhalla 衍生 JEP」。

## Delivered Valhalla-derived JEPs

| JEP | 特性 | 交付版本 | 状态 |
| --- | --- | --- | --- |
| **JEP 371** | **Hidden Classes** | JDK 15 | **已 GA（已独立）** |
| JEP 390 | Warnings for Value-based Classes | JDK 16 | 已 GA |
| JEP 334 | JVM Constants API | JDK 12 | 已 GA |
| JEP 309 | Dynamic Class-File Constants | JDK 11 | 已 GA |
| JEP 181 | Nest-Based Access Control | JDK 11 | 已 GA |
| JEP 401 | Value Classes and Objects | — | **JDK 25 仍为预览** |

> 注意：本页旧版把 **Hidden Classes** 当作 Valhalla 主体内容，实际它已于 JDK 15 作为独立特性交付，只是起源于 Valhalla 早期探索。其机制（`Lookup.defineHiddenClass` 不经 `ClassLoader` 定义类，常用于 Lambda/动态代理/字节码增强框架）保留如下。

### Hidden Classes (JEP 371, JDK 15)

Creates a hidden class or interface from bytes, returning a `Lookup` on the newly created class. Unlike ordinary classes defined by a class loader, a hidden class has **no initiating loader recorded**, cannot be discovered by name, and is not observable via `Class::forName`. It is definitionally tied to the lookup class's package/module/protection domain.

```java
public Lookup defineHiddenClass(byte[] bytes, boolean initialize, ClassOption... options)
                throws IllegalAccessException
{
    // ...
    return makeHiddenClassDefiner(bytes.clone(), Set.of(options), false)
        .defineClassAsLookup(initialize);
}
```

`Class.getName()` returns `N + "/" + <suffix>` (not a valid binary name); `describeConstable()` returns empty because it cannot be named nominally. This is exactly how `LambdaMetafactory` and many bytecode frameworks inject anonymous adapters at runtime.

## Value Classes (JEP 401, Preview)

A **value class** is declared with the `value` modifier:

```java
value class Point(int x, int y) { }
```

Key properties:

- **No identity** — cannot be `synchronized` on, `==` compares **structurally** (field-wise) rather than by reference, `System.identityHashCode` is meaningless.
- **All fields final** and the class is implicitly final / non-nullable (null-restricted variants are a follow-on preview).
- The JVM is **allowed to flatten** instances directly into containing objects, arrays, and stack frames — no header, no indirection, no per-instance heap allocation.

## Performance: Flattening & Scalarization

The entire reason Valhalla exists is memory layout. A `value record Point(int x, int y)` inside a `Point[1_000_000]`:

- **Before**：a million 24-byte heap allocations + a million pointer hops = fragmented, GC-heavy.
- **After flattening**：8 MB of contiguous `int`s — no headers, better cache locality, near-zero GC pressure.

`scalarization` goes further: during JIT compilation, value objects can be passed in **registers / on the stack** as scalar components, avoiding allocation entirely in hot paths. Immutable data carriers (DTOs, coordinates, `java.time` types) benefit most; I/O-bound services see little change.

## Value-based Classes (JEP 390, JDK 16)

As migration groundwork, classes like `Optional`, `LocalDate`, `LocalDateTime`, `Duration` are declared **value-based** — they may become value classes in future, so you must not rely on identity (`==`, `synchronized`, `hashCode` stability). The compiler emits warnings when you do. This is the bridge that lets the JDK later flip candidates to `value` without source-level breakage.

## Relationship with Generics (Parametric JVM)

Today generics are reference-only (type erasure). The long-term Valhalla goal is a **Parametric JVM** that specializes `List<int>` / `List<Point>` at runtime, eliminating boxing. This is the least mature of the five sets and has **no preview yet** — do not assume primitive generics are available in any shipped JDK.

## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)
- [ClassFile](/docs/CS/Java/JDK/JVM/ClassFile.md)
- [Object Header](/docs/CS/Java/JDK/JVM/Object_Header.md)
- [Lambda](/docs/CS/Java/JDK/Basic/Lambda.md)

## References

1. [Project Valhalla](https://openjdk.org/projects/valhalla/)
2. [JEP 401: Value Classes and Objects (Preview)](https://openjdk.org/jeps/401)
3. [JEP 371: Hidden Classes](https://openjdk.org/jeps/371)
4. [JEP 390: Warnings for Value-based Classes](https://openjdk.org/jeps/390)
5. [The State of Valhalla (design note)](https://openjdk.org/projects/valhalla/)
