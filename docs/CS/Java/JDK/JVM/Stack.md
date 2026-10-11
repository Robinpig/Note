## Introduction

Java Virtual Machine Stacks（Java 虚拟机栈）是 [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md) 中线程私有的一块内存，
生命周期与线程相同。每个 Java 方法被调用时，JVM 都会同步创建一个 **Stack Frame（栈帧）** 压入当前线程的虚拟机栈；
方法执行结束（无论正常 return 还是抛出未捕获异常）时栈帧出栈。

```
当前线程 VM Stack（后进先出）
        ┌─────────────────────┐
        │   frame: method C   │  ← 栈顶 = 当前正在执行的方法
        ├─────────────────────┤
        │   frame: method B   │
        ├─────────────────────┤
        │   frame: method A   │  ← main / 入口方法
        └─────────────────────┘
```

在活动线程中只有栈顶帧有效，称为 **Current Frame**，所有字节码指令都只对当前栈帧操作。
以上是规范层面的图景；落到 HotSpot 源码，这块内存还要回答三个更硬的问题：**它如何构造**
（`ThreadStackSize`、red / yellow / reserved / shadow 四个区、守卫页、`StackOverflowError` 与 SIGSEGV 的边界）；
**帧如何被定位与遍历**（`frame` 类只是几个指针，GC 靠 oop map 从字长槽里认出引用）；
**Loom 打破了什么**（虚拟线程的栈以堆上 chunk 链存在，"VM Stack 是连续内存"的说法已不成立）。
源码层帧表示的细节见 [frame](/docs/CS/Java/JDK/JVM/frame.md)，执行引擎视角见 [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)。

## Version Baseline

> [!NOTE]
> **版本口径**：本篇以 **JDK 27**（HotSpot `jdk-27-ga`）源码实测为准，LTS 基线 JDK 25。本主题最容易被写错的三点：
>
> 1. **`-XX:StackSize` 已彻底消失**：全源码树 grep 无一处命中，flag 统一叫 `ThreadStackSize`
>    （`share/runtime/globals.hpp:1472`），`-Xss` 也解析到它（`share/runtime/arguments.cpp:2188-2197`）。
> 2. **JEP 534 默认启用紧凑对象头，但不改变栈槽宽度**：`Interpreter::stackElementWords` 仍是 `1`
>    （`share/interpreter/abstractInterpreter.hpp:237`），LP64 上一个槽位仍占 8 字节。紧凑头改的是堆上的
>    `markWord`（narrow klass 挪进头部位 43–64，`share/oops/markWord.hpp:144-155`），与栈帧无关。
> 3. **守卫与水位机制已换代**：旧文档的 `os::guard_page`（往守卫页写 trap 指令）在本树 grep 不到，
>    守卫统一为 `os::guard_memory` → `mprotect(PROT_NONE)`；`StackWatermarkKind` 只剩 `gc` 一种
>    （`share/runtime/stackWatermarkKind.hpp:28-30`），JDK 21–24 时代的多 kind 已删。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Frame Structure

每个栈帧由四部分组成：

- **Local Variables Table（局部变量表）**：存放方法参数和方法内定义的局部变量，以变量槽（Variable Slot）为最小单位。
  `long`/`double` 占两个连续的 Slot，其余基本类型和对象引用占一个。实例方法的第 0 个 Slot 固定是 `this`。
  局部变量表的容量在编译期就写入方法的 Code 属性，运行期不会改变。
- **Operand Stack（操作数栈）**：字节码的工作区。`iload` 把变量压栈，`iadd` 弹出两个 int 相加再压回，
  `istore` 把栈顶写回局部变量表。方法调用时，调用方的操作数栈会通过参数传递与被调方的局部变量表重叠，避免参数拷贝。
- **Dynamic Linking（动态链接）**：指向运行时常量池中该栈帧所属方法的引用，
  支撑符号引用到实际方法入口的解析（静态分派/动态分派，见 invokevirtual）。
- **Return Address（方法返回地址）**：方法退出后回到调用方指令的位置。正常退出时由调用者的 PC 计数器恢复；异常退出时通过异常表确定。

这四段是**规范概念**。HotSpot 的物理帧长什么样、如何从一帧走到上一帧，见下文 The frame Class 一节与
[frame](/docs/CS/Java/JDK/JVM/frame.md)（vframe / compiledVFrame 等源码层帧表示）。

## Thread Stack Memory in HotSpot

