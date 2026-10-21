## Introduction

`free()` 把对象还给 arena，和把内存还给操作系统，是两件相隔很远的事。中间那条流水线要回答三个彼此独立的问题：**该留下多少**（decay 模型）、**由谁在什么时候来问**（ticker 与背景线程）、**"还"这个动作在系统调用层面是什么**（purge 的状态阶梯）。本篇按这三个维度展开，每一处断言都可回到 jemalloc `5.4.0` 树的 `路径:行号`。

一条容易被忽略的结构性事实：这条流水线**和分配路径共享的数据只有页数**。`decay_t` 自己说得很清楚——"基本上是单线程数据结构，完全不关心同步；同步由调用方自理"（`include/jemalloc/internal/decay.h:16-24`），唯一可无锁读的字段是当前设置值。所以"jemalloc 归还内存慢"从来不是锁竞争问题，而是它的模型本来就是**按时间分布的加权平均**，不是倒计时。

## Three States Between Heap and OS

PAC 手里有四个 ecache（`include/jemalloc/internal/pac.h:120-123`），每个装同一种状态的 extent：

| 状态 | 含义 | 是否仍占 RSS | 是否仍占 VSZ |
| :--- | :--- | :--- | :--- |
| `dirty` | 释放了、内容还留着 | 是 | 是 |
| `muzzy` | 已 `MADV_FREE`，内核可随时回收 | 视内核而定 | 是 |
| `retained` | 已 decommit 或 forced purge | 否 | 是 |
| `pinned` | 5.4 新增，标记为不可回收 | 是 | 是 |

"retained 技术上仍是 mapped，但从 `pac_mapped` 里排除；pinned 与之相反，计入 `pac_mapped`"——这段注释（pac.h:73-92）解释了为什么 `stats.arenas.<i>.mapped` 与 RSS 的差值不能直接当碎片读。

关键默认值：**muzzy 这一级默认不存在**。`MUZZY_DECAY_MS_DEFAULT` 是 `(0)`，`DIRTY_DECAY_MS_DEFAULT` 是 `ZD(10 * 1000)`（`include/jemalloc/internal/arena.h:30-32`）。于是 `pac_decay_stashed` 里 `try_muzzy = !fully_decay && pac_decay_ms_get(pac, extent_state_muzzy) != 0`（`src/pac.c:610-611`）默认即为假，dirty 直接跳到彻底归还那一档。想让页面先"变模糊"再消失，必须显式打开 `muzzy_decay_ms`。

## The Decay Curve Is a Table, Not a Timer

`decay_t` 只有一个字段是用户设定的：`time_ms`，注释写成"从一批未用脏页产生，到等量的一批被 purge 或复用，所经过的近似毫秒数"（decay.h:34-39）。其余全是推导件：

```
interval = time_ms / SMOOTHSTEP_NSTEPS        /* src/decay.c:32-36 */
deadline = epoch + interval + jitter          /* src/decay.c:15-27 */
npages_limit = sum(backlog[i] * h_steps[i]) >> 24   /* src/decay.c:95-109 */
```

`h_steps` 来自一张预生成的表：变体 `smoother`、200 段、24 位定点（`include/jemalloc/internal/smoothstep.h:26-28`），文件头写明生成命令 `sh smoothstep.sh smoother 200 24 3 15`（:5-7），曲线是 `6x^5 - 15x^4 + 10x^3`（:19-20）。表的目的是"避免浮点运算"（:12-14）；注意它和 `fxp.h` 的 16.16 定点毫无关系，别把两套定点混为一谈。

默认 10s 配 200 段，一个 epoch 是 **50ms**。而曲线的首尾值差得很悬殊：`h_steps[1] = 0x14`，除以 2^24 只有 4.8e-4；`h_steps[100] = 0x800000`，正好 0.5（smoothstep.h:31, :130）；到 `h_steps[200] = 0x1000000` 才满 1（:230）。也就是说一批脏页在其产生的**第一个 epoch 里几乎没有被回收的义务**，衰减几乎全部发生在后半程。这正是 `decay_t.npages_limit` 与 `backlog` 的设计动机（decay.h:60-82），而不是某个定时器。

## Epochs Advance in Bulk, and Jitter Keeps Arenas Apart

