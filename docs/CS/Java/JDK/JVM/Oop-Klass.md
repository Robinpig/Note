## Introduction


```cpp
// oopsHierarchy.hpp

// OBJECT hierarchy
// This hierarchy is a representation hierarchy, i.e. if A is a superclass
// of B, A's representation is a prefix of B's representation.

typedef juint narrowOop; // Offset instead of address for an oop within a java object

// If compressed klass pointers then use narrowKlass.
typedef juint  narrowKlass;

typedef void* OopOrNarrowOopStar;
typedef class   markOopDesc*                markOop;

typedef class oopDesc*                            oop;
typedef class   instanceOopDesc*            instanceOop;
typedef class   arrayOopDesc*                    arrayOop;
typedef class     objArrayOopDesc*            objArrayOop;
typedef class     typeArrayOopDesc*            typeArrayOop;
```



```cpp
// The metadata hierarchy is separate from the oop hierarchy

//      class MetaspaceObj
class   ConstMethod;
class   ConstantPoolCache;
class   MethodData;
//      class Metadata
class   Method;
class   ConstantPool;
//      class CHeapObj
class   CompiledICHolder;
```



```cpp
// The klass hierarchy is separate from the oop hierarchy.

class Klass;
class   InstanceKlass;
class     InstanceMirrorKlass;
class     InstanceClassLoaderKlass;
class     InstanceRefKlass;
class   ArrayKlass;
class     ObjArrayKlass;
class     TypeArrayKlass;
```

## oop

1. markOop
2. metadata

```cpp
//oop.hpp
class oopDesc {
  friend class VMStructs;
  friend class JVMCIVMStructs;
 private:
  volatile markOop _mark;
  union _metadata {
    Klass*      _klass;
    narrowKlass _compressed_klass;
  } _metadata;

 public:
  inline markOop  mark()          const;
  inline markOop  mark_raw()      const;
  inline markOop* mark_addr_raw() const;

  inline void set_mark(volatile markOop m);
  inline void set_mark_raw(volatile markOop m);
  static inline void set_mark_raw(HeapWord* mem, markOop m);

  inline void release_set_mark(markOop m);
  inline markOop cas_set_mark(markOop new_mark, markOop old_mark);
  inline markOop cas_set_mark_raw(markOop new_mark, markOop old_mark, atomic_memory_order order = memory_order_conservative);

  // Used only to re-initialize the mark word (e.g., of promoted
  // objects during a GC) -- requires a valid klass pointer
  inline void init_mark();
  inline void init_mark_raw();

  inline Klass* klass() const;
  inline Klass* klass_or_null() const volatile;
  inline Klass* klass_or_null_acquire() const volatile;
  static inline Klass** klass_addr(HeapWord* mem);
  static inline narrowKlass* compressed_klass_addr(HeapWord* mem);
  inline Klass** klass_addr();
  inline narrowKlass* compressed_klass_addr();
...
}
```


### markOop
```cpp
//markOop.hpp
class markOopDesc: public oopDesc
  ObjectMonitor* monitor() const {
    assert(has_monitor(), "check");
    // Use xor instead of &~ to provide one extra tag-bit check.
    return (ObjectMonitor*) (value() ^ monitor_value);//monitor_value = 2
  }
...
}
```






默认开启

```shell
-XX:+UseCompressedOops
```

由于使用了8字节对齐后每个对象的地址偏移量后3位必定为0，所以在存储的时候可以将后3位0抹除（转化为bit是抹除了最后24位）
在此基础上再去掉最高位，就完成了指针从8字节到4字节的压缩。而在实际使用时，在压缩后的指针后加3位0，就能够实现向真实地址的映射。
指针的32位中的每一个bit，都可以代表8个字节，这样就相当于使原有的内存地址得到了8倍的扩容。所以在8字节对齐的情况下，32位最大能表示2^32*8=32GB内存
由于能够表示的最大内存是32GB，所以如果配置的最大的堆内存超过这个数值时，那么指针压缩将会失效。
-XX:ObjectAlignmentInBytes=16 对应64g

实例数据排序规则
根据对齐规则会压缩调整

```shell
-XX:+CompactFields
```

父类先
大字段先
基本类型先，可调整

```shell
-XX:FieldsAllocationStyle=0 # POJO first, primitive second, default =1
```


超过15 报错

```
-XX:MaxTenuringThreshold=15
```


#### Example

add dependency

```groovy
// https://mvnrepository.com/artifact/org.openjdk.jol/jol-core
compile group: 'org.openjdk.jol', name: 'jol-core', version: '0.13'
```


```java
System.out.println(VM.current().details());
```

```shell
# Running 64-bit HotSpot VM.
# Using compressed oop with 3-bit shift.
# Using compressed klass with 3-bit shift.
# WARNING | Compressed references base/shifts are guessed by the experiment!
# WARNING | Therefore, computed addresses are just guesses, and ARE NOT RELIABLE.
# WARNING | Make sure to attach Serviceability Agent to get the reliable addresses.
# Objects are 8 bytes aligned.
# Field sizes by type: 4, 1, 1, 2, 2, 4, 4, 8, 8 [bytes]
# Array element sizes: 4, 1, 1, 2, 2, 4, 4, 8, 8 [bytes]
```



```java
Object o = new Object();
System.out.println(ClassLayout.parseInstance(o).toPrintable());

String[] array = new String[]{"dfs", "fds", "ds", "fs"};
System.out.println(ClassLayout.parseInstance(array).toPrintable());
```



output

```shell
java.lang.Object object internals:
 OFFSET  SIZE   TYPE DESCRIPTION                               VALUE
      0     4        (object header)                           01 00 00 00 (00000001 00000000 00000000 00000000) (1)
      4     4        (object header)                           00 00 00 00 (00000000 00000000 00000000 00000000) (0)
      8     4        (object header)                           e5 01 00 f8 (11100101 00000001 00000000 11111000) (-134217243)
     12     4        (loss due to the next object alignment)
Instance size: 16 bytes
Space losses: 0 bytes internal + 4 bytes external = 4 bytes total

[Ljava.lang.String; object internals:
 OFFSET  SIZE               TYPE DESCRIPTION                               VALUE
      0     4                    (object header)                           01 00 00 00 (00000001 00000000 00000000 00000000) (1)
      4     4                    (object header)                           00 00 00 00 (00000000 00000000 00000000 00000000) (0)
      8     4                    (object header)                           43 37 00 f8 (01000011 00110111 00000000 11111000) (-134203581)
     12     4                    (object header)                           04 00 00 00 (00000100 00000000 00000000 00000000) (4) #array size
     16    16   java.lang.String String;.<elements>                        N/A
Instance size: 32 bytes
Space losses: 0 bytes internal + 0 bytes external = 0 bytes total
```






### metadata



Klass*

Method*

ConstantPool*


## klass

_layout_helper:
instance >0
array <0
tag primer type or OOP type
hsz first element offset
ebt primer type element
esz element size
others =0

_name

_access_flags

_java_mirror: Class object  instance

_super

_subklass
point the first subkclass

_next_sibling

is a linked list to get all of sibling klasses

_methods

_method_ordering

_local_interfaces: implement

_transitive_interfaces: extends

_fields

_constants

_class_loader

_protection_domain

vtables

itables

static fields

non-static oop-map block

### vtable