一条 Java 线程的虚拟机栈就是一段 pthread 栈：`os::create_thread`（`os/linux/os_linux.cpp:1066`）用
`os::Posix::get_initial_stack_size`（`os/posix/os_posix.cpp:1205`）算出大小后设置 `pthread_attr_setstacksize`。
`-Xss` 由 `Arguments::parse_xss` 换算成 KB 存入 `ThreadStackSize`（内部单位 1024 字节、上限 1 GiB，
`share/runtime/arguments.cpp:1812-1861`），为 0 表示用系统默认。各平台默认值（KB，证据在各 `os_cpu/<os>_<cpu>/globals_*.hpp`）：

| 平台 | ThreadStackSize | VMThreadStackSize | CompilerThreadStackSize |
| :-- | :-- | :-- | :-- |
| linux-x86_64 | 1024 | 1024 | 1024 |
| linux-aarch64 | 2040 | 2040 | 2040 |
| macos-aarch64 | 2048 | 2048 | 2048 |
| macos-x86_64 | 1024 | 1024 | 1024 |
| windows-x64 | 0 即系统默认 | 0 即系统默认 | 0，debug 构建 1024 |

linux-aarch64 的 2040 是刻意比 2MB 小两页，防止线程栈被 2MB 大页 / THP 合并
（`os_cpu/linux_aarch64/globals_linux_aarch64.hpp:32-38` 注释）。

栈**创建之后不扩容**，调用深度超出这段内存即得 `StackOverflowError`。例外只有附着线程
（用户以 glibc `MAP_GROWSDOWN` 自建线程后 attach）靠 `os::Linux::manually_expand_stack` 配合内核扩栈
（`os/posix/os_posix.cpp:1350-1360`），以及主线程栈由 `os::Linux::capture_initial_stack` 从 `RLIMIT_STACK`
探测（`os/linux/os_linux.cpp:1344`）。

### Guard Zones

`ThreadStackSize` 圈出的区间并不全部可用。`StackOverflow` 类头注释给出布局（低地址在上、栈向低地址增长；
省略的下半段是 shadow zone 与 frame 0 直到高地址侧的 `stack_base()`）：

```cpp
  //
  // The Java thread stack is structured as follows:
  //
  //  (low addresses)
  //
  //  --  <-- stack_end()                   ---
  //  |  red zone                            |
  //  --  <-- stack_red_zone_base()          |
  //  |  yellow zone                        guard
  //  --  <-- stack_yellow_zone_base()       zone
  //  |  reserved zone                       |
  //  --  <-- stack_reserved_zone_base()    ---   ---
  //                                               ^
  //                                               |    <--  stack_overflow_limit() [somewhere in here]
  //                                               |  shadow zone size
  //                                               v
  //                                              ---   <--  shadow_zone_safe_limit()
  // (Here and below: not yet touched stack)
```

四个区由四个 flag 定义，**单位固定 4KB**，实际页更大时向上对齐
（`StackOverflow::initialize_stack_zone_sizes`，`share/runtime/stackOverflow.cpp:37-67`；flag 声明
`share/runtime/globals.hpp:1447-1470`）：

| Flag | 语义 | x86 默认页 | aarch64 默认页 | 换算 |
| :-- | :-- | :-- | :-- | :-- |
| `StackRedPages` | 不可恢复溢出区 | 1 | 1 | 4 KB |
| `StackYellowPages` | 可恢复溢出区 | 2，Windows 3 | 2 | 8 KB |
| `StackReservedPages` | `@ReservedStackAccess` 预留区 | 1，Windows 0 | 1 | 4 KB |
| `StackShadowPages` | bang 检测区，不保护 | 20，Win64 8，debug +4 | 20，debug +5 | 80 KB |

证据在 `cpu/x86/globals_x86.hpp:56-69` 与 `cpu/aarch64/globals_aarch64.hpp:45-56`。两个细节：
x86 shadow 取 20 页的原因写在源码注释里——`Java_java_net_SocketOutputStream_socketWrite0()`
在 unix 上有一个 64KB 栈上缓冲区，16 页只是它一家；且 x86 / aarch64 上 yellow 与 red 的**最小值就等于默认值**
（`MIN_STACK_YELLOW_PAGES DEFAULT_STACK_YELLOW_PAGES`），"把 StackYellowPages 调成 1"根本进不了 range。
red + yellow + reserved 合称 guard zone，整段被 `mprotect(PROT_NONE)`；
shadow zone **不保护也不预留**，它只是"每个 Java 方法入口一定向下 probe 的距离"。

