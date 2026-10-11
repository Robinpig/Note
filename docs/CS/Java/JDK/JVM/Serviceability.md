## Introduction

「Serviceability」一词在 HotSpot 里有两层完全不同的含义，写作和检索时极易混淆。

**历史含义**是 Serviceability Agent，即 `jdk.hotspot.agent` 模块与 `hsdb` 工具。它靠读取 `VMStructs`
导出的调试元信息，在**外部进程**里重建 JVM 的对象图，从而对 core dump 或活进程做交互式检视。这条路
本质是「带外调试器」，代价是要维护一套与内核数据结构强耦合的镜像类型系统，属于深水区。

**今天的实际含义**是「JVM 自己把内部状态吐出来的能力」，也就是本文的三块底座：

| 底座 | 载体 | 回答的问题 | 侵入性 |
| :-- | :-- | :-- | :-- |
| 统一日志 | `-Xlog` / `VM.log` | 过去发生过什么 | 低，可在生产常开 |
| NMT | `-XX:NativeMemoryTracking` / `VM.native_memory` | 堆外的 native 内存去哪了 | 中，有分配路径开销 |
| 诊断命令 + attach | `jcmd` / `AttachListener` | 现在这一刻是什么状态 | 取决于具体命令 |

三者互相支撑的方式很直白：线上进程不能挂调试器，也不能重启加参数，于是**先靠 attach 把命令送进去**，
**dcmd 提供瞬时快照**（线程栈、堆信息、metaspace 明细、标志位），**统一日志提供时间轴**（GC、安全点、
反优化、类加载的因果序列），**NMT 补上 JVM 堆之外那块常规工具完全看不见的账**。一个典型的内存增长
排查就是三者串起来的：`VM.native_memory baseline` 定基线 → `-Xlog:gc*,safepoint` 观察增长节奏 →
`summary.diff` 定位到具体 tag 与调用点 → `System.map` 核对进程级映射。

本文只覆盖 HotSpot 侧的实现与真实命令名，工具层的用法见 [Arthas](/docs/CS/Java/Tools/Arthas.md)，
事件型剖析见 [JFR](/docs/CS/Java/Tools/JFR.md)。

## Version Baseline

> [!NOTE]
>
> JDK 27 上有三个最容易写错的点，全部与「以为已经改名」或「以为已经删掉」有关：
>
> 1. **NMT 与 metaspace 的 dcmd 名前缀仍然是 `VM.`，没有迁到 `GC.`**。`src/hotspot/share/nmt/nmtDCmd.hpp:49`
>    是 `"VM.native_memory"`，`src/hotspot/share/memory/metaspace/metaspaceDCmd.hpp:47` 是 `"VM.metaspace"`，
>    `src/hotspot/share/classfile/classLoaderHierarchyDCmd.hpp:40` 是 `"VM.classloaders"`。`GC.` 前缀只用于
>    真正的 GC 动作命令（`GC.run`、`GC.heap_info`、`GC.heap_dump`、`GC.class_histogram` 等）。
> 2. **`VM.flags` 只剩一个参数 `-all`**。历史上 `-final` / `-range` / `-experimental` / `-diagnostic`
>    四变体在 `PrintVMFlagsDCmd` 的构造里已不存在（`src/hotspot/share/services/diagnosticCommand.cpp`），
>    要看全部标志直接用 `jcmd <pid> VM.flags -all`。
> 3. **`-XX:+PrintGC` / `-XX:+PrintGCDetails` 还没报错，只是被翻译**。两个标志仍在
>    `src/hotspot/share/gc/shared/gc_globals.hpp:414,418`，命中时打 warning 并转成等价的 `-Xlog` 配置。
>    「已废弃」和「已废止」是两回事，obsolete 表里的条目才会直接拒绝启动。

详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Unified Logging

JEP 158 把此前散落在 `Trace*` 布尔标志、`gclogReader`、`jvmtiLog`、`Error` 文件里的输出统一成一套
编译期标签体系，JEP 271 再把 GC 日志并入。所有 `log_xxx(tag, ...)` 调用最终落到同一套选择器、输出器
与装饰器上，因此可以运行时改级别、可以重定向到轮换文件、可以带时间戳。

### Tag Syntax and Levels

标签集合由 `src/hotspot/share/logging/logTag.hpp:36` 的 `LOG_TAG_LIST` 单一宏定义生成，是**唯一权威清单**
（`jcmd <pid> VM.log` 或 `-Xlog` 不带参数时的帮助文本也会打印它）。条件标签由构建开关控制：
`NOT_PRODUCT(LOG_TAG(codestrings))`、`COMPILER2_PRESENT(LOG_TAG(hotcode))`、`DEBUG_ONLY(LOG_TAG(deathtest))`
——这意味着同一份命令行在不同构建上可用的标签集合不同。

常用标签与其在 `logTag.hpp` 中的位置：

