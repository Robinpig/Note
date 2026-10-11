## Introduction

HotSpot 里的 `frame` 不是对象，而是**对一段栈内存的解读方式**：只装 `{sp, fp, pc}` 加少量缓存，
字段全是可拷贝的值，没有基类、没有 `virtual`、不继承 `ResourceObj`。类注释
（`runtime/frame.hpp:57-61`）同时给出了它与 vframe 的分工：

```cpp
// A frame represents a physical stack frame (an activation).  Frames
// can be C or Java frames, and the Java frames can be interpreted or
// compiled.  In contrast, vframes represent source-level activations,
// so that one physical frame can correspond to multiple source level
// frames because of inlining.
```

正因为是值类型，栈遍历、GC 根扫描、反优化、JVMTI 才敢在热路径上按值返回、按值拷贝、随手重建帧：
`frame::sender()` 返回 `frame`，`vframe::_fr` 内嵌一个 `frame`，
`runtime/continuationFreezeThaw.cpp` 在冻结/解冻里构造大量临时帧。需要多态的是**源码级视图**
`vframe`（`runtime/vframe.hpp:58` 才是 `ResourceObj` 子类）。

本页是「栈帧」家族的**实现主页**：帧的字段、种类如何判定、sender 链、x86 与 aarch64 差异、
堆上帧、解释器帧内布局、vframe 家族。与 [Stack](/docs/CS/Java/JDK/JVM/Stack.md) 的分工固定：
**Stack 讲这块内存**（`-Xss`、保护页、`StackOverflowError`、《规范》四要素），
**本页讲如何解读其中一段**。所以本页不复述栈页数字——那几个 flag 是 `product_pd`，各平台默认值不同
（`DEFAULT_STACK_SHADOW_PAGES` 在 x86 是 `NOT_WIN64(20) WIN64_ONLY(8)`，见
`cpu/x86/globals_x86.hpp:66`；aarch64 / riscv 为 20，arm 为 5），抄成快照表必然过时。

## Version Baseline

> [!NOTE]
> **版本口径**：本主题三处极易照旧书抄错。
> 1. **`frame` 没有子类家族**。`interpreterFrame` / `compiledFrame` / `entryFrame` / `nativeFrame` /
>    `sentryFrame` / `runtimeFrame` / `javaFrame` / `optimizedFrame` 以及 `idtype` 枚举，在 JDK 27 全树
>    grep **零命中**；帧类型改成 `frame` 上的一组**非虚谓词**。
> 2. **JEP 534 不改栈槽宽度**：一个 JVM 槽恒等于一个机器字（`interpreter/abstractInterpreter.hpp:237`），
>    紧凑头对帧的影响落在 `BasicLock`——**displaced header 字段已删除**。旧代码里的
>    `frame::wordsize_ex()` 也已不存在。
> 3. **帧不一定在栈上**：Loom 之后 `frame` 可以指向 Java 堆里的 stack chunk（`_on_heap`），
>    此时内部指针全部**相对 fp 存储**，`sp()` / `fp()` / `id()` 对这类帧不可用。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## frame Is a Value Type

字段清单（`runtime/frame.hpp:65-85` + `cpu/x86/frame_x86.hpp:120-135`）：

| 字段 | 位置 | 作用 |
| :-- | :-- | :-- |
| `union { intptr_t* _sp; int _offset_sp; }` | `runtime/frame.hpp:66-69` | 栈指针；堆上帧存相对偏移 |
| `address _pc` | `:70` | 本帧将要继续执行的指令，非硬件返回地址 |
| `mutable CodeBlob* _cb` | `:71` | 拥有 `_pc` 的 CodeBlob，多数判定的入口 |
| `mutable const ImmutableOopMap* _oop_map` | `:72` | 编译帧 / stub 帧的 oop map，惰性求值 |
| `deopt_state _deopt_state` | `:73-79` | `not_deoptimized` / `is_deoptimized` / `unknown` |
| `bool _on_heap` | `:84` | 是否为堆上（continuation）帧 |
| `DEBUG_ONLY(int _frame_index)` | `:85` | chunk 内帧序号，栈上帧为 -1 |
| `union { intptr_t* _fp; int _offset_fp; }` | `cpu/x86/frame_x86.hpp:121-124` | 帧指针（aarch64 同） |
| `union { intptr_t* _unextended_sp; int _offset_unextended_sp; }` | `cpu/x86/frame_x86.hpp:132-135` | 被 callee 扩展前的调用方 sp |
| `bool _sp_is_trusted` | `cpu/aarch64/frame_aarch64.hpp:147` | **仅 aarch64**：`_sp` 能否用来推 sender_sp |

三条支撑「值类型」的证据：

1. **无虚表**：`class frame {` 后直接 `private:`（`runtime/frame.hpp:63`），全类无 `virtual`；
   vframe 的类型判定却是虚函数（`runtime/vframe.hpp:95-98`）。
2. **相等即值相等**：`frame::equal()` 逐项比 `sp / unextended_sp / fp / pc`
   （`cpu/x86/frame_x86.inline.hpp:223-230`）；`frame::id()` 返回 `real_fp()`（同文件 `:235`），
   **地址就是身份**。默认构造的 `frame()` 是空帧（`is_empty()` 判 `_pc == nullptr`，
   `runtime/frame.hpp:185`），`frame::next_frame()` 正拿它当「走不下去」的返回值
   （`runtime/frame.cpp:1551`）。
3. **不继承 `AnyObj`**：`AnyObj` 在 ASSERT 构建下要为记录分配位置多付两个字
   （`uintptr_t _allocation_t[2]`，`memory/allocation.hpp:441-447`），而帧的拷贝次数以万计。

