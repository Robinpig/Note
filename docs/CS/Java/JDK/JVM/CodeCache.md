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

## CodeBlob

CodeBlob - superclass for all entries in the CodeCache.

```
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

## init

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

Enables segmentation of the code cache, without which the code cache consists of one large segment.
With `-XX:+SegmentedCodeCache`, separate segments will be used for non\-method, profiled method, and non\-profiled method code.
The segments are not resized at runtime.
The advantages are better control of the memory footprint, reduced code fragmentation, and better CPU iTLB (instruction translation lookaside buffer) and instruction cache behavior due to improved locality.
(see [JEP 197: Segmented Code Cache](https://openjdk.java.net/jeps/197))

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

### initialize_heaps

```cpp

void CodeCache::initialize_heaps() {
  bool non_nmethod_set      = FLAG_IS_CMDLINE(NonNMethodCodeHeapSize);
  bool profiled_set         = FLAG_IS_CMDLINE(ProfiledCodeHeapSize);
  bool non_profiled_set     = FLAG_IS_CMDLINE(NonProfiledCodeHeapSize);
  size_t min_size           = os::vm_page_size();
  size_t cache_size         = ReservedCodeCacheSize;
  size_t non_nmethod_size   = NonNMethodCodeHeapSize;
  size_t profiled_size      = ProfiledCodeHeapSize;
  size_t non_profiled_size  = NonProfiledCodeHeapSize;
  // Check if total size set via command line flags exceeds the reserved size
  check_heap_sizes((non_nmethod_set  ? non_nmethod_size  : min_size),
                   (profiled_set     ? profiled_size     : min_size),
                   (non_profiled_set ? non_profiled_size : min_size),
                   cache_size,
                   non_nmethod_set && profiled_set && non_profiled_set);

  // Determine size of compiler buffers
  size_t code_buffers_size = 0;
#ifdef COMPILER1
  // C1 temporary code buffers (see Compiler::init_buffer_blob())
  const int c1_count = CompilationPolicy::c1_count();
  code_buffers_size += c1_count * Compiler::code_buffer_size();
#endif
#ifdef COMPILER2
  // C2 scratch buffers (see Compile::init_scratch_buffer_blob())
  const int c2_count = CompilationPolicy::c2_count();
  // Initial size of constant table (this may be increased if a compiled method needs more space)
  code_buffers_size += c2_count * C2Compiler::initial_code_buffer_size();
#endif

  // Increase default non_nmethod_size to account for compiler buffers
  if (!non_nmethod_set) {
    non_nmethod_size += code_buffers_size;
  }
  // Calculate default CodeHeap sizes if not set by user
  if (!non_nmethod_set && !profiled_set && !non_profiled_set) {
    // Check if we have enough space for the non-nmethod code heap
    if (cache_size > non_nmethod_size) {
      // Use the default value for non_nmethod_size and one half of the
      // remaining size for non-profiled and one half for profiled methods
      size_t remaining_size = cache_size - non_nmethod_size;
      profiled_size = remaining_size / 2;
      non_profiled_size = remaining_size - profiled_size;
    } else {
      // Use all space for the non-nmethod heap and set other heaps to minimal size
      non_nmethod_size = cache_size - 2 * min_size;
      profiled_size = min_size;
      non_profiled_size = min_size;
    }
  } else if (!non_nmethod_set || !profiled_set || !non_profiled_set) {
    // The user explicitly set some code heap sizes. Increase or decrease the (default)
    // sizes of the other code heaps accordingly. First adapt non-profiled and profiled
    // code heap sizes and then only change non-nmethod code heap size if still necessary.
    intx diff_size = cache_size - (non_nmethod_size + profiled_size + non_profiled_size);
    if (non_profiled_set) {
      if (!profiled_set) {
        // Adapt size of profiled code heap
        if (diff_size < 0 && ((intx)profiled_size + diff_size) <= 0) {
          // Not enough space available, set to minimum size
          diff_size += profiled_size - min_size;
          profiled_size = min_size;
        } else {
          profiled_size += diff_size;
          diff_size = 0;
        }
      }
    } else if (profiled_set) {
      // Adapt size of non-profiled code heap
      if (diff_size < 0 && ((intx)non_profiled_size + diff_size) <= 0) {
        // Not enough space available, set to minimum size
        diff_size += non_profiled_size - min_size;
        non_profiled_size = min_size;
      } else {
        non_profiled_size += diff_size;
        diff_size = 0;
      }
    } else if (non_nmethod_set) {
      // Distribute remaining size between profiled and non-profiled code heaps
      diff_size = cache_size - non_nmethod_size;
      profiled_size = diff_size / 2;
      non_profiled_size = diff_size - profiled_size;
      diff_size = 0;
    }
    if (diff_size != 0) {
      // Use non-nmethod code heap for remaining space requirements
      assert(!non_nmethod_set && ((intx)non_nmethod_size + diff_size) > 0, "sanity");
      non_nmethod_size += diff_size;
    }
  }

  // We do not need the profiled CodeHeap, use all space for the non-profiled CodeHeap
  if (!heap_available(CodeBlobType::MethodProfiled)) {
    non_profiled_size += profiled_size;
    profiled_size = 0;
  }
  // We do not need the non-profiled CodeHeap, use all space for the non-nmethod CodeHeap
  if (!heap_available(CodeBlobType::MethodNonProfiled)) {
    non_nmethod_size += non_profiled_size;
    non_profiled_size = 0;
  }
  // Make sure we have enough space for VM internal code
  uint min_code_cache_size = CodeCacheMinimumUseSpace DEBUG_ONLY(* 3);
  if (non_nmethod_size < min_code_cache_size) {
    vm_exit_during_initialization(err_msg(
        "Not enough space in non-nmethod code heap to run VM: " SIZE_FORMAT "K < " SIZE_FORMAT "K",
        non_nmethod_size/K, min_code_cache_size/K));
  }

  // Verify sizes and update flag values
  assert(non_profiled_size + profiled_size + non_nmethod_size == cache_size, "Invalid code heap sizes");
  FLAG_SET_ERGO(NonNMethodCodeHeapSize, non_nmethod_size);
  FLAG_SET_ERGO(ProfiledCodeHeapSize, profiled_size);
  FLAG_SET_ERGO(NonProfiledCodeHeapSize, non_profiled_size);

  // If large page support is enabled, align code heaps according to large
  // page size to make sure that code cache is covered by large pages.
  const size_t alignment = MAX2(page_size(false, 8), (size_t) os::vm_allocation_granularity());
  non_nmethod_size = align_up(non_nmethod_size, alignment);
  profiled_size    = align_down(profiled_size, alignment);

  // Reserve one continuous chunk of memory for CodeHeaps and split it into
  // parts for the individual heaps. The memory layout looks like this:
  // ---------- high -----------
  //    Non-profiled nmethods
  //      Profiled nmethods
  //         Non-nmethods
  // ---------- low ------------
  ReservedCodeSpace rs = reserve_heap_memory(cache_size);
  ReservedSpace non_method_space    = rs.first_part(non_nmethod_size);
  ReservedSpace rest                = rs.last_part(non_nmethod_size);
  ReservedSpace profiled_space      = rest.first_part(profiled_size);
  ReservedSpace non_profiled_space  = rest.last_part(profiled_size);

  // Non-nmethods (stubs, adapters, ...)
  add_heap(non_method_space, "CodeHeap 'non-nmethods'", CodeBlobType::NonNMethod);
  // Tier 2 and tier 3 (profiled) methods
  add_heap(profiled_space, "CodeHeap 'profiled nmethods'", CodeBlobType::MethodProfiled);
  // Tier 1 and tier 4 (non-profiled) methods and native methods
  add_heap(non_profiled_space, "CodeHeap 'non-profiled nmethods'", CodeBlobType::MethodNonProfiled);
}
```

```cpp

