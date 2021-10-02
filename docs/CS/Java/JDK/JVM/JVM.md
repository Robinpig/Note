## Introduction

[Class File and compiler](/docs/CS/Java/JDK/JVM/ClassFile.md)
[Javac](/docs/CS/Java/JDK/JVM/Javac.md)


[start](/docs/CS/Java/JDK/JVM/start.md)
[destroy](/docs/CS/Java/JDK/JVM/destroy.md)

## ClassLoader
- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)


## Object
[Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
[Thread](/docs/CS/Java/JDK/JVM/Thread.md)


## Runtime
- [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- Heap
- JVM Stack
- Native Method Stack
- Method Area
- Direct Memory
- Program Counter Register


## GC
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)


## Collector
- [CMS](/docs/CS/Java/JDK/JVM/CMS.md)
- [GC](/docs/CS/Java/JDK/JVM/GC.md)
- [G1](/docs/CS/Java/JDK/JVM/G1.md)
- [Shenandoah](/docs/CS/Java/JDK/JVM/Shenandoah.md)


### Execution Engine
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)

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

## Reference
1. [Java T point](https://www.javatpoint.com/jvm-java-virtual-machine)