最直接的证明是 JFR 那组**静态** helper（`runtime/frame.hpp:514-524`，`#if INCLUDE_JFR`）：
不构造 `frame`，直接从裸 `fp` / `sp` 取值——`interpreter_bcp(fp)` 读 `fp[interpreter_frame_bcp_offset]`、
`return_address(sp)` 读 `sp[-1]`、`fp(sp)` 读 `sp[-2]`（`cpu/x86/frame_x86.inline.hpp:42-81`）。
调用方是异步采样器 `jfr/periodic/sampling/jfrSampleRequest.cpp:53,79,87,180`：信号语境里
不能分配对象、不能拷寄存器表，只有纯地址运算能活下来。同理 GC 扫 Java 帧也不需要完整
`RegisterMap`——Java 帧除 `rbp` 外没有 callee-saved 寄存器（注释见
`cpu/x86/smallRegisterMap_x86.inline.hpp:33`），于是有 constexpr 单例 `SmallRegisterMapNoArgs` /
`SmallRegisterMapWithArgs`（`runtime/smallRegisterMap.inline.hpp:32-45`），
`oops_interpreted_do` 被模板化以同时接受两者（`runtime/frame.cpp:976-978`）。

## Frame Kinds As Predicates

| 谓词 | 判定依据 | 位置 |
| :-- | :-- | :-- |
| `is_interpreted_frame()` | `Interpreter::contains(pc())` | `cpu/x86/frame_x86.inline.hpp:382`、`cpu/aarch64/frame_aarch64.inline.hpp:398` |
| `is_compiled_frame()` | `_cb->is_nmethod() && is_java_method()` | `runtime/frame.inline.hpp:65-72` |
| `is_native_frame()` | nmethod 且 `is_native_method()` | `runtime/frame.cpp:245-249` |
| `is_runtime_frame()` | `_cb->is_runtime_stub()` | `runtime/frame.cpp:257-259` |
| `is_safepoint_blob_frame()` | `_cb->is_safepoint_stub()` | `runtime/frame.cpp:261-263` |
| `is_stub_frame()` | `StubRoutines::is_stub_code(pc)` 或 adapter blob | `runtime/frame.inline.hpp:51-53` |
| `is_entry_frame()` | `StubRoutines::returns_to_call_stub(pc())` | `runtime/frame.inline.hpp:47-49` |
| `is_upcall_stub_frame()` | `_cb->is_upcall_stub()` | `runtime/frame.inline.hpp:61-63` |
| `is_java_frame()` | interpreted 或 compiled | `runtime/frame.cpp:251-255` |
| `is_ignored_frame()` | **恒 false**，注释 `FIXME: some LambdaForm frames should be ignored` | `runtime/frame.cpp:241-243` |
| `is_deoptimized_frame()` | `_deopt_state == is_deoptimized` | `runtime/frame.inline.hpp:87-90` |
| `is_heap_frame()` | `_on_heap` | `runtime/frame.hpp:197` |
| `is_first_frame()` | entry 帧且 `entry_frame_is_first()`，或 upcall stub 到底 | `runtime/frame.inline.hpp:55-59` |

判定的三个底层来源，全部只看 `pc` 与 `_cb`，**不读栈内存**：

- **解释器帧**：`Interpreter::contains(pc)` → `_code != nullptr && _code->contains(pc)`
  （`interpreter/templateInterpreter.hpp:141`），`_code` 是启动时生成的 codelet 队列
  （`interpreter/templateInterpreter.cpp:54-55`）。
- **entry 帧**：一次相等比较 `return_pc == _call_stub_return_address`
  （`cpu/x86/stubRoutines_x86.hpp:32`、`cpu/aarch64/stubRoutines_aarch64.hpp:33-35`），
  该地址由 stubGenerator 生成 call_stub 时记录（`cpu/x86/stubGenerator_x86_64.cpp:306,4751`）。
- **其余帧**：`_cb = CodeCache::find_blob(pc)`（`cpu/x86/frame_x86.inline.hpp:109,180`）；
  `get_cb()` 在 `_cb` 为空时顺手把 oop map 槽位一起找出来（`runtime/frame.inline.hpp:121-131`），
  这就是 `mutable` 的用途。

`frame::print_name()`（`runtime/frame.cpp:526-535`）给出这些谓词的使用顺序，也就是线程栈 dump 里
能出现的种类：`Native` → `Interpreted` → `Deoptimized` / `Compiled` → `Empty` → **`C`**。
末项才是真 native 帧——它没有 CodeBlob。

### Removed Subclass Family

| 旧类名 | JDK 27 现状 | 证据 |
| :-- | :-- | :-- |
| `interpreterFrame` | 谓词 + 一族 `interpreter_frame_*()` 直接挂在 `frame` 上 | `runtime/frame.hpp:312-404` |
| `compiledFrame` | `is_compiled_frame()` + `sender_for_compiled_frame()` | `runtime/frame.inline.hpp:65`、`cpu/x86/frame_x86.inline.hpp:427` |
| `entryFrame` | `is_entry_frame()`；**仅 Zero 平台保留同名类** `EntryFrame : public ZeroFrame` | `cpu/zero/entryFrame_zero.hpp:43` |
| `nativeFrame` | `is_native_frame()` 指 native 方法的 nmethod 帧，**不是 C 帧**；C 帧走 `os::get_sender_for_C_frame()` | `runtime/frame.cpp:245,1567-1572` |
| `sentryFrame` | 由 `is_first_frame()` + `JavaCallWrapper::is_first_frame()`（判 `_anchor.last_Java_sp() == nullptr`）承担 | `runtime/frame.inline.hpp:55`、`runtime/javaCalls.hpp:67` |
| `runtimeFrame` | 谓词 + **主动跳过**：`real_sender()` 与 `new_vframe()` 都会越过它 | `runtime/frame.cpp:417-424`、`runtime/vframe.cpp:77-82` |
| `javaFrame` | `is_java_frame()`；`javaVFrame` 还在，但属 vframe 侧 | `runtime/frame.cpp:251`、`runtime/vframe.hpp:109` |
| `optimizedFrame` | `_deopt_state` 三态 + `raw_pc()` / `patch_pc()` + `ScopeDesc` 展开 | `runtime/frame.hpp:73-79`、`runtime/frame.cpp:205-213` |
| `idtype` | 枚举整体删除；`runtime/frame.hpp:167-172` 仍留「sparc/ia32 用 sp 当 id」的注释，**实际 `id()` 返回 `real_fp()`** | `cpu/x86/frame_x86.inline.hpp:235` |

