## Introduction

JVM 的冷启动不是一笔开销，而是**五笔可以分别计量的账**。把它们拆开，才能看懂 CDS / AppCDS / AOT 这条演进线
上每一步到底在削哪一笔：

| 账目 | 做什么 | 代价来源 | 被哪项技术削掉 |
| :-- | :-- | :-- | :-- |
| 读字节码 | 打开 class 文件、读入 constant pool 与属性 | 磁盘 IO、大量小文件、模块解析 | CDS 的 static / dynamic archive |
| 解析与校验 | symbol 去重、`ClassFileParser` 建 `InstanceKlass`、字节码 verify | CPU + Metaspace 分配 | CDS（产物已解析）、AOT class loading |
| 链接 | super / interface 层次、字段方法表、反射与 `ConstantPool` 缓存、invokedynamic 解析 | 依赖类加载器状态，顺序敏感 | AOT class **linking** |
| 初始化 | 跑 `<clinit>`、构造静态对象图 | 分配对象、触发 GC、预热 Metaspace | AOT object caching，即归档 Java heap |
| 预热编译 | 解释执行若干轮后由 C1/C2 编译热点 | 采样 + 编译排队，分钟级 | AOT method code / 训练-回放 |

传统 CDS 只碰前两笔：它把**已解析的产物**存成可 mmap 的镜像，于是"读 class 文件 + 解析"整段被替换成一次
地址映射。链接与初始化仍然要在每次启动时重做——这正是 JDK 24 之后 AOT 路线要解决的：把链接结果、初始化后的
对象图、乃至编译好的机器码也一并落到归档里。

本节的结论先行：**归档（archive / cache）本质上是一个"进程快照文件"，演进方向就是让这张快照覆盖启动路径
上越来越多的阶段**。HotSpot 侧的这套机制在源码里统一住在 `share/cds/`（目录名仍是 CDS，但 AOT 相关代码
已占大半）与 `share/code/aotCodeCache.{hpp,cpp}`。

## Version Baseline

