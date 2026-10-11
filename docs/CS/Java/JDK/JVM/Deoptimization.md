## Introduction

HotSpot 的 JIT 是**乐观编译**：C1/C2 基于 profile 做类型推测（type speculation）、去虚化（devirtualization）、空检查消除（null-check elision）、数组边界检查消除等优化——这些优化都建立在"当前观测到的类型 / 分支 / 常量在可预见的将来仍然成立"的推测之上。推测一旦破产（例如 bimorphic 内联的接收者出现了第三个类型、被判定"永不为 null"的引用真的为 null、循环次数推测失败），编译好的机器码就不再继续正确。

**反优化（deoptimization）就是乐观编译的安全网**：把一个已经编译、正在执行的帧（甚至整段内联帧链）"退回"成解释器帧，把编译器没有维护的完整 Java 语义状态（局部变量表、操作数栈、锁、bci）重建回真实栈上，从推测破产的那个字节码处继续用模板解释器执行。之后解释器重新收集 profile，必要时按分层编译策略重新入队编译（编译侧机制见 [JIT](/docs/CS/Java/JDK/JVM/JIT.md)，恢复执行的一侧见 [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)）。

反优化本身不便宜：一次 unwind 要付出堆上构建 `vframeArray`、整栈重写帧、锁重撤销的代价；但它保护的是**正确性**，换来的是编译器敢做更激进的推测。代价的边界由"同一 bci 反复失败"控制——trap 历史让下一次编译收敛到保守形态，而不是一路 deopt 到关编译（`Action_make_not_compilable`）。

本文以 JDK 27 的 HotSpot 源码为准，主干文件是 `share/runtime/deoptimization.hpp` 与 `share/runtime/deoptimization.cpp`（下文所有 `file:line` 均相对 `src/hotspot/`）。

## Version Baseline

> [!NOTE]
> **版本口径**：本篇主题最容易写错的三处版本变化——
> ① JDK 22 的 JEP 483 把类加载与反优化的协调从全局 safepoint 改成了**协作式协议**，JDK 27 树中 `nmethod` 上还留有直接证据：`uint64_t _deoptimization_generation`，注释写明"Used to track in which deoptimize handshake this method will be deoptimized"（`code/nmethod.hpp:168-169`）。
> ② 旧文档里的函数名 `SharedRuntime::install_deopt_blob` 与类名 `vframeArray::ElementFrame` 在 JDK 27 树中**都已不存在**：前者改名 `SharedRuntime::generate_deopt_blob`（`runtime/sharedRuntime.cpp:179` 声明于 `runtime/sharedRuntime.hpp:377`），后者改名 `vframeArrayElement`（`runtime/vframeArray.hpp:51`）。
> ③ `CodeDebugInfo` 这个类在 JDK 27 的 `share/` 全树 grep **零命中**（已被移除，移除版本未在本树核实），nmethod 头注释现在直接说调试信息是 "Scopes data array / Scopes pcs array"（`code/nmethod.hpp:154-156`）。
> 另：统一日志 tag `deoptimization` 在 JDK 27 **已定义但 share 树内没有任何调用点**，`-Xlog:deoptimization` 当前无输出（见观测一节）。
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## DeoptReason

每次反优化都带一个**原因**（`DeoptReason`）和一个**后续动作**（`DeoptAction`），两者一起被打包进编译器在陷阱点传递给 runtime 的 `trap_request` 整数里。枚举定义在 `runtime/deoptimization.hpp:76-122`，摘录核心部分（原注释保留）：