⚠️ 别把 `sentry` 当线索：`interpreter/templateInterpreter.hpp:50` 的 `EntryPoint(..., address sentry, ...)`
是**按返回类型分派的方法入口表**里 `stos`（reference-to-String）那一项
（`interpreter/templateInterpreter.cpp:98-110`），与 `sentryFrame` 无关。

### ContinuationHelper Frame Kinds

新增的「帧种类家族」在 Loom 侧，且刻意不是运行时对象：`runtime/continuationHelper.hpp:65-160`
里 `ContinuationHelper::Frame` 及其派生类全部 `: public AllStatic`，用
`static const bool interpreted / compiled / stub / native` 当编译期 trait，再以模板参数 `FKind`
喂给 freeze/thaw。派生关系：`Frame` → `InterpretedFrame`（`:87`，`ExtraT` 是 `InterpreterOopMap*`）
与 `NonInterpretedFrame`（`:114`）→ `NonInterpretedUnknownFrame`（`:124`）、`CompiledFrame`（`:129`）、
`NativeFrame`（`:141`，`stack_argsize()` 恒 0）、`StubFrame`（`:154`）。分派只有一行：
`runtime/continuationFreezeThaw.cpp:468-470` 按 `f.is_interpreted_frame()` 选 `sender<InterpretedFrame>`
还是 `sender<CompiledFrame>`。这仍是「谓词代替子类」的风格——分类信息来自 `frame`，
派生类只提供**编译期**行为。

## No fp Tag Bits

常见说法「HotSpot 靠 fp 低位打标签识别帧类型」「fp 指向一张帧类型常量表」，在 JDK 27 的
`cpu/x86/frame_x86.*` 与 `cpu/aarch64/frame_aarch64.*` 里找不到依据。唯一对 fp 做的位运算是
**对齐检查**（`cpu/x86/frame_x86.cpp:475-482`，节选）：

```cpp
bool frame::is_interpreted_frame_valid(JavaThread* thread) const {
  assert(is_interpreted_frame(), "Not an interpreted frame");
  // These are reasonable sanity checks
  if (fp() == nullptr || (intptr_t(fp()) & (wordSize-1)) != 0) {
    return false;
  }
```

（aarch64 同名函数 `cpu/aarch64/frame_aarch64.cpp:488`。）低比特打标签在 HotSpot 里只存在于
**对象头**：`oops/markWord.hpp:33-72` 的 `lock:2`。

`_fp` 真正的坑是**含义随帧类型而变**：
- 解释器帧：`fp()` 就是本帧所有槽位的基址，`fp[0]`（`link_offset`）存的才是 sender 的 fp。
- 编译帧：`_fp` 只是「调用时保存的那个寄存器值」。x86 注释：「This is the saved value of EBP which
  may or may not really be an FP. It is only an FP if the sender is an interpreter frame (or C1?)」
  （`cpu/x86/frame_x86.inline.hpp:438-440`）；aarch64 更直白：C2 把 `rfp` 当**可分配的
  callee-saved 寄存器**（`cpu/aarch64/frame_aarch64.inline.hpp:498-501`）。
- 需要 ABI 意义的帧指针时用 `real_fp()`：优先 `unextended_sp() + _cb->frame_size()`，
  拿不到合法 frame_size 才退回 `fp()`（`cpu/x86/frame_x86.inline.hpp:253-264`）。

两平台 `PreserveFramePointer` 默认都是 `false`（`cpu/x86/globals_x86.hpp:85`、
`cpu/aarch64/globals_aarch64.hpp:68`；声明在 `runtime/globals.hpp:1863`），
所以默认配置下**不要假定 `fp()` 是帧指针**。防御手段因此只剩「先造出 sender 再验证」的
`frame::safe_for_sender()`（`cpu/x86/frame_x86.cpp:56-269`）。

### Classification Drives GC Scanning

`frame::oops_do`（`runtime/frame.hpp:481-499`）转发到 `oops_do_internal`
（`runtime/frame.cpp:1152-1170`，节选）：

```cpp
  if (is_interpreted_frame()) {
    oops_interpreted_do(f, map, use_interpreter_oop_map_cache);
  } else if (is_entry_frame()) {
    oops_entry_do(f, map);
  } else if (is_upcall_stub_frame()) {
    oops_upcall_do(f, map);
  } else if (CodeCache::contains(pc())) {
    oops_nmethod_do(f, cf, df, derived_mode, map);
  } else {
    ShouldNotReachHere();
  }
```

与旧版本的差异值得记一笔：闭包类型 `CodeBlobClosure` 已换成 `NMethodClosure`；新增
`is_upcall_stub_frame()` 一支（FFM）；`CrashGCForDumpingJavaThread` 从「故意写空指针」改成
`guarantee`（同文件 `:1155-1158`）。`oops_interpreted_do`（`:911-974`）里最容易被漏掉的一条是
**klass mirror 强制作为根**：注释说明帧里的 `Method*` 可能是唯一能到达其 klass 的路径，而 GC 不跟
`Method*`（`:940-944`）；此外停在 invoke 上时由本帧代扫尚未建帧的 callee 实参
（`:952-961`，靠 `map->include_argument_oops()`）。`frame::metadata_do`（`:1180-1187`）
只对解释器帧上报 `Method*`。

## Interpreter Frame Layout

### x86 Layout

`cpu/x86/frame_x86.hpp:34-53` 的原图，地址向下增长：