| Tag | 行号 | 覆盖内容 |
| :-- | :-- | :-- |
| `gc` | 91 | GC 各阶段，可继续细分 `gc+phases`、`gc+heap`、`gc+ref` |
| `safepoint` | 180 | 安全点同步时间、参与线程、停顿统计 |
| `ergo` | 81 | 自动选型决策，如堆大小、GC 策略 |
| `arguments` | 42 | 命令行解析与标志改写 |
| `cds` | 52 | 类数据共享加载与 dump |
| `metaspace` | 129 | Metaspace 与 chunk 分配 |
| `class` / `loader` | 54 / 120 | 类加载轨迹 |
| `nmt` | 142 | NMT 自身行为，如级别降级 |
| `os` | 152 | 操作系统层调用与线程栈 |
| `jit` | 111 | JIT 编译，常配 `+compilation`、`+inlining` |
| `jfr` | 110 | JFR 内部状态，不是事件内容 |
| `codecache` | 57 | 分段 CodeCache 的占用与回收 |
| `exceptions` | 83 | 异常抛出轨迹 |
| `attach` | 45 | attach 触发与命令分发 |
| `logging` | 121 | 日志子系统自身的告警 |

级别只有五档加隐式关闭，定义在 `src/hotspot/share/logging/logLevel.hpp:46` 的 `LOG_LEVEL_LIST`：
`trace` / `debug` / `info` / `warning` / `error`。`-Xlog:gc` 不带级别时默认 `info`。

### The What Who Decorators Grammar

帮助文本 `src/hotspot/share/logging/logConfiguration.cpp:602` 给出的完整形式是：

```text
-Xlog[:[selections][:[output][:[decorators][:output-options]]]]
    selections = tag1[+tag2...][*][=level][,...]
```

三段分别叫 what（选什么）、who（发到哪）、decorators（每行前缀什么），第四段是输出选项。几个容易踩的
组合语义，同样来自帮助文本（`logConfiguration.cpp:668` 起的 examples 段）：

- `-Xlog:gc,safepoint` 是**或**关系：只带 `gc` 或只带 `safepoint` 的都记，**同时带两个 tag 的消息反而不记**。
- `-Xlog:gc+ref=debug` 是**与**关系：必须同时带 `gc` 和 `ref`。
- `*` 是前缀通配。`-Xlog:gc*=debug` 匹配 `gc`、`gc+phases`、`gc+heap` 等所有以 `gc` 开头的标签组合；
  不写 `*` 时只精确匹配列出的那一组 tag。
- `-Xlog:gc*` 单独使用等价于「所有 `gc` 前缀、级别 `info`、输出 stdout、默认装饰」。
- `all` 作为 tag 出现时匹配一切，裸 `-Xlog` 等价于 `-Xlog:all=info:stdout:uptime,levels,tags`。

组合起来的实战写法：

```bash
-Xlog:safepoint,gc*=debug:file=gc-%p-%t.log:uptime,levels,tags:filecount=5,filesize=32m
```

含义是：`safepoint` 单标签与所有 `gc` 前缀组合都记到 `debug`，写进带 PID 与启动时间戳的文件，
每行前缀「相对启动秒数 + 级别 + 标签」，文件级轮换 5 × 32 MB。

### Decorators

装饰器枚举在 `src/hotspot/share/logging/logDecorators.hpp:44` 的 `DECORATOR_LIST`，每项是「全名, 缩写」
一对，两者都能写在命令行里（`src/hotspot/share/logging/logDecorators.cpp:44` 用 `{#n, #a}` 同时导出）。

| 全名 | 缩写 | 含义 |
| :-- | :-- | :-- |
| `time` | `t` | 墙上时钟，秒精度 |
| `utctime` | `utc` | 带毫秒与时区偏移的 UTC 时间 |
| `uptime` | `u` | JVM 启动至今，秒 |
| `timemillis` | `tm` | 墙上时钟，毫秒 |
| `uptimemillis` | `um` | 启动至今，毫秒 |
| `timenanos` | `tn` | 墙上时钟，纳秒 |
| `uptimenanos` | `un` | 启动至今，纳秒 |
| `hostname` | `hn` | 主机名，多机汇总时必备 |
| `pid` | `p` | 进程号 |
| `tid` | `ti` | 线程 id |
| `level` | `l` | 日志级别 |
| `tags` | `tg` | 标签组合 |

`decorators` 段写 `none` 关闭全部装饰（`logConfiguration.cpp:620`）。另有一处**内置例外**值得知道：
`logDecorators.cpp:48` 的 `UNDECORATED_DEFAULT(AnyLevel, LOG_TAGS(jit, inlining))` 让 `jit+inlining` 的
输出在任何级别下都**默认不带装饰**——因为内联轨迹是给工具消费的，加前缀会破坏可读性。想加回装饰必须
显式写出 decorators 段。

### File Output Rotation

文件名占位符由 `src/hotspot/share/logging/logFileOutput.cpp:37-38` 定义：

```cpp
const char* const LogFileOutput::PidFilenamePlaceholder = "%p";
const char* const LogFileOutput::TimestampFilenamePlaceholder = "%t";
```

