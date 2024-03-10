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

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)

## References

1. [Java Programming Tutorial Java Native Interface (JNI)](https://www3.ntu.edu.sg/home/ehchua/programming/java/JavaNativeInterface.html)
2. [Java Native Interface Specification Contents](https://docs.oracle.com/en/java/javase/11/docs/specs/jni/index.html)
3. [JEP 454: Foreign Function & Memory API](https://openjdk.java.net/jeps/454)
