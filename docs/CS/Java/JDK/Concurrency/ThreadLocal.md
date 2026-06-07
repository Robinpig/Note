## Introduction

此类提供线程局部变量。
这些变量与其正常对应物的不同之处在于，每个访问一个变量的线程（通过其 get 或 set 方法）都有其自己的、独立初始化的变量副本。
**ThreadLocal 实例通常是希望将状态与[线程](/docs/CS/Java/JDK/Concurrency/Thread.md)关联的类中的私有静态字段（例如，用户 ID 或事务 ID）**。

每个线程持有对其线程局部变量副本的隐式引用，只要线程存活且 ThreadLocal 实例可访问；
**线程消失后，其所有线程局部实例的副本都将被垃圾回收（除非存在对这些副本的其他引用）**。

> Don't Cache Expensive Reusable Objects in Thread-Local Variables

## ThreadLocal

与 HashMap 不同的是，Entry 的 key 就是 ThreadLocal 对象本身，value 就是用户具体需要存储的值
当调用 ThreadLocal.set() 添加 Entry 对象时，是如何解决 Hash 冲突的呢？这就需要我们了解线性探测法的实现原理
每个 ThreadLocal 在初始化时都会有一个 Hash 值为 threadLocalHashCode，每增加一个 ThreadLocal， Hash 值就会固定增加一个魔术 HASH_INCREMENT = 0x61c88647
为什么取 0x61c88647 这个魔数呢？
实验证明，通过 0x61c88647 累加生成的 threadLocalHashCode 与 2 的幂取模，得到的结果可以较为均匀地分布在长度为 2 的幂大小的数组中

虽然 Entry 的 key 设计成了弱引用，但是当 ThreadLocal 不再使用被 GC 回收后，ThreadLocalMap 中可能出现 Entry 的 key 为 NULL，那么 Entry 的 value 一直会强引用数据而得不到释放，只能等待线程销毁

### Create ThreadLocal withInitial

```java
ThreadLocal<SimpleDateFormat> dateFormat = ThreadLocal.withInitial(
    () -> new SimpleDateFormat("yyyy-MM-dd"));
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