### Guard Page Creation and Removal

`os::guard_page` 是 JDK 8 时代的机制（守卫页里放 trap 指令，执行到就 SIGILL）；JDK 27 全树已 grep 不到这个名字。
现役流程：`Thread::record_stack_base_and_size` 记录基址并 `stack_overflow_state()->initialize(base, end)`
（`share/runtime/thread.cpp:190-205`），`JavaThread::run()` 里 `create_stack_guard_pages()`
（`share/runtime/javaThread.cpp:600`）；主线程在 `Threads::create_vm` 中补打
（`share/runtime/threads.cpp:586-588`，EXPERIMENTAL 的 `DisablePrimordialThreadGuardPages` 可跳过，默认 false）。
`StackOverflow::create_stack_guard_pages`（`share/runtime/stackOverflow.cpp:79-111`）先
`os::create_stack_guard_pages`——Linux 上 `must_commit_stack_guard_pages()` 为 true，要用
`mmap(PROT_NONE)` 把尚未映射的栈底实占住（`os/linux/os_linux.cpp:3625`）——再 `os::guard_memory`，
Linux 实现即 `linux_mprotect(addr, size, PROT_NONE)`（`os/linux/os_linux.cpp:3820`）；失败则
`vm_exit_out_of_memory(... OOM_MPROTECT_ERROR ...)`。注意 Linux 上另有**一层不属于 HotSpot 的守卫**：
`os::Linux::default_guard_size`（`os/linux/os_linux.cpp:3282`）为 glibc 保留一页 guard 防止相邻栈 VMA
被 khugepaged 合并（`THPStackMitigation`），所以一个线程实际可能有 glibc 与 JVM 两段 guard。

最小栈在启动期校验：`os::set_minimum_stack_sizes`（`share/runtime/os.cpp:2508-2527`）=
平台底座 + guard zone + shadow zone 向上对齐页；`-Xss` 低于它打印
"The Java thread stack size specified is too small" 并**拒绝启动**——这是配置错误，不是运行期异常。

## Stack Banging and the SOE Boundary

HotSpot 不用"显式比较 sp 再抛异常"，而是 **stack banging**：每个 Java 方法入口沿栈向下按页写探测，
保证每次栈增长都踩进已被检查的区域；踩进 PROT_NONE 的 guard zone 即触发 SIGSEGV。设计目标四条（shadow 区
装下正常 native/VM 深度；bang 不能"溜过"守卫区；某些 OS 靠 bang 触发页提交；trap 必须落在 runtime 认识的
代码里）见 `share/runtime/stackOverflow.hpp:165-183`。

共享的编译期逻辑在 `AbstractAssembler::generate_stack_overflow_check`（`share/asm/assembler.cpp:121-150`）：

```cpp
void AbstractAssembler::generate_stack_overflow_check(int frame_size_in_bytes) {
  // Each code entry causes one stack bang n pages down the stack where n
  // is configurable by StackShadowPages. ... only java code can raise a
  // stack overflow exception using the stack banging mechanism.
  // The VM and native code does not detect stack overflow.
  ...
  int bang_offset = bang_end_safe;
  while (bang_offset <= bang_end) {
    // Need at least one stack bang at end of shadow zone.
    bang_stack_with_offset(bang_offset);
    bang_offset += page_size;
  }
}
```

解释器入口用 **growth watermark** 消掉绝大多数 bang（x86 `bang_stack_shadow_pages`，
`cpu/x86/templateInterpreterGenerator_x86.cpp:645-691`）：SP 仍高于"上次 bang 到的最低点"就整轮跳过；
否则逐页 bang 一个 shadow 区，最后仅当 SP 高于 safe limit 才把水位下调：

```cpp
  __ cmpptr(rsp, Address(thread, JavaThread::shadow_zone_growth_watermark()));
  __ jcc(Assembler::above, L_done);
  for (int p = 1; p <= n_shadow_pages; p++) {
    __ bang_stack_with_offset(p*page_size);
  }
  // Record the new watermark, but only if update is above the safe limit.
  __ cmpptr(rsp, Address(thread, JavaThread::shadow_zone_safe_limit()));
  __ jccb(Assembler::belowEqual, L_done);
  __ movptr(Address(thread, JavaThread::shadow_zone_growth_watermark()), rsp);
```