`%p` 展开为 JVM 的 PID，`%t` 展开为**启动时刻**的时间戳，另有 `%hn` 展开为主机名
（见 `logConfiguration.cpp:634`）。`%t` 是启动时间而非每文件时间，所以多进程场景下靠 `%p` 区分实例、
靠 `filecount` 区分批次，两者可以同写。

轮换选项的键名在 `logFileOutput.cpp:41-42`：`filesize`（目标单文件大小，支持 K/M/G 后缀）与
`filecount`（保留的历史文件数，**不含活动文件**）。轮换后的文件名后缀是 `.0`、`.1` …，由
`LogFileOutput` 内部按编号轮转。`LogConfiguration` 的自述输出在 `logFileOutput.cpp:458` 打印
`,filecount=%u,filesize=%zu%s,async=%s`，可用于核对当前生效配置。

需要特别记住：**没有按天或按小时的时间维度轮换**，只有按大小。日志要按时间归档必须外挂
`logrotate` 或 `copytruncate` 方案，而 `copytruncate` 与 `filecount` 轮换会互相干扰。

### Async Logging

`logConfiguration.cpp:656-661` 描述了异步模式：`-Xlog:async[:[mode]]`，模式取 `drop` 或 `stall`。
所有消息先进中间缓冲区再由专职线程刷出，避免慢文件系统把 GC 停顿拉长。缓冲区大小由
`AsyncLogBufferSize` 控制，默认 `2*M`（`src/hotspot/share/runtime/globals.hpp:1867`）。

`drop` 在缓冲满时直接丢弃新消息，保证不阻塞被日志的线程；`stall` 会等待，此时异步的意义就退化成
「至少不丢」。生产上想拿可预测的停顿用 `drop`，想拿完整轨迹用 `stall`，两者不能同时。异步模式与
`LogVMOutput` / `-Xlog` 输出到 `syslog` 之类的外部汇不一定兼容，配置冲突时日志子系统自身会打
`logging` 标签的 warning。

### Tag Availability

⚠️ **标签存在于 `LOG_TAG_LIST` 里，不等于打开它就有任何输出。**

`logTag.hpp:75` 定义了 `LOG_TAG(deoptimization)`，但在整棵 `src/hotspot/share/` 树里检索不到任何一次以该
标签发起的日志调用——`grep -rn "deoptimization" src/hotspot/share --include='*.cpp' --include='*.hpp'`
的命中全是注释与普通文本，`LOG_TAGS(deoptimization)` 与 `log_debug(deoptimization` 形式**均为 0 处**。
也就是说 `-Xlog:deoptimization=debug` 会是一个语法完全合法、运行起来一行输出都没有的选择器。

判断方法固定三步，别只看清单：

```bash
# 1) 标签是否定义
grep -n "LOG_TAG(deoptimization)" src/hotspot/share/logging/logTag.hpp
# 2) 是否真有调用点 —— 这一步才是决定性的
grep -rn "log_debug(deoptimization\|log_trace(deoptimization\|LOG_TAGS(deoptimization)" src/hotspot/share/
# 3) 条件标签还要看它被哪个构建开关包着，以及本机构建是否满足
grep -n "LOG_TAG(hotcode)" src/hotspot/share/logging/logTag.hpp
```

第 2 步为空时，反优化的实际输出要到别的标签下找（如 `reinterpret`、`jit` 相关组合），或者直接读
[Deoptimization](/docs/CS/Java/JDK/JVM/Deoptimization.md) 里描述的机制。同一套判断也适用于
「`nmt` 标签明明定义了却没有输出」这类反馈——多半是 `LOG_TARGET` 的级别被后续选择器覆盖，或该路径
只在 `debug` 构建里编译。

### Legacy Flag Replacement

JEP 271 起，旧的 GC 打印标志全部改成了 `-Xlog` 的**语法糖**。翻译点集中在
`src/hotspot/share/runtime/arguments.cpp:3154-3169`：

```cpp
if (PrintGC) {
  log_warning(gc)("-XX:+PrintGC is deprecated. Will use -Xlog:gc instead.");
}
if (PrintGCDetails) {
  log_warning(gc)("-XX:+PrintGCDetails is deprecated. Will use -Xlog:gc* instead.");
}
...
const char* gc_conf = PrintGCDetails ? "gc*" : "gc";
```

| 旧写法 | 等价新写法 | JDK 27 现状 |
| :-- | :-- | :-- |
| `-XX:+PrintGC` | `-Xlog:gc` | 可用，打 deprecation warning |
| `-XX:+PrintGCDetails` | `-Xlog:gc*` | 可用，打 deprecation warning |
| `-verbose:gc` | `-Xlog:gc` | 可用，走同一 `_legacyGCLogging` 路径 |
| `-XX:+PrintGCTimeStamps` | `-Xlog:gc::uptime` | 装饰器接管 |
| `-XX:+PrintGCDateStamps` | `-Xlog:gc::time` 或 `utctime` | 装饰器接管 |
| `-XX:+PrintAdaptiveSizePolicy` | `-Xlog:gc+ihop,ergo*=debug` | 按 tag 拆分 |
| `-Xloggc:<file>` | `-Xlog:gc*:file=<file>` | 且天然获得轮换能力 |
| `-XX:+UseG1GC -XX:+PrintGCApplicationStoppedTime` | `-Xlog:safepoint` | 安全点统计归 `safepoint` |

