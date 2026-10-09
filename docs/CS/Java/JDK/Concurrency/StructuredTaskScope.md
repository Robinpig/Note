## Introduction

[VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md) 让「一个请求一个线程」重新变得可行，于是写出一个几万个线程的
并发程序不再昂贵。但它同时放大了非结构化并发的老问题：`ExecutorService` 提交出去的任务与创建它的方法之间**没有任何生命周期约束**，
子任务可能在父方法早已返回后继续跑，没人能引用它，也没人能取消它。这类问题在线程数量少时是偶发 bug，在虚拟线程下变成每天都在发生的线上事故。

Structured Concurrency 就是 JDK 对这个问题的语言级答案：把一组并发的子任务当作**单个工作单元**对待——所有 fork 出去的子任务，
要么在作用域退出前完成，要么被取消，绝不泄漏。它属于 Project Loom 的三件套之一（另两件是虚拟线程与
[ScopedValue](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)），三者是配套设计的。

需要先说清状态：**截至 JDK 25，Structured Concurrency 仍是预览特性**，第五次预览，对应 **JEP 505**。它的演进历史相当长，
每一轮预览都改了 API，因此网上大量文章里的代码在当前版本编译不过：

| 版本 | JEP | 阶段 | 关键变化 |
| --- | --- | --- | --- |
| 19 | 428 | Incubator（孵化模块） | `StructuredTaskScope` 首次出现 |
| 20 | 437 | 第二轮孵化 | 仍在 `jdk.incubator.concurrent` |
| 21 | 453 | 转为预览 | 移入 `java.util.concurrent`；`fork` 返回 `Subtask` 而非 `Future` |
| 22 / 23 / 24 | 462 / 480 / 499 | 第二～四次预览 | 延续 `Subtask` 形态 |
| 25 | **505** | 第五次预览 | **公开构造器改为静态工厂方法**，引入 `Joiner` 与 `Configuration` |
| 26 / 27 | 525 / 533 | 第六～七次预览 | 小幅调整 |
| — | 543 | 计划在 JDK 28 转正 | 目标是不再改动 |

使用需要 `--enable-preview`。本篇以 **JDK 25（tag `jdk-25+36`）** 源码为准。

## Unstructured Concurrency

先看清问题。假设一个请求要并行取两份数据：用 `ExecutorService` 写出来是这样的。

```java
Response handle() throws ExecutionException, InterruptedException {
    Future<User> user = executor.submit(() -> findUser());
    Future<List<Order>> orders = executor.submit(() -> fetchOrder());

    String theUser = user.get();   // 若这里抛异常……
    int count = orders.get().size();
    return new Response(theUser, count);
}
```

这段代码在四个点上不可靠，而且**没有一处是编译器或 API 强制你处理的**：

1. **线程泄漏**。`findUser()` 抛异常后 `handle()` 抛出，但 `fetchOrder()` 仍在自己的线程上跑到底。最坏情况下它会写库、发消息，
   干扰其它请求——这已经是一个真实的线上故障模式。
2. **中断不传播**。执行 `handle()` 的线程被中断时，两个子任务线程都不会被取消，继续泄漏。
3. **无谓等待**。`findUser()` 很慢而 `orders` 先失败了，`handle()` 仍然阻塞在 `user.get()` 上傻等，而不是取消掉慢的那个。
4. **可观测性缺失**。`handle()` 返回后，追踪请求生命周期的工具看到的是「两个还活着的线程」，无法知道它们属于哪个请求。

用非结构化并发修好这些，需要在**每一个**并发调用点手写「跟踪所有 future + 任一失败就取消其余 + 中断时级联取消 + 兜底 finally 清理」。
代码量翻倍且极易漏写，而漏写的那一处不会报错，只会在生产环境里安静地泄漏。

## Scope Lifecycle

Structured Concurrency 的解法是把并发子任务关进一个**词法作用域**，作用域的生命周期就是父任务的生命周期。
核心类 `StructuredTaskScope<T, R>` 在 JDK 25 是个 `sealed interface extends AutoCloseable`（只允许 `StructuredTaskScopeImpl` 实现），
配合 try-with-resources 使用：