> [!NOTE]
>
> 本篇基线是 **JDK 27**。最容易写错的三点：
>
> 1. **经典 CDS 开关在 JDK 19 就已全部作废**。`-XX:+DumpSharedSpaces`、`-XX:+DynamicDumpSharedSpaces`、
>    `-XX:+RequireSharedSpaces`、`-XX:+UseSharedSpaces` 在 JDK 18 deprecated、**JDK 19 obsolete**
>    （`runtime/arguments.cpp:528-531`）。网上大量"两步生成 AppCDS"教程已不可执行，见
>    [Obsolete Classic Flags](#obsolete-classic-flags)。
> 2. **AOT 选项实名是 `AOTMode` / `AOTConfiguration` / `AOTCache` / `AOTCacheOutput`**
>    （`cds/cds_globals.hpp:109-126`）。早期 Project Leyden 预览构建里的 `CacheDataStore` /
>    `-XX:AOTMode=generate` 一类命名在 jdk-27-ga 源码树里 grep 不到，不要照旧文写。
> 3. **JEP 归属容易记串**（本库有过多次教训，均已逐条 curl 核实标题）：JEP 483 = *Ahead-of-Time Class
>    Loading & Linking*（JDK 24），JEP 514 = *Ahead-of-Time Command-Line Ergonomics*、JEP 515 =
>    *Ahead-of-Time Method Profiling*（JDK 25），JEP 516 = *Ahead-of-Time Object Caching with Any GC*
>    （JDK 26）。JEP 544 *Ahead-of-Time Code Compilation* 与 JEP 545 *Faster Startup and Warmup with
>    ZGC* 在 27 时点仍标注 Target 28，**不能写成 JDK 27 已交付**。
>
> 详见 [JVM 版本基线](/docs/CS/Java/JDK/JVM/JVM.md?id=version-baseline)。

## Technique Evolution

| 阶段 | 触发方式 | 归档里多存了什么 | 启动阶段被跳过的部分 | 源码主干 |
| :-- | :-- | :-- | :-- | :-- |
| 静态 CDS | `-Xshare:dump` 生成 `classes.jsa` | boot loader 类的已解析 `Klass`、符号表 | 读字节码 + 解析 | `archiveBuilder`, `filemap` |
| AppCDS | 运行时 class list / `-XX:SharedClassListFile` | 应用与库类 | 同上，覆盖应用类 | `classListWriter`, `metadata` 处理 |
| 动态归档 | `-XX:ArchiveClassesAtExit=<file>` | **实际加载过**的类（跑一遍即得） | 同上，无需手维护清单 | `dynamicArchive.cpp` |
| 归档 Java heap | `-XX:AOTMode=create`（AOT 堆归档） | 静态字段可达的对象图 | `<clinit>` 不必重跑 | `heapShared`, `aotMappedHeap*`, `aotStreamedHeap*` |
| AOT class linking | `-XX:AOTMode=record` → `create` | 链接完成态的 `InstanceKlass` + 预解析常量池 | 链接阶段 | `aotClassLinker`, `aotLinkedClassTable`, `aotConstantPoolResolver` |
| AOT method code | `-XX:+AOTRecordTraining` / `AOTReplayTraining` | C1/C2 产物、adapter、shared blob | 预热编译 | `code/aotCodeCache.cpp` |
| final image | `-XX:AOTMode=create` 产出的 cache | 上面这些的合成体 | 启动路径被压成"映射 + 少量修补" | `finalImageRecipes.cpp` |

注意最后两行的关系：**final image 不是一个单独开关，而是 `-XX:AOTMode=create` 写出的那个文件的角色**。
`cdsConfig.hpp:121-140` 把静态归档的写出模式明确分成三种，这段注释是全库对术语最权威的定义：

```cpp
  // "classic"   - This is the traditional CDS workflow of
  //               "java -Xshare:dump -XX:SharedClassListFile=file.txt".
  //
  // "preimage"  - This happens when we execute the JEP 483 training run, e.g:
  //               "java -XX:AOTMode=record -XX:AOTConfiguration=app.aotconfig -cp app.jar App"
  //               The above command writes app.aotconfig as a "CDS preimage". This
  //               is a binary file that contains all the classes loaded during the
  //               training run, plus profiling data (e.g., the resolved constant pool entries).
  //
  // "final"     - This happens when we execute the JEP 483 assembly phase, e.g:
  //               "java -XX:AOTMode=create -XX:AOTConfiguration=app.aotconfig -XX:AOTCache=app.aot -cp app.jar"
  //               The above command loads all classes from app.aotconfig, perform additional linking,
  //               and writes app.aot as a "CDS final image" file.
  //
  // The main structural difference between "preimage" and "final" is that the preimage
  // - has a different magic number (0xcafea07c)
  // - does not have any archived Java heap objects
  // - does not have aot-linked classes
```

三态对应三个 predicate：`CDSConfig::is_dumping_classic_static_archive()`、
`is_dumping_preimage_static_archive()`、`is_dumping_final_static_archive()`（`cdsConfig.cpp:796-804`）。
**preimage 里没有 Java heap 对象、也没有 aot-linked 类**——这条差别决定了后面所有开关的排布。

## Static and Dynamic Archives

### Xshare Mode Semantics

`-Xshare` 不是"一个布尔"，它在 `arguments.cpp:2300-2319` 被翻译成两个独立 flag 的组合，语义一目了然：

| 选项 | 实现动作 | 实际含义 |
| :-- | :-- | :-- |
| `-Xshare:dump` | `CDSConfig::enable_dumping_static_archive()` | 只写归档、不跑应用；生成 `classes.jsa` |
| `-Xshare:on` | `UseSharedSpaces = true; RequireSharedSpaces = true` | 必须用归档，映射失败就退出 |
| `-Xshare:auto` | `UseSharedSpaces = true; RequireSharedSpaces = false` | 有归档就用，没有就退回解析 class 文件 |
| `-Xshare:off` | 两个 flag 都置 false | 完全关闭，等价 `-XX:-UseSharedSpaces`（该 flag 已作废）|

四个分支**都会**调用 `CDSConfig::set_old_cds_flags_used()`，这一点决定了它与新 AOT 开关的互斥关系
（见 [Boundaries and Division of Labor](#boundaries-and-division-of-labor)）。

诊断侧的配套项：

| 选项 / flag | 位置 | 用途 |
| :-- | :-- | :-- |
| `-Xlog:cds` | `logging/logTag.hpp:52` 定义 `cds` tag | 归档加载失败、映射地址、被跳过的类的原因 |
| `-Xlog:aot` | `logTag.hpp:41` | AOT 三阶段与 flag ergonomics 的决策过程 |
| `-Xlog:aot,codecache` | 两个 tag 组合 | AOT 代码缓存的存取细节 |
| `-XX:+PrintSharedArchiveAndExit` | `cds_globals.hpp:51` | 打印归档内容后立刻退出，用来核对"到底进没进去" |
| `-XX:+VerifySharedSpaces` | `cds_globals.hpp:42` | 载入时校验完整性 |
| `jcmd <pid> VM.cds` | `services/diagnosticCommand.hpp` | 运行中做 `dynamic_dump`，配合 `RecordDynamicDumpInfo` |

### Archive Contents and Mapping

归档不是"class 文件的拼接包"，而是**按运行时布局排好的二进制镜像**：`archiveBuilder` 在 dump 期把
`InstanceKlass`、方法/字段数组、常量池、符号表按目标地址摆进只读区与读写区，`filemap` 负责写出与 mmap 时
的搬迁（relocation）。因此载入时大多数类不需要再解析，直接"就是那个对象"。

几个值得记住的落盘参数：

- `-XX:SharedBaseAddress`（`cds_globals.hpp:54`）：LP64 默认 `32*G`。归档里存的是绝对地址，理想情况下一次
  mmap 到位就零搬迁。
- `-XX:ArchiveRelocationMode`（`cds_globals.hpp:97`，DIAGNOSTIC，默认 1）三种取值：`0` 先试首选地址、失败再
  换地址；`1` 总是用替代地址（默认）；`2` 只用首选地址、映射不上就干脆不用归档。
- `-XX:SharedSymbolTableBucketSize`（`cds_globals.hpp:62`，默认 4）：共享符号表每桶平均符号数。
- `-XX:SharedArchiveFile`（`cds_globals.hpp:88`）可以**在同一个值里写两个路径**（base 与 top），由
  `CDSConfig::extract_archive_paths()`（`cdsConfig.hpp:61`）拆开，内部对应
  `_input_static_archive_path` 与 `_input_dynamic_archive_path` 两个成员——这就是"分层归档 / layered
  archive"的实现位置。
- `-XX:ExtraSharedClassListFile`（`cds_globals.hpp:94`）在默认 class list 之上追加，`-XX:SharedClassListFile`
  （`:85`）整体替换。
- 类清单本身由 `-XX:DumpLoadedClassList=<file>`（`cds_globals.hpp:75`）在"关闭归档"的一次运行里导出，
  实现见 `cds/classListWriter.cpp`。**这个选项仍然有效，作废的是它的第二步**（见下文）。

Java heap 也在归档里（AOT 路线），但**它的落盘方式有两种，取舍完全不同**，这是本篇最需要展开的一节，见
[Mapped Heap and Streamed Heap](#mapped-heap-and-streamed-heap)。

### Dynamic Dumping at Exit

动态归档的真实选项名是 `-XX:ArchiveClassesAtExit=<file>`（`cds_globals.hpp:91`，描述就是 "The path and name
of the dynamic archive file"），它的消费点在 `cds/dynamicArchive.cpp:403`。与静态 dump 的关键区别是**它发生在
正常运行的 VM 退出时**，归档的是"这次真的加载过"的类，因此不需要预先维护 class list。

约束都在 `CDSConfig` 里，逐条都是硬报错或警告：

- 不能和 `-Xshare:dump` 同时用（`cdsConfig.cpp:210-213`）。
- 不能把归档目标指向默认 CDS 归档本身（`cdsConfig.cpp:217-219`）。
- `-XX:SharedArchiveFile` 已经指定了动态归档时，不能再用 `ArchiveClassesAtExit`（`cdsConfig.cpp:300-301`）。
- **基座静态归档没加载成功时，动态归档直接放弃**，并提示 `Run with -Xlog:cds for more info`
  （`prepare_for_dumping()`，`cdsConfig.cpp:771-791`）。这是实践中最常见的"归档没生效"原因。
- `-XX:+RecordDynamicDumpInfo` 与 `ArchiveClassesAtExit` 互斥（`cdsConfig.cpp:692-697`）；前者只记录
  "下次该归档什么"的信息，供 `jcmd VM.cds dynamic_dump` 使用（`cds_globals.hpp:45-46`）。

### Auto Create Shared Archive

`-XX:+AutoCreateSharedArchive` **确实存在**（`cds_globals.hpp:48`，描述 "Create shared archive at exit if cds
mapping failed"），语义是"用 `-XX:SharedArchiveFile` 指定的路径，不存在就顺手生成一个"。规则：

- 必须搭配 `-XX:SharedArchiveFile`，否则警告 `-XX:+AutoCreateSharedArchive requires -XX:SharedArchiveFile`
  并失效（`cdsConfig.cpp:705-709`）。
- 与 `-XX:ArchiveClassesAtExit` 互斥（`cdsConfig.cpp:710-713`）。
- 当指定的归档文件不存在时，内部把它转成一次动态归档：`FLAG_SET_ERGO(ArchiveClassesAtExit, SharedArchiveFile)`
  （`cdsConfig.cpp:262-266`）。
- 基座 CDS 归档未加载时不支持，会关闭该 flag 并提示（`cdsConfig.cpp:270-272`）。
- 若 `-XX:SharedArchiveFile` 指向的是**静态**归档，该选项被忽略并告警（`cds/filemap.cpp:597-598`）。

典型用法是把 cache 放在应用可写目录里，第一次运行自举、后续运行直接受益：

```bash
java -XX:SharedArchiveFile=./app.jsa -XX:+AutoCreateSharedArchive -jar app.jar
```

### Obsolete Classic Flags

> [!WARNING]
>
> 这四个 CDS 开关在 JDK 27 源码里**只剩 obsolete 表中的墓碑**（`runtime/arguments.cpp:528-531`，
> deprecated in 18 / **obsolete in 19**）：
>
> - `-XX:+DumpSharedSpaces` → 改用 `-Xshare:dump`
> - `-XX:+DynamicDumpSharedSpaces` → 改用 `-XX:ArchiveClassesAtExit=<file>` 或 `-XX:+AutoCreateSharedArchive`
> - `-XX:+RequireSharedSpaces` → 改用 `-Xshare:on`
> - `-XX:+UseSharedSpaces` → 改用 `-Xshare:off`（关）/ `-Xshare:auto`（开）
>
> 于是**"用 `-XX:DumpLoadedClassList` 导出清单、再用 `-XX:+DumpSharedSpaces` 生成归档"这套流传极广的两步
> 教程在 JDK 19 之后完全不可执行**——第二步会直接报 "Unrecognized VM option"。正确的两步是
> `-XX:DumpLoadedClassList=classes.lst` 导出、再 `-Xshare:dump -XX:SharedClassListFile=classes.lst`
> 生成（`cdsConfig.hpp:123-124` 的 classic 工作流注释就是这一条）。
>
> 另一个高频坑：旧文章里的 `-XX:CacheDataStore=<file>`、`-XX:+CacheAppCDS`、`-XX:AOTMode=generate` 一类写法。
> `CacheDataStore` 与 `CacheAppCDS` 在 jdk-27-ga 的 `src/hotspot/` 全树 grep **零命中**；`generate` 则会被
> `AOTModeConstraintFunc` 直接判为非法（它只放行 `off/record/create/auto/on/required`）。**27 的实名是
> `AOTMode` / `AOTConfiguration` / `AOTCache` / `AOTCacheOutput`**。另外 `-XX:+AutoCreateSharedArchive`
> 与 `-XX:ArchiveClassesAtExit` 是**两个不同**的东西，别混为一谈。

## AOT Class Loading and Linking

### AOTMode Value Set

`-XX:AOTMode` 是 `ccstr` flag（`cds_globals.hpp:109-112`），**带 constraint**：合法取值集由
`AOTModeConstraintFunc`（`runtime/flags/jvmFlagConstraintsRuntime.cpp:58-76`）逐个 `strcmp` 判定，报错串写得很
明确——`Must be one of the following: off, record, create, auto, on, required`，共 **6 个**取值，默认 `auto`。
注意 **flag 自己的描述串只列了 5 个**（`cds_globals.hpp:110-111` 漏掉了 `required`），以 constraint 为准。
分发逻辑在 `CDSConfig::check_aot_flags()`（`cdsConfig.cpp:478-487`）：

| 取值 | 入口函数 | 实际语义（源码行为） |
| :-- | :-- | :-- |
| `auto` | `check_aotmode_auto_or_on()` | `UseSharedSpaces=true`、`RequireSharedSpaces=false`：有可用 cache 就用，没有就退回经典流程；**不允许同时给 `AOTConfiguration`**（`cdsConfig.cpp:496-499` 直接退出） |
| `on` | `check_aotmode_auto_or_on()` | 同上，但 `RequireSharedSpaces=true`：cache 必须能用，否则退出 |
| `required` | `check_aotmode_auto_or_on()` | **当前与 `on` 行为完全相同**（`cdsConfig.cpp:478` 与 `:502-507` 把两者走同一分支），差异只体现在字面上 |
| `off` | `check_aotmode_off()` | 两个 flag 都置 false，彻底关闭 CDS/AOT（`cdsConfig.cpp:490-493`） |
| `record` | `check_aotmode_record()` | **训练阶段**：写 preimage 到 `AOTConfiguration`；要求 `AOTCacheOutput` 与 `AOTConfiguration` 至少给一个；`AOTCache` **必须不给**（`cdsConfig.cpp:561-563`） |
| `create` | `check_aotmode_create()` | **组装阶段**：读 `AOTConfiguration`，写 `AOTCache`；`AOTConfiguration` 必给，`AOTCache`/`AOTCacheOutput` 二选一 |

三处实现细节值得单独记：

1. **`AOTMode` 可以省略**。只给 `-XX:AOTCacheOutput=<file>` 时，VM 会 ergo 地把 mode 设成 `record`
   （`cdsConfig.cpp:466-473`，日志 `Selected AOTMode=record because AOTCacheOutput is specified`）。这就是
   "single-command training"：`_is_single_command_training = true`，并自动生成临时配置名
   `AOTCacheOutput + ".config"`（`cdsConfig.cpp:547-558`）。
2. **组装阶段会禁掉所有 JVMTI agent**。`check_aotmode_create()` 末尾调用
   `JvmtiAgentList::disable_agent_list()`（`cdsConfig.cpp:612-620`），理由写在注释里：agent 不能影响 cache
   内容（既不能重定义已缓存的类，也不能改被缓存的堆对象），而组装阶段根本不跑应用代码，"没人会注意到 agent
   没加载"。
3. 文件名支持 `%p` / `%t` 占位（`substitute_aot_filename()`，`cdsConfig.cpp:511-537`），且各自**最多出现一次**，
   否则报错——注意 single-command training 下 `%p` 是**训练进程**的 pid，不是组装进程的（注释在 `:529-530`）。
4. `required` 是**只在 constraint 里出现、没写进 flag 描述**的第六个取值，且 `check_aotmode_auto_or_on()` 对
   `on` 与 `required` 走同一分支（`cdsConfig.cpp:502-507` 的 assert 同时接受两者）。写文档时列 5 个还是 6 个，
   取决于你引的是 `cds_globals.hpp` 的描述串还是 `jvmFlagConstraintsRuntime.cpp` 的判定串——**以判定串为准**。

三个阶段的完整链条（`record` → `create` → 生产运行）：

```bash
# 1. 训练：跑一遍应用，把加载过的类与 profiling 数据写成 preimage
java -XX:AOTMode=record -XX:AOTConfiguration=hello.aotconfig -cp hello.jar Hello

# 2. 组装：加载 preimage、补做链接、写出 final image
java -XX:AOTMode=create -XX:AOTConfiguration=hello.aotconfig -XX:AOTCache=hello.aot -cp hello.jar

# 3. 生产：直接吃 cache
java -XX:AOTCache=hello.aot -cp hello.jar Hello
```

`cds_globals.hpp:105-108` 有一句关键注释：`AOTMode` 等 flag 是 **`-Xshare:dump`、`-XX:SharedArchiveFile`
等经典选项的别名层**（"The following 3 flags are aliases of `-Xshare:dump`, `-XX:SharedArchiveFile=...`,
etc. See `CDSConfig::check_flag_aliases()`"），路径选择由 `ergo_init_aot_paths()` 完成
（`cdsConfig.cpp:623-641`）：preimage 的输出就是 `AOTConfiguration`；final image 的**输入是
`AOTConfiguration`、输出是 `AOTCache`**；生产运行若没给 `AOTCache`，输入退回 `default_archive_path()`。

### Ergonomics Chain of AOT Flags

AOT 的收益依赖一串联动开关，源码把关系写死在 `CDSConfig::check_vm_args_consistency()`
（`cdsConfig.cpp:648-659`）：

```cpp
  if (!FLAG_IS_DEFAULT(AOTMode)) {
    // Using any form of the new AOTMode switch enables enhanced optimizations.
    FLAG_SET_ERGO_IF_DEFAULT(AOTClassLinking, true);
  }

  if (AOTClassLinking) {
    // If AOTClassLinking is specified, enable all AOT optimizations by default.
    FLAG_SET_ERGO_IF_DEFAULT(AOTInvokeDynamicLinking, true);
  } else {
    // AOTInvokeDynamicLinking depends on AOTClassLinking.
    FLAG_SET_ERGO(AOTInvokeDynamicLinking, false);
  }
```

也就是 **`AOTMode` 非默认 → `AOTClassLinking` 自动开 → `AOTInvokeDynamicLinking` 自动开**；反过来手动关掉
`AOTClassLinking` 会连带强制关掉 indy 链接。这正是 JEP 514（Command-Line Ergonomics）想要达成的"用户只写一个
选项"的效果，也是判断"为什么我加了 flag 却没生效"时该先看的地方。

### AOT Linked Classes and Constant Pools

普通 CDS 存的是**解析完但未链接**的 `InstanceKlass`；AOT class linking 存的是链接完成态。落盘的类在载入时若
仍处于未链接状态就无法使用，`classfile/systemDictionaryShared.cpp:457` 有对应的错误串
`"Unlinked class not supported by AOTClassLinking"`。相关实现文件：

| 文件 | 责任 |
| :-- | :-- |
| `cds/aotClassLinker.cpp` | 组装阶段替类完成链接 |
| `cds/aotLinkedClassTable.cpp` | 已 AOT 链接类的索引表 |
| `cds/aotConstantPoolResolver.cpp` | 预解析常量池项（class / field / method / indy） |
| `cds/aotClassInitializer.cpp` | 组装阶段跑 `<clinit>`，把初始化后的对象图交给堆归档 |
| `cds/aotMetaspace.cpp` | AOT 路径下的 Metaspace 分配与加载错误处理 |
| `cds/aotArtifactFinder.cpp` | 按模块/类定位归档中的产物 |

一个可观测的细节：`-XX:AOTInitTestClass=<class>`（develop 级，`cds_globals.hpp:71-73`）允许把指定类
**以已初始化状态**存进 AOT cache，注释直言"for JVM internal testing only"——它是验证"初始化被跳过"这条
语义的内部把手。`-XX:ArchiveHeapTestClass`（`:66`）是同类测试入口，走的是旧 CDS 堆归档路径。

模块系统在启动路径上很贵，因此归档期有专门的优化位：`is_using_optimized_module_handling()` 与
`is_dumping_full_module_graph()` / `is_using_full_module_graph()`（`cdsConfig.hpp:159-201`）。但
**训练阶段会主动关掉它们**：`check_aotmode_record()` 末尾把三者都置 false，注释说得很清楚——VM 退出时
module graph 已被程序状态污染，组装阶段要重建（`cdsConfig.cpp:572-576`）。另外，正在写 full module graph
时会 `FLAG_SET_ERGO(DisableAttachMechanism, true)`（`cdsConfig.cpp:114-125`），也就是**那次 dump 进程不能
被 jcmd attach**。

### Mapped Heap and Streamed Heap

对象图落盘有**两种互斥策略**，由 DIAGNOSTIC flag `-XX:+AOTStreamableObjects` 选择
（`cds_globals.hpp:79`，描述 "Archive the Java heap in a generic streamable object format"）。这是本篇
最有判断价值的一节，因为两者不是"新旧替换"，而是**各有硬约束**。

| 维度 | mapped，默认 | streamed，`+AOTStreamableObjects` |
| :-- | :-- | :-- |
| 核心文件 | `aotMappedHeap{,Loader,Writer}.cpp` | `aotStreamedHeap{,Loader,Writer}.cpp` |
| 落盘形态 | 与目标 GC 布局一致的**镜像**：位图 + 原样对象 | 通用流式对象格式 + 转发（forwarding）表 |
| 头部信息 | `AOTMappedHeapHeader`：`_ptrmap_start_pos` / `_oopmap_start_pos` / `HeapRootSegments` | `AOTStreamedHeapHeader`：`_forwarding_offset` / `_roots_offset` / `_num_roots` / `_num_archived_objects` |
| 位图 | **两张**：`_oopmap` 与 `_ptrmap`（`aotMappedHeap.hpp:54-55`） | **一张**：只有 `_oopmap`（`aotStreamedHeap.hpp:60`） |
| 载入动作 | mmap 进堆地址即完成，`AOTMappedHeapLoader` 维护 `_narrow_oop_base` / `_narrow_oop_shift`（`.cpp:57-59`） | 逐个对象物化（copy + 修引用），`AOTStreamedHeapLoader` 支持迭代/并发（`:813` 的 `is_async`） |
| 大对象限制 | **超过 `MIN_GC_REGION_ALIGNMENT` 的对象不可归档**；region 型收集器还要填 region 间隙 | 无尺寸限制（`HeapShared::is_too_large_to_archive()` 在 streaming 下直接 `return false`） |
| GC 耦合 | 强：依赖 compressed oop 移位基数与 region 对齐，`#include` 了 `g1CollectedHeap.hpp` | 弱：格式与 GC 无关 |
| ZGC | **明确禁止**："Never write mapped heap with ZGC"，会被 ergo 改成 streaming | 允许，且是唯一选择 |
| 并发度控制 | — | `-XX:+AOTEagerlyLoadObjects`（`:82`）关掉并发、同步物化 |

取舍的逻辑因此很清晰：**mapped 快但脆**——它把"载入对象图"变成一次地址映射，代价是归档与写出时的 GC 配置
（压缩指针的 base/shift、region 大小）强绑定，且超大对象进不去；**streamed 通用但要付出物化成本**——格式与
GC 解耦，正好对应 JEP 516 的标题 *Object Caching with Any GC*，任何对象都能进，代价是载入时要逐对象建出来，
于是才有了 `AOTStreamedHeapLoader` 的迭代式/并发加载与 `AOTThread`。

模式选择代码只有几行，但把默认值规则讲完了（`cds/heapShared.cpp:373-388`）：

```cpp
  if (FLAG_IS_DEFAULT(AOTStreamableObjects)) {
    // By default, the value of AOTStreamableObjects should match !UseCompressedOops.
    FLAG_SET_DEFAULT(AOTStreamableObjects, !UseCompressedOops);
  } else if (!AOTStreamableObjects && UseZGC) {
    // Never write mapped heap with ZGC
    if (CDSConfig::is_dumping_archive()) {
      log_warning(cds)("Heap archiving without streaming not supported for -XX:+UseZGC");
    }
    FLAG_SET_ERGO(AOTStreamableObjects, true);
  }
```

注意两点实现细节：默认策略是 **`!UseCompressedOops`**——开压缩指针就走 mapped，关了就 streaming；而这里用
`!FLAG_IS_DEFAULT` 而非 `FLAG_IS_CMDLINE` 做判断，因为 single-command 组装阶段是通过**环境变量把 flag 以
ERGONOMIC 来源传给第二个 JVM** 的（注释在 `:369-372`）。另外 `-XX:+AOTStreamableObjects` 只在**写 cache**
时有意义，在非 dump 进程上指定会被告知 "only used for writing the AOT cache"（`:361-366`）——读取端由归档
文件头部记录的 mode 决定（`HeapShared::initialize_loading_mode()`）。

与压缩指针/对象编码相关的背景见 [Object_Header](/docs/CS/Java/JDK/JVM/Object_Header.md)，
ZGC 侧的加载屏障约束见 [ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC.md)。

### AOTThread

`cds/aotThread.hpp:31-49` 的类注释一句话概括了它的存在理由：**"A hidden from external view JavaThread for
materializing archived objects"**。它是一个真正的 `JavaThread` 子类，但对所有外部视角隐身
（`is_hidden_from_external_view()` 返回 `true`），入口是静态的 `aot_thread_entry`，并提供
`materialize_thread_object()`。

为什么对象物化需要一个"Java 线程"而不是 VM thread：物化过程可能执行 Java 语义（例如需要 `JavaThread` 上下文的
句柄、锁、以及线程本地分配）。而对外部隐身，则是避免这个纯内部线程出现在线程枚举、`jcmd Thread.print`、
MXBean 之类观察面上，被应用误读成一个多出来的业务线程。

## AOT Method Code

### Training and Replay Model

方法级 AOT 是**训练-回放**模型，载体是两个 DIAGNOSTIC flag：`-XX:+AOTRecordTraining`（"Request output of
training data for improved deployment"）与 `-XX:+AOTReplayTraining`（"Read training data, if available, for
use in this execution"），`cds_globals.hpp:141-145`。数据结构的读/写判定直接绑在这两个 flag 上
（`oops/trainingData.hpp:286-287`）：

```cpp
  static bool have_data() { return AOTReplayTraining;  } // Going to read
  static bool need_data() { return AOTRecordTraining;  } // Going to write
```

三个开关**不是让用户手调的，而是按阶段 ergo 设定**，全在 `CDSConfig::setup_compiler_args()`
（`cdsConfig.cpp:734-758`）。前置条件一行写完："AOT profiles and AOT-compiled code are supported only in the
JEP 483 workflow"：`can_dump_profile_and_compiled_code = AOTClassLinking && new_aot_flags_used()`。

| 阶段判定 | Record | Replay | AOT code 生成 |
| :-- | :-- | :-- | :-- |
| 训练（preimage） | `true` | `false` | `AOTCodeCache::disable_caching()`——训练跑时不产 AOT code |
| 组装（final image） | `false` | `true` | `enable_caching()` + `disable_dumping_aot_code()`——先生成，等元数据与堆落盘后再写 |
| 生产（用 cache） | `false` | `true` | `enable_caching()` |
| 其它（经典 CDS 等） | `false` | `false` | `disable_caching()` |

所以典型现象是：**只给 `-XX:AOTCache=hello.aot` 生产运行时，`AOTReplayTraining` 自动是 true**，不需要显式
指定；而 `-XX:+AOTPrintTrainingInfo`（`:147`）与 `-XX:+AOTVerifyTrainingData`（`:150`，debug build 默认
true）是排障把手。`-XX:+AOTCompileEagerly`（`:153`，**EXPERIMENTAL**）配合组装阶段"尽早编译"，注释就一句
"Compile methods as soon as possible"。

顺带说明 dump 期与执行模式的一处交互：组装阶段提交的是**非阻塞**编译请求并等全部完成，若用户加了 `-Xcomp`
会逐条阻塞、反而拖慢测试，因此会把执行模式切回 mixed（`cdsConfig.cpp:664-670`）。

### AOT Code Cache Entries

`share/code/aotCodeCache.hpp:33-38` 的文件级注释是整个子系统的定义：

```cpp
/*
 * AOT Code Cache collects code from Code Cache and corresponding metadata
 * during application training run.
 * In following "production" runs this code and data can be loaded into
 * Code Cache skipping its generation.
 */
```

它缓存的是**普通 Code Cache 里的代码及其元数据**，条目类型由一个 X-macro 枚举定义
（`aotCodeCache.hpp:53-59`），照此可判断"哪些东西值得进 cache"：

| `AOTCodeEntry::Kind` | 含义 |
| :-- | :-- |
| `None` | 空槽 |
| `Adapter` | i2c / c2i adapter 桩，受 `-XX:+AOTAdapterCaching` 控制（"Enable saving and restoring i2c2i adapters"） |
| `SharedBlob` | runtime stub / shared code blob，受 `-XX:+AOTStubCaching` 控制 |
| `C1Blob` | C1 编译的 nmethod |
| `C2Blob` | C2 编译的 nmethod |
| `StubGenBlob` | StubRoutines 生成器的产物 |

条目描述符里两个字段能说明"跨进程恢复代码"的难点：`_id` 复用为 adapter id、stub 的
`vmIntrinsic::ID` 或 nmethod 的名字 hash（`:74`），而 `_dumptime_content_start_addr` 记录 dump 时代码起始地址、
**专门用于载入时应用重定位**（`:81` 注释 "used for applying relocations"）。这也解释了
`-XX:+AOTCacheParallelRelocation`（`cds_globals.hpp:136`，**默认 true**，"Use parallel relocation code to speed
up startup"）存在的意义：cache 里的机器码不是原样可用，得先按新地址搬迁。

## Final Image Recipes

`cds/finalImageRecipes.cpp` 是**训练阶段与组装阶段之间的传递通道**，头文件注释把角色说得非常直白
（`finalImageRecipes.hpp:37-44`）：

```cpp
// This class is used for transferring information from the AOTConfiguration file (aka the "preimage")
// to the JVM that creates the AOTCache (aka the "final image").
//   - The recipes are recorded when CDSConfig::is_dumping_preimage_static_archive() is true.
//   - The recipes are applied when CDSConfig::is_dumping_final_static_archive() is true.
// The following information are recorded:
//   - The list of all classes that are stored in the AOTConfiguration file.
//   - The list of all classes that require AOT resolution of invokedynamic call sites.
```

为什么需要"菜谱"这一层：preimage 只能记录**加载过什么**，而组装 JVM 要把这些类一路推到"已链接、常量池已
预解析、`<clinit>` 已执行"的状态，就必须知道**训练时每个常量池项到底解析成了什么**。`FinalImageRecipes`
存的正是这份逐类清单：`_all_klasses` 是要整体搬进 final image 的类数组，`_cp_recipes` 与每个类一一对应、
列出训练期被解析过的 class / field / method / indy 的 CP 下标，`_flags` 记附加信息（`:50-57`）。
四个标志位直接对应启动路径上四类昂贵操作：

| 标志位 | 值 | 含义 |
| :-- | :-- | :-- |
| `CP_RESOLVE_CLASS` | `0x1 << 0` | CP 里有预解析的 class 项 |
| `CP_RESOLVE_FIELD_AND_METHOD` | `0x1 << 1` | CP 里有预解析的字段 / 方法项 |
| `CP_RESOLVE_INDY` | `0x1 << 2` | CP 里有预解析的 invokedynamic 项 |
| `WAS_INITED` | `0x1 << 3` | 该类在训练运行中被初始化过 |

两侧的入口函数名就是它的工作方式：record 侧 `record_recipes()` → `record_all_classes()` +
`record_recipes_for_constantpool()`，apply 侧 `apply_recipes()` → `load_all_classes()` +
`apply_recipes_for_constantpool()`（`:63-79`）。采集是纯顺序遍历：对每个 `InstanceKlass` 扫常量池，命中
`JVM_CONSTANT_Class` 且 `resolved_klass_at()` 有值就记一条并置 `CP_RESOLVE_CLASS`，若 `ik->is_initialized()`
则置 `WAS_INITED`，再遍历 `ConstantPoolCache` 的 `resolved_field_entries()` 判断 `getstatic` / `putstatic`
是否已解析（`.cpp:63-93`）。对象本身由 `ArchiveBuilder::current()->ro_region_alloc()` 分配到归档只读区
（`.cpp:43-45`），所以菜谱也是归档的一部分。

一处容易误解的点：`record_recipes_for_constantpool()` 开头的注释说明**菜谱是无条件记录的**，不管
`is_dumping_{invokedynamic,dynamic_proxies,reflection_data}()` 是否开启；开关没开时，对应部分的菜谱在组装期
被忽略（`.cpp:55-57`）。

**与 jlink final image 的关系要划清边界**：HotSpot 侧看到的接口只有"preimage 文件 → final image 文件"这一对
（由 `AOTConfiguration` 与 `AOTCache` 指定，`ergo_init_aot_paths()`，`cdsConfig.cpp:623-641`），加上
`CDSConfig::get_status()` 导出给 `jdk.internal.misc.CDS.getCDSConfigStatus()` 的六个状态位
（`cdsConfig.hpp:82-90`）。把 cache 与运行时镜像打包成可分发产物的工具链在 `jdk.jlink` 一侧，而**本机源码树只
有 `src/hotspot`，没有 jlink 的 Java 源码**，因此本篇不复述 jlink 的选项名与打包步骤，只认定一点：
VM 侧的 final image 就是 `-XX:AOTMode=create` 的产物文件，不是一种独立的运行时格式。

## Boundaries and Division of Labor

### Flag Combination Boundaries

**`-Xshare` 与 `-XX:AOTMode` 互斥**，这是源码里写明的设计约束。`cdsConfig.cpp:83-87` 的注释：

```cpp
    // Note: -Xshare and -XX:AOTMode flags are mutually exclusive.
    // - Classic workflow: -Xshare:on and -Xshare:dump cannot take effect at the same time.
    // - JEP 483 workflow: -XX:AOTMode:record and -XX:AOTMode=on cannot take effect at the same time.
    // So we can never come to here with RequireSharedSpaces==true.
```

实现上靠两条线兜住：

- `CHECK_NEW_FLAG(AOTCache / AOTCacheOutput / AOTConfiguration / AOTMode)`（`cdsConfig.cpp:435-439`），配套
  注释 "New AOT flags must not be mixed with classic CDS flags such as -Xshare:dump"；四个新 flag 还各自
  只允许一个路径（`CHECK_SINGLE_PATH`，`:441-443`）。
- 一旦用到任一 AOT flag，`_new_aot_flags_used = true`（`:476`），路径初始化就走
  `ergo_init_aot_paths()` 而不是 `ergo_init_classic_archive_paths()`（`:98-104`）。

其余边界条件：

| 组合 | 结果 | 证据 |
| :-- | :-- | :-- |
| `AOTCache` 与 `AOTCacheOutput` 同时给 | 直接退出："Only one of AOTCache or AOTCacheOutput can be specified" | `cdsConfig.cpp:462-464` |
| `AOTMode=record` 加 `AOTCache` | 退出："AOTCache must not be specified when using -XX:AOTMode=record" | `:561-563` |
| `AOTMode=create` 但 `AOTConfiguration` 不是合法 preimage | 退出："Must be a valid AOT configuration generated by the current JVM" | `:606-608` |
| `AOTMode=auto/on` 加 `AOTConfiguration` | 退出："AOTConfiguration can only be used with when AOTMode is record or create" | `:496-499` |
| 没给 `AOTCache` 却开 `AOTAdapterCaching` / `AOTStubCaching` | 被忽略，debug 日志记一条 | `:445-450` |
| 动态归档 + `AOTClassLinking` | 不支持，ergo 关闭并 `log_warning(cds)` | `prepare_for_dumping()`，`cdsConfig.cpp:764-769` |
| 训练 / classic dump 时 | `UseSharedSpaces = false`，为 sanity 全部从 class 文件重新解析 | `ergo_initialize()`，`cdsConfig.cpp:82-94` |
| 组装阶段 | 所有 JVMTI agent 被禁用 | `cdsConfig.cpp:612-620` |

### Size Limits and Failure Behavior

`-XX:AOTCodeMaxSize` 默认 **10 MB**（`cds_globals.hpp:164`，DIAGNOSTIC，range 从 `1*M` 到
`CODE_CACHE_SIZE_LIMIT`）。实际使用上限会按分配粒度对齐（`code/aotCodeCache.cpp:246-249`）。满了之后
**不抛错、不退出**，只在写条目时告警并跳过该项：

```cpp
    log_warning(aot,codecache)("Failed to ensure %d bytes at offset %d in AOT Code Cache. Increase AOTCodeMaxSize.",
```

（`aotCodeCache.cpp:719`；写入路径的同类告警在 `:741`；debug build 另有 `:874` 的 size assert。）
更宏观的兜底来自 `-XX:+AbortVMOnAOTCodeFailure`（`cds_globals.hpp:168`）的描述：**默认 VM 会在缺少 AOT code
时继续正常执行**。也就是说 AOT code 是纯增益项，装不下就退回 JIT 路径，不会因此启动失败——排障时应当
`-Xlog:aot,codecache` 看告警，而不是猜"为什么没变快"。

### Division of Labor with Sibling Notes

本篇只管"把启动成果落盘再复用"这条主线，相邻机制各自有主页：

| 主题 | 去处 |
| :-- | :-- |
| VM 启动流程本身（`create_vm` 各阶段与顺序） | [Start](/docs/CS/Java/JDK/JVM/start.md) |
| 类加载器委派、解析与 `SystemDictionary` | [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md) |
| `InstanceKlass` 与 Metaspace 分配（归档搬迁的落点） | [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md) |
| 机器码放回后与 Code Cache 的关系 | [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md) |
| 未命中 AOT 时的执行路径：解释器、编译器与执行引擎入口 | [interpreter](/docs/CS/Java/JDK/JVM/interpreter.md) / [JIT](/docs/CS/Java/JDK/JVM/JIT.md) / [ExecutionEngine](/docs/CS/Java/JDK/JVM/ExecutionEngine.md) |

## Links

- [Start](/docs/CS/Java/JDK/JVM/start.md)
- [ClassLoader](/docs/CS/Java/JDK/JVM/ClassLoader.md)
- [Metaspace](/docs/CS/Java/JDK/JVM/Metaspace.md)
- [ExecutionEngine](/docs/CS/Java/JDK/JVM/ExecutionEngine.md)
- [JIT](/docs/CS/Java/JDK/JVM/JIT.md)
- [CodeCache](/docs/CS/Java/JDK/JVM/CodeCache.md)

## References

- [JEP 483: Ahead-of-Time Class Loading & Linking](https://openjdk.org/jeps/483)
- [JEP 514: Ahead-of-Time Command-Line Ergonomics](https://openjdk.org/jeps/514)
- [JEP 515: Ahead-of-Time Method Profiling](https://openjdk.org/jeps/515)
- [JEP 516: Ahead-of-Time Object Caching with Any GC](https://openjdk.org/jeps/516)
- [Class Data Sharing - JVM Tools and Tuning Guide](https://docs.oracle.com/en/java/javase/27/vm/class-data-sharing.html)
