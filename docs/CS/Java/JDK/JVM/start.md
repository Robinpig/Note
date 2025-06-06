## Introduction

## build

[Building the JDK](https://github.com/openjdk/jdk/blob/master/doc/building.md)

write a Hello.java and compile it

-XX:+PauseAtStartup
-XX:+PauseAtExit

```shell
gdb -args java Hello
gdb> b java.c:JavaMain
```

regression test jtreg
based on JDK12

## Entry



Windows

jvm.dll



Bootstrap ClassLoader





虚拟机的生命周期





main-> JLI_Launch -> JVMInit -> ContinueInNewThread -> [JavaMain](/docs/CS/Java/JDK/JVM/start.md?id=JavaMain)

```c
// main.c
JNIEXPORT int
main(int argc, char **argv)
{
    return JLI_Launch(margc, ...);
}


// java.c
JNIEXPORT int JNICALL
JLI_Launch(int argc, char ** argv, ...)
{
    return JVMInit(&ifn, threadStackSize, argc, argv, mode, what, ret);
}


// java_md_macosx.m
// MacOSX we may continue in the same thread
int JVMInit(InvocationFunctions* ifn, jlong threadStackSize, ...) {
   return ContinueInNewThread(ifn, threadStackSize, argc, argv, mode, what, ret);
}


// java.c
int
ContinueInNewThread(InvocationFunctions* ifn, jlong threadStackSize, ...)
{
    return ContinueInNewThread0(JavaMain, threadStackSize, (void*)&args);
}
```

Block current thread and continue execution in a new thread(JavaThread).

```c
int
CallJavaMainInNewThread(jlong stack_size, void* args) {
    int rslt;
    pthread_t tid;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_JOINABLE);
    size_t adjusted_stack_size;

    if (stack_size > 0) {
        if (pthread_attr_setstacksize(&attr, stack_size) == EINVAL) {
            // System may require stack size to be multiple of page size
            // Retry with adjusted value
            adjusted_stack_size = adjustStackSize(stack_size);
            if (adjusted_stack_size != (size_t) stack_size) {
                pthread_attr_setstacksize(&attr, adjusted_stack_size);
            }
        }
    }
    pthread_attr_setguardsize(&attr, 0); // no pthread guard page on java threads

    if (pthread_create(&tid, &attr, ThreadJavaMain, args) == 0) {
        void* tmp;
        pthread_join(tid, &tmp);
        rslt = (int)(intptr_t)tmp;
    } else {
       /*
        * Continue execution in current thread if for some reason (e.g. out of
        * memory/LWP)  a new thread can't be created. This will likely fail
        * later in JavaMain as JNI_CreateJavaVM needs to create quite a
        * few new threads, anyway, just give it a try..
        */
        rslt = JavaMain(args);
    }

    pthread_attr_destroy(&attr);
    return rslt;
}
```

#### JavaMain

- InitializeJVM  -> JNI_CreateJavaVM -> [Thread.create_vm](/docs/CS/Java/JDK/JVM/start.md?id=create_vm)
- [Invoke main method](/docs/CS/Java/JDK/JVM/start.md?id=MainClass)
- [DestroyJavaVM](/docs/CS/Java/JDK/JVM/destroy.md?id=destroy_vm)

```cpp
// java.c
int
JavaMain(void* _args)
{
    if (!InitializeJVM(&vm, &env, &ifn)) {
        exit(1);
    }

    mainClass = LoadMainClass(env, mode, what);
    mainID = (*env)->GetStaticMethodID(env, mainClass, "main",
    (*env)->CallStaticVoidMethod(env, mainClass, mainID, mainArgs);

    LEAVE();

    #define LEAVE() \
    do { \
        if ((*vm)->DetachCurrentThread(vm) != JNI_OK) { \
            JLI_ReportErrorMessage(JVM_ERROR2); \
            ret = 1; \
        } \
        if (JNI_TRUE) { \
            (*vm)->DestroyJavaVM(vm); \
            return ret; \
        } \
    } while (JNI_FALSE)
```
 
## create_vm

1. Initialize library-based TLS
2. Initialize the output stream module
3. Initialize the os module
4. os::init_container_support()
5. Initialize global data structures and create system classes in heap
6. Attach the main thread to this os thread
7. Enable guard page *after* os::create_main_thread()
8. Initialize Java-Level synchronization subsystem
9. Initialize global modules
10. Create the VMThread
11. initialize_java_lang_classes
12. start Signal Dispatcher before VMInit event is posted
13. initialize compiler(s)
14. post vm initialized


JVM 在一开始的时候就会根据 -Xmx,-XX:MaxMetaspaceSize 指定的大小预先向操作系统申请一批内存作为 reserve_memory。这部分 reserve_memory 的权限就是 PROT_NONE ，是不可访问的。用于首先确定 JVM 堆和 MetaSpace 这些内存区域的地址范围（首先划分势力范围）



char* os::reserve_memory(size_t bytes, bool executable, MEMFLAGS flags) {
  char* result = pd_reserve_memory(bytes, executable);
  if (result != nullptr) {
    MemTracker::record_virtual_memory_reserve(result, bytes, CALLER_PC, flags);
  }
  return result;
}

// os_linux.cpp
char* os::pd_reserve_memory(size_t bytes, bool exec) {
  return anon_mmap(nullptr, bytes);
}

static char* anon_mmap(char* requested_addr, size_t bytes) {
  // MAP_FIXED is intentionally left out, to leave existing mappings intact.
  const int flags = MAP_PRIVATE | MAP_NORESERVE | MAP_ANONYMOUS;

  // Map reserved/uncommitted pages PROT_NONE so we fail early if we
  // touch an uncommitted page. Otherwise, the read/write might
  // succeed if we have enough swap space to back the physical page.
  char* addr = (char*)::mmap(requested_addr, bytes, PROT_NONE, flags, -1, 0);

  return addr == MAP_FAILED ? nullptr : addr;
}


当 JVM 真正需要内存的时候，就会从这部分 reserve_memory 中划分出一部分（commit_memory）来使用 —— JVM 通过 mmap 重新映射 commit_memory 大小的虚拟内存出来

JVM 在调用 mmap 重新映射的时候，flags 参数指定了 MAP_FIXED 标志，强制内核从之前的 reserve_memory 中重新映射。参数 prot  重新指定了 PROT_READ | PROT_WRITE 权限



// os_linux.cpp
bool os::pd_commit_memory(char* addr, size_t size, bool exec) {
  return os::Linux::commit_memory_impl(addr, size, exec) == 0;
}

int os::Linux::commit_memory_impl(char* addr, size_t size, bool exec) {
  int prot = exec ? PROT_READ|PROT_WRITE|PROT_EXEC : PROT_READ|PROT_WRITE;
  uintptr_t res = (uintptr_t) ::mmap(addr, size, prot,
                                     MAP_PRIVATE|MAP_FIXED|MAP_ANONYMOUS, -1, 0);
  if (res != (uintptr_t) MAP_FAILED) {
    if (UseNUMAInterleaving) {
      numa_make_global(addr, size);
    }
    return 0;
  }
  
  
  



```cpp
// thread.cpp
jint Threads::create_vm(JavaVMInitArgs* args, bool* canTryAgain) {
  extern void JDK_Version_init();

  // Preinitialize version info.
  VM_Version::early_initialize();

  // Check version
  if (!is_supported_jni_version(args->version)) return JNI_EVERSION;

  // Initialize library-based TLS
  ThreadLocalStorage::init();

  // Initialize the output stream module
  ostream_init();

  // Process java launcher properties.
  Arguments::process_sun_java_launcher_properties(args);

  // Initialize the os module
  os::init();

  // Record VM creation timing statistics
  TraceVmCreationTime create_vm_timer;
  create_vm_timer.start();

  // Initialize system properties.
  Arguments::init_system_properties();

  // So that JDK version can be used as a discriminator when parsing arguments
  JDK_Version_init();

  // Update/Initialize System properties after JDK version number is known
  Arguments::init_version_specific_system_properties();

  // Make sure to initialize log configuration *before* parsing arguments
  LogConfiguration::initialize(create_vm_timer.begin_time());

  // Parse arguments
  // Note: this internally calls os::init_container_support()
  jint parse_result = Arguments::parse(args);
  if (parse_result != JNI_OK) return parse_result;

  os::init_before_ergo();

  jint ergo_result = Arguments::apply_ergo();
  if (ergo_result != JNI_OK) return ergo_result;

  // Final check of all ranges after ergonomics which may change values.
  if (!JVMFlagRangeList::check_ranges()) {
    return JNI_EINVAL;
  }

  // Final check of all 'AfterErgo' constraints after ergonomics which may change values.
  bool constraint_result = JVMFlagConstraintList::check_constraints(JVMFlagConstraint::AfterErgo);
  if (!constraint_result) {
    return JNI_EINVAL;
  }

  JVMFlagWriteableList::mark_startup();

  if (PauseAtStartup) {
    os::pause();
  }

  HOTSPOT_VM_INIT_BEGIN();

  // Timing (must come after argument parsing)
  TraceTime timer("Create VM", TRACETIME_LOG(Info, startuptime));
  
  #ifdef CAN_SHOW_REGISTERS_ON_ASSERT
    // Initialize assert poison page mechanism.
    if (ShowRegistersOnAssert) {
      initialize_assert_poison();
    }
  #endif // CAN_SHOW_REGISTERS_ON_ASSERT

  // Initialize the os module after parsing the args
  jint os_init_2_result = os::init_2();
  if (os_init_2_result != JNI_OK) return os_init_2_result;

  SafepointMechanism::initialize();

  jint adjust_after_os_result = Arguments::adjust_after_os();
  if (adjust_after_os_result != JNI_OK) return adjust_after_os_result;

  // Initialize output stream logging
  ostream_init_log();

  // Convert -Xrun to -agentlib: if there is no JVM_OnLoad
  // Must be before create_vm_init_agents()
  if (Arguments::init_libraries_at_startup()) {
    convert_vm_init_libraries_to_agents();
  }

  // Launch -agentlib/-agentpath and converted -Xrun agents
  if (Arguments::init_agents_at_startup()) {
    create_vm_init_agents();
  }

  // Initialize Threads state
  _thread_list = NULL;
  _number_of_threads = 0;
  _number_of_non_daemon_threads = 0;

  // Initialize global data structures and create system classes in heap
  vm_init_globals();

  #if INCLUDE_JVMCI
    if (JVMCICounterSize > 0) {
      JavaThread::_jvmci_old_thread_counters = NEW_C_HEAP_ARRAY(jlong, JVMCICounterSize, mtInternal);
      memset(JavaThread::_jvmci_old_thread_counters, 0, sizeof(jlong) * JVMCICounterSize);
    } else {
      JavaThread::_jvmci_old_thread_counters = NULL;
    }
  #endif // INCLUDE_JVMCI
```

Attach the main thread to this os thread

```cpp
  JavaThread* main_thread = new JavaThread();
  main_thread->set_thread_state(_thread_in_vm);
  main_thread->initialize_thread_current();
  // must do this before set_active_handles
  main_thread->record_stack_base_and_size();
  main_thread->register_thread_stack_with_NMT();
  main_thread->set_active_handles(JNIHandleBlock::allocate_block());

  if (!main_thread->set_as_starting_thread()) {
    vm_shutdown_during_initialization(
                                      "Failed necessary internal allocation. Out of swap space");
    main_thread->smr_delete();
    *canTryAgain = false; // don't let caller call JNI_CreateJavaVM again
    return JNI_ENOMEM;
  }
```

Enable guard page *after* os::create_main_thread(), otherwise it would crash Linux VM, see notes in `os_linux.cpp`. (Allows throw SOF and still running)

see [JEP 270: Reserved Stack Areas for Critical Sections](https://openjdk.java.net/jeps/270)

```cpp
  main_thread->create_stack_guard_pages();

  // Initialize Java-Level synchronization subsystem
  ObjectMonitor::Initialize();

  // Initialize global modules
  jint status = init_globals();
  if (status != JNI_OK) {
    main_thread->smr_delete();
    *canTryAgain = false; // don't let caller call JNI_CreateJavaVM again
    return status;
  }

  JFR_ONLY(Jfr::on_vm_init();)

  // Should be done after the heap is fully created
  main_thread->cache_global_variables();

  HandleMark hm;

  { MutexLocker mu(Threads_lock);
    Threads::add(main_thread);
  }

  // Any JVMTI raw monitors entered in onload will transition into
  // real raw monitor. VM is setup enough here for raw monitor enter.
  JvmtiExport::transition_pending_onload_raw_monitors();
```

Create the [VMThread](/docs/CS/Java/JDK/JVM/Thread.md?id=VMThread)

```cpp
  { 
    VMThread::create();
    Thread* vmthread = VMThread::vm_thread();

    if (!os::create_thread(vmthread, os::vm_thread)) {
      vm_exit_during_initialization("Cannot create VM thread. Out of system resources.");
    }
```

Wait for the VM thread to become ready, and [VMThread::run](/docs/CS/Java/JDK/JVM/Thread.md?id=VMThreadrun) to initialize Monitors can have spurious returns, must always check another state flag.

```cpp
    {
      MutexLocker ml(Notify_lock);
      os::start_thread(vmthread);
      while (vmthread->active_handles() == NULL) {
        Notify_lock->wait();
      }
    }
  }

  assert(Universe::is_fully_initialized(), "not initialized");
  if (VerifyDuringStartup) {
    // Make sure we're starting with a clean slate.
    VM_Verify verify_op;
    VMThread::execute(&verify_op);
  }

  // We need this to update the java.vm.info property in case any flags used
  // to initially define it have been changed. This is needed for both CDS and
  // AOT, since UseSharedSpaces and UseAOT may be changed after java.vm.info
  // is initially computed. See Abstract_VM_Version::vm_info_string().
  // This update must happen before we initialize the java classes, but
  // after any initialization logic that might modify the flags.
  Arguments::update_vm_info_property(VM_Version::vm_info_string());

  Thread* THREAD = Thread::current();

  // Always call even when there are not JVMTI environments yet, since environments
  // may be attached late and JVMTI must track phases of VM execution
  JvmtiExport::enter_early_start_phase();

  // Notify JVMTI agents that VM has started (JNI is up) - nop if no agents.
  JvmtiExport::post_early_vm_start();

  initialize_java_lang_classes(main_thread, CHECK_JNI_ERR);

  quicken_jni_functions();

  // No more stub generation allowed after that point.
  StubCodeDesc::freeze();

  // Set flag that basic initialization has completed. Used by exceptions and various
  // debug stuff, that does not work until all basic classes have been initialized.
  set_init_completed();

  LogConfiguration::post_initialize();
  Metaspace::post_initialize();

  HOTSPOT_VM_INIT_END();

  // record VM initialization completion time
#if INCLUDE_MANAGEMENT
  Management::record_vm_init_completed();
#endif // INCLUDE_MANAGEMENT

  // Signal Dispatcher needs to be started before VMInit event is posted
  os::initialize_jdk_signal_support(CHECK_JNI_ERR);

  // Start Attach Listener if +StartAttachListener or it can't be started lazily
  if (!DisableAttachMechanism) {
    AttachListener::vm_start();
    if (StartAttachListener || AttachListener::init_at_startup()) {
      AttachListener::init();
    }
  }

  // Launch -Xrun agents
  // Must be done in the JVMTI live phase so that for backward compatibility the JDWP
  // back-end can launch with -Xdebug -Xrunjdwp.
  if (!EagerXrunInit && Arguments::init_libraries_at_startup()) {
    create_vm_init_libraries();
  }

    Chunk::start_chunk_pool_cleaner_task();
```

[Start the service thread](/docs/CS/Java/JDK/JVM/Thread.md?id=ServiceThreadinitialize)

The service thread enqueues JVMTI deferred events and does various hashtable and other cleanups.
Needs to start before the compilers start posting events.

```cpp
  ServiceThread::initialize();
```

[Start the monitor deflation thread](/docs/CS/Java/JDK/JVM/Thread.md?id=MonitorDeflationThreadinitialize):

```
  MonitorDeflationThread::initialize();
```

initialize compiler(s) with [compilation_init_phase1](/docs/CS/Java/JDK/JVM/Thread.md?id=compilation_init_phase1)

```cpp
#if defined(COMPILER1) || COMPILER2_OR_JVMCI
#if INCLUDE_JVMCI
  bool force_JVMCI_intialization = false;
  if (EnableJVMCI) {
    // Initialize JVMCI eagerly when it is explicitly requested.
    // Or when JVMCIPrintProperties is enabled.
    // The JVMCI Java initialization code will read this flag and
    // do the printing if it's set.
    force_JVMCI_intialization = EagerJVMCI || JVMCIPrintProperties;

    if (!force_JVMCI_intialization) {
      // 8145270: Force initialization of JVMCI runtime otherwise requests for blocking
      // compilations via JVMCI will not actually block until JVMCI is initialized.
      force_JVMCI_intialization = UseJVMCICompiler && (!UseInterpreter || !BackgroundCompilation);
    }
  }
#endif
  CompileBroker::compilation_init_phase1(CHECK_JNI_ERR);
  // Postpone completion of compiler initialization to after JVMCI
  // is initialized to avoid timeouts of blocking compilations.
  if (JVMCI_ONLY(!force_JVMCI_intialization) NOT_JVMCI(true)) {
    CompileBroker::compilation_init_phase2();
  }
#endif

  // Pre-initialize some JSR292 core classes to avoid deadlock during class loading.
  // It is done after compilers are initialized, because otherwise compilations of
  // signature polymorphic MH intrinsics can be missed
  // (see SystemDictionary::find_method_handle_intrinsic).
  initialize_jsr292_core_classes(CHECK_JNI_ERR);

  // This will initialize the module system.  Only java.base classes can be
  // loaded until phase 2 completes
  call_initPhase2(CHECK_JNI_ERR);

  // Always call even when there are not JVMTI environments yet, since environments
  // may be attached late and JVMTI must track phases of VM execution
  JvmtiExport::enter_start_phase();

  // Notify JVMTI agents that VM has started (JNI is up) - nop if no agents.
  JvmtiExport::post_vm_start();

  // Final system initialization including security manager and system class loader
  call_initPhase3(CHECK_JNI_ERR);
```

cache the [system and platform class loaders](/docs/CS/Java/JDK/JVM/ClassLoader.md?id=init)

```cpp
  SystemDictionary::compute_java_loaders(CHECK_JNI_ERR);

#if INCLUDE_CDS
  if (DumpSharedSpaces) {
    // capture the module path info from the ModuleEntryTable
    ClassLoader::initialize_module_path(THREAD);
  }
#endif

#if INCLUDE_JVMCI
  if (force_JVMCI_intialization) {
    JVMCIRuntime::force_initialization(CHECK_JNI_ERR);
    CompileBroker::compilation_init_phase2();
  }
#endif

  // Always call even when there are not JVMTI environments yet, since environments
  // may be attached late and JVMTI must track phases of VM execution
  JvmtiExport::enter_live_phase();

  // Make perfmemory accessible
  PerfMemory::set_accessible(true);

  // Notify JVMTI agents that VM initialization is complete - nop if no agents.
  JvmtiExport::post_vm_initialized();

  JFR_ONLY(Jfr::on_vm_start();)

#if INCLUDE_MANAGEMENT
  Management::initialize(THREAD);

  if (HAS_PENDING_EXCEPTION) {
    // management agent fails to start possibly due to
    // configuration problem and is responsible for printing
    // stack trace if appropriate. Simply exit VM.
    vm_exit(1);
  }
#endif // INCLUDE_MANAGEMENT

  if (MemProfiling)                   MemProfiler::engage();
  StatSampler::engage();
  if (CheckJNICalls)                  JniPeriodicChecker::engage();

  BiasedLocking::init();

#if INCLUDE_RTM_OPT
  RTMLockingCounters::init();
#endif

  if (JDK_Version::current().post_vm_init_hook_enabled()) {
    call_postVMInitHook(THREAD);
    // The Java side of PostVMInitHook.run must deal with all
    // exceptions and provide means of diagnosis.
    if (HAS_PENDING_EXCEPTION) {
      CLEAR_PENDING_EXCEPTION;
    }
  }

  {
    MutexLocker ml(PeriodicTask_lock);
```

Make sure the WatcherThread can be started by [WatcherThread::start()](/docs/CS/Java/JDK/JVM/Thread.md?id=WatcherThreadstart) or by dynamic enrollment.

```cpp
    WatcherThread::make_startable();
    // Start up the WatcherThread if there are any periodic tasks
    // NOTE:  All PeriodicTasks should be registered by now. If they
    //   aren't, late joiners might appear to start slowly (we might
    //   take a while to process their first tick).
    if (PeriodicTask::num_tasks() > 0) {
      WatcherThread::start();
    }
  }

  create_vm_timer.end();
#ifdef ASSERT
  _vm_complete = true;
#endif

  if (DumpSharedSpaces) {
    MetaspaceShared::preload_and_dump(CHECK_JNI_ERR);
    ShouldNotReachHere();
  }

  return JNI_OK;
}
```

### init

```cpp
// init.cpp
void vm_init_globals() {
  check_ThreadShadow();
  basic_types_init();
  eventlog_init();
  mutex_init();
  chunkpool_init();
  perfMemory_init();
  SuspendibleThreadSet_init();
}

```

### init_globals

```cpp
jint init_globals() {
  HandleMark hm;
  management_init();
  bytecodes_init();
  classLoader_init1();
  compilationPolicy_init();
```

init [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md?id=init)

```cpp
  codeCache_init();
  VM_Version_init();
  os_init_globals();
```

init [stub](/docs/CS/Java/JDK/JVM/JavaCall?id=init)

```cpp
  stubRoutines_init1();
  jint status = universe_init();  // dependent on codeCache_init and
                                  // stubRoutines_init1 and metaspace_init.
  if (status != JNI_OK)
    return status;

  gc_barrier_stubs_init();   // depends on universe_init, must be before interpreter_init
```

interpreter_init_stub before methods get loaded

```cpp
  interpreter_init_stub();
  accessFlags_init();
  InterfaceSupport_init();
  VMRegImpl::set_regName(); // need this before generate_stubs (for printing oop maps).
  SharedRuntime::generate_stubs();
  universe2_init();  // dependent on codeCache_init and stubRoutines_init1
  javaClasses_init();// must happen after vtable initialization, before referenceProcessor_init
```

interpreter_init_code after javaClasses_init and before any method gets linked

```cpp
  interpreter_init_code();
  referenceProcessor_init();
  jni_handles_init();
  #if INCLUDE_VM_STRUCTS
  vmStructs_init();
  #endif // INCLUDE_VM_STRUCTS

  vtableStubs_init();
  InlineCacheBuffer_init();
  compilerOracle_init();
  dependencyContext_init();

  if (!compileBroker_init()) {
    return JNI_EINVAL;
  }
  VMRegImpl::set_regName();

  if (!universe_post_init()) {
    return JNI_ERR;
  }
  stubRoutines_init2(); // note: StubRoutines need 2-phase init
  MethodHandles::generate_adapters();

  #if INCLUDE_NMT
  // Solaris stack is walkable only after stubRoutines are set up.
  // On Other platforms, the stack is always walkable.
  NMT_stack_walkable = true;
  #endif // INCLUDE_NMT

  // All the flags that get adjusted by VM_Version_init and os::init_2
  // have been set so dump the flags now.
  if (PrintFlagsFinal || PrintFlagsRanges) {
    JVMFlag::printFlags(tty, false, PrintFlagsRanges);
  }

  return JNI_OK;
}
```


#### universe_init

```cpp

jint universe_init() {
  assert(!Universe::_fully_initialized, "called after initialize_vtables");
  guarantee(1 << LogHeapWordSize == sizeof(HeapWord),
         "LogHeapWordSize is incorrect.");
  guarantee(sizeof(oop) >= sizeof(HeapWord), "HeapWord larger than oop?");
  guarantee(sizeof(oop) % sizeof(HeapWord) == 0,
            "oop size is not not a multiple of HeapWord size");

  TraceTime timer("Genesis", TRACETIME_LOG(Info, startuptime));

  initialize_global_behaviours();

  GCLogPrecious::initialize();

#ifdef _LP64
  MetaspaceShared::adjust_heap_sizes_for_dumping();
#endif // _LP64

  GCConfig::arguments()->initialize_heap_sizes();

  jint status = Universe::initialize_heap();
  if (status != JNI_OK) {
    return status;
  }

  Universe::initialize_tlab();

  Metaspace::global_initialize();

  // Initialize performance counters for metaspaces
  MetaspaceCounters::initialize_performance_counters();

  // Checks 'AfterMemoryInit' constraints.
  if (!JVMFlagLimit::check_all_constraints(JVMFlagConstraintPhase::AfterMemoryInit)) {
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
  Universe::_throw_no_such_method_error_cache = new LatestMethodCache();
  Universe::_do_stack_walk_cache = new LatestMethodCache();

#if INCLUDE_CDS
  DynamicArchive::check_for_dynamic_dump();
  if (UseSharedSpaces) {
    // Read the data structures supporting the shared spaces (shared
    // system dictionary, symbol table, etc.)
    MetaspaceShared::initialize_shared_spaces();
  }
  if (Arguments::is_dumping_archive()) {
    MetaspaceShared::prepare_for_dumping();
  }
#endif

  SymbolTable::create_table();
  StringTable::create_table();

  if (strlen(VerifySubSet) > 0) {
    Universe::initialize_verify_flags();
  }

  ResolvedMethodTable::create_table();

  return JNI_OK;
}
```


### init_globals2


```c++
jint init_globals2() {
  universe2_init();          // dependent on codeCache_init and initial_stubs_init
  javaClasses_init();        // must happen after vtable initialization, before referenceProcessor_init
  interpreter_init_code();   // after javaClasses_init and before any method gets linked
  referenceProcessor_init();
  jni_handles_init();

  vtableStubs_init();
  InlineCacheBuffer_init();
  compilerOracle_init();
  dependencyContext_init();
  dependencies_init();

  if (!compileBroker_init()) {
    return JNI_EINVAL;
  }
#if INCLUDE_JVMCI
  if (EnableJVMCI) {
    JVMCI::initialize_globals();
  }
#endif

  if (!universe_post_init()) {
    return JNI_ERR;
  }
  compiler_stubs_init(false /* in_compiler_thread */); // compiler's intrinsics stubs
  final_stubs_init();    // final StubRoutines stubs
  MethodHandles::generate_adapters();

  // All the flags that get adjusted by VM_Version_init and os::init_2
  // have been set so dump the flags now.
  if (PrintFlagsFinal || PrintFlagsRanges) {
    JVMFlag::printFlags(tty, false, PrintFlagsRanges);
  }

  return JNI_OK;
}
```


#### universe_post_init

init_globals2 -> universe_post_init -> Universe::initialize_known_methods -> link_class_or_fail

init OutOfMemoryError allocate instances

```cpp
// universe.cpp
bool universe_post_init() {
  assert(!is_init_completed(), "Error: initialization not yet completed!");
  Universe::_fully_initialized = true;
  EXCEPTION_MARK;
  { ResourceMark rm;
    Interpreter::initialize();      // needed for interpreter entry points
    if (!UseSharedSpaces) {
      Universe::reinitialize_vtables(CHECK_false);
      Universe::reinitialize_itables(CHECK_false);
    }
  }

  HandleMark hm(THREAD);
  // Setup preallocated empty java.lang.Class array
  Universe::_the_empty_class_klass_array = oopFactory::new_objArray(SystemDictionary::Class_klass(), 0, CHECK_false);

  // Setup preallocated OutOfMemoryError errors
  Klass* k = SystemDictionary::resolve_or_fail(vmSymbols::java_lang_OutOfMemoryError(), true, CHECK_false);
  InstanceKlass* ik = InstanceKlass::cast(k);
  Universe::_out_of_memory_error_java_heap = ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_metaspace = ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_class_metaspace = ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_array_size = ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_gc_overhead_limit =
    ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_realloc_objects = ik->allocate_instance(CHECK_false);
  Universe::_out_of_memory_error_retry = ik->allocate_instance(CHECK_false);

  // Setup preallocated cause message for delayed StackOverflowError
  if (StackReservedPages > 0) {
    Universe::_delayed_stack_overflow_error_message =
      java_lang_String::create_oop_from_str("Delayed StackOverflowError due to ReservedStackAccess annotated method", CHECK_false);
  }

  // Setup preallocated NullPointerException
  // (this is currently used for a cheap & dirty solution in compiler exception handling)
  k = SystemDictionary::resolve_or_fail(vmSymbols::java_lang_NullPointerException(), true, CHECK_false);
  Universe::_null_ptr_exception_instance = InstanceKlass::cast(k)->allocate_instance(CHECK_false);
  // Setup preallocated ArithmeticException
  // (this is currently used for a cheap & dirty solution in compiler exception handling)
  k = SystemDictionary::resolve_or_fail(vmSymbols::java_lang_ArithmeticException(), true, CHECK_false);
  Universe::_arithmetic_exception_instance = InstanceKlass::cast(k)->allocate_instance(CHECK_false);
  // Virtual Machine Error for when we get into a situation we can't resolve
  k = SystemDictionary::resolve_or_fail(
    vmSymbols::java_lang_VirtualMachineError(), true, CHECK_false);
  bool linked = InstanceKlass::cast(k)->link_class_or_fail(CHECK_false);
  if (!linked) {
     tty->print_cr("Unable to link/verify VirtualMachineError class");
     return false; // initialization failed
  }
  Universe::_virtual_machine_error_instance =
    InstanceKlass::cast(k)->allocate_instance(CHECK_false);

  Universe::_vm_exception = InstanceKlass::cast(k)->allocate_instance(CHECK_false);

  Handle msg = java_lang_String::create_from_str("Java heap space", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_java_heap, msg());

  msg = java_lang_String::create_from_str("Metaspace", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_metaspace, msg());
  msg = java_lang_String::create_from_str("Compressed class space", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_class_metaspace, msg());

  msg = java_lang_String::create_from_str("Requested array size exceeds VM limit", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_array_size, msg());

  msg = java_lang_String::create_from_str("GC overhead limit exceeded", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_gc_overhead_limit, msg());

  msg = java_lang_String::create_from_str("Java heap space: failed reallocation of scalar replaced objects", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_realloc_objects, msg());

  msg = java_lang_String::create_from_str("Java heap space: failed retryable allocation", CHECK_false);
  java_lang_Throwable::set_message(Universe::_out_of_memory_error_retry, msg());

  msg = java_lang_String::create_from_str("/ by zero", CHECK_false);
  java_lang_Throwable::set_message(Universe::_arithmetic_exception_instance, msg());

  // Setup the array of errors that have preallocated backtrace
  k = Universe::_out_of_memory_error_java_heap->klass();
  assert(k->name() == vmSymbols::java_lang_OutOfMemoryError(), "should be out of memory error");
  ik = InstanceKlass::cast(k);

  int len = (StackTraceInThrowable) ? (int)PreallocatedOutOfMemoryErrorCount : 0;
  Universe::_preallocated_out_of_memory_error_array = oopFactory::new_objArray(ik, len, CHECK_false);
  for (int i=0; i<len; i++) {
    oop err = ik->allocate_instance(CHECK_false);
    Handle err_h = Handle(THREAD, err);
    java_lang_Throwable::allocate_backtrace(err_h, CHECK_false);
    Universe::preallocated_out_of_memory_errors()->obj_at_put(i, err_h());
  }
  Universe::_preallocated_out_of_memory_error_avail_count = (jint)len;

  Universe::initialize_known_methods(CHECK_false);

  // This needs to be done before the first scavenge/gc, since
  // it's an input to soft ref clearing policy.
  {
    MutexLocker x(Heap_lock);
    Universe::update_heap_info_at_gc();
  }

  // ("weak") refs processing infrastructure initialization
  Universe::heap()->post_initialize();

  MemoryService::add_metaspace_memory_pools();

  MemoryService::set_universe_heap(Universe::heap());
#if INCLUDE_CDS
  MetaspaceShared::post_initialize(CHECK_false);
#endif
  return true;
}
```

#### init classloader

Initialize the class loader's access to methods in libzip.  Parse and process the boot classpath into a list ClassPathEntry objects.  Once this list has been created, it must not change order (see class PackageInfo) it can be appended to and is by jvmti and the kernel vm.

## MainClass


通过[JavaCalls::call()](/docs/CS/Java/JDK/JVM/JavaCall.md)函数来调用Java主类的main()方法

```cpp

static void jni_invoke_static(JNIEnv *env, JavaValue* result, jobject receiver, JNICallType call_type, jmethodID method_id, JNI_ArgumentPusher *args, TRAPS) {
  methodHandle method(THREAD, Method::resolve_jmethod_id(method_id));

  // Create object to hold arguments for the JavaCall, and associate it with
  // the jni parser
  ResourceMark rm(THREAD);
  int number_of_parameters = method->size_of_parameters();
  JavaCallArguments java_args(number_of_parameters);

  assert(method->is_static(), "method should be static");

  // Fill out JavaCallArguments object
  args->push_arguments_on(&java_args);
  // Initialize result type
  result->set_type(args->return_type());

  // Invoke the method. Result is returned as oop.
  JavaCalls::call(result, method, &java_args, CHECK);

  // Convert result
  if (is_reference_type(result->get_type())) {
    result->set_jobject(JNIHandles::make_local(THREAD, result->get_oop()));
  }
}
```


## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Destroy JVM](/docs/CS/Java/JDK/JVM/destroy.md)
