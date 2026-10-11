## Introduction

`sun.misc.Unsafe` 是一个用于执行底层、不安全操作的类。虽然类和所有方法都是 public 的，但其使用受到限制——只有受信任的代码（位于 `jdk.unsupported` 模块、通常由 bootstrap classloader 加载）才能拿到实例。

> **Note:** 调用方有责任在调用方法前自行检查参数。虽然运行时会对输入做最基本的检查，但这些检查是 best-effort 的；当性能优先（如被 JIT 优化）时，部分或全部检查可能被省略。因此调用方**绝不能依赖这些检查及其抛出的异常**。

Unsafe 的 87 个方法中 **79 个是内存访问方法**（on-heap / off-heap / bimodal），其余用于对象分配、线程调度、类定义等。滥用这些方法会绕过 JVM 的安全性与内存管理，直接导致未定义行为甚至 JVM 崩溃——这也是它名字的由来。

## Acquire Instance

历史上获取 Unsafe 实例有两条路径：

```java
// 1. 标准 API：仅对 bootstrap classloader 加载的类可用，否则抛 SecurityException
public static Unsafe getUnsafe() {
    Class<?> caller = Reflection.getCallerClass();
    if (!VM.isSystemDomainLoader(caller.getClassLoader()))
        throw new SecurityException("Unsafe");
    return theUnsafe;
}

// 2. 反射私有字段 theUnsafe（被广泛使用的绕过手段）
Field f = Unsafe.class.getDeclaredField("theUnsafe");
f.setAccessible(true);
Unsafe unsafe = (Unsafe) f.get(null);
```

**JPMS 下的变化：** JDK 9 起强封装（JEP 403 在 JDK 17 成为硬默认），`sun.misc` 包默认不向普通模块开放，仅靠反射 `theUnsafe` 会触发 `InaccessibleObjectException`。需要 `--add-opens java.base/sun.misc` 或依赖 `jdk.unsupported` 模块的特殊导出。更现代的替代是 `MethodHandles.Lookup` 的私有访问能力，但本质上仍是受限的内部 API。

