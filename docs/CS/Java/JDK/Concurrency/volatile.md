## Introduction



注意：当且仅当满足以下所有条件时，才应该用volatile变量

- 对变量的写入操作不依赖变量的当前值，或者你能确保只有单个线程更新变量的值。
- 该变量不会与其他的状态一起纳入不变性条件中。
- 在访问变量时不需要加锁。

### 术语定义

| 术语       | 英文单词               | 描述                                                         |
| ---------- | ---------------------- | ------------------------------------------------------------ |
| 共享变量   | Share Variables        | 在多个线程之间能够被共享的变量被称为共享变量。共享变量包括所有的实例变量，静态变量和数组元素。他们都被存放在堆内存中，Volatile 只作用于共享变量。 |
| 内存屏障   | Memory Barriers        | 是一组处理器指令，用于实现对内存操作的顺序限制。             |
| 缓冲行     | Cache line             | 缓存中可以分配的最小存储单位。处理器填写缓存线时会加载整个缓存线，需要使用多个主内存读周期。 |
| 原子操作   | Atomic operations      | 不可中断的一个或一系列操作。                                 |
| 缓存行填充 | cache line fill        | 当处理器识别到从内存中读取操作数是可缓存的，处理器读取整个缓存行到适当的缓存（L1，L2，L3 的或所有） |
| 缓存命中   | cache hit              | 如果进行高速缓存行填充操作的内存位置仍然是下次处理器访问的地址时，处理器从缓存中读取操作数，而不是从内存。 |
| 写命中     | write hit              | 当处理器将操作数写回到一个内存缓存的区域时，它首先会检查这个缓存的内存地址是否在缓存行中，如果存在一个有效的缓存行，则处理器将这个操作数写回到缓存，而不是写回到内存，这个操作被称为写命中。 |
| 写缺失     | write misses the cache | 一个有效的缓存行被写入到不存在的内存区域。                   |

### 官方定义

当一个变量定义为volatile之后，它具备两种特性：

1. 保证此变量对所有线程的可见性，这里的“可见性”是指当一条线程修改了这个变量的值，新值对于其他线程来说是可以立即得知的。
2. 禁止指令重排序优化。




```asm
 0x01a3de1d: movb $0x0
 0x1104800(%esi)
 0x01a3de24: **lock** addl $0x0,(%esp)
```



**Lock sync to memory like memory barrier**(Cache Coherence Protocol will invalid changed cache)


## Using volatile

著名的 Java 并发编程大师 Doug lea 在 JDK7 的并发包里新增一个队列集合类 LinkedTransferQueue，他在使用 Volatile 变量时，用一种追加字节的方式来优化队列出队和入队的性能。

追加字节能优化性能？这种方式看起来很神奇，但如果深入理解处理器架构就能理解其中的奥秘。让我们先来看看 LinkedTransferQueue 这个类，它使用一个内部类类型来定义队列的头队列（Head）和尾节点（tail），而这个内部类 PaddedAtomicReference 相对于父类 AtomicReference 只做了一件事情，就将共享变量追加到 64 字节。我们可以来计算下，一个对象的引用占 4 个字节，它追加了 15 个变量共占 60 个字节，再加上父类的 Value 变量，一共 64 个字节。

```java
/** head of the queue */
private transient final PaddedAtomicReference < QNode > head;

/** tail of the queue */

private transient final PaddedAtomicReference < QNode > tail;


static final class PaddedAtomicReference < T > extends AtomicReference < T > {

    // enough padding for 64bytes with 4byte refs 
    Object p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, pa, pb, pc, pd, pe;

    PaddedAtomicReference(T r) {

        super(r);

    }

}

public class AtomicReference < V > implements java.io.Serializable {

    private volatile V value;

    // 省略其他代码 ｝
```

**为什么追加 64 字节能够提高并发编程的效率呢？**

 因为对于英特尔酷睿 i7，酷睿， Atom 和 NetBurst， Core Solo 和 Pentium M 处理器的 L1，L2 或 L3 缓存的高速缓存行是 64 个字节宽，不支持部分填充缓存行，这意味着如果队列的头节点和尾节点都不足 64 字节的话，处理器会将它们都读到同一个高速缓存行中，在多处理器下每个处理器都会缓存同样的头尾节点，当一个处理器试图修改头接点时会将整个缓存行锁定，那么在缓存一致性机制的作用下，会导致其他处理器不能访问自己高速缓存中的尾节点，而队列的入队和出队操作是需要不停修改头接点和尾节点，所以在多处理器的情况下将会严重影响到队列的入队和出队效率。Doug lea 使用追加到 64 字节的方式来填满高速缓冲区的缓存行，避免头接点和尾节点加载到同一个缓存行，使得头尾节点在修改时不会互相锁定。

