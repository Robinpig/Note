## Introduction


- [Object](/docs/CS/Java/JDK/Basic/Object.md)
- [String](/docs/CS/Java/JDK/Basic/String.md)
- [SPI](/docs/CS/Java/JDK/Basic/SPI.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)
- [Direct Buffer](/docs/CS/Java/JDK/Basic/Direct_Buffer.md)
- [JDK Tools and Utilities](/docs/CS/Java/JDK/Basic/Tools.md)
- [Annotation](/docs/CS/Java/JDK/Basic/Annotation.md)


Like the Java programming language, the Java Virtual Machine operates on two kinds of types: [primitive types](/docs/CS/Java/JDK/Basic/PrimitiveType.md) and reference types.



### Reference Types and Values

There are four kinds of *reference types*: class types, interface types, type variables, and array types.


An array type consists of a `component type` with a single dimension.

The element type of an array type is necessarily either a primitive type, or a class type, or an interface type.

A reference value may also be the special null reference, a reference to no object, 
which will be denoted here by null. 
The null reference initially has no run-time type, but may be cast to any type. 
The default value of a reference type is null.

**This specification does not mandate a concrete value encoding null.**

```
ReferenceType:
	ClassOrInterfaceType 
	TypeVariable 
	ArrayType
	
ClassOrInterfaceType:
 	ClassType 
 	InterfaceType
 	
ClassType:
	{Annotation} TypeIdentifier [TypeArguments] 
	PackageName . {Annotation} TypeIdentifier [TypeArguments] 
	ClassOrInterfaceType . {Annotation} TypeIdentifier [TypeArguments]

InterfaceType:
	ClassType

TypeVariable:
	{Annotation} TypeIdentifier

ArrayType:
	PrimitiveType Dims 
	ClassOrInterfaceType Dims 
	TypeVariable Dims

Dims:
	{Annotation} [ ] {{Annotation} [ ]}
```



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



## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)