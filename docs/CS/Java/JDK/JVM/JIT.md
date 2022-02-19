## Overview

OpenJDK is a three tiered compilation environment. 
Methods that are only executed a few times are interpreted. 
Once a method hits a certain threshold of executions it is compiled using a text book style compiler called C1. 
Only when the method has hit an even higher threshold of executions will it be compiled using C2, the optimizing compiler.

The JVM interprets and executes bytecode at runtime. In addition, it makes use of the just-in-time (JIT) compilation to boost performance.

In earlier versions of Java, we had to manually choose between the two types of JIT compilers available in the Hotspot JVM. One is optimized for faster application start-up, while the other achieves better overall performance. Java 7 introduced tiered compilation in order to achieve the best of both worlds.

A JIT compiler compiles bytecode to native code for frequently executed sections. These sections are called hotspots, hence the name Hotspot JVM. As a result, Java can run with similar performance to a fully compiled language. Let's look at the two types of JIT compilers available in the JVM.

C1 – Client Compiler

The client compiler, also called C1, is a type of a JIT compiler optimized for faster start-up time. It tries to optimize and compile the code as soon as possible.

Historically, we used C1 for short-lived applications and applications where start-up time was an important non-functional requirement. Prior to Java 8, we had to specify the -client flag to use the C1 compiler. However, if we use Java 8 or higher, this flag will have no effect.

C2 – Server Compiler

The server compiler, also called C2(Opto), is a type of a JIT compiler optimized for better overall performance. C2 observes and analyzes the code over a longer period of time compared to C1. This allows C2 to make better optimizations in the compiled code.

Historically, we used C2 for long-running server-side applications. Prior to Java 8, we had to specify the -server flag to use the C2 compiler. However, this flag will have no effect in Java 8 or higher.

We should note that the Graal JIT compiler is also available since Java 10, as an alternative to C2. Unlike C2, Graal can run in both just-in-time and ahead-of-time compilation modes to produce

### On-stack Replacement

On-stack replacement (OSR) is a programming language implementation technique that allows a running program to switch to a different version of code.


### Tiered Compilation
The C2 compiler often takes more time and consumes more memory to compile the same methods. However, it generates better-optimized native code than that produced by C1.

The tiered compilation concept was first introduced in Java 7. Its goal was to use a mix of C1 and C2 compilers in order to achieve both fast startup and good long-term performance.

Tiered compilation is enabled by default since Java 8.

**JVM doesn't use the generic CompileThreshold parameter when tiered compilation is enabled.**

final not optimize


### Counter

- Invocation Counter
- Back Edge Counter


- from_compiled_entry
- from_interpreted_entry

### code cache

Since Java 9, the JVM segments the code cache into three areas:

The non-method segment – JVM internal related code (around 5 MB, configurable via -XX:NonNMethodCodeHeapSize)
The profiled-code segment – C1 compiled code with potentially short lifetimes (around 122 MB by default, configurable via -XX:ProfiledCodeHeapSize)
The non-profiled segment – C2 compiled code with potentially long lifetimes (similarly 122 MB by default, configurable via -XX:NonProfiledCodeHeapSize)
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



### adapter

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

### compile_java_method
[CompilerThread](/docs/CS/Java/JDK/JVM/Thread.md?id=CompilerThread) -> Compilation::compile_method -> Compilation::compile_java_method

1. build hir
2. build lir
3. generate emit_code
```cpp
int Compilation::compile_java_method() {
  if (BailoutOnExceptionHandlers) {
    if (method()->has_exception_handlers()) {
      bailout("linear scan can't handle exception handlers");
    }
  }

  CHECK_BAILOUT_(no_frame_size);

  if (is_profiling() && !method()->ensure_method_data()) {
    BAILOUT_("mdo allocation failed", no_frame_size);
  }

  {
    PhaseTraceTime timeit(_t_buildIR);
    build_hir();
  }
  if (BailoutAfterHIR) {
    BAILOUT_("Bailing out because of -XX:+BailoutAfterHIR", no_frame_size);
  }


  {
    PhaseTraceTime timeit(_t_emit_lir);

    _frame_map = new FrameMap(method(), hir()->number_of_locks(), MAX2(4, hir()->max_stack()));
    emit_lir();
  }
  CHECK_BAILOUT_(no_frame_size);

  // Dump compilation data to replay it.
  if (_directive->DumpReplayOption) {
    env()->dump_replay_data(env()->compile_id());
  }

  {
    PhaseTraceTime timeit(_t_codeemit);
    return emit_code_body();
  }
}
```

Or see Timer
```cpp
typedef enum {
  _t_compile,
    _t_setup,
    _t_buildIR,
      _t_hir_parse,
      _t_gvn,
      _t_optimize_blocks,
      _t_optimize_null_checks,
      _t_rangeCheckElimination,
    _t_emit_lir,
      _t_linearScan,
      _t_lirGeneration,
    _t_codeemit,
    _t_codeinstall,
  max_phase_timers
} TimerName;
```

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




## References
1. [Tiered Compilation in JVM](https://www.baeldung.com/jvm-tiered-compilation)
2. [Compilation Optimization - Java Platform, Standard Edition JRockit to HotSpot Migration Guide](https://docs.oracle.com/javacomponents/jrockit-hotspot/migration-guide/comp-opt.htm#JRHMG117)
3. [Bril JIT with On-Stack Replacement](https://www.cs.cornell.edu/courses/cs6120/2019fa/blog/bril-osr/)
4. [深入浅出 Java 10 的实验性 JIT 编译器 Graal](https://www.infoq.cn/article/java-10-jit-compiler-graal)
