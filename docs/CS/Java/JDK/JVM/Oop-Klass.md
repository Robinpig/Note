## Introduction

One reason for the oop/klass dichotomy in the implementation is that we don't want a C++ vtbl pointer in every object.
Thus, normal oops don't have any virtual functions.
<br/>
Instead, they forward all "virtual" functions to their klass, which does have a vtbl and does the C++ dispatch depending on the object's actual type.







## Klass

A Klass provides:

1. language level class object (method dictionary etc.)
2. provide vm dispatch behavior for the object



Both functions are combined into one C++ class.



### Klass hierarchy

The klass hierarchy is separate from the oop hierarchy.

<div style="text-align: center;">

![](img/Klass.svg)

</div>


<p style="text-align: center;">
Fig.1. Klass hierarchy.
</p>



<div class="center">

| Type                     | Java Level                |
| ------------------------ | ------------------------- |
|                          |                           |
| InstanceMirrorKlass      | `java.lang.CLass`         |
| InstanceRefKlass         | `java.lang.ref.Reference` |
| InstanceClassLoaderKlass | `java.lang.ClassLoader`   |


</div>




### Klass Struct

```cpp
class Klass : public Metadata {

protected:
  enum { _primary_super_limit = 8 };
  
  jint        _layout_helper;

  const KlassID _id;

  int _vtable_len;
  
  juint       _super_check_offset;
  Symbol*     _name;
  Klass*      _secondary_super_cache;
  Array<Klass*>* _secondary_supers;
  Klass*      _primary_supers[_primary_super_limit];
  
  OopHandle   _java_mirror;     // java/lang/Class instance mirroring this class
  Klass*      _super;
  Klass* volatile _subklass;
  Klass* volatile _next_sibling;
  Klass*      _next_link;       // All klasses loaded by a class loader are chained through these links

  // The VM's representation of the ClassLoader used to load this class.
  // Provide access the corresponding instance java.lang.ClassLoader.
  ClassLoaderData* _class_loader_data;

  jint        _modifier_flags;  // Processed access flags, for use by Class.getModifiers.
  AccessFlags _access_flags;    // Access flags. The class/interface distinction is stored here.

  // Biased locking implementation and statistics
  // (the 64-bit chunk goes first, to avoid some fragmentation)
  jlong    _last_biased_lock_bulk_revocation_time;
  markWord _prototype_header;   // Used when biased locking is both enabled and disabled for this type
  jint     _biased_lock_revocation_count;
}
```

### ArrayKlass

```cpp
class ArrayKlass: public Klass {
  friend class VMStructs;
 private:
  // If you add a new field that points to any metaspace object, you
  // must add this field to ArrayKlass::metaspace_pointers_do().
  int      _dimension;         // This is n'th-dimensional array.
  Klass* volatile _higher_dimension;  // Refers the (n+1)'th-dimensional array (if present).
  Klass* volatile _lower_dimension;   // Refers the (n-1)'th-dimensional array (if present).


```

#### TypeArrayKlass
```cpp
class TypeArrayKlass : public ArrayKlass {
 private:
  jint _max_length;            // maximum number of elements allowed in an array
}
```
#### ObjArrayKlass

```cpp
class ObjArrayKlass : public ArrayKlass {
 private:
  Klass* _element_klass;            // The klass of the elements of this array type
  Klass* _bottom_klass;             // The one-dimensional type (InstanceKlass or TypeArrayKlass)
}  
```

```dot
digraph g{
    rankdir="LR"
    Obj[label="InstanceKlass", shape=box]
    One[label="ObjArrayKlass \n (1 dimension)", shape=box]
    Two[label="ObjArrayKlass \n (2 dimension)", shape=box]
    One->Obj[label="_element_klass \n _bottom_klass"]
    Two->Obj[label="_bottom_klass"]
    Two->One[label="_element_klass"]
}
```


### oop_oop_iterate


