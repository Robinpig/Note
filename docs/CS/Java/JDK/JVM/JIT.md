## Overview

OpenJDK is a three tiered compilation environment.
Methods that are only executed a few times are interpreted.
Once a method hits a certain threshold of executions it is compiled using a text book style compiler called C1.
Only when the method has hit an even higher threshold of executions will it be compiled using C2, the optimizing compiler.

The JVM interprets and executes bytecode at runtime. In addition, it makes use of the just-in-time (JIT) compilation to boost performance.

In earlier versions of Java, we had to manually choose between the two types of JIT compilers available in the Hotspot JVM. 
One is optimized for faster application start-up, while the other achieves better overall performance.
Java 7 introduced tiered compilation in order to achieve the best of both worlds.

A JIT compiler compiles bytecode to native code for frequently executed sections.
These sections are called hotspots, hence the name Hotspot JVM.
As a result, Java can run with similar performance to a fully compiled language.
Let's look at the two types of JIT compilers available in the JVM.

The system supports 5 execution levels:

* level 0 - interpreter (Profiling is tracked by a MethodData object, or MDO in short)
* level 1 - C1 with full optimization (no profiling)
* level 2 - C1 with invocation and backedge counters
* level 3 - C1 with full profiling (level 2 + All other MDO profiling information)
* level 4 - C2 with full profile guided optimization

C1 – Client Compiler

The client compiler, also called C1, is a type of a JIT compiler optimized for faster start-up time. 
It tries to optimize and compile the code as soon as possible.

Historically, we used C1 for short-lived applications and applications where start-up time was an important non-functional requirement. 
Prior to Java 8, we had to specify the -client flag to use the C1 compiler. However, if we use Java 8 or higher, this flag will have no effect.

C2 – Server Compiler

The server compiler, also called C2(Opto), is a type of a JIT compiler optimized for better overall performance. 
C2 observes and analyzes the code over a longer period of time compared to C1. This allows C2 to make better optimizations in the compiled code.

Historically, we used C2 for long-running server-side applications. 
Prior to Java 8, we had to specify the -server flag to use the C2 compiler. However, this flag will have no effect in Java 8 or higher.

We should note that the Graal JIT compiler is also available since Java 10, as an alternative to C2. Unlike C2, Graal can run in both just-in-time and ahead-of-time compilation modes to produce

## Init



### compilationPolicy_init

编译策略通常由CompilationPolicy来表示，CompilationPolicy是选择哪个方法要用什么程度优化的抽象层。此类的继承体系如下
在创建虚拟机时 `init_global()` 会调用compilationPolicy_init()函数


```cpp
void compilationPolicy_init() {
  CompilationPolicy::initialize();
}


void CompilationPolicy::initialize() {
  if (!CompilerConfig::is_interpreter_only()) {
    int count = CICompilerCount;
    bool c1_only = CompilerConfig::is_c1_only();
    bool c2_only = CompilerConfig::is_c2_or_jvmci_compiler_only();

#ifdef _LP64
    // Turn on ergonomic compiler count selection
    if (FLAG_IS_DEFAULT(CICompilerCountPerCPU) && FLAG_IS_DEFAULT(CICompilerCount)) {
      FLAG_SET_DEFAULT(CICompilerCountPerCPU, true);
    }
    if (CICompilerCountPerCPU) {
      // Simple log n seems to grow too slowly for tiered, try something faster: log n * log log n
      int log_cpu = log2i(os::active_processor_count());
      int loglog_cpu = log2i(MAX2(log_cpu, 1));
      count = MAX2(log_cpu * loglog_cpu * 3 / 2, 2);
      // Make sure there is enough space in the code cache to hold all the compiler buffers
      size_t c1_size = 0;
#ifdef COMPILER1
      c1_size = Compiler::code_buffer_size();
#endif
      size_t c2_size = 0;
#ifdef COMPILER2
      c2_size = C2Compiler::initial_code_buffer_size();
#endif
      size_t buffer_size = c1_only ? c1_size : (c1_size/3 + 2*c2_size/3);
      int max_count = (ReservedCodeCacheSize - (CodeCacheMinimumUseSpace DEBUG_ONLY(* 3))) / (int)buffer_size;
      if (count > max_count) {
        // Lower the compiler count such that all buffers fit into the code cache
        count = MAX2(max_count, c1_only ? 1 : 2);
      }
      FLAG_SET_ERGO(CICompilerCount, count);
    }
#endif

    if (c1_only) {
      // No C2 compiler thread required
      set_c1_count(count);
    } else if (c2_only) {
      set_c2_count(count);
    } else {
        set_c1_count(MAX2(count / 3, 1));
        set_c2_count(MAX2(count - c1_count(), 1));
    }
    assert(count == c1_count() + c2_count(), "inconsistent compiler thread count");
    set_increase_threshold_at_ratio();
  }
  set_start_time(nanos_to_millis(os::javaTimeNanos()));
}
```



