## Introduction


> JSR133
> In the original specification, accesses to volatile and non-volatile variables could be freely ordered.


Volatile variables are a lighter-weight synchronization mechanism than locking because they do not involve context switches or thread scheduling.


You can use volatile variables only when all the following criteria are met:
- Writes to the variable do not depend on its current value, or you can ensure that only a single thread ever updates the value;
- The variable does not participate in invariants with other state variables; and
- Locking is not required for any other reason while the variable is being accessed.



```asm
 0x01a3de1d: movb $0x0
 0x1104800(%esi)
 0x01a3de24: **lock** addl $0x0,(%esp)
```



**Lock sync to memory like memory barrier**(Cache Coherence Protocol will invalid changed cache)


## Using volatile

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





## References

1. [The "Double-Checked Locking is Broken" Declaration](https://www.cs.umd.edu/~pugh/java/memoryModel/DoubleCheckedLocking.html)