```cpp
enum DeoptReason {
  Reason_many = -1,             // indicates presence of several reasons
  Reason_none = 0,              // indicates absence of a relevant deopt.

  Reason_null_check,            // saw unexpected null or zero divisor (@bci)
  Reason_null_assert,           // saw unexpected non-null or non-zero (@bci)
  Reason_range_check,           // saw unexpected array index (@bci)
  Reason_class_check,           // saw unexpected object class (@bci)
  Reason_array_check,           // saw unexpected array class (aastore @bci)
  Reason_intrinsic,             // saw unexpected operand to intrinsic (@bci)
  Reason_bimorphic,             // saw unexpected object class in bimorphic inlining (@bci)

  Reason_profile_predicate,     // compiler generated predicate moved from frequent branch in a loop failed
  Reason_auto_vectorization_check, // compiler generated (speculative) auto vectorization checks failed

  Reason_unloaded,              // unloaded class or constant pool entry
  Reason_uninitialized,         // bad class state (uninitialized)
  Reason_initialized,           // class has been fully initialized
  Reason_unreached,             // code is not reached, compiler
  Reason_unhandled,             // arbitrary compiler limitation
  Reason_constraint,            // arbitrary runtime constraint violated
  Reason_div0_check,            // a null_check due to division by zero
  Reason_age,                   // nmethod too old; tier threshold reached
  Reason_predicate,             // compiler generated predicate failed
  Reason_loop_limit_check,      // compiler generated loop limits check failed
  Reason_speculate_class_check, // saw unexpected object class from type speculation
  Reason_speculate_null_check,  // saw unexpected null from type speculation
  Reason_speculate_null_assert, // saw unexpected null from type speculation
  Reason_unstable_if,           // a branch predicted always false was taken
  Reason_unstable_fused_if,     // fused two ifs that had each one untaken branch. One is now taken.
  Reason_receiver_constraint,   // receiver subtype check failed
  Reason_not_compiled_exception_handler, // missing compiled exception handler
  Reason_short_running_long_loop,    // profile reports loop runs for small number of iterations

  Reason_TRAP_HISTORY_LENGTH,
  Reason_tenured = Reason_TRAP_HISTORY_LENGTH, // age of the code has reached the limit
  Reason_LIMIT,

  Reason_RECORDED_LIMIT = Reason_profile_predicate,  // some are not recorded per bc
};
```

全部取值、含义与**在本树 grep 到的抛出点**整理成表。"抛出点"只列本次直接检索到的调用处（C2 侧集中在 `opto/graphKit.cpp`、`opto/library_call.cpp`、`opto/parse1.cpp` 的 `uncommon_trap()`，C1 侧是 `c1/c1_LIR.cpp`、`c1/c1_LIRGenerator.cpp` 构造的 `DeoptimizeStub`）；标"—"的行只有枚举注释这一条证据，本树未逐一检索抛出点。

| DeoptReason | 含义 | 抛出点（file:line，本树证据） | 典型后续动作 |
| :-- | :-- | :-- | :-- |
| `Reason_many` | 多个原因并存（哨兵） | `deoptimization.hpp:77` | — |
| `Reason_none` | 无相关反优化 | trap 历史计数下标（`c1/c1_Runtime1.cpp:1475`） | — |
| `Reason_null_check` | 意外的 null 或零除数 | C1 `c1/c1_LIR.cpp:1459`；C2 推测辅助函数 `opto/graphKit.cpp:3197` | 重解释，profile 复位后重编 |
| `Reason_null_assert` | 意外出现非 null / 非 0 | — | 同上 |
| `Reason_range_check` | 意外的数组下标 | C1 `c1/c1_LIRGenerator.cpp:1851-1865`；C2 `opto/library_call.cpp:1208` | 边界推测作废 |
| `Reason_class_check` | 意外的对象类型 | C2 `opto/library_call.cpp:4653-4659` | 去虚化/类型推测作废 |
| `Reason_array_check` | aastore 时意外的数组类型 | — | 同上 |
| `Reason_intrinsic` | 内部方法的意外操作数 | C2 `opto/library_call.cpp:1177` 等大量调用点 | 该 bci 记入 trap 历史 |
| `Reason_bimorphic` | 双态内联出现第三个接收者类型 | —（枚举注释自明） | IC 复位、重新 profile |
| `Reason_profile_predicate` | 从热分支提升出的谓词失败 | — | 谓词回退 |
| `Reason_auto_vectorization_check` | 自动向量化的推测检查失败 | — | 放弃向量化路径 |
| `Reason_unloaded` | 类 / 常量池项未加载 | C2 `opto/graphKit.cpp:1358` | 加载类后重执（`load_class_by_index`，`runtime/deoptimization.cpp:1595`） |
| `Reason_uninitialized` | 类尚未初始化 | C2 `opto/graphKit.cpp:3111,3126` | 初始化后重编 |
| `Reason_initialized` | 类已完全初始化 | C2 `opto/graphKit.cpp:3092` | 重解释 |
| `Reason_unreached` | 编译器认定不可达的代码被执行 | C2 `opto/parse1.cpp:1586` | 重解释 |
| `Reason_unhandled` | 任意编译器限制 | C2 `opto/graphKit.cpp:2722` | 重解释 |
| `Reason_constraint` | 任意运行时约束被违反 | C2 `opto/parse1.cpp:411`；`deoptimize()` 的默认参数（`runtime/deoptimization.hpp:160`） | 视调用方而定 |
| `Reason_div0_check` | 由除零触发的 null_check | C2 `opto/graphKit.cpp:1435` | 按 null_check 记账 |
| `Reason_age` | nmethod 太老 / 到达 tier 阈值 | — | 换代重编 |
| `Reason_predicate` | 编译器生成谓词失败 | — | 谓词回退 |
| `Reason_loop_limit_check` | 循环次数推测失败 | — | 去掉循环限制推测重编 |
| `Reason_speculate_class_check` | 类型推测的类检查失败 | `opto/graphKit.cpp:3196` | 记录时折叠为 `class_check` |
| `Reason_speculate_null_check` | 类型推测的 null 检查失败 | `opto/graphKit.cpp:3197` | 记录时折叠为 `null_check` |
| `Reason_speculate_null_assert` | 类型推测的 null_assert 失败 | —（与上两个同族） | 记录时折叠为 `null_assert` |
| `Reason_unstable_if` | 被预测"永假"的分支被走到 | — | 记录时折叠为 `intrinsic`（`runtime/deoptimization.hpp:378-381`，以源码为准） |
| `Reason_unstable_fused_if` | 融合的两条"永假"分支有一条被走到 | — | 记录时折叠为 `range_check`（同上） |
| `Reason_receiver_constraint` | 接收者子类型检查失败 | —（`deoptimization.cpp:1809` 对其单独开日志） | 去虚化作废 |
| `Reason_not_compiled_exception_handler` | 缺少编译版异常 handler | runtime 自身：`runtime/deoptimization.cpp:1530` | 整帧交给 deopt blob |
| `Reason_short_running_long_loop` | profile 显示循环迭代次数很少 | — | 去掉展开重编 |
| `Reason_tenured` | 代码年龄到达上限（**不计入 trap 历史**，单独计数） | C1 runtime `c1/c1_Runtime1.cpp:810` | 不再重编该层 |