```text
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

`fp[]` 下标（两平台各自 enum，`cpu/x86/frame_x86.hpp:56-109`、
`cpu/aarch64/frame_aarch64.hpp:68-116`；正向槽两平台一致：`link_offset=0`、
`return_addr_offset=1`、`sender_sp_offset=2`、`interpreter_frame_oop_temp_offset=2`、
`..._result_handler_offset=3`）：

| 槽 | x86 | aarch64 |
| :-- | --: | --: |
| `interpreter_frame_sender_sp` | -1 | -1 |
| `interpreter_frame_last_sp` | -2 | -2 |
| `interpreter_frame_method` | -3 | -3 |
| `interpreter_frame_mdp` | -5 | -4 |
| `interpreter_frame_extended_sp` | — | -5 |
| `interpreter_frame_mirror` | -4 | -6 |
| `interpreter_frame_cache` | -6 | -7 |
| `interpreter_frame_locals` | -7 | -8 |
| `interpreter_frame_bcp` | -8 | -9 |
| `interpreter_frame_initial_sp` | -9 | -10 |

aarch64 因多一个 `extended_sp` 槽而比 x86 宽一字，其布局注释
（`cpu/aarch64/frame_aarch64.hpp:35-65`）另外标出 `padding`（机器 sp 对齐用）。
两平台 `frame_alignment = 16`、`align_wiggle = 1`、`metadata_words = sender_sp_offset = 2`；
entry 帧常量差异见下面的差异表。

### Slot Sizing

- 一个 JVM 槽 = 一个机器字：`stackElementWords = 1`、`stackElementSize = stackElementWords * wordSize`
  （`interpreter/abstractInterpreter.hpp:237-239`）。
- 表达式栈方向：`interpreter_frame_expression_stack_direction()` **所有平台都返回 -1**
  （`cpu/x86/frame_x86.hpp:175`、`cpu/aarch64/frame_aarch64.hpp:190`）。但
  `expr_offset_in_bytes` 在 PPC / S390 上要额外 `+ wordSize`（「point to one word past TOS」，
  `interpreter/abstractInterpreter.hpp:245-250`）——跨平台抄偏移最容易踩的一处。
- 三个指针：`interpreter_frame_expression_stack()` = `monitor_end - 1`，即表达式栈**底**
  （`cpu/x86/frame_x86.inline.hpp:356-359`）；`interpreter_frame_tos_address()` 优先用 `last_sp`，
  为空才用 `sp()`（同文件 `:331-342`，注释解释 adapter 可能改动 sp）；
  `interpreter_frame_locals()` = `&fp()[n]`（同文件 `:291-294`）。
- 元素个数 `interpreter_frame_expression_stack_size()` =
  `(expression_stack - tos_address + 1) / stackElementWords`（`runtime/frame.cpp:508-522`）；
  bci 不存，存 bcp，靠 `Method::bci_from` 反算（`:446-456`）。

⚠️ **`locals` / `last_sp` / `monitor_block_top` 存的已不是绝对地址，而是相对 fp 的偏移**：
读时 `&fp()[n]`，写时 `ptr_at_put(..., value - fp())`，源码注释直接写着
`// set relativized locals`（`cpu/x86/frame_x86.inline.hpp:291-300`、
`cpu/x86/frame_x86.cpp:319-323,352-364`）。旧书「locals 指针」的写法在 JDK 27 上会读出天书。

## Sender Chain

### unextended_sp and sender_sp

`cpu/x86/frame_x86.hpp:125-135` 把双 sp 的必要性说清了（原文）：

```cpp
  // The interpreter and adapters will extend the frame of the caller.
  // Since oopMaps are based on the sp of the caller before extension
  // we need to know that value. However in order to compute the address
  // of the return address we need the real "raw" sp. By convention we
  // use sp() to mean "raw" sp and unextended_sp() to mean the caller's
  // original sp.
```

`frame_size()` 因此分两路：解释器帧 = `sender_sp - sp`，编译帧直接
`cb()->frame_size()`（`cpu/x86/frame_x86.inline.hpp:266-270`）。
`sender_sp()` 读 `fp[2]`（同文件 `:289`），语义是**调用方的 raw sp**；调用方的 unextended sp
另占一槽 `interpreter_frame_sender_sp()` = `fp[-1]`（`cpu/x86/frame_x86.cpp:327-330`）。
`safe_for_sender()` 点明区别：「the value below is the sender "raw" sp, which can be different
from the sender unextended sp (the sp seen by the sender) because of current frame local
variables」（`cpu/x86/frame_x86.cpp:127-131`）。

### sender Dispatch

```cpp
inline frame frame::sender_raw(RegisterMap* map) const {
  map->set_include_argument_oops(false);

  if (map->in_cont()) { // already in an h-stack
    return map->stack_chunk()->sender(*this, map);
  }

  if (is_entry_frame())       return sender_for_entry_frame(map);
  if (is_upcall_stub_frame()) return sender_for_upcall_stub_frame(map);
  if (is_interpreted_frame()) return sender_for_interpreter_frame(map);

  assert(_cb == CodeCache::find_blob(pc()), "Must be the same");
  if (_cb != nullptr) return sender_for_compiled_frame(map);

  // Must be native-compiled frame, i.e. the marshaling code for native
  // methods that exists in the core system.
  return frame(sender_sp(), link(), sender_pc());
}
```
（`cpu/x86/frame_x86.inline.hpp:406-425`，删去两处空注释行；aarch64 版
`cpu/aarch64/frame_aarch64.inline.hpp:421-444`。）外层 `frame::sender()` 只多做一件事：
`StackWatermarkSet::on_iteration(thread, result)`，把「走到哪一帧」广播给虚拟线程水位线；
紧随的断言 `result.is_older(this->id())` 特意放过堆上帧——**`id()` 对 heap frame 不可用**
（同文件 `:393-404`）。

- `sender_for_interpreter_frame`（`cpu/x86/frame_x86.cpp:447-473`）：三个量分别来自
  `sender_sp()`（raw）、`interpreter_frame_sender_sp()`（unextended）、`link()`（saved fp），
  `sender_pc` 取 `fp[1]`；若 `sender_pc` 是 return barrier 则转进 continuation。
- `sender_for_compiled_frame`（`cpu/x86/frame_x86.inline.hpp:427-476`）：
  `sender_sp = unextended_sp() + _cb->frame_size()`，返回地址 `*(sender_sp - 1)`，
  saved fp `*(sender_sp - sender_sp_offset)`；再手工把 `rbp` 的位置写进 RegisterMap——
  prolog 存了 rbp 却没有对应的 oop map 条目（`:458-461` 注释）。
- 两者都会 `map->set_include_argument_oops(...)`，这正是**整条链必须复用同一个 RegisterMap**
  的原因（`runtime/registerMap.hpp:44-56`）。

### Entry Frame and JavaFrameAnchor

