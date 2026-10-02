## Introduction

Java Virtual Machine Stacks（Java 虚拟机栈）是 [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) 中线程私有的一块内存，
生命周期与线程相同。每个 Java 方法被调用时，JVM 都会同步创建一个 **Stack Frame（栈帧）** 压入当前线程的虚拟机栈；
方法执行结束（无论正常 return 还是抛出未捕获异常）时栈帧出栈。

```
当前线程 VM Stack（后进先出）
        ┌─────────────────────┐
        │   frame: method C   │  ← 栈顶 = 当前正在执行的方法
        ├─────────────────────┤
        │   frame: method B   │
        ├─────────────────────┤
        │   frame: method A   │  ← main / 入口方法
        └─────────────────────┘
```

对一个执行引擎而言，在活动线程中，只有栈顶的栈帧是有效的，称为 **Current Frame（当前栈帧）**，
其对应的方法称为当前方法。所有字节码指令都只对当前栈帧操作。

## Frame

每个栈帧由四部分组成：

- **Local Variables Table（局部变量表）**：存放方法参数和方法内定义的局部变量，以变量槽（Variable Slot）为最小单位。
  `long`/`double` 占两个连续的 Slot，其余基本类型和对象引用占一个。实例方法的第 0 个 Slot 固定是 `this`。
  局部变量表的容量在编译期就写入方法的 Code 属性，运行期不会改变。
- **Operand Stack（操作数栈）**：字节码的工作区。`iload` 把变量压栈，`iadd` 弹出两个 int 相加再压回，
  `istore` 把栈顶写回局部变量表。方法调用时，调用方的操作数栈会通过参数传递与被调方的局部变量表重叠，避免参数拷贝。
- **Dynamic Linking（动态链接）**：指向运行时常量池中该栈帧所属方法的引用，
  支撑符号引用到实际方法入口的解析（静态分派/动态分派，见 invokevirtual）。
- **Return Address（方法返回地址）**：方法退出后回到调用方指令的位置。正常退出时由调用者的 PC 计数器恢复；异常退出时通过异常表确定。

HotSpot 源码层面的栈帧实现（vframe/compiledVFrame/interpreter frame 等）见 [frame](/docs/CS/Java/JDK/JVM/frame.md)。

### Stack Overflow 与 OOM

虚拟机栈有两种容量异常，常被混为一谈：

- 方法调用深度超过栈容量（最典型是无终止条件的递归）→ 抛出 `StackOverflowError`；
- 栈本身可以动态扩展，但扩展时无法申请到足够内存，或创建新线程时无法为其分配栈 → 抛出 `OutOfMemoryError`。

HotSpot 的虚拟机栈不支持扩展，因此在线程运行中只会在方法调用时得到 `StackOverflowError`；
只有在新线程创建、初始栈分配失败时才可能出现 `OutOfMemoryError: unable to create native thread`。

### 栈上分配与逃逸分析

栈帧内的局部变量随方法返回自动销毁，不需要 GC 介入。若 JIT 通过逃逸分析（Escape Analysis）确认一个对象
**不会逃逸出方法/线程**（NoEscape），可能做 **Scalar Replacement（标量替换）**：对象根本不创建，
其字段拆散为标量直接分配在寄存器或局部变量表中，比在 [Heap](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md?id=heap) 上分配再回收便宜得多。
注意「栈上分配」在 HotSpot 中并非真的把对象塞进 Java 虚拟机栈，而是标量替换的通俗说法。

## Native Method Stack

与虚拟机栈的区别仅在于：虚拟机栈为 Java 方法（字节码）服务，[Native Method Stacks](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md?id=native-method-stacks)
为 [JNI](/docs/CS/Java/JDK/Basic/JNI.md) native 方法服务。HotSpot 直接把两者合二为一。

## Links

- [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [frame](/docs/CS/Java/JDK/JVM/frame.md)
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Thread](/docs/CS/Java/JDK/Concurrency/Thread.md) — Java 线程与虚拟机栈 1:1 对应

## References

1. [The Java® Virtual Machine Specification: Run-Time Data Areas](https://docs.oracle.com/javase/specs/jvms/se17/html/jvms-2.html#jvms-2.5)
2. [The Java® Virtual Machine Specification: Frames](https://docs.oracle.com/javase/specs/jvms/se17/html/jvms-2.html#jvms-2.6)
