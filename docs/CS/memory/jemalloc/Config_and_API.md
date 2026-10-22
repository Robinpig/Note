## Introduction

jemalloc 的"配置"不是一张统一的表。同一个旋钮在三个不同时刻被决定：**编译期**决定它存不存在（`config.*`），**启动期**决定它取什么值（`opt.*`），**运行期**只允许改少数被显式打开的口子（`arena.<i>.dirty_decay_ms`、`thread.arena`、`prof.*` 之类）。把这三层混为一谈，就会出现"我在 `MALLOC_CONF` 里改了 `dirty_decay_ms` 却对 mallctl 无效"或者"我调 `opt.dirty_decay_ms` 想它生效"这类错位。

API 面同理：`mallocx` 那一族看起来是七套接口，实际上只有**一个分配核心** `imalloc`。flags 不是模式开关，而是把原本藏在默认值里的四个决策——对齐、清零、tcache、arena——搬到调用点上；`x` 变体则是在此之上表达"原地调整"与"尽力而为"。基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。

## Three Lifetimes of a Setting

三层的分界写在 ctl 树的形状里，不在文档说明里：

- `config.*` 是编译期常量，读都走 `CTL_RO_NL_CGEN`（src/ctl.c:2259-2291）。节点列表见 ctl.c:478-489：`config.debug`、`config.fill`、`config.prof`、`config.stats`、`config.infallible_new`……**它们连启动期都改不了**，只能重新编译。
- `opt.*` 是启动期结果的**只读投影**，全部由 `CTL_RO_NL_GEN` 生成（ctl.c:2199-2295）。`opt.dirty_decay_ms`、`opt.hpa`、`opt.experimental_pac_sec_nshards` 都在这里，节点表见 ctl.c:496-566。写入 `opt.anything` 一律 `EPERM`。
- 真正可在运行期改的，是另一套名字：`arena.<i>.dirty_decay_ms` 与 `arena.<i>.muzzy_decay_ms` 走同一个实现（ctl.c:2935-2976），`arena.<i>.purge` / `.decay` 触发回收（ctl.c:2691-2754），`thread.arena` 把线程迁到另一个 arena（ctl.c:2312-2366）。

`5.4.0` 恰好提供了一个反面教材：tcache 的容量控制从"固定参数"改成"按 bin 自适应"，于是七个旧旋钮——`lg_tcache_nslots_mul`、`tcache_nslots_small_min`、`tcache_nslots_small_max`、`tcache_nslots_large`、`tcache_gc_delay_bytes`、`lg_tcache_flush_small_div`、`lg_tcache_flush_large_div`——被整体移除（ChangeLog:33-41）。移除的方式很能说明这三层的差别：

- 写在 `MALLOC_CONF` 里**不报错**，因为 `conf_error` 对这七个名字直接返回（src/conf.c:227-239，"Silently tolerate deprecated features"）。
- 用 mallctl 读 `opt.lg_tcache_nslots_mul` 会得到 `ENOENT`，因为 `opt_node[]` 里已经没有这个节点（ctl.c:496-566）。
- 替代品 `tcache_ncached_max` 保留（ChangeLog:40-41）。

也就是说：**同一个"选项已被删除"，配置文件路径静默忽略、mallctl 路径明确报错**。写监控或迁移脚本时，只有后者能被发现。

## Five Sources, One Parse Order

`malloc_conf` 有五个来源（conf.c:302-303 的 `MALLOC_CONF_NSOURCES 5`），按固定顺序读取（conf.c:319-392，说明文字见 conf.c:422-430）：

| 序号 | 来源 |
| :--- | :--- |
| 0 | 编译进二进制的 `--with-malloc-conf` |
| 1 | 全局变量 `malloc_conf` 指向的字符串 |
| 2 | `/etc/malloc.conf` 符号链接的**名字** |
| 3 | 环境变量 `MALLOC_CONF` |
| 4 | 全局变量 `malloc_conf_2_conf_harder` |

解析是从 0 到 4 顺序进行的，**后解析到的覆盖先解析到的**（conf.c:435-451）。注意第 2 项读的是 `readlink` 的结果而不是文件内容（conf.c:346-359）——所以"配置文件"其实是一串写在链接名里的选项，这也意味着它不会引入文件读取失败的分支。

环境变量这一路走 `jemalloc_getenv`，优先 `secure_getenv`，退路是 `issetugid()` 检查后调 `getenv`（conf.c:25-41）。**setuid 程序里 `MALLOC_CONF` 会被忽略**，这是安全边界而不是 bug。

解析本身分两遍（conf.c:1155-1171）：第一遍只取 `confirm_conf` 并把五个来源的字符串缓存下来，第二遍才真正处理选项。`confirm_conf` 因此能让 jemalloc 把"每个来源解析出了什么"逐条打印，包括来源编号与解释文字（conf.c:441-467）。这在排查"到底哪个来源赢了"时是唯一可靠的手段。

