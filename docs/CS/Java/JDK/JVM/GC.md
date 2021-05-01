# GC
Garbage Collection 
## GC Algorithms
   引用计数算法：

   为对象添加一个引用计数器，当对象增加一个引用时计数器加 1，
        引用失效时计数器减 1。引用计数为 0 的对象可被回收，
        但存在循环引用而无法回收问题，已不再适用。
     
   可达性分析算法：

  以 GC Roots 为起始点进行搜索，可达的对象都是存活的，不可达的对象可被回收。
  Java 虚拟机使用该算法来判断对象是否可被回收，GC Roots 一般包含以下内容：



GC Roots

  - 虚拟机栈中局部变量表中引用的对象
  - 本地方法栈中 JNI 中引用的对象 包括global handles和local handles
  - 方法区中类静态属性引用的对象
  - 方法区中的常量引用的对象
  - 所有当前被加载的Java类
  - JVM内部数据结构的一些引用，比如`sun.jvm.hotspot.memory.Universe`类
  - 用于同步的监控对象，比如调用了对象的`wait()`方法







## Reference Types

- 强引用：
- 软引用:

- 弱引用:
- 虚引用:





![image-20210425062416346](/Users/robin/Library/Application Support/typora-user-images/image-20210425062416346.png)