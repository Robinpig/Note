

## Introduction



## Memory

Run-Time Data Areas
- The pc Register
- Java Virtual Machine Stacks
- Heap
- Method Area
- Run-Time Constant Pool
- Native Method Stacks






## Heap
The Java Virtual Machine has a heap that is shared among all Java Virtual Machine threads. The heap is the run-time data area from which memory for all class instances and arrays is allocated.

The heap is created on virtual machine start-up. Heap storage for objects is reclaimed by an automatic storage management system (known as a garbage collector); objects are never explicitly deallocated. The Java Virtual Machine assumes no particular type of automatic storage management system, and the storage management technique may be chosen according to the implementor’s system requirements. The heap may be of a fixed size or may be expanded as required by the computation and may be contracted if a larger heap becomes unnecessary. The memory for the heap does not need to be contiguous.

If a computation requires more heap than can be made available by the automatic storage management system, the Java Virtual Machine throws an **OutOfMemoryError**.


Generation see https://dl.acm.org/doi/10.1145/800020.808261

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







## Method Area

The Java Virtual Machine has a method area that is shared among all Java Virtual Machine threads. The method area is analogous to the storage area for compiled code of a conventional language or analogous to the “text” segment in an operating system process. It stores per-class structures such as the run-time constant pool, field and method data, and the code for methods and constructors, including the special methods used in class and interface initialization and in instance initialization.


If memory in the method area cannot be made available to satisfy an allocation request, the Java Virtual Machine throws an OutOfMemoryError.


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


## Program Counter Register




## Native Method Stacks

Java虚拟机栈管理Java方法的调用，而本地方法栈用于管理本地方法的调用

本地方法栈，也是线程私有的。

允许被实现成固定或者是可动态扩展的内存大小。 内存溢出情况和Java虚拟机栈相同

使用C语言实现

具体做法是Native Method Stack 中登记native方法，在Execution Engine执行时加载到本地方法库

当某个线程调用一个本地方法时，就会进入一个全新，不受虚拟机限制的世界，它和虚拟机拥有同样的权限。

并不是所有的JVM都支持本地方法，因为Java虚拟机规范并没有明确要求本地方法栈的使用语言，具体实现方式，数据结构等

**Hotspot JVM中，直接将本地方法栈和虚拟机栈合二为一**


## Java Virtual Machine Stacks



### Frames
- Local Variables
- Operand Stacks
- Dynamic Linking
- Normal Method Invocation Completion
- Abrupt Method Invocation Completion


#### Local Variables Table 

in compiler file

Non-static method has **this** param default;

slot复用

#### Operand Stack

in runtime
shared memory for optimize return value




## Run-Time Constant Pool



Constant Pool SymbolTable use ref count



SymbolTable

1.8 20011

15 32768


## Metaspace

CompressedClassSpaceSize default 1G



Klass Metaspace

a memory block used to storage Klass

default size  = CompressedClassSpaceSize

this space will removed if CompressedClassSpaceSize = 0 or -Xmx > 32G.  and Klass will be storaged into NoKlass Metaspace



NoKlass Metaspace

Multiple memory blocks to storage method constantPool or Klass.



jstat




## Direct Memory
not a part of Run-Time Data Areas