entry 帧没有内存意义上的上一帧，它的 sender 来自 `JavaCallWrapper` 保存的 `JavaFrameAnchor`
（`cpu/x86/frame_x86.cpp:366-381`，节选）：

```cpp
frame frame::sender_for_entry_frame(RegisterMap* map) const {
  // Java frame called from C; skip all C frames and return top C
  // frame of that chunk as the sender
  JavaCallWrapper* jfa = entry_frame_call_wrapper()->anchor();
  assert(!entry_frame_is_first(), "next Java fp must be non zero");
  assert(jfa->last_Java_sp() > sp(), "must be above this frame on stack");
  jfa->make_walkable();
  map->clear();
  frame fr(jfa->last_Java_sp(), jfa->last_Java_fp(), jfa->last_Java_pc());
```

`entry_frame_call_wrapper_addr()` 读的槽位随 ABI 而变：ELF x86-64 是 `fp[-6]`、Win64 是 `fp[2]`
（`cpu/x86/frame_x86.hpp:83-93`），aarch64 是 `fp[-8]`，且注释明说「these values are determined
by the layout defined in stubGenerator for the Java call stub」
（`cpu/aarch64/frame_aarch64.hpp:94-98`）。递归终点是
`JavaCallWrapper::is_first_frame()`：`_anchor.last_Java_sp() == nullptr`（`runtime/javaCalls.hpp:67`）。

反方向的入口在锚点上：`JavaThread::last_frame()` = `make_walkable()` + `pd_last_frame()`
（`runtime/javaThread.hpp:949-952`），后者只是把 `_anchor` 三字段拼成帧
（`os_cpu/linux_x86/javaThread_linux_x86.cpp:28`）。锚点约定「`_last_Java_sp != nullptr` 时其余字段必须有效」
见 `runtime/javaFrameAnchor.hpp:58-73` 与 `cpu/x86/javaFrameAnchor_x86.hpp:29-66`；
Java→C→Java 的嵌套由此能一层层退回，调用约定见 [JavaCall](/docs/CS/Java/JDK/JVM/JavaCall.md)。

### java_sender and real_sender

```cpp
frame frame::java_sender() const {
  RegisterMap map(JavaThread::current(),
                  RegisterMap::UpdateMap::skip,
                  RegisterMap::ProcessFrames::include,
                  RegisterMap::WalkContinuation::skip);
  frame s;
  for (s = sender(&map); !(s.is_java_frame() || s.is_first_frame()); s = s.sender(&map)) ;
  guarantee(s.is_java_frame(), "tried to get caller of first java frame");
  return s;
}
```
（`runtime/frame.cpp:406-415`。）它**跳过所有中间 C 帧**，且不需要寄存器故传 `UpdateMap::skip`。
`real_sender()`（`:417-424`）方向相反，只跳 runtime / ignored 帧；`is_first_java_frame()`（`:267-275`）
是同一循环的布尔版。vframe 侧的 `vframe::java_sender()`（`runtime/vframe.cpp:109-118`）会额外在
虚拟线程入口与 `Continuation.enter` intrinsic 处停下。

### C Frames

`frame::next_frame(fr, t)`（`runtime/frame.cpp:1548-1574`）用于混合栈：`cb()->frame_size() > 0`
就走 `sender()`，否则走 `os::is_first_C_frame()` / `os::get_sender_for_C_frame()`。它的注释是本节
最实用的警告：「Compiled code may use EBP register on x86 so it looks like non-walkable C frame」。
`frame::verify_return_pc()`（`:1218-1234`）给出「一个返回地址是否可信」的判据：必须命中
`returns_to_call_stub` / `CodeCache::contains` / `Interpreter::contains` 之一。

遍历工具按 `RegisterMap` 的三个策略枚举组合（`runtime/registerMap.hpp:73-75`）：
`UpdateMap`（是否维护 callee-saved 位置）、`ProcessFrames`（是否触发 stack watermark 屏障）、
`WalkContinuation`（是否进入 h-stack）。`StackFrameStream` 按物理帧走
（`runtime/stackFrameStream.hpp:53-68`）、`StackChunkFrameStream` 走堆上 chunk
（`runtime/stackChunkFrameStream.hpp:41+`）、`vframeStream` 走源码级帧
（`runtime/vframe.hpp:318-326`）。线程侧入口一分为三：`last_frame()`（`runtime/javaThread.hpp:949`）、
`carrier_last_frame()`（`runtime/javaThread.cpp:1840-1849`）、`vthread_last_frame()`（同文件
`:1835-1838`）。线程与栈的持有关系见 [Thread](/docs/CS/Java/JDK/JVM/Thread.md)，
安全点期间的帧处理见 [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)。

## x86 and aarch64 Differences

| 维度 | x86-64 | aarch64 | 证据 |
| :-- | :-- | :-- | :-- |
| sender_sp 计算 | 恒为 `unextended_sp() + frame_size()` | 先看 `_sp_is_trusted`，不可信时改用 fp 相对的 `sender_sp()` | `cpu/aarch64/frame_aarch64.inline.hpp:452-453` |
| `_sp_is_trusted` | 无此字段 | 每次 `setup()` 置 false，只有从锚点取帧才 `set_sp_is_trusted()` | `cpu/aarch64/frame_aarch64.hpp:143-147`、`cpu/aarch64/frame_aarch64.inline.hpp:125`、`os_cpu/linux_aarch64/javaThread_linux_aarch64.cpp:29-33` |
| 帧元数据槽 | 9 个负偏移槽 | 多 `interpreter_frame_extended_sp`，initial_sp 从 -9 变 -10 | `cpu/x86/frame_x86.hpp:68-81`、`cpu/aarch64/frame_aarch64.hpp:79-93` |
| 返回地址 | 裸地址 | 可能被 FEAT_PAuth 签名：读要 `pauth_strip_pointer` / `pauth_strip_verifiable`，写回要 `pauth_sign_return_address` | `cpu/aarch64/frame_aarch64.inline.hpp:301-302,459`、`cpu/aarch64/frame_aarch64.cpp:280-302` |
| saved oop 结果寄存器 | `rax` | `r0` | `cpu/x86/frame_x86.inline.hpp:369-373`、`cpu/aarch64/frame_aarch64.inline.hpp:385-389` |
| entry 帧常量 | Win64 `28 / 2` 且 `arg_reg_save_area_bytes=32`；ELF `13 / -6` | `29 / -8`，无 save area | `cpu/x86/frame_x86.hpp:83-93`、`cpu/aarch64/frame_aarch64.hpp:94-101` |
| frame pointer 语义 | `rbp`，注释假定解释器总会存 | 注释明示 C2 把 `rfp` 当可分配 callee-saved 寄存器 | `cpu/x86/frame_x86.inline.hpp:478-496`、`cpu/aarch64/frame_aarch64.inline.hpp:496-511` |
| 无帧数学入口收尾 | `pop(rax); mov(rsp, r13); jmp(rax)` | `mov(sp, r19_sender_sp)` + `ret`，返回地址在 `lr` | `cpu/x86/templateInterpreterGenerator_x86_64.cpp:494-496`、`cpu/aarch64/templateInterpreterGenerator_aarch64.cpp:158-177` |