要点是**一旦显式给了 `-Xlog:gc...`，旧标志的翻译就不再生效**，两者混写时以显式 `-Xlog` 为准，
否则很容易出现「加了参数却没输出」的错觉。运行时想改配置不需要重启：`jcmd <pid> VM.log list` 查看
当前选择器，`VM.log what=gc*=debug output=stdout` 现场提升级别——这条命令本身也是 dcmd，
定义在 `src/hotspot/share/logging/logDiagnosticCommand.cpp`，注册名 `VM.log`
（`logDiagnosticCommand.hpp:55`）。

## Native Memory Tracking

NMT 的思路是给 VM 自己的每一笔 `malloc` / `mmap` 打上标签，累计成一张**堆外**账本。它不是剖析器，
而是记账器，这个定位决定了它的能力边界与开销形态。

### Enabling NMT

只有两档可开，解析点在 `src/hotspot/share/runtime/arguments.cpp:3423`：

```text
-XX:NativeMemoryTracking=[off|summary|detail]
```

默认值是 `off`（`src/hotspot/share/runtime/globals.hpp:584`，debug 构建下默认 `summary`）。写错取值
会在启动期直接报 `Syntax error, expecting -XX:NativeMemoryTracking=[off|summary|detail]`。

`summary` 只按 tag 与虚拟内存区域记账；`detail` 额外为每个调用点建账，代价是每次分配都要抓 native
call stack 并查哈希表。`detail` 是 `VM.native_memory detail` 与 `detail.diff` 的前置条件——
`NMTDCmd::check_detail_tracking_level` 在级别不足时会直接返回提示而不是给出半截结果。

一个常被忽略的行为：内存吃紧时 NMT 会**自动从 detail 降级到 summary**，事件本身走 `nmt` 标签的
warning。所以「查了两次，第二次 detail 不可用」不是 bug，而通常已经说明进程离 native OOM 不远了。
排查时把 `-Xlog:nmt=info` 一起打开，能在事后还原出降级时刻。

### Memory Tags

tag 枚举定义在 `src/hotspot/share/nmt/memTag.hpp:32-61`，用 `f(mtXxx, "显示名")` 的宏展开。这份清单
就是 `jcmd ... summary` 输出的行名：

| 显示名 | 枚举 | 覆盖范围 |
| :-- | :-- | :-- |
| `Java Heap` | `mtJavaHeap` | 堆预留与提交 |
| `Class` | `mtClass` | 类元数据相关的 native 结构 |
| `Thread` | `mtThread` | `JavaThread` 等 VM 侧线程对象 |
| `Thread Stack` | `mtThreadStack` | 线程栈映射，**与上一行分开算** |
| `Code` | `mtCode` | CodeCache 与生成的代码 |
| `GC` | `mtGC` | GC 策略自身的数据结构 |
| `GCCardSet` | `mtGCCardSet` | G1 记忆集，单独列出便于归因 |
| `Compiler` | `mtCompiler` | JIT 编译期临时分配 |
| `Internal` | `mtInternal` | VM 使用但不属于任何已知类别的分配 |
| `Other` | `mtOther` | 非 VM 使用，例如 JNI 库自己 malloc 的 |
| `Symbol` | `mtSymbol` | 符号表 |
| `NMT` | `mtNMT` | NMT 自身的开销，用于解释「开了 NMT 就涨了」 |
| `Shared class space` | `mtClassShared` | CDS |
| `Arena Chunk` | `mtChunk` | arena 的 chunk 分配器 |
| `Metaspace` | `mtMetaspace` | Metaspace 与 class space 的整体 |
| `Synchronization` | `mtSynchronizer` | 锁与 monitor 结构 |
| `Object Monitors` | `mtObjectMonitor` | 对象监视器表 |
| `Logging` | `mtLogging` | 日志子系统 |
| `Serviceability` | `mtServiceability` | 可观测性底座自身 |
| `JNI` | `mtJNI` | JNI 相关结构 |

这里必须点破一个常见误解：**清单里没有 `Standard` 这个 tag**。NMT 汇总里的「分类合计」与「全量合计」
之差不是某个叫 `Standard` 的类别，而是未被 `TAG_STATIC_ALLOC` 或显式 tag 标注的路径落进了 `Internal`
与 `Other`。把 `Internal` 当成「标准库占用的内存」是错的，它只是「VM 分配的、暂时无主的部分」，
真正的第三方库内存应落在 `Other`。

`Class` 与 `Metaspace` 的区分同样值得记：`Class` 记的是 `InstanceKlass` 等 C++ 元数据结构的 native
分配，`Metaspace` 记的是 Metaspace 这块虚拟内存区间。两者口径不同、会互相包含，不能相加。要看
Metaspace 内部的 chunk 与按类加载器拆分，走 `VM.metaspace show-loaders=true`，
详见 [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)。

### The VM native_memory Command