那么是不是在使用 Volatile 变量时都应该追加到 64 字节呢？不是的。在两种场景下不应该使用这种方式。第一：**缓存行非 64 字节宽的处理器**，如 P6 系列和奔腾处理器，它们的 L1 和 L2 高速缓存行是 32 个字节宽。第二：**共享变量不会被频繁的写**。因为使用追加字节的方式需要处理器读取更多的字节到高速缓冲区，这本身就会带来一定的性能消耗，共享变量如果不被频繁写的话，锁的几率也非常小，就没必要通过追加字节的方式来避免相互锁定。



由于volatile变量只能保证可见性，在不符合以下两条规则的运算场景中，仍然要通过加锁（使用synchronized或java.util.concurrent中的原子类）来保证原子性：

1. 运行结果并不依赖变量的当前值，或者能够确保只有单一的线程修改变量的值。
2. 变量不需要与其他的状态变量共同参与不变约束。

在某些情况下，volatile的同步机制性要优于锁。并且，volatile变量读操作的性能消耗与普通变量几乎没有什么差别，但是写操作则可能会慢一些，因为它需要在本地代码中插入许多内存屏障指令来保证处理器不发生乱序执行。



JIT

```java
    private static int sharedVariable = 0;
    private static final int MAX = 10;

    public static void main(String[] args) {

        new Thread(() -> {
            int oldValue = sharedVariable;
            while (sharedVariable < MAX) {
                if (sharedVariable != oldValue) {
                    System.out.println(Thread.currentThread().getName() + " watched the change : " + oldValue + "->" + sharedVariable);
                    oldValue = sharedVariable;
                }
            }
            System.out.println(Thread.currentThread().getName() + " stop run");
        }, "t1").start();

        new Thread(() -> {
            int oldValue = sharedVariable;
            while (sharedVariable < MAX) {
                System.out.println(Thread.currentThread().getName() + " do the change : " + sharedVariable + "->" + (++oldValue));
                sharedVariable = oldValue;
                try {
                    Thread.sleep(500);
                } catch (InterruptedException e) {
                    e.printStackTrace();
                }
            }
            System.out.println(Thread.currentThread().getName() + " stop run");
        }, "t2").start();

    }
```

-XX:-UseCompiler



Store Buffer

Invalidate Queue



## volatile源码分析

如果你看到这个章节了，意味着你对可见性有一个清晰的认识了，也知道JMM是基于禁止指令重排序来实现可见性的，那么我们再来分析volatile的源码，就会简单很多

**基于最开始演示的这段代码作为入口**

```java
public class VolatileDemo {
    public volatile static boolean stop=false;
    public static void main(String[] args) throws InterruptedException {
        Thread thread=new Thread(()->{
            int i=0;
            while(!stop){
                i++;
            }
        });
        thread.start();
        System.out.println("begin start thread");
        Thread.sleep(1000);
        stop=true;
    }
}
```

`javap-v VolatileDemo.class`

```java
public static volatile boolean stop;
    descriptor: Z
    flags: ACC_PUBLIC, ACC_STATIC, ACC_VOLATILE
...//省略
 public static void main(java.lang.String[]) throws java.lang.InterruptedException;
    descriptor: ([Ljava/lang/String;)V
    flags: ACC_PUBLIC, ACC_STATIC
    Code:
      stack=3, locals=2, args_size=1
         0: new           #2                  // class java/lang/Thread
         3: dup
         4: invokedynamic #3,  0              // InvokeDynamic #0:run:()Ljava/lang/Runnable;
         9: invokespecial #4                  // Method java/lang/Thread."<init>":(Ljava/lang/Runnable;)V
        12: astore_1
        13: aload_1
        14: invokevirtual #5                  // Method java/lang/Thread.start:()V
        17: getstatic     #6                  // Field java/lang/System.out:Ljava/io/PrintStream;
        20: ldc           #7                  // String begin start thread
        22: invokevirtual #8                  // Method java/io/PrintStream.println:(Ljava/lang/String;)V
        25: ldc2_w        #9                  // long 1000l
        28: invokestatic  #11                 // Method java/lang/Thread.sleep:(J)V
        31: iconst_1
        32: putstatic     #12                 // Field stop:Z
        35: return
```