C2 用 `PhaseOutput::need_stack_bang`（`share/opto/output.cpp:353`）判断帧大小能否保证不再踩新页从而省略 bang。
VM 侧发起调用前还有预检：`JavaCalls::call_helper` 里 `os::stack_shadow_pages_available` 不够时直接返回
`STACK_OVERFLOW_ERROR`，根本不进入被调方法（`share/runtime/javaCalls.cpp:364`、`share/runtime/os.cpp:1663-1675`）。
反优化路径有对称约定：编译帧入口要多 bang 出 deopt 后解释器需要的深度，所以 deopt blob / uncommon trap
不应出现 SOE（`share/runtime/sharedRuntime.cpp:918-923` 注释；两处 `reguard_stack_if_needed` 见
`share/runtime/deoptimization.cpp:1617`、`share/opto/runtime.cpp:1944-1948`）。

bang 踩进守卫区的 SIGSEGV 由 `os::Posix::handle_stack_overflow` 裁决（`os/posix/os_posix.cpp:1297-1348`）：

```cpp
  StackOverflow* overflow_state = thread->stack_overflow_state();
  if (overflow_state->in_stack_yellow_reserved_zone(addr)) {
    if (thread->thread_state() == _thread_in_Java) {
      ...
      // Throw a stack overflow exception.  Guard pages will be re-enabled
      // while unwinding the stack.
      overflow_state->disable_stack_yellow_reserved_zone();
      *stub = SharedRuntime::continuation_for_implicit_exception(thread, pc, SharedRuntime::STACK_OVERFLOW);
    } else {
      // Thread was in the vm or native code.  Return and try to finish.
      overflow_state->disable_stack_yellow_reserved_zone();
      return true; // just continue
    }
  } else if (overflow_state->in_stack_red_zone(addr)) {
    // Fatal red zone violation. Disable the guard pages and keep
    // on handling the signal.
    overflow_state->disable_stack_red_zone();
    tty->print_raw_cr("An irrecoverable stack overflow has occurred.");
```

| 被踩区 | 线程状态 | 结果 |
| :-- | :-- | :-- |
| yellow | `_thread_in_Java` | 临时解除保护，抛 `StackOverflowError` |
| yellow | VM / native | 解除保护后返回继续（native 侧无溢出检测语义） |
| reserved | `_thread_in_Java` | 栈遍历找 `@ReservedStackAccess` 帧，有则放行该区，否则同 yellow |
| red | 任意 | 不可恢复，`disable_stack_red_zone` 后落入常规 SIGSEGV 处理 → hs_err 崩溃 |

所以 `StackOverflowError` 与崩溃的分界不是"递归深度"，而是**踩进 yellow 还是 red**：Java 帧把栈用光、
bang 落在 yellow → 干净的 SOE；异常处理链自己又把 yellow 用完（或 native/VM 栈过深）→ 落进 red →
进程崩溃，hs_err 带 `StackOverflowErrors=<次数>` 计数（`share/utilities/exceptions.cpp:561-562`）。
SOE 的构造刻意避开一切再耗栈的动作：`SharedRuntime::throw_StackOverflowError_common`
（`share/runtime/sharedRuntime.cpp:875-896`）注释明言"normal exception construction ... performs an upcall
to Java, and we're already out of stack space"，故不走 `<init>`、直接 `allocate_instance`；"delayed" 变体带
`Universe::delayed_stack_overflow_error_message` 消息（`share/memory/universe.cpp:719`）。展开穿过守卫区后由
`StackOverflow::reguard_stack` 重新打回保护（`share/runtime/stackOverflow.cpp:220-243`）。
Windows 不走信号路，`EXCEPTION_STACK_OVERFLOW` 在 VEH 里汇入同一个 `continuation_for_implicit_exception`
（`os/windows/os_windows.cpp:2720-2757`）。reserved zone 服务 `java.lang.annotation.ReservedStackAccess`：
被标注方法在接近栈耗尽时可继续递归一段，查找在
`SharedRuntime::look_for_reserved_stack_annotated_method`（`share/runtime/sharedRuntime.cpp:3400`）。

## The frame Class and Stack Walking

HotSpot 的 `frame` 不代表"一块内存"，只是几个指针（`share/runtime/frame.hpp:63-85` 节选）：

