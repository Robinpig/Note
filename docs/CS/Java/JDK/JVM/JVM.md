## Introduction

JVM is the core of the [Java ecosystem](/docs/CS/Java/JDK/JDK.md), and makes it possible for Java-based software programs to follow the "write once, run anywhere" approach.
JVM was initially designed to support only Java.
However, over the time, many other languages such as Scala, Kotlin and Groovy were adopted on the Java platform.
All of these languages are collectively known as JVM languages.

Before we jump into the JVM, let's revisit the concept of a [Virtual Machine (VM)](/docs/CS/OS/VM.md).
Similar to virtual machines, the JVM creates an isolated space on a host machine.
This space can be used to execute Java programs irrespective of the platform or operating system of the machine.

### Directories

Directory based on JDK12 HotSpot, [Git Link](https://github.com/openjdk/jdk/tree/master/src/hotspot)

```
hotspot
    |--- cpu   
    |--- os
    |--- os_cpu
    |--- share
        |--- adlc               # 
        |--- aot                # 
        |--- asm                # 
        |--- c1                 # C1 JIT
        |--- ci                 # compiler interface
        |--- classfile          #
        |--- code   
        |--- compiler   
        |--- gc   
        |--- include  
        |--- interpreter  
        |--- jfr                # Java Flight Record
        |--- jvmci  
        |--- libadt   
        |--- logging  
        |--- memory   
        |--- metaprogramming  
        |--- oops   
        |--- opto               # C2 JIT
        |--- precompiled  
        |--- prims              # implement JNI, JVMTI, Unsafe
        |--- runtime  
        |--- services           # HeapDump, MXBean, jcmd, jinfo
        |--- utilities          # hashtable, JSON parser, elf, etc.
```

log:

```
-Xlog:
    codecache+sweep*=trace,
    class+unload,
    class+load,
    os+thread,
    safepoint,
    gc*,
    gc+stringdedup=debug,
    gc+ergo=trace,
    gc+age=trace,
    gc+phases=trace,
    gc+humongous=trace,
    jit+compilation=debug
:file=/path_to_logs/app.log
:level,tags,time,uptime,pid
:filesize=104857600,filecount=5
```

### heap object

CHeapObj

- 0xAB around obj to check if the memory been broken

AllStatic

```hpp
// os.hpp
class os: AllStatic {
  friend class VMStructs;
  friend class JVMCIVMStructs;
  friend class MallocTracker;

static char*  reserve_memory(size_t bytes, char* addr = 0,
                               size_t alignment_hint = 0, int file_desc = -1);
}
```

## Architecture

<div style="text-align: center;">

![Fig.1. Architecture](./img/Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. JVM Architecture.
</p>

As shown in the above architecture diagram, the JVM is divided into three main subsystems:

1. ClassLoader Subsystem
2. Runtime Data Area
3. Execution Engine

Before

- [Class File and Compiler](/docs/CS/Java/JDK/JVM/ClassFile.md)
- [Javac](/docs/CS/Java/JDK/JVM/Javac.md)

### Class Loader Subsystem

Java's dynamic class loading functionality is handled by the [ClassLoader subsystem](/docs/CS/Java/JDK/JVM/ClassLoader.md).
It loads, links. and initializes the class file when it refers to a class for the first time at runtime, not compile time.

<div style="text-align: center;">

![Fig.2. ClassLoader](./img/ClassLoader.svg)

</div>

<p style="text-align: center;">
Fig.2. ClassLoader.
</p>

### Runtime Data Area

The Java Virtual Machine defines various [run-time data areas](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) that are used during execution of a program.
Some of these data areas are created on Java Virtual Machine start-up and are destroyed only when the Java Virtual Machine exits.

Other data areas are per thread. Per-thread data areas are created when a thread is created and destroyed when the thread exits.

[CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)

The Runtime Data Area is divided into five major components:

1. **Method Area** – All the class level data such as the run-time constant pool, field, and method data, and the code for methods and constructors, are stored here. There is only one method area per JVM, and it is a shared resource.
2. **Heap Area** – All the Objects and their corresponding instance variables and arrays will be stored here. There is also one Heap Area per JVM. Since the Method and Heap areas share memory for multiple threads, the data stored is not thread-safe.
3. **Stack Area** – For every thread, a separate runtime stack will be created. For every method call, one entry will be made in the stack memory which is called Stack Frame. All local variables will be created in the stack memory. The stack area is thread-safe since it is not a shared resource. The Stack Frame is divided into three subentities:
   1. **Local Variable Array** – Related to the method how many local variables are involved and the corresponding values will be stored here.
   2. **Operand stack** – If any intermediate operation is required to perform, operand stack acts as runtime workspace to perform the operation.
   3. **Frame data** – All symbols corresponding to the method is stored here. In the case of any  **exception** , the catch block information will be maintained in the frame data.
4. **PC Registers** – Each thread will have separate PC Registers, to hold the address of current executing instruction once the instruction is executed the PC register will be updated with the next instruction.
5. **Native Method stacks** – Native Method Stack holds native method information. For every thread, a separate native method stack will be created.

### Execution Engine

The bytecode, which is assigned to the **Runtime Data Area,** will be executed by the [Execution Engine](/docs/CS/Java/JDK/JVM/ExecutionEngine.md).
The Execution Engine reads the bytecode and executes it piece by piece.

1. **Interpreter** – The interpreter interprets the bytecode faster but executes slowly.
   The disadvantage of the interpreter is that when one method is called multiple times, every time a new interpretation is required.
2. **JIT Compiler** – The JIT Compiler neutralizes the disadvantage of the interpreter. 
   The Execution Engine will be using the help of the interpreter in converting byte code, but when it finds repeated code it uses the JIT compiler, 
   which compiles the entire bytecode and changes it to native code. 
   This native code will be used directly for repeated method calls, which improve the performance of the system.
   1. **Intermediate Code Generator** – Produces intermediate code
   2. **Code Optimizer** – Responsible for optimizing the intermediate code generated above
   3. **Target Code Generator** – Responsible for Generating Machine Code or Native Code
   4. **Profiler** – A special component, responsible for finding hotspots, i.e. whether the method is called multiple times or not.
3. [**Garbage Collector**](/docs/CS/Java/JDK/JVM/GC.md) - Collects and removes unreferenced objects. 
   Garbage Collection can be triggered by calling `System.gc()`, but the execution is not guaranteed. Garbage collection of the JVM collects the objects that are created.

Early VM’s were interpreter−only. Later VM’s were interpreter plus template generated code, and finally interpreter plus optimized code.

These optimizations include class−hierarchy aware inlining, fast−path/slow−path idioms, global value−numbering, optimistic constant propagation, optimal instruction selection, graph−coloring register allocation, and peephole optimization.

Several of the most significant features are: a single native stack per running thread for interpreting and executing compiled or native code,
accurate garbage collection using card−marks, exception handling, efficient synchronization using a meta−lock, class−hierarchy analysis, compilation events,
on−stack replacement of interpreter frames with compiled−code frames, deoptimization from compiled code back to the interpreter, a compiler interface that supports compilations in parallel with garbage collection,
and runtime support routines which may be generated at system startup.

The runtime generates the interpreter at startup using macro assembler templates for each bytecode and an interpreter dispatch loop.
This provides assembly level instrumentation that collects counts at method entry and backward branches, type−profiles at call sites, and never−null object pointers for instanceof or checkcast bytecodes.
Additional instrumentation has been implemented, e.g., branch frequencies, but is not turned on by default.

The runtime environment uses adaptive optimization to focus compilation efforts on performance critical methods.
These methods are identified using method−entry and backward−branch counters with additional heuristics that investigate the caller of a triggering method.
When the combined method−entry and backward−branch counters for a method exceed the CompileThreshold, the runtime system determines which method to make the root of a compilation by examining the call stack.
If the caller frequently invokes the callee, the recompilation policy may decide to start compiling at the caller.
This upwards traversal may continue multiple times relying upon the compiler to inline the path to the triggering method.
Compiled code for the standard entry point is registered with the method object (methodOop) in a reserved field.
At method invocation, the interpreter transfers control to compiled code when this field is not null.
A different transition, on stack replacement, occurs when a method’s combined counter exceeds the OnStackReplaceThreshold at a backward branch.
The method is compiled with an entry point at the target of the backwards branch.
The resulting code is registered with the methodOop, which contains a linked list of target bytecode index and compiled−code pairs.
The runtime transfers execution from the interpreted frame to an on−stack−replacement frame and compiled code.
The methodOop is used to cache other information as well, including the possibility that the compiler has refused to generate code for a method.
**A non−compilable method will always be run within the interpreter.** This is used to support porting and debugging.

The server compiler proceeds through the following traditional phases: parser, machine−independent optimization, instruction selection, global code motion and scheduling, register allocation, peephole optimization, and code generation.

In HotSpot, we compile methods that have crossed a threshold.
In most cases any necessary class initialization or class loading has already been done by the interpreter which handles all initialization semantics.
We investigated having the generated code handle class initialization properly and discovered that it is too rare.
Instead the compiler generates an uncommon trap, a trampoline back to interpreted mode, when it compiles a reference to an uninitialized class.
The compiled code is then deoptimized and it is flagged as being unusable.
Threads entering the method are interpreted until its recompilation is finished. As a side effect, field offsets are always known so short−form addressing modes can be used without backpatching.

### Java Native Interface

At times, it is necessary to use native (non-Java) code (for example, C/C++).
This can be in cases where we need to interact with hardware, or to overcome the memory management and performance constraints in Java.
Java supports the execution of native code via the Java Native Interface (JNI).

JNI acts as a bridge for permitting the supporting packages for other programming languages such as C, C++, and so on.
This is especially helpful in cases where you need to write code that is not entirely supported by Java, like some platform specific features that can only be written in C.

You can use the native keyword to indicate that the method implementation will be provided by a native library.
You will also need to invoke System.loadLibrary() to load the shared native library into memory, and make its functions available to Java.

### Native Method Libraries

Native Method Libraries are libraries that are written in other programming languages, such as C, C++, and assembly. 
These libraries are usually present in the form of .dll or .so files. These native libraries can be loaded through JNI.

## Runtime

- [start](/docs/CS/Java/JDK/JVM/start.md) and [destroy](/docs/CS/Java/JDK/JVM/destroy.md)
- [Thread](/docs/CS/Java/JDK/JVM/Thread.md)

[JavaCalls](/docs/CS/Java/JDK/JVM/Stub.md?id=JavaCalls) and [JNI](/docs/CS/Java/JDK/Basic/JNI.md)

```dot
strict digraph {
    rankdir=LR
    java [shape="polygon" label="Java Method"]
    VM [shape="polygon" label="VM"]
    java -> VM [label="JNI"]
    VM -> java [label="\n\nJavaCalls" labelfloat=false]
}
```

### Class

- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)

### Representation of Objects

The Java Virtual Machine does not mandate any particular internal structure for objects.

In some of Oracle’s implementations of the Java Virtual Machine, a reference to a class instance is a pointer to a handle that is itself a pair of pointers(see [OOP-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)):

- one to a table containing the methods of the object and a pointer to the Class object that represents the type of the object
- and the other to the memory allocated from the heap for the object data.

## GC

- [GC](/docs/CS/Java/JDK/JVM/GC.md)
- [SafePoint](/docs/CS/Java/JDK/JVM/Safepoint.md)

### Deoptimization

If class loading invalidates inlining or other optimization decisions, the dependent methods are deoptimized.
Threads currently executing in the method are rolled forward to a safepoint, at which point the native frame is converted into an interpreter frame.
The invalidating class load is not visible to the executing thread until it has been brought to a safepoint.
Execution of the method continues in the interpreter.

- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)

