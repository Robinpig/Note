# JVM



## Class Loader





## Runtime Data Area

- Heap
- JVM Stack
- Native Method Stack
- Method Area
- Direct Memory
- Program Counter Register



### JVM Stack



#### Stack Frame

1. Local Variables
2. Operand Stack
3. Reference 
4. Return Address
5. Dynamic Linking





##### Local Variables Table 

编译时确定最大容量

Non-static method has **this** param default;

slot复用

##### Operand Stack

编译时确定最大深度



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
4. Old Generation



默认old/young=2:1

Eden:from:to=8:1:1



### Method Area

Constant Pool

Method 元信息

Class 元信息



## Execution Engine

## Native Method Inteface



## Native Method Library