```cpp
class frame {
 private:
  // Instance variables:
  union {
    intptr_t* _sp; // stack pointer (from Thread::last_Java_sp)
    int _offset_sp; // used by frames in stack chunks
  };
  address   _pc; // program counter (the next instruction after the call)
  mutable CodeBlob* _cb; // CodeBlob that "owns" pc
  mutable const ImmutableOopMap* _oop_map; // oop map, for compiled/stubs frames only
  // ...
  bool        _on_heap;  // This frame represents a frame on the heap.
```

`_sp` 与 `_offset_sp` 的 union 已经预告：同一帧对象既可能指向线程栈，也可能指向**堆上的栈块**（见 Freeze Thaw）。
经典教材引用的 `java_frameSP() / out_frame_sp() / sender_sp()` 三段式是 JDK 8 时代 `frame.hpp` 的函数名；
**这些名字在 JDK 27 全树 grep 已不存在**，同一职责现在是三个访问器：`sp()` 是硬件意义的 raw sp；
`unextended_sp()` 是调用方扩展前的原始 sp；`sender_sp()` 是出帧指针。为什么需要 `unextended_sp`——
x86 帧文件注释（`cpu/x86/frame_x86.hpp:125-131`）：

```cpp
  // The interpreter and adapters will extend the frame of the caller.
  // Since oopMaps are based on the sp of the caller before extension
  // we need to know that value. However in order to compute the address
  // of the return address we need the real "raw" sp. By convention we
  // use sp() to mean "raw" sp and unextended_sp() to mean the caller's
  // original sp.
```

`sender_sp()` 的取法分帧类型：解释器帧从 fp 的 `interpreter_frame_sender_sp_offset = -1` 槽读保存值，
编译帧取 `fp + sender_sp_offset`（`cpu/x86/frame_x86.hpp:68`、`cpu/x86/frame_x86.inline.hpp:52-65,289`）。
x86 解释器帧的物理布局（`cpu/x86/frame_x86.hpp:34-52`，原注释即此图，地址自上而下递减）：

```
// Layout of asm interpreter frame:
//    [expression stack      ] * <- sp
//    [monitors              ]   \
//     ...                        | monitor block size
//    [monitors              ]   /
//    [monitor block size    ]
//    [byte code pointer     ]                   = bcp()                bcp_offset
//    [pointer to locals     ]                   = locals()             locals_offset
//    [constant pool cache   ]                   = cache()              cache_offset
//    [methodData            ]                   = mdp()                mdx_offset
//    [klass of method       ]                   = mirror()             mirror_offset
//    [Method*               ]                   = method()             method_offset
//    [last sp               ]                   = last_sp()            last_sp_offset
//    [old stack pointer     ]                     (sender_sp)          sender_sp_offset
//    [old frame pointer     ]   <- fp           = link()
//    [return pc             ]
//    [oop temp              ]                     (only for native calls)
//    [locals and parameters ]
//                               <- sender sp
```

规范的"动态链接"在图里对应 `cache() / method() / bcp()` 一组元数据槽；"操作数栈"是 sp 向下的低地址区
（`interpreter_frame_expression_stack_direction()` 返回 `-1`，`cpu/x86/frame_x86.hpp:175`）。
整体方向约定在 `StackOverflow::stack_available` 里写死：`// This code assumes java stacks grow down`
（`share/runtime/stackOverflow.hpp:320-321`）。帧遍历与 vframe 体系继续见 [frame](/docs/CS/Java/JDK/JVM/frame.md)。

## Interpreter Slots and OOPMap

GC 与 JVMTI 在任意安全点都要回答"这个帧的哪个字是引用"。编译帧靠 nmethod 内嵌的 `ImmutableOopMap`
（每个 safepoint pc 一张，缓存在 `frame._oop_map`，`share/runtime/frame.hpp:72`）；
**解释器帧没有预编译信息**——字节码本身不记录哪些槽存了 oop。解法是对方法做抽象解释，
按需生成 `(method, bci) -> InterpreterOopMap` 并缓存，这就是 OOPMap
（`share/interpreter/oopMapCache.hpp:32-46` 节选）：

```
// A Cache for storing (method, bci) -> oopMap.
// The memory management system uses the cache when locating object
// references in an interpreted frame.
//
// OopMapCache's are allocated lazily per InstanceKlass.
// The oopMap (InterpreterOopMap) is stored as a bit mask. If the
// bit_mask can fit into four words it is stored in
// the _bit_mask array, otherwise it is allocated on the heap.
```

掩码按槽一 bit、≤ `small_mask_limit = 4 * BitsPerWord` 时内联，否则 C 堆分配、跨 GC 持久。
GC 扫根时 `frame::oops_interpreted_do`（`share/runtime/frame.cpp:911-976`）消费它：