错误处理有两条特殊规则：

- 键名以 `experimental_` 开头时，坏值**静默容忍**（conf.c:219-226）。
- 其他坏值记入 `had_conf_error`，默认只打印；只有 `abort_conf:true` 才在全部选项处理完后中止（conf.c:241-245、:1132-1134）。

顺序还受一条硬依赖约束：初始化必须**先 `sc_boot`、再 `malloc_conf_init`、最后 `sz_boot` 与 `bin_info_boot`**。源码注释说明原因是"任何 slab 尺寸调整都必须在 `sz_boot`/`bin_info_boot` 之前完成，因为它们假定从 `sc_data_global` 读到的值已是最终值"（src/jemalloc_init.c:165-188）。**配置能改变尺寸类，所以它必须跑在尺寸类初始化之前**——这条顺序错了就是静默地用错尺寸。

## mallctl Is a Typed Tree, Not a Switch

所有 mallctl 名字都挂在同一棵静态树上。根节点只有十几个分支（ctl.c:953-966）：

```c
static const ctl_named_node_t root_node[] = {{NAME("version"), CTL(version)},
    {NAME("epoch"), CTL(epoch)},
    {NAME("background_thread"), CTL(background_thread)},
    ...
    {NAME("arena"), CHILD(indexed, arena)},
    {NAME("arenas"), CHILD(named, arenas)}, {NAME("prof"), CHILD(named, prof)},
    {NAME("stats"), CHILD(named, stats)},
    ...
```

节点分两种：`CTL(...)` 是叶子，直接对应一个处理函数；`CHILD(...)` 是子树。`arena` 是**索引节点**，下一段必须是数字；其余是命名节点，下一段必须是固定字符串（ctl.c:436-446 的 `NAME`/`CHILD`/`CTL`/`INDEX` 宏）。三种入口最终都归到同一处：`ctl_byname` 走名字、`ctl_nametomib` 把名字翻译成 MIB、`ctl_bymib` 直接用 MIB 查（ctl.c:1669-1768）；名字查到一半就停（"partial MIB"）时返回 `ENOENT`（ctl.c:1769-1772）。

树的结构决定了几个容易踩的语义：

- **MIB 是稳定的，名字不是**：`mallctlnametomib` 一次解析后缓存 MIB，后续 `mallctlbymib` 就绕开字符串比较，这也是高频读 stats 的推荐做法。
- `stats.arenas.<i>.*` 的 `<i>` 可以是 `MALLCTL_ARENAS_ALL`，也可以是被标记为 deprecated 的 `narenas` 下标；两者都由 `ctl_arena_ind_is_all` 判定（ctl.c:1002-1015），并且注释写明"新代码应使用 `MALLCTL_ARENAS_ALL`"。
- 整个 ctl 状态由一把 `ctl_mtx` 保护，Arena 数量还会在运行期增长，所以读 `narenas` 必须持锁（ctl.c:1017-1026）。

## The Four-Argument Protocol

`mallctl(name, oldp, oldlenp, newp, newlen)` 的四个参数没有统一语义，具体行为由每个叶子自己选。所有叶子都通过四个小函数之一来声明自己的性别（ctl.c:1888-1949）：

| 辅助函数 | 语义 | 违约返回 |
| :--- | :--- | :--- |
| `ctl_read` | 只读；`oldlen` 与源长度不符时复制 `min` 并回报实际长度 | `EINVAL` |
| `ctl_write` | 只写；`newp == NULL` 视为空操作 | `EINVAL` |
| `ctl_writeonly` | 只写；传了 `oldp`/`oldlenp` | `EPERM` |
| `ctl_readonly` | 只读；传了 `newp`/`newlen` | `EPERM` |
| `ctl_neither_read_nor_write` | 是动作而非查询，四个参数都得空 | `EPERM` |

三个细节值得记：

1. **长度不符不是失败**。`ctl_read` 会把源数据截断到调用方给的缓冲区，把真实长度写回 `*oldlenp`，然后返回 `EINVAL`（ctl.c:1911-1916）。所以"先传 0 长度问大小"这个惯例在 jemalloc 里能用——只要接受返回码是错误而不是成功。
2. **写 `NULL` 常常是合法的**。`ctl_write` 在 `newp == NULL` 时直接返回 0（ctl.c:1924-1926），于是 `mallctl("arena.0.purge", NULL, NULL, NULL, 0)` 这类"纯触发"调用成立。
3. **`epoch` 是刷新开关**。写一次 `epoch` 会调 `ctl_refresh`，然后读出新的 epoch 值；只读则只返回当前计数（ctl.c:2061-2077）。`stats.*` 本身**不会**顺手刷新，[Decay and Purge](/docs/CS/memory/jemalloc/Decay_and_Purge.md) 里讲的"快照"语义就是这条规则的结果。