```c
template <typename OopClosureType>
void oopDesc::oop_iterate(OopClosureType* cl) {
  OopIteratorClosureDispatch::oop_oop_iterate(cl, this, klass());
}

template <typename OopClosureType>
void OopIteratorClosureDispatch::oop_oop_iterate(OopClosureType* cl, oop obj, Klass* klass) {
  OopOopIterateDispatch<OopClosureType>::function(klass)(cl, obj, klass);
}
```

获取开始OopMapBlock和结束OopMapBlock，然后遍历这些OopMapBlock。OopMapBlock存储了该对象的字段偏移和个数，分别用offset和count表示
offset表示第一个字段相对于对象头的偏移，count表示对象有多少个字段
另外，如果有父类，则再用一个OopMapBlock表示父类，因此通过遍历对象的所有OopMapBlock就能访问对象的全部字段

```c
template <typename T, class OopClosureType>
ALWAYSINLINE void InstanceKlass::oop_oop_iterate(oop obj, OopClosureType* closure) {
  if (Devirtualizer::do_metadata(closure)) {
    Devirtualizer::do_klass(closure, this);
  }

  oop_oop_iterate_oop_maps<T>(obj, closure);
}

template <typename T, class OopClosureType>
ALWAYSINLINE void InstanceKlass::oop_oop_iterate_oop_maps(oop obj, OopClosureType* closure) {
  OopMapBlock* map           = start_of_nonstatic_oop_maps();
  OopMapBlock* const end_map = map + nonstatic_oop_map_count();

  for (; map < end_map; ++map) {
    oop_oop_iterate_oop_map<T>(map, obj, closure);
  }
}
```

```cpp
// share/gc/serial/markSweep.cpp
inline void MarkSweep::follow_object(oop obj) {
  if (obj->is_objArray()) {
    // Handle object arrays explicitly to allow them to
    // be split into chunks if needed.
    MarkSweep::follow_array((objArrayOop)obj);
  } else {
    obj->oop_iterate(&mark_and_push_closure);
  }
}
```

```cpp
// InstanceKlass.inline.hpp
template <typename T, class OopClosureType>
ALWAYSINLINE void InstanceKlass::oop_oop_iterate_oop_maps(oop obj, OopClosureType* closure) {
  OopMapBlock* map           = start_of_nonstatic_oop_maps();
  OopMapBlock* const end_map = map + nonstatic_oop_map_count();

  for (; map < end_map; ++map) {
    oop_oop_iterate_oop_map<T>(map, obj, closure);
  }
}
```

The iteration over the oops in objects is a hot path in the GC code.
By force inlining the following functions, we get similar GC performance as the previous macro based implementation.

```cpp
template <typename T, class OopClosureType>
ALWAYSINLINE void InstanceKlass::oop_oop_iterate_oop_map(OopMapBlock* map, oop obj, OopClosureType* closure) {
  T* p         = (T*)obj->obj_field_addr_raw<T>(map->offset());
  T* const end = p + map->count();

  for (; p < end; ++p) {
    Devirtualizer::do_oop(closure, p);
  }
}
```

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


### CLD

```cpp
// ClassLoaderData.hpp
class ClassLoaderData : public CHeapObj<mtClass> {


  static ClassLoaderData * _the_null_class_loader_data;

  WeakHandle<vm_class_loader_data> _holder; // The oop that determines lifetime of this class loader
  OopHandle _class_loader;    // The instance of java/lang/ClassLoader associated with
                              // this ClassLoaderData
     
  ClassLoaderMetaspace * volatile _metaspace;  // Meta-space where meta-data defined by the
                                    // classes in the class loader are allocated.
  Mutex* _metaspace_lock;  // Locks the metaspace for allocations and setup.
  
  bool _unloading;         // true if this class loader goes away
  bool _is_unsafe_anonymous; // CLD is dedicated to one class and that class determines the CLDs lifecycle.
                             // For example, an unsafe anonymous class.

  // Remembered sets support for the oops in the class loader data.
  bool _modified_oops;             // Card Table Equivalent (YC/CMS support)
  bool _accumulated_modified_oops; // Mod Union Equivalent (CMS support)

  s2 _keep_alive;          // if this CLD is kept alive.
                           // Used for unsafe anonymous classes and the boot class
                           // loader. _keep_alive does not need to be volatile or
                           // atomic since there is one unique CLD per unsafe anonymous class.
                                       
  // Support for walking class loader data objects
  ClassLoaderData* _next; /// Next loader_datas created
  
  Klass* volatile _klasses;              // The classes defined by the class loader.
  
  // Support for walking class loader data objects
  ClassLoaderData* _next; /// Next loader_datas created
  
  Klass*  _class_loader_klass;
  Symbol* _name;
  }
```

