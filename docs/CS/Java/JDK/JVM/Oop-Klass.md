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



### metadata



Klass*

Method*

ConstantPool*