> ⚠️ **弃用趋势（JEP 471 / JEP 498）**：见文末 [Deprecation](#deprecation-jep-471) 一节——JDK 23 起这 79 个内存访问方法已被标记为 `@Deprecated(forRemoval=true)`，新代码不应再依赖它们。

## Core API Categories

| 类别 | 代表方法 |
| -------- | -------- |
| 字段偏移 | `objectFieldOffset` / `staticFieldOffset` / `arrayBaseOffset` / `arrayIndexScale` |
| 堆内读写 | `getInt`/`putInt`、`getObject`/`putObject`、`getXVolatile`/`putXVolatile`、`getXAcquire`/`putXRelease` |
| 原子更新 | `compareAndSwapInt`/`compareAndSwapLong`/`compareAndSwapObject`、`getAndAddInt`、`putOrderedInt` |
| 堆外分配 | `allocateMemory` / `reallocateMemory` / `freeMemory` / `allocateInstance` |
| 线程调度 | `park` / `unpark` |
| 内存屏障 | `loadFence` / `storeFence` / `fullFence` |
| 异常抛出 | `throwException` |
| 类定义 | `defineAnonymousClass`（JDK 15 起 deprecated）/ `defineClass` |

## Memory

### Direct Memory

与 [DirectByteBuffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md) 不同，`Unsafe#allocateMemory` 分配的内存**必须手动 `freeMemory` 释放**，否则造成堆外内存泄漏（DirectByteBuffer 由 Cleaner 在 GC 时自动释放，见 [Ref](/docs/CS/Java/JDK/Basic/Ref.md?id=cleaner)）。

```java
long addr = unsafe.allocateMemory(1024);
unsafe.setMemory(addr, 1024, (byte) 0);
// ... 操作 addr ...
unsafe.freeMemory(addr);   // 必须手动释放
```

### Object Layout & Field Offset

`objectFieldOffset(Field)` 返回某字段在对象内部的**字节偏移**，常配合 `getInt(obj, offset)` / `putInt(obj, offset, v)` 直接读写对象字段，绕过访问控制甚至 `final` 语义（这正是序列化框架、并发容器的底层手段）。

- 偏移量依赖对象头和字段排列，与 [Object Header](/docs/CS/Java/JDK/JVM/Object_Header.md) 布局强相关。
- **缓存 offset 的风险**：JVM 可能在未来版本中重排字段或修改对象头大小（如 JDK 25 的 [Compact Object Headers，JEP 519](/docs/CS/Java/JDK/JVM/Object_Header.md)），硬编码的偏移会失效。这也是 VarHandle 优于 Unsafe 的原因——它动态感知布局。

## CAS

In [computer science](https://en.wikipedia.org/wiki/Computer_science), **compare-and-swap** (**CAS**) is an [atomic](https://en.wikipedia.org/wiki/Atomic_(computer_science)) [instruction](https://en.wikipedia.org/wiki/Instruction_(computer_science)) used in [multithreading](https://en.wikipedia.org/wiki/Thread_(computer_science)#Multithreading) to achieve [synchronization](https://en.wikipedia.org/wiki/Synchronization_(computer_science)). It compares the contents of a memory location with a given value and, only if they are the same, modifies the contents of that memory location to a new given value. This is done as a single atomic operation.

### Overview

CAS-based 算法通常先读取关键内存位置、记住旧值，基于旧值算出新值，再用 CAS 尝试写入（仅当位置仍等于旧值时成功）。失败后从开头重试。在多线程频繁更新共享变量的场景，失败后采用指数退避（exponential backoff）可改善整体性能。

```cpp
// unsafe.cpp
UNSAFE_ENTRY(jboolean, Unsafe_CompareAndSetInt(JNIEnv *env, jobject unsafe, jobject obj, jlong offset, jint e, jint x)) {
  oop p = JNIHandles::resolve(obj);
  if (p == NULL) {
    volatile jint* addr = (volatile jint*)index_oop_from_field_offset_long(p, offset);
    return RawAccess<>::atomic_cmpxchg(x, addr, e) == e;
  } else {
    assert_field_offset_sane(p, offset);
    return HeapAccess<>::atomic_cmpxchg_at(x, p, (ptrdiff_t)offset, e) == e;
  }
} UNSAFE_END
```

平台实现（x86-64）最终落到 `lock cmpxchg`：

```cpp
// atomic_linux_x86.hpp
inline T Atomic::PlatformCmpxchg<8>::operator()(T exchange_value,
                                                T volatile* dest,
                                                T compare_value,
                                                atomic_memory_order /* order */) const {
  STATIC_ASSERT(8 == sizeof(T));
  __asm__ __volatile__ ("lock cmpxchgq %1,(%3)"
                        : "=a" (exchange_value)
                        : "r" (exchange_value), "a" (compare_value), "r" (dest)
                        : "cc", "memory");
  return exchange_value;
}
```

### ABA Problem

ABA 问题发生在：某位置被读两次、两次值相同，于是误判"什么都没变"；但另一线程可能在两次读取之间改了值、做了别的工作、又改回原值，从而骗过第一次读取。

- **DCAS（双字 CAS）**：在 32 位系统用 64 位 CAS，高 32 位放计数器，比较时同时比较指针与计数器。
- **SMR（Safe Memory Reclamation）**：本质是 lock-free 垃圾回收，保证同一指针在数据结构中的唯一存在性，从而彻底解决 ABA。

## Memory Barrier

Fence 类似 `volatile` 的语义。参见 [JEP 171: Fence Intrinsics](https://openjdk.java.net/jeps/171)。

| 方法 | 屏障组合 | 语义对应 |
| -------- | -------- | -------- |
| `loadFence()` | LoadLoad + LoadStore | C11 `memory_order_acquire` |
| `storeFence()` | StoreStore + LoadStore | C11 `memory_order_release` |
| `fullFence()` | 上述二者 + StoreLoad | C11 `memory_order_seq_cst` |

`fullFence` 被用于 [StampedLock](/docs/CS/Java/JDK/Concurrency/Lock.md) 等无锁结构的全屏障点。注意 JVM 不为 pure LoadLoad 提供独立 fence，因为多数硬件的 LoadLoad 屏障免费附带 LoadStore。

```java
public native void loadFence();
public native void storeFence();
public native void fullFence();
```

## Parker

`Unsafe#park` / `unpark` 是 JVM 线程阻塞原语，底层基于 `futex`（Linux）。[StampedLock](/docs/CS/Java/JDK/Concurrency/Lock.md)、[LockSupport](/docs/CS/Java/JDK/Concurrency/Lock.md) 都经由此实现。`_counter` 只可能为 0 或 1。

```cpp
// unsafe.cpp
UNSAFE_ENTRY(void, Unsafe_Park(JNIEnv *env, jobject unsafe, jboolean isAbsolute, jlong time)) {
  HOTSPOT_THREAD_PARK_BEGIN((uintptr_t) thread->parker(), (int) isAbsolute, time);
  EventThreadPark event;
  JavaThreadParkedState jtps(thread, time != 0);
  thread->parker()->park(isAbsolute != 0, time);
  // ... 事件上报 ...
  HOTSPOT_THREAD_PARK_END((uintptr_t) thread->parker());
} UNSAFE_END
```

`Parker::park` 的快路径：若 `_counter > 0` 直接返回（permit 可用），否则在 `_mutex` 保护下 `pthread_cond_wait`/`timedwait`，退出前 `_counter = 0`。`unpark` 将 `_counter` 置 1 并对条件变量 `pthread_cond_signal`。

```cpp
// Parker::park 片段（os_posix.cpp）
if (Atomic::xchg(0, &_counter) > 0) return;   // 快路径
// ... 中断检查、mutex trylock ...
if (_counter > 0) { _counter = 0; pthread_mutex_unlock(_mutex); OrderAccess::fence(); return; }
// ... cond_wait ...
_counter = 0; pthread_mutex_unlock(_mutex); OrderAccess::fence();
```

## Class & Lambda Generation

`defineAnonymousClass` 定义一个类但不让它进入类加载器或系统字典（JDK 15 起 deprecated，改用 `MethodHandles.Lookup.defineHiddenClass`，见 [Valhalla](/docs/CS/Java/JDK/Valhalla.md) 中关于 Hidden Classes 的章节）：

```java
// 已 deprecated since 15
public Class<?> defineAnonymousClass(Class<?> hostClass, byte[] data, Object[] cpPatches) {
    if (hostClass == null || data == null) throw new NullPointerException();
    if (hostClass.isArray() || hostClass.isPrimitive()) throw new IllegalArgumentException();
    return defineAnonymousClass0(hostClass, data, cpPatches);
}
```

**Lambda 的实现依赖此机制**：Lambda 表达式经 `invokedynamic` 调用引导方法生成调用点，过程中通过 ASM 动态生成字节码，再借 Unsafe 的 `defineAnonymousClass` 定义实现相应函数式接口的匿名类并实例化，返回与该匿名类函数式方法句柄关联的调用点。

## allocateInstance

`allocateInstance(Class)` **不调用任何构造器**直接分配对象，是反序列化框架、某些单例破坏手段的底层。反射的 `BootstrapConstructorAccessorImpl` 也用它来实例化类（仅用于引导期）：

```java
// BootstrapConstructorAccessorImpl
public Object newInstance(Object[] args) throws ... {
    try {
        return UnsafeFieldAccessorImpl.unsafe.allocateInstance(constructor.getDeclaringClass());
    } catch (InstantiationException e) { throw new InvocationTargetException(e); }
}
```

`[Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)` 中 `Constructor.newInstance` 在反射创建 enum 时会显式抛 `IllegalArgumentException("Cannot reflectively create enum objects")`，但 `allocateInstance` 可绕过这一保护。

## Deprecation: JEP 471

`sun.misc.Unsafe` 的内存访问方法正被标准 API 取代，弃用分多阶段推进：

| 阶段 | 版本 | 行为 |
| -------- | -------- | -------- |
| 标准替代引入 | JDK 9（VarHandle, JEP 193）/ JDK 22（FFM, JEP 454） | 安全、高性能的公开替代 API 可用 |
| 终止式弃用 | **JDK 23（JEP 471）** | 79 个内存访问方法标 `@Deprecated(forRemoval=true)`，编译期警告 |
| 运行时警告 | **JDK 24（JEP 498）** | 整个运行期首次调用时向 stderr 输出一次警告（报首个被调用的方法名） |
| 默认拒绝 | 未来版本 | 默认 `deny`，调用抛 `UnsupportedOperationException`；最终 `NoSuchMethodError` |

`--sun-misc-unsafe-memory-access` 选项控制强制力度：`allow` / `warn`（JDK 24–26 默认）/ `debug`（每次调用打栈）/ `deny`（立即模拟未来默认）。JDK 25 上 86 个 public 方法中 83 个带 `@Deprecated(forRemoval=true)`，仅 `allocateInstance`、`pageSize`、`throwException` 不在 JEP 471 范围内。

**迁移方向**：
- 堆内字段偏移与原子更新 → `java.lang.invoke.VarHandle`（JEP 193, JDK 9），动态感知对象布局，避免硬编码偏移的内存损坏风险。
- 堆外内存管理 → `java.lang.foreign.MemorySegment`（JEP 454, JDK 22），配合 `Arena` 作用域自动释放。

## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)
- [Reflection](/docs/CS/Java/JDK/Basic/Reflection.md)
- [Ref](/docs/CS/Java/JDK/Basic/Ref.md?id=cleaner)
- [Object Header](/docs/CS/Java/JDK/JVM/Object_Header.md)
- [Valhalla](/docs/CS/Java/JDK/Valhalla.md)
- [Lock](/docs/CS/Java/JDK/Concurrency/Lock.md)

## References

1. [Java魔法类：Unsafe应用解析 - 美团技术团队](https://tech.meituan.com/2019/02/14/talk-about-java-magic-class-unsafe.html)
2. [JEP 471: Deprecate the Memory-Access Methods in sun.misc.Unsafe for Removal](https://openjdk.org/jeps/471)
3. [JEP 454: Foreign Function & Memory API](https://openjdk.org/jeps/454)
4. [JEP 193: Variable Handles](https://openjdk.org/jeps/193)