```java
Response handle() throws InterruptedException {
    try (var scope = StructuredTaskScope.open()) {
        var user = scope.fork(() -> findUser());    // 立即返回 Subtask，不阻塞
        var order = scope.fork(() -> fetchOrder());

        scope.join();                               // 等待并决定成败

        // 只有走到这里，两个子任务都才成功结束
        return new Response(user.get(), order.get());
    }
    // 离开 try 块时 close() 兜底：任何异常路径下都不会有子任务残留
}
```

对照上面四个问题：子任务失败时 scope 被取消、`fetchOrder()` 的线程被中断（问题 1、2）；`orders` 失败则 `join()` 立刻抛，
不等 `findUser`（问题 3）；线程全部在 `join()` 处汇合，生命周期与 `handle()` 一致（问题 4）。

这个保证的关键字是「**全部**」：作用域退出时，每一个 fork 出去的子任务都**已经完成或已被取消**，
写法上等价于「方法的局部变量不可能比方法活得更久」。

### Ownership

作用域有明确的**所有者线程**（owner），即调用 `open()` 的线程。JDK 25 用三种不同的异常区分越界调用，
这个设计比早期预览的单一大异常精确得多：

| 异常 | 触发条件 |
| --- | --- |
| `WrongThreadException` | 非 owner 线程调用了 `fork` / `join` / `close` |
| `IllegalStateException` | 已 `join` 之后又 `fork`，或作用域已 `close` |
| `StructureViolationException` | 当前 `ScopedValue` 绑定与创建作用域时捕获的不一致；或 `close` 时仍有未关闭的嵌套作用域 |

`join()` 还额外要求**只能调用一次**（重复调用抛 `IllegalStateException`）。这条约束保证了「join 点」在每个作用域里是一个
可静态推断的位置，也让实现不必支持多次合并等待。

### Fork

`fork` 有两个重载，都**立即返回**而不等待：

```java
<U extends T> Subtask<U> fork(Callable<? extends U> task);
<U extends T> Subtask<U> fork(Runnable task);   // Subtask.get() 成功时返回 null
```

JDK 25 的 `fork` 有一段容易忽略的短路逻辑，按源码顺序是：先建一个处于 `UNAVAILABLE` 状态的 `Subtask` 对象 → 调 joiner 的
`onFork` → 若 `onFork` 抛异常则向上传播且**不创建线程** → 若作用域已被取消，或 `onFork` 返回 `true`，则**直接返回 `UNAVAILABLE`
状态的 Subtask，不创建线程**。只有真正创建线程并启动，绑定才被继承进去。

「作用域取消后再 fork 不起线程」这一点很重要：它保证了取消之后仍然可以安全地继续 fork 一批任务拿到空壳对象，
而这些对象的状态是 `UNAVAILABLE`，`get()` 不允许调用——不会误用。

### Subtask

`Subtask<T>` 是 `sealed interface extends Supplier<T>`，代表一个被 fork 的子任务，状态机只有三个值：

| State | 含义 |
| --- | --- |
| `UNAVAILABLE` | 结果不可得：已 fork 未完成、取消后才完成、或 fork 时作用域已取消（根本没起线程） |
| `SUCCESS` | 成功完成，终态，可 `get()` |
| `FAILED` | 抛异常终止，终态，可 `exception()` |

`get()` / `exception()` 有严格的双重前置条件：**必须是 owner 线程、且必须已 `join()` 之后**。违反时抛 `IllegalStateException`。
作用域在取消前就完成或失败的子任务，两个方法都不能用来取结果。这个设计堵死了「结果还在但值取不到」的竞态误用。

## Joiner

