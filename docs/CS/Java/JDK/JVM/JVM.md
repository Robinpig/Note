## Introduction

[start](/docs/CS/Java/JDK/JVM/start.md)
[destroy](/docs/CS/Java/JDK/JVM/destroy.md)


## Object
[Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
[Thread](/docs/CS/Java/JDK/JVM/Thread.md)



## The Structure of the Java Virtual Machine




### Run-Time Data Areas
The Java Virtual Machine defines various [run-time data areas](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) that are used during execution of a program. 
Some of these data areas are created on Java Virtual Machine start-up and are destroyed only when the Java Virtual Machine exits. 
Other data areas are per thread. Per-thread data areas are created when a thread is created and destroyed when the thread exits.

###  Representation of Objects
The Java Virtual Machine does not mandate any particular internal structure for objects.

In some of Oracle’s implementations of the Java Virtual Machine, a reference to a class instance is a pointer to a handle that is itself a pair of pointers(see [OOP-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)):
- one to a table containing the methods of the object and a pointer to the Class object that represents the type of the object
- and the other to the memory allocated from the heap for the object data.

## The class File Format

[Class File and compiler](/docs/CS/Java/JDK/JVM/ClassFile.md)
[Javac](/docs/CS/Java/JDK/JVM/Javac.md)


## Loading, Linking, and Initializing

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)


## GC
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)


## Collector
- [CMS](/docs/CS/Java/JDK/JVM/CMS.md)
- [GC](/docs/CS/Java/JDK/JVM/GC.md)
- [G1](/docs/CS/Java/JDK/JVM/G1.md)
- [Shenandoah](/docs/CS/Java/JDK/JVM/Shenandoah.md)
- [ZGC](/docs/CS/Java/JDK/JVM/ZGC.md)


### Execution Engine
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)

### Native Method Interface



### Native Method Library


Top-of-Stack Cashing
based on stack VM need more instrument dispatch

cached in CPU registers and reduce accessing memory
```cpp
// globalDefinitions.hpp

// TosState describes the top-of-stack state before and after the execution of
// a bytecode or method. The top-of-stack value may be cached in one or more CPU
// registers. The TosState corresponds to the 'machine representation' of this cached
// value. There's 4 states corresponding to the JAVA types int, long, float & double
// as well as a 5th state in case the top-of-stack value is actually on the top
// of stack (in memory) and thus not cached. The atos state corresponds to the itos
// state when it comes to machine representation but is used separately for (oop)
// type specific operations (e.g. verification code).

enum TosState {         // describes the tos cache contents
  btos = 0,             // byte, bool tos cached
  ztos = 1,             // byte, bool tos cached
  ctos = 2,             // char tos cached
  stos = 3,             // short tos cached
  itos = 4,             // int tos cached
  ltos = 5,             // long tos cached
  ftos = 6,             // float tos cached
  dtos = 7,             // double tos cached
  atos = 8,             // object cached
  vtos = 9,             // tos not cached
  number_of_states,
  ilgl                  // illegal state: should not occur
};
```
check previous and after TosState in transition,


```cpp
// templateTable_x86.cpp

void TemplateTable::iop2(Operation op) {
  transition(itos, itos);
  switch (op) {
  case add  :                    __ pop_i(rdx); __ addl (rax, rdx); break;
  case sub  : __ movl(rdx, rax); __ pop_i(rax); __ subl (rax, rdx); break;
  case mul  :                    __ pop_i(rdx); __ imull(rax, rdx); break;
  case _and :                    __ pop_i(rdx); __ andl (rax, rdx); break;
  case _or  :                    __ pop_i(rdx); __ orl  (rax, rdx); break;
  case _xor :                    __ pop_i(rdx); __ xorl (rax, rdx); break;
  case shl  : __ movl(rcx, rax); __ pop_i(rax); __ shll (rax);      break;
  case shr  : __ movl(rcx, rax); __ pop_i(rax); __ sarl (rax);      break;
  case ushr : __ movl(rcx, rax); __ pop_i(rax); __ shrl (rax);      break;
  default   : ShouldNotReachHere();
  }
}
```

## projects

- Amber
- Coin
- Graal
- jigsaw
- Kulla
- Loom
- Panama
- Shenandoah
- Sumatra
- Tsan
- Valhalla
- ZGC



```java
/** based on JDK12
  * 
  *     |--- cpu                     
  *     |--- os
  *     |--- os_cpu
  *     |--- share
  *         |--- adlc               # 
  *         |--- aot                # 
  *         |--- asm                # 
  *         |--- c1                 # C1 JIT
  *         |--- ci                 # compiler interface
  *         |--- classfile          #
  *         |--- code               
  *         |--- compiler           
  *         |--- gc                 
  *         |--- include            
  *         |--- interpreter        
  *         |--- jfr                # Java Flight Record
  *         |--- jvmci              
  *         |--- libadt             
  *         |--- logging            
  *         |--- memory             
  *         |--- metaprogramming    
  *         |--- oops               
  *         |--- opto               # C2 JIT
  *         |--- precompiled        
  *         |--- prims              # implement JNI, JVMTI, Unsafe
  *         |--- runtime            
  *         |--- services           # HeapDump, MXBean, jcmd, jinfo
  *         |--- utilities          # hashtable, JSON parser, elf, etc.
 */
```

## Compiling for the Java Virtual Machine


## Reference
1. [Java T point](https://www.javatpoint.com/jvm-java-virtual-machine)
2. [The Java® Virtual Machine Specification Java SE 17 Edition](https://docs.oracle.com/javase/specs/jvms/se17/html/)
3. [深入理解Java虚拟机（第3版）- 周志明](https://book.douban.com/subject/34907497/)