## Native Method Interface

### Native Method Library

```dot

strict digraph {
    subgraph cluster_CollectedHeap {
            label="CollectedHeap"
        Heap;
        Interface[label="Manger interface"];
        Heap ->  Interface;
        Interface -> Heap;  
    }
    CollectPolicy -> Heap;
    Allocate_Request -> Interface;
    Active_GC_request -> Interface;
}
```

Top-of-Stack Cashing
based on stack VM need more instrument dispatch

cached in CPU registers and reduce accessing memory

```cpp
// globalDefinitions.hpp

// TosState describes the top-of-stack state before and after the execution of
// a bytecode or method. The top-of-stack value may be cached in one or more CPU
// registers. The TosState corresponds to the 'machine representation' of this cached
// value. There's 4 states corresponding to the JAVA types int, long, float & double
// as well as a 5th state in case the top-of-stack value is actually on the top
// of stack (in memory) and thus not cached. The atos state corresponds to the itos
// state when it comes to machine representation but is used separately for (oop)
// type specific operations (e.g. verification code).

enum TosState {         // describes the tos cache contents
  btos = 0,             // byte, bool tos cached
  ztos = 1,             // byte, bool tos cached
  ctos = 2,             // char tos cached
  stos = 3,             // short tos cached
  itos = 4,             // int tos cached
  ltos = 5,             // long tos cached
  ftos = 6,             // float tos cached
  dtos = 7,             // double tos cached
  atos = 8,             // object cached
  vtos = 9,             // tos not cached
  number_of_states,
  ilgl                  // illegal state: should not occur
};
```

check previous and after TosState in transition,

```cpp
// templateTable_x86.cpp

void TemplateTable::iop2(Operation op) {
  transition(itos, itos);
  switch (op) {
  case add  :                    __ pop_i(rdx); __ addl (rax, rdx); break;
  case sub  : __ movl(rdx, rax); __ pop_i(rax); __ subl (rax, rdx); break;
  case mul  :                    __ pop_i(rdx); __ imull(rax, rdx); break;
  case _and :                    __ pop_i(rdx); __ andl (rax, rdx); break;
  case _or  :                    __ pop_i(rdx); __ orl  (rax, rdx); break;
  case _xor :                    __ pop_i(rdx); __ xorl (rax, rdx); break;
  case shl  : __ movl(rcx, rax); __ pop_i(rax); __ shll (rax);      break;
  case shr  : __ movl(rcx, rax); __ pop_i(rax); __ sarl (rax);      break;
  case ushr : __ movl(rcx, rax); __ pop_i(rax); __ shrl (rax);      break;
  default   : ShouldNotReachHere();
  }
}
```

All classes in adlc may be derived from one of the following allocation classes:
For objects allocated in the C-heap (managed by: malloc & free).

- CHeapObj
  For classes used as name spaces.
- AllStatic

```cpp
// share/adlc/arena.hpp
class CHeapObj {
 public:
  void* operator new(size_t size) throw();
  void  operator delete(void* p);
  void* new_array(size_t size);
};
```

Base class for classes that constitute name spaces.

