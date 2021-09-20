## Introduction


- [Object](/docs/CS/Java/JDK/Basic/Object.md)
- [String](/docs/CS/Java/JDK/Basic/String.md)
- [SPI](/docs/CS/Java/JDK/Basic/SPI.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)
- [Direct Buffer](/docs/CS/Java/JDK/Basic/Direct_Buffer.md)
- [Effective Java](/docs/CS/Java/JDK/Basic/EffectiveJava.md)
- [JDK Tools and Utilities](/docs/CS/Java/JDK/Basic/Tools.md)
## Prims

define open interface

- JNI
- JVM
- Perf
- JVMTI


## Module

- Services - for JMX
  - Management
  - MemoryService
  - MemoryPool
  - MemoryManager
  - RuntimeService
  - ThreadService
  - ClassLoadingService
  - AttachListener
  - HeapDumper
- Runtime
  - Thread
  - Arguments
  - Frame
  - StubRoutines/StubCodeGenerator
  - CompilationPolicy
  - Init
  - VmThread
  - VmOperation
- Oops
- Compiler
- Interpreter
- Code
- Memory
- GC
- C1/Opto/Shark

## launcher
use java/javaw

start:
1. get args
2. pre env
3. load libjvm
4. parse args path
5. new thread create VM and invoke main method

