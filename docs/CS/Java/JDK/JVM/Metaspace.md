## Introduction


在介绍Metaspace之前 我们首先需要回顾一下 PermGen 内存上它是挨着堆的 垃圾回收使用的是老年代的回收算法
PermGen 上主要存放以下数据
- JVM internal representation of classes and their metadata
- Class statics
- Interned strings
从 JDK7 开始，JDK 开发者们就有消灭永久代的打算了。有部分数据移到永久代之外了：
- Symbols => native memory
- Interned strings => Java Heap
- Class statics => Java Heap

JDK8后 彻底废弃 PermGen 由Metaspace取而代之
OOM

Metaspace is memory the VM uses to store class metadata.
Class metadata are the runtime representation of java classes within a JVM process - basically any information the JVM needs to work with a Java class. That includes, but is not limited to, runtime representation of data from the JVM class file format.
Examples:
- the “Klass” structure - the VM-internal representation of runtime state of a java class. This includes both vtable and itable.
- Method metadata - runtime equivalent of the method_info in the class file, containing things like the bytecode, exception table, constants, etc.
- The constant pool
- Annotations
- method counters collected at runtime as a base for JIT decisions
- etc.



Allocation from Metaspace is coupled to class loading. When a class is loaded and its runtime representation in the JVM is being prepared, Metaspace is allocated by its class loader to store the class’ metadata.

The allocated Metaspace for a class is owned by its class loader. It is only released when that class loader itself is unloaded, not before.
However, “releasing Metaspace” does not necessarily mean that memory is returned to the OS.

All or a part of that memory may be retained within the JVM; it may be reused for future class loading, but at the moment it remains unused within the JVM process.