```
class AllStatic {
 public:
  void* operator new(size_t size) throw();
  void operator delete(void* p);
};
```

AllStatic

```cpp
// share/runtime/os.hpp
class os: AllStatic {
  friend class VMStructs;
  friend class JVMCIVMStructs;
  friend class MallocTracker;

#ifdef ASSERT
 private:
  static bool _mutex_init_done;
 public:
  static void set_mutex_init_done() { _mutex_init_done = true; }
  static bool mutex_init_done() { return _mutex_init_done; }
#endif

 public:
  enum { page_sizes_max = 9 }; // Size of _page_sizes array (8 plus a sentinel)

 private:
  static OSThread*          _starting_thread;
  static address            _polling_page;
 public:
  static size_t             _page_sizes[page_sizes_max];

 private:
  static void init_page_sizes(size_t default_page_size) {
    _page_sizes[0] = default_page_size;
    _page_sizes[1] = 0; // sentinel
  }

  static char*  pd_reserve_memory(size_t bytes, char* addr = 0,
                                  size_t alignment_hint = 0);
  static char*  pd_attempt_reserve_memory_at(size_t bytes, char* addr);
  static char*  pd_attempt_reserve_memory_at(size_t bytes, char* addr, int file_desc);
  static void   pd_split_reserved_memory(char *base, size_t size,
                                      size_t split, bool realloc);
  static bool   pd_commit_memory(char* addr, size_t bytes, bool executable);
  static bool   pd_commit_memory(char* addr, size_t size, size_t alignment_hint,
                                 bool executable);
  // Same as pd_commit_memory() that either succeeds or calls
  // vm_exit_out_of_memory() with the specified mesg.
  static void   pd_commit_memory_or_exit(char* addr, size_t bytes,
                                         bool executable, const char* mesg);
  static void   pd_commit_memory_or_exit(char* addr, size_t size,
                                         size_t alignment_hint,
                                         bool executable, const char* mesg);
  static bool   pd_uncommit_memory(char* addr, size_t bytes);
  static bool   pd_release_memory(char* addr, size_t bytes);

  static char*  pd_map_memory(int fd, const char* file_name, size_t file_offset,
                           char *addr, size_t bytes, bool read_only = false,
                           bool allow_exec = false);
  static char*  pd_remap_memory(int fd, const char* file_name, size_t file_offset,
                             char *addr, size_t bytes, bool read_only,
                             bool allow_exec);
  static bool   pd_unmap_memory(char *addr, size_t bytes);
  static void   pd_free_memory(char *addr, size_t bytes, size_t alignment_hint);
  static void   pd_realign_memory(char *addr, size_t bytes, size_t alignment_hint);

  static size_t page_size_for_region(size_t region_size, size_t min_pages, bool must_be_aligned);

  // Get summary strings for system information in buffer provided
  static void  get_summary_cpu_info(char* buf, size_t buflen);
  static void  get_summary_os_info(char* buf, size_t buflen);

  static void initialize_initial_active_processor_count();

  LINUX_ONLY(static void pd_init_container_support();)

 public:
  static void init(void);                      // Called before command line parsing

  static void init_container_support() {       // Called during command line parsing.
     LINUX_ONLY(pd_init_container_support();)
  }

  static void init_before_ergo(void);          // Called after command line parsing
                                               // before VM ergonomics processing.
  static jint init_2(void);                    // Called after command line parsing
                                               // and VM ergonomics processing
  static void init_globals(void) {             // Called from init_globals() in init.cpp
    init_globals_ext();
  }

  // File names are case-insensitive on windows only
  // Override me as needed
  static int    file_name_strncmp(const char* s1, const char* s2, size_t num);

  // unset environment variable
  static bool unsetenv(const char* name);

  static bool have_special_privileges();

  static jlong  javaTimeMillis();
  static jlong  javaTimeNanos();
  static void   javaTimeNanos_info(jvmtiTimerInfo *info_ptr);
  static void   javaTimeSystemUTC(jlong &seconds, jlong &nanos);
  static void   run_periodic_checks();
  static bool   supports_monotonic_clock();

  // Returns the elapsed time in seconds since the vm started.
  static double elapsedTime();

  // Returns real time in seconds since an arbitrary point
  // in the past.
  static bool getTimesSecs(double* process_real_time,
                           double* process_user_time,
                           double* process_system_time);

  // Interface to the performance counter
  static jlong elapsed_counter();
  static jlong elapsed_frequency();

  // The "virtual time" of a thread is the amount of time a thread has
  // actually run.  The first function indicates whether the OS supports
  // this functionality for the current thread, and if so:
  //   * the second enables vtime tracking (if that is required).
  //   * the third tells whether vtime is enabled.
  //   * the fourth returns the elapsed virtual time for the current
  //     thread.
  static bool supports_vtime();
  static bool enable_vtime();
  static bool vtime_enabled();
  static double elapsedVTime();

  // Return current local time in a string (YYYY-MM-DD HH:MM:SS).
  // It is MT safe, but not async-safe, as reading time zone
  // information may require a lock on some platforms.
  static char*      local_time_string(char *buf, size_t buflen);
  static struct tm* localtime_pd     (const time_t* clock, struct tm*  res);
  static struct tm* gmtime_pd        (const time_t* clock, struct tm*  res);
  // Fill in buffer with current local time as an ISO-8601 string.
  // E.g., YYYY-MM-DDThh:mm:ss.mmm+zzzz.
  // Returns buffer, or NULL if it failed.
  static char* iso8601_time(char* buffer, size_t buffer_length, bool utc = false);

  // Interface for detecting multiprocessor system
  static inline bool is_MP() {
    // During bootstrap if _processor_count is not yet initialized
    // we claim to be MP as that is safest. If any platform has a
    // stub generator that might be triggered in this phase and for
    // which being declared MP when in fact not, is a problem - then
    // the bootstrap routine for the stub generator needs to check
    // the processor count directly and leave the bootstrap routine
    // in place until called after initialization has ocurred.
    return (_processor_count != 1);
  }

  static julong available_memory();
  static julong physical_memory();
  static bool has_allocatable_memory_limit(julong* limit);
  static bool is_server_class_machine();

  // Returns the id of the processor on which the calling thread is currently executing.
  // The returned value is guaranteed to be between 0 and (os::processor_count() - 1).
  static uint processor_id();

  // number of CPUs
  static int processor_count() {
    return _processor_count;
  }
  static void set_processor_count(int count) { _processor_count = count; }

  // Returns the number of CPUs this process is currently allowed to run on.
  // Note that on some OSes this can change dynamically.
  static int active_processor_count();

  // At startup the number of active CPUs this process is allowed to run on.
  // This value does not change dynamically. May be different from active_processor_count().
  static int initial_active_processor_count() {
    assert(_initial_active_processor_count > 0, "Initial active processor count not set yet.");
    return _initial_active_processor_count;
  }

  // Bind processes to processors.
  //     This is a two step procedure:
  //     first you generate a distribution of processes to processors,
  //     then you bind processes according to that distribution.
  // Compute a distribution for number of processes to processors.
  //    Stores the processor id's into the distribution array argument.
  //    Returns true if it worked, false if it didn't.
  static bool distribute_processes(uint length, uint* distribution);
  // Binds the current process to a processor.
  //    Returns true if it worked, false if it didn't.
  static bool bind_to_processor(uint processor_id);

  // Give a name to the current thread.
  static void set_native_thread_name(const char *name);

  // Interface for stack banging (predetect possible stack overflow for
  // exception processing)  There are guard pages, and above that shadow
  // pages for stack overflow checking.
  static bool uses_stack_guard_pages();
  static bool must_commit_stack_guard_pages();
  static void map_stack_shadow_pages(address sp);
  static bool stack_shadow_pages_available(Thread *thread, const methodHandle& method, address sp);

  // Find committed memory region within specified range (start, start + size),
  // return true if found any
  static bool committed_in_range(address start, size_t size, address& committed_start, size_t& committed_size);

  // OS interface to Virtual Memory

  // Return the default page size.
  static int    vm_page_size();

  // Returns the page size to use for a region of memory.
  // region_size / min_pages will always be greater than or equal to the
  // returned value. The returned value will divide region_size.
  static size_t page_size_for_region_aligned(size_t region_size, size_t min_pages);

  // Returns the page size to use for a region of memory.
  // region_size / min_pages will always be greater than or equal to the
  // returned value. The returned value might not divide region_size.
  static size_t page_size_for_region_unaligned(size_t region_size, size_t min_pages);

  // Return the largest page size that can be used
  static size_t max_page_size() {
    // The _page_sizes array is sorted in descending order.
    return _page_sizes[0];
  }

  // Return a lower bound for page sizes. Also works before os::init completed.
  static size_t min_page_size() { return 4 * K; }

  // Methods for tracing page sizes returned by the above method.
  // The region_{min,max}_size parameters should be the values
  // passed to page_size_for_region() and page_size should be the result of that
  // call.  The (optional) base and size parameters should come from the
  // ReservedSpace base() and size() methods.
  static void trace_page_sizes(const char* str, const size_t* page_sizes, int count);
  static void trace_page_sizes(const char* str,
                               const size_t region_min_size,
                               const size_t region_max_size,
                               const size_t page_size,
                               const char* base,
                               const size_t size);
  static void trace_page_sizes_for_requested_size(const char* str,
                                                  const size_t requested_size,
                                                  const size_t page_size,
                                                  const size_t alignment,
                                                  const char* base,
                                                  const size_t size);

  static int    vm_allocation_granularity();
```