命令名以源码为准，`src/hotspot/share/nmt/nmtDCmd.hpp:49`：

```cpp
static const char* name() { return "VM.native_memory"; }
static const char* impact() { return "Medium"; }
```

**JDK 27 上它不叫 `GC.native_memory`**，前缀迁移在这条命令上没有发生。

它是一个带解析器的 dcmd，七个**命名选项**全部是可选的（`src/hotspot/share/nmt/nmtDCmd.cpp:34-58`），
彼此互斥，最多选一个：

| 选项 | 作用 |
| :-- | :-- |
| `summary` | 默认行为，按 tag 打印 reserved / committed |
| `detail` | 按调用点打印 ≥ 1K 的分配，要求 `NativeMemoryTracking=detail` |
| `baseline` | 打一条基线快照，供后续 diff |
| `summary.diff` | 与上次 baseline 比，按 tag 显示增减 |
| `detail.diff` | 与上次 detail baseline 比，按调用点显示增减 |
| `statistics` | 打印追踪器自身的统计量，用于调优 |
| `scale` | `KB` / `MB` / `GB`，默认 `KB` |

因此真实用法是 `jcmd <pid> VM.native_memory summary`、`jcmd <pid> VM.native_memory detail.diff scale=MB`，
而不是把它当子命令树。**位置参数会被拒**：`NMTDCmd::execute` 统计被显式设置的互斥项数量，超过一个时
打印 `At most one of the following option can be specified: ...`（`nmtDCmd.cpp:96-98`）并直接返回；
一个都没设时落到 `summary`。所有查询都被 `MemTracker::query_lock()` 串行化，因此高频轮询 `detail`
会形成排队，表现为命令响应时间持续变长。

### Baseline and Diff

三步式用法是唯一可靠的定位手段，因为绝对值里混着启动期的固定开销：

```bash
jcmd $PID VM.native_memory baseline
# 让负载跑一段代表性时间
jcmd $PID VM.native_memory summary.diff scale=MB
```

`summary.diff` 输出里 `Total: reserved=... +..., committed=... +...` 的第二个数字就是净增。要下钻到
调用点必须 `detail.diff`，而它在 `baseline` 时级别不是 detail 的前提下会报 `No detail baseline for
comparison`——**baseline 的级别必须与 diff 的级别一致**，这一点常在事后才发现取错了。

`baseline` 可以反复打，每次覆盖上一次，所以适合「每十分钟打一次、跨发布版本对照」。但 `MemBaseline`
只保留一份，多轮对照要靠把输出重定向到文件自己留存。

### Malloc Limit

`-XX:MallocLimit` 是一个常被漏掉的诊断能力：给指定 tag 的 malloc 总量设上限，触顶后**主动制造一次
native OOM 或 fatal error**，从而在受控环境里把泄漏点逼出来。声明在
`src/hotspot/share/runtime/globals.hpp:1312`，注意它是 **DIAGNOSTIC** 级标志，命令行上必须先给
`-XX:+UnlockDiagnosticVMOptions`：

```bash
java -XX:+UnlockDiagnosticVMOptions \
     -XX:NativeMemoryTracking=summary \
     -XX:MallocLimit=compiler:200m:oom,code:100m \
     -jar app.jar
```

约束写死在标志说明里：**`MallocLimit` 依赖 NMT，取值必须是 `summary` 或 `detail`**，否则没有 tag
可以归类、限制无从生效。动作关键字两选：`fatal`（默认，在分配点 fatal error）与 `oom`（模拟 native
OOM，走正常的 `OutOfMemoryError` 路径，更接近真实故障形态）。语法上
`-XX:MallocLimit=2g` 是全局上限，`<category>:<size>[:<flag>]` 逗号串是分类上限。

### Cost and Blind Spots

NMT 的开销与两个量成正比：分配次数、以及是否 detail。summary 级别只多做一次 tag 累加；detail 级别
每次分配要构造 `NativeCallStack`、查 `MallocSiteTable`，对分配密集的 native 路径可能是数倍劣化。
它自己的账记在 `NMT` tag 下，`statistics` 选项给出的哈希表冲突与丢弃计数就是用来判断有没有开爆的。

更关键的是**它看不到的部分**，这决定了「NMT 说没涨」不能推出「native 没涨」：

- 只统计打了点的路径。libc 内部行为、`dlopen` 加载的第三方库自己的 malloc、JVM 外的映射都不在账上。
- `mmap` 直连的映射走 `VirtualMemory` 记账，但绕过封装的原始映射不会进来。
- 它只记 reserved / committed，不记 RSS，也不区分脏页。
- 开了 `MallocLimit` 时超限后返回 nullptr 的那条路径**不计入**当前分类。

所以 NMT 与进程 RSS 对不上是常态。标准收尾动作是拿 `System.map` 做进程级映射清单，与 NMT 汇总逐项
核对——这条 dcmd 见下一节。

## Diagnostic Commands

### Registration

诊断命令的骨架是「一个 `DCmd` 子类 + 一个 `DCmdFactory`」。`DCmdFactory` 声明在
`src/hotspot/share/services/diagnosticFramework.hpp:341`，注释直接写明工厂必须注册才能被看到，注册点
集中在 `src/hotspot/share/services/diagnosticCommand.cpp:96` 起的一串调用：

