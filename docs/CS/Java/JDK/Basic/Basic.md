## Introduction

- 
- [String](/docs/CS/Java/JDK/Basic/String.md)
- [SPI](/docs/CS/Java/JDK/Basic/SPI.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)
- [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)
- [JDK Tools and Utilities](/docs/CS/Java/JDK/Basic/Tools.md)
- [Annotation](/docs/CS/Java/JDK/Basic/Annotation.md)
- [Lambda](/docs/CS/Java/JDK/Basic/Lambda.md)

与 Java 编程语言一样，Java 虚拟机操作两种类型： [primitive types](/docs/CS/Java/JDK/Basic/PrimitiveType.md) 和 reference types。



### Reference Types and Values

有四种 *reference types*： class types、interface types、type variables 和 array types。


数组类型由单一维度的 `component type` 组成。

数组类型的元素类型必须是 primitive type、class type 或 interface type。

引用值也可以是一个特殊的 null 引用（即不引用任何对象的引用），
在此用 null 表示。
null 引用初始没有运行时类型，但可以转换为任何类型。
引用类型的默认值是 null。

**本规范不强制要求具体的 null 值编码。**

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

定义开放接口

- JNI
- JVM
- Perf
- JVMTI


## Module

- Services - 用于 JMX
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
使用 java/javaw

启动流程：
1. 获取参数
2. 预初始化环境
3. 加载 libjvm
4. 解析参数路径
5. 新建线程创建 VM 并调用 main 方法



## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)