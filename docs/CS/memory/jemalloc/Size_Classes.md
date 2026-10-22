## Introduction

任何 malloc 实现都必须先回答一个问题：请求 41 字节，到底给几个字节。答案不能是 41——那意味着 free 时无法从指针反推出它属于哪个管理单元；答案也不能是"下一个 2 的幂"，那样平均每笔浪费四分之一。jemalloc 的答案是一套**代数**：所有尺寸类都写成

```tex
size = (1 \ll lg\_base) + ndelta \times (1 \ll lg\_delta)
```

于是一个尺寸类只需三个整数就能描述，"该用哪个尺寸类"退化成位运算。

本篇讲这套代数的四个决定：组内间距怎么定、tiny 与伪组从哪来、slab 占几页按什么规则、查找表如何压到 513 字节。基线是 jemalloc `5.4.0`（tag `5.4.0`，HEAD `7a34f18`），文中 `路径:行号` 一律相对 jemalloc 仓库根，可回 tag 复核。

## Group Spacing

`include/jemalloc/internal/sc.h:7-167` 是全系列注释最长的一段（160 行），它先抛开最前面几个尺寸类，只讲剩余部分怎么分组：按 2 的幂切段，每段的 base 就是那个 2 的幂，段内放 `SC_NGROUP` 个等距的类，间距 `delta == base / SC_NGROUP`，因此 `lg_delta == lg_base - SC_LG_NGROUP`（`sc.h:18-27`）。每段最后一个类正好落在下一个 2 的幂上，下一段选 delta 的归纳前提由此成立（sc.h:41-43）。

`SC_LG_NGROUP` 取 2，即 `SC_NGROUP == 4`（sc.h:172、184）。注释直接承认"当前每组只有 4 个类，所以上面那些省略号在实践中是空的"（sc.h:39-40）。**每个请求向上取整最多浪费一个组距，即 25%**，这是这个常数换来的性质；`SC_LG_NGROUP` 同时充当位段宽度，多处用 `>> SC_LG_NGROUP` 直接取组号。

每个类的元数据只记 `lg_base / lg_delta / ndelta`（sc.h:315-337），不变式写在 sc.h:142：`size == (1 << lg_base) + ndelta * (1 << lg_delta)`。

## Tiny Classes and the Pseudo-group

`LG_QUANTUM` 是平台最小对齐字节的以 2 为底的对数（`include/jemalloc/internal/quantum.h:4-6`）。x86-64 取 4，也就是 16 字节（quantum.h:22-24）；架构不认识时编译报错，要求显式传 `--with-lg-quantum`（quantum.h:76-80）。小于 `1 << LG_QUANTUM` 的请求不必满足这个对齐（"我们不支持类型对齐大于其大小的平台"），于是为每个 2 的幂开一个 tiny 类，个数是 `LG_QUANTUM - SC_LG_TINY_MIN`（sc.h:45-55、186）。

`1 << LG_QUANTUM` 本身**不能**当组 base：拿它除以 `SC_NGROUP` 会得到小于 quantum 的 delta，而对 `>= (1 << LG_QUANTUM)` 的尺寸用小于 quantum 的间距是违反规则的（sc.h:57-61）。能安全分割的第一个 base 是 `SC_NGROUP * (1 << LG_QUANTUM)`，而走到那里需要 `SC_NGROUP` 个间距恰为 `1 << LG_QUANTUM` 的类——这就是伪组（sc.h:62-80）。它跨多个 2 的幂、分割方式也和常规组不同，起止都落在 2 的幂上（常规组只在右端点落），所以只能"视作"一组。

伪组的 ndelta 记法有个分岔：无 tiny 类时 `lg_base == lg_delta == LG_QUANTUM`，ndelta 从 0 到 `SC_NGROUP - 1`；有 tiny 类时第一个类必须相对**最大 tiny 类**取 delta，于是 `lg_base == lg_delta == LG_QUANTUM - 1` 且 `ndelta == 1`（sc.h:151-159）。运行期生成器里对应那两行是 `lg_base--; ndelta = 1;`（src/sc.c:141-142）。

## Slab Size Is a Least Common Multiple