在64位JVM中，有2种情况来计算总的编译线程数，如下：

- -XX:+CICompilerCountPerCPU=true， 默认情况下，编译线程的总数根据处理器数量来调整；
- -XX:+CICompilerCountPerCPU=false且-XX:+CICompilerCount=N，强制设定总编译线程数。

无论以上哪种情况，HotSpot VM都会将这些编译线程按照1:2的比例分配给C1和C2（至少1个），举个例子，对于一个四核机器来说，总的编译线程数目为 3，其中包含一个 C1 编译线程和两个 C2 编译线程。

设置完成编译器线程数量后，会在创建虚拟机实例时 `Threads::create_vm` 调用CompileBroker::compilation_init_phase1()函数初始化编译相关组件，包括编译器实现，编译线程，计数器等

```cpp
void CompileBroker::compilation_init_phase1(JavaThread* THREAD) {
  // No need to initialize compilation system if we do not use it.
  if (!UseCompiler) {
    return;
  }
  // Set the interface to the current compiler(s).
  _c1_count = CompilationPolicy::c1_count();
  _c2_count = CompilationPolicy::c2_count();


#ifdef COMPILER1
  if (_c1_count > 0) {
    _compilers[0] = new Compiler();
  }
#endif // COMPILER1

#ifdef COMPILER2
  if (true JVMCI_ONLY( && !UseJVMCICompiler)) {
    if (_c2_count > 0) {
      _compilers[1] = new C2Compiler();
      // Register c2 first as c2 CompilerPhaseType idToPhase mapping is explicit.
      // idToPhase mapping for c2 is in opto/phasetype.hpp
      JFR_ONLY(register_jfr_phasetype_serializer(compiler_c2);)
    }
  }
#endif // COMPILER2

  // Start the compiler thread(s)
  init_compiler_threads();
  // totalTime performance counter is always created as it is required
  // by the implementation of java.lang.management.CompilationMXBean.
  {
    // Ensure OOM leads to vm_exit_during_initialization.
    EXCEPTION_MARK;
    _perf_total_compilation =
                 PerfDataManager::create_counter(JAVA_CI, "totalTime",
                                                 PerfData::U_Ticks, CHECK);
  }

}
```





### init_compiler_threads

