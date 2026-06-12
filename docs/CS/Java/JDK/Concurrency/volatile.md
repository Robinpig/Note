## Introduction


> JSR133
> In the original specification, accesses to volatile and non-volatile variables could be freely ordered.


Volatile variables are a lighter-weight synchronization mechanism than locking because they do not involve context switches or thread scheduling.


You can use volatile variables only when all the following criteria are met:
- Writes to the variable do not depend on its current value, or you can ensure that only a single thread ever updates the value;
- The variable does not participate in invariants with other state variables; and
- Locking is not required for any other reason while the variable is being accessed.

 





## volatile analysis
 
put volatile value

```cpp
CASE(_putstatic):
        {
          // ... 
          if (cache->is_volatile()) {
            // ...
            OrderAccess::storeload();
          } else {
            // ...
          }
        }
```









```cpp
// x86
inline void OrderAccess::loadload()   { compiler_barrier(); }
inline void OrderAccess::storestore() { compiler_barrier(); }
inline void OrderAccess::loadstore()  { compiler_barrier(); }
inline void OrderAccess::storeload()  { fence();            }
```

当调用storeload屏障时，它会调用fence()方法

```cpp
inline void OrderAccess::fence() {
  // always use locked addl since mfence is sometimes expensive
#ifdef AMD64
  __asm__ volatile ("lock; addl $0,0(%%rsp)" : : : "cc", "memory");
#else
  __asm__ volatile ("lock; addl $0,0(%%esp)" : : : "cc", "memory");
#endif
  compiler_barrier();
}
```

LOCK指令前缀功能如下：

- 被修饰的汇编指令成为“原子的” 在汇编指令A（被LOCK指令前缀修饰的汇编指令）执行期间锁住所涉及到的Cache Line，此时其他CPU核不能存取其内缓存中对应的Cache Line
- 与被修饰的汇编指令一起提供内存屏障效果




为了保证能正确实现volatile的内存语义，JMM在采取了保守策略：在每个volatile写的后面，或者在每个volatile读的前面插入一个StoreLoad屏障。因为volatile写-读内存语义的常见使用模式是：一个写线程写volatile变量，多个读线程读同一个volatile变量。当读线程的数量大大超过写线程时，选择在volatile写之后插入StoreLoad屏障将带来可观的执行效率的提升。从这里可以看到JMM在实现上的一个特点：首先确保正确性，然后再去追求执行效率



## Links

- [Concurrency](/docs/CS/Java/JDK/Concurrency/Concurrency.md)


## References

1. [The "Double-Checked Locking is Broken" Declaration](https://www.cs.umd.edu/~pugh/java/memoryModel/DoubleCheckedLocking.html)
2. [关于汇编：在x86上，哪个更好的写障碍是：lock + addl或xchgl？](https://www.codenong.com/4232660/)
3. [汇编指令的LOCK指令前缀](https://dslztx.github.io/blog/2019/06/08/%E6%B1%87%E7%BC%96%E6%8C%87%E4%BB%A4%E7%9A%84LOCK%E6%8C%87%E4%BB%A4%E5%89%8D%E7%BC%80/)

