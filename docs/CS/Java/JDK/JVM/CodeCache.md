## Introduction




CodeBlob Types
Used in the CodeCache to assign CodeBlobs to different CodeHeaps
```cpp
// 
struct CodeBlobType {
  enum {
    MethodNonProfiled   = 0,    // Execution level 1 and 4 (non-profiled) nmethods (including native nmethods)
    MethodProfiled      = 1,    // Execution level 2 and 3 (profiled) nmethods
    NonNMethod          = 2,    // Non-nmethods like Buffers, Adapters and Runtime Stubs
    All                 = 3,    // All types (No code cache segmentation)
    NumTypes            = 4     // Number of CodeBlobTypes
  };
};
```


```
CodeBlob - superclass for all entries in the CodeCache.

Subtypes are:
 CompiledMethod       : Compiled Java methods (include method that calls to native code)
  nmethod             : JIT Compiled Java methods
 RuntimeBlob          : Non-compiled method code; generated glue code
  BufferBlob          : Used for non-relocatable code such as interpreter, stubroutines, etc.
   AdapterBlob        : Used to hold C2I/I2C adapters
   VtableBlob         : Used for holding vtable chunks
   MethodHandlesAdapterBlob : Used to hold MethodHandles adapters
   OptimizedEntryBlob : Used for upcalls from native code
  RuntimeStub         : Call to VM runtime methods
  SingletonBlob       : Super-class for all blobs that exist in only one instance
   DeoptimizationBlob : Used for deoptimization
   ExceptionBlob      : Used for stack unrolling
   SafepointBlob      : Used to handle illegal instruction exceptions
   UncommonTrapBlob   : Used to handle uncommon traps


Layout : continuous in the CodeCache
  - header
  - relocation
  - content space
    - instruction space
  - data space
```


### init
init when [start vm](/docs/CS/Java/JDK/JVM/start.md?id=init_globals)

```cpp
// 
void CodeCache::initialize() {
  assert(CodeCacheSegmentSize >= (uintx)CodeEntryAlignment, "CodeCacheSegmentSize must be large enough to align entry points");
#ifdef COMPILER2
  assert(CodeCacheSegmentSize >= (uintx)OptoLoopAlignment,  "CodeCacheSegmentSize must be large enough to align inner loops");
#endif
  assert(CodeCacheSegmentSize >= sizeof(jdouble),    "CodeCacheSegmentSize must be large enough to align constants");
  // This was originally just a check of the alignment, causing failure, instead, round
  // the code cache to the page size.  In particular, Solaris is moving to a larger
  // default page size.
  CodeCacheExpansionSize = align_up(CodeCacheExpansionSize, os::vm_page_size());
```

see [JEP 197: Segmented Code Cache](https://openjdk.java.net/jeps/197)

```cpp
  if (SegmentedCodeCache) {
    // Use multiple code heaps
    initialize_heaps();
  } else {
    // Use a single code heap
    FLAG_SET_ERGO(NonNMethodCodeHeapSize, 0);
    FLAG_SET_ERGO(ProfiledCodeHeapSize, 0);
    FLAG_SET_ERGO(NonProfiledCodeHeapSize, 0);
    ReservedCodeSpace rs = reserve_heap_memory(ReservedCodeCacheSize);
    add_heap(rs, "CodeCache", CodeBlobType::All);
  }

  // Initialize ICache flush mechanism
  // This service is needed for os::register_code_area
  icache_init();

  // Give OS a chance to register generated code area.
  // This is used on Windows 64 bit platforms to register
  // Structured Exception Handlers for our generated code.
  os::register_code_area((char*)low_bound(), (char*)high_bound());
}
```


```cpp
// For init.cpp
void icache_init() {
  ICache::initialize();
}
```

Interface for updating the instruction cache.  
Whenever the VM modifies code, part of the processor instruction cache potentially has to be flushed.  
This implementation is empty: Zero never deals with code.

```
class ICache : public AbstractICache {
 public:
  static void initialize() {}
  static void invalidate_word(address addr) {}
  static void invalidate_range(address start, int nbytes) {}
};


void AbstractICache::initialize() {
  // Making this stub must be FIRST use of assembler
  ResourceMark rm;

  BufferBlob* b = BufferBlob::create("flush_icache_stub", ICache::stub_size);
  if (b == NULL) {
    vm_exit_out_of_memory(ICache::stub_size, OOM_MALLOC_ERROR, "CodeCache: no space for flush_icache_stub");
  }
  CodeBuffer c(b);
```
generate_icache_flush implemented by different arch `ICacheStubGenerator::generate_icache_flush()`
```
  ICacheStubGenerator g(&c);
  g.generate_icache_flush(&_flush_icache_stub);

  // The first use of flush_icache_stub must apply it to itself.
  // The StubCodeMark destructor in generate_icache_flush will
  // call Assembler::flush, which in turn will call invalidate_range,
  // which will in turn call the flush stub.  Thus we don't need an
  // explicit call to invalidate_range here.  This assumption is
  // checked in invalidate_range.
}
```



## Links
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)