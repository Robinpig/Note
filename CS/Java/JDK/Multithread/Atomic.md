## 前言

为了研究Java对原子类的实现，从AtomicInteger类开始，分析Java如果对原子操作的实现。

## 什么是原子操作？

原子操作是指不会被线程调度机制打断的操作；这种操作一旦开始，就一直运行到结束，中间不会有任何上下文的切换。
注：原子操作可以是一个步骤，也可以是多个操作步骤，但是其顺序不可以被打乱，也不可以被切割只执行其中的一部分。

## 源码分析

首先从AtomicInteger类的属性聊起：

```
// setup to use Unsafe.compareAndSwapInt for updates
private static final Unsafe unsafe = Unsafe.getUnsafe();
private static final long valueOffset;
private volatile int value;
```

该类共有三个成员属性。

- unsafe：该类是JDK提供的可以对内存直接操作的工具类。
- valueOffset：该值保存着AtomicInteger基础数据的内存地址，方便unsafe直接对内存的操作。
- value：保存着AtomicInteger基础数据，使用volatile修饰，可以保证该值对内存可见，也是原子类实现的理论保障。

再谈静态代码块（初始化）

```
    try {
        valueOffset = unsafe.objectFieldOffset
            (AtomicInteger.class.getDeclaredField("value"));
    } catch (Exception ex) { throw new Error(ex); }
}
```

该过程实际上就是计算成员变量value的内存偏移地址，计算后，可以更直接的对内存进行操作。
了解核心方法compareAndSet(int expect,int update)：

```
public final boolean compareAndSet(int expect, int update) {
    return unsafe.compareAndSwapInt(this, valueOffset, expect, update);
}
```

在该方法中调用了unsafe提供的服务：

```
public final native boolean compareAndSwapInt(Object var1, long var2, int var4, int var5);
```

下面看看这个类在JDK中是如何实现的：

```
jboolean sun::misc::Unsafe::compareAndSwapInt (jobject obj, jlong offset,jint expect, jint update)  {  
  jint *addr = (jint *)((char *)obj + offset); //1
  return compareAndSwap (addr, expect, update);
}  

static inline bool compareAndSwap (volatile jlong *addr, jlong old, jlong new_val)    {    
  jboolean result = false;    
  spinlock lock;    //2
  if ((result = (*addr == old)))    //3
    *addr = new_val;    //4
  return result;  //5
}  
```

1. 通过对象地址和value的偏移量地址，来计算value的内存地址。
2. 使用自旋锁来处理并发问题。
3. 比较内存中的值与调用方法时调用方所期待的值。
4. 如果3中的比较符合预期，则重置内存中的值。
5. 如果成功置换则返回true，否则返回false；

综上所述：compareAndSet的实现依赖于两个条件：

- volatile原语：保证在操作内存的值时，该值的状态为最新的。（被volatile所修饰的变量在读取值时都会从变量的地址中读取，而不是从寄存器中读取，保证数据对所有线程都是可见的）
- Unsafe类：通过该类提供的功能，可以直接对内存进行操作。

了解常见操作getAndIncrement()：

```
    return unsafe.getAndAddInt(this, valueOffset, 1);
}
```

同样使用unsafe提供的方法：

```
public final int getAndAddInt(Object var1, long var2, int var4) {
    int var5;
    do {
        var5 = this.getIntVolatile(var1, var2);//1
    } while(!this.compareAndSwapInt(var1, var2, var5, var5 + var4));//2
    return var5;
}
 
//getIntVolatile方法native实现
jint sun::misc::Unsafe::getIntVolatile (jobject obj, jlong offset)    
{    
  volatile jint *addr = (jint *) ((char *) obj + offset);    //3
  jint result = *addr;    //4
  read_barrier ();    //5
  return result;    //6
}  
inline static void read_barrier(){
  __asm__ __volatile__("" : : : "memory");
}
```

1. 通过volatile方法获取当前内存中该对象的value值。
2. 计算value的内存地址。
3. 将值赋值给中间变量result。
4. 插入读屏障，保证该屏障之前的读操作后后续的操作可见。
5. 返回当前内存值
6. 通过compareAndSwapInt操作对value进行+1操作，如果再执行该操作过程中，内存数据发生变更，则执行失败，但循环操作直至成功。