```cpp
void CompileBroker::init_compiler_threads() {
  // Ensure any exceptions lead to vm_exit_during_initialization.
  EXCEPTION_MARK;
#if !defined(ZERO)
  assert(_c2_count > 0 || _c1_count > 0, "No compilers?");
#endif // !ZERO
  // Initialize the compilation queue
  if (_c2_count > 0) {
    const char* name = JVMCI_ONLY(UseJVMCICompiler ? "JVMCI compile queue" :) "C2 compile queue";
    _c2_compile_queue  = new CompileQueue(name);
    _compiler2_objects = NEW_C_HEAP_ARRAY(jobject, _c2_count, mtCompiler);
    _compiler2_logs = NEW_C_HEAP_ARRAY(CompileLog*, _c2_count, mtCompiler);
  }
  if (_c1_count > 0) {
    _c1_compile_queue  = new CompileQueue("C1 compile queue");
    _compiler1_objects = NEW_C_HEAP_ARRAY(jobject, _c1_count, mtCompiler);
    _compiler1_logs = NEW_C_HEAP_ARRAY(CompileLog*, _c1_count, mtCompiler);
  }

  char name_buffer[256];

  for (int i = 0; i < _c2_count; i++) {
    jobject thread_handle = nullptr;
    // Create all j.l.Thread objects for C1 and C2 threads here, but only one
    // for JVMCI compiler which can create further ones on demand.
    JVMCI_ONLY(if (!UseJVMCICompiler || !UseDynamicNumberOfCompilerThreads || i == 0) {)
    // Create a name for our thread.
    os::snprintf_checked(name_buffer, sizeof(name_buffer), "%s CompilerThread%d", _compilers[1]->name(), i);
    Handle thread_oop = create_thread_oop(name_buffer, CHECK);
    thread_handle = JNIHandles::make_global(thread_oop);
    JVMCI_ONLY(})
    _compiler2_objects[i] = thread_handle;
    _compiler2_logs[i] = nullptr;

    if (!UseDynamicNumberOfCompilerThreads || i == 0) {
      JavaThread *ct = make_thread(compiler_t, thread_handle, _c2_compile_queue, _compilers[1], THREAD);
      assert(ct != nullptr, "should have been handled for initial thread");
      _compilers[1]->set_num_compiler_threads(i + 1);
      if (trace_compiler_threads()) {
        ResourceMark rm;
        ThreadsListHandle tlh;  // name() depends on the TLH.
        assert(tlh.includes(ct), "ct=" INTPTR_FORMAT " exited unexpectedly.", p2i(ct));
        stringStream msg;
        msg.print("Added initial compiler thread %s", ct->name());
        print_compiler_threads(msg);
      }
    }
  }

  for (int i = 0; i < _c1_count; i++) {
    // Create a name for our thread.
    os::snprintf_checked(name_buffer, sizeof(name_buffer), "C1 CompilerThread%d", i);
    Handle thread_oop = create_thread_oop(name_buffer, CHECK);
    jobject thread_handle = JNIHandles::make_global(thread_oop);
    _compiler1_objects[i] = thread_handle;
    _compiler1_logs[i] = nullptr;

    if (!UseDynamicNumberOfCompilerThreads || i == 0) {
      JavaThread *ct = make_thread(compiler_t, thread_handle, _c1_compile_queue, _compilers[0], THREAD);
      assert(ct != nullptr, "should have been handled for initial thread");
      _compilers[0]->set_num_compiler_threads(i + 1);
      if (trace_compiler_threads()) {
        ResourceMark rm;
        ThreadsListHandle tlh;  // name() depends on the TLH.
        assert(tlh.includes(ct), "ct=" INTPTR_FORMAT " exited unexpectedly.", p2i(ct));
        stringStream msg;
        msg.print("Added initial compiler thread %s", ct->name());
        print_compiler_threads(msg);
      }
    }
  }

  if (UsePerfData) {
    PerfDataManager::create_constant(SUN_CI, "threads", PerfData::U_Bytes, _c1_count + _c2_count, CHECK);
  }

#if defined(ASSERT) && COMPILER2_OR_JVMCI
  if (DeoptimizeObjectsALot) {
    // Initialize and start the object deoptimizer threads
    const int total_count = DeoptimizeObjectsALotThreadCountSingle + DeoptimizeObjectsALotThreadCountAll;
    for (int count = 0; count < total_count; count++) {
      Handle thread_oop = create_thread_oop("Deoptimize objects a lot single mode", CHECK);
      jobject thread_handle = JNIHandles::make_local(THREAD, thread_oop());
      make_thread(deoptimizer_t, thread_handle, nullptr, nullptr, THREAD);
    }
  }
#endif // defined(ASSERT) && COMPILER2_OR_JVMCI
}
```