reserve_memory

```cpp

  static char*  reserve_memory(size_t bytes, char* addr = 0,
                               size_t alignment_hint = 0, int file_desc = -1);
  static char*  reserve_memory(size_t bytes, char* addr,
                               size_t alignment_hint, MEMFLAGS flags);
  static char*  reserve_memory_aligned(size_t size, size_t alignment, int file_desc = -1);
  static char*  attempt_reserve_memory_at(size_t bytes, char* addr, int file_desc = -1);
  static void   split_reserved_memory(char *base, size_t size,
                                      size_t split, bool realloc);
  static bool   commit_memory(char* addr, size_t bytes, bool executable);
  static bool   commit_memory(char* addr, size_t size, size_t alignment_hint,
                              bool executable);
  // Same as commit_memory() that either succeeds or calls
  // vm_exit_out_of_memory() with the specified mesg.
  static void   commit_memory_or_exit(char* addr, size_t bytes,
                                      bool executable, const char* mesg);
  static void   commit_memory_or_exit(char* addr, size_t size,
                                      size_t alignment_hint,
                                      bool executable, const char* mesg);
  static bool   uncommit_memory(char* addr, size_t bytes);
  static bool   release_memory(char* addr, size_t bytes);

  // Touch memory pages that cover the memory range from start to end (exclusive)
  // to make the OS back the memory range with actual memory.
  // Current implementation may not touch the last page if unaligned addresses
  // are passed.
  static void   pretouch_memory(void* start, void* end, size_t page_size = vm_page_size());

  enum ProtType { MEM_PROT_NONE, MEM_PROT_READ, MEM_PROT_RW, MEM_PROT_RWX };
  static bool   protect_memory(char* addr, size_t bytes, ProtType prot,
                               bool is_committed = true);

  static bool   guard_memory(char* addr, size_t bytes);
  static bool   unguard_memory(char* addr, size_t bytes);
  static bool   create_stack_guard_pages(char* addr, size_t bytes);
  static bool   pd_create_stack_guard_pages(char* addr, size_t bytes);
  static bool   remove_stack_guard_pages(char* addr, size_t bytes);
  // Helper function to create a new file with template jvmheap.XXXXXX.
  // Returns a valid fd on success or else returns -1
  static int create_file_for_heap(const char* dir);
  // Map memory to the file referred by fd. This function is slightly different from map_memory()
  // and is added to be used for implementation of -XX:AllocateHeapAt
  static char* map_memory_to_file(char* base, size_t size, int fd);
  // Replace existing reserved memory with file mapping
  static char* replace_existing_mapping_with_file_mapping(char* base, size_t size, int fd);

  static char*  map_memory(int fd, const char* file_name, size_t file_offset,
                           char *addr, size_t bytes, bool read_only = false,
                           bool allow_exec = false);
  static char*  remap_memory(int fd, const char* file_name, size_t file_offset,
                             char *addr, size_t bytes, bool read_only,
                             bool allow_exec);
  static bool   unmap_memory(char *addr, size_t bytes);
  static void   free_memory(char *addr, size_t bytes, size_t alignment_hint);
  static void   realign_memory(char *addr, size_t bytes, size_t alignment_hint);

  // NUMA-specific interface
  static bool   numa_has_static_binding();
  static bool   numa_has_group_homing();
  static void   numa_make_local(char *addr, size_t bytes, int lgrp_hint);
  static void   numa_make_global(char *addr, size_t bytes);
  static size_t numa_get_groups_num();
  static size_t numa_get_leaf_groups(int *ids, size_t size);
  static bool   numa_topology_changed();
  static int    numa_get_group_id();

  // Page manipulation
  struct page_info {
    size_t size;
    int lgrp_id;
  };
  static bool   get_page_info(char *start, page_info* info);
  static char*  scan_pages(char *start, char* end, page_info* page_expected, page_info* page_found);

  static char*  non_memory_address_word();
  // reserve, commit and pin the entire memory region
  static char*  reserve_memory_special(size_t size, size_t alignment,
                                       char* addr, bool executable);
  static bool   release_memory_special(char* addr, size_t bytes);
  static void   large_page_init();
  static size_t large_page_size();
  static bool   can_commit_large_page_memory();
  static bool   can_execute_large_page_memory();

  // OS interface to polling page
  static address get_polling_page()             { return _polling_page; }
  static void    set_polling_page(address page) { _polling_page = page; }
  static bool    is_poll_address(address addr)  { return addr >= _polling_page && addr < (_polling_page + os::vm_page_size()); }
  static void    make_polling_page_unreadable();
  static void    make_polling_page_readable();

  // Check if pointer points to readable memory (by 4-byte read access)
  static bool    is_readable_pointer(const void* p);
  static bool    is_readable_range(const void* from, const void* to);

  // threads

  enum ThreadType {
    vm_thread,
    cgc_thread,        // Concurrent GC thread
    pgc_thread,        // Parallel GC thread
    java_thread,       // Java, CodeCacheSweeper, JVMTIAgent and Service threads.
    compiler_thread,
    watcher_thread,
    os_thread
  };

  static bool create_thread(Thread* thread,
                            ThreadType thr_type,
                            size_t req_stack_size = 0);

  // The "main thread", also known as "starting thread", is the thread
  // that loads/creates the JVM via JNI_CreateJavaVM.
  static bool create_main_thread(JavaThread* thread);

  // The primordial thread is the initial process thread. The java
  // launcher never uses the primordial thread as the main thread, but
  // applications that host the JVM directly may do so. Some platforms
  // need special-case handling of the primordial thread if it attaches
  // to the VM.
  static bool is_primordial_thread(void)
#if defined(_WINDOWS) || defined(BSD)
    // No way to identify the primordial thread.
    { return false; }
#else
  ;
#endif

  static bool create_attached_thread(JavaThread* thread);
  static void pd_start_thread(Thread* thread);
  static void start_thread(Thread* thread);

  static void free_thread(OSThread* osthread);

  // thread id on Linux/64bit is 64bit, on Windows and Solaris, it's 32bit
  static intx current_thread_id();
  static int current_process_id();
  static int sleep(Thread* thread, jlong ms, bool interruptable);
  // Short standalone OS sleep suitable for slow path spin loop.
  // Ignores Thread.interrupt() (so keep it short).
  // ms = 0, will sleep for the least amount of time allowed by the OS.
  static void naked_short_sleep(jlong ms);
  static void infinite_sleep(); // never returns, use with CAUTION
  static void naked_yield () ;
  static OSReturn set_priority(Thread* thread, ThreadPriority priority);
  static OSReturn get_priority(const Thread* const thread, ThreadPriority& priority);

  static void interrupt(Thread* thread);
  static bool is_interrupted(Thread* thread, bool clear_interrupted);

  static int pd_self_suspend_thread(Thread* thread);

  static ExtendedPC fetch_frame_from_context(const void* ucVoid, intptr_t** sp, intptr_t** fp);
  static frame      fetch_frame_from_context(const void* ucVoid);
  static frame      fetch_frame_from_ucontext(Thread* thread, void* ucVoid);

  static void breakpoint();
  static bool start_debugging(char *buf, int buflen);

  static address current_stack_pointer();
  static address current_stack_base();
  static size_t current_stack_size();

  static void verify_stack_alignment() PRODUCT_RETURN;

  static bool message_box(const char* title, const char* message);
  static char* do_you_want_to_debug(const char* message);

  // run cmd in a separate process and return its exit code; or -1 on failures
  static int fork_and_exec(char *cmd, bool use_vfork_if_available = false);

  // Call ::exit() on all platforms but Windows
  static void exit(int num);

  // Terminate the VM, but don't exit the process
  static void shutdown();

  // Terminate with an error.  Default is to generate a core file on platforms
  // that support such things.  This calls shutdown() and then aborts.
  static void abort(bool dump_core, void *siginfo, const void *context);
  static void abort(bool dump_core = true);

  // Die immediately, no exit hook, no abort hook, no cleanup.
  static void die();

  // File i/o operations
  static const int default_file_open_flags();
  static int open(const char *path, int oflag, int mode);
  static FILE* open(int fd, const char* mode);
  static FILE* fopen(const char* path, const char* mode);
  static int close(int fd);
  static jlong lseek(int fd, jlong offset, int whence);
  // This function, on Windows, canonicalizes a given path (see os_windows.cpp for details).
  // On Posix, this function is a noop: it does not change anything and just returns
  // the input pointer.
  static char* native_path(char *path);
  static int ftruncate(int fd, jlong length);
  static int fsync(int fd);
  static int available(int fd, jlong *bytes);
  static int get_fileno(FILE* fp);
  static void flockfile(FILE* fp);
  static void funlockfile(FILE* fp);

  static int compare_file_modified_times(const char* file1, const char* file2);

  //File i/o operations

  static size_t read(int fd, void *buf, unsigned int nBytes);
  static size_t read_at(int fd, void *buf, unsigned int nBytes, jlong offset);
  static size_t restartable_read(int fd, void *buf, unsigned int nBytes);
  static size_t write(int fd, const void *buf, unsigned int nBytes);

  // Reading directories.
  static DIR*           opendir(const char* dirname);
  static struct dirent* readdir(DIR* dirp);
  static int            closedir(DIR* dirp);

  // Dynamic library extension
  static const char*    dll_file_extension();

  static const char*    get_temp_directory();
  static const char*    get_current_directory(char *buf, size_t buflen);

  // Builds the platform-specific name of a library.
  // Returns false if the buffer is too small.
  static bool           dll_build_name(char* buffer, size_t size,
                                       const char* fname);

  // Builds a platform-specific full library path given an ld path and
  // unadorned library name. Returns true if the buffer contains a full
  // path to an existing file, false otherwise. If pathname is empty,
  // uses the path to the current directory.
  static bool           dll_locate_lib(char* buffer, size_t size,
                                       const char* pathname, const char* fname);

  // Symbol lookup, find nearest function name; basically it implements
  // dladdr() for all platforms. Name of the nearest function is copied
  // to buf. Distance from its base address is optionally returned as offset.
  // If function name is not found, buf[0] is set to '\0' and offset is
  // set to -1 (if offset is non-NULL).
  static bool dll_address_to_function_name(address addr, char* buf,
                                           int buflen, int* offset,
                                           bool demangle = true);

  // Locate DLL/DSO. On success, full path of the library is copied to
  // buf, and offset is optionally set to be the distance between addr
  // and the library's base address. On failure, buf[0] is set to '\0'
  // and offset is set to -1 (if offset is non-NULL).
  static bool dll_address_to_library_name(address addr, char* buf,
                                          int buflen, int* offset);

  // Find out whether the pc is in the static code for jvm.dll/libjvm.so.
  static bool address_is_in_vm(address addr);

  // Loads .dll/.so and
  // in case of error it checks if .dll/.so was built for the
  // same architecture as HotSpot is running on
  static void* dll_load(const char *name, char *ebuf, int ebuflen);

  // lookup symbol in a shared library
  static void* dll_lookup(void* handle, const char* name);

  // Unload library
  static void  dll_unload(void *lib);

  // Callback for loaded module information
  // Input parameters:
  //    char*     module_file_name,
  //    address   module_base_addr,
  //    address   module_top_addr,
  //    void*     param
  typedef int (*LoadedModulesCallbackFunc)(const char *, address, address, void *);

  static int get_loaded_modules_info(LoadedModulesCallbackFunc callback, void *param);

  // Return the handle of this process
  static void* get_default_process_handle();

  // Check for static linked agent library
  static bool find_builtin_agent(AgentLibrary *agent_lib, const char *syms[],
                                 size_t syms_len);

  // Find agent entry point
  static void *find_agent_function(AgentLibrary *agent_lib, bool check_lib,
                                   const char *syms[], size_t syms_len);

  // Provide C99 compliant versions of these functions, since some versions
  // of some platforms don't.
  static int vsnprintf(char* buf, size_t len, const char* fmt, va_list args) ATTRIBUTE_PRINTF(3, 0);
  static int snprintf(char* buf, size_t len, const char* fmt, ...) ATTRIBUTE_PRINTF(3, 4);

  // Get host name in buffer provided
  static bool get_host_name(char* buf, size_t buflen);

  // Print out system information; they are called by fatal error handler.
  // Output format may be different on different platforms.
  static void print_os_info(outputStream* st);
  static void print_os_info_brief(outputStream* st);
  static void print_cpu_info(outputStream* st, char* buf, size_t buflen);
  static void pd_print_cpu_info(outputStream* st, char* buf, size_t buflen);
  static void print_summary_info(outputStream* st, char* buf, size_t buflen);
  static void print_memory_info(outputStream* st);
  static void print_dll_info(outputStream* st);
  static void print_environment_variables(outputStream* st, const char** env_list);
  static void print_context(outputStream* st, const void* context);
  static void print_register_info(outputStream* st, const void* context);
  static void print_siginfo(outputStream* st, const void* siginfo);
  static void print_signal_handlers(outputStream* st, char* buf, size_t buflen);
  static void print_date_and_time(outputStream* st, char* buf, size_t buflen);

  static void print_location(outputStream* st, intptr_t x, bool verbose = false);
  static size_t lasterror(char *buf, size_t len);
  static int get_last_error();

  // Replacement for strerror().
  // Will return the english description of the error (e.g. "File not found", as
  //  suggested in the POSIX standard.
  // Will return "Unknown error" for an unknown errno value.
  // Will not attempt to localize the returned string.
  // Will always return a valid string which is a static constant.
  // Will not change the value of errno.
  static const char* strerror(int e);

  // Will return the literalized version of the given errno (e.g. "EINVAL"
  //  for EINVAL).
  // Will return "Unknown error" for an unknown errno value.
  // Will always return a valid string which is a static constant.
  // Will not change the value of errno.
  static const char* errno_name(int e);

  // Determines whether the calling process is being debugged by a user-mode debugger.
  static bool is_debugger_attached();

  // wait for a key press if PauseAtExit is set
  static void wait_for_keypress_at_exit(void);

  // The following two functions are used by fatal error handler to trace
  // native (C) frames. They are not part of frame.hpp/frame.cpp because
  // frame.hpp/cpp assume thread is JavaThread, and also because different
  // OS/compiler may have different convention or provide different API to
  // walk C frames.
  //
  // We don't attempt to become a debugger, so we only follow frames if that
  // does not require a lookup in the unwind table, which is part of the binary
  // file but may be unsafe to read after a fatal error. So on x86, we can
  // only walk stack if %ebp is used as frame pointer; on ia64, it's not
  // possible to walk C stack without having the unwind table.
  static bool is_first_C_frame(frame *fr);
  static frame get_sender_for_C_frame(frame *fr);

  // return current frame. pc() and sp() are set to NULL on failure.
  static frame      current_frame();

  static void print_hex_dump(outputStream* st, address start, address end, int unitsize);

  // returns a string to describe the exception/signal;
  // returns NULL if exception_code is not an OS exception/signal.
  static const char* exception_name(int exception_code, char* buf, size_t buflen);

  // Returns the signal number (e.g. 11) for a given signal name (SIGSEGV).
  static int get_signal_number(const char* signal_name);

  // Returns native Java library, loads if necessary
  static void*    native_java_library();

  // Fills in path to jvm.dll/libjvm.so (used by the Disassembler)
  static void     jvm_path(char *buf, jint buflen);

  // JNI names
  static void     print_jni_name_prefix_on(outputStream* st, int args_size);
  static void     print_jni_name_suffix_on(outputStream* st, int args_size);

  // Init os specific system properties values
  static void init_system_properties_values();

  // IO operations, non-JVM_ version.
  static int stat(const char* path, struct stat* sbuf);
  static bool dir_is_empty(const char* path);

  // IO operations on binary files
  static int create_binary_file(const char* path, bool rewrite_existing);
  static jlong current_file_offset(int fd);
  static jlong seek_to_file_offset(int fd, jlong offset);

  // Retrieve native stack frames.
  // Parameter:
  //   stack:  an array to storage stack pointers.
  //   frames: size of above array.
  //   toSkip: number of stack frames to skip at the beginning.
  // Return: number of stack frames captured.
  static int get_native_stack(address* stack, int size, int toSkip = 0);

  // General allocation (must be MT-safe)
  static void* malloc  (size_t size, MEMFLAGS flags, const NativeCallStack& stack);
  static void* malloc  (size_t size, MEMFLAGS flags);
  static void* realloc (void *memblock, size_t size, MEMFLAGS flag, const NativeCallStack& stack);
  static void* realloc (void *memblock, size_t size, MEMFLAGS flag);

  static void  free    (void *memblock);
  static char* strdup(const char *, MEMFLAGS flags = mtInternal);  // Like strdup
  // Like strdup, but exit VM when strdup() returns NULL
  static char* strdup_check_oom(const char*, MEMFLAGS flags = mtInternal);

#ifndef PRODUCT
  static julong num_mallocs;         // # of calls to malloc/realloc
  static julong alloc_bytes;         // # of bytes allocated
  static julong num_frees;           // # of calls to free
  static julong free_bytes;          // # of bytes freed
#endif

  // SocketInterface (ex HPI SocketInterface )
  static int socket(int domain, int type, int protocol);
  static int socket_close(int fd);
  static int recv(int fd, char* buf, size_t nBytes, uint flags);
  static int send(int fd, char* buf, size_t nBytes, uint flags);
  static int raw_send(int fd, char* buf, size_t nBytes, uint flags);
  static int connect(int fd, struct sockaddr* him, socklen_t len);
  static struct hostent* get_host_by_name(char* name);

  // Support for signals (see JVM_RaiseSignal, JVM_RegisterSignal)
  static void  initialize_jdk_signal_support(TRAPS);
  static void  signal_notify(int signal_number);
  static void* signal(int signal_number, void* handler);
  static void  signal_raise(int signal_number);
  static int   signal_wait();
  static void* user_handler();
  static void  terminate_signal_thread();
  static int   sigexitnum_pd();

  // random number generation
  static int random();                     // return 32bit pseudorandom number
  static void init_random(unsigned int initval);    // initialize random sequence

  // Structured OS Exception support
  static void os_exception_wrapper(java_call_t f, JavaValue* value, const methodHandle& method, JavaCallArguments* args, Thread* thread);

  // On Posix compatible OS it will simply check core dump limits while on Windows
  // it will check if dump file can be created. Check or prepare a core dump to be
  // taken at a later point in the same thread in os::abort(). Use the caller
  // provided buffer as a scratch buffer. The status message which will be written
  // into the error log either is file location or a short error message, depending
  // on the checking result.
  static void check_dump_limit(char* buffer, size_t bufferSize);

  // Get the default path to the core file
  // Returns the length of the string
  static int get_core_path(char* buffer, size_t bufferSize);

  // JVMTI & JVM monitoring and management support
  // The thread_cpu_time() and current_thread_cpu_time() are only
  // supported if is_thread_cpu_time_supported() returns true.
  // They are not supported on Solaris T1.

  // Thread CPU Time - return the fast estimate on a platform
  // On Solaris - call gethrvtime (fast) - user time only
  // On Linux   - fast clock_gettime where available - user+sys
  //            - otherwise: very slow /proc fs - user+sys
  // On Windows - GetThreadTimes - user+sys
  static jlong current_thread_cpu_time();
  static jlong thread_cpu_time(Thread* t);

  // Thread CPU Time with user_sys_cpu_time parameter.
  //
  // If user_sys_cpu_time is true, user+sys time is returned.
  // Otherwise, only user time is returned
  static jlong current_thread_cpu_time(bool user_sys_cpu_time);
  static jlong thread_cpu_time(Thread* t, bool user_sys_cpu_time);

  // Return a bunch of info about the timers.
  // Note that the returned info for these two functions may be different
  // on some platforms
  static void current_thread_cpu_time_info(jvmtiTimerInfo *info_ptr);
  static void thread_cpu_time_info(jvmtiTimerInfo *info_ptr);

  static bool is_thread_cpu_time_supported();

  // System loadavg support.  Returns -1 if load average cannot be obtained.
  static int loadavg(double loadavg[], int nelem);

  // Amount beyond the callee frame size that we bang the stack.
  static int extra_bang_size_in_bytes();

  static char** split_path(const char* path, int* n);

  // Extensions
#include "runtime/os_ext.hpp"

 public:
  class CrashProtectionCallback : public StackObj {
  public:
    virtual void call() = 0;
  };

  // Platform dependent stuff
#ifndef _WINDOWS
# include "os_posix.hpp"
#endif
#include OS_CPU_HEADER(os)
#include OS_HEADER(os)

#ifndef OS_NATIVE_THREAD_CREATION_FAILED_MSG
#define OS_NATIVE_THREAD_CREATION_FAILED_MSG "unable to create native thread: possibly out of memory or process/resource limits reached"
#endif

 public:
#ifndef PLATFORM_PRINT_NATIVE_STACK
  // No platform-specific code for printing the native stack.
  static bool platform_print_native_stack(outputStream* st, const void* context,
                                          char *buf, int buf_size) {
    return false;
  }
#endif

  // debugging support (mostly used by debug.cpp but also fatal error handler)
  static bool find(address pc, outputStream* st = tty); // OS specific function to make sense out of an address

  static bool dont_yield();                     // when true, JVM_Yield() is nop
  static void print_statistics();

  // Thread priority helpers (implemented in OS-specific part)
  static OSReturn set_native_priority(Thread* thread, int native_prio);
  static OSReturn get_native_priority(const Thread* const thread, int* priority_ptr);
  static int java_to_os_priority[CriticalPriority + 1];
  // Hint to the underlying OS that a task switch would not be good.
  // Void return because it's a hint and can fail.
  static const char* native_thread_creation_failed_msg() {
    return OS_NATIVE_THREAD_CREATION_FAILED_MSG;
  }

  // Used at creation if requested by the diagnostic flag PauseAtStartup.
  // Causes the VM to wait until an external stimulus has been applied
  // (for Unix, that stimulus is a signal, for Windows, an external
  // ResumeThread call)
  static void pause();

  // Builds a platform dependent Agent_OnLoad_<libname> function name
  // which is used to find statically linked in agents.
  static char*  build_agent_function_name(const char *sym, const char *cname,
                                          bool is_absolute_path);

  class SuspendedThreadTaskContext {
  public:
    SuspendedThreadTaskContext(Thread* thread, void *ucontext) : _thread(thread), _ucontext(ucontext) {}
    Thread* thread() const { return _thread; }
    void* ucontext() const { return _ucontext; }
  private:
    Thread* _thread;
    void* _ucontext;
  };

  class SuspendedThreadTask {
  public:
    SuspendedThreadTask(Thread* thread) : _thread(thread), _done(false) {}
    void run();
    bool is_done() { return _done; }
    virtual void do_task(const SuspendedThreadTaskContext& context) = 0;
  protected:
    ~SuspendedThreadTask() {}
  private:
    void internal_do_task();
    Thread* _thread;
    bool _done;
  };

#ifndef _WINDOWS
  // Suspend/resume support
  // Protocol:
  //
  // a thread starts in SR_RUNNING
  //
  // SR_RUNNING can go to
  //   * SR_SUSPEND_REQUEST when the WatcherThread wants to suspend it
  // SR_SUSPEND_REQUEST can go to
  //   * SR_RUNNING if WatcherThread decides it waited for SR_SUSPENDED too long (timeout)
  //   * SR_SUSPENDED if the stopped thread receives the signal and switches state
  // SR_SUSPENDED can go to
  //   * SR_WAKEUP_REQUEST when the WatcherThread has done the work and wants to resume
  // SR_WAKEUP_REQUEST can go to
  //   * SR_RUNNING when the stopped thread receives the signal
  //   * SR_WAKEUP_REQUEST on timeout (resend the signal and try again)
  class SuspendResume {
   public:
    enum State {
      SR_RUNNING,
      SR_SUSPEND_REQUEST,
      SR_SUSPENDED,
      SR_WAKEUP_REQUEST
    };

  private:
    volatile State _state;

  private:
    /* try to switch state from state "from" to state "to"
     * returns the state set after the method is complete
     */
    State switch_state(State from, State to);

  public:
    SuspendResume() : _state(SR_RUNNING) { }

    State state() const { return _state; }

    State request_suspend() {
      return switch_state(SR_RUNNING, SR_SUSPEND_REQUEST);
    }

    State cancel_suspend() {
      return switch_state(SR_SUSPEND_REQUEST, SR_RUNNING);
    }

    State suspended() {
      return switch_state(SR_SUSPEND_REQUEST, SR_SUSPENDED);
    }

    State request_wakeup() {
      return switch_state(SR_SUSPENDED, SR_WAKEUP_REQUEST);
    }

    State running() {
      return switch_state(SR_WAKEUP_REQUEST, SR_RUNNING);
    }

    bool is_running() const {
      return _state == SR_RUNNING;
    }

    bool is_suspend_request() const {
      return _state == SR_SUSPEND_REQUEST;
    }

    bool is_suspended() const {
      return _state == SR_SUSPENDED;
    }
  };
#endif // !WINDOWS


 protected:
  static volatile unsigned int _rand_seed;    // seed for random number generator
  static int _processor_count;                // number of processors
  static int _initial_active_processor_count; // number of active processors during initialization.

  static char* format_boot_path(const char* format_string,
                                const char* home,
                                int home_len,
                                char fileSep,
                                char pathSep);
  static bool set_boot_path(char fileSep, char pathSep);

};
```