注意被修饰了volatile关键字的 stop字段，会多一个 ACC_VOLATILE的flag，在给 stop复制的时候，调用的字节码是 putstatic,这个字节码会通过`BytecodeInterpreter`解释器来执行，找到Hotspot的源码 `bytecodeInterpreter.cpp`文件，搜索 putstatic指令定位到代码

```cpp
CASE(_putstatic):
        {
          u2 index = Bytes::get_native_u2(pc+1);
          ConstantPoolCacheEntry* cache = cp->entry_at(index);
          if (!cache->is_resolved((Bytecodes::Code)opcode)) {
            CALL_VM(InterpreterRuntime::resolve_get_put(THREAD, (Bytecodes::Code)opcode),
                    handle_exception);
            cache = cp->entry_at(index);
          }

#ifdef VM_JVMTI
          if (_jvmti_interp_events) {
            int *count_addr;
            oop obj;
            // Check to see if a field modification watch has been set
            // before we take the time to call into the VM.
            count_addr = (int *)JvmtiExport::get_field_modification_count_addr();
            if ( *count_addr > 0 ) {
              if ((Bytecodes::Code)opcode == Bytecodes::_putstatic) {
                obj = (oop)NULL;
              }
              else {
                if (cache->is_long() || cache->is_double()) {
                  obj = (oop) STACK_OBJECT(-3);
                } else {
                  obj = (oop) STACK_OBJECT(-2);
                }
                VERIFY_OOP(obj);
              }

              CALL_VM(InterpreterRuntime::post_field_modification(THREAD,
                                          obj,
                                          cache,
                                          (jvalue *)STACK_SLOT(-1)),
                                          handle_exception);
            }
          }
#endif /* VM_JVMTI */

          // QQQ Need to make this as inlined as possible. Probably need to split all the bytecode cases
          // out so c++ compiler has a chance for constant prop to fold everything possible away.

          oop obj;
          int count;
          TosState tos_type = cache->flag_state();

          count = -1;
          if (tos_type == ltos || tos_type == dtos) {
            --count;
          }
          if ((Bytecodes::Code)opcode == Bytecodes::_putstatic) {
            Klass* k = cache->f1_as_klass();
            obj = k->java_mirror();
          } else {
            --count;
            obj = (oop) STACK_OBJECT(count);
            CHECK_NULL(obj);
          }

          //
          // Now store the result
          //
          int field_offset = cache->f2_as_index();
          if (cache->is_volatile()) {
            if (tos_type == itos) {
              obj->release_int_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == atos) {
              VERIFY_OOP(STACK_OBJECT(-1));
              obj->release_obj_field_put(field_offset, STACK_OBJECT(-1));
              OrderAccess::release_store(&BYTE_MAP_BASE[(uintptr_t)obj >> CardTableModRefBS::card_shift], 0);
            } else if (tos_type == btos) {
              obj->release_byte_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == ltos) {
              obj->release_long_field_put(field_offset, STACK_LONG(-1));
            } else if (tos_type == ctos) {
              obj->release_char_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == stos) {
              obj->release_short_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == ftos) {
              obj->release_float_field_put(field_offset, STACK_FLOAT(-1));
            } else {
              obj->release_double_field_put(field_offset, STACK_DOUBLE(-1));
            }
            OrderAccess::storeload();
          } else {
            if (tos_type == itos) {
              obj->int_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == atos) {
              VERIFY_OOP(STACK_OBJECT(-1));
              obj->obj_field_put(field_offset, STACK_OBJECT(-1));
              OrderAccess::release_store(&BYTE_MAP_BASE[(uintptr_t)obj >> CardTableModRefBS::card_shift], 0);
            } else if (tos_type == btos) {
              obj->byte_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == ltos) {
              obj->long_field_put(field_offset, STACK_LONG(-1));
            } else if (tos_type == ctos) {
              obj->char_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == stos) {
              obj->short_field_put(field_offset, STACK_INT(-1));
            } else if (tos_type == ftos) {
              obj->float_field_put(field_offset, STACK_FLOAT(-1));
            } else {
              obj->double_field_put(field_offset, STACK_DOUBLE(-1));
            }
          }
...
```



cache->is_volatile() ，cache是 stop在常量池缓存中的一个实例，这段代码是判断这个cache是否是被 volatile修饰， is_volatile()方法的定义在 accessFlags.hpp文件中，代码如下

