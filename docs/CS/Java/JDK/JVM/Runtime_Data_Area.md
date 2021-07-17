

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
2. Old Generation



默认old/young=2:1

Eden:from:to=8:1:1

### allocate memory for instance

If TLAB

eden cas

Minior GC to Old 

Full GC







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