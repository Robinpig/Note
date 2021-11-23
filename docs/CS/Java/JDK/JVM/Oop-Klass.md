## Introduction

One reason for the oop/klass dichotomy in the implementation is that we don't want a C++ vtbl pointer in every object. Thus, normal oops don't have any virtual functions. Instead, they forward all "virtual" functions to their klass, which does have a vtbl and does the C++ dispatch depending on the object's actual type. (See oop.inline.hpp for some of the forwarding code.)



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

## oop


#### InstanceKlass::allocate_instance


```cpp
instanceOop InstanceKlass::allocate_instance(TRAPS) {
  bool has_finalizer_flag = has_finalizer(); // Query before possible GC
  int size = size_helper();  // Query before forming handle.

  instanceOop i;

  i = (instanceOop)Universe::heap()->obj_allocate(this, size, CHECK_NULL);
  if (has_finalizer_flag && !RegisterFinalizersAtInit) {
    i = register_finalizer(i, CHECK_NULL);
  }
  return i;
}
```


```cpp
// collectedHeap.cpp
oop CollectedHeap::obj_allocate(Klass* klass, int size, TRAPS) {
  ObjAllocator allocator(klass, size, THREAD);
  return allocator.allocate();
}
```



```cpp
// shenandoahHeap.cpp
oop ShenandoahHeap::obj_allocate(Klass* klass, int size, TRAPS) {
  ObjAllocator initializer(klass, size, THREAD);
  ShenandoahMemAllocator allocator(initializer, klass, size, THREAD);
  return allocator.allocate();
}
```


also allow use TLAB
```cpp
// memAllocator.cpp
oop MemAllocator::allocate() const {
  oop obj = NULL;
  {
    Allocation allocation(*this, &obj);
    HeapWord* mem = mem_allocate(allocation);
    if (mem != NULL) {
      obj = initialize(mem); // clear_mem & set markOop
    }
  }
  return obj;
}

HeapWord* MemAllocator::mem_allocate(Allocation& allocation) const {
  if (UseTLAB) {
    HeapWord* result = allocate_inside_tlab(allocation);
    if (result != NULL) {
      return result;
    }
  }

  return allocate_outside_tlab(allocation);
}
```


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

## 

```cpp
// MarkSweep.cpp
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


// The iteration over the oops in objects is a hot path in the GC code.
// By force inlining the following functions, we get similar GC performance
// as the previous macro based implementation.

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

### vtable

array 

-Xlog:vtables=trace

update_inherited_vtable

#### initialize_vtable
```cpp
// klassVtable.cpp
// Revised lookup semantics   introduced 1.3 (Kestrel beta)
void klassVtable::initialize_vtable(bool checkconstraints, TRAPS) {

  // Note:  Arrays can have intermediate array supers.  Use java_super to skip them.
  InstanceKlass* super = _klass->java_super();
  int nofNewEntries = 0;

  bool is_shared = _klass->is_shared();

  if (!_klass->is_array_klass()) {
    ResourceMark rm(THREAD);
    log_develop_debug(vtables)("Initializing: %s", _klass->name()->as_C_string());
  }

#ifdef ASSERT
  oop* end_of_obj = (oop*)_klass + _klass->size();
  oop* end_of_vtable = (oop*)&table()[_length];
  assert(end_of_vtable <= end_of_obj, "vtable extends beyond end");
#endif

  if (Universe::is_bootstrapping()) {
    assert(!is_shared, "sanity");
    // just clear everything
    for (int i = 0; i < _length; i++) table()[i].clear();
    return;
  }

  int super_vtable_len = initialize_from_super(super);
  if (_klass->is_array_klass()) {
    assert(super_vtable_len == _length, "arrays shouldn't introduce new methods");
  } else {
    assert(_klass->is_instance_klass(), "must be InstanceKlass");

    Array<Method*>* methods = ik()->methods();
    int len = methods->length();
    int initialized = super_vtable_len;

    // Check each of this class's methods against super;
    // if override, replace in copy of super vtable, otherwise append to end
    for (int i = 0; i < len; i++) {
      // update_inherited_vtable can stop for gc - ensure using handles
      HandleMark hm(THREAD);
      assert(methods->at(i)->is_method(), "must be a Method*");
      methodHandle mh(THREAD, methods->at(i));

      bool needs_new_entry = update_inherited_vtable(ik(), mh, super_vtable_len, -1, checkconstraints, CHECK);

      if (needs_new_entry) {
        put_method_at(mh(), initialized);
        mh()->set_vtable_index(initialized); // set primary vtable index
        initialized++;
      }
    }

    // update vtable with default_methods
    Array<Method*>* default_methods = ik()->default_methods();
    if (default_methods != NULL) {
      len = default_methods->length();
      if (len > 0) {
        Array<int>* def_vtable_indices = NULL;
        if ((def_vtable_indices = ik()->default_vtable_indices()) == NULL) {
          assert(!is_shared, "shared class def_vtable_indices does not exist");
          def_vtable_indices = ik()->create_new_default_vtable_indices(len, CHECK);
        } else {
          assert(def_vtable_indices->length() == len, "reinit vtable len?");
        }
        for (int i = 0; i < len; i++) {
          HandleMark hm(THREAD);
          assert(default_methods->at(i)->is_method(), "must be a Method*");
          methodHandle mh(THREAD, default_methods->at(i));
          assert(!mh->is_private(), "private interface method in the default method list");
          bool needs_new_entry = update_inherited_vtable(ik(), mh, super_vtable_len, i, checkconstraints, CHECK);

          // needs new entry
          if (needs_new_entry) {
            put_method_at(mh(), initialized);
            if (is_preinitialized_vtable()) {
              // At runtime initialize_vtable is rerun for a shared class
              // (loaded by the non-boot loader) as part of link_class_impl().
              // The dumptime vtable index should be the same as the runtime index.
              assert(def_vtable_indices->at(i) == initialized,
                     "dump time vtable index is different from runtime index");
            } else {
              def_vtable_indices->at_put(i, initialized); //set vtable index
            }
            initialized++;
          }
        }
      }
    }

    // add miranda methods; it will also return the updated initialized
    // Interfaces do not need interface methods in their vtables
    // This includes miranda methods and during later processing, default methods
    if (!ik()->is_interface()) {
      initialized = fill_in_mirandas(initialized, THREAD);
    }

    // In class hierarchies where the accessibility is not increasing (i.e., going from private ->
    // package_private -> public/protected), the vtable might actually be smaller than our initial
    // calculation, for classfile versions for which we do not do transitive override
    // calculations.
    if (ik()->major_version() >= VTABLE_TRANSITIVE_OVERRIDE_VERSION) {
      assert(initialized == _length, "vtable initialization failed");
    } else {
      assert(initialized <= _length, "vtable initialization failed");
      for(;initialized < _length; initialized++) {
        table()[initialized].clear();
      }
    }
    NOT_PRODUCT(verify(tty, true));
  }
}
```



Update child's copy of super vtable for overrides
OR return true if a new vtable entry is required.
Only called for InstanceKlass's, i.e. not for arrays
If that changed, could not use _klass as handle for klass




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