```cpp
// accessFlags.hpp
public:
  // Java access flags
  ...//
  bool is_volatile    () const         { return (_flags & JVM_ACC_VOLATILE    ) != 0; }
  bool is_transient   () const         { return (_flags & JVM_ACC_TRANSIENT   ) != 0; }
  bool is_native      () const         { return (_flags & JVM_ACC_NATIVE      ) != 0; }
```

is_volatile是判断是否有 ACC_VOLATILE这个flag，很显然，通过 volatile修饰的stop的字节码中是存在这个flag的，所以 is_volatile()返回true
接着，根据当前字段的类型来给 stop赋值，执行 release_byte_field_put方法赋值,这个方法的实现在 oop.inline.hpp中

```cpp
inline void oopDesc::release_byte_field_put(int offset, jbyte contents)     
{ OrderAccess::release_store(byte_field_addr(offset), contents); }
```

赋值的动作被包装了一层，看看 OrderAccess::release_store做了什么事情呢？这个方法的定义在 orderAccess.hpp中，

```cpp
// orderAccess_linux_x86.inline.hpp
inline void OrderAccess::release_store(volatile jbyte* p, jbyte v) { *p = v; }
```

可以看到其实Java的volatile操作，在JVM实现层面第一步是给予了C++的原语实现。c/c++中的volatile关键字，用来修饰变量，通常用于语言级别的 memory barrier。被volatile声明的变量表示随时可能发生变化，每次使用时，都必须从变量i对应的内存地址读取，编译器对操作该变量的代码不再进行优化

> 赋值操作完成以后，如果大家仔细看了前面putstatic的代码，就会发现还会执行一个 OrderAccess::storeload();的代码，这个代码的实现是在 orderAccess_linux_x86.inline.hpp,它其实就是一个storeload内存屏障，JVM层面的四种内存屏障的定义以及实现

```cpp
inline void OrderAccess::loadload()   { acquire(); }
inline void OrderAccess::storestore() { release(); }
inline void OrderAccess::loadstore()  { acquire(); }
inline void OrderAccess::storeload()  { fence(); }
```

当调用 storeload屏障时，它会调用fence()方法

```cpp
inline void OrderAccess::fence() {
  if (os::is_MP()) { //返回是否多处理器,如果是多处理器才有必要增加内存屏障
    // always use locked addl since mfence is sometimes expensive
#ifdef AMD64
    //__asm__ volatile 嵌入汇编指令
    //lock 汇编指令,lock指令会锁住操作的缓存行,也就是缓存锁的实现
    __asm__ volatile ("lock; addl $0,0(%%rsp)" : : : "cc", "memory");
#else
    __asm__ volatile ("lock; addl $0,0(%%esp)" : : : "cc", "memory");
#endif
  }
}
```

os::is_MP()判断是否是多核,如果是单核,那么就不存在内存不可见或者乱序的问题 

__volatile__:禁止编译器对代码进行某些优化.
Lock :汇编指令，lock指令会锁住操作的缓存行(cacheline), 一般用于read-Modify-write的操作;用来保证后续的操作是原子的
cc代表的是寄存器,memory代表是内存;这边同时用了”cc”和”memory”,来通知编译器内存或者寄存器内的内容已经发生了修改,要重新生成加载指令(不可以从缓存寄存器中取)
这边的read/write请求不能越过lock指令进行重排,那么所有带有lock prefix指令(lock ,xchgl等)都会构成一个天然的x86 Mfence(读写屏障),这里用lock指令作为内存屏障,然后利用asm volatile("" ::: "cc,memory")作为编译器屏障. 这里并没有使用x86的内存屏障指令(mfence,lfence,sfence)，应该是跟x86的架构有关系，x86处理器是强一致内存模型

> storeload屏障是固定调用的方法?为什么要固定调用呢？

原因是：避免volatile写与后面可能有的volatile读/写操作重排序。因为编译器常常无法准确判断在一个volatile写的后面是否需要插入一个StoreLoad屏障。为了保证能正确实现volatile的内存语义，JMM在采取了保守策略：在每个volatile写的后面，或者在每个volatile读的前面插入一个StoreLoad屏障。因为volatile写-读内存语义的常见使用模式是：一个写线程写volatile变量，多个读线程读同一个volatile变量。当读线程的数量大大超过写线程时，选择在volatile写之后插入StoreLoad屏障将带来可观的执行效率的提升。从这里可以看到JMM在实现上的一个特点：首先确保正确性，然后再去追求执行效率







## Reference

1. [The "Double-Checked Locking is Broken" Declaration](https://www.cs.umd.edu/~pugh/java/memoryModel/DoubleCheckedLocking.html)