推进发生在 `decay_maybe_advance_epoch`（`src/decay.c:176-209`）：deadline 未到就直接返回；到了则一次算出跨了几段（`nadvance_u64 = delta / interval`），epoch **按 interval 的整数倍**前进，backlog 用 `memmove` 整体左移，超过 200 段就把前 199 项清零（:119-121）。注释明确承认这种粗糙："我们不等到 epoch 真正开始才推进，因为调度和计算延迟；甚至可能完全跳过若干个 epoch。无论哪种情况，推进时把所有相关活动并入最近记录的那个 epoch"（decay.h:42-49）。

`nunpurged` 是这套合并语义的支点：它记的是"本 epoch 开始时、按 policy 认可保留的页数"，取 `max(npages_limit, current_npages)`（:204-206），下一轮用 `current_npages - nunpurged` 反推新增脏页（:135-138）。由此得到一条对读 stats 很重要的推论，写在 PAC 侧：

> "本 epoch 期间产生的脏页要到未来的 epoch 才受 purge 约束，因此 purge 只发生在 epoch 推进时，或由后台线程（调度事件）触发。"（`src/pac.c:762-768`）

deadline 抖动是**每 arena 独立**的：`jitter_state` 的种子就是 `decay_t` 自身的地址（`src/decay.c:39`），抖动量是 `[0, interval)` 上的均匀随机数。注释给出理由："epoch 总是按 interval 的精确倍数前进，但我们随机化 deadline，以降低各 arena 同步 purge 的可能性"（decay.h:52-58）。没有这一条，所有 arena 会在同一毫秒一起 `madvise`。

时间还可能倒退。`decay_maybe_update_time`（:74-93）在非单调时钟且发现 epoch 落后时，把 epoch 拉回并重新生成 deadline，注释同时承认这个策略"容易被时钟抖动触发过早的 epoch 推进，但在这里做抖动估计与补偿不可行，因为调用本代码是事件驱动的"。

## Who Asks: One Geometric Ticker, One Deadline-Driven Thread

`pac_maybe_decay_purge` 由三种 eagerness 支配（`src/pac.c:997-1011`）：背景线程 → `PAC_PURGE_ALWAYS`；背景线程已启用 → 应用线程 `PAC_PURGE_NEVER`（只推进 epoch，不碰 madvise）；否则 → `PAC_PURGE_ON_EPOCH_ADVANCE`。也就是说**同一份 decay 状态，谁来问决定了它动不动手**。

应用线程侧的触发器是几何 ticker。`arena_decay_ticks`（`include/jemalloc/internal/arena_inlines.h:293-313`）的注释解释了为什么不做 per-arena-per-thread 计数器："线程与 arena 在合理假设下都随 CPU 数线性增长，于是每线程存每 arena 一份会二次方膨胀；而且这些 ticker 在 tcache 刷回路径上常常是 cache miss。改成每 tick 掷一次硬币（正面概率 1/nticks），平均次数不变，元数据只剩一份。" 硬币来自 `ticker_geom_fixup` 查表（`include/jemalloc/internal/ticker.h:157-165`），表本身是 `ceil(log(u)/log(1-1/nticks))` 的预计算，用 uint8 缩放存储（乘数 `TICKER_GEOM_MUL = 61`，6 bit 索引），理由同样是"核心路径不能碰浮点——不带 SSE 编译的 glibc 动态加载器仍相当常见"（`src/ticker.c:5-27`）。

`ARENA_DECAY_NTICKS_PER_UPDATE` 是 1000，而它在 5.4 被搬进了一个**只有这一条常量**的新头文件 `include/jemalloc/internal/arena_decay_constants.h`，那里注释说明原因：让 `arena.h` 与 `tsd_internals.h` 都能拿到它，而不在 tsd 的解析链上拖进整个 arena 类型。ticker 状态则挂在 TSD 上（`include/jemalloc/internal/tsd_internals.h:84, :103-104`，用 `TICKER_GEOM_INIT`）。

计数的单位是 extent／页批次，不是一次 free：tcache 刷回时按刷了几个打几格（`src/arena.c:1128-1129` 传 `flush_start - prev_flush_start`，`:1228` 传 `nflush - ndeferred`），而 `arena_dalloc_small` 每次打一格（`src/arena.c:966-970`）。

