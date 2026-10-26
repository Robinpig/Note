## Introduction

> Define the skeleton of an algorithm in an operation, deferring some steps to subclasses. Template Method lets subclasses redefine certain steps of an algorithm without changing the algorithm's structure.
> —— GoF

模板方法模式在父类里固定算法骨架，把易变的步骤声明为抽象/钩子方法交给子类。与 [Strategy](/docs/CS/DesignPatterns/StrategyPattern.md)正好互补：**模板方法是"整体流程不变、替换其中几步"（继承，编译期绑定），策略是"整个算法可替换"（组合，运行期绑定）**。选它的信号是：一批处理流程共享同一骨架、只有个别步骤不同，且步骤数量会继续增加。

## The JDK's Textbook Case: AQS

`AbstractQueuedSynchronizer` 是整个 JDK 并发包里最重要的模板方法应用，它的类注释原文就是模式宣言：

> 子类必须定义用于改变该状态的 protected 方法，并由这些方法定义该状态在本对象被获取或释放方面的含义。有了这些方法，本类中的其他方法便可承担全部排队与阻塞机制。

- **固定骨架（父类，不许改）**：`acquire()` 的完整流程——先试 `tryAcquire`，失败则打包成 node 进入 CLH 等待队列，`LockSupport.park` 挂起，被唤醒后重新尝试，全程处理中断与取消；
- **可变步骤（子类，protected 钩子）**：`tryAcquire(int)`、`tryRelease(int)`、`tryAcquireShared(int)`、`tryReleaseShared(int)`、`isHeldExclusively()`；
- **收益**：`ReentrantLock`（独占语义，状态=重入次数）、`Semaphore`（共享语义，状态=许可数）、`CountDownLatch`、`ReentrantReadWriteLock` 各自只写几个小方法，队列、park/unpark、公平/非公平全部复用。详见 [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)。

这就是模板方法在大规模框架里的正确用法：**不变量集中在基类，可变点收敛成小接口**，新增同步器只需回答"什么算获取成功"。

## Other Classic Uses

- **Servlet 生命周期**：容器调用 `init → service → destroy`，业务只填 `doGet`/`doPost`——模板即 `HttpServlet.service()` 按 HTTP 方法分发；
- **JDBC `JdbcTemplate`**：`execute(Connection, callback)` 固定"取连接 → 回调 → 处理异常 → 归还连接"，业务只在 `StatementCallback` 里写 SQL，异常翻译与资源关闭永不出错。Spring 全家 `RedisTemplate`、`RestTemplate` 同构，见 [Spring 模板](/docs/CS/Framework/Spring/Data.md)；
- **`AbstractList.get(int)`**：迭代器、`indexOf`、`contains` 全部基于随机访问或顺序访问两个钩子推导；
- **Netty `ChannelInboundHandlerAdapter`**：`channelRead`、`exceptionCaught` 等钩子由用户填，pipeline 的传播顺序由基类固定，见 [ChannelHandler](/docs/CS/Framework/Netty/ChannelHandler.md)；
- **排序算法**：快排固定"选 pivot → 分区 → 递归"，分区方式可换（三数取中、Dutch flag），骨架不变。

## Hook Methods and the Trap

模板方法有两种扩展点，混用会出事：

- **抽象方法**：子类**必须**实现（`tryAcquire`）；
- **钩子方法（Hook）**：基类给空实现，子类**可选**覆写，且基类在固定位置调用它（如 `Collections.sort` 前后、`ThreadPoolExecutor.beforeExecute`）。

经典陷阱是**基类在构造器里调用可覆写方法**：此时子类字段尚未初始化，覆写方法读到的是默认值。`ThreadPoolExecutor` 的 `beforeExecute`/`afterExecute` 由执行线程调用而非构造器调用，正是为了绕开这个坑；`AbstractList` 的 `modCount` 在构造器里初始化而子类 modCount 逻辑只在方法期运行，同理。

另一个成本：**继承的静态绑定让"换一步"需要新建子类**。若同一批步骤要在运行时重组，就该改用策略/组合。经验法则——流程固定用模板，流程多变用策略；两者都大量出现的代码通常是抽象层次出了问题。

## Links

- [Design Patterns](/docs/CS/DesignPatterns/DesignPatterns.md)
- [Strategy](/docs/CS/DesignPatterns/StrategyPattern.md)
- [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md)
- [Java 并发](/docs/CS/Java/JDK/Concurrency/Concurrency.md)

## References

1. [Refactoring.Guru - Template Method](https://refactoring.guru/design-patterns/template-method)
2. [OODesign - Template Method Pattern](https://www.oodesign.com/template-method-pattern)
3. [JDK 17 AbstractQueuedSynchronizer 源码注释](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/concurrent/locks/AbstractQueuedSynchronizer.html)
