

## Introduction



## Memory

- Heap
- JVM Stack
- Native Method Stack
- Method Area
- Direct Memory
- Program Counter Register





#### Stack Frame

1. Local Variables
2. Operand Stack
3. Reference 
4. Return Address
5. Dynamic Linking





##### Local Variables Table 

in compiler file

Non-static method has **this** param default;

slot复用

##### Operand Stack

in runtime
shared memory for optimize return value


##### Reference




### Native Method Stack

Java虚拟机栈管理Java方法的调用，而本地方法栈用于管理本地方法的调用

本地方法栈，也是线程私有的。

允许被实现成固定或者是可动态扩展的内存大小。 内存溢出情况和Java虚拟机栈相同

使用C语言实现

具体做法是Native Method Stack 中登记native方法，在Execution Engine执行时加载到本地方法库

当某个线程调用一个本地方法时，就会进入一个全新，不受虚拟机限制的世界，它和虚拟机拥有同样的权限。

并不是所有的JVM都支持本地方法，因为Java虚拟机规范并没有明确要求本地方法栈的使用语言，具体实现方式，数据结构等

**Hotspot JVM中，直接将本地方法栈和虚拟机栈合二为一**



### Heap

1. Young Generation
   1. Eden
   2. Survivor
      1. From
      2. To
      3. 
2. Old Generation



默认old/young=2:1

Eden:from:to=8:1:1


FastTLABRefill                            = true  
MinTLABSize                               = 2048
PrintTLAB                                 = false
ResizeTLAB                                = true  
TLABAllocationWeight                      = 35   
TLABRefillWasteFraction                   = 64   
TLABSize                                  = 0    
TLABStats                                 = true
TLABWasteIncrement                        = 4    
TLABWasteTargetPercent                    = 1
UseTLAB                                   = true
ZeroTLAB                                  = false
### new instance

1. is_unresolved_klass, slow case allocation
2. Enable fastpath_allocated, try UseTLAB
3. CAS retry allocate in shared_eden, fail slow allocation
4. Initialize object set mark

```cpp
// bytecodeInterpreter.cpp
CASE(_new): {
        u2 index = Bytes::get_Java_u2(pc+1);
        ConstantPool* constants = istate->method()->constants();
        if (!constants->tag_at(index).is_unresolved_klass()) {
          // Make sure klass is initialized and doesn't have a finalizer
          Klass* entry = constants->resolved_klass_at(index);
          InstanceKlass* ik = InstanceKlass::cast(entry);
          if (ik->is_initialized() && ik->can_be_fastpath_allocated() ) {
            size_t obj_size = ik->size_helper();
            oop result = NULL;
            // If the TLAB isn't pre-zeroed then we'll have to do it
            bool need_zero = !ZeroTLAB;
            if (UseTLAB) {
              result = (oop) THREAD->tlab().allocate(obj_size);
            }
            // Disable non-TLAB-based fast-path, because profiling requires that all
            // allocations go through InterpreterRuntime::_new() if THREAD->tlab().allocate
            // returns NULL.
#ifndef CC_INTERP_PROFILE
            if (result == NULL) {
              need_zero = true;
              // Try allocate in shared eden
            retry:
              HeapWord* compare_to = *Universe::heap()->top_addr();
              HeapWord* new_top = compare_to + obj_size;
              if (new_top <= *Universe::heap()->end_addr()) {
                if (Atomic::cmpxchg(new_top, Universe::heap()->top_addr(), compare_to) != compare_to) {
                  goto retry;
                }
                result = (oop) compare_to;
              }
            }
#endif
            if (result != NULL) {
              // Initialize object (if nonzero size and need) and then the header
              if (need_zero ) {
                HeapWord* to_zero = (HeapWord*) result + sizeof(oopDesc) / oopSize;
                obj_size -= sizeof(oopDesc) / oopSize;
                if (obj_size > 0 ) {
                  memset(to_zero, 0, obj_size * HeapWordSize);
                }
              }
              if (UseBiasedLocking) {
                result->set_mark(ik->prototype_header());
              } else {
                result->set_mark(markOopDesc::prototype());
              }
              result->set_klass_gap(0);
              result->set_klass(ik);
              // Must prevent reordering of stores for object initialization
              // with stores that publish the new object.
              OrderAccess::storestore();
              SET_STACK_OBJECT(result, 0);
              UPDATE_PC_AND_TOS_AND_CONTINUE(3, 1);
            }
          }
        }
        // Slow case allocation
        CALL_VM(InterpreterRuntime::_new(THREAD, METHOD->constants(), index),
                handle_exception);
        // Must prevent reordering of stores for object initialization
        // with stores that publish the new object.
        OrderAccess::storestore();
        SET_STACK_OBJECT(THREAD->vm_result(), 0);
        THREAD->set_vm_result(NULL);
        UPDATE_PC_AND_TOS_AND_CONTINUE(3, 1);
      }
```