背景线程侧则完全按"下一次什么时候有活"来睡。`background_work_sleep_once`（`src/background_thread.c:301-344`）以 `i += max_background_threads` 的跨步方式分摊 arena，取所有 arena 里最早的 deferred-work 时刻；`DEFERRED_WORK_MAX` 表示"无事可做"于是无限睡，`DEFERRED_WORK_MIN` 表示"现在就欠"（`include/jemalloc/internal/deferral.h:20-28`），最短间隔 100ms（`BACKGROUND_THREAD_MIN_INTERVAL_NS = BILLION / 10`，background_thread.c:204）。

时刻本身由 `decay_ns_until_purge`（`src/decay.c:241-296`）二分算出：目标不是"精确 purge 到阈值"，而是落在阈值 `[0.5x, 1.5x]` 区间内即可（`include/jemalloc/internal/decay.h:178-186`）。核心是 `decay_npurge_after_interval`（:227-239）——把 backlog 左移 k 段后再套一次曲线，两次循环合并成一次以免重复遍历 `[k, 200)`，那段注释（:211-225）特别说明实现与描述"本质上同一个计算，只是做了优化"。下界取 2 个 interval 而非 1，注释写着"确保能到达下一个 epoch deadline"（:266）。

5.4 把这套编排的所有权收归 PAC：`ChangeLog:78-81` 记着"用直接调用取代 PAI vtable，移除 `pai_t`/`pai.h`，并把 deferred-work 与 decay 编排搬出 arena"。所以现在应用路径的入口只有一个 `pa_shard_do_deferred_work` → `pac_do_deferred_work`（`src/pa.c:273-285`，`src/pac.c:950-982`）。

## Waking the Thread Early Is Deliberately Coupled

默认 4 个背景线程（`DEFAULT_NUM_BACKGROUND_THREAD`，`include/jemalloc/internal/background_thread.h:13-15`），而且整个特性是 **opt-in**：`BACKGROUND_THREAD_DEFAULT` 上方就一句注释"This option should be opt-in only."（`src/background_thread.c:22-25`）。没开它，归还全靠应用线程自己那枚硬币，以及下面这条兜底。

开启时，free 路径会在 epoch 真的推进后去敲背景线程的锁——非阻塞（trylock），拿不到就"把这活留给下一个 epoch"（:907-916）。判断要不要提前叫醒集中在一处，代码罕见地写了一整段"为什么不再拆细"的注释（`src/pac.c:839-860`）：提前唤醒本质上**同时**需要 `info` 与 `decay` 两边的数据（在持有 `info->mtx` 时 trylock `decay->mtx`，原子地读 `remaining_sleep = wakeup_time - epoch` 与 `decay_npages_purge_in()` 的估计），拆开只会新增接口而无行为收益；而且它跑在 free 路径上，性能必须对齐。

触发条件是累计待 purge 页数越过 1024：`PAC_DECAY_PURGE_NPAGES_THRESHOLD`（`include/jemalloc/internal/pac.h:31-37`），该注释顺带标出 PAC 与 HPA 的分野——"HPA 按时间区间而非页数来决定，所以这个常量只属于 PAC"。同一段注释还留了一条"parity trap"：`npages_new == 0` 时跳过累加，但**已有** backlog 仍要参加阈值比较，不许顺手 early-return（:856-859）。

真叫醒之前还有一道"批处理"闸门：如果剩余睡眠时间已短于 100ms，就干脆别叫——"我们知道背景线程很快会自己醒，此时刚释放内存的缓存时间是有界且低的"（`src/background_thread.c:737-750`）。

睡眠用的时钟是 5.4 的一个独立修复：`ChangeLog:99-101` 记"背景线程睡眠改用 `CLOCK_MONOTONIC`，以防时钟回拨导致停滞，并在 configure 期检测 monotonic condvar 支持"。落点是新 OS 抽象层——`os_cond_init` 用 `pthread_condattr_setclock` 把条件变量与单调钟绑定（`include/jemalloc/internal/os/posix/cond.h:15-36`），`os_cond_now` 读同一个钟（:58-73），而背景线程算绝对 deadline 时依赖的正是这个配对："`os_cond_now()` 读的就是 `os_cond_init()` 给条件变量配的那个钟，所以 deadline 落在正确的 epoch 里"（`src/background_thread.c:226-240`）。

## Purging Is a Ladder of syscalls