small 类（= bin 类 = slab 分配的类）的判据是 `size < page size * group size`（sc.h:162-166）。每个 small 类要决定 slab 占几页，规则不是"取装得下最小 region 数的页数"，而是取 **PAGE 与 reg_size 的最小公倍数**：src/sc.c:22-51 的 `slab_size()` 从一页开始逐页累加，直到 `perfect_slab_size == perfect_nregs * reg_size`——slab 恰好是整数个 region，页内不留尾巴。

循环上界写在注释里（src/sc.c:32-39）：因为 `reg_size == (ndelta + ngroup) * delta`，且 `delta <= page`、`ndelta < ngroup`，所以最多跑 `2 * ngroup - 1` 次，"以当前默认设置算最多 7 页"。7 不是理论值——x86-64 上 `reg_size == 448` 的类正好是 7 页：`448 = 2^6 * 7`，4096 的倍数要能被 448 整除最少需要 7 页，slab 28672 字节切成 64 个 region。对照另外两个：8 字节类 1 页 512 region，96 字节类 3 页 128 region。**slab 大小因类而异，而且不是"页数的最小上界"**，这是 jemalloc 与"slab 恒等于一页"的实现最容易混淆的一点。

region 数上限来自 bitmap：`SC_LG_SLAB_MAXREGS == LG_PAGE - SC_LG_TINY_MIN`（sc.h:283-292，可用 `CONFIG_LG_SLAB_MAXREGS` 抬高），`BITMAP_MAXBITS` 在 `SC_LG_SLAB_MAXREGS` 与 `LG_CEIL(SC_NSIZES)` 之间取大者（`include/jemalloc/internal/bitmap.h:11-19`）。

启动时 `bin_info_boot()` 把三元组落成运行期事实：`reg_size`、`slab_size = sc->pgs << LG_PAGE`、`nregs = slab_size / reg_size`、以及按 `nregs` 初始化的 bitmap 描述（src/bin_info.c:14-22）。

## Two Independent Computations

`sc_data_t` 里的 `npsizes / small_maxclass / large_minclass / large_maxclass` 等量**算了两次**：一次在 `size_classes()` 里边生成边累积（src/sc.c:211-227），一次在 sc.h 里写成编译期宏。理由逐字记在 src/sc.c:229-237：增量计算容易写对，而宏形式让快路径"不必去碰那条额外的全局 cacheline"，两者用 assert 锁成等价（src/sc.c:238-243）。

同一文件还有一条 assert 解释快路径的另一个前提：`assert(SC_LARGE_MAXCLASS < SSIZE_MAX)`，注释说最大分配尺寸必须小于 `SSIZE_MAX`，快路径才能无条件地把请求尺寸从一个 `ssize_t` 里减掉并正确检测穿过 0（src/sc.c:245-252）。这条约束是给 [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md) 的线程事件计时用的。

## A 513-byte Lookup Table

`sz_size2index()` 是热路径，做法是三段式：请求不超过 `SC_LOOKUP_MAXCLASS`（`= 1 << SC_LG_MAX_LOOKUP == 4096`，sc.h:250-252）时查表，否则现算（`include/jemalloc/internal/sz.h:219-225`）。

表刻意压缩过。压缩方式注释写得很短——"为了保持这张表小，我们把尺寸除以 tiny min size，那是结果还能变化的最小间隔"（src/sz.c:84-87）。于是维度只有 `(SC_LOOKUP_MAXCLASS >> SC_LG_TINY_MIN) + 1` 项，每项一个 `uint8_t`：x86-64 下就是 **513 字节**，并且 `JEMALLOC_ALIGNED(CACHELINE)`（src/sz.c:88-89）。取索引即一次移位加一次查表（sz.h:205-210），填表则按尺寸升序把每个 sc_ind 向后铺到"下一个类开始改变结果"为止（src/sz.c:91-107）。

用 `uint8_t` 编码意味着 small 类不能多于 256 个，这是编译期检查（sc.h:242-248）。

`sz_index2size` 方向另有未压缩表 `sz_index2size_tab[SC_NSIZES]`（sz.h:38-42）与 compute 版本；debug 构建里查表路径会 assert 两种算法给出同一结果（sz.h:212-217、263-268）。

还有一条只在 LTO 下生效的分支：`sz_size2index_usize_fastpath()` 先用 `util_compile_time_const(size)` 判断 size 是否在调用点变成编译期常量，是则走 compute 版，让静态优化直接把索引和 usize 都算出来（sz.h:299-315）。