```cpp
// share/adlc/arena.cpp
void* AllocateHeap(size_t size) {
  unsigned char* ptr = (unsigned char*) malloc(size);
  if (ptr == NULL && size != 0) {
    fprintf(stderr, "Error: Out of memory in ADLC\n"); // logging can cause crash!
    fflush(stderr);
    exit(1);
  }
  return ptr;
}

```

### CollectedHeap

![](../Collection/img/CollectedHeap.svg)

```cpp
class CollectedHeap : public CHeapObj<mtInternal> {
  virtual oop obj_allocate(Klass* klass, int size, TRAPS);
  virtual oop array_allocate(Klass* klass, int size, int length, bool do_zero, TRAPS);
  virtual oop class_allocate(Klass* klass, int size, TRAPS);
}
```

```cpp
class Universe: AllStatic {

  // The particular choice of collected heap.
  static CollectedHeap* _collectedHeap;
  
  static CollectedHeap* create_heap();
  
  // The particular choice of collected heap.
  static CollectedHeap* heap() { return _collectedHeap; }
}  
```

### CollectorPolicy

![](img/CollectorPolicy.svg)

```cpp
span
```

### universe_init

```cpp
// share/memory/universe.cpp
jint universe_init() {
  assert(!Universe::_fully_initialized, "called after initialize_vtables");
  guarantee(1 << LogHeapWordSize == sizeof(HeapWord),
         "LogHeapWordSize is incorrect.");
  guarantee(sizeof(oop) >= sizeof(HeapWord), "HeapWord larger than oop?");
  guarantee(sizeof(oop) % sizeof(HeapWord) == 0,
            "oop size is not not a multiple of HeapWord size");

  TraceTime timer("Genesis", TRACETIME_LOG(Info, startuptime));

  JavaClasses::compute_hard_coded_offsets();

  initialize_global_behaviours();
```

