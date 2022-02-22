## Introduction


## Stack

```
StackRedPages                             = 1   
StackShadowPages                          = 20  
StackTraceInThrowable                     = true
StackYellowPages                          = 2   
```

### vframe
vframes are virtual stack frames representing source level activations.
A single frame may hold several source level activations in the case of optimized code.
The debugging stored with the optimized code enables us to unfold a frame as a stack of vframes.

A cVFrame represents an activation of a non-java method.

The vframe inheritance hierarchy:
- vframe
    - javaVFrame
        - interpretedVFrame
        - compiledVFrame     ; (used for both compiled Java methods and native stubs)
    - externalVFrame
        - entryVFrame        ; special frame created when calling Java from C
    - BasicLock
```cpp
// vframe.hpp
class vframe: public ResourceObj {
 protected:
  frame        _fr;      // Raw frame behind the virtual frame.
  RegisterMap  _reg_map; // Register map for the raw frame (used to handle callee-saved registers).
  JavaThread*  _thread;  // The thread owning the raw frame.
}
```




A frame represents a physical stack frame (an activation).  
Frames can be C or Java frames, and the Java frames can be interpreted or compiled.

In contrast, vframes represent source-level activations,
so that one physical frame can correspond to multiple source level frames because of inlining.

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

CPU_HEADER associate to `frame_<CPU_arch>.hpp`, such as frame_x86.hpp
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