```java

public class ClassLoaderDataGraph {
    /** Lookup an already loaded class in any class loader. */
    public Klass find(String className) {
        for (ClassLoaderData cld = getClassLoaderGraphHead(); cld != null; cld = cld.next()) {
            Klass k = cld.find(className);
            if (k != null) {
                return k;
            }
        }
        return null;
    }


    /** Interface for iterating through all classes and their class
     loaders in dictionary */
    public static interface ClassAndLoaderVisitor {
        public void visit(Klass k, Oop loader);
    }

    /** Iterate over all klasses - including object, primitive
     array klasses */
    public void classesDo(ClassVisitor v) {
        for (ClassLoaderData cld = getClassLoaderGraphHead(); cld != null; cld = cld.next()) {
            cld.classesDo(v);
        }
    }
}
```

```cpp
// ClassLoaderDataGraph.cpp
// These functions assume that the caller has locked the ClassLoaderDataGraph_lock
// if they are not calling the function from a safepoint.
void ClassLoaderDataGraph::classes_do(KlassClosure* klass_closure) {
  ClassLoaderDataGraphIterator iter;
  while (ClassLoaderData* cld = iter.get_next()) {
    cld->classes_do(klass_closure);
  }
}


// ClassLoaderData.cpp
void ClassLoaderData::classes_do(KlassClosure* klass_closure) {
  // Lock-free access requires load_acquire
  for (Klass* k = OrderAccess::load_acquire(&_klasses); k != NULL; k = k->next_link()) {
    klass_closure->do_klass(k);
    assert(k != k->next_link(), "no loops!");
  }
}
```

## Oop

oopDesc is the top baseclass for objects classes. The Desc classes describe the format of Java objects so the fields can be accessed from C++.
oopDesc is abstract, and no virtual functions allowed.

### Oop Hierarchy

This hierarchy is a representation hierarchy, i.e.
if A is a superclass of B, A's representation is a prefix of B's representation.

<div style="text-align: center;">

```dot
strict digraph {
    oopDesc [shape="polygon" ]
    arrayOopDesc [shape="polygon" ]
    oopDesc -> arrayOopDesc 
    instanceOopDesc [shape="polygon" ]
    oopDesc -> instanceOopDesc
    objArrayOopDesc [shape="polygon" ]
    typeArrayOopDesc [shape="polygon" ]
    arrayOopDesc -> objArrayOopDesc
    arrayOopDesc -> typeArrayOopDesc
}
```
</div>


<p style="text-align: center;">
Fig.2. Oop hierarchy.
</p>


<div class="center">

| Type         | Java  |
| ------------ | ----- |
| instanceOop  | Obj   |
| objArrayOop  | Obj[] |
| typeArrayOop | []    |

</div>

### Oop struct

The layout of Oops is:

- [markWord](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=MarkWord)
- [Klass*](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=klass)    // 32 bits if compressed but declared 64 in LP64.
- length    // shares klass memory or allocated after declared fields if array Oop.

```cpp
class oopDesc {
 private:
  volatile markWord _mark;
  union _metadata {
    Klass*      _klass;
    narrowKlass _compressed_klass;
  } _metadata;
}
```


### MarkWord

The markOop describes the header of an object.

> [!NOTE]
>
> Note that the mark is not a real oop but just a word.
> It is placed in the oop hierarchy for historical reasons.

Bit-format of an object header (most significant first, big endian layout below):