`ctl_refresh` 做的是把每个 arena 的计数合并进 `ctl_sarena`，再算出一组派生值（`allocated`、`active`、`metadata`、`resident`、`retained`、`pinned`……），最后 `epoch++`（ctl.c:1403-1497）。它持 `ctl_mtx` 全程，并且先把汇总项清零再重算（ctl.c:1417-1421）——所以两次 `epoch` 之间看到的是同一份快照，而不是逐字段的实时值。

## stats_print Is a mallctl Client

`malloc_stats_print` 没有任何旁路。它自己先调一次 `mallctl("epoch", ...)` 强制刷新，注释写得很直白："Refresh stats, in case mallctl() was called by the application"（src/stats.c:107-129）。之后才进入 5.4 重构出来的两段式：

- **gather**：通过 mallctl 把各段读进带类型的结构体，注释强调"把 mallctl 读集中放置、与输出分离，使覆盖面可审计"（stats.c:173-178）。
- **emit**：同一个 `emitter_t` 按 `json` 开关选择 JSON 或表格输出（stats.c:145-168）。

选项字符串不另立门户，它和 `malloc_conf` 里的 `stats_print_opts` 共用一张 `STATS_PRINT_OPTIONS` 表：conf.c 用它校验字符合法性（conf.c:43-60），stats.c 用它把字符映射成布尔开关（stats.c:131-143）。**非法字符直接被忽略**，不报错。

发布构建里输出还包了一层 64 KiB 的 `buf_writer`（src/jemalloc.c:2051-2070），这样每个字段不必各发一次 `write_cb`。`config_debug` 下则直连回调，便于断点观察。

## The mallocx Family Is One Core With Explicit Knobs

flags 的编码方式决定了"默认"必须是**数值 0**，所以每个字段都做了偏置：

```c
#define MALLOCX_TCACHE(tc)	((int)(((tc)+2) << 8))
#define MALLOCX_ARENA(a)	((((int)(a))+1) << 20)
```

（include/jemalloc/jemalloc_macros.h.in:24-33，源码注释逐字说明了偏置的理由）。加上偏置后，tcache 字段 0 表示自动、1 表示禁用（`MALLOCX_TCACHE(-1)`），arena 字段 0 表示自动选择。于是 `je_mallocx` 的主路径就是 `if (unlikely(flags != 0))`：非零才解码对齐、清零、tcache、arena 四项（src/jemalloc.c:1429-1434），然后统一进 `imalloc(&sopts, &dopts)`（jemalloc.c:1436）。`mallocx` 不是另一条分配路径，它只是把 `malloc` 隐含的默认值显式化了。

几个 `x` 变体的语义差别不在实现，而在**承诺**：

- `xallocx(ptr, size, extra, flags)` 是"原地调整，改不动就原样返回"。它先反查 `old_usize`，把 `extra` 截断到 `SC_LARGE_MAXCLASS - size`，再调 `ixalloc`；返回的是**最终 usable size**，失败时就是旧值（jemalloc.c:1769-1851）。它还有一条断言：调整前后 `emap_edata_lookup` 必须返回**同一个 `edata_t` 对象**（jemalloc.c:1787-1793、:1826-1831）——内容可以变，对象不能换。
- `rallocx(ptr, size, flags)` 是"要搬就搬"，内部走 `do_rallocx` 后再可能落到 `iralloct`（jemalloc.c:1585-1591、:1490）。
- `sallocx` 只读尺寸；debug 或 `force_ivsalloc` 时用 `ivsalloc`（任意指针安全检查），否则用 `isalloc`（依赖指针有效）——这正是 [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md) 里 dependent 读的两种用法（jemalloc.c:1853-1877）。
- `nallocx` 只算不分配，`SC_LARGE_MAXCLASS` 之上返回 0（jemalloc.c:1962-1985）。

`realloc(ptr, 0)` 这个历史雷区被显式建模成三选一：`zero_realloc:alloc` 相当于 `malloc(1)`（并强制关掉 tcache 以拿到真正的 first fit）、`free` 相当于释放并返回 NULL、`abort` 直接触发安全检查失败（jemalloc.c:1593-1632）。**默认行为不是"未定义"，而是由 `opt_zero_realloc` 决定的确定动作**。

## fork Is a Global Lock-Order Exercise

fork 之后子进程只保留调用线程，其余线程可能正持着 allocator 的锁——所以 jemalloc 在 fork 前把**所有**锁按序拿住。注册发生在初始化阶段的 `malloc_init_hard_recursible`，通过 `os_process_register_atfork` 挂三个回调（src/jemalloc_init.c:350-368）。