```cpp
uint32_t full_export = DCmd_Source_Internal | DCmd_Source_AttachAPI | DCmd_Source_MBean;
DCmdFactory::register_DCmdFactory(new DCmdFactoryImpl<VersionDCmd>(full_export));
...
DCmdFactory::register_DCmdFactory(new DCmdFactoryImpl<HeapDumpDCmd>(DCmd_Source_Internal | DCmd_Source_AttachAPI));
```

三个来源位定义在 `diagnosticFramework.hpp:36-39`：`Internal` 是 VM 内部调用，`AttachAPI` 是 `jcmd` /
`jattach` 这类走 attach 的外部调用，`MBean` 是 `HotSpotDiagnosticMXBean`。注意 `GC.heap_dump` **没有**
MBean 位——堆转储刻意不暴露成 JMX 可远程触发的操作。注册是一次性的，头文件里明写「一旦注册不得
反注册」，工厂挂在 `DCmdFactory_lock` 保护的单向链表上。

命令的元信息是纯静态的：`name()`、`description()`、`impact()` 三个静态函数，加上
`num_arguments()`。`DCmdFactoryImpl` 在 debug 构建里会用反射解析出的参数个数和 `num_arguments()`
做 `assert` 比对（`diagnosticFramework.hpp` 的 `get_num_arguments`），所以「命令能列出但参数报错」
在 release 上偶尔仍会发生，而 debug 构建会在启动期就炸出来。

### Impact Levels

`DCmd::impact()` 返回一句对人有用的分级说明，源码注释（`diagnosticFramework.hpp:236-240`）明确
「部分诊断命令会严重干扰 JVM 行为」。常见的几档：

| 级别 | 典型命令 | 为什么 |
| :-- | :-- | :-- |
| `No cost` / `Low` | `VM.version`、`VM.flags`、`VM.command_line`、`Thread.vthread_pollers` | 读现成状态 |
| `Medium` | `VM.native_memory`、`VM.metaspace` | 要遍历内部结构，可能持锁 |
| `Medium: Pause time depends on number of threads` | `Thread.print`、`Compiler.queue` | 需要安全点 |
| `High` | `GC.heap_dump` | STW + 大量写盘 |

轮询脚本里最该警惕的是把 `Medium` 及以上当免费：`Thread.print` 会触发一次安全点同步，
高频采集本身就能把停顿分布拉坏。

### Command Naming

命名前缀是**语义分组，不是历史包袱**，且 JDK 27 上分组很清楚。全量清单的权威来源是
`jcmd <pid> help`，下面是本树 grep 到的实际字符串与其位置：

| 前缀 | 实例 | 位置 |
| :-- | :-- | :-- |
| `VM.` | `VM.version`、`VM.flags`、`VM.info`、`VM.uptime`、`VM.log`、`VM.native_memory`、`VM.metaspace`、`VM.classloaders`、`VM.symboltable`、`VM.stringtable`、`VM.cds` | `diagnosticCommand.hpp:62,113,207,194`、`logDiagnosticCommand.hpp:55`、`nmtDCmd.hpp:49`、`metaspaceDCmd.hpp:47`、`classLoaderHierarchyDCmd.hpp:40` |
| `GC.` | `GC.run`、`GC.run_finalization`、`GC.heap_info`、`GC.finalizer_info`、`GC.heap_dump`、`GC.class_histogram` | `diagnosticCommand.hpp:218,231,244,258,282,304` |
| `Thread.` | `Thread.print`、`Thread.dump_to_file`、`Thread.vthread_scheduler`、`Thread.vthread_pollers` | `diagnosticCommand.hpp:381,794,810,824` |
| `Compiler.` | `Compiler.codelist`、`Compiler.codecache`、`Compiler.queue`、`Compiler.perfmap`、`Compiler.CodeHeap_Analytics`、`Compiler.memory`、`Compiler.directives_add` | `diagnosticCommand.hpp:538,553,503,522,573,842,623` |
| `System.` | `System.map`、`System.dump_map`、`System.trim_native_heap`、`System.native_heap_info` | `diagnosticCommand.hpp:858,871`、`os/linux/trimCHeapDCmd.hpp:37`、`os/linux/mallocInfoDcmd.hpp:36` |
| `JFR.` | `JFR.start`、`JFR.dump`、`JFR.check`、`JFR.stop`、`JFR.view`、`JFR.query`、`JFR.configure` | `share/jfr/dcmd/jfrDcmds.hpp:54-196` |

三条结论：

1. **`VM.` 前缀指的是「虚拟机自身状态」，不是「尚未迁移的旧名」**。Metaspace、NMT、符号表、类加载器
   层级这些虽然和堆有关，但归属仍是 VM 级结构，JDK 27 依然在 `VM.` 下。