两个与统计口径相关的细节（均以源码为准）：

- `Reason` 与 `Action` 各占 trap_request 整数的 5 bit / 3 bit（`runtime/deoptimization.hpp:136-142` 的 `_reason_bits` / `_action_bits`），由 `make_trap_request()`（同文件 :333）打包。
- 只有 `Reason_none` 到 `Reason_RECORDED_LIMIT`（= `Reason_profile_predicate`，:122）之间的原因**按字节码记入 `MethodData::_trap_hist`**；超出者只进全局直方图 `_deoptimization_hist[Reason_LIMIT][1+Action_LIMIT][BC_CASE_LIMIT]`（:447）。
- `reason_recorded_per_bytecode_if_any()`（:367-383）定义了若干原因在记账时折叠为更早、更"基础"的原因，映射如下（严格按源码）：

| 实际原因 | 按 bci 记账为 | 源码行 |
| :-- | :-- | :-- |
| `Reason_div0_check` | `Reason_null_check` | :370-371 |
| `Reason_speculate_class_check` | `Reason_class_check` | :372-373 |
| `Reason_speculate_null_check` | `Reason_null_check` | :374-375 |
| `Reason_speculate_null_assert` | `Reason_null_assert` | :376-377 |
| `Reason_unstable_if` | `Reason_intrinsic` | :378-379 |
| `Reason_unstable_fused_if` | `Reason_range_check` | :380-381 |
| 其余未单列者 | 自身（≤ RECORDED_LIMIT 时）否则 `Reason_none` | :364-384 |

下一次编译通过 `too_many_traps()` 消费这份历史（C2 例：`opto/library_call.cpp:1167`）——**这就是反优化反馈回编译器的通道**，profile 与分层策略的完整机制见 [JIT](/docs/CS/Java/JDK/JVM/JIT.md)。

## DeoptAction and Unpack Modes

`DeoptAction`（`runtime/deoptimization.hpp:127-134`）决定反优化之后这段代码的命运，原注释即语义：

```cpp
enum DeoptAction {
  Action_none,                  // just interpret, do not invalidate nmethod
  Action_maybe_recompile,       // recompile the nmethod; need not invalidate
  Action_reinterpret,           // invalidate the nmethod, reset IC, maybe recompile
  Action_make_not_entrant,      // invalidate the nmethod, recompile (probably)
  Action_make_not_compilable,   // invalidate the nmethod and do not compile
  Action_LIMIT
};
```