#### InstanceKlass::allocate_instance

also allow use TLAB

```cpp
instanceOop InstanceKlass::allocate_instance(TRAPS) {
  bool has_finalizer_flag = has_finalizer(); // Query before possible GC
  int size = size_helper();  // Query before forming handle.

  instanceOop i;

  i = (instanceOop)Universe::heap()->obj_allocate(this, size, CHECK_NULL);
  if (has_finalizer_flag && !RegisterFinalizersAtInit) {
    i = register_finalizer(i, CHECK_NULL);
  }
  return i;
}
```


```cpp
// collectedHeap.cpp
oop CollectedHeap::obj_allocate(Klass* klass, int size, TRAPS) {
  ObjAllocator allocator(klass, size, THREAD);
  return allocator.allocate();
}
```



```cpp
// shenandoahHeap.cpp
oop ShenandoahHeap::obj_allocate(Klass* klass, int size, TRAPS) {
  ObjAllocator initializer(klass, size, THREAD);
  ShenandoahMemAllocator allocator(initializer, klass, size, THREAD);
  return allocator.allocate();
}
```

```cpp
// memAllocator.cpp
oop MemAllocator::allocate() const {
  oop obj = NULL;
  {
    Allocation allocation(*this, &obj);
    HeapWord* mem = mem_allocate(allocation);
    if (mem != NULL) {
      obj = initialize(mem);
    }
  }
  return obj;
}

HeapWord* MemAllocator::mem_allocate(Allocation& allocation) const {
  if (UseTLAB) {
    HeapWord* result = allocate_inside_tlab(allocation);
    if (result != NULL) {
      return result;
    }
  }

  return allocate_outside_tlab(allocation);
}
```




### Method Area



```java
// -XX:MaxMetaspaceSize=10M
public static void main(String[] args) {
    while (true) {
        Enhancer enhancer = new Enhancer();
        enhancer.setSuperclass(HeapOOM.class);
        enhancer.setUseCache(false); // use cache if true to avoid OOM
        enhancer.setCallback((MethodInterceptor) (o, method, objects, methodProxy) -> methodProxy.invoke(o, objects));
        enhancer.create();

    }
}
```

Method 元信息

Class 元信息

[JEP 122: Remove the Permanent Generation](https://openjdk.java.net/jeps/122)


## 程序计数器

## 本地方法栈

## 虚拟机栈

### 栈帧：

     每个 Java 方法在执行的同时会创建一个栈帧用于存储局部变量表、操作数栈、 函数调用的上下文 和方法出口。从方法调用直至执行完成的过程，对应着一个栈帧在 Java 虚拟机栈中入栈和出栈的过程，会抛出StackOverflowError 异常和OutOfMemoryError 异常 。

操作数栈负责具体指令执行。

## 堆

所有对象都在这里分配内存，是垃圾收集的主要区域（"GC 堆"）。

现代的垃圾收集器基本都是采用分代收集算法，其主要的思想是针对不同类型的对象采取不同的垃圾回收算法。可以将堆分成两块：

   - 新生代（Young Generation）
   - 老年代（Old Generation）

会抛出 OutOfMemoryError 异常

可以通过 -Xms 和 -Xmx 这两个虚拟机参数来指定一个程序的堆内存大小，第一个参数设置初始值，第二个参数设置最大值。

## 方法区

用于存放已被加载的类信息、常量、静态变量、即时编译器编译后的代码等数据。

会抛出 OutOfMemoryError 异常。

对这块区域进行垃圾回收的主要目标是对常量池的回收和对类的卸载，但是一般比较难实现。

会抛出 OutOfMemoryError 异常从 JDK 1.8 开始，移除永久代，并把方法区移至元空间，它位于本地内存中，而不是虚拟机内存中。元空间存储类的元信息，静态变量和常量池等放入堆中。

### 运行时常量池

Class 文件中的常量池（编译器生成的字面量和符号引用）会在类加载后被放入这个区域。

除了在编译期生成的常量，还允许动态生成，例如 String 类的 intern()。

## 直接内存

在 JDK 1.4 中新引入了 NIO 类，它可以使用 Native 函数库直接分配堆外内存，然后通过 Java 堆里的 DirectByteBuffer 对象作为这块内存的引用进行操作。这样能在一些场景中显著提高性能，因为避免了在堆内存和堆外内存来回拷贝数据。



## Metaspace

CompressedClassSpaceSize default 1G



Klass Metaspace

a memory block used to storage Klass

default size  = CompressedClassSpaceSize

this space will removed if CompressedClassSpaceSize = 0 or -Xmx > 32G.  and Klass will be storaged into NoKlass Metaspace



NoKlass Metaspace

Multiple memory blocks to storage method constantPool or Klass.



jstat