```
 32 bits:
 --------
            hash:25 ------------>| age:4    biased_lock:1 lock:2 (normal object)
            JavaThread*:23 epoch:2 age:4    biased_lock:1 lock:2 (biased object)
            size:32 ------------------------------------------>| (CMS free block)
            PromotedObject*:29 ---------->| promo_bits:3 ----->| (CMS promoted object)

 64 bits:
 --------
 unused:25 hash:31 -->| unused:1   age:4    biased_lock:1 lock:2 (normal object)
 JavaThread*:54 epoch:2 unused:1   age:4    biased_lock:1 lock:2 (biased object)
PromotedObject*:61 --------------------->| promo_bits:3 ----->| (CMS promoted object)
size:64 ----------------------------------------------------->| (CMS free block)

unused:25 hash:31 -->| cms_free:1 age:4    biased_lock:1 lock:2 (COOPs && normal object)
JavaThread*:54 epoch:2 cms_free:1 age:4    biased_lock:1 lock:2 (COOPs && biased object)
narrowOop:32 unused:24 cms_free:1 unused:4 promo_bits:3 ----->| (COOPs && CMS promoted object)
unused:21 size:35 -->| cms_free:1 unused:7 ------------------>| (COOPs && CMS free block)
```

- hash contains the identity hash value: largest value is 31 bits, see os::random().  
  Also, 64-bit vm's require a hash value no bigger than 32 bits because they will not properly generate a mask larger than that: see library_call.cpp and c1_CodePatterns_sparc.cpp.(see [HashCode](/docs/CS/Java/JDK/Basic/Object.md?id=hashCode))
- the biased lock pattern is used to bias a lock toward a given thread.
  When this pattern is set in the low three bits, the lock is either biased toward a given thread or "anonymously" biased, indicating that it is possible for it to be biased. 
  When the lock is biased toward a given thread, locking and unlocking can be performed by that thread without using atomic operations.
  When a lock's bias is revoked, it reverts back to the normal locking scheme described below.

Note that we are overloading the meaning of the "unlocked" state of the header.
Because we steal a bit from the age we can guarantee that the bias pattern will never be seen for a truly unlocked object.

Note also that the biased state contains the age bits normally contained in the object header.
Large increases in scavenge times were seen when these bits were absent and an arbitrary age assigned to all biased objects, because they tended to consume a significant fraction of the eden semispaces and were not promoted promptly, causing an increase in the amount of copying performed.
The runtime system aligns all JavaThread* pointers to a very large value (currently 128 bytes (32bVM) or 256 bytes (64bVM)) to make room for the age bits & the epoch bits (used in support of biased locking), and for the CMS "freeness" bit in the 64bVM (+COOPs).

```
  [JavaThread* | epoch | age | 1 | 01]       lock is biased toward given thread
  [0           | epoch | age | 1 | 01]       lock is anonymously biased
```

- the two lock bits are used to describe three states: locked/unlocked and monitor.

```
  [ptr             | 00]  locked             ptr points to real header on stack
  [header      | 0 | 01]  unlocked           regular object header
  [ptr             | 10]  monitor            inflated lock (header is wapped out)
  [ptr             | 11]  marked             used by markSweep to mark an object not valid at any other time
```

We assume that stack/thread pointers have the lowest two bits cleared.

In JDK12, and now `markOopDesc` changed to `markWord`

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

```cpp
// share/oops/markWord.hpp
class markWord {
 private:
  uintptr_t _value;

 public:
  explicit markWord(uintptr_t value) : _value(value) {}

  markWord() = default;         // Doesn't initialize _value.
}
```

```shell
-XX:+UseCompressedOops
```


```hpp
// globals.hpp
product(intx, FieldsAllocationStyle, 1,                                     \
          "0 - type based with oops first, "                                \
          "1 - with oops last, "                                            \
          "2 - oops in super and sub classes are together")                 \
          range(0, 2)                                                       \
                                                                            \
product(bool, CompactFields, true,                                          \
          "Allocate nonstatic fields in gaps between previous fields")      \
```

64-bit padding for 8bytes

