## Introduction

注意：JVM 使用了两个非常相似的结构：
1. ParkEvent 用于 Java 级别的"monitor"同步。
2. Parker 用于 JSR166-JUC park-unpark。

> [!NOTE]
> 
> In the future we'll want to think about eliminating Parker and using ParkEvent instead.
> There's considerable duplication between the two services.

## Parker

JSR166 的每线程阻塞支持。
有关原理，请参阅 Java 级别的文档。基本上，`park` 类似于 `wait`，`unpark` 类似于 `notify`。

Parker 本质上是其关联 JavaThread 的一部分，并且仅在保证 JavaThread 存活时才能访问（例如，通过在当前线程上操作，或通过 ThreadsListHandle 保护线程）。

Class Parker 在共享代码中声明，并扩展了平台特定的 os::PlatformParker 类，该类包含实际的实现机制（condvars/events 等）。
park() 和 unpark() 的实现也在平台特定的 os_<os>.cpp 文件中。

```cpp
// share/runtime/park.hpp
class Parker : public os::PlatformParker {
 private:
  NONCOPYABLE(Parker);
 public:
  // ...
};
```

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
