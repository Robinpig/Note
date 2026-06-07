## Introduction

用于执行低级不安全操作的方法集合。
尽管该类及其所有方法都是公共的，但此类的使用受到限制，因为只有受信任的代码才能获得它的实例。

**注意：** 调用者有责任确保在调用此类的任何方法之前检查参数。
虽然对输入执行了一些基本的检查，但这些检查是尽力而为的；当性能是最优先考虑的因素时，
就像此类方法被运行时编译器优化时一样，部分或全部检查（如果有的话）可能会被省略。
因此，调用者不得依赖检查及相应的异常！

```java
public class TestUnsafe {
    public static void main(String[] args) {
        Field f = null;
        try{
            f = Unsafe.class.getDeclaredField("theUnsafe");
            f.setAccessible(true);
            
        }catch (NoSuchFieldException | IllegalAccessException e){
            e.printStackTrace();
        }
        
    }
}
```

## Memory

Unsafe 类提供直接内存访问能力，包括分配、释放和操作堆外内存。

```java
// 分配内存
long address = unsafe.allocateMemory(size);
// 写入内存
unsafe.putInt(address, 123);
// 读取内存
int value = unsafe.getInt(address);
// 释放内存
unsafe.freeMemory(address);
```

### CAS

Compare-And-Swap 操作，提供硬件级别的原子操作。

```java
public final native boolean compareAndSwapObject(Object o, long offset, Object expected, Object x);
public final native boolean compareAndSwapInt(Object o, long offset, int expected, int x);
public final native boolean compareAndSwapLong(Object o, long offset, long expected, long x);
```

### Park/Unpark

线程阻塞和唤醒机制。

```java
// 阻塞当前线程
unsafe.park(false, 0L);
// 唤醒指定线程
unsafe.unpark(thread);
```

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