```hpp
lp64_product(intx, ObjectAlignmentInBytes, 8,                               \
          "Default object alignment in bytes, 8 is minimum")                \
          range(8, 256)                                                     \
          constraint(ObjectAlignmentInBytesConstraintFunc,AtParse)          \
```

if UseCompressedOops in 64-bit VM

```hpp

 lp64_product(bool, UseCompressedOops, false,                               \
          "Use 32-bit object references in 64-bit VM. "                     \
          "lp64_product means flag is always constant in 32 bit VM")        \
```

超过15 报错

```
-XX:MaxTenuringThreshold=15
```

access object use direct-pointer or handle

#### JOL

add JOL dependency.

```groovy
// https://mvnrepository.com/artifact/org.openjdk.jol/jol-core
compile group: 'org.openjdk.jol', name: 'jol-core', version: '0.13'
```

Print VM details.

```
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

Print object layout.

```
Object o = new Object();
System.out.println(ClassLayout.parseInstance(o).toPrintable());

String[] array = new String[]{"dfs", "fds", "ds", "fs"};
System.out.println(ClassLayout.parseInstance(array).toPrintable());
```

Output:

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



#### jhsdb




## Handle

In order to preserve oops during garbage collection, they should be allocated and passed around via Handles within the VM. A handle is simply an extra indirection allocated in a thread local handle area.
A handle is a value object, so it can be passed around as a value, can be used as a parameter w/o using &-passing, and can be returned as a return value.

oop parameters and return types should be Handles whenever feasible.


Handles are specialized for different oop types to provide extra type information and avoid unnecessary casting.
For each oop type xxxOop there is a corresponding handle called xxxHandle.

获取被封装的oop对象，并不会直接调用Handle对象的obj()或non_null_obj() 函数，而是通过C++的运算符重载来获取Handle类重载了()和->运算符

```c
class Handle {
 private:
  oop* _handle;

 protected:
  oop     obj() const                            { return _handle == nullptr ? (oop)nullptr : *_handle; }
  oop     non_null_obj() const                   { assert(_handle != nullptr, "resolving null handle"); return *_handle; }
 public:
  // Constructors
  Handle()                                       { _handle = nullptr; }
  inline Handle(Thread* thread, oop obj);

  // General access
  oop     operator () () const                   { return obj(); }
  oop     operator -> () const                   { return non_null_obj(); }
}
```

Handles are declared in a straight-forward manner, e.g.


```c
oop obj = ...;
Handle h2(thread, obj);      // allocate a new handle in thread
Handle h3;                   // declare handle only, no allocation occurs
...
h3 = h1;                     // make h3 refer to same indirection as h1
oop obj2 = h2();             // get handle value
h1->print();                 // invoking operation on oop
```

Handle被分配在本地线程的HandleArea中，这样在进行垃圾回收时只需要扫描每个线程的HandleArea即可找出所有Handle，进而找出所有引用的活跃对象

```c
// these inline functions are in a separate file to break an include cycle
// between Thread and Handle

inline Handle::Handle(Thread* thread, oop obj) {
  assert(thread == Thread::current(), "sanity check");
  if (obj == nullptr) {
    _handle = nullptr;
  } else {
    _handle = thread->handle_area()->allocate_handle(obj);
  }
}
```
在创建线程时初始化_handle_area属性，然后通过handle_area()函数获取该属性的值


```c
public:
oop* allocate_handle(oop obj) { return real_allocate_handle(obj); }
// Handle allocation
private:
oop* real_allocate_handle(oop obj) {
    oop* handle = (oop*)internal_amalloc(oopSize);
    *handle = obj;
    return handle;
}
```
句柄的释放要通过HandleMark来完成

```c
class HandleArea: public Arena {
friend class HandleMark;
friend class NoHandleMark;
friend class ResetNoHandleMark;
HandleArea* _prev;          // link to outer (older) area
};
```



```c
class Arena : public CHeapObjBase {
protected:
friend class HandleMark;
friend class NoHandleMark;
friend class VMStructs;

MEMFLAGS    _flags;           // Memory tracking flags

Chunk *_first;                // First chunk
Chunk *_chunk;                // current chunk
char *_hwm, *_max;            // High water mark and max in current chunk
// Get a new Chunk of at least size x
void* grow(size_t x, AllocFailType alloc_failmode = AllocFailStrategy::EXIT_OOM);
size_t _size_in_bytes;        // Size of arena (used for native memory tracking)

void* internal_amalloc(size_t x, AllocFailType alloc_failmode = AllocFailStrategy::EXIT_OOM)  {
    assert(is_aligned(x, BytesPerWord), "misaligned size");
    if (pointer_delta(_max, _hwm, 1) >= x) {
        char *old = _hwm;
        _hwm += x;
        return old;
    } else {
        return grow(x, alloc_failmode);
    }
}
};
```



```c