### On-stack Replacement

On-stack replacement (OSR) is essential technology for adaptive optimization, allowing changes to code actively executing in a managed runtime.

OSR embodiments have to ensure that, whenever control is transferred from a currently running function version to another one, execution can transparently continue without altering the intended program semantics.
In the adaptive optimization practice, optimizing OSR transitions typically happen at places where state realignment is simple, i.e., at a method or loop entry.
The placement of deoptimizing OSR points is determined by the runtime: it can emit them for all instructions that might deoptimize, or group them and resume execution from the last instruction in the deoptimized code that causes outside-visible effects.

### Tiered Compilation

The C2 compiler often takes more time and consumes more memory to compile the same methods. However, it generates better-optimized native code than that produced by C1.

The tiered compilation concept was first introduced in Java 7. Its goal was to use a mix of C1 and C2 compilers in order to achieve both fast startup and good long-term performance.

Tiered compilation is enabled by default since Java 8.
```shell
-XX:+TieredCompilation
```

**JVM doesn't use the generic CompileThreshold parameter when tiered compilation is enabled.**

final not optimize

### Counter

- Invocation Counter
- Back Edge Counter
- from_compiled_entry
- from_interpreted_entry

### code cache

Since Java 9, the JVM segments the code cache into three areas:

- The non-method segment – JVM internal related code (around 5 MB, configurable via -XX:NonNMethodCodeHeapSize)
- The profiled-code segment – C1 compiled code with potentially short lifetimes (around 122 MB by default, configurable via -XX:ProfiledCodeHeapSize)
- The non-profiled segment – C2 compiled code with potentially long lifetimes (similarly 122 MB by default, configurable via -XX:NonProfiledCodeHeapSize)

Segmented code cache helps to improve code locality and reduces memory fragmentation. Thus, it improves overall performance.

### Deoptimization

Even though C2 compiled code is highly optimized and long-lived, it can be deoptimized. As a result, the JVM would temporarily roll back to interpretation.

Deoptimization happens when the compiler’s optimistic assumptions are proven wrong — for example, when profile information does not match method behavior:

jstat  -compiler process_id 编译信息

### Compilation Levels

Even though the JVM works with only one interpreter and two JIT compilers, there are five possible levels of compilation. The reason behind this is that the C1 compiler can operate on three different levels. The difference between those three levels is in the amount of profiling done.

- level 0 - interpreter
- level 1 - C1 with full optimization (no profiling)
- level 2 - C1 with invocation and backedge counters
- level 3 - C1 with full profiling (level 2 + MDO)
- level 4 - C2

The most common scenario in JIT compilation is that the interpreted code jumps directly from level 0 to level 3.

### Compilation Logs

By default, JIT compilation logs are disabled. To enable them, we can set the `-XX:+PrintCompilation` flag. The compilation logs are formatted as:

Timestamp – In milliseconds since application start-up
Compile ID – Incremental ID for each compiled method
Attributes – The state of the compilation with five possible values:
% – On-stack replacement occurred
s – The method is synchronized
! – The method contains an exception handler
b – Compilation occurred in blocking mode
n – Compilation transformed a wrapper to a native method
Compilation level – Between 0 and 4
Method name
Bytecode size
Deoptimisation indicator – With two possible values:
Made not entrant – Standard C1 deoptimization or the compiler’s optimistic assumptions proven wrong
Made zombie – A cleanup mechanism for the garbage collector to free space from the code cache

Tier3CompileThreshold
Tier4CompileThreshold

compile Threads

inline

EscapeAnalysis

```cpp
CompileBroker::compile_method
  
// CompileBroker::invoke_compiler_on_method
// Compile a method.
```