// For init.cpp
void icache_init() {
  ICache::initialize();
}


// share/runtime/icache.cpp
void AbstractICache::initialize() {
  // Making this stub must be FIRST use of assembler
  ResourceMark rm;

  BufferBlob* b = BufferBlob::create("flush_icache_stub", ICache::stub_size);
  if (b == NULL) {
    vm_exit_out_of_memory(ICache::stub_size, OOM_MALLOC_ERROR, "CodeCache: no space for flush_icache_stub");
  }
  CodeBuffer c(b);

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
#### generate_icache_flush
x86
```cpp
void ICacheStubGenerator::generate_icache_flush(ICache::flush_icache_stub_t* flush_icache_stub) {
  StubCodeMark mark(this, "ICache", "flush_icache_stub");

  address start = __ pc();
#ifdef AMD64

  const Register addr  = c_rarg0;
  const Register lines = c_rarg1;
  const Register magic = c_rarg2;

  Label flush_line, done;

  __ testl(lines, lines);
  __ jcc(Assembler::zero, done);

  // Force ordering wrt cflush.
  // Other fence and sync instructions won't do the job.
  __ mfence();

  __ bind(flush_line);
  __ clflush(Address(addr, 0));
  __ addptr(addr, ICache::line_size);
  __ decrementl(lines);
  __ jcc(Assembler::notZero, flush_line);

  __ mfence();

  __ bind(done);

#else
  const Address magic(rsp, 3*wordSize);
  __ lock(); __ addl(Address(rsp, 0), 0);
#endif // AMD64
  __ movptr(rax, magic); // Handshake with caller to make sure it happened!
  __ ret(0);

  // Must be set here so StubCodeMark destructor can call the flush stub.
  *flush_icache_stub = (ICache::flush_icache_stub_t)start;
}
```

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