| DeoptAction | 源码注释含义 | 效果 |
| :-- | :-- | :-- |
| `Action_none` | just interpret, do not invalidate nmethod | 只退回解释帧，nmethod 保持有效 |
| `Action_maybe_recompile` | recompile the nmethod; need not invalidate | 可能重编，nmethod 不作废 |
| `Action_reinterpret` | invalidate the nmethod, reset IC, maybe recompile | 作废 + IC 复位 |
| `Action_make_not_entrant` | invalidate the nmethod, recompile (probably) | 作废并（大概率）重编 |
| `Action_make_not_compilable` | invalidate the nmethod and do not compile | 作废且不再编译 |

`UnpackType`（:144-149，即 `UnrollBlock::_unpack_kind`，:207）则告诉 blob 这次解包属于哪一类：

| UnpackType | 值 | 含义 |
| :-- | :-- | :-- |
| `Unpack_deopt` | 0 | 正常反优化，pc 由 `unpack_vframe_on_stack` 计算（注释原文） |
| `Unpack_exception` | 1 | 有挂起异常待派发 |
| `Unpack_uncommon_trap` | 2 | 重执最后一条字节码（C2 only） |
| `Unpack_reexecute` | 3 | 重执字节码（C1 only） |
| `Unpack_none` | 4 | 并不反优化帧，只为 JVMTI 重分配对象 / 重锁 monitor |

## Entry Points of Deoptimization

按触发方式分四类，全部是 `Deoptimization` 的静态入口（定义位置：`runtime/deoptimization.cpp`）：

**1. 编译代码自带陷阱（最常见）。** C2 在推测点生成一条到 `uncommon_trap` 桩的路径，运行时进入 `Deoptimization::uncommon_trap(thread, trap_request, exec_mode)`（cpp:2242，声明 `deoptimization.hpp:285`）；需要加载类时走 `uncommon_trap_inner`（cpp:1713，`JRT_ENTRY`，会在 safepoint 上加载 `Reason_unloaded` 对应的类，见 `load_class_by_index` cpp:1595）。C1 的等价物是 `DeoptimizeStub`（`c1/c1_LIR.cpp:1459` 构造），异常路径经 `c1/c1_Runtime1.cpp:614,690` 选 blob 的 TLS 入口。

**2. 编译帧缺异常 handler。** `Deoptimization::deoptimize_for_missing_exception_handler()`（cpp:1511）：以 `Reason_not_compiled_exception_handler` 调 `deoptimize()`（cpp:1530），并把 blob 的 `unpack_with_exception_in_tls()`（cpp:1532）作为新 handler 返回；C2 侧 handler 选择在同名逻辑中返回 `unpack_with_exception()`（`opto/runtime.cpp:1966,2042`；`runtime/sharedRuntime.cpp:604` 也是此家族入口，且注释说明栈越界防护要在 blob 里补回）。

**3. 针对单个帧的定向反优化。** `deoptimize()`（cpp:1500，默认原因 `Reason_constraint`）与 `deoptimize_single_frame()`（cpp:1471）；调试器 / JVMTI 按栈 id 走 `deoptimize_frame()`（cpp:1553/1563，内部 `deoptimize_frame_internal` cpp:1535）。

**4. 全局批量反优化。** 类重定义、JVMCI 编译失效等场景先把受影响的 nmethod 打标记，再在安全点批量执行：`deoptimize_all_marked()`（cpp:1030）。JEP 483 之后类加载与反优化的协调走带 `_deoptimization_generation` 的握手协议（`code/nmethod.hpp:168-169`），roll-forward 与 safepoint 本身的机制见 [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)。运行期依赖该机制的公开例子还包括 JVMTI redefine 与 JEP 410 Stable Values 的二次写失效（见 References）。

## Deoptimization Blob

反优化的现场切换不是 C++ 函数调用，而是一段预生成的机器码 stub——**deopt blob**，类 `DeoptimizationBlob : public SingletonBlob`（`code/codeBlob.hpp:578`），4 个入口点（`ENTRY_COUNT = 4`，:600）：

```cpp
address unpack() const                    { return code_begin() + _unpack_offset;           }
address unpack_with_exception() const     { return code_begin() + _unpack_with_exception;   }
address unpack_with_reexecution() const   { return code_begin() + _unpack_with_reexecution; }

// Alternate entry point for C1 where the exception and issuing pc
// are in JavaThread::_exception_oop and JavaThread::_exception_pc
// instead of being in registers.  This is needed because C1 doesn't
// model exception paths in a way that keeps these registers free so
// there may be live values in those registers during deopt.
address unpack_with_exception_in_tls() const { ... }
```