真正动手的是 `pac_decay_stashed`（`src/pac.c:598-690`）。它先按 `npages_limit` 从 ecache 里**摘出**一批 extent（`pac_stash_decayed` :538-558），再逐个走状态机。摘与做分开是为了能在放锁期间干活：`pac_decay_to_limit`（:699-724）在开工前置 `decay->purging = true` 并**释放 `decay->mtx`**，回来再加锁清标志。那段注释解释了为什么必须有 `npages_decay_max` 这个上界——"否则当前这轮 decay 期间新加入的页可以无限增长，purging 线程永远收不了尾"（:692-698）。

摘取顺序是 LRU，而且**先普通后 guarded**："guarded extent 的 purge 更贵（不可合并），所以宁愿缓存得更久"（`src/extent.c:183-190`）。延迟合并的 arena 会在摘取时才尝试合并，合不成就从头再来一遍（:178-214）。

剩下的是一段带 `JEMALLOC_FALLTHROUGH` 的三态 switch（`src/pac.c:645-673`）：

```
dirty  + try_muzzy → extent_purge_lazy_wrapper(MADV_FREE) → 移入 ecache_muzzy
dirty  + 否则       ↘
muzzy               → extent_dalloc_wrapper（或已 purge 过则 _purged）→ ecache_retained
```

`extent_purge_lazy_wrapper` 底层是 `os_vm_purge_lazy`，编译期在 `MADV_FREE` 与"退化用 `MADV_DONTNEED`"之间选（`include/jemalloc/internal/os/posix/vm.h:265-285`），运行期还能被探测结果关掉（`src/pages.c:148-157` 的 `pages_can_purge_lazy_runtime`）。

`extent_dalloc_wrapper`（`src/extent.c:1206-1252`）是最后一级阶梯，顺序值得逐条读：能真 `munmap` 就真 munmap（先注销、失败再重新注册，避免与并发分配者抢同一地址）；否则依次试 decommit → forced purge（`MADV_DONTNEED`）→ lazy purge。每一档都记录 `zeroed`，决定这块地址复用时要不要补 memset——这条标志位就是"retained 内存可以省掉清零"的由来。

这里还藏着 `retain` 的真实语义。`ehooks_dalloc_will_fail` 对默认 hooks 而言**就是 `opt_retain`**（`include/jemalloc/internal/ehooks.h:122-124`），于是一旦打开 retain，第一级 `munmap` 分支被整体跳过，代码注释写着"非必要不调用默认 extent_dalloc"（`src/extent.c:1213`）。效果是 RSS 掉、VSZ 不掉。

`process_madvise` 是一条旁路捷径，条件苛刻但收益明显（`src/pac.c:613-633`）：仅在 1) 启用（`opt_process_madvise_max_batch > 0`，默认 0，`include/jemalloc/internal/extent.h:23-24`）、2) 本就要 purged 到 retained、3) 非自定义 hooks 时尝试。它把整批 extent 攒成栈上 `iovec` 数组分批提交（:560-596，上限受 `VARIABLE_ARRAY_SIZE_MAX` 约束 :26-29），一旦出任何意外（不支持 `MADV_DONTNEED`、部分成功）就当作"什么都没 purge"并回落到常规 madvise（:623-629）。成功时改走 `extent_dalloc_wrapper_purged`，它断言不会再走 munmap 路线，只把 `zeroed` 置真后登记进 retained（`src/extent.c:1192-1204`）——省掉第二次 syscall。这个选项本身是 5.3.1 引入的（`ChangeLog:142-144`），5.4 修的是它跨路径吞掉 `errno` 的问题（:43-46）。

## Two Shortcuts That Bypass the Curve

**超尺寸即时回收**。`extent_record` 在把大 extent 登记进 dirty 时检查四个条件，全满足就绕过整条 decay 直接最大化 purge（`src/extent.c:1089-1099`）：属于 `ecache_dirty`、尺寸 ≥ `oversize_threshold`、背景线程未启用、且 `extent_may_force_decay`（dirty 与 muzzy 两个 decay 都没被设成 -1，:71-75）。默认阈值 8M（`include/jemalloc/internal/arena.h:58-63`），而 `src/conf.c:762-767` 直说这个运行时选项"仍未文档化，可能在 6.0 调整，默认值 8M 相当保守"。同一处还留了 pinned 的豁免："pinned extent 不能被 purge，跳过超尺寸捷径"（`src/extent.c:1089`）。

