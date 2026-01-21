## Introduction

Java Native Interface


### Example

javac -h generate .h file
create .c file
compile link file


JDK17
```
--add-modules jdk.incubator.foreign  --enable-native-access=ALL-UNNAMED
```

```java

import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodType;

import jdk.incubator.foreign.*;

public class Hello {
    public static void main(String[] args) throws Throwable {
        try (ResourceScope scope = ResourceScope.newConfinedScope()) {
            CLinker cLinker = CLinker.getInstance();
            MemorySegment helloWorld =
                    CLinker.toCString("Hello, world!\n", scope);
            MethodHandle cPrintf = cLinker.downcallHandle(
                    CLinker.systemLookup().lookup("printf").get(),
                    MethodType.methodType(int.class, MemoryAddress.class),
                    FunctionDescriptor.of(CLinker.C_INT, CLinker.C_POINTER));
            cPrintf.invoke(helloWorld.address());
        }
    }
}
```

## native call Java

```c
#include<jni.h>
```

Pointer of JVM

Pointer of JNIEnv : *env

JNI_createJavaVM

```c
_JNI_IMPORT_OR_EXPORT_ jint JNICALL JNI_CreateJavaVM(JavaVM **vm, void **penv, void *args) {
  jint result = JNI_ERR;
  // On Windows, let CreateJavaVM run with SEH protection
#if defined(_WIN32) && !defined(USE_VECTORED_EXCEPTION_HANDLING)
  __try {
#endif
    result = JNI_CreateJavaVM_inner(vm, penv, args);
#if defined(_WIN32) && !defined(USE_VECTORED_EXCEPTION_HANDLING)
  } __except(topLevelExceptionFilter((_EXCEPTION_POINTERS*)_exception_info())) {
    // Nothing to do.
  }
#endif
  return result;
}
```

JNI_CreateJavaVM_inner

```c
static jint JNI_CreateJavaVM_inner(JavaVM **vm, void **penv, void *args) {
  HOTSPOT_JNI_CREATEJAVAVM_ENTRY((void **) vm, penv, args);

  jint result = JNI_ERR;
  DT_RETURN_MARK(CreateJavaVM, jint, (const jint&)result);

  // We're about to use Atomic::xchg for synchronization.  Some Zero
  // platforms use the GCC builtin __sync_lock_test_and_set for this,
  // but __sync_lock_test_and_set is not guaranteed to do what we want
  // on all architectures.  So we check it works before relying on it.
#if defined(ZERO) && defined(ASSERT)
  {
    jint a = 0xcafebabe;
    jint b = Atomic::xchg(&a, (jint) 0xdeadbeef);
    void *c = &a;
    void *d = Atomic::xchg(&c, &b);
    assert(a == (jint) 0xdeadbeef && b == (jint) 0xcafebabe, "Atomic::xchg() works");
    assert(c == &b && d == &a, "Atomic::xchg() works");
  }
#endif // ZERO && ASSERT

  if (Atomic::xchg(&vm_created, IN_PROGRESS) != NOT_CREATED) {
    return JNI_EEXIST;   // already created, or create attempt in progress
  }

  if (Atomic::xchg(&safe_to_recreate_vm, 0) == 0) {
    return JNI_ERR;
  }

  bool can_try_again = true;

  result = Threads::create_vm((JavaVMInitArgs*) args, &can_try_again);
  if (result == JNI_OK) {
    JavaThread *thread = JavaThread::current();
    assert(!thread->has_pending_exception(), "should have returned not OK");
    // thread is thread_in_vm here
    *vm = (JavaVM *)(&main_vm);
    *(JNIEnv**)penv = thread->jni_environment();
    // mark creation complete for other JNI ops
    Atomic::release_store(&vm_created, COMPLETE);

#if INCLUDE_JVMCI
    if (EnableJVMCI) {
      if (UseJVMCICompiler) {
        // JVMCI is initialized on a CompilerThread
        if (BootstrapJVMCI) {
          JavaThread* THREAD = thread; // For exception macros.
          JVMCICompiler* compiler = JVMCICompiler::instance(true, CATCH);
          compiler->bootstrap(THREAD);
          if (HAS_PENDING_EXCEPTION) {
            HandleMark hm(THREAD);
            vm_exit_during_initialization(Handle(THREAD, PENDING_EXCEPTION));
          }
        }
      }
    }
#endif

    // Notify JVMTI
    if (JvmtiExport::should_post_thread_life()) {
       JvmtiExport::post_thread_start(thread);
    }

    JFR_ONLY(Jfr::on_thread_start(thread);)

    if (ReplayCompiles) ciReplay::replay(thread);

#ifdef ASSERT
    // Some platforms (like Win*) need a wrapper around these test
    // functions in order to properly handle error conditions.
    if (ErrorHandlerTest != 0) {
      VMError::controlled_crash(ErrorHandlerTest);
    }
#endif

    // Since this is not a JVM_ENTRY we have to set the thread state manually before leaving.
    ThreadStateTransition::transition_from_vm(thread, _thread_in_native);
    MACOS_AARCH64_ONLY(thread->enable_wx(WXExec));
  } else {
    // If create_vm exits because of a pending exception, exit with that
    // exception.  In the future when we figure out how to reclaim memory,
    // we may be able to exit with JNI_ERR and allow the calling application
    // to continue.
    if (Universe::is_fully_initialized()) {
      // otherwise no pending exception possible - VM will already have aborted
      Thread* current = Thread::current_or_null();
      if (current != nullptr) {
        JavaThread* THREAD = JavaThread::cast(current); // For exception macros.
        assert(HAS_PENDING_EXCEPTION, "must be - else no current thread exists");
        HandleMark hm(THREAD);
        vm_exit_during_initialization(Handle(THREAD, PENDING_EXCEPTION));
      }
    }

    if (can_try_again) {
      // reset safe_to_recreate_vm to 1 so that retrial would be possible
      safe_to_recreate_vm = 1;
    }

    // Creation failed. We must reset vm_created
    *vm = 0;
    *(JNIEnv**)penv = 0;
    // reset vm_created last to avoid race condition. Use OrderAccess to
    // control both compiler and architectural-based reordering.
    assert(vm_created == IN_PROGRESS, "must be");
    Atomic::release_store(&vm_created, NOT_CREATED);
  }

  // Flush stdout and stderr before exit.
  fflush(stdout);
  fflush(stderr);

  return result;

}
```