JEP 505 最大的 API 变化是把「等待策略」从类继承体系搬到了 `Joiner` 接口 + 静态工厂方法上。
JDK 21～24 的 `StructuredTaskScope`（默认）/`ShutdownOnFailure` / `ShutdownOnSuccess` 三个类**在 JDK 25 里已被完全移除**——
我在源码目录里按名字找过，`ShutdownOnFailure.java` 已不存在，只剩 `StructuredTaskScope.java`。

JDK 25 提供五个 `Joiner` 工厂方法，覆盖了绝大多数场景：

| 工厂方法 | `join()` 返回 | 取消时机 | 典型用途 |
| --- | --- | --- | --- |
| `awaitAllSuccessfulOrThrow()` | `null` | 任一子任务失败即取消 | **默认**；子任务类型不一致时取结果 |
| `allSuccessfulOrThrow()` | `Stream<Subtask<T>>` | 任一子任务失败即取消 | 子任务类型一致，想拿到结果流 |
| `anySuccessfulResultOrThrow()` | 第一个成功的子任务结果 | 全部失败才取消 | 冗余查询/竞速 |
| `awaitAll()` | `null` | **不取消，也不抛** | 尽力而为的清理类任务 |
| `allUntil(Predicate)` | `Stream<Subtask<T>>` | 谓词命中即取消 | 自定义策略的积木 |

无参的 `open()` 就是最常用的那一种的语法糖，源码写得很直白：

```java
static <T> StructuredTaskScope<T, Void> open() {
    return open(Joiner.awaitAllSuccessfulOrThrow(), Function.identity());
}
```

几个容易踩的语义差异：

- **`awaitAllSuccessfulOrThrow()` 与 `allSuccessfulOrThrow()` 只差返回值**，前者 `Void`、后者 `Stream<Subtask<T>>`。
  官方 `@apiNote` 明确建议：子任务返回**不同类型**时用前者（从各自的 `Subtask` 取），**同一类型**时用后者（直接拿流做归约）。
- **`anySuccessfulResultOrThrow()` 在一个子任务都没 fork 时抛 `NoSuchElementException`**（`result()` 里取的迭代器没有元素），
  而不是返回 null。
- **`awaitAll()` 刻意不传播异常**，`result()` 直接 `return null`。它的 javadoc 里给了一个 `accept()` 循环的例子，
  用于「尽力关闭所有已接受的连接」这类清理场景——不因为某个连接失败就放弃其余的。

`allUntil` 是唯一暴露策略原语的入口，它返回一个 `Joiner<T, Stream<Subtask<T>>>`，谓词在每个子任务完成时被求值，返回 `true` 就取消作用域。
想实现「拿到前 N 个结果就停」这类策略，应当基于它而不是直接实现 `Joiner` 接口——源码的 `@apiNote` 特别强调
「Joiner 应尽量通用，**不该在实现里放业务逻辑**」，因为 `join()` 返回值的使用方式是调用点决定的。

真要实现 `Joiner` 接口，只有三个方法：

```java
interface Joiner<T, R> {
    default boolean onFork(Subtask<? extends T> subtask)   { return false; }
    default boolean onComplete(Subtask<? extends T> subtask) { return false; }
    R result();                                            // 唯一必须实现的方法
}
```

返回 `boolean` 的含义是「是否取消作用域」。`onComplete` 会被**多个线程并发调用**，所以自定义 `Joiner` 必须线程安全，
通常要靠 `ConcurrentLinkedQueue` 这类并发结构收集结果。Javadoc 有一条容易被忽略的硬性要求：
**每个作用域必须新建一个 `Joiner` 对象，绝不能在多个作用域间共享或在关闭后复用**。

## Configuration

JDK 25 新增了 `Configuration`，用函数式方式配置作用域，默认值是「每个子任务一个匿名虚拟线程 + 无超时」。

```java
static <T, R> StructuredTaskScope<T, R> open(Joiner<? super T, ? extends R> joiner,
                                             Function<Configuration, Configuration> configFunction);
```

`Configuration` 是个 `sealed interface`，三个不可变方法，各自返回新对象：