（第 4 个入口专为 C1 保留区注释原样摘录于 :615-619。）

**生成时机**：VM 启动期生成运行时 stub 时，与 safepoint 轮询 handler 同批调用 `generate_deopt_blob()`（`runtime/sharedRuntime.cpp:179`），声明为 `static void generate_deopt_blob(void)`（`runtime/sharedRuntime.hpp:377`）。**⚠️ 旧文档中的名字 `install_deopt_blob` 在 x86 / aarch64 目录中 grep 均为零命中**，现役实现按架构分别提供：

| 架构 | 实现文件 | 行号 |
| :-- | :-- | :-- |
| x86-64 | `cpu/x86/sharedRuntime_x86_64.cpp` | 2469 |
| AArch64 | `cpu/aarch64/sharedRuntime_aarch64.cpp` | 2054 |
| PPC / ARM / RISC-V / s390 / Zero | 各 `cpu/*/sharedRuntime_*.cpp` | ppc:2832 / arm:1325 / riscv:1976 / s390:2521 / zero:98 |

**blob 的工作序列**（汇编不逐条读，按两侧 C++ 接口的对账单概述）：编译代码陷阱后跳进 blob，blob 调 `Deoptimization::fetch_unroll_info()`（`JRT_BLOCK_ENTRY`，cpp:283——放在 safepoint 边界的 block 层，允许在此停顿），后者返回一个 `UnrollBlock`。头文件注释点明了这对契约："UnrollBlock is returned by fetch_unroll_info() to the deoptimization handler (blob)"（`runtime/deoptimization.hpp:191`）。blob 据 `UnrollBlock` 里记录的各帧尺寸与寄存器保存区，把编译帧整体替换成一串骨架解释帧，再调 `Deoptimization::unpack_frames()`（`JRT_LEAF`，cpp:852）把真实内容灌进去，最后跳回模板解释器循环继续执行（衔接 [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)）。

异常派发选中 blob 入口时还有一条栈防护细节：返回地址已落在 deopt pc 上时，栈溢出状态要先补回 guard page，因为 blob 里的 stack bang 可能再次踩爆栈（`runtime/sharedRuntime.cpp:591-604`，注释原文 "Reguard the stack otherwise if we return to the deopt blob and the stack bang causes a stack overflow we crash"）。

CDS / AOT 场景下 blob 入口偏移也要随镜像重定位：`share/code/aotCodeCache.cpp:1573-1574` 直接按 `DeoptimizationBlob::unpack()` 的偏移核对 AOT 桩（启动加速整体见 [Startup_Acceleration](/docs/CS/Java/JDK/JVM/Startup_Acceleration.md)）。blob 本身常驻 CodeCache，机制背景见 [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)。

## vframeArray Reconstruction

编译帧里**没有**解释器帧必须的东西：完整局部变量表、操作数栈、当前 bci、按 JVMS 语义持锁的 monitor。HotSpot 的做法是先在堆上重建一份"虚拟的解释帧数组"，再整批灌回栈——这就是 `vframeArray`（`runtime/vframeArray.hpp`，文件头注释："A vframeArray is an array used for momentarily storing off stack Java method activations during deoptimization"，并说明该结构**从不跨越 safepoint 存在**，其中 oop 无需 GC）。

**编译帧状态从哪来**：`fetch_unroll_info_helper()`（cpp:470）沿 nmethod 的调试信息把编译帧展开成一串 `compiledVFrame`。元数据由 nmethod 携带：`code/nmethod.hpp:154-156` 的注释列出 "Debugging information: Scopes data array / Scopes pcs array"；pc 到 scope 的映射按 `PcDesc` 查询（`code/nmethod.hpp:111-133` 的 `PcDescContainer`），scope 内的值位置由 `ScopeDesc`（`runtime/scopeDesc.hpp`）与 `DebugInfo`（`code/debugInfo.hpp`）解析出 `ScopeValue` / `ObjectValue`。**⚠️ JDK 27 树中已无 `CodeDebugInfo` 类**（grep 零命中），旧文档以它为准的叙述要按 nmethod 现状改写。nmethod 与 CodeCache 的关系不在本篇展开，见 [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)。