1. Iterative Global Value Numbering
2. Inline
3. eliminate boxing
4. cut edge from root to loop safepoints
5. cleanup_expensive_nodes
6. Perform escape analysis
7. Optimize out fields loads from scalar replaceable allocations.
8. Loop transforms on the ideal graph.  Range Check Elimination, peeling, unrolling, etc.
9. Conditional Constant Propagation
10. Iterative Global Value Numbering, including ideal transforms
11.

```cpp
// Given a graph, optimize it.
void Compile::Optimize() {
```

call `method::set_code()`

```cpp
// ciEnv::register_method
void ciEnv::register_method(...) {
  VM_ENTRY_MARK;
  nmethod* nm = NULL;
  {
    nm =  nmethod::new_nmethod(...);

    // Free codeBlobs
    code_buffer->free_blob();

    if (nm != NULL) {
      // Record successful registration.
      // (Put nm into the task handle *before* publishing to the Java heap.)
      if (task() != NULL) {
        task()->set_code(nm);
      }

      if (entry_bci == InvocationEntryBci) {
        // Allow the code to be executed
        method->set_code(method, nm);
      } else {
        method->method_holder()->add_osr_nmethod(nm);
      }
      nm->make_in_use();
    }
  }  // safepoints are allowed again
}
```


ciEnv::lookup_method
```c
// Perform an appropriate method lookup based on accessor, holder,
// name, signature, and bytecode.
Method* ciEnv::lookup_method(ciInstanceKlass* accessor,
                             ciKlass*         holder,
                             Symbol*          name,
                             Symbol*          sig,
                             Bytecodes::Code  bc,
                             constantTag      tag) {
  InstanceKlass* accessor_klass = accessor->get_instanceKlass();
  Klass* holder_klass = holder->get_Klass();

  // Accessibility checks are performed in ciEnv::get_method_by_index_impl.
  assert(check_klass_accessibility(accessor, holder_klass), "holder not accessible");

  LinkInfo link_info(holder_klass, name, sig, accessor_klass,
                     LinkInfo::AccessCheck::required,
                     LinkInfo::LoaderConstraintCheck::required,
                     tag);
  switch (bc) {
    case Bytecodes::_invokestatic:
      return LinkResolver::resolve_static_call_or_null(link_info);
    case Bytecodes::_invokespecial:
      return LinkResolver::resolve_special_call_or_null(link_info);
    case Bytecodes::_invokeinterface:
      return LinkResolver::linktime_resolve_interface_method_or_null(link_info);
    case Bytecodes::_invokevirtual:
      return LinkResolver::linktime_resolve_virtual_method_or_null(link_info);
    default:
      fatal("Unhandled bytecode: %s", Bytecodes::name(bc));
      return nullptr; // silence compiler warnings
  }
}
```

### adapter

c2i是指编译模式到解释模式（Compiler-to-Interpreter），i2c是指解释模式到编译模式（Interpreter-to-Compiler）。由于编译产出的本地代码可能用寄存器存放参数1，用栈存放参数2，而解释器都用栈存放参数，需要一段代码来消弭它们的不同，适配器应运而生。它是一段跳床（Trampoline）代码，以i2c为例，可以形象地认为解释器“跳入”这段代码，将解释器的参数传递到机器代码要求的地方，这种要求即调用约定（Calling Convention），然后“跳出”到机器代码继续执行
两个适配器都是由SharedRuntime::generate_i2c2i_adapters生成的