initialize_heap

```cpp
  jint status = Universe::initialize_heap();
  if (status != JNI_OK) {
    return status;
  }

  SystemDictionary::initialize_oop_storage();

  Metaspace::global_initialize();

  // Initialize performance counters for metaspaces
  MetaspaceCounters::initialize_performance_counters();
  CompressedClassSpaceCounters::initialize_performance_counters();

  AOTLoader::universe_init();

  // Checks 'AfterMemoryInit' constraints.
  if (!JVMFlagConstraintList::check_constraints(JVMFlagConstraint::AfterMemoryInit)) {
    return JNI_EINVAL;
  }

  // Create memory for metadata.  Must be after initializing heap for
  // DumpSharedSpaces.
  ClassLoaderData::init_null_class_loader_data();

  // We have a heap so create the Method* caches before
  // Metaspace::initialize_shared_spaces() tries to populate them.
  Universe::_finalizer_register_cache = new LatestMethodCache();
  Universe::_loader_addClass_cache    = new LatestMethodCache();
  Universe::_throw_illegal_access_error_cache = new LatestMethodCache();
  Universe::_do_stack_walk_cache = new LatestMethodCache();

#if INCLUDE_CDS
  if (UseSharedSpaces) {
    // Read the data structures supporting the shared spaces (shared
    // system dictionary, symbol table, etc.).  After that, access to
    // the file (other than the mapped regions) is no longer needed, and
    // the file is closed. Closing the file does not affect the
    // currently mapped regions.
    MetaspaceShared::initialize_shared_spaces();
    StringTable::create_table();
  } else
#endif
  {
    SymbolTable::create_table();
    StringTable::create_table();

#if INCLUDE_CDS
    if (DumpSharedSpaces) {
      MetaspaceShared::prepare_for_dumping();
    }
#endif
  }
  if (strlen(VerifySubSet) > 0) {
    Universe::initialize_verify_flags();
  }

  ResolvedMethodTable::create_table();

  return JNI_OK;
}
```

