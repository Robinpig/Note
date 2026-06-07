## Introduction

一种基于能力的锁，具有三种模式用于控制读/写访问。
**StampedLock 的状态由版本和模式组成**。
锁获取方法返回一个 stamp，表示和控制对锁状态的访问；
这些方法的"try"版本可能返回特殊值零来表示获取访问失败。
锁释放和转换方法需要 stamp 作为参数，如果与锁状态不匹配则失败。

三种模式：

Writing。writeLock 方法可能阻塞等待独占访问，返回一个 stamp，可在 unlockWrite 方法中用于释放锁。
还提供了 untimed 和 timed 版本的 tryWriteLock。
当锁处于写模式时，无法获得读锁，并且所有乐观读验证都将失败。

Reading。readLock 方法可能阻塞等待非独占访问，返回一个 stamp，可在 unlockRead 方法中用于释放锁。
还提供了 untimed 和 timed 版本的 tryReadLock。

Optimistic Reading。tryOptimisticRead 方法仅在锁当前未处于写模式时返回非零 stamp。
如果自获得给定 stamp 以来未在写模式下获取锁，则 validate 方法返回 true。
此模式可以被视为读锁的极弱版本，随时可能被写者打破。
对短只读代码段使用乐观模式通常可以减少争用并提高吞吐量。
然而，其使用本质上是不稳定的。乐观读段应仅读取字段并将其保存在局部变量中以供后续验证后使用。
在乐观模式下读取的字段可能严重不一致，因此仅当你足够熟悉数据表示以检查一致性和/或重复调用 `validate()` 方法时才能使用。

此类还支持在三种模式之间有条件地转换的方法。
例如，tryConvertToWriteLock 尝试"升级"模式，如果以下条件之一成立，则返回有效的写 stamp：

1. 已在写模式
2. 在读模式且没有其他读者
3. 持有乐观读 stamp 且锁当前可用

```java
public class StampedLock implements java.io.Serializable {
    // ...
}
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