`jemalloc_prefork` 的获取顺序是：ctl → tcache → arenas 管理 → 后台线程 → prof →（再到）每个 arena 的九个阶段，外层循环九轮、内层遍历所有 arena（src/jemalloc_fork.c:57-113）。**同一阶段跨所有 arena 走完再进下一阶段**，这样锁序与 arena 下标无关，也不会出现 A 的 stage2 与 B 的 stage1 交叉。父子进程的 postfork 按**逆序**释放（jemalloc_fork.c:140-157）。`witness_prefork` / `witness_postfork_*` 还顺手把锁序追踪表本身切到对应状态（jemalloc_fork.c:61、:140、:168）。

这套设计的一个直接后果是：**fork 期间分配会被拖住**。jemalloc 没有做"fork 期间降级为无锁"的魔法，代价就体现在这里。

## What 5.4 Changed on This Surface

`5.4.0`（Sep 17, 2026）的 ChangeLog 明确说这一版以技术债清理为主，超过 160 个提交（ChangeLog:7-12）。与配置/API 面直接相关的有几项：

- **新增 pinned extent 的可观测性**：`EXTENT_ALLOC_FLAG_PINNED` 让自定义 extent hook 能标记不可回收映射，并配套 `stats.pinned`、`stats.arenas.<i>.pinned`、`stats.arenas.<i>.extents.<j>.npinned`、`.pinned_bytes` 与 `mutexes.extents_pinned.{counter}`（ChangeLog:14-22）。
- **`thread.arena` 支持恢复 per-CPU 选择**：把线程设到 auto 范围内表示"交还给 per-CPU 管理"，源码注释解释了为什么没有这条就再也回不去（ctl.c:2340-2356）。
- **tcache 策略改为按 bin 自适应**，七个旧旋钮移除（ChangeLog:33-41，细节见上文"三层生命周期"）。
- **`experimental_infallible_new` 从运行期选项变成编译期 `--enable-cxx-infallible-new`**（ChangeLog:27-30）——又一个"配置从运行期升到编译期"的例子，`config.infallible_new` 节点因此存在（ctl.c:481）。
- **前端模块化**：arena 管理、初始化、fork 编排、分配分发从 `jemalloc.c` 拆了出去（ChangeLog:63-68），对应 `arenas_management.c`、`jemalloc_init.c`、`jemalloc_fork.c`、`malloc_dispatch.c` 这些文件。本篇引用的 `jemalloc_init.c` / `jemalloc_fork.c` 就来自这次拆分。
- **页分配边界去掉 PAI vtable**，改为直接调 PAC/HPA（ChangeLog:78-81）。这解释了为什么 [Page Allocator](/docs/CS/memory/jemalloc/Page_Allocator.md) 里 `pa_alloc` 是两条 `if` 而不是函数指针表。
- **背景线程睡眠改用 `CLOCK_MONOTONIC`**，防止时钟回拨导致停顿（ChangeLog:99-101）。

另有一条容易误解的兼容性说明：旧版 `pai_t` 抽象虽然删了，但 `edata_pai_get` 仍在用——`pa_dalloc` 依旧按它把释放路由回 HPA 或 PAC。**"抽象层删了"不等于"概念没了"**。

## Version and Verification Notes

- 全部 `路径:行号` 按 jemalloc `5.4.0` 本地树核对。本机树无 autoconf 生成物（`jemalloc_internal_defs.h` 缺失），因此 `config_*` 宏、`PAGE`、`SC_*` 的实际取值无法验证；本篇只使用源码里能直接读到的结构、顺序与字面常量。
- 五个配置来源的顺序、`secure_getenv` 退化路径、两遍解析、`experimental_` 与 deprecated 键的静默规则，均逐行读过 conf.c；未在运行中的进程里实测过优先级，结论是**读代码所得**。
- `epoch` 刷新、`stats_print` 内部先调 `mallctl("epoch")`、四个 `ctl_*` 辅助函数的返回码，均为源码级事实；没有在没有构建产物的情况下跑过 mallctl 调用序列。
- 5.4 的变更条目全部来自仓库内 `ChangeLog:7-110`，未引用任何外部 release note。ChangeLog 里给出的提交短哈希保持原样，未做核验。
- `MALLOC_CONF` 里被移除的七个 tcache 选项"静默忽略"来自 `conf.c` 的 `deprecated[]` 名单，与 ChangeLog:39-40 的描述一致；两者的对应关系是本篇的推断，源码没有把这两处显式关联起来。

## Links

- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Page Allocator](/docs/CS/memory/jemalloc/Page_Allocator.md)
- [Decay and Purge](/docs/CS/memory/jemalloc/Decay_and_Purge.md)
- [Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md)
- [Arena Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)

## References

- [jemalloc](https://jemalloc.net/)
- [jemalloc manual page](https://jemalloc.net/jemalloc.3.html)
- [jemalloc source repository](https://github.com/jemalloc/jemalloc)