```cpp
  // The method pointer in the frame might be the only path to the method's
  // klass, and the klass needs to be kept alive while executing. The GCs
  // don't trace through method pointers, so the mirror of the method's klass
  // is installed as a GC root.
  f->do_oop(interpreter_frame_mirror_addr());
  ...
  InterpreterOopMap mask;
  if (query_oop_map_cache) {
    m->mask_for(m, bci, &mask);
  } else {
    OopMapCache::compute_one_oop_map(m, bci, &mask);
  }
  mask.iterate_oop(&blk);
```

另有两点：停在 invoke 处的帧要按签名补扫**调用方形成的参数槽**（`oops_interpreted_arguments_do`）；帧里的
method mirror 槽被无条件当根，因为沿 `Method*` 找 Klass 不是 GC 的追溯路径。

**槽位宽度与紧凑对象头无关**——每个槽就是一个机器字（`share/interpreter/abstractInterpreter.hpp:237-238`：
`stackElementWords = 1`、`stackElementSize = stackElementWords * wordSize`）。JEP 534 把 narrow klass
从独立压缩指针挪进 markWord 高位（`klass_shift = 42`，占位 43–64，`share/oops/markWord.hpp:144-155`），
堆对象头省了字，但**栈槽一个字节都不少**：LP64 上引用槽仍是 8 字节，`UseCompactObjectHeaders` 与
`UseCompressedOops` 同开也不变。真正改变"栈上引用表示"的只有一处：堆上的 stack chunk 被 GC 处理时
把槽内容重编码为 narrowOop（见下文 `transform`），解冻回线程栈前再解码回宽 oop——那是帧在堆里的表示法，
与线程栈无关。

## Stack Watermarks

`stackWatermark.hpp` 提供一个通用机制：**对一块正在执行的栈做惰性、增量、可并发的快照处理**
（`share/runtime/stackWatermark.hpp:63-68` 节选）："marking a frame (the watermark) from which returns
(or other forms of unwinding) will take a slow path to perform additional processing required when
exposing more frames that were part of the snapshot to the system"。水位指针是快照时刻的 SP；活跃帧会因
适配器与寄存器保存任意伸缩，所以比较一律拿**帧指针**对水位。状态压成一个 uint32——高 31 位 epoch、
最低位 is_done，可无锁读做快路径判断（`StackWatermarkState`，同文件 48-61 行）。
`StackWatermarkSet` 把多条水位挂成线程本地链表，暴露 `before_unwind` / `after_unwind`、`on_iteration`、
`on_safepoint`、`start_processing` / `finish_processing`（`share/runtime/stackWatermarkSet.hpp:35-95`）。
慢路径入口藏在安全点轮询里：未触发安全点时 `SafepointMechanism::compute_poll_word` 把 poll word
**直接写成最低水位值**（`share/runtime/safepointMechanism.cpp:81-104`），编译帧每帧必做的 poll 检查顺手完成
"是否退到水位之下"的判断，零额外开销。

JDK 27 中 `StackWatermarkKind` 只剩 `gc` 一种（`share/runtime/stackWatermarkKind.hpp:28-30`），
消费者是并发栈根处理者：ZGC 的 `ZStackWatermark`（`share/gc/z/zStackWatermark.hpp:58`）与 Shenandoah 的
`ShenandoahStackWatermark`（`share/gc/shenandoah/shenandoahStackWatermark.hpp:50`），GC 在并发周期里不停世界
地逐帧扫线程栈；需要把整条栈钉在"已处理"状态的遍历方（`StackWalker`、JVMTI、逃逸屏障）用
`KeepStackGCProcessedMark` 包住（`share/runtime/keepStackGCProcessed.hpp:33-36`，用法如 `share/prims/stackwalk.cpp:455`）。
说水位是"Loom stack chunk 的地基"，是因为**虚拟线程的栈随时会被搬进堆，前提是该范围的栈已被并发处理机制结清**：
freeze 在最后一刻调用 `ContinuationEntry::flush_stack_processing` 把水位以下的帧全部走完，才允许帧离开线程栈
（`share/runtime/continuationEntry.cpp:79-98`）；调试构建里 `assert_frames_in_continuation_are_safe`
逐帧验证水位安全（`share/runtime/continuationFreezeThaw.cpp:579-595`）。虚拟线程本身的行为
（挂载 / 卸载 / pinning）见 [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)，本篇不展开。

