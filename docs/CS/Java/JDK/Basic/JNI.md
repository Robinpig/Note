## Introduction

Java Native Interface（JNI）是 JVM 与本地（C/C++）代码互操作的官方标准机制：它允许 Java 调用 native 方法、native 代码回调 Java 方法、访问 Java 对象字段，并在 Java 与 C 类型间转换。JNI 自 Java 1.1 起存在，但因样板繁重（javah 头文件、JNIEnv 不透明句柄、手工内存管理、每平台单独编译 .so/.dll/.dylib）而长期被诟病——一个指针错误即可静默损坏内存甚至直接崩溃 JVM。

> ⚠️ **现代替代**：JDK 22 起 [FFM API（JEP 454）](/docs/CS/Java/JDK/Basic/JNI.md?id=ffm-api-the-modern-alternative) 提供了纯 Java、内存安全、性能接近 JNI 的替代，是新的 native 互操作首选。

## FFM API: The Modern Alternative

Foreign Function & Memory API（项目 Panama，JEP 454）在 **JDK 22 GA**，位于 `java.lang.foreign`，无需 `--enable-preview`。核心类型：

- `Linker`：绑定 native 函数（downcall）与 Java 回调（upcall）。
- `MemorySegment` / `Arena`：作用域化的堆外内存，Arena 关闭即自动释放。
- `MemoryLayout` / `FunctionDescriptor`：以纯 Java 描述 C 结构体与函数签名。
- `ValueLayout`：映射 C 基本类型（`JAVA_INT` / `JAVA_LONG` / `C_POINTER` 等）。

```java
import java.lang.foreign.*;
import java.lang.invoke.MethodHandle;

public class Hello {
    public static void main(String[] args) throws Throwable {
        try (Arena arena = Arena.ofConfined()) {
            Linker linker = Linker.nativeLinker();
            MemorySegment hello = arena.allocateFrom("Hello, world!\n");
            MethodHandle printf = linker.downcallHandle(
                linker.defaultLookup().find("printf").orElseThrow(),
                FunctionDescriptor.of(ValueLayout.JAVA_INT, ValueLayout.ADDRESS));
            printf.invoke(hello);
        }
    }
}
```