## Where Small Stops

三个边界定义都在 sc.h：

- `SC_SMALL_MAXCLASS`——能进 slab 的最大类，`(1 << (LG_PAGE + SC_LG_NGROUP - 1)) + (SC_NGROUP - 1) * (1 << (LG_PAGE - 1))`（sc.h:254-260）。
- `SC_LARGE_MINCLASS`——`1 << (LG_PAGE + SC_LG_NGROUP)`（sc.h:267-268）。
- 两者之间没有空隙，`sz_can_use_slab(size)` 就是 `size <= SC_SMALL_MAXCLASS`（sz.h:475-478）。

`SC_SMALL_MAXCLASS` 必须覆盖整张查找表，否则快路径"假定凡可查表者皆为 small"就错了；这条不变式同样是一句编译期 `#error "Lookup table sizes must be small"`（sc.h:262-265）。

`sz_can_use_slab` 的注释还埋着一个例外：**被 profiling 采样的分配即使尺寸属于 small 也不能用 slab**，因为采样对象要靠强制页对齐来识别，所以若干函数存在 `*_explicit_slab` 变体（sz.h:465-474）。展开在 [Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md)。

## Page Size Classes

"页数量"另有一套索引。`pszind_t` 与 `szind_t` 都只是 `unsigned`（sz.h:27-31），`sz_pind2sz_tab[SC_NPSIZES + 1]` 存所有为页整数倍的尺寸类（sz.h:33-37）；`SC_NPSIZES` 的推导注释配了一张 `lg(base) | base | highest SC | page-multiple SCs` 表，结论是 `SC_NGROUP + (SC_LG_BASE_MAX - (LG_PAGE + SC_LG_NGROUP)) * SC_NGROUP + SC_NGROUP - 1`（sc.h:201-227）。

`sz_psz2ind()` 是位段拆分的教科书例子（sz.h:63-114）：先 `lg_ceil(psz)` 定组偏移，再用注释里那张 ASCII 位图把 `psz - 1` 切成 base / ndelta / delta 三段取组内偏移（sz.h:94-112）；用 `psz - 1` 的理由是处理 `psz % (1 << lg_delta) == 0` 的边界。`sz_psz_quantize_ceil()` 在 floor 结果不够时**故意跳过一档**，注释解释"跳过一个可能给出够大 extent 的量化，因为undersized extent 会被混进来"（src/sz.c:32-54）。

## Alignment-aware Usable Size

`sz_sa2u(size, alignment)` 把 `(size, alignment)` 折成 usize。先试 small：把 size 向上取整到 alignment 的倍数再算 usize，成立的关键是注释那张表——**每个 small 类的每个对象都按"该尺寸二进制表示中最低的和非零的那一位"对齐**，所以 96 保证 32 对齐、144 保证 32、192 保证 64（sz.h:410-431）。

走不通就落到 large：`size <= SC_LARGE_MINCLASS` 时直接取 `SC_LARGE_MINCLASS`，否则 `sz_s2u(size)`，并且要检查三处溢出（sz.h:437-461）。最后那条 `usize + sz_large_pad + PAGE_CEILING(alignment) - PAGE < usize` 算的是 `large_palloc()` 为保证对齐所需多页映射的额外开销——对齐请求在大尺寸上要付页的代价。

## Cache-oblivious Padding

`sz_large_pad` 只有两个取值：`opt_cache_oblivious` 为真时是 `PAGE`，否则 0（sz.h:50-54、src/sz.c:110-111）。垫这一页的目的是让同尺寸的大对象**落在不同的缓存组**，代价是每个大对象多占一页虚拟空间。页量化函数全程都在加减这个 pad（src/sz.c:10-54）。

## Derived Constants for x86-64

⚠️ 本机无法构建 jemalloc：autoconf 依赖的 `/usr/bin/perl5.30` 已失效，`configure` 生成不出来，因此拿不到 `jemalloc_internal_defs.h`。下表是**把已逐字读到的宏代入公式算出的**，不是实测值。代入前提：`LG_QUANTUM = 4`（quantum.h:22-24，已核实）、`SC_PTR_BITS = 64`、`SC_LG_NGROUP = 2`、`SC_LG_TINY_MIN = 3`、`LG_PAGE = 12`（4K 页；具体平台的 configure 取值本机未验证）。