JNI_DestroyJavaVM

for example

java -jar spring-application.jar  using Java Launcher   - -   JNI - - > libjvm.so

## register

```cpp

static JNINativeMethod methods[] = {
    {"getDeclaredFields0","(Z)[" FLD,       (void *)&JVM_GetClassDeclaredFields},
    ...
}

JNIEXPORT void JNICALL
Java_java_lang_Class_registerNatives(JNIEnv *env, jclass cls)
{
    methods[1].fnPtr = (void *)(*env)->GetSuperclass;
    (*env)->RegisterNatives(env, cls, methods,
                            sizeof(methods)/sizeof(JNINativeMethod));
}
```

### set_native_function

```cpp

void Method::set_native_function(address function, bool post_event_flag) {
  assert(function != NULL, "use clear_native_function to unregister natives");
  assert(!is_method_handle_intrinsic() || function == SharedRuntime::native_method_throw_unsatisfied_link_error_entry(), "");
  address* native_function = native_function_addr();

  // We can see racers trying to place the same native function into place. Once
  // is plenty.
  address current = *native_function;
  if (current == function) return;
  if (post_event_flag && JvmtiExport::should_post_native_method_bind() &&
      function != NULL) {
    // native_method_throw_unsatisfied_link_error_entry() should only
    // be passed when post_event_flag is false.
    assert(function !=
      SharedRuntime::native_method_throw_unsatisfied_link_error_entry(),
      "post_event_flag mis-match");

    // post the bind event, and possible change the bind function
    JvmtiExport::post_native_method_bind(this, &function);
  }
  *native_function = function;
  // This function can be called more than once. We must make sure that we always
  // use the latest registered method -> check if a stub already has been generated.
  // If so, we have to make it not_entrant.
  CompiledMethod* nm = code(); // Put it into local variable to guard against concurrent updates
  if (nm != NULL) {
    nm->make_not_entrant();
  }
}
```

## Call

### prepare_native_call

```cpp

JRT_ENTRY(void, InterpreterRuntime::prepare_native_call(JavaThread* current, Method* method))
  methodHandle m(current, method);
  assert(m->is_native(), "sanity check");
  // lookup native function entry point if it doesn't exist
  if (!m->has_native_function()) {
    NativeLookup::lookup(m, CHECK);
  }
  // make sure signature handler is installed
  SignatureHandlerLibrary::add(m);
  // The interpreter entry point checks the signature handler first,
  // before trying to fetch the native entry point and klass mirror.
  // We must set the signature handler last, so that multiple processors
  // preparing the same method will be sure to see non-null entry & mirror.
JRT_END
```

### lookup

if !has_native_function:

1. lookup -> `os::dll_lookup`(`dlsym` in Linux)
2. set_native_function

```cpp

address NativeLookup::lookup(const methodHandle& method, TRAPS) {
  if (!method->has_native_function()) {
    address entry = lookup_base(method, CHECK_NULL);
    method->set_native_function(entry,
      Method::native_bind_event_is_interesting);
    // -verbose:jni printing
    if (log_is_enabled(Debug, jni, resolve)) {
      ResourceMark rm(THREAD);
      log_debug(jni, resolve)("[Dynamic-linking native method %s.%s ... JNI]",
                              method->method_holder()->external_name(),
                              method->name()->as_C_string());
    }
  }
  return method->native_function();
}
```

## Thread

state in native is RUNNABLE

## JNI and safepoint

## JNI and GC







JNI 编程时不要随意截获信号处理

```java
// JNITest.java
import java.util.UUID;
public class JNITest {
    public static void main(String[] args) throws Exception {
        System.loadLibrary("JNITest");
        UUID.fromString(null);
    }
}

// JNITest.c
#include <signal.h>
#include <jni.h>

JNIEXPORT
jint JNICALL JNI_OnLoad(JavaVM *jvm, void *reserved) {
    signal(SIGSEGV, SIG_DFL);//如果注释这条语句，在运行时会出现NullPointerExcetpion异常
    return JNI_VERSION_1_8;
}
```





```shell
$ gcc -Wall -shared -fPIC JNITest.c -o libJNITest.so -I$JAVA_HOME/include -I$JAVA_HOME/include/linux
$ javac JNITest.java
$ java -Xcomp -Djava.library.path=./ JNITest
```





## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References

1. [Java Programming Tutorial Java Native Interface (JNI)](https://www3.ntu.edu.sg/home/ehchua/programming/java/JavaNativeInterface.html)
2. [Java Native Interface Specification Contents](https://docs.oracle.com/en/java/javase/11/docs/specs/jni/index.html)
3. [JEP 454: Foreign Function & Memory API](https://openjdk.java.net/jeps/454)
4. [JNI 中错误的信号处理导致 JVM 崩溃问题分析](https://mp.weixin.qq.com/s?__biz=MzkyMjYzNjU0Ng==&mid=2247507047&idx=1&sn=fc1a4942877f4197653f0e0c031070c5&source=41#wechat_redirect)