**线程退出兜底**。`tcache_destroy` 末尾会主动打两次 deferred work，注释解释这是为了避开病理情况：正在 tcache 关停路径上（TSD 可能非 nominal），前面那些释放未必触发过 decay；并且 arena 0 也得带上，因为 tcache 数组本身就分配在它上面（`src/tcache.c:1062-1070`）。更狠的是紧接着的分叉——若该 arena 已无挂载线程且背景线程未启用，就 `pa_shard_flush(all = true)` **完全 decay**，"在没有线程分配到这个 arena 时强制 purge"（:1072-1080）。`pa_shard_flush` 也是 `arena_reset` / `arena_destroy` 的入口（`src/pa.c:97-109`）。

## Pinned Extents Opt Out Entirely

`EXTENT_ALLOC_FLAG_PINNED` 是 5.4 的新特性，注释写得很克制：让自定义 extent 分配 hooks 把不可回收的映射（例如 HugeTLB 页）标记出来，以便在 decay 与 purge 流水线**之外**优先复用（`ChangeLog:14-22`）。实现上是四处避让：分配时置 `pac->has_pinned`（`src/extent.c:1166-1168`）；释放时按 `edata_pinned_get` 分流到第四个 ecache 而非 dirty（`src/pac.c:130-136`）；`pac_decay_data_get` 的 switch 只认 dirty 与 muzzy，pinned 落进 `unreachable()`（:25-47）；`pac_decay_stashed` 的状态机把 pinned 归到 `not_reached()`（:666-672）。

它也不是"免费的缓存"：`pac_record_grown` 会把 pinned 的字节加进 `pac_mapped`（pac.h:204-214），所以它不像 retained 那样从 mapped 统计里消失。销毁 arena 时需要一段专门的重排——清掉 pinned 位、让 eager coalesce 把碎片合回原始 OS 分配基址，再登记进 `ecache_retained`，注释点名这是因为 Windows 的 `VirtualFree` 只接受 `VirtualAlloc` 的原址（`src/pac.c:1085-1124`）。

## Version and Verification Notes

- 本篇所有 5.3 → 5.4 的跨版本判断只依据两处：`ChangeLog` 原文（5.4.0 段是 :7-110，5.3.1 段是 :111-258），以及 5.4 树内的**存在性**证据。**本地是浅历史（单提交、仅 `5.4.0` tag），没有做过 5.3 源码 diff**，因此不许写"5.3 的某函数怎样"这类具体断言。
- "10s / 200 段 = 50ms 一个 epoch"是把已核实的常量代入 `src/decay.c:32-36` 的推导；`h_steps` 的具体十六进制值直接摘自 `include/jemalloc/internal/smoothstep.h`。本机 **jemalloc 构建失败**（`autom4te` 的 perl 解释器失效），`jemalloc_internal_defs.h` 不存在，故 `LG_PAGE` 无本地值，本篇不写任何绝对字节数。
- `have_background_thread` 是编译期量，定义在生成的 `jemalloc_internal_defs.h` 中，本地不可读；本篇只引用它的**用法**与注释（`src/background_thread.c:38-44`："定义是无条件的，运行期以 `have_background_thread` 为闸门，于是 ctl.c / arena.c 的调用方永远不直接碰 `background_thread_lock` 或 `info->state`"）。
- `src/extent.c:1055-1075` 那段关于 `lg_max_coalesce` 的块注释风格与仓库其余注释明显不同，本篇只取其**可核实的部分**：合并上限来自 `opt_lg_extent_max_active_fit`（默认 6，`include/jemalloc/internal/extent.h:16-21`），而"decay/purge 期间的合并不受此限制"这一句确实成立——那条路径走 `extent_try_delayed_coalesce`，调用的是不带尺寸上限的 `extent_try_coalesce`（`src/extent.c:77-93`）。
- HPA 侧的归还策略（按时间区间而非页数）本篇只在 `pac.h:31-37` 那条对比注释处引用，不展开。
- 效果量级本机无法测（无法构建、未跑任何 benchmark），本篇只描述机制与代价结构，不给任何性能数字。

## Links

- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [Thread Cache](/docs/CS/memory/jemalloc/Tcache.md)
- [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Configuration and the mallctl Surface](/docs/CS/memory/jemalloc/Config_and_API.md)
- [Memory Allocation](/docs/CS/memory/memory.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
- [madvise(2)](https://man7.org/linux/man-pages/man2/madvise.2.html)