| 方法 | 作用 |
| --- | --- |
| `withThreadFactory(ThreadFactory)` | 指定创建子任务线程的工厂；不设则用匿名虚拟线程 |
| `withName(String)` | 给作用域起名，便于监控与排查 |
| `withTimeout(Duration)` | **从作用域打开时就开始计时**的全局超时 |

超时的语义有个细节容易误解：`withTimeout` 设的是**整个作用域的预算**，不是单个子任务的。超时在 `join()` 之前或等待期间到期，
作用域被取消，`join()` 抛 `TimeoutException`。也就是说「每个子任务 100ms 超时、5 个子任务」的语义要用两次 `open` 嵌套才能表达。

`withTimeout` 是 JDK 24 才加进 `Configuration` 的（JEP 503 同期）。更细的超时控制要放到每个 `fork` 的任务体里自己用
`Future.get(timeout)` 或 `StructuredTaskScope` 的嵌套作用域处理。

## Close

`close()` 是这套结构化保证的落地点，行为契约在 javadoc 里写得很密：

- 尚未取消则取消，**中断**执行未完成子任务的线程；
- 然后**等待所有线程结束**；等待期间若被中断，**不提前放弃**——继续等到线程真正结束，退出时把中断状态置回；
- 只能由 owner 调用；已关闭时重复调用无效果（幂等）；
- 若在嵌套作用域还没关时就关外层，会**按创建的逆序**依次关闭底层构造，关完本作用域后抛 `StructureViolationException`；
- 若在线程终止时仍有未关闭的作用域，线程终止会触发这些作用域的关闭（同样逆序），这可能**延迟线程终止**。

最容易被忽略的一条：**fork 之后没有尝试 `join()` 就 `close()` 会抛 `IllegalStateException`**（注意是在关闭完成之后才抛）。
这条看似烦人的约束恰恰是结构化纪律的强制点——它把「我 fork 了但忘了管它」从一个安静的泄漏变成一个响亮的异常。

## Cancellation

取消是「**中断**」，不是「杀死线程」。`close()` 与超时都通过 `Thread.interrupt()` 通知子任务，
子任务需要自己响应中断（检查 `Thread.interrupted()`、让阻塞调用抛 `InterruptedException`）。
JEP 543（计划在 JDK 28 转正的版本）明确把「替换掉现有线程中断机制」列为非目标——
所以任务不能假设取消会立即停止，正在执行的不可中断计算会继续跑完。

`Subtask.State` 里 `UNAVAILABLE` 覆盖的三种情形（取消后才完成、取消后才 fork）也是这个语义的直接结果：
被取消的子任务没有可靠的终态可取。

## Preview Status

预览特性的实际影响，写代码前要认清：

- 编译与运行都需要 `--enable-preview`，且编译时的 flag 必须与运行时一致；
- **API 在每次预览轮次都可能变**。历史教训具体到代码：`fork` 的返回类型从 `Future` 改成 `Subtask`（JDK 21），
  三个策略类被 `Joiner` 取代、构造器改成工厂方法（JDK 25）。依赖当前 API 的生产代码在升级时要改；
- 预览 API **不保证向后兼容**，也不适合作为对外暴露的库 API。

尽管形态反复，API 的**演化方向是清晰的**：`Joiner` 从类继承变成接口 + 组合，`Configuration` 从构造器参数变成不可变 builder，
`Subtask` 状态机显式化。每一轮都在往「组合优于继承、状态可枚举」的方向收紧。

## Links

- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
- [ScopedValues](/docs/CS/Java/JDK/Concurrency/ScopedValues.md)
- [CompletableFuture](/docs/CS/Java/JDK/Concurrency/Future.md)
- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [JEP 505: Structured Concurrency (Fifth Preview)](https://openjdk.org/jeps/505)
2. [JEP 543: Structured Concurrency](https://openjdk.org/jeps/543)
3. [JEP 453: Structured Concurrency (Preview)](https://openjdk.org/jeps/453)
4. [StructuredTaskScope (Java 25 API)](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/concurrent/StructuredTaskScope.html)