```cpp
// SharedRuntime.cpp


  // Generate I2C and C2I adapters. These adapters are simple argument marshalling
  // blobs. Unlike adapters in the tiger and earlier releases the code in these
  // blobs does not create a new frame and are therefore virtually invisible
  // to the stack walking code. In general these blobs extend the callers stack
  // as needed for the conversion of argument locations.

  // When calling a c2i blob the code will always call the interpreter even if
  // by the time we reach the blob there is compiled code available. This allows
  // the blob to pass the incoming stack pointer (the sender sp) in a known
  // location for the interpreter to record. This is used by the frame code
  // to correct the sender code to match up with the stack pointer when the
  // thread left the compiled code. In addition it allows the interpreter
  // to remove the space the c2i adapter allocated to do its argument conversion.

  // Although a c2i blob will always run interpreted even if compiled code is
  // present if we see that compiled code is present the compiled call site
  // will be patched/re-resolved so that later calls will run compiled.

  // Additionally a c2i blob need to have a unverified entry because it can be reached
  // in situations where the call site is an inlined cache site and may go megamorphic.

  // A i2c adapter is simpler than the c2i adapter. This is because it is assumed
  // that the interpreter before it does any call dispatch will record the current
  // stack pointer in the interpreter frame. On return it will restore the stack
  // pointer as needed. This means the i2c adapter code doesn't need any special
  // handshaking path with compiled code to keep the stack walking correct.

  static AdapterHandlerEntry* generate_i2c2i_adapters(MacroAssembler *_masm,
                                                      int total_args_passed,
                                                      int max_arg,
                                                      const BasicType *sig_bt,
                                                      const VMRegPair *regs,
                                                      AdapterFingerPrint* fingerprint);

  static void gen_i2c_adapter(MacroAssembler *_masm,
                              int total_args_passed,
                              int comp_args_on_stack,
                              const BasicType *sig_bt,
                              const VMRegPair *regs);
```

## c1

## c2

[CompilerThread](/docs/CS/Java/JDK/JVM/Thread.md?id=CompilerThread) -> `C2Compiler::compile_method`

### compile_method

```cpp

void C2Compiler::compile_method(ciEnv* env, ciMethod* target, int entry_bci, bool install_code, DirectiveSet* directive) {
  assert(is_initialized(), "Compiler thread must be initialized");

  bool subsume_loads = SubsumeLoads;
  bool do_escape_analysis = DoEscapeAnalysis;
  bool do_iterative_escape_analysis = DoEscapeAnalysis;
  bool eliminate_boxing = EliminateAutoBox;
  bool do_locks_coarsening = EliminateLocks;

  while (!env->failing()) {
    // Attempt to compile while subsuming loads into machine instructions.
    Options options(subsume_loads, do_escape_analysis, do_iterative_escape_analysis, eliminate_boxing, do_locks_coarsening, install_code);
    Compile C(env, target, entry_bci, options, directive);

    // Check result and retry if appropriate.
    if (C.failure_reason() != NULL) {
      if (C.failure_reason_is(retry_class_loading_during_parsing())) {
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      if (C.failure_reason_is(retry_no_subsuming_loads())) {
        assert(subsume_loads, "must make progress");
        subsume_loads = false;
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      if (C.failure_reason_is(retry_no_escape_analysis())) {
        assert(do_escape_analysis, "must make progress");
        do_escape_analysis = false;
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      if (C.failure_reason_is(retry_no_iterative_escape_analysis())) {
        assert(do_iterative_escape_analysis, "must make progress");
        do_iterative_escape_analysis = false;
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      if (C.failure_reason_is(retry_no_locks_coarsening())) {
        assert(do_locks_coarsening, "must make progress");
        do_locks_coarsening = false;
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      if (C.has_boxed_value()) {
        // Recompile without boxing elimination regardless failure reason.
        assert(eliminate_boxing, "must make progress");
        eliminate_boxing = false;
        env->report_failure(C.failure_reason());
        continue;  // retry
      }
      // Pass any other failure reason up to the ciEnv.
      // Note that serious, irreversible failures are already logged
      // on the ciEnv via env->record_method_not_compilable().
      env->record_failure(C.failure_reason());
    }
    if (StressRecompilation) {
      if (subsume_loads) {
        subsume_loads = false;
        continue;  // retry
      }
      if (do_escape_analysis) {
        do_escape_analysis = false;
        continue;  // retry
      }
      if (do_locks_coarsening) {
        do_locks_coarsening = false;
        continue;  // retry
      }
    }
    // print inlining for last compilation only
    C.dump_print_inlining();

    // No retry; just break the loop.
    break;
  }
}
```

Or see PhaseTraceId

```cpp

  enum PhaseTraceId {
    _t_parser,
    _t_optimizer,
      _t_escapeAnalysis,
        _t_connectionGraph,
        _t_macroEliminate,
      _t_iterGVN,
      _t_incrInline,
        _t_incrInline_ideal,
        _t_incrInline_igvn,
        _t_incrInline_pru,
        _t_incrInline_inline,
      _t_vector,
        _t_vector_elimination,
          _t_vector_igvn,
          _t_vector_pru,
      _t_renumberLive,
      _t_idealLoop,
      _t_idealLoopVerify,
      _t_ccp,
      _t_iterGVN2,
      _t_macroExpand,
      _t_barrierExpand,
      _t_graphReshaping,
    _t_matcher,
      _t_postselect_cleanup,
    _t_scheduler,
    _t_registerAllocation,
      _t_ctorChaitin,
      _t_buildIFGvirtual,
      _t_buildIFGphysical,
      _t_computeLive,
      _t_regAllocSplit,
      _t_postAllocCopyRemoval,
      _t_mergeMultidefs,
      _t_fixupSpills,
      _t_chaitinCompact,
      _t_chaitinCoalesce1,
      _t_chaitinCoalesce2,
      _t_chaitinCoalesce3,
      _t_chaitinCacheLRG,
      _t_chaitinSimplify,
      _t_chaitinSelect,
    _t_blockOrdering,
    _t_peephole,
    _t_postalloc_expand,
    _t_output,
      _t_instrSched,
      _t_shortenBranches,
      _t_buildOopMaps,
      _t_fillBuffer,
      _t_registerMethod,
    _t_temporaryTimer1,
    _t_temporaryTimer2,
    max_phase_timers
   };
```

Compile::Compile -> Compile::Optimize

## Optimization

### Inline Method

### Escape Analysis

```cpp
// c2_globals.hpp
  notproduct(bool, PrintEscapeAnalysis, false,                              \
          "Print the results of escape analysis")                           \
                                                                            \
  product(bool, EliminateAllocations, true,                                 \
          "Use escape analysis to eliminate allocations")                   \
                                                                            \
  notproduct(bool, PrintEliminateAllocations, false,                        \
          "Print out when allocations are eliminated")                      \
                                                                            \
  product(intx, EliminateAllocationArraySizeLimit, 64,                      \
          "Array size (number of elements) limit for scalar replacement")   \
          range(0, max_jint)                                                \
```

Compile::Optimize -> ConnectionGraph::do_analysis

#### Stack Allocations

support escape method, not support escape thread

#### Scalar Replacement

like a special situation of Stack Allocations

use many primitive fields replace a Aggregate

not support escape method

#### Synchronization Elimination

### Common Subexpression Elimination

### Array bounds Checking Elimination

### Autobox Elimination

### Safepoint Elimination

### Dereflection

## Tools

1. c1visualizer
2. idealgraphvisualizer
3. JITWatch

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)

## References

1. [Tiered Compilation in JVM](https://www.baeldung.com/jvm-tiered-compilation)
2. [Compilation Optimization - Java Platform, Standard Edition JRockit to HotSpot Migration Guide](https://docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm#JRHMG117)
3. [Bril JIT with On-Stack Replacement](https://www.cs.cornell.edu/courses/cs6120/2019fa/blog/bril-osr/)
4. [深入浅出 Java 10 的实验性 JIT 编译器 Graal](https://www.infoq.cn/article/java-10-jit-compiler-graal)
5. [基本功 | Java即时编译器原理解析及实践](https://tech.meituan.com/2020/10/22/java-jit-practice-in-meituan.html)