从 JDK 22 起直接调用 native 函数需显式声明 native access：`--enable-native-access=ALL-UNNAMED`（JEP 472），否则运行期告警（见 [Migration](#migration-to-ffm)）。

## JNI Function Table

`JNIEnv` 与 `JavaVM` 本质上都是**函数指针表**的指针：

- `JNIEnv*`：每个 Java 线程独有一份，指向 JNI 函数表（FindClass、GetMethodID、CallXxxMethod、NewXxx 等）。native 方法通过它访问 JVM 能力。
- `JavaVM*`：进程级，提供 `JNI_CreateJavaVM` / `DestroyJavaVM` / `GetEnv` / `AttachCurrentThread`，用于从 C/C++ 侧创建或附着 JVM（如嵌入式场景）。

## Java calls native

### Example

```shell
javac -h . Hello.java     # 生成 Hello.h 头文件
# 实现 Hello.c，编译链接
gcc -shared -fPIC Hello.c -o libHello.so -I$JAVA_HOME/include -I$JAVA_HOME/include/linux
java -Djava.library.path=. Hello
```

JVM 启动时（`java -jar app.jar` → Java Launcher → JNI → `libjvm.so`）经 `JNI_CreateJavaVM` 创建虚拟机：

```c
static jint JNI_CreateJavaVM_inner(JavaVM **vm, void **penv, void *args) {
  // ... 原子标记 vm_created，调用 Threads::create_vm ...
  if (result == JNI_OK) {
    JavaThread *thread = JavaThread::current();
    *vm = (JavaVM *)(&main_vm);
    *(JNIEnv**)penv = thread->jni_environment();
    Atomic::release_store(&vm_created, COMPLETE);
  }
  // ...
}
```

### Native binding

native 方法通过 `registerNatives` 把 Java 层声明绑定到 C 函数指针，之后首次调用经 `prepare_native_call` 完成链接：

```cpp
void Method::set_native_function(address function, bool post_event_flag) {
  assert(function != NULL, "use clear_native_function to unregister natives");
  address* native_function = native_function_addr();
  address current = *native_function;
  if (current == function) return;          // 并发重复绑定只放一次
  if (post_event_flag && JvmtiExport::should_post_native_method_bind() && function != NULL)
      JvmtiExport::post_native_method_bind(this, &function);
  *native_function = function;
  CompiledMethod* nm = code();
  if (nm != NULL) nm->make_not_entrant();    // 已有编译代码须失效
}
```

链接解析走 `NativeLookup::lookup` → `os::dll_lookup`（Linux 下 `dlsym`）→ `set_native_function`：

```cpp
address NativeLookup::lookup(const methodHandle& method, TRAPS) {
  if (!method->has_native_function()) {
    address entry = lookup_base(method, CHECK_NULL);
    method->set_native_function(entry, Method::native_bind_event_is_interesting);
  }
  return method->native_function();
}
```

## native calls Java

native 代码通过 `JNIEnv` 反向调用 Java：

- **构造对象**：`NewObject` / `NewObjectA`，先 `GetMethodID` 取得构造器 `<init>`。
- **调用实例方法**：`Call<Type>Method`（`Type` ∈ Void/Int/Long/.../Object）；`CallNonvirtual<Type>Method` 绕过虚分派、强制调指定类版本。
- **调用静态方法**：`CallStatic<Type>Method`。
- **访问字段**：`GetFieldID`/`Get<Type>Field`/`Set<Type>Field`；静态对应 `GetStaticFieldID`。
- **异常检查**：JNI 函数多返回错误码而非抛异常；native 侧须用 `ExceptionCheck()` / `ExceptionOccurred()` 判断，并用 `ThrowNew` 抛出 Java 异常。longjmp 式的 Java 异常**不能**跨 JNI 边界用 C 的 try/catch 捕获。

## Reference Management

JNI 引用管理是 native 代码与 GC 正确协作的关键：

- **Local Reference（局部引用）**：每次 JNI 调用（FindClass、NewObject、GetObjectField 等）返回的对象都是局部引用。它是 **GC Root**，在 native 方法返回时自动释放。若在长循环或递归 native 中持续创建而不 `DeleteLocalRef`，会撑爆引用表（默认上限约 512 个，超限抛 `OutOfMemoryError: JNI local reference table overflow`）。
- **Global Reference（全局引用）**：`NewGlobalRef` / `DeleteGlobalRef`，跨多次 native 调用甚至跨线程存活，直到显式释放；它同样阻止 GC 回收目标对象，泄漏会造成 Java 堆对象长期驻留。
- **Weak Global Reference（弱全局引用）**：`NewWeakGlobalRef` / `DeleteWeakGlobalRef`，**不阻止** GC 回收，需 `IsSameObject(env, ref, NULL)` 判断目标是否已被回收。

## JNI and GC

JNI 局部引用本身是 GC Root，会阻止其指向的 Java 对象被回收——这正是"native 持有 Java 对象期间对象安全"的机制，但也意味着必须及时 `DeleteLocalRef`。

更关键的是 **Critical 区域**：`GetXxxCritical` / `ReleaseXxxCritical`（如 `GetPrimitiveArrayCritical`）允许 native 直接访问 Java 数组底层内存，避免一次拷贝。但进入 Critical 区域后：

- JVM **可能抑制 GC 或禁止对象移动**（视 GC 实现），以保证 native 拿到的裸指针有效；
- 因此**不能在 Critical 区域内调用任何其他 JNI 函数，也不能阻塞或调用 Java 方法**——否则可能引发死锁或崩溃（GC 无法在 Critical 区域完成 safepoint）；
- 必须尽快 `ReleaseXxxCritical`。

这正是 `JNI and GC` 的核心约束：Critical 区域是 JVM 内存管理的一道"闸门"，用错了比普通 JNI 调用更危险。

## JNI and Safepoint

- native 方法执行期间，Java 线程处于 `_thread_in_native` 状态（对 Java 层可见为 **RUNNABLE**）——native 调用边界是 **safepoint 安全点**，JVM 可在 native 返回 Java 时安全地暂停该线程。
- 线程进入/退出 native 时做状态转换（`ThreadBlockInVM` 等），并处理挂起请求（suspend）。
- 在 Critical 区域（见上节）JVM 通常**不**在该线程上推进需要移动对象的 GC，这与 safepoint 协作保证裸指针安全。

## Thread

线程在 native 代码执行期间，Java 层看到的状态是 **RUNNABLE**（而非 WAITING/BLOCKED），即使 native 侧实际在 `pthread_cond_wait`。这是 JVM 线程状态与 OS 线程状态不一致的典型情形，排查"假 RUNNABLE"时需结合 native 栈。

## Migration to FFM

- **`jnativescan`（JEP 472，JDK 24）**：静态扫描应用的 JNI 用法（直接 native 声明、JNI 函数指针等），给出迁移清单，是审计 native 依赖的官方工具。
- **仍用 JNI 的场景**：JVM TI agent、需精细控制 JNI 引用语义、或维护无法升级的遗留库。新代码优先 FFM；遗留代码在 JDK 24+ 会收到 native access 警告，需 `--enable-native-access` 显式授权。
- 与 [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md?id=deprecation-jep-471) 的弃用趋势一致，JDK 正系统性收紧"绕过平台边界"的通道（JNI / Unsafe / Agent 动态加载），默认趋向 integrity。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [unsafe](/docs/CS/Java/JDK/Basic/unsafe.md)
- [Handles](/docs/CS/Java/JDK/JVM/Handles.md)
- [Stack](/docs/CS/Java/JDK/JVM/Stack.md)

## References

1. [Java Native Interface Specification](https://docs.oracle.com/en/java/javase/11/docs/specs/jni/index.html)
2. [JEP 454: Foreign Function & Memory API](https://openjdk.org/jeps/454)
3. [JEP 472: Prepare to Restrict the Use of JNI](https://openjdk.org/jeps/472)
4. [JNI 中错误的信号处理导致 JVM 崩溃问题分析](https://mp.weixin.qq.com/s?__biz=MzkyMjYzNjU0Ng==&mid=2247507047&idx=1&sn=fc1a4942877f4197653f0e0c031070c5)