## Heap Frames in Stack Chunks

Loom 把虚拟线程栈**冻结**进 Java 堆上的 `stackChunkOop`，于是 `frame` 有了第二种存在形式。
`runtime/frame.hpp:81-84` 的注释就是设计说明（原文，含上游拼写 `adddresses`）：

```cpp
  // Do internal pointers in interpreter frames use absolute adddresses or relative (to fp)?
  // Frames in stack chunks are on the Java heap and use relative addressing; on the stack
  // they use absolute addressing
  bool        _on_heap;  // This frame represents a frame on the heap.
```

配套约束：`_sp` / `_fp` / `_unextended_sp` 全做成 union 以容纳 `int` 偏移
（`runtime/frame.hpp:66-69`）；`sp()` / `fp()` / `unextended_sp()` 内有 `assert_absolute()`、
偏移版有 `assert_offset()`（`:88-90,132-136`）；读槽位要选对 `at()` / `at_absolute()` /
`at_relative()`（`:257-270`，`at_relative` 把槽值当偏移再加 `fp`）；
`id()` / `is_older()` 不能用于堆上帧（`cpu/x86/frame_x86.inline.hpp:232-235`）。

走链时 `sender_raw()` 的第一个分支就把控制权交给 chunk（`map->in_cont()`，
`cpu/x86/frame_x86.inline.hpp:411-413`；`in_cont` 定义见 `runtime/registerMap.hpp:146`）。
实现是「还原 → 走一步 → 再相对化」（`oops/stackChunkOop.cpp:97-123`，节选）：

```cpp
frame stackChunkOopDesc::sender(const frame& f, RegisterMap* map) {
  int index = f.frame_index(); // we need to capture the index before calling derelativize, which destroys it
  StackChunkFrameStream<ChunkFrames::Mixed> fs(this, derelativize(f));
  fs.next(map);
  if (!fs.is_done()) {
    frame sender = fs.to_frame();
    relativize_frame(sender);
    sender.set_frame_index(index+1);
    return sender;
  }
  if (parent() != nullptr) { ... return parent()->top_frame(map); }
  return Continuation::continuation_parent_frame(map);
}
```

`_frame_index` 因此成了堆上帧的身份证。`ChunkFrames` 只有 `CompiledOnly` / `Mixed` 两值
（`runtime/stackChunkFrameStream.hpp:41`）。oop map 的位置换算也有堆上分支：
`reg_map->in_cont()` 时改用 `relativize_usp_offset`（`runtime/frame.inline.hpp:106-112`、
`oops/stackChunkOop.inline.hpp:316`）。栈另一侧的出入口是 `Continuation::top_frame()`
（`runtime/continuation.cpp:270-276`）与 `continuation_bottom_sender()`（同文件 `:380`）。
完整机制见 [Loom](/docs/CS/Java/JDK/Loom.md)。

## Method Entries That Build No Frame

先纠正两个词。**「mono 方法」在 JDK 27 的 HotSpot 里不存在**：全树 grep `mono`（排除
monotonic / monomorphic / `mono_c` 之类局部变量）没有任何帧相关含义；旧资料里的 mono / C++ 解释器
只剩 Zero 移植那一份（`interpreter/zero/bytecodeInterpreter.cpp`，仅 zero 平台使用），见
[interpreter](/docs/CS/Java/JDK/JVM/interpreter.md?id=cppinterpreter)。其次，模板解释器里
`empty` / `getter` / `setter` 这三类 `MethodKind` **不会省掉帧**：`generate_method_entry` 对它们
是 `break`，最终复用 `zerolocals` 的正常入口（`interpreter/templateInterpreterGenerator.cpp:406-442`）。

真正不建帧的三类：

1. **数学 intrinsic 入口** `generate_math_entry`：直接在调用方的表达式栈上取参数，
   x86-64 的栈注释是 `stack: [ ret adr ] <-- rsp`，收尾三行 `__ pop(rax); __ mov(rsp, r13);
   __ jmp(rax);`（`cpu/x86/templateInterpreterGenerator_x86_64.cpp:375-497`）；aarch64 版把返回地址
   留在 `lr`，用 `__ mov(sp, r19_sender_sp)` 恢复调用方 sp
   （`cpu/aarch64/templateInterpreterGenerator_aarch64.cpp:142-177`）。为什么可以省掉安全点检查，
   两份实现同一处注释回答了：「These don't need a safepoint check because they aren't virtually
   callable」。另外 `UseFMA` 关闭时 `fmaD` / `fmaF` 会 `return nullptr` 退回普通入口（同文件 `:399-402`）。
2. **abstract 方法入口** `generate_abstract_entry()`：只做 `empty_expression_stack()` +
   `restore_bcp()` + `restore_locals()` + `call_VM` 抛 `AbstractMethodError`，
   **不调用 `generate_fixed_frame()`**——后者才是布置解释器帧那一步
   （`cpu/x86/templateInterpreterGenerator_x86.cpp:1184-1201`、声明
   `interpreter/templateInterpreterGenerator.hpp:113`）。