2. `System.trim_native_heap` 与 `System.native_heap_info` 是 **Linux 专属**，实现分别在
   `os/linux/trimCHeapDCmd.hpp` 与 `os/linux/mallocInfoDcmd.hpp`。前者调 `malloc_trim` 归还 glibc
   碎片，是「NMT 显示已释放但 RSS 不降」的第一个应对手段；后者读 glibc `mallinfo`。
   非 Linux 平台的 `jcmd help` 里不会出现这两条。
3. `System.map` / `System.dump_map` 在 Linux、Windows、macOS 上有实现（描述文本明确限定这三者），
   输出的是**带 HotSpot 标注的进程内存映射**——把 NMT 的 tag 贴到 `/proc/self/maps` 的每一段上，
   这是把「账本」和「实际映射」对上的唯一命令。

`VM.flags` 的参数只剩 `-all`，`VM.metaspace` 的参数则是一串命名选项
（`basic`、`show-loaders`、`show-classes`、`by-spacetype`、`by-chunktype`、`vslist`、`chunkfreelist`、
`scale`，见 `metaspaceDCmd.cpp:40-49`）。**dcmd 的参数风格是「名字=值」而不是位置参数**，与
`java` 命令行标志的 `-`/`+` 语法完全不同，这是脚本里最常见的报错来源。

### Diagnostic and Experimental Gating

必须区分**两套互不相干的门槛**，这是本篇最容易写错的一节：

- `-XX:+UnlockDiagnosticVMOptions` / `-XX:+UnlockExperimentalVMOptions` 管的是**JVM 标志**。
  `MallocLimit`、`PrintAssembly`、`LogVMOutput` 都是 `DIAGNOSTIC` 级，不给 unlock 就直接拒绝。
  标志的可见性还影响 `VM.flags` 是否打印它。
- **dcmd 本身没有 diagnostic / experimental 的解锁开关**。`diagnosticFramework` 里只有一个
  `_hidden` 位（`diagnosticFramework.hpp:350-352`），语义是「hidden 的命令不出现在 `help` 列表里」，
  而不是「需要授权才能调用」。也就是说，**只要 attach 能连上，隐藏命令依然可被执行**——
  隐藏只是不在列表里提示，不是访问控制。

结论：想用 `jcmd <pid> VM.set_flag <flag> <value>` 去改一个 DIAGNOSTIC 标志，卡点在目标标志本身是否
可写（`services/writeableFlags.cpp`），而不是 dcmd 权限。运行时可改标志是一个明确的子集，`develop`
级与 `manageable=false` 的标志一律改不动。attach 本身的开关才是唯一真正的安全闸门，见下一节。

## The Attach Mechanism

### Socket and Trigger File

POSIX 实现全在 `src/hotspot/os/posix/attachListener_posix.cpp`。监听是一个 **AF_UNIX 域套接字**，
路径为 `<temp>/.java_pid<pid>`（`attachListener_posix.cpp:198`），默认 temp 目录即 `/tmp`。协议是
极简的行式命令：客户端发命令名与参数，服务端把 `DCmd` 的输出流写回去。

启动时机有两种：

```cpp
// globals.hpp:1753
product(bool, StartAttachListener, false, ...)
// globals.hpp:1750
product(bool, DisableAttachMechanism, false, ...)
```

`-XX:+StartAttachListener` 让 JVM 一启动就建好套接字；否则走**惰性触发**：`AttachListener::is_init_trigger()`
（`attachListener_posix.cpp:408`）检查工作目录或 temp 目录下是否存在 `.attach_pid<pid>` 文件：

```cpp
os::snprintf_checked(fn, sizeof(fn), ".attach_pid%d", os::current_process_id());
RESTARTABLE(::stat(fn, &st), ret);
if (ret == -1) {
  log_trace(attach)("Failed to find attach file: %s, trying alternate", fn);
  os::snprintf_checked(fn, sizeof(fn), "%s/.attach_pid%d", os::get_temp_directory(), ...);
}
```

这正是 `jcmd <pid> help` / `jstack` 首次连接慢一下的原因：客户端先创建 `.attach_pid<pid>` 触发文件并
向目标进程发信号，目标进程在**信号处理线程**里检查到触发文件才把监听建起来（`share/runtime/os.cpp:399`
的 `case SIGBREAK` 分支，整段被 `!DisableAttachMechanism` 包着），客户端再重试连接。同一处还先用
`AttachListener::transit_state(AL_INITIALIZING, AL_NOT_INITIALIZED)` 做状态跃迁，并发到达的第二个信号
会直接 `continue`，避免两个信号同时初始化监听；若 socket 文件已丢失，则走
`AttachListener::check_socket_file()` 重启监听。整个握手有重试间隔，
**首连延迟可达秒级**，脚本里应当加重试而不是把 timeout 调大。

两条安全检查值得知道：触发文件的 owner 必须是目标进程的有效 uid 或 root，否则直接忽略并打
`log_debug(attach)("File %s has wrong user id ...")`——避免任意本地用户凭创建文件启动别人的 attach；
另外 Linux/BSD 上会清理残留的 `.java_pid` 文件（`attachListener_posix.cpp:340-349`），防止崩溃遗留的
套接字让后续连接挂死。`DisableAttachMechanism=true` 时上述路径全部关闭，这是容器镜像加固里
少数真正有效的 JVM 侧开关。