## Freeze Thaw and the Contiguous Stack

`runtime/continuationFreezeThaw.cpp` 实现 continuation 的冻结（yield）与解冻（run），开篇注释挑明工程约束
（`share/runtime/continuationFreezeThaw.cpp:91-107`）：freeze 可能发生在每次 I/O、每次获取 j.u.c. 锁、每次从
队列取消息，**每次操作的摊销预算约 100–150ns**；快路径上全编译帧整块复制、只 patch 最底帧，慢路径才做解释器
帧内部指针的相对化/绝对化并触发屏障。文件内的线程栈布局图（同文件 112-159 行，下半段 native freeze/thaw 帧省略）：

```
Thread-stack layout on freeze/thaw.
See corresponding stack-chunk layout in instanceStackChunkKlass.hpp

            +----------------------------+
            |      .                     |
            |      .                     |
            |      .                     |
            |   carrier frames           |
            |                            |
            |----------------------------|
            |                            |
            |    Continuation.run        |
            |                            |
            |============================|
            |    enterSpecial frame      |
            |  pc                        |
            |  rbp                       |
            |  -----                     |
        ^   |  int argsize               | = ContinuationEntry
        |   |  oopDesc* cont             |
        |   |  oopDesc* chunk            |
        |   |  ContinuationEntry* parent |
        |   |  ...                       |
        |   |============================| <------ JavaThread::_cont_entry = entry->sp()
        |   |  ? alignment word ?        |
        |   |----------------------------| <--\
        |   |                            |    |
        |   |  ? caller stack args ?     |    |   argsize (might not be 2-word aligned) words
Address |   |                            |    |   Caller is still in the chunk.
        |   |----------------------------|    |
        |   |  pc (? return barrier ?)   |    |  This pc contains the return barrier when the bottom-most frame
        |   |  rbp                       |    |  isn't the last one in the continuation.
        |   |                            |    |
        |   |    frame                   |    |
        |   |                            |    |
            +----------------------------|     \__ Continuation frames to be frozen/thawed
            |                            |     /
            |    frame                   |    |
            |                            |    |
            |----------------------------|    |
            |                            |    |
            |    frame                   |    |
            |                            |    |
            |----------------------------| <--/
            |                            |
            |    doYield/safepoint stub  | When preempting forcefully, we could have a safepoint stub
            |                            | instead of a doYield stub
            |============================| <- the sp passed to freeze
```

这张图已经暗示："栈"分成了载体栈上的一截和 chunk 里的一截。完整证据链：

1. **帧可以根本不在栈上**。chunk 是堆对象：`class stackChunkOopDesc : public instanceOopDesc`
   （`share/oops/stackChunkOop.hpp:48`），用普通 `MemAllocator::allocate()` 分配
   （`share/runtime/continuationFreezeThaw.cpp:1544`）。`frame` 的 `_on_heap` 与 `offset_sp / offset_fp`
   整型偏移就是为堆帧准备的（`share/runtime/frame.hpp:66-85`；x86 侧 `_offset_fp / _offset_unextended_sp`
   见 `cpu/x86/frame_x86.hpp:121-135`），chunk 内解释器帧的内部指针一律转成**相对 fp 的偏移**
   （`share/oops/instanceStackChunkKlass.hpp:45-47`）。
2. **一个 continuation 的栈是 chunk 链表**。每个 chunk 带 parent 指针，新 chunk 链到上一个非空 chunk
   （`share/runtime/continuationFreezeThaw.cpp:1595`）。已挂载虚拟线程的"这条 Java 栈" = 载体栈上从栈顶
   到解冻点的连续段 + 其下若干堆 chunk 段。
3. **monitors 的 lock stack 也会搬**：`FreezeBase::freeze_lockstack` 把线程 lock stack 复制进 chunk 头部
   （`share/runtime/continuationFreezeThaw.cpp:556-562`）。
4. **chunk 有大小上限，超了照样 SOE**。G1 把 `CollectedHeap::stack_chunk_max_size` 设为 humongous 阈值
   （`share/gc/g1/g1CollectedHeap.cpp:1363`；默认 0 即不限，`share/gc/shared/collectedHeap.cpp:70`），
   分配超限 chunk 直接抛 `StackOverflowError: Humongous stack chunk`
   （`share/runtime/continuationFreezeThaw.cpp:1559-1563,1631-1633`）——一种与线程栈守卫区无关的 SOE 来源。
