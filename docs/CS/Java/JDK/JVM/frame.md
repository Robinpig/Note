## Introduction


## Stack

```
StackRedPages                             = 1   
StackShadowPages                          = 20  
StackTraceInThrowable                     = true
StackYellowPages                          = 2   
```

### vframe

vframe 是表示源码级别 activations 的虚拟栈帧。
在优化代码的情况下，单个帧可能包含多个源码级别的 activations。
与优化代码一起存储的调试信息使我们能够将帧展开为 vframes 栈。

cVFrame 表示非 Java 方法的 activation。

vframe 继承层次结构：
- vframe
    - javaVFrame
        - interpretedVFrame
        - compiledVFrame     ; （用于编译的 Java 方法和 native stubs）
    - externalVFrame
        - entryVFrame        ; 从 C 调用 Java 时创建的特殊帧
    - BasicLock


内存分配管理


默认分配在资源区的对象的基类。
可选地，对象可以分配到 C 堆（new (AnyObj::C_HEAP) Foo(...)）或 Arena（new (&arena) Foo(...)）中。
AnyObj 可以分配到其他对象中，但不要使用 new 或 delete 来分配（allocation_type 未知）。如果用 new 配置，使用 delete 来释放。

```cpp
class AnyObj {
 public:
  enum allocation_type { STACK_OR_EMBEDDED = 0, RESOURCE_AREA, C_HEAP, ARENA, allocation_mask = 0x3 };
 }
```



```cpp
// vframe.hpp
class vframe: public ResourceObj {
 protected:
  frame        _fr;      // Raw frame behind the virtual frame.
  RegisterMap  _reg_map; // Register map for the raw frame (used to handle callee-saved registers).
  JavaThread*  _thread;  // The thread owning the raw frame.
}
```




frame 表示一个物理栈帧（一个 activation）。
帧可以是 C 帧或 Java 帧，Java 帧可以是解释帧或编译帧。

相比之下，vframe 表示源码级别的 activations，
因此由于内联，一个物理帧可能对应多个源码级别的帧。

```cpp
// frame.hpp
class frame {
 private:
  // Instance variables:
  intptr_t* _sp; // stack pointer (from Thread::last_Java_sp)
  address   _pc; // program counter (the next instruction after the call)

  CodeBlob* _cb; // CodeBlob that "owns" pc
  enum deopt_state {
    not_deoptimized,
    is_deoptimized,
    unknown
  };

  deopt_state _deopt_state;
  
```

CPU_HEADER 关联到 `frame_<CPU_arch>.hpp`，例如 frame_x86.hpp
```
#include CPU_HEADER(frame)
}
```



```cpp
// frame.hpp
void oops_do(OopClosure* f, CodeBlobClosure* cf, RegisterMap* map) { oops_do_internal(f, cf, map, true); }

// frame.cpp
void frame::oops_do_internal(OopClosure* f, CodeBlobClosure* cf, RegisterMap* map, bool use_interpreter_oop_map_cache) {
#ifndef PRODUCT
#if defined(__SUNPRO_CC) && __SUNPRO_CC >= 0x5140
#pragma error_messages(off, SEC_NULL_PTR_DEREF)
#endif
  // simulate GC crash here to dump java thread in error report
  if (CrashGCForDumpingJavaThread) {
    char *t = NULL;
    *t = 'c';
  }
#endif
  if (is_interpreted_frame()) {
    oops_interpreted_do(f, map, use_interpreter_oop_map_cache);
  } else if (is_entry_frame()) {    // call_stub
    oops_entry_do(f, map);
  } else if (CodeCache::contains(pc())) {
    oops_code_blob_do(f, cf, map);
  } else {
    ShouldNotReachHere();
  }
}
```


