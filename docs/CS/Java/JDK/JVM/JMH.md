## Introduction

One of the positive aspects of working with microbenchmarks is that it exposes the highly dynamic behavior and non-normal distributions that are produced by low-level subsystems. This, in turn, leads to a better understanding and mental models of the complexities of the JVM.

- Do not microbenchmark unless you know you are a known use case for it.
- If you must microbenchmark, use JMH.
- Discuss your results as publicly as you can, and in the company of your peers.
- Be prepared to be wrong a lot and to have your thinking challenged repeatedly.

## 版本基线

> [!NOTE]
> **版本口径**：JMH（Java Microbenchmark Harness）是 OpenJDK 官方微基准框架，当前版本 **1.37**。它随 OpenJDK 源码一起分发（`test/micro/`），因此**可用 `java -jar benchmarks.jar` 直接跑 JDK 自带的微基准**——这也是验证「本机性能基线是否正常」最快的途径。
>
> **JFR 与 JMH 是两回事**：[JFR](https://openjdk.org/jeps/328)（JEP 328，Release 11）是随 JDK 内置、面向**生产诊断**的飞行记录器，详见 [Tools/JFR](/docs/CS/Java/Tools/JFR.md)；JMH 面向**开发期严谨测量**，需要外部依赖（`jmh-core` + `jmh-annprocess`）。选错工具是常见误区，见下文「JFR vs JMH vs async-profiler」。

## 为什么手写计时不可信

微基准最大的陷阱是**你测的不是你以为的那个东西**。JIT 会在你没意识到的地方改写代码：

1. **预热（warm-up）** —— 方法先被解释执行，达到调用阈值后被 C1 编译，再被 C2 编译。冷态与热态是两回事。
2. **死代码消除（DCE）** —— 结果没人使用时，JIT 直接把整段计算删掉，你测出 0 ns。
3. **循环不外提** —— 与循环无关的表达式被提到循环外，循环体被优化成空壳。
4. **常量折叠与去虚拟化** —— 编译期可算的先算掉，`final` 类型的方法调用被静态绑定。
5. **逃逸分析 + 标量替换** —— 不逃逸的对象根本不分配，被拆成栈上局部变量，于是「分配开销」消失。
6. **内存模型下的重排序** —— 编译器与 CPU 都会重排，naive 循环可能测出被优化掉的假象。

JMH 的核心价值就是把上述因素**全部显式控制住**：强制预热迭代、Blackhole 消费结果防 DCE、独立 fork 进程、给出统计置信区间。

## 核心机制

### Benchmark 与注解

```java
import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.infra.Blackhole;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)          // 测单次耗时
@OutputTimeUnit(TimeUnit.NANOSECONDS)
@State(Scope.Benchmark)                     // 状态作用域
@Fork(2)                                   // fork 2 个独立 JVM 进程
@Warmup(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
public class MyBenchmark {

    @Param({"16", "256", "4096"})           // 参数化：展开成多组
    int size;

    int[] data;

    @Setup                                    // 每个 fork 前初始化
    public void setup() {
        data = new int[size];
        for (int i = 0; i < size; i++) data[i] = i;
    }

    @Benchmark
    public int sum() {
        int s = 0;
        for (int v : data) s += v;
        return s;                             // 返回值本身也防 DCE
    }
}
```

关键注解：

| 注解 | 作用 | 踩坑点 |
| :-- | :-- | :-- |
| `@Benchmark` | 标记被测方法 | 方法必须 **public** 且**不能有参数**（要用参数就放 `@State`） |
| `@State(Scope.Benchmark/Thread)` | 持有多线程基准的数据 | `Thread` 作用域每个线程一份副本，多线程基准要用它 |
| `@Setup` / `@TearDown` | 初始化 / 清理 | 别在被测逻辑里分配对象，准备工作挪到 Setup |
| `@Param` | 参数化扫描 | 生成多组结果，便于看清规模对性能的影响 |
| `@Fork(n)` | 用 n 个独立 JVM 跑 | **必须 ≥1**；`@Fork(0)` 结果不可信 |
| `@Warmup` / `@Measurement` | 预热与测量迭代数 | 预热不足是最常见的错误来源 |
| `@BenchmarkMode` | `Throughput`（ops/s）、`AverageTime`（ns/op）、`SampleTime`（分位数）、`SingleShotTime` | 测延迟分布用 `SampleTime` 而非 `AverageTime` |
| `Blackhole` | 消费结果防 DCE | 比单纯「返回个值」更严格，适合结果无意义的方法 |

### 为什么必须 fork

`@Fork(0)`（在当前 JVM 内跑）几乎总是错的：

- 当前 JVM 已被其它代码污染（已加载的类、C2 队列残留、堆中存活对象）；
- 无法隔离 JIT 状态，两个基准互相影响；
- 内存参数（`-Xmx` 等）不可控。

**每个 fork 是一个全新 JVM 进程**，这是可复现的前提。默认 `@Fork(1)`，正式结论用 2~5。

### Blackhole

```java
@Benchmark
public void consume(Blackhole bh) {
    bh.consume(compute());
}
```

`Blackhole` 把结果吃掉，让 JIT **无法证明计算无用**，因而不能删除。日志里的 `Blackhole mode: compiler (auto-detected)` 表示 JMH 自动选了最强的一种 blackhole 实现。返回值的写法也能防 DCE，但强度不如 `Blackhole`。

## 测量模式怎么选

| 模式 | 输出 | 适用 |
| :-- | :-- | :-- |
| `Throughput` | ops/time | 整体吞吐，如每秒处理多少请求 |
| `AverageTime` | time/op | 单次平均耗时 |
| `SampleTime` | 分位数分布 | **关心 P99/P999 延迟**（采样而非全量统计） |
| `SingleShotTime` | 一次调用耗时 | 冷启动类场景 |

调优时先用 `AverageTime` 找热点，验延迟看 `SampleTime`——**别用 `AverageTime` 推断尾延迟**。

## 常见反模式

```java
// ❌ 错误：循环里计时
long start = System.nanoTime();
for (int i = 0; i < N; i++) { work(); }
long cost = System.nanoTime() - start;
```

问题：预热不足、循环体可能被外提优化、结果可能被 DCE、`System.nanoTime()` 自身有开销、拿不到分布。这类代码常见结果是**一个被优化后的漂亮数字**，比稳态快好几倍。

其他反模式：

- **只报一个数字** —— 不给误差范围。应报 `avgt 3 101951.485 ±(99.9%) 343.733 ns/op`（含置信区间）。
- **不检查预热收敛** —— `-v EXTRA` 能看到逐次迭代值；若预热迭代明显慢于测量迭代，说明预热不足，结论不可用。
- **不记录 fork 数与 JVM 版本** —— 结论无法复现。
- **用 JMH 测端到端** —— JMH 测微基准，服务级压测要用别的方式。
- **在 Debug 模式或有 profiler 干扰下测** —— 结果无意义。

## JFR vs JMH vs async-profiler

三者常被混用，但目标完全不同：

| 工具 | 定位 | 何时用 |
| :-- | :-- | :-- |
| **JMH** | 开发期**严谨微基准** | 要为某个方法/数据结构定性能，需要可复现与误差范围 |
| **[JFR](/docs/CS/Java/Tools/JFR.md)** | JDK 内置**生产诊断**（JEP 328） | 线上偶发慢请求，要看 GC、锁竞争、IO、分配热点；开销约 1% |
| **async-profiler** | 第三方低开销 CPU 采样 | 精确定位 CPU 热点方法（火焰图），分钟级窗口 |
| **[Arthas](/docs/CS/Java/Tools/Arthas.md)** | 在线诊断与热更新 | 排查运行中进程、方法级耗时、实时改动 |

> [!TIP]
>
> 经验搭配：**JFR 常开做生产诊断**（成本极低），**async-profiler 做事后 CPU 归因**，**JMH 用于开发期定性能**。JFR 与 async-profiler 互补而非竞争：前者覆盖更广的事件面（GC / 锁 / IO），后者在 CPU 归因上更锐利。

## 跑起来

用官方 archetype 起项目（当前 archetype 版本 1.37）：

```bash
mvn archetype:generate -DinteractiveMode=false \
  -DarchetypeGroupId=org.openjdk.jmh -DarchetypeArtifactId=jmh-java-benchmark-archetype \
  -DarchetypeVersion=1.37 -DgroupId=com.example -DartifactId=jmh-benchmark
```

常用参数：

```bash
# 只跑某个基准
java -jar target/benchmarks.jar MyBenchmark.sum

# 缩短迭代（仅用于确认能跑通，正式测量别这么干）
java -jar target/benchmarks.jar -f 1 -wi 3 -i 3 -w 1s -r 1s

# 列出所有基准
java -jar target/benchmarks.jar -l

# 覆盖 @Param
java -jar target/benchmarks.jar -p size=1024
```

> [!WARNING]
> `@Fork(1) -wi 1 -i 1` 只能用来「确认能跑起来」，**绝不能作为性能结论**——预热与统计量都不足。

## 跑 JDK 自带的微基准

因为 JMH 随 OpenJDK 分发，装了 JDK 就能直接跑官方基准，无需任何外部依赖：

```bash
# 在 OpenJDK 源码的 build 目录下
java -jar test/micro/benchmarks.jar -l
java -jar test/micro/benchmarks.jar
```

官方基准的参数可用 `-p` 覆盖（如 `StringHashCode` 系列可扫描不同字符串长度）。跑它们有两个额外价值：**验证本机性能基线是否正常**（能发现硬件或虚拟化层面的问题），以及学习规范的测量方法。

## Links

- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)
- [ClassFile](/docs/CS/Java/JDK/JVM/ClassFile.md)
- [JFR](/docs/CS/Java/Tools/JFR.md)
- [Arthas](/docs/CS/Java/Tools/Arthas.md)