3. **Zero 平台的快速入口**：`empty` / `getter` / `setter` 由 `UseFastEmptyMethods` /
   `UseFastAccessorMethods`（**仅 Zero 有的 flag**，`cpu/zero/globals_zero.hpp:83-88`，默认 true）
   走 `empty_entry` / `getter_entry` / `setter_entry` 直接返回
   （`interpreter/zero/zeroInterpreterGenerator.cpp:153-178`）。JVMTI 一需要方法进出事件，
   VM 就把两个 flag 关掉（`prims/jvmtiManageCapabilities.cpp:338-339`）——**无帧就没有局部变量，
   也就无法回调**。

共同点：不产生可回溯的 Java 帧，所以不出现在栈轨迹里，也没有 oop 需要被扫；
代价是不能 safepoint、不能读局部变量、不能被反优化。

## Compact Object Headers and Frame Slots

结论：**JEP 534 不改变栈槽宽度**。逐条给证据。

- 一个 JVM 槽恒为一个机器字（`interpreter/abstractInterpreter.hpp:237-239`），
  槽里放的是 **oop handle**：`oop_addr_in_slot()` 直接把槽地址当 `oop*`（同文件 `:270-272`），
  没有 compressed 形式。
- 旧书用来算「表达式栈占多少字」的 `frame::wordsize_ex()` 在 JDK 27 **已不存在**（全树 grep 零命中）。
  今天的等价物是 `interpreter_frame_expression_stack_size()`（`runtime/frame.cpp:508-522`）与
  `compiled_frame_stack_argsize()`（`cpu/x86/frame_x86.inline.hpp:272-276`）。
- 第二种「slot」是编译器接口的 `VMReg` 半字槽：`VMRegImpl::stack_slot_size = 4`、
  `slots_per_word = wordSize / 4`（`code/vmreg.cpp:34-36`，注释「VMRegs are 4 bytes wide on all
  platforms」）。混用两个概念就会得出「槽是 4 字节」的错误结论。
- `heapOopSize` 只描述**对象内部字段与数组元素**的引用宽度（压缩 oops 时为 4，
  `utilities/globalDefinitions.cpp:186,192`），不参与帧布局。
- `runtime/frame.{hpp,cpp,inline.hpp}` 与 `cpu/x86/frame_x86.*`、`cpu/aarch64/frame_aarch64.*`
  对 `UseCompactObjectHeaders` / `header_size` 的引用数是 **0**。

JEP 534（`runtime/globals.hpp:131` 默认 true；32 位下是常量 false，同文件 `:150`）对帧的**唯一**
实际影响是锁槽的内容。紧凑头要求 `UseObjectMonitorTable`（默认 true，`runtime/globals.hpp:1947`）
不能被关：`+UseCompactObjectHeaders` 与 `-UseObjectMonitorTable` 不兼容，后者被忽略并 warning
（`runtime/arguments.cpp:3462-3465`）。于是 `BasicLock` 里那个 displaced mark word 字段没了
（`runtime/basicLock.hpp:34-39`）：

```cpp
class BasicLock {
 private:
  // Used as a cache of the ObjectMonitor* used when locking. Must either
  // be nullptr or the ObjectMonitor* used when locking.
  ObjectMonitor* volatile _monitor;
```

嵌进解释器帧的是 `BasicObjectLock { BasicLock _lock; oop _obj; }`（同文件 `:70-74`），
`frame::interpreter_frame_monitor_size()` 就是它的字长数
（`cpu/x86/frame_x86.inline.hpp:348-350`）。

⚠️ 注释比代码旧：`runtime/basicLock.cpp:41-56` 的 `move_to()` 仍在讲
「the displaced_header() contains the header」「a BasicLock (which contains a displaced word)」，
而该字段已不存在；`runtime/objectMonitor.cpp:875` 的 "displaced mark word (dmw)" 是 inflate/deflate
路径上的另一件事。以 `basicLock.hpp` 的字段为准。锁机制本身见
[synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)。

## vframe Family

`runtime/vframe.hpp:39-51` 原文（本页保留并订正的那段）：

```cpp
// vframes are virtual stack frames representing source level activations.
// A single frame may hold several source level activations in the case of
// optimized code. The debugging stored with the optimized code enables
// us to unfold a frame as a stack of vframes.
// A cVFrame represents an activation of a non-java method.

// The vframe inheritance hierarchy:
// - vframe
//   - javaVFrame
//     - interpretedVFrame
//     - compiledVFrame     ; (used for both compiled Java methods and native stubs)
//   - externalVFrame
//     - entryVFrame        ; special frame created when calling Java from C

// - BasicLock
```

订正三点：① `compiledVFrame` **不在** `runtime/vframe.hpp`，它定义在 `runtime/vframe_hp.hpp:29`
（实现 `runtime/vframe_hp.cpp`，文件名的 HP 是历史残留）；② 末行 `// - BasicLock` 是头文件里的
**遗留注释**，`BasicLock` 既不是 vframe 子类也不继承 vframe（见 `runtime/basicLock.hpp:34`），
旧笔记把它抄进继承树属误读；③ `cVFrame` 这个名字同样只活在注释里，代码对应
`externalVFrame` / `entryVFrame`（`runtime/vframe.hpp:191,204`）。

`vframe` 是 `ResourceObj`（`:58`），三个字段就是一份完整回溯上下文（`:60-63`）：内嵌的物理帧
`frame _fr`（值语义在此体现）、`RegisterMap _reg_map`、`JavaThread* _thread`，JDK 27 又加了
`stackChunkHandle _chunk` 以支持堆上帧。工厂 `vframe::new_vframe()`（`runtime/vframe.cpp:63-92`）：
解释器帧 → `interpretedVFrame`；nmethod → `compiledVFrame`；**runtime 帧就地跳过**（`:77-82`）；
entry → `entryVFrame`；其余 → `externalVFrame`。

| frame 侧 | vframe 侧 | 差异 |
| :-- | :-- | :-- |
| `is_interpreted_frame()` 非虚、看 pc | `interpretedVFrame::is_interpreted_frame()` 覆写返回 true | 一个判物理地址，一个判源码级激活 |
| `sender(RegisterMap*)` 需要外部 map | `sender()` 无参，内部复用 `_reg_map` | vframe 自带 map 副本 |
| 一个物理帧 | 同一物理帧内可展开成多个 vframe | 见下节 |