**vframeArrayElement——旧名 ElementFrame**。每个元素对应"最终要造出来的一个解释帧"（`runtime/vframeArray.hpp:51-117`）：

```cpp
class vframeArrayElement {
    frame _frame;                // the interpreter frame we will unpack into
    int  _bci;                   // raw bci for this vframe
    bool _reexecute;             // whether we should reexecute this bytecode
    Method*    _method;          // the method for this vframe
    MonitorChunk* _monitors;     // active monitors for this vframe
    StackValueCollection* _locals;
    StackValueCollection* _expressions;
    ...
```

采集侧的入口是 `fill_in(compiledVFrame* vf, bool realloc_failures)`（:87）。数组本体（:123-216）的内存布局注释原样如下：

```text
      fixed part
        description of the original frame
        _frames - number of vframes in this array
        adapter info
        callee register save area
      variable part
        vframeArrayElement   [ 0 ]
        ...
        vframeArrayElement   [_frames - 1]
```

固定部分还含 `_owner_thread` / `_original` / `_caller` / `_sender` / `_unroll_block` 与 `_callee_registers[RegisterMap::reg_count]`（:144-156）。构造链：`create_vframeArray()`（cpp:1392）→ `vframeArray::allocate()`（cpp:1407，声明 hpp:167），逐元素 `fill_in`。

**锁与标量替换对象的重建**：编译代码里 monitor 可能被扁平化（锁撤销需要重新走 `monitorenter` 排队），逃逸分析被标量替换的对象可能需要重新分配回堆上。对应三组函数：`relock_objects()`（cpp:1335）、`realloc_objects()`（cpp:1048）与字段/数组回写 `reassign_fields()` / `retype_array_elements` 家族（cpp:1106,1161,1281）。`realloc` 失败的帧由 `pop_frames_failed_reallocs()`（cpp:1443）处理——JVMTI 的 `Unpack_none` 场景（只为重分配/重锁、并不真反优化）就是这条线。解包完成后 `deallocate_monitor_chunks()`（hpp:201）释放栈外 MonitorChunk。monitor 的栈上语义见 [frame](/docs/CS/Java/JDK/JVM/frame.md) 与 [synchronized](/docs/CS/Java/JDK/Concurrency/synchronized.md)。

**回到正确 bci**：`vframeArray::unpack_to_stack(stub_frame, exec_mode, caller_actual_parameters)`（hpp:197，调用点 cpp:883）自底向上对每个元素执行 `unpack_on_stack()`（hpp:100），把 locals / expressions 写进刚拼好的解释帧槽位，并把 `_bci` 恢复为该帧的挂起点；是否**重执**该字节码由 `should_reexecute(is_top_frame, exec_mode)`（hpp:74）结合上表 `Unpack_uncommon_trap` / `Unpack_reexecute` 决定——这正是 C2 "重执最后一条"与 C1 "重执"语义差异的落点。`unwind_callee_save_values()`（cpp:807）负责 callee 保存寄存器的回卷，`cleanup_deopt_info()`（cpp:763）在解包后释放堆上的 vframeArray。整个过程栈帧与 vframe 家族的形态变化以 [frame](/docs/CS/Java/JDK/JVM/frame.md) 为准，本篇不重复。

## Observability

**统一日志：tag 存在但没有生产者。** `LOG_TAG(deoptimization)` 已在 `logging/logTag.hpp:75` 注册，但在整个 `share/` 树检索 `log(deoptimization` 与其它级别调用均**零命中**——JDK 27 上 `-Xlog:deoptimization` 不会输出反优化事件。这正是"flag/tag 存在 ≠ 还生效"的现行案例。

**JFR：本树无 deopt 事件。** 在 jdk-27-ga 全 `src/` 检索 `DeoptimizationEvent` 零命中，本文不提供 JFR 观测途径。

**真正可用的 flag（globals.hpp，注意构建类型）**：

