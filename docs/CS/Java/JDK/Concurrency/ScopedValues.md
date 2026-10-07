## Introduction

ScopedValue 提供一种**安全、高效地在线程内及跨线程共享不可变数据**的方式，是 [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)
在「请求上下文」这类场景下的替代品。它在 JDK 20 中作为孵化 API 引入（JEP 429），JDK 21/22/23/24 中多轮预览改进
（JEP 446/464/481/487），最终在 **JDK 25 转正（JEP 506）**。在大量 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
并发的程序中，它的优势尤其明显。

## ThreadLocal Issues

ThreadLocal 能做到「每个线程一份变量」，但作为上下文传递手段有几个结构性缺陷：

- **可变且生命周期不受限**：`set()` 之后任何下游代码都能再次 `set`/`remove`；忘记 `remove()` 会在线程被池化复用时造成数据串号与内存泄漏。
- **可继承但代价高**：`InheritableThreadLocal` 只在「新建子线程」那一刻拷贝一份；虚拟线程是海量、短命的，逐线程复制上下文既浪费语义又不清晰。
- **写法上像可变全局变量**：数据从哪一层绑定、在哪一层失效，在调用链上不可见。

ScopedValue 的设计目标就是只保留 ThreadLocal 的「隐式上下文传递」用途，去掉其可变、无界、易泄漏的部分。

## Usage

ScopedValue 的值只在一个**有界的代码执行区间（scope）**内有效：通过 `where(...).run(...)`（或 `call(...)`）绑定，
Runnable 执行结束后绑定自动、不可恢复地撤销。

```java
// 声明：通常是 static final，自身只是一个 key，不持有状态
private static final ScopedValue<String> CURRENT_USER = ScopedValue.newInstance();

ScopedValue.where(CURRENT_USER, "alice")
           .run(() -> handleRequest());   // 在此调用区间内

void handleRequest() {
    String user = CURRENT_USER.get();      // 深层方法直接读取，无需层层透传参数
}
// run 返回后，CURRENT_USER 在当前线程上不再绑定，get() 会抛 NoSuchElementException
```

- 绑定后值**不可变**，下游只能 `get()`，不能改；
- 未绑定时调用 `get()` 抛异常，可用 `isBound()` 判断，或用 `orElse(...)`/`orElseThrow(...)` 提供缺省值；
- key 一般声明为 `static final`，真正的值不在 key 里，而在当前线程的绑定栈上。

## Inheritance

ScopedValue 的跨线程传播只在**结构化并发**（Structured Concurrency，JEP 505）显式 fork 子任务时发生：
父线程绑定的 ScopedValue 自动对子任务可见（只读继承），子任务无法把改动传回父线程。

```java
ScopedValue.where(CURRENT_USER, "alice").run(() -> {
    try (var scope = StructuredTaskScope.open()) {
        scope.fork(() -> { CURRENT_USER.get(); return "a"; }); // 读到 "alice"
        scope.fork(() -> { CURRENT_USER.get(); return "b"; }); // 同样读到 "alice"
        scope.join();
    }
});
```

这与虚拟线程模型契合：请求内 fork 出成千上万虚拟线程并发调用下游服务，它们共享同一份请求上下文（用户身份、trace id、租户），
却不需要每个线程复制存储；scope 结束，所有子任务结束，绑定整体失效。

## ThreadLocal vs ScopedValue

| 维度 | ThreadLocal | ScopedValue |
| --- | --- | --- |
| 可变性 | 可变，任意层可 `set` | 绑定后不可变，只能读 |
| 生命周期 | 显式 `remove`，否则随线程存活 | `run/call` 区间结束自动失效 |
| 在线程池中的安全性 | 复用线程易数据串号，必须清理 | 区间有界，天然不泄漏 |
| 子线程传播 | InheritableThreadLocal，创建时拷贝 | 结构化 fork 时只读继承 |
| 海量虚拟线程开销 | 每线程持有可变槽位，较重 | 绑定按帧保存，轻量、不可变、可优化 |
| 适用场景 | 确实需要 per-thread 可变状态（如遗留库） | 请求上下文、身份、trace、租户等一次性只读数据 |

## Links

- [ThreadLocal](/docs/CS/Java/JDK/Concurrency/ThreadLocal.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [JEP 506: Scoped Values](https://openjdk.org/jeps/506)
2. [JEP 446: Scoped Values (Preview)](https://openjdk.org/jeps/446)
3. [JEP 429: Scoped Values (Incubator)](https://openjdk.org/jeps/429)
4. [JEP 505: Structured Concurrency (Fifth Preview)](https://openjdk.org/jeps/505)