`javaVFrame` 抽象出「有 method / bci / locals / expressions / monitors 的激活」
（`runtime/vframe.hpp:109-153`）；`MonitorInfo`（`:224-246`）额外记 `eliminated` 与
`owner_is_scalar_replaced`——被标量替换的对象只能退化成 klass 来报告。

### One Frame Unfolds Into Many vframes

关键机制是 `compiledVFrame::sender()`：只要当前 `ScopeDesc` 不是顶层，就**留在同一个物理帧**里，
换一层 scope、`vframe_id` 加一（`runtime/vframe_hp.cpp:392-403`）：

```cpp
vframe* compiledVFrame::sender() const {
  const frame f = fr();
  if (scope() == nullptr) {
    // native nmethods have no scope the method/bci is implied
    nmethod* nm = code();
    assert(nm->is_native_method(), "must be native");
    return vframe::sender();
  } else {
    return scope()->is_top()
      ? vframe::sender()
      : new compiledVFrame(&f, register_map(), thread(), scope()->sender(), vframe_id() + 1);
  }
}
```

`compiledVFrame::is_top()`（同文件 `:325-329`）就是「本 vframe 是否还在同一个物理帧里」的定义；
两个私有字段是 `ScopeDesc* _scope` 与 `int _vframe_id`（`runtime/vframe_hp.hpp:92-93`）。
展开成几个由 debug info 决定，不是运行时猜测：`num_java_frames(nmethod*, pc)` 就是沿
`nm->scope_desc_at(pc)` 的 `sender()` 链计数（`oops/stackChunkOop.cpp:125-131`），
解释器帧则恒为 1（同文件 `:133-137`）。

```text
一个 nmethod 物理帧（inlining 后）           vframe 链
┌────────────────────────────┐  ┌──────────────────────────────────┐
│ A 的方法体 + 内联的 B、C    │→ │ compiledVFrame C  id=0  is_top   │
│ ScopeDesc:  C -> B -> A    │  │ compiledVFrame B  id=1           │  同一个 _fr
│ OopMap / DebugInfo 决定    │  │ compiledVFrame A  id=2           │
└────────────────────────────┘  │ vframe::sender() 才换物理帧      │
                                └──────────────────────────────────┘
```

C1 与 C2 都写这份 debug info，只差详细程度。`vframeStreamCommon` / `vframeStream`
（`runtime/vframe.hpp:248-326`）是「按源码帧遍历」的上层封装，缓存
`_decode_offset` / `_sender_decode_offset` / `_vframe_id` 三件套并保留
`interpreted_mode` / `compiled_mode` / `at_end_mode`——比逐个 new vframe 更省的老办法，
至今仍是安全栈遍历的实现。

## vframeArray

`vframeArray` **不是** vframe 子类，而是反优化期间把一串 `compiledVFrame` 暂存到栈外的数组
（`runtime/vframeArray.hpp:36-39`，原文）：

```cpp
// A vframeArray is an array used for momentarily storing off stack Java method activations
// during deoptimization. Essentially it is an array of vframes where each vframe
// data is stored off stack. This structure will never exist across a safepoint so
// there is no need to gc any oops that are stored in the structure.
```

- 它是 `CHeapObj<mtCompiler>`（同文件 `:123`）而非 ResourceObj：反优化后线程自己会改栈，
  它必须活得比 resource 区域久（`runtime/deoptimization.cpp:1404-1406` 注释）。
- 布局是「固定头 + `_frames` 个 `vframeArrayElement`」（同文件 `:129-156`）：固定头含
  `_owner_thread`、`_original` / `_caller` / `_sender` 三个 `frame`、`UnrollBlock*`、
  `_callee_registers[RegisterMap::reg_count]`。
- 每个元素是一份「将来的解释器帧」：`frame _frame`、`_bci`、`_reexecute`、`_method`、
  `MonitorChunk*`、locals 与 expressions 两个 `StackValueCollection*`（同文件 `:56-62`）；
  `on_stack_size()`（`:94-97`）算它将来占多少字，`unpack_on_stack()`（`:100-106`）负责写回。
- 生产者：`Deoptimization::fetch_unroll_info_helper()`（`runtime/deoptimization.cpp:470`）→
  `create_vframeArray()`（同文件 `:565`，实现 `:1392-1420`）→
  `current->set_vframe_array_head(array)`（`:575`）；Debug 下还有
  `array->structural_compare(thread, chunk)` 兜底（`:1410`）。
- 消费者：`vframeArray::unpack_to_stack()`（`runtime/vframeArray.cpp:608`）。

| 维度 | vframe | vframeArray |
| :-- | :-- | :-- |
| 存在时机 | 遍历栈时按需构造 | 仅反优化窗口内 |
| 分配位置 | 线程 resource area | C 堆 `mtCompiler` |
| 是否需 GC 扫描 | 是（持 frame 与 RegisterMap） | 否，注释明说 never exist across a safepoint |
| 语义 | 源码级激活的视图 | 待回放的解释器帧蓝图 |

反优化全流程见 [Deoptimization](/docs/CS/Java/JDK/JVM/Deoptimization.md)。

## Links

- [Runtime Data Area](/docs/CS/Java/JDK/JVM/Runtime_Data_Area.md)
- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Method](/docs/CS/Java/JDK/JVM/Method.md)
- [Oop-Klass](/docs/CS/Java/JDK/JVM/Oop-Klass.md)
- [c1](/docs/CS/Java/JDK/JVM/c1.md)
- [Virtual Thread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)

## References

- [JEP 534: Compact Object Headers by Default](https://openjdk.org/jeps/534)
- [JEP 450: Compact Object Headers (Experimental)](https://openjdk.org/jeps/450)
- [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
- [JEP 454: Foreign Function & Memory API](https://openjdk.org/jeps/454)
- [The Java® Virtual Machine Specification: Frames](https://docs.oracle.com/javase/specs/jvms/se25/html/jvms-2.html#jvms-2.6)
