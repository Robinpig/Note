## Overview
The JVM interprets and executes bytecode at runtime. In addition, it makes use of the just-in-time (JIT) compilation to boost performance.

In earlier versions of Java, we had to manually choose between the two types of JIT compilers available in the Hotspot JVM. One is optimized for faster application start-up, while the other achieves better overall performance. Java 7 introduced tiered compilation in order to achieve the best of both worlds.

A JIT compiler compiles bytecode to native code for frequently executed sections. These sections are called hotspots, hence the name Hotspot JVM. As a result, Java can run with similar performance to a fully compiled language. Let's look at the two types of JIT compilers available in the JVM.

C1 – Client Compiler

The client compiler, also called C1, is a type of a JIT compiler optimized for faster start-up time. It tries to optimize and compile the code as soon as possible.

Historically, we used C1 for short-lived applications and applications where start-up time was an important non-functional requirement. Prior to Java 8, we had to specify the -client flag to use the C1 compiler. However, if we use Java 8 or higher, this flag will have no effect.

C2 – Server Compiler

The server compiler, also called C2, is a type of a JIT compiler optimized for better overall performance. C2 observes and analyzes the code over a longer period of time compared to C1. This allows C2 to make better optimizations in the compiled code.

Historically, we used C2 for long-running server-side applications. Prior to Java 8, we had to specify the -server flag to use the C2 compiler. However, this flag will have no effect in Java 8 or higher.

We should note that the Graal JIT compiler is also available since Java 10, as an alternative to C2. Unlike C2, Graal can run in both just-in-time and ahead-of-time compilation modes to produce


### Tiered Compilation
The C2 compiler often takes more time and consumes more memory to compile the same methods. However, it generates better-optimized native code than that produced by C1.

The tiered compilation concept was first introduced in Java 7. Its goal was to use a mix of C1 and C2 compilers in order to achieve both fast startup and good long-term performance.

Tiered compilation is enabled by default since Java 8.

**JVM doesn't use the generic CompileThreshold parameter when tiered compilation is enabled.**

final并没有提升

### code cache

Since Java 9, the JVM segments the code cache into three areas:

The non-method segment – JVM internal related code (around 5 MB, configurable via -XX:NonNMethodCodeHeapSize)
The profiled-code segment – C1 compiled code with potentially short lifetimes (around 122 MB by default, configurable via -XX:ProfiledCodeHeapSize)
The non-profiled segment – C2 compiled code with potentially long lifetimes (similarly 122 MB by default, configurable via -XX:NonProfiledCodeHeapSize)
Segmented code cache helps to improve code locality and reduces memory fragmentation. Thus, it improves overall performance.

### Deoptimization
Even though C2 compiled code is highly optimized and long-lived, it can be deoptimized. As a result, the JVM would temporarily roll back to interpretation.

Deoptimization happens when the compiler’s optimistic assumptions are proven wrong — for example, when profile information does not match method behavior:

jstat  -compiler process_id 编译信息

### Compilation Levels
Even though the JVM works with only one interpreter and two JIT compilers, there are five possible levels of compilation. The reason behind this is that the C1 compiler can operate on three different levels. The difference between those three levels is in the amount of profiling done.

- level 0 - interpreter
- level 1 - C1 with full optimization (no profiling)
- level 2 - C1 with invocation and backedge counters
- level 3 - C1 with full profiling (level 2 + MDO)
- level 4 - C2

The most common scenario in JIT compilation is that the interpreted code jumps directly from level 0 to level 3.

### Compilation Logs
By default, JIT compilation logs are disabled. To enable them, we can set the `-XX:+PrintCompilation` flag. The compilation logs are formatted as:

Timestamp – In milliseconds since application start-up
Compile ID – Incremental ID for each compiled method
Attributes – The state of the compilation with five possible values:
% – On-stack replacement occurred
s – The method is synchronized
! – The method contains an exception handler
b – Compilation occurred in blocking mode
n – Compilation transformed a wrapper to a native method
Compilation level – Between 0 and 4
Method name
Bytecode size
Deoptimisation indicator – With two possible values:
Made not entrant – Standard C1 deoptimization or the compiler’s optimistic assumptions proven wrong
Made zombie – A cleanup mechanism for the garbage collector to free space from the code cache

Tier3CompileThreshold
Tier4CompileThreshold

compile Threads



inline



EscapeAnalysis


## References
1. [Tiered Compilation in JVM](https://www.baeldung.com/jvm-tiered-compilation)
2. [Compilation Optimization - Java Platform, Standard Edition JRockit to HotSpot Migration Guide](https://docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm#JRHMG117)