### initialize_heap

Choose the heap base address and oop encoding mode when compressed oops are used:

- Unscaled  - Use 32-bits oops without encoding when NarrowOopHeapBaseMin + heap_size < 4Gb
- ZeroBased - Use zero based compressed oops with encoding when NarrowOopHeapBaseMin + heap_size < 32Gb
- HeapBased - Use compressed oops with heap base + encoding.

```cpp
// share/memory/universe.cpp
jint Universe::initialize_heap() {
  _collectedHeap = create_heap();
  jint status = _collectedHeap->initialize();
  if (status != JNI_OK) {
    return status;
  }
  log_info(gc)("Using %s", _collectedHeap->name());

  ThreadLocalAllocBuffer::set_max_size(Universe::heap()->max_tlab_size());

#ifdef _LP64
  if (UseCompressedOops) {
    // Subtract a page because something can get allocated at heap base.
    // This also makes implicit null checking work, because the
    // memory+1 page below heap_base needs to cause a signal.
    // See needs_explicit_null_check.
    // Only set the heap base for compressed oops because it indicates
    // compressed oops for pstack code.
    if ((uint64_t)Universe::heap()->reserved_region().end() > UnscaledOopHeapMax) {
      // Didn't reserve heap below 4Gb.  Must shift.
      Universe::set_narrow_oop_shift(LogMinObjAlignmentInBytes);
    }
    if ((uint64_t)Universe::heap()->reserved_region().end() <= OopEncodingHeapMax) {
      // Did reserve heap below 32Gb. Can use base == 0;
      Universe::set_narrow_oop_base(0);
    }
    AOTLoader::set_narrow_oop_shift();

    Universe::set_narrow_ptrs_base(Universe::narrow_oop_base());

    LogTarget(Info, gc, heap, coops) lt;
    if (lt.is_enabled()) {
      ResourceMark rm;
      LogStream ls(lt);
      Universe::print_compressed_oops_mode(&ls);
    }

    // Tell tests in which mode we run.
    Arguments::PropertyList_add(new SystemProperty("java.vm.compressedOopsMode",
                                                   narrow_oop_mode_to_string(narrow_oop_mode()),
                                                   false));
  }
  // Universe::narrow_oop_base() is one page below the heap.
  assert((intptr_t)Universe::narrow_oop_base() <= (intptr_t)(Universe::heap()->base() -
         os::vm_page_size()) ||
         Universe::narrow_oop_base() == NULL, "invalid value");
  assert(Universe::narrow_oop_shift() == LogMinObjAlignmentInBytes ||
         Universe::narrow_oop_shift() == 0, "invalid value");
#endif

  // We will never reach the CATCH below since Exceptions::_throw will cause
  // the VM to exit if an exception is thrown during initialization

  if (UseTLAB) {
    assert(Universe::heap()->supports_tlab_allocation(),
           "Should support thread-local allocation buffers");
    ThreadLocalAllocBuffer::startup_initialization();
  }
  return JNI_OK;
}
```