There are two parameters to limit Metaspace size:
- -XX:MaxMetaspaceSize determines the maximum committed size the Metaspace is allowed to grow. It is by default unlimited.
- -XX:CompressedClassSpaceSize determines the virtual size of one important portion of the Metaspace, the Compressed Class Space. Its default value is 1G (note: reserved space, not committed



Klass Metaspace

1. Klass Metaspace就是用来存**klass**的，就是class文件在jvm里的运行时数据结构（不过我们看到的类似A.class其实是存在heap里的，是java.lang.Class的对象实例）。
2. 这部分默认放在**Compressed Class Pointer Space**中，是一块连续的内存区域，
   紧接着Heap，和之前的perm一样。通过-XX:CompressedClassSpaceSize来控制这块内存的大小，默认是1G。
   下图展示了对象的存储模型，_mark是对象的Mark Word，_klass是元数据指针

Compressed Class Pointer Space**不是必须有的**，如果设置了**-XX:-UseCompressedClassPointers**，或者**-Xmx设置大于32G**，就不会有这块内存，这种情况下klass都会存在NoKlass Metaspace里




NoKlass Metaspace

1. NoKlass Metaspace专门来存klass相关的其他的内容，比如method，constantPool等，可以由多块不连续的内存组成。
2. 这块内存是必须的，虽然叫做NoKlass Metaspace，但是也其实可以存klass的内容，上面已经提到了对应场景。
3. NoKlass Metaspace在本地内存中分配



A Metaspace-induced GC is triggered in two cases:

- When allocating Metaspace: the VM holds a threshold beyond which it will not grow the Metaspace without attempting to collect old class loaders first - and thereby reusing their Metaspace - by triggering a GC. That point is the *Metaspace GC threshold*. It prevents Metaspace from growing without releasing stale metadata. That threshold moves up and down, roughly following the sum of committed metaspace by a certain margin.
- When encountering a *Metaspace OOM* - which happen either when the sum of committed memory hits the *MaxMetaspaceSize* cap or when we run out of *Compressed Class Space* - a GC is attempted to remedy this situation. If it actually unloads class loaders this ins fine, if not we may run into a bad GC cycle even though we have enough Java heap.



## Architecture

Metaspace is implemented in layers.

- At the bottom, memory is allocated in large regions from the OS. 
- At the middle, we carve those regions in not-so-large chunks and hand them over to class loaders. 
- At the top, the class loaders cut up those chunks to serve the caller code.



At the bottom-most layer - at the most coarse granularity - memory for Metaspace is reserved and on demand committed from the OS via virtual memory calls like mmap(3). This happens in regions of 2MB size (on 64bit platforms).

These mapped regions are kept as nodes in a global linked list named [VirtualSpaceList](http://hg.openjdk.java.net/jdk/jdk11/file/1ddf9a99e4ad/src/hotspot/share/memory/metaspace/virtualSpaceList.hpp#l39).



The class loader keeps its native representation in a native structure called [ClassLoaderData](http://hg.openjdk.java.net/jdk/jdk11/file/1ddf9a99e4ad/src/hotspot/share/classfile/classLoaderData.hpp#l176).

That structure has a reference to one [ClassLoaderMetaspace](http://hg.openjdk.java.net/jdk/jdk11/file/1ddf9a99e4ad/src/hotspot/share/memory/metaspace.hpp#l230) structure which keeps a list of all Metachunks this loader has in use.



When the loader gets unloaded, the associated `ClassLoaderData` and its `ClassLoaderMetaspace` get deleted. This releases all chunks used by this class loader into the Metaspace freelist. It may or may not result in memory released to the OS if the conditions are right, see below.



When all chunks within one VirtualSpaceListNode happen to be free, that node itself is removed. The node is removed from the VirtualSpaceList. Its free chunks are removed from the Metaspace freelist. The node is unmapped and its memory returned to the OS. The node is [“purged”](http://hg.openjdk.java.net/jdk/jdk11/file/1ddf9a99e4ad/src/hotspot/share/memory/metaspace/virtualSpaceList.cpp#l74).

For each loaded class there will be space allocated from class metadata from both class and non-class space.Into Class Space goes the Klass structure, which is fixed-sized.

That is followed by two variable sized structures, the vtable and the itable. Size of the former grows with the number of methods, size of the latter with the number of inherited interface methods from implemented interfaces.

That in turn is followed by a map describing the positions of Object-referencing members in the Java class, the non-static Oopmap. This structure is also variable sized though typically very small.

Both vtable and itable are typically small but can grow to enormous proportions for weird large classes. But these are test cases, apart from automatic code generation one will not find such classes in the wild.

Into Non-Class Space go a lot of things, among them as largest contributors:

- the constant pool, which is variable sized.
- meta data for any of the class methods: the ConstMethod structure with a lot of associated, largely variable-sized embedded structures like the method bytecode, the local variable table, the exception table, parameter infos, signature etc.
- Runtime method data used to control the JIT
- Annotations



A ClassLoaderMetaspace manages MetaspaceArena(s) for a CLD.

A CLD owns one MetaspaceArena if UseCompressedClassPointers is false. 
Otherwise it owns two - one for the Klass* objects from the class space, one for the other types of MetaspaceObjs from the non-class space.

```c
// +------+       +----------------------+       +-------------------+
// | CLD  | --->  | ClassLoaderMetaspace | ----> | (non class) Arena |
// +------+       +----------------------+  |    +-------------------+     allocation top
//                                          |       |                        v
//                                          |       + chunk -- chunk ... -- chunk
//                                          |
//                                          |    +-------------------+
//                                          +--> | (class) Arena     |
//                                               +-------------------+
//                                                  |
//                                                  + chunk ... chunk
//                                                               ^
//                                                               alloc top
```


## Tuning


排查metaspace OOM


经常会出问题的几个点有 Orika 的 classMap、JSON 的 ASMSerializer、Groovy 动态加载类等，基本都集中在反射、Javasisit 字节码增强、CGLIB 动态代理、OSGi 自定义类加载器等的技术点上。另外就是及时给 MetaSpace 区的使用率加一个监控，如果指标有波动提前发现并解决问题






## Link

- [RuntimeArea](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)