### jps and jcmd

`jps` 与 attach 是**两条独立通道**，理解这点能省掉很多无效排查：

- `jps` 读的是 temp 目录下的 **hsperfdata** 文件（`/tmp/hsperfdata_<user>/<pid>`），由
  `PerfMemory` 维护，`src/hotspot/share/services/management.cpp:222` 的 `PerfMemory::set_accessible(true)`
  是它对外开放的动作。
- `jcmd <pid>` 才走 `.java_pid<pid>` 套接字。

所以：`jps` 看不到某个进程不代表它不能被 attach（perfdata 可能被清理），反之 `jps` 能列出但
`jcmd` 连不上多半就是 attach 未启用或 `-XX:+DisableAttachMechanism`。容器里最常见的失效原因是
`/tmp` 不是同一个挂载点或 `TMPDIR` 在 JVM 与客户端之间不一致，两个通道会同时或分别断掉。
`jcmd -l` 的输出等于「perfdata 列表 + 主类名」，它同样不依赖 attach 成功。

## Version Traps and Boundaries

### Flags and hsdis

`-XX:+PrintFlagsFinal` 与 `-XX:+PrintFlagsInitial` 仍然工作，但对**未 unlock 的 DIAGNOSTIC /
EXPERIMENTAL 标志会隐藏**，看起来像「少了一批参数」。要拿全集：

```bash
java -XX:+UnlockDiagnosticVMOptions -XX:+UnlockExperimentalVMOptions -XX:+PrintFlagsFinal -version
```

运行时更常用的其实是 `jcmd <pid> VM.flags -all`，它不需要重启，缺点是只给当前值、不给出处与取值范围。
`PrintAssembly` 系列是 `DIAGNOSTIC`（`globals.hpp:621`），配套 `PrintAssemblyOptions`
（`globals.hpp:624`）。而 **hsdis 不在这棵源码树里**：`src/hotspot` 下只有各平台的
`disassembler_x86.cpp` 之类的内部汇编器，hsdis 是一个**外部动态库**，运行期按名字加载，需要单独构建或
从发行版取得，装不上时 `-XX:+PrintAssembly` 退化成打印地址而不报错。这是本批新笔记里容易写错的点，
所以本篇只标注「外部库、树内无定义」，不给构建步骤。

### VMStructs and hsdb

Serviceability Agent 那条路一句话概括：内核用 `VMStructs` / `VMFieldsInfo` 宏把 C++ 类与字段的
布局导出成一张可被外部读取的表，`jdk.hotspot.agent` 里的镜像类据此在堆外重建对象图，`hsdb` 是它的
REPL。它的价值是能读 core dump，代价是**对内核改动极度敏感**，且需要非 strip 的二进制。本篇不展开，
定位与用法归 [JVM](/docs/CS/Java/JDK/JVM/JVM.md)。

### Boundaries With JFR and JNI

本文只讲底座，不讲建立在其上的产品：

- **JFR** 是事件型环形缓冲剖析，走的是另一套（`share/jfr/`），它通过 `JFR.*` 一组 dcmd 被驱动，
  因此复用了本篇的 attach + 诊断命令通道；但事件定义、飞行记录与采样开销归
  [JFR](/docs/CS/Java/Tools/JFR.md)。日志里 `jfr` 标签记的是 JFR 自身状态，不是事件内容。
- **`-Xcheck:jni`** 是 JNI 调用的运行期校验，输出走 `Error` 文件与 `jni` 标签。它的语义依附于
  JNI 引用体系，归 [Handles](/docs/CS/Java/JDK/JVM/Handles.md)。
- **Agent** 分 `premain` / `agentmain` 两类，`agentmain` 正是靠本篇的 attach 机制注入的；
  instrument 与 JVMTI 的细节归 [Agent](/docs/CS/Java/JDK/Agent.md)。
- **Arthas** 等工具全部是这两层的消费者：`javaagent` 注入 + dcmd/attach 通信，
  见 [Arthas](/docs/CS/Java/Tools/Arthas.md)。

## Links

- [JVM](/docs/CS/Java/JDK/JVM/JVM.md)
- [Safepoint](/docs/CS/Java/JDK/JVM/Safepoint.md)
- [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)
- [Deoptimization](/docs/CS/Java/JDK/JVM/Deoptimization.md)
- [JFR](/docs/CS/Java/Tools/JFR.md)
- [Agent](/docs/CS/Java/JDK/Agent.md)

## References

- [JEP 158: Unified JVM Logging](https://openjdk.org/jeps/158)
- [JEP 271: Unified GC Logging](https://openjdk.org/jeps/271)
- [Native Memory Tracking](https://docs.oracle.com/en/java/javase/27/vm/native-memory-tracking.html)
- [jcmd](https://docs.oracle.com/en/java/javase/27/tools/jcmd.html)
- [Managing System-Level Observability](https://docs.oracle.com/en/java/javase/27/vm/managing-system-level-observability.html)