```cpp
CollectedHeap* Universe::create_heap() {
  assert(_collectedHeap == NULL, "Heap already created");
  return GCConfig::arguments()->create_heap();
}
```

create_heap() implemented by different collector Arguments

Such as g1Arguments

```cpp
// share/gc/g1/g1Arguments.cpp
CollectedHeap* G1Arguments::create_heap() {
  if (AllocateOldGenAt != NULL) {
    return create_heap_with_policy<G1CollectedHeap, G1HeterogeneousCollectorPolicy>();
  } else {
    return create_heap_with_policy<G1CollectedHeap, G1CollectorPolicy>();
  }
}
```

## Tuning

```shell
java -XX:+PrintFlagsFinal -XX:+UnlockDiagnosticVMOptions -version
```

### OOM


The -XX:HeapDumpOnOutOfMemoryError Option
This option tells the Java HotSpot VM to generate a heap dump when an allocation from the Java heap or the permanent generation cannot be satisfied. 
There is no overhead in running with this option, so it can be useful for production systems where the OutOfMemoryError exception takes a long time to surface.
You can also specify this option at runtime with the MBeans tab in the JConsole utility.


容器环境下
- 无法生成dump文件
  - 中间层目录没创建 FileNotFoundException
  - 对外内存不足 



```shell
jmap -heap <pid>
```

dumpfile
```shell
jmap -dump:format=b
```
with jvisualvm


## Links

- [JDK](/docs/CS/Java/JDK/JDK.md)

## References

1. [Java T point](https://www.javatpoint.com/jvm-java-virtual-machine)
2. [The Java® Virtual Machine Specification Java SE 17 Edition](https://docs.oracle.com/javase/specs/jvms/se17/html/)
3. [深入理解Java虚拟机（第3版）- 周志明](https://book.douban.com/subject/34907497/)
4. [Java虚拟机精讲]
5. [实战JAVA虚拟机 JVM故障诊断与性能优化]
6. [自己动手写Java虚拟机]
7. [深入浅出：Java虚拟机设计与实现]
8. [揭秘Java虚拟机：JVM设计原理与实现]
9. [虚拟机设计与实现：以JVM为例]
10. [深入解析Java虚拟机HotSpot]
11. [HotSpot实战]
12. [深入Java虚拟机：JVM G1 GC的算法与实现]
13. [深入探索JVM垃圾回收]
14. [JVM G1源码分析和调优]
15. [新一代垃圾回收器-ZGC设计与实现]
16. [深入剖析Java虚拟机 : 源码剖析与实例详解（基础卷）]