```



## Metadata

### Metadata hierarchy

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

- Klass
- Method
- MethodData
- MethodCounters
- ConstantPool

## Constant Pool

A ConstantPool is an **array** containing class constants as described in the class file.

Most of the constant pool entries are written during [class parsing](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=parse_stream), which is safe.
For klass types, the constant pool entry is modified when the entry is resolved.
If a klass constant pool entry is read without a lock, only the resolved state guarantees that the entry in the constant pool is a klass object and not a Symbol*.

```cpp

class ConstantPool : public Metadata {
 private:
  // If you add a new field that points to any metaspace object, you
  // must add this field to ConstantPool::metaspace_pointers_do().
  Array<u1>*           _tags;        // the tag array describing the constant pool's contents
  ConstantPoolCache*   _cache;       // the cache holding interpreter runtime information
  InstanceKlass*       _pool_holder; // the corresponding class
  Array<u2>*           _operands;    // for variable-sized (InvokeDynamic) nodes, usually empty

  // Consider using an array of compressed klass pointers to
  // save space on 64-bit platforms.
  Array<Klass*>*       _resolved_klasses;

  u2              _major_version;        // major version number of class file
  u2              _minor_version;        // minor version number of class file

  // Constant pool index to the utf8 entry of the Generic signature,
  // or 0 if none.
  u2              _generic_signature_index;
  // Constant pool index to the utf8 entry for the name of source file
  // containing this klass, 0 if not specified.
  u2              _source_file_name_index;

  enum {
    _has_preresolution    = 1,       // Flags
    _on_stack             = 2,
    _is_shared            = 4,
    _has_dynamic_constant = 8
  };
}  
```

parse_constant_pool ->
allocate

```cpp
// constantPool.cpp
ConstantPool* ConstantPool::allocate(ClassLoaderData* loader_data, int length, TRAPS) {
  Array<u1>* tags = MetadataFactory::new_array<u1>(loader_data, length, 0, CHECK_NULL);
  int size = ConstantPool::size(length);
  return new (loader_data, size, MetaspaceObj::ConstantPoolType, THREAD) ConstantPool(tags);
}
```

### Cache

A constant pool cache is a runtime data structure set aside to a constant pool.
The cache holds interpreter runtime information for all field access and invoke bytecodes.
The cache is created and initialized before a class is actively used (i.e., initialized), the individual cache entries are filled at resolution (i.e., "link") time (see also: rewriter.*).

`ConstantPool::resolved_references_or_null()`

## Handle


```cpp
class Handle {
 private:
  oop* _handle;

 protected:
  oop     obj() const                            { return _handle == NULL ? (oop)NULL : *_handle; }
  oop     non_null_obj() const                   { assert(_handle != NULL, "resolving NULL handle"); return *_handle; }
}
```


```cpp
class OopHandle {
private:
  oop* _obj;

public:
  OopHandle() : _obj(NULL) {}
  explicit OopHandle(oop* w) : _obj(w) {}
  OopHandle(OopStorage* storage, oop obj);

  OopHandle(const OopHandle& copy) : _obj(copy._obj) {}
}  
```

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Class File and Compiler](/docs/CS/Java/JDK/JVM/ClassFile.md)

## References