| 量 | 公式出处 | 推导值 |
| :--- | :--- | :--- |
| `SC_NTINY` | sc.h:186 | 1 |
| `SC_NPSEUDO` | sc.h:188 | 4 |
| `SC_LG_FIRST_REGULAR_BASE` | sc.h:189 | 6 |
| `SC_NREGULAR` | sc.h:197-198 | 227 |
| `SC_NSIZES` | sc.h:199 | 232 |
| `SC_NBINS` | sc.h:233-240 | 36 |
| `SC_NPSIZES` | sc.h:225-227 | 199 |
| `SC_LOOKUP_MAXCLASS` | sc.h:251-252 | 4096 |
| `SC_SMALL_MAXCLASS` | sc.h:259-260 | 14336 |
| `SC_LARGE_MINCLASS` | sc.h:268 | 16384 |
| `SC_SLAB_MAXREGS` | sc.h:283-312 | 512 |
| `USIZE_GROW_SLOW_THRESHOLD` | sc.h:309-310 | 32768 |

由此，最前面几个尺寸类是 `8 | 16, 32, 48, 64 | 80, 96, 112, 128 | 160, 192, 224, 256 | ...`：竖线分隔 tiny、伪组与常规组。

## Slow Threshold for Large Usize

`sc.h:294-310` 有一段专门的注释解释 `USIZE_GROW_SLOW_THRESHOLD`：关闭 large 尺寸类（`disable_large_size_classes`）后，`> SC_SMALL_MAXCLASS` 的尺寸不再有类，usize 与请求之差被保证不超过一页；但在 `[SC_LARGE_MINCLASS, 2 * SC_NGROUP * PAGE]` 这段区间里，类间距本来就等于页，usize 不变化，所以**唯独 tcache 与 sec 把可缓存上限抬到 `USIZE_GROW_SLOW_THRESHOLD`**，其余模块一律以 `SC_LARGE_MINCLASS` 为界。`sz_index2size()` 里那条 assert 就是这个例外的落点——它断言的是 `USIZE_GROW_SLOW_THRESHOLD` 而不是 `SC_LARGE_MINCLASS`（sz.h:276-297）。

## Overriding Slab Sizes at Boot

`malloc_conf` 的 `slab_sizes` 键能在启动时改写某些类的页数：值要么是 `default`（重跑 `sc_data_init`），要么是一串 `start-end-pages` 三元组，逐个用 `multi_setting_parse_next` 解析后交给 `sc_data_update_slab_size(sc_data, slab_start, slab_end, pgs)`（src/conf.c:929-956）。该函数只对落在 `[begin, end]` 的 small 类生效，并把请求夹到 `[min_pgs, max_pgs]`：`min_pgs` 是 `reg_size / PAGE` 向上取整，`max_pgs = BITMAP_MAXBITS * reg_size / PAGE`（src/sc.c:263-299）。**"想要几页"和"能给你几页"是两件事，bitmap 容量是硬上界。**

同一族的 `bin_shards`（src/conf.c:632-650）改的是每个 bin 的分片数，属 [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)。

## Version and Verification Notes

本篇断言全部取自本地 `5.4.0` 源码树。仍未闭合的两点，一条都不许写进上面的正文：

- `LG_PAGE` / `SC_NSIZES` / `SC_NBINS` 的**具体数值**必须跑 configure 生成头文件才算实测；本机工具链坏（autoconf 的 perl shebang 失效、release tarball 下载失败），故"Derived Constants"一节按公式代入标注，换平台或换页大小需重算。
- `sc.h:305-307` 那段注释写着 "With the default SC_NGROUP being 2"，而 `SC_NGROUP` 实际是 4（2 是 `SC_LG_NGROUP`）。结论不受影响——阈值由 `SC_LG_NGROUP + LG_PAGE + 1` 直接算出——但引用这段注释时不要照抄那句措辞。

## Links

- [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md)
- [Thread Cache](/docs/CS/memory/jemalloc/Tcache.md)
- [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md)
- [Memory Allocation](/docs/CS/memory/memory.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
- [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)
