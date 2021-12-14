

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
```
make sure is resolved klass
```cpp
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
```
Disable non-TLAB-based fast-path, because profiling requires that all allocations go through InterpreterRuntime::_new() if THREAD->tlab().allocate returns NULL.
```
#ifndef CC_INTERP_PROFILE
            if (result == NULL) {
              need_zero = true;
```
Try allocate in shared eden, use CAS retry
```cpp
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
```
Initialize object (if nonzero size and need) and then the header
```cpp
              if (need_zero ) {
                HeapWord* to_zero = (HeapWord*) result + sizeof(oopDesc) / oopSize;
                obj_size -= sizeof(oopDesc) / oopSize;
                if (obj_size > 0 ) {
                  memset(to_zero, 0, obj_size * HeapWordSize);
                }
              }
```
if UseBiasedLocking
```cpp
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
```
Slow case allocation
```
        CALL_VM(InterpreterRuntime::_new(THREAD, METHOD->constants(), index),
                handle_exception);
        // Must prevent reordering of stores for object initialization
        // with stores that publish the new object.
        OrderAccess::storestore();
```
Set stack object and update pc register and continue
```
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

Consider using the "-J-Xss<size>" command line option to increase the memory allocated for the Java stack.




### Frames
A frame is used to store data and partial results, as well as to perform dynamic linking, return values for methods, and dispatch exceptions.

A new frame is created each time a method is invoked. A frame is destroyed when its method invocation completes, whether that completion is normal or abrupt (it throws an uncaught exception). 
Frames are allocated from the Java Virtual Machine stack of the thread creating the frame. 
Each frame has its own array of local variables, its own operand stack, and a reference to the run-time constant pool of the class of the current method.
- Local Variables
- Operand Stacks
- Dynamic Linking


#### Local Variables Table 
Each frame contains an array of variables known as its local variables. 
The length of the local variable array of a frame is determined at compile-time and supplied in the binary representation of a class or interface along with the code for the method associated with the frame.

A single local variable can hold a value of type `boolean`, `byte`, `char`, `short`, `int`, `float`, `reference`, or `returnAddress`. A pair of local variables can hold a value of type `long` or `double`.

Local variables are addressed by indexing. The index of the first local variable is zero. An integer is considered to be an index into the local variable array if and only if that integer is between zero and one less than the size of the local variable array.

A value of type `long` or type `double` occupies two consecutive local variables. Such a value may only be addressed using the lesser index. For example, a value of type `double` stored in the local variable array at index *n* actually occupies the local variables with indices *n* and *n*+1; however, the local variable at index *n*+1 cannot be loaded from. It can be stored into. However, doing so invalidates the contents of local variable *n*.

The Java Virtual Machine does not require *n* to be even. In intuitive terms, values of types `long` and `double` need not be 64-bit aligned in the local variables array. Implementors are free to decide the appropriate way to represent such values using the two local variables reserved for the value.



The Java Virtual Machine uses local variables to pass parameters on method invocation. 
- On class method invocation, any parameters are passed in consecutive local variables starting from local variable 0. 
- On instance method invocation, local variable 0 is always used to pass a reference to the object on which the instance method is being invoked (`this` in the Java programming language). Any parameters are subsequently passed in consecutive local variables starting from local variable 1.

**Reuse slots**

#### Operand Stack
Each frame contains a last-in-first-out (LIFO) stack known as its operand stack. 
The maximum depth of the operand stack of a frame is determined at compile-time and is supplied along with the code for the method associated with the frame.

in runtime
shared memory for optimize return value


#### Dynamic Linking
Each frame contains a reference to the run-time constant pool for the type of the current method to support dynamic linking of the method code. The class file code for a method refers to methods to be invoked and variables to be accessed via symbolic references. Dynamic linking translates these symbolic method references into concrete method references, loading classes as necessary to resolve as-yet-undefined symbols, and translates variable accesses into appropriate offsets in storage structures associated with the run-time location of these variables.

This late binding of the methods and variables makes changes in other classes that a method uses less likely to break this code.

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

```hpp
// globals.hpp
  product(uint64_t, MaxDirectMemorySize, 0,                                 \
          "Maximum total size of NIO direct-buffer allocations")            \
          range(0, max_jlong)                                               \
```