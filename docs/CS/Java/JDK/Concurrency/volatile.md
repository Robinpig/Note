## Introduction

> JSR133
> In the original specification, accesses to volatile and non-volatile variables could be freely ordered.

volatile 变量是一种比锁定更轻量级的同步机制，因为它们不涉及上下文切换或线程调度。

只有在满足以下所有条件时，才能使用 volatile 变量：
- 对变量的写入不依赖于其当前值，或者可以确保只有一个线程更新该值；
- 该变量不参与与其他状态变量的不变量；
- 访问变量时不需要因任何其他原因而锁定。

## volatile analysis

put volatile value

```cpp
CASE(_putstatic):
        {
          // ... 
          if (cache->is_volatile()) {
            // ... 
          }
        }
```

volatile 的底层实现通过内存屏障（Memory Barrier）来保证可见性和有序性：
- 对 volatile 变量的写操作会在其后插入一个 StoreLoad 屏障
- 对 volatile 变量的读操作会在其前插入一个 LoadLoad 屏障

## Links

- [JDK Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)