5. **GC 处理过的 chunk 里引用表示变窄**。`stackChunkOopDesc::transform` 进入 gc 模式、建 bitmap，逐帧经
   `CompressOopsOopClosure::convert_oop_to_narrowOop` 把宽 oop 压成 narrowOop 存回原槽
   （`share/oops/stackChunkOop.cpp:356-367`、`share/gc/shared/barrierSetStackChunk.cpp:46-80`）；
   解冻前 `fix_thawed_frame` → `decode_gc_mode` 还原（`share/oops/stackChunkOop.cpp:426-440`）。
6. **最底帧的返回地址被换成 return barrier**（见上图 "pc (? return barrier ?)"；判定入口
   `Continuation::is_return_barrier_entry`，`share/runtime/continuation.hpp:102`），
   所以"return 就弹栈"也不总成立——return 可能触发下一段 chunk 的解冻。

结论：规范与多数教材仍按"线程私有、连续、LIFO 的一小块栈内存"讲 VM Stack；JDK 27 的 HotSpot 里这句话
只对平台线程与已挂载部分成立——freeze/thaw 把"栈"变成了"线程栈段与堆 chunk 段拼接的惰性结构"，
连续内存只是快路径下暂时成立的表象。

## Stack Overflow and OOM

虚拟机栈的两种容量异常常被混为一谈：方法调用深度超过栈容量（最典型是无终止条件的递归）→ `StackOverflowError`；
创建新线程时无法为其分配栈 → `OutOfMemoryError`。结合上文，HotSpot 的精确边界是：bang 落进 yellow zone
（或 JavaCalls 预检不过、chunk 超 humongous 上限）得 SOE；落进 red zone 直接 hs_err 崩溃。
`OutOfMemoryError` 只发生在**线程创建期**——VM 栈创建后不扩容，`-Xss` 过小是启动失败而非运行期异常。
线程创建失败的文案 `OS_NATIVE_THREAD_CREATION_FAILED_MSG`（`share/runtime/os.hpp:1106`）：
"unable to create native thread: possibly out of memory or process/resource limits reached"。

## Stack Allocation and Escape Analysis

栈帧内的局部变量随方法返回自动销毁，不需要 GC 介入。若 JIT 通过逃逸分析（Escape Analysis）确认一个对象
**不会逃逸出方法/线程**（NoEscape），可能做 **Scalar Replacement（标量替换）**：对象根本不创建，
其字段拆散为标量直接分配在寄存器或局部变量表中，比在 [Heap](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md?id=heap) 上分配再回收便宜得多。
注意「栈上分配」在 HotSpot 中并非真的把对象塞进 Java 虚拟机栈，而是标量替换的通俗说法；
反优化时虚拟对象又要在帧里"具象化"，见 [Deoptimization](/docs/CS/Java/JDK/JVM/Deoptimization.md)。

## Native Method Stack

与虚拟机栈的区别仅在于：虚拟机栈为 Java 方法（字节码）服务，[Native Method Stacks](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md?id=native-method-stacks)
为 [JNI](/docs/CS/Java/JDK/Basic/JNI.md) native 方法服务。HotSpot 直接把两者合二为一——native 帧就是同一段
pthread 栈上的 C 帧，也因此共享同一套 shadow zone："shadow 页必须装下最深的一次 native/VM 调用"正是这个
设计的代价（`cpu/x86/globals_x86.hpp:64-66` 的 64KB socket 缓冲注释就是实例）。

## Links

- [frame](/docs/CS/Java/JDK/JVM/frame.md)
- [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)
- [GC](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [VirtualThread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)

## References

- [The Java® Virtual Machine Specification: Run-Time Data Areas](https://docs.oracle.com/javase/specs/jvms/se27/html/jvms-2.html#jvms-2.5)
- [The Java® Virtual Machine Specification: Frames](https://docs.oracle.com/javase/specs/jvms/se27/html/jvms-2.html#jvms-2.6)
- [JEP 450: Compact Object Headers (Experimental)](https://openjdk.org/jeps/450)
- [JEP 534: Compact Object Headers by Default](https://openjdk.org/jeps/534)
- [HotSpot Virtual Machine Command-Line Options](https://docs.oracle.com/en/java/javase/27/vm/tools.html)
- [ReservedStackAccess (Java SE 27 API Specification)](https://docs.oracle.com/en/java/javase/27/docs/api/java.base/java/lang/annotation/ReservedStackAccess.html)