| Flag | 类型 | 默认 | 定义位置 | 用途 |
| :-- | :-- | :-- | :-- | :-- |
| `TraceDeoptimization` | product + DIAGNOSTIC | false | `runtime/globals.hpp:1231` | 向 tty 打印每次 deopt；消费点 `runtime/deoptimization.cpp:361,381,1412,1809,1861`、`runtime/vframeArray.cpp:636,661,693`、`oops/method.cpp:1098`；需 `-XX:+UnlockDiagnosticVMOptions` |
| `DeoptimizeOnAllocationException` | product + DIAGNOSTIC | false | globals.hpp:652 | 分配异常时改为 deopt 而非就地处理 |
| `DeoptimizeNMethodBarriersALot` | product + DIAGNOSTIC | false | globals.hpp:1939 | 压力测试：nmethod barrier 触发频繁 deopt |
| `TrapBasedNullChecks` | product_pd | 平台相关 | globals.hpp:941 | 陷阱式空检查（配合信号 handler 的 deopt/慢路径） |
| `DeoptimizeALot` / `DeoptimizeRandom` | **develop** | false | globals.hpp:386,392 | 仅 debug 构建：每次 / 随机在 runtime 出口 deopt |
| `DeoptimizeOnlyAt` / `DeoptimizeALotInterval` | **develop** | "" / 5 | globals.hpp:389,1306 | 上两者的节流与选址参数 |
| `DeoptimizeObjectsALot` + 3 参数 | **develop** | false | globals.hpp:401-420 | 仅 debug：针对标量替换的重分配压力 |
| `PrintDeoptimizationDetails` / `DebugDeoptimization` | **develop** | false | globals.hpp:1234,1237 | 仅 debug：详情打印 / 结构一致性自检 |
| `LoomDeoptAfterThaw` | **develop** | false | globals.hpp:1899 | 仅 debug：thaw 之后强制 deopt（Loom × deopt 的测试开关） |
| `ProfileTraps` | **develop_pd** | 平台相关 | globals.hpp:1174 | 仅 debug：trap 记录粒度参数 |

产品 JVM 里实际可操作的就是 `TraceDeoptimization`（DIAGNOSTIC）；`Deoptimize*ALot` 一族全部是 `develop`，**只在 fastdebug 构建生效**，生产 JVM 设了也无效果——很多旧博客把它们写成生产可调项，属于典型过时。

`TraceDeoptimization` 打开后打印什么，可从调用点反推：`fetch_unroll_info` 路径内两处输出点（cpp:361,381），`create_vframeArray` 完成后输出重建出的 vframeArray（cpp:1412，配合 debug 构建的 `PrintDeoptimizationDetails`），uncommon trap 处理时输出 reason/action 解码串（`format_trap_request`，cpp:2410；cpp:1809 处对 `Reason_receiver_constraint` 失败单独放宽了打印条件，cpp:1861 注释原文 "make noise on the tty"）。它与 `LogCompilation` 共用 xtty 通道输出方法级痕迹（`oops/method.cpp:1098`）。典型用法：

```bash
# DIAGNOSTIC 类 flag 需要先解锁
java -XX:+UnlockDiagnosticVMOptions -XX:+TraceDeoptimization -jar app.jar
```

**计数与统计接口**：`Deoptimization::total_deoptimization_count()`（cpp:2466）与按原因的 `deoptimization_count(reason_str, action_str)`（cpp:2474）、直方图 `print_statistics()`（cpp:2494）在 HotSpot 内的消费点只有 **WhiteBox**（`prims/whitebox.cpp:1028`），不是产品可观测面；生产上更实用的口径是用 `-XX:+TraceDeoptimization` 的输出，或按方法读 `MethodData` 的 trap history（`too_many_traps` 的编译期数据源，见 DeoptReason 一节）。

**反优化风暴的定位思路**（基于上述机制）：`TraceDeoptimization` 抓到反复出现的同一 bci 与 reason → 说明推测性优化（多为类型推测 / unstable if）与程序实际行为冲突 → 反优化后解释重攒 profile、再编译、再失败，循环烧 CPU。分层重编译策略细节归 [JIT](/docs/CS/Java/JDK/JVM/JIT.md)，C1 侧陷阱生成归 [c1](/docs/CS/Java/JDK/JVM/c1.md)。

## Links

- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [c1](/docs/CS/Java/JDK/JVM/c1.md)
- [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md)
- [frame](/docs/CS/Java/JDK/JVM/frame.md)
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)
- [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)

## References

- [JEP 483: Coordinated Class Loading and Deoptimization](https://openjdk.org/jeps/483)
- [JEP 410: Stable Values](https://openjdk.org/jeps/410)
- [Java SE 27 — Options to Control the Runtime Behavior of the JVM](https://docs.oracle.com/en/java/javase/27/vm/java-options-to-control-runtime-behavior.html)
- [JDK 27 release page](https://openjdk.org/projects/jdk/27/)
