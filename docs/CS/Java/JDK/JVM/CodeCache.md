## Introduction

CodeCache 

CodeBlob Types

用于在 CodeCache 中将 CodeBlobs 分配到不同的 CodeHeaps

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

CodeBlob - CodeCache 中所有条目的超类。

```
子类型包括：
 CompiledMethod       : 编译的 Java 方法（包括调用 native code 的方法）
  nmethod             : JIT 编译的 Java 方法
 RuntimeBlob          : 非编译方法代码；生成的胶水代码
  BufferBlob          : 用于不可重定位代码，如 interpreter、stubroutines 等
   AdapterBlob        : 用于保存 C2I/I2C 适配器
   VtableBlob         : 用于保存 vtable 块
   MethodHandlesAdapterBlob : 用于保存 MethodHandles 适配器
   OptimizedEntryBlob : 用于从 native code 上行调用
  RuntimeStub         : 调用 VM 运行时方法
  SingletonBlob       : 只存在单一实例的所有 blob 的超类
   DeoptimizationBlob : 用于去优化
   ExceptionBlob      : 用于栈展开
   SafepointBlob      : 用于处理非法指令异常
   UncommonTrapBlob   : 用于处理 uncommon trap


布局：在 CodeCache 中连续存放
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

启用代码缓存分段，没有此选项时代码缓存由一个大段组成。
使用 `-XX:+SegmentedCodeCache` 后，将为 non-method、profiled method 和 non-profiled method 代码使用独立的段。
这些段在运行时不会调整大小。
其优点是更好地控制内存占用、减少代码碎片，以及由于改进的局部性而带来更好的 CPU iTLB（指令转换后备缓冲区）和指令缓存行为。
（参见 [JEP 197: Segmented Code Cache](https://openjdk.java.net/jeps/197)）

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

用于更新指令缓存的接口。
每当 VM 修改代码时，处理器指令缓存的部分可能需要刷新。
此实现为空：Zero 从不处理代码。

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

## Tuning


监控 > 2%告警

编译类太多

服务每次发布/重启后都会短暂地出现CPU满线程池满的情况，然后过一段时间又能自动恢复
排查后发现是启动时JVM将部分热点代码编译为机器代码导致的，这个过程中JIT编译器会占用大量的CPU



Code Cache的增长过程就像ArrayList一样，一开始分配一个初始的大小，此后随着越来越多的代码被编译为机器码，code cache不够用了之后，就会引发扩容
默认的初始大小是2496KB，最大大小是240MB，二者可分别通过JVM参数-XX:InitialCodeCacheSize=N和-XX:ReservedCodeCacheSize=N进行设定。
自Java 9开始，Code Cache的管理被分为了三个区域：
- non-method segment：存储JVM内部代码，大小可使用-XX:NonNMethodCodeHeapSize参数配置；
- profiled-code segment：C1编译后的代码，特点是生命周期较短（随时都有可能升级到C2编译），大小可使用-XX:ProfiledCodeHeapSize参数配置；
- non-profiled segment：C2编译后的代码，特点是生命周期较长（因为极少发生反优化降级），大小可使用-XX:NonProfiledCodeHeapSize参数配置；

Code Cache分区的好处是降低内存碎片的产生，提高运行效率










## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
