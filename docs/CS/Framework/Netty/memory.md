## Introduction

Some methods such as `ByteBuf.readBytes(int)` will cause a memory leak if the returned buffer is not released or added to the out List.
Use derived buffers like `ByteBuf.readSlice(int)` to avoid leaking memory.

在 4.1.52.Final 之前 Netty 内存池是基于 jemalloc3 的设计思想实现的，由于在该版本的实现中，内存规格的粒度设计的比较粗，可能会引起比较严重的内存碎片问题。所以为了近一步降低内存碎片，Netty 在  4.1.52.Final  版本中重新基于 jemalloc4 的设计思想对内存池进行了重构，通过将内存规格近一步拆分成更细的粒度，以及重新设计了内存分配算法尽量将内存碎片控制在比较小的范围内
随后在 4.1.75.Final 版本中，Netty 为了近一步降低不必要的内存消耗，将 ChunkSize 从原来的 16M 改为了 4M 。而且在默认情况下不在为普通的用户线程提供内存池的 Thread Local 缓存。在兼顾性能的前提下，将不必要的内存消耗尽量控制在比较小的范围内。
PoolArena 有两个实现，一个是 HeapArena，负责池化堆内内存，另一个是 DirectArena，负责池化堆外内存
为了避免多线程竞争从PoolArena中获取内存 netty设计了多个PoolArena来分摊竞争 同时支持线程绑定 提高并行度

PoolArena 的默认个数为 availableProcessors * 2 , 因为 Netty 中的 Reactor 线程个数默认恰好也是 CPU 核数的两倍，而内存的分配与释放在 Reactor 线程中是一个非常高频的操作，所以这里将 Reactor 线程与 PoolArena 一对一绑定起来，避免 Reactor 线程之间的相互竞争

无论是什么类型的线程，在它运行起来之后，当第一次向内存池申请内存的时候，都会采用 Round-Robin 的方式与一个固定的 PoolArena 进行绑定，后续在线程整个生命周期中的内存申请以及释放等操作都只会与这个绑定的 PoolArena 进行交互


>可以通过 -Dio.netty.allocator.numHeapArenas 以及 -Dio.netty.allocator.numDirectArenas 来调整系统中 HeapArena 和 DirectArena 的个数
>




在服务端NioServerSocketChannel的配置类NioServerSocketChannelConfig以及客户端NioSocketChannel的配置类NioSocketChannelConfig实例化的时候会触发 PooledByteBufAllocator 的创建 
创建出来的PooledByteBufAllocator实例保存在DefaultChannelConfig类中的ByteBufAllocator allocator字段中

默认情况下是使用 pooled 的（Android 上是 unpooled）——这是 **4.1** 的行为。

> [!WARNING]
>
> **4.2 起默认值已改为 `adaptive`**，`ByteBufAllocator.DEFAULT` 不再是 `PooledByteBufAllocator.DEFAULT`，而是 `new AdaptiveByteBufAllocator()`。4.2 上要退回池化需显式 `-Dio.netty.allocator.type=pooled`。未知值回落到 `PooledByteBufAllocator.DEFAULT`。详见 [AdaptiveByteBufAllocator](#adaptivebytebufallocator)。


```java
public interface ByteBufAllocator {

    ByteBufAllocator DEFAULT = ByteBufUtil.DEFAULT_ALLOCATOR;
}
```

> [!NOTE]
>
> 下面是 **4.2.19 的实际代码**。注意两点容易被旧资料误导的地方：
>
> 1. 默认值是**无条件**的字符串 `"adaptive"`——4.2 里**没有** `PlatformDependent.isAndroid() ? "unpooled" : "adaptive"` 这个三元判断（那是 4.1 的写法）。Android 上的差异改由其它路径处理。
> 2. `"adaptive"` 分支 `new AdaptiveByteBufAllocator()`；`"pooled"` 分支用单例 `PooledByteBufAllocator.DEFAULT`；`"unpooled"` 用 `UnpooledByteBufAllocator.DEFAULT`；三者都不匹配时**静默回落到 pooled** 并打一条 debug 日志。

// 源码：buffer/src/main/java/io/netty/buffer/ByteBufUtil.java:76-105
```java
static final ByteBufAllocator DEFAULT_ALLOCATOR;

static {
    String allocType = SystemPropertyUtil.get(
            "io.netty.allocator.type", "adaptive");

    ByteBufAllocator alloc;
    if ("unpooled".equals(allocType)) {
        alloc = UnpooledByteBufAllocator.DEFAULT;
        logger.debug("-Dio.netty.allocator.type: {}", allocType);
    } else if ("pooled".equals(allocType)) {
        alloc = PooledByteBufAllocator.DEFAULT;
        logger.debug("-Dio.netty.allocator.type: {}", allocType);
    } else if ("adaptive".equals(allocType)) {
        alloc = new AdaptiveByteBufAllocator();
        logger.debug("-Dio.netty.allocator.type: {}", allocType);
    } else {
        alloc = PooledByteBufAllocator.DEFAULT;
        logger.debug("-Dio.netty.allocator.type: pooled (unknown: {})", allocType);
    }

    DEFAULT_ALLOCATOR = alloc;

    THREAD_LOCAL_BUFFER_SIZE = SystemPropertyUtil.getInt("io.netty.threadLocalDirectBufferSize", 0);
    logger.debug("-Dio.netty.threadLocalDirectBufferSize: {}", THREAD_LOCAL_BUFFER_SIZE);

    MAX_CHAR_BUFFER_SIZE = SystemPropertyUtil.getInt("io.netty.maxThreadLocalCharBufferSize", 16 * 1024);
    logger.debug("-Dio.netty.maxThreadLocalCharBufferSize: {}", MAX_CHAR_BUFFER_SIZE);
}
```

| 版本   | `io.netty.allocator.type` 默认值   | `ByteBufAllocator.DEFAULT`           |
| :--- | :------------------------------- | :----------------------------------- |
| 4.1  | `pooled`（Android 上 `unpooled`）   | `PooledByteBufAllocator.DEFAULT`     |
| 4.2  | `adaptive`（**无 Android 特判**）     | `new AdaptiveByteBufAllocator()`     |


```java
public static final PooledByteBufAllocator DEFAULT =
        new PooledByteBufAllocator(PlatformDependent.directBufferPreferred());
```





```java
public class PooledByteBufAllocator extends AbstractByteBufAllocator implements ByteBufAllocatorMetricProvider {

    private static final InternalLogger logger = InternalLoggerFactory.getInstance(PooledByteBufAllocator.class);
    private static final int DEFAULT_NUM_HEAP_ARENA;
    private static final int DEFAULT_NUM_DIRECT_ARENA;

    private static final int DEFAULT_PAGE_SIZE;
    private static final int DEFAULT_MAX_ORDER; // 8192 << 9 = 4 MiB per chunk
    private static final int DEFAULT_SMALL_CACHE_SIZE;
    private static final int DEFAULT_NORMAL_CACHE_SIZE;
    static final int DEFAULT_MAX_CACHED_BUFFER_CAPACITY;
    private static final int DEFAULT_CACHE_TRIM_INTERVAL;
    private static final long DEFAULT_CACHE_TRIM_INTERVAL_MILLIS;
    private static final boolean DEFAULT_USE_CACHE_FOR_ALL_THREADS;
    private static final int DEFAULT_DIRECT_MEMORY_CACHE_ALIGNMENT;
    static final int DEFAULT_MAX_CACHED_BYTEBUFFERS_PER_CHUNK;
    private static final boolean DEFAULT_DISABLE_CACHE_FINALIZERS_FOR_FAST_THREAD_LOCAL_THREADS;

    private static final int MIN_PAGE_SIZE = 4096;
    private static final int MAX_CHUNK_SIZE = (int) (((long) Integer.MAX_VALUE + 1) / 2);

    private static final int CACHE_NOT_USED = 0;

    private final Runnable trimTask = new Runnable() {
        @Override
        public void run() {
            PooledByteBufAllocator.this.trimCurrentThreadCache();
        }
    };

    static {
        int defaultAlignment = SystemPropertyUtil.getInt(
            "io.netty.allocator.directMemoryCacheAlignment", 0);
        int defaultPageSize = SystemPropertyUtil.getInt("io.netty.allocator.pageSize", 8192);
        Throwable pageSizeFallbackCause = null;
        try {
            validateAndCalculatePageShifts(defaultPageSize, defaultAlignment);
        } catch (Throwable t) {
            pageSizeFallbackCause = t;
            defaultPageSize = 8192;
            defaultAlignment = 0;
        }
        DEFAULT_PAGE_SIZE = defaultPageSize;
        DEFAULT_DIRECT_MEMORY_CACHE_ALIGNMENT = defaultAlignment;

        int defaultMaxOrder = SystemPropertyUtil.getInt("io.netty.allocator.maxOrder", 9);
        Throwable maxOrderFallbackCause = null;
        try {
            validateAndCalculateChunkSize(DEFAULT_PAGE_SIZE, defaultMaxOrder);
        } catch (Throwable t) {
            maxOrderFallbackCause = t;
            defaultMaxOrder = 9;
        }
        DEFAULT_MAX_ORDER = defaultMaxOrder;

        // Determine reasonable default for nHeapArena and nDirectArena.
        // Assuming each arena has 3 chunks, the pool should not consume more than 50% of max memory.
        final Runtime runtime = Runtime.getRuntime();

        /*
  * We use 2 * available processors by default to reduce contention as we use 2 * available processors for the
  * number of EventLoops in NIO and EPOLL as well. If we choose a smaller number we will run into hot spots as
  * allocation and de-allocation needs to be synchronized on the PoolArena.
  *
  * See https://github.com/netty/netty/issues/3888.
  */
        final int defaultMinNumArena = NettyRuntime.availableProcessors() * 2;
        final int defaultChunkSize = DEFAULT_PAGE_SIZE << DEFAULT_MAX_ORDER;
        DEFAULT_NUM_HEAP_ARENA = Math.max(0,
                                          SystemPropertyUtil.getInt(
                        "io.netty.allocator.numHeapArenas",
                        (int) Math.min(
                                defaultMinNumArena,
                                runtime.maxMemory() / defaultChunkSize / 2 / 3)));
        DEFAULT_NUM_DIRECT_ARENA = Math.max(0,
                SystemPropertyUtil.getInt(
                        "io.netty.allocator.numDirectArenas",
                        (int) Math.min(
                                defaultMinNumArena,
                                PlatformDependent.maxDirectMemory() / defaultChunkSize / 2 / 3)));

        // cache sizes
        DEFAULT_SMALL_CACHE_SIZE = SystemPropertyUtil.getInt("io.netty.allocator.smallCacheSize", 256);
        DEFAULT_NORMAL_CACHE_SIZE = SystemPropertyUtil.getInt("io.netty.allocator.normalCacheSize", 64);

        // 32 kb is the default maximum capacity of the cached buffer. Similar to what is explained in
        // 'Scalable memory allocation using jemalloc'
        DEFAULT_MAX_CACHED_BUFFER_CAPACITY = SystemPropertyUtil.getInt(
                "io.netty.allocator.maxCachedBufferCapacity", 32 * 1024);

        // the number of threshold of allocations when cached entries will be freed up if not frequently used
        DEFAULT_CACHE_TRIM_INTERVAL = SystemPropertyUtil.getInt(
                "io.netty.allocator.cacheTrimInterval", 8192);

        if (SystemPropertyUtil.contains("io.netty.allocation.cacheTrimIntervalMillis")) {
            logger.warn("-Dio.netty.allocation.cacheTrimIntervalMillis is deprecated," +
                    " use -Dio.netty.allocator.cacheTrimIntervalMillis");

            if (SystemPropertyUtil.contains("io.netty.allocator.cacheTrimIntervalMillis")) {
                // Both system properties are specified. Use the non-deprecated one.
                DEFAULT_CACHE_TRIM_INTERVAL_MILLIS = SystemPropertyUtil.getLong(
                        "io.netty.allocator.cacheTrimIntervalMillis", 0);
            } else {
                DEFAULT_CACHE_TRIM_INTERVAL_MILLIS = SystemPropertyUtil.getLong(
                        "io.netty.allocation.cacheTrimIntervalMillis", 0);
            }
        } else {
            DEFAULT_CACHE_TRIM_INTERVAL_MILLIS = SystemPropertyUtil.getLong(
                    "io.netty.allocator.cacheTrimIntervalMillis", 0);
        }

        DEFAULT_USE_CACHE_FOR_ALL_THREADS = SystemPropertyUtil.getBoolean(
                "io.netty.allocator.useCacheForAllThreads", false);

        DEFAULT_DISABLE_CACHE_FINALIZERS_FOR_FAST_THREAD_LOCAL_THREADS = SystemPropertyUtil.getBoolean(
                "io.netty.allocator.disableCacheFinalizersForFastThreadLocalThreads", false);

        // Use 1023 by default as we use an ArrayDeque as backing storage which will then allocate an internal array
        // of 1024 elements. Otherwise we would allocate 2048 and only use 1024 which is wasteful.
        DEFAULT_MAX_CACHED_BYTEBUFFERS_PER_CHUNK = SystemPropertyUtil.getInt(
                "io.netty.allocator.maxCachedByteBuffersPerChunk", 1023);
    }
}
```

多个线程与同一个PoolArena进行了绑定 它们之间还是会存在竞争的情况
比如现在有两个线程：Thread1 和 Thread2 ，它俩共同绑定到了同一个 PoolArena 上，Thread1 首先向 PoolArena 申请了一个内存块，并加载到运行它的 CPU1  L1 Cache 中，Thread1 使用完之后将这个内存块释放回 PoolArena。
假设此时 Thread2 向 PoolArena 申请同样尺寸的内存块，而且恰好申请到了刚刚被 Thread1 释放的内存块。注意，此时这个内存块已经在 CPU1  L1 Cache 中缓存了，运行 Thread2 的 CPU2  L1 Cache 中并没有，这就涉及到了 cacheline 的核间通信（MESI 协议相关），又要耗费几十个时钟周期

内存池的第二个模型 —— PoolThreadCache ，作为线程的 Thread Local 缓存，它用于缓存线程从 PoolArena 中申请到的内存块，线程每次申请内存的时候首先会到 PoolThreadCache 中查看是否已经缓存了相应尺寸的内存块，如果有，则直接从 PoolThreadCache 获取，如果没有，再到 PoolArena 中去申请。同理，线程每次释放内存的时候，也是先释放到 PoolThreadCache 中，而不会直接释放回 PoolArena
为每个线程引入 Thread Local 本地缓存 —— PoolThreadCache，实现了内存申请与释放的无锁化，同时也避免了 cacheline 在多核之间的通信开销，极大地提升了内存池的性能
但是这样又会引来一个问题，就是内存消耗太大了，系统中有那么多的线程，如果每个线程在向 PoolArena 申请内存的时候，我们都为它默认创建一个 PoolThreadCache 本地缓存的话，这一部分的内存消耗将会特别大。
因此为了近一步降低内存消耗又同时兼顾内存池的性能，在 Netty 的权衡之下，默认只会为 Reactor 线程以及  FastThreadLocalThread 类型的线程创建 PoolThreadCache，而普通的用户线程在默认情况下将不再拥有本地缓存
配置选项 -Dio.netty.allocator.useCacheForAllThreads, 默认为 false 。如果我们将其配置为 true , 那么 Netty 默认将会为系统中的所有线程分配 PoolThreadCache

Netty 中一个 page 的大小默认为 8k，我们可以通过 -Dio.netty.allocator.pageSize 调整 page 大小，但最低只能调整到 4k，而且 pageSize 必须是 2 的次幂


Netty 内存池最小的管理单位是 page , 而内存池单次向 OS 申请内存的单位是 Chunk，一个 Chunk 的大小默认为 4M。Netty 用一个 PoolChunk 的结构来管理这 4M 的内存空间。我们可以通过 -Dio.netty.allocator.maxOrder 来调整 chunkSize 的大小（默认为 4M），maxOrder 的默认值为 9 ，最大值为 14


ChunkSize 的大小是由 PAGE_SIZE 和 MAX_ORDER 共同决定的 —— PAGE_SIZE << MAX_ORDER，当 pageSize 为 8K 的时候，chunkSize 最大不能超过 128M，无论 pageSize 配置成哪种大小，最大的 chunkSize 不能超过 1G


Netty 在向 OS 申请到一个 PoolChunk 的内存空间（4M）之后，会通过 SizeClasses 近一步将这 4M 的内存空间切分成 68 种规格的内存块来进行池化管理。其中最小规格的内存块为 16 字节，最大规格的内存块为 4M 。也就是说，Netty 的内存池只提供如下 68 种内存规格来让用户申请

> 这个数字不是硬编码的，而是由 `SizeClasses` 的构造器算出来的：数组长度上界是 `(log2(chunkSize) - LOG2_QUANTUM - LOG2_SIZE_CLASS_GROUP + 1) << LOG2_SIZE_CLASS_GROUP`，代入默认参数（chunkSize = 2^22、LOG2_QUANTUM = 4、LOG2_SIZE_CLASS_GROUP = 2）得 `17 << 2 = 68`；随后按"每组 4 档、组内步长随组翻倍"的规则填充，直到 size 追平 chunkSize 为止（源码：`buffer/src/main/java/io/netty/buffer/SizeClasses.java:118-152`）。

按默认参数展开，`sizeIdx` 0 → 67 依次是：

| 档位                | sizeIdx   | 尺寸                                                                                                    |
| :---------------- | :-------- | :------------------------------------------------------------------------------------------------------ |
| Small（subpage）    | 0 – 38    | 16, 32, 48, 64, 80, 96, 112, 128, 160 … 4096, 5120, 6144, 7168, 8192, 10240, 12288, 14336, 16384, 20480, 24576, 28672（**共 39 档**，`smallMaxSizeIdx = 38`）|
| Normal（run）       | 39 – 67   | 32768, 40960 … 直至 4194304（4 MiB = chunkSize）                                                              |

`nSizes = 68`、`nSubpages = 39`、`smallMaxSizeIdx = 38` 都在构造末尾统计得出（源码：`SizeClasses.java:158-175`）；"是否 subpage" 的判据是 `log2Size < pageShifts + LOG2_SIZE_CLASS_GROUP`（源码：`SizeClasses.java:208`），默认即 `log2Size < 15`，也就是 28 KiB 以下。

Netty 又将这 68 种内存规格分为了三类：
1. [16B , 28K] 这段范围内的规格被划分为 Small 规格。
2. [32K , 4M] 这段范围内的规格被划分为 Normal 规格。
3. 超过 4M 的内存规格被划分为 Huge 规格。

其中 Small 和 Normal 规格的内存块会被内存池（PoolArena）进行池化管理，Huge 规格的内存块不会被内存池管理，当我们向内存池申请 Huge 规格的内存块时，内存池是直接向 OS 申请内存，释放的时候也是直接释放回 OS ，内存池并不会缓存这些 Huge 规格的内存块

> `PoolArena.allocate` 里三分支的判据直接对应上表：`sizeIdx <= smallMaxSizeIdx` → Small；`sizeIdx < nSizes` → Normal；否则 `sizeIdx == nSizes`（`size2SizeIdx` 对超出 chunkSize 的请求返回 `nSizes`）→ Huge（源码：`buffer/src/main/java/io/netty/buffer/PoolArena.java:135-148`）。注意 Huge 分支**不走线程缓存**，这在源码注释里写明了："Huge allocations are never served via the cache so just call allocateHuge"。



```java
abstract class PoolArena<T> implements PoolArenaMetric {
    enum SizeClass {
        Small,
        Normal
    }
}
```

PoolChunk 的设计参考了 Linux 内核中的伙伴系统，在内核中，内存管理的基本单位也是 Page（4K），这些 Page 会按照伙伴的形式被内核组织在伙伴系统中
同样是对 Page 的管理，Netty 中的 PoolChunk 的实现和内核中的伙伴系统非常相似。PoolChunk 也有一个数组 runsAvail

```java
final class PoolChunk<T> implements PoolChunkMetric {
    /**
     * store the first page and last page of each avail run
     */
    private final LongLongHashMap runsAvailMap;

    /**
     * manage all avail runs
     */
    private final IntPriorityQueue[] runsAvail;
}
```


Netty 中的伙伴系统一共有 32 个 Page 级别的内存块尺寸， 与内核的free area数据不同 PoolChunk 中管理的这些 Page 级别的内存块尺寸只要是 Page 的整数倍就可以，而不是内核中要求的 2 的次幂个 Page
runsAvail 数组中一共有 32 个元素，数组下标就是 pageIndex ， 数组类型为 IntPriorityQueue（优先级队列），数组中的每一项存储着所有相同 size 的内存块，这里的 size 就是上图中 pageIndex 对应的 size
当我们向 PoolChunk 申请 Page 级别的内存块时，Netty 首先会从上面的 Page 规格表中获取到内存块尺寸对应的 pageIndex，然后到 runsAvail[pageIndex] 中去获取对应尺寸的内存块。
如果没有空闲内存块，Netty 的处理方式也是和内核一样，逐级向上去找，直到在 runsAvail[pageIndex + n] 中找到内存块。然后从这个大的内存块中将我们需要的内存块尺寸切分出来分配，剩下的内存块直接插入到对应的 runsAvail[剩下的内存块尺寸 index]中，并不会像内核那样逐级减半分裂

PoolChunk 的内存块回收过程则和内核一样，回收的时候会将连续的内存块合并成更大的，直到无法合并为止。最后将合并后的内存块插入到对应的  runsAvail[合并后内存块尺寸 index] 中。
Netty 这里还有一点和内核不一样的是，内核的伙伴系统是使用 struct free_area 结构来组织相同尺寸的内存块，它是一个双向链表的结构，每次向内核申请 Page 的时候，都是从 free_list 的头部获取内存块。释放的时候也是讲内存块插入到 free_list 的头部。这样一来我们总是可以获取到刚刚被释放的内存块，局部性比较好。
但 Netty 的伙伴系统采用的是 IntPriorityQueue ，一个优先级队列来组织相同尺寸的内存块，它会按照内存地址从低到高组织这些内存块，我们每次从 IntPriorityQueue 中获取的都是内存地址最低的内存块。Netty 这样设计的目的主要还是为了降低内存碎片，牺牲一定的局部性。


Netty 借鉴了 Linux 内核中 Slab 的设计思想，当我们第一次申请一个 Small 规格的内存块时，Netty 会首先到 PoolChunk 中申请一个或者若干个 Page 组成的大内存块（Page 粒度），这个大内存块在 Netty 中的模型就是 PoolSubpage 。然后按照对应的 Small 规格将这个大内存块切分成多个尺寸相同的小内存块缓存在 PoolSubpage 中

每次申请这个规格的内存块时，Netty 都会到对应尺寸的 PoolSubpage 中去获取，每次释放这个规格的内存块时，Netty 会直接将其释放回对应的 PoolSubpage 中。而且每次申请 Small 规格的内存块时，Netty 都会优先获取刚刚释放回 PoolSubpage 的内存块，保证了局部性。当 PoolSubpage 中缓存的所有内存块全部被释放回来后，Netty 就会将整个 PoolSubpage 重新释放回 PoolChunk 中。
比如当我们首次向 Netty 内存池申请一个 16 字节的内存块时，首先会从 PoolChunk 中申请 1 个 Page（8K），然后包装成 PoolSubpage 。随后会将 PoolSubpage 中的这 8K 内存空间切分成 512 个 16 字节的小内存块。后续针对 16 字节小内存块的申请和释放就都只会和这个 PoolSubpage 打交道了。
当我们第一次申请 28K 的内存块时，由于它也是 Small 规格的尺寸，所以按照相同的套路，Netty 会首先从 PoolChunk 中申请 7 个 Pages（56K）, 然后包装成 PoolSubpage。随后会将 PoolSubpage 中的这 56K 内存空间切分成 2 个 28K 的内存块。
PoolSubpage 的尺寸是内存块的尺寸与 PageSize 的最小公倍数。

每当一个 PoolSubpage 分配完之后，Netty 就会重新到 PoolChunk 中申请一个新的 PoolSubpage 。这样一来，慢慢的，针对某一种特定的 Small 规格，就形成了一个 PoolSubpage 链表，这个链表是一个双向循环链表


在 Netty 中，每一个 Small 规格尺寸都会对应一个这样的 PoolSubpage 双向循环链表，内存池中一共设计了 39 个 Small 规格尺寸 —— [16B , 28k]，所以也就对应了 39 个这样的 PoolSubpage 双向循环链表，形成一个 PoolSubpage 链表数组 —— smallSubpagePools，它是内存池中管理 Small 规格内存块的核心数据结构



```java
abstract class PoolArena<T> implements PoolArenaMetric {
    final PoolSubpage<T>[] smallSubpagePools;
}
```


这个设计也是参考了内核中的 kmalloc 体系，内核中的 kmalloc 也是用一个数组来组织不同尺寸的 slab , 只不过和 Netty 不同的是，kmalloc 支持的小内存块尺寸在 8 字节到 8K 之间

当一个PoolChunk使用完后 需要向内核申请新的PoolChunk
PoolChunkList 是一个双向链表的数据结构，它用来组织和管理 PoolArena 中的这些 PoolChunk
PoolArena 中一共有 6 个 PoolChunkList，分别是：qInit，q000，q025，q050，q075，q100。它们之间通过一个双向链表串联在一起，每个 PoolChunkList 管理着内存使用率在相同范围内的 PoolChunk
- qInit 顾名思义，当一个新的 PoolChunk 被创建出来之后，它就会被放到 qInit 中，该 PoolChunkList 管理的 PoolChunk 内存使用率在 [0% , 25%) 之间，当里边的 PoolChunk 内存使用率大于等于 25% 时，就会被向后移动到下一个 q000 中。
- q000 管理的 PoolChunk 内存使用率在 [1% , 50%) 之间，当里边的 PoolChunk 内存使用率大于等于 50% 时，就会被向后移动到下一个 q025 中。当里边的 PoolChunk 内存使用率小于 1% 时，PoolChunk 就会被重新释放回 OS 中。因为 ChunkSize 是 4M ，Netty 内存池提供的最小内存块尺寸为 16 字节，当 PoolChunk 内存使用率小于 1% 时， 其实内存使用率已经就是 0% 了，对于一个已经全部释放完的 Empty PoolChunk，就需要释放回 OS 中。
- q025 管理的 PoolChunk 内存使用率在 [25% , 75%) 之间，当里边的 PoolChunk 内存使用率大于等于 75% 时，就会被向后移动到下一个 q050 中。当里边的 PoolChunk 内存使用率小于 25% 时，就会被向前移动到上一个 q000 中。
- q050 管理的 PoolChunk 内存使用率在 [50% , 100%) 之间，当里边的 PoolChunk 内存使用率小于 50% 时，就会被向前移动到上一个 q025 中。当里边的 PoolChunk 内存使用率达到 100% 时，直接移动到 q100 中。
- q075  管理的 PoolChunk 内存使用率在 [75% , 100%) 之间，当里边的 PoolChunk 内存使用率小于 75% 时，就会被向前移动到上一个 q050 中。当里边的 PoolChunk 内存使用率达到 100% 时，直接移动到 q100 中。
- q100 管理的全部都是内存使用率 100 % 的 PoolChunk，当有内存释放回 PoolChunk 之后，才会向前移动到 q075 中。

上面这些区间就是 `PoolArena` 构造器里那六行的字面量（源码：`buffer/src/main/java/io/netty/buffer/PoolArena.java:91-96`，签名 `PoolChunkList(arena, nextList, minUsage, maxUsage, chunkSize)`）：

```java
q100 = new PoolChunkList<T>(this, null, 100, Integer.MAX_VALUE, sizeClass.chunkSize);
q075 = new PoolChunkList<T>(this, q100, 75, 100, sizeClass.chunkSize);
q050 = new PoolChunkList<T>(this, q100, 50, 100, sizeClass.chunkSize);
q025 = new PoolChunkList<T>(this, q050, 25, 75, sizeClass.chunkSize);
q000 = new PoolChunkList<T>(this, q025, 1, 50, sizeClass.chunkSize);
qInit = new PoolChunkList<T>(this, q000, Integer.MIN_VALUE, 25, sizeClass.chunkSize);
```

注意 `q050` 与 `q075` 的 `nextList` **都是 `q100`**（不是 `q075` / `q100` 依次串），即使用率到 100% 时一步跳到 q100；向前则由 `prevList(...)` 单独指定。




PoolArena 中的每一个 PoolChunkList 都规定了其中 PoolChunk 的内存使用率的上限和下限，当某个 PoolChunkList 中的 PoolChunk 内存使用率低于规定的下限时，Netty 首先会将其从当前 PoolChunkList 中移除，然后移动到前一个 PoolChunkList 中。
当 PoolChunk 的内存使用率达到规定的上限时，Netty 会将其移动到下一个 PoolChunkList 中。但这里有一个特殊的设计不知大家注意到没有，就是 q000 它的 prevList 指向 NULL , 也就是说当 q000 中的 PoolChunk 内存使用率低于下限 —— 1% 时，这个 PoolChunk 并不会向前移动到 qInit 中，而是会释放回 OS 中


Netty 将整个内存池的实现封装在 PooledByteBufAllocator 类中


```java
public class PooledByteBufAllocator {
    public static final PooledByteBufAllocator DEFAULT =
            new PooledByteBufAllocator(PlatformDependent.directBufferPreferred());
}
```

首先会创建 PoolThreadLocalCache，它是一个 FastThreadLocal 类型的成员变量，主要作用是用于后续实现线程与 PoolArena 之间的绑定，并为线程创建本地缓存 PoolThreadCache

```java
// 源码：buffer/src/main/java/io/netty/buffer/PooledByteBufAllocator.java:516-556
private final class PoolThreadLocalCache extends FastThreadLocal<PoolThreadCache> {
    private final boolean useCacheForAllThreads;

    PoolThreadLocalCache(boolean useCacheForAllThreads) {
        this.useCacheForAllThreads = useCacheForAllThreads;
    }

    @Override
    protected synchronized PoolThreadCache initialValue() {
        final PoolArena<byte[]> heapArena = leastUsedArena(heapArenas);
        final PoolArena<ByteBuffer> directArena = leastUsedArena(directArenas);

        final Thread current = Thread.currentThread();
        final EventExecutor executor = ThreadExecutorMap.currentExecutor();

        if (useCacheForAllThreads ||
            // If the current thread is a FastThreadLocalThread we will always use the cache
            FastThreadLocalThread.currentThreadHasFastThreadLocal() ||
            // The Thread is used by an EventExecutor, let's use the cache as the chances are good that we
            // will allocate a lot!
            executor != null) {
            final PoolThreadCache cache = new PoolThreadCache(
                heapArena, directArena, smallCacheSize, normalCacheSize,
                DEFAULT_MAX_CACHED_BUFFER_CAPACITY, DEFAULT_CACHE_TRIM_INTERVAL, useCacheFinalizers());

            if (DEFAULT_CACHE_TRIM_INTERVAL_MILLIS > 0) {
                if (executor != null) {
                    executor.scheduleAtFixedRate(trimTask, DEFAULT_CACHE_TRIM_INTERVAL_MILLIS,
                                                 DEFAULT_CACHE_TRIM_INTERVAL_MILLIS, TimeUnit.MILLISECONDS);
                }
            }
            return cache;
        }
        // No caching so just use 0 as sizes.
        return new PoolThreadCache(heapArena, directArena, 0, 0, 0, 0, false);
    }

    @Override
    protected void onRemoval(PoolThreadCache threadCache) {
        threadCache.free(false);
    }
}
```

> [!NOTE]
>
> 两处是 4.2 才有的写法，旧资料里常写成 4.1 的样子：① 判断线程类型用的是 `FastThreadLocalThread.currentThreadHasFastThreadLocal()`，不是 `current instanceof FastThreadLocalThread`；② `useCacheFinalizers()` **不带参数**（4.1 是 `useCacheFinalizers(current)`）。
>
> 另外 `leastUsedArena()` 才是"Round-Robin 之外又加了一层均衡"的地方：它挑 `numThreadCaches` 最少的那个 arena，而不是简单轮转（源码：`PooledByteBufAllocator.java:558-575`）。

当线程与一个固定的 PoolArena 绑定好之后，后续线程的内存申请与释放就都和这个 PoolArena 打交道了，在进入 PoolArena 之后，首先我们需要从对象池中取出一个 PooledByteBuf 实例，因为后续从内存池申请的内存块我们还无法直接使用，需要包装成一个 PooledByteBuf 实例返回。Netty 针对 PooledByteBuf 实例也做了池化管理

```java
abstract class PoolArena<T> implements PoolArenaMetric {
    PooledByteBuf<T> allocate(PoolThreadCache cache, int reqCapacity, int maxCapacity) {
        PooledByteBuf<T> buf = newByteBuf(maxCapacity);
        allocate(cache, buf, reqCapacity);
        return buf;
    }
}
```

- 对于 Small 内存规格来说，走 tcacheAllocateSmall 进行分配。
- 对于 Normal 内存规格来说，走 tcacheAllocateNormal 进行分配。
- 对于 Huge 内存规格来说，则直接向 OS 申请，不会走内存池。

// 源码：buffer/src/main/java/io/netty/buffer/PoolArena.java:135-148
```java
private void allocate(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity) {
    final int sizeIdx = sizeClass.size2SizeIdx(reqCapacity);

    if (sizeIdx <= sizeClass.smallMaxSizeIdx) {
        tcacheAllocateSmall(cache, buf, reqCapacity, sizeIdx);
    } else if (sizeIdx < sizeClass.nSizes) {
        tcacheAllocateNormal(cache, buf, reqCapacity, sizeIdx);
    } else {
        int normCapacity = sizeClass.directMemoryCacheAlignment > 0
                ? sizeClass.normalizeSize(reqCapacity) : reqCapacity;
        // Huge allocations are never served via the cache so just call allocateHuge
        allocateHuge(buf, normCapacity);
    }
}
```

tcacheAllocateSmall

Small 规格内存块的申请首先会尝试从线程本地缓存 PoolThreadCache 中去获取，如果缓存中没有，则到 smallSubpagePools 中申请

// 源码：buffer/src/main/java/io/netty/buffer/PoolArena.java:150-189
```java
private void tcacheAllocateSmall(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity,
                                     final int sizeIdx) {

        if (cache.allocateSmall(this, buf, reqCapacity, sizeIdx)) {
            // was able to allocate out of the cache so move on
            return;
        }

        /*
         * Synchronize on the head. This is needed as {@link PoolChunk#allocateSubpage(int)} and
         * {@link PoolChunk#free(long)} may modify the doubly linked list as well.
         */
        final PoolSubpage<T> head = smallSubpagePools[sizeIdx];
        final boolean needsNormalAllocation;
        head.lock();
        try {
            final PoolSubpage<T> s = head.next;
            needsNormalAllocation = s == head;
            if (!needsNormalAllocation) {
                assert s.doNotDestroy && s.elemSize == sizeClass.sizeIdx2size(sizeIdx) : "doNotDestroy=" +
                        s.doNotDestroy + ", elemSize=" + s.elemSize + ", sizeIdx=" + sizeIdx;
            long handle = s.allocate();
            assert handle >= 0;
            s.chunk.initBufWithSubpage(buf, null, handle, reqCapacity, cache, false);
        }
    } finally {
        head.unlock();
    }

    if (needsNormalAllocation) {
        lock();
        try {
            allocateNormal(buf, reqCapacity, sizeIdx, cache);
        } finally {
            unlock();
        }
    }

    incSmallAllocation();
}
```

`head.lock()` / `head.unlock()` 用的是 `PoolSubpage` 自带的 `ReentrantLock`——注意**只有链表头那个 `PoolSubpage` 持有锁**：`PoolSubpage(int headIndex)` 这个特殊构造器里 `lock = new ReentrantLock()`，而普通 subpage 的 `lock` 是 `null`（源码：`buffer/src/main/java/io/netty/buffer/PoolSubpage.java:53` 与 `:83`）。`PoolArena` 自己另有一把锁，保护 `PoolChunkList` 的迁移，`allocateNormal` 开头的 `assert lock.isHeldByCurrentThread()` 就是它。

4.2 相比 4.1 的两处细节差异：`initBufWithSubpage(...)` 多了一个 `threadLocal` 形参（从线程缓存命中时传 `true`，此处传 `false`，源码：`buffer/src/main/java/io/netty/buffer/PoolThreadCache.java:308`）；`incSmallAllocation()` 改为对 `LongAdder allocationsSmall` 自增（源码：`PoolArena.java:225-227`），不再是普通的 `++`。

// 源码：buffer/src/main/java/io/netty/buffer/PoolThreadCache.java:146-169
```java
final class PoolThreadCache {
    boolean allocateSmall(PoolArena<?> area, PooledByteBuf<?> buf, int reqCapacity, int sizeIdx) {
        return allocate(cacheForSmall(area, sizeIdx), buf, reqCapacity);
    }
    private boolean allocate(MemoryRegionCache<?> cache, PooledByteBuf buf, int reqCapacity) {
        if (cache == null) {
            // no cache found so just return false here
            return false;
        }
        boolean allocated = cache.allocate(buf, reqCapacity, this);
        if (++ allocations >= freeSweepAllocationThreshold) {
            allocations = 0;
            trim();
        }
        return allocated;
    }
}
```

```java
final class PoolThreadCache {
public final boolean allocate(PooledByteBuf<T> buf, int reqCapacity, PoolThreadCache threadCache) {
            Entry<T> entry = queue.poll();
            if (entry == null) {
                return false;
            }
            initBuf(entry.chunk, entry.nioBuffer, entry.handle, buf, reqCapacity, threadCache);
            entry.unguardedRecycle();

            // allocations is not thread-safe which is fine as this is only called from the same thread all time.
            ++ allocations;
            return true;
        }
}
```



tcacheAllocateNormal

// 源码：buffer/src/main/java/io/netty/buffer/PoolArena.java:191-204
```java
private void tcacheAllocateNormal(PoolThreadCache cache, PooledByteBuf<T> buf, final int reqCapacity,
                                      final int sizeIdx) {
        if (cache.allocateNormal(this, buf, reqCapacity, sizeIdx)) {
            // was able to allocate out of the cache so move on
            return;
        }
        lock();
        try {
            allocateNormal(buf, reqCapacity, sizeIdx, cache);
            ++allocationsNormal;
        } finally {
            unlock();
        }
    }
```


// 源码：buffer/src/main/java/io/netty/buffer/PoolArena.java:206-223
```java
private void allocateNormal(PooledByteBuf<T> buf, int reqCapacity, int sizeIdx, PoolThreadCache threadCache) {
    assert lock.isHeldByCurrentThread();
    if (q050.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q025.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q000.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        qInit.allocate(buf, reqCapacity, sizeIdx, threadCache) ||
        q075.allocate(buf, reqCapacity, sizeIdx, threadCache)) {
        return;
    }

    // Add a new chunk.
    PoolChunk<T> c = newChunk(sizeClass.pageSize, sizeClass.nPSizes, sizeClass.pageShifts, sizeClass.chunkSize);
    PooledByteBufAllocator.onAllocateChunk(c, true);
    boolean success = c.allocate(buf, reqCapacity, sizeIdx, threadCache);
    assert success;
    qInit.add(c);
    ++pooledChunkAllocations;
}
```

遍历顺序 `q050 → q025 → q000 → qInit → q075` 是刻意设计的：**跳过 q100**（满载），从中间使用率的 chunk 开始找，命中率与碎片率折中；全部失败才 `newChunk()` 并挂进 `qInit`。4.2 新增了 `PooledByteBufAllocator.onAllocateChunk(c, true)` 与 `++pooledChunkAllocations` 两行——它们服务于 4.2 引入的 buffer/chunk 事件与指标（`AllocateChunkEvent` 等），不影响分配语义。

### MemoryRegionCache

`MemoryRegionCache` 是 `PoolThreadCache` 的每个 size class 一个的缓存槽位，本质是**一个定长 MPSC 队列 + 一个分配计数器**：

// 源码：buffer/src/main/java/io/netty/buffer/PoolThreadCache.java:328-409
```java
private abstract static class MemoryRegionCache<T> {
    private final int size;
    private final Queue<Entry<T>> queue;
    private final SizeClass sizeClass;
    private int allocations;

    MemoryRegionCache(int size, SizeClass sizeClass) {
        this.size = MathUtil.safeFindNextPositivePowerOfTwo(size);
        queue = PlatformDependent.newFixedMpscUnpaddedQueue(this.size);
        this.sizeClass = sizeClass;
    }

    /**
     * Add to cache if not already full.
     */
    public final boolean add(PoolChunk<T> chunk, ByteBuffer nioBuffer, long handle, int normCapacity) {
        Entry<T> entry = newEntry(chunk, nioBuffer, handle, normCapacity);
        boolean queued = queue.offer(entry);
        if (!queued) {
            // If it was not possible to cache the chunk, immediately recycle the entry
            entry.unguardedRecycle();
        }

        return queued;
    }

    /**
     * Allocate something out of the cache if possible and remove the entry from the cache.
     */
    public final boolean allocate(PooledByteBuf<T> buf, int reqCapacity, PoolThreadCache threadCache) {
        Entry<T> entry = queue.poll();
        if (entry == null) {
            return false;
        }
        initBuf(entry.chunk, entry.nioBuffer, entry.handle, buf, reqCapacity, threadCache);
        entry.unguardedRecycle();

        // allocations is not thread-safe which is fine as this is only called from the same thread all time.
        ++ allocations;
        return true;
    }

    /**
     * Free up cached {@link PoolChunk}s if not allocated frequently enough.
     */
    public final void trim() {
        int free = size - allocations;
        allocations = 0;

        // We not even allocated all the number that are
        if (free > 0) {
            free(free, false);
        }
    }
}
```

命中路径只有三步：`queue.poll()` → `initBuf(...)`（把缓存的 chunk + handle 填进复用的 `PooledByteBuf`）→ `entry.unguardedRecycle()`（`Entry` 自身也走 Recycler）。`unguardedRecycle` 而非 `recycle` 是因为这里必然是 owner 线程在操作，可以省掉 owner 校验。

两个子类只差一行 `initBuf` 的实现：`SubPageMemoryRegionCache` 走 `chunk.initBufWithSubpage(..., threadLocal = true)`，`NormalMemoryRegionCache` 走 `chunk.initBuf(..., true)`（源码：`PoolThreadCache.java:299-326`）。

缓存槽位的定位也要区分 Small / Normal：`cacheForSmall` 直接用 `sizeIdx` 作下标；`cacheForNormal` 必须先减掉 `nSubpages`（39），因为 `sizeIdx` 是**全 68 档**的全局下标，而 normal 缓存数组只有 68 - 39 = 29 个元素：

// 源码：buffer/src/main/java/io/netty/buffer/PoolThreadCache.java:273-287
```java
private MemoryRegionCache<?> cacheForSmall(PoolArena<?> area, int sizeIdx) {
    if (area.isDirect()) {
        return cache(smallSubPageDirectCaches, sizeIdx);
    }
    return cache(smallSubPageHeapCaches, sizeIdx);
}

private MemoryRegionCache<?> cacheForNormal(PoolArena<?> area, int sizeIdx) {
    // We need to subtract area.sizeClass.nSubpages as sizeIdx is the overall index for all sizes.
    int idx = sizeIdx - area.sizeClass.nSubpages;
    if (area.isDirect()) {
        return cache(normalDirectCaches, idx);
    }
    return cache(normalHeapCaches, idx);
}
```

`PoolThreadCache.add()`（释放侧）在写缓存前还会检查 `freed.get()`——线程缓存一旦被释放就不再接受新条目（源码：`PoolThreadCache.java:176-187`）。

Netty 清理 PoolThreadCache 缓存有两个时机，一个是主动清理，当 PoolThreadCache 分配内存块的次数 allocations （包括 Small 规格，Normal 规格的分配次数）达到阈值 freeSweepAllocationThreshold （8192）时 , Netty  将会把  PoolThreadCache 中缓存的所有 Small 规格以及 Normal 规格的内存块全部释放回 PoolSubpage 中


当线程终结的时候，那么 PoolThreadCache 与 FreeOnFinalize 对象将会被 GC 回收，但由于 FreeOnFinalize 被一个 FinalReference（Finalizer） 引用，所以 JVM 会将 FreeOnFinalize 对象再次复活，由于 FreeOnFinalize 对象也引用了 PoolThreadCache，所以 PoolThreadCache 也会被复活。
随后 JDK 中的 2 号线程 —— finalizer 会执行 FreeOnFinalize 对象的 finalize() 方法，释放 PoolThreadCache

但如果有人不想使用 Finalizer 来释放的话，则可以通过将 -Dio.netty.allocator.disableCacheFinalizersForFastThreadLocalThreads 设置为 true , 那么 useFinalizer 就会变为 false  。
这样一来当线程终结的时候，它的本地缓存 PoolThreadCache 将不会由 Finalizer 来清理。这种情况下，我们就需要特别注意，一定要通过 FastThreadLocal.removeAll() 或者  PoolThreadLocalCache.remove(PoolThreadCache) 来手动进行清理。否则就会造成内存泄露。



```java

private final class PoolThreadLocalCache extends FastThreadLocal<PoolThreadCache> {
    @Override
    protected void onRemoval(PoolThreadCache threadCache) {
        threadCache.free(false);
    }
}
```


```java
final class PoolThreadCache {
    private final AtomicBoolean freed = new AtomicBoolean();
    @SuppressWarnings("unused") // Field is only here for the finalizer.
    private final FreeOnFinalize freeOnFinalize;

    void free(boolean finalizer) {
        // As free() may be called either by the finalizer or by FastThreadLocal.onRemoval(...) we need to ensure
        // we only call this one time.
        if (freed.compareAndSet(false, true)) {
            if (freeOnFinalize != null) {
                // Help GC: this can race with a finalizer thread, but will be null out regardless
                freeOnFinalize.cache = null;
            }
            int numFreed = free(smallSubPageDirectCaches, finalizer) +
            free(normalDirectCaches, finalizer) +
            free(smallSubPageHeapCaches, finalizer) +
            free(normalHeapCaches, finalizer);

            if (directArena != null) {
                directArena.numThreadCaches.getAndDecrement();
            }

            if (heapArena != null) {
                heapArena.numThreadCaches.getAndDecrement();
            }
        }
    }
}
```

## Recycler

Java 中频繁地创建和销毁对象的开销是很大的，所以很多人会将一些通用对象缓存起来，当需要某个对象时，优先从对象池中获取对象实例。
通过重用对象，不仅避免频繁地创建和销毁所带来的性能损耗，而且对 JVM GC 是友好的，这就是对象池的作用

Recycler 是 Netty 提供的自定义实现的轻量级对象回收站，借助 Recycler 可以完成对象的获取和回收

> [!WARNING]
>
> **下面的 Stack / WeakOrderQueue / Link / DefaultHandle 四组件是 Netty 4.0~4.1 早期的设计，现版本源码中已不存在。** 经核实：`WeakOrderQueue` 在 4.2.19 的 `Recycler.java` 中**无定义**（grep 计数为 0），跨线程回收改由 jctools 的 `MessagePassingQueue<H> pooledHandles` 承担（源码：`common/src/main/java/io/netty/util/Recycler.java:507`）；`BLOCKING_POOL_LIMIT` 同样不存在。
>
> **更正一处旧结论**：`io.netty.recycler.blocking` 这个开关**在 4.2.19 里仍然存在**（源码：`Recycler.java:102`，`BLOCKING_POOL = SystemPropertyUtil.getBoolean("io.netty.recycler.blocking", false)`），并非"4.2 删掉了"。
>
> 现版本（4.2.19）的结构是：
>
> ```java
> public abstract class Recycler<T> {
>     private static final int DEFAULT_INITIAL_MAX_CAPACITY_PER_THREAD = 4 * 1024;  // Use 4k instances as default.
>     private static final int DEFAULT_QUEUE_CHUNK_SIZE_PER_THREAD;   // io.netty.recycler.chunkSize，默认 32
>     private static final int RATIO = max(0, SystemPropertyUtil.getInt("io.netty.recycler.ratio", 8));
>     private static final boolean BATCH_FAST_TL_ONLY =
>             SystemPropertyUtil.getBoolean("io.netty.recycler.batchFastThreadLocalOnly", true);
>     private final FastThreadLocal<LocalPool<?, T>> threadLocalPool;
> }
> ```
>
> 源码行号：`Recycler.java:77`（`DEFAULT_INITIAL_MAX_CAPACITY_PER_THREAD`）、`:95`（`DEFAULT_QUEUE_CHUNK_SIZE_PER_THREAD`）、`:100`（`RATIO`）、`:102-103`（`BLOCKING_POOL` / `BATCH_FAST_TL_ONLY`）。
>
> - 池本体是 `LocalPool`（`private abstract static class`，源码：`:502`），两个实现 `GuardedLocalPool`（`:437`，校验 owner 线程）与 `UnguardedLocalPool`（`:474`，不校验）
> - `maxCapacityPerThread` 读 `io.netty.recycler.maxCapacityPerThread`（回退读 `io.netty.recycler.maxCapacity`），`< 0` 时回落 4096（源码：`:88-94`）
> - `chunkSize` 默认 32，构造时 `max(2, min(chunkSize, maxCapacityPerThread >> 1))`（源码：`:264-267`）
> - **回收比率语义**：`ratioInterval`（即 `RATIO`）默认 8，即**每 8 次 recycle 才真正入池 1 次**（`ratioCounter = ratioInterval; // Start at interval so the first one will be recycled.`，源码：`:529`）
> - `BATCH_FAST_TL_ONLY` 默认 true：批量回收只对 `FastThreadLocalThread` 生效
> - `EnhancedHandle` 是 4.2 新增的 handle 接口，比 `Handle<T>` 多了 `unguardedRecycle()`——`PoolThreadCache.Entry` 用的就是它（见 [MemoryRegionCache](/docs/CS/Framework/Netty/memory.md?id=memoryregioncache)）
> - 池本体是 `LocalPool`，分 `GuardedLocalPool` / `UnguardedLocalPool`（后者不校验 owner 线程）
> - `maxCapacityPerThread` 读 `io.netty.recycler.maxCapacityPerThread`（回退读 `io.netty.recycler.maxCapacity`），`< 0` 时回落 4096，构造时 `max(4, ...)`
> - `chunkSize` 默认 32，构造时 `max(2, min(chunkSize, maxCapacityPerThread >> 1))`
> - **回收比率语义**：`ratioInterval` 默认 8，即**每 8 次 recycle 才真正入池 1 次**（`ratioCounter = ratioInterval; // Start at interval so the first one will be recycled.`）
> - `BATCH_FAST_TL_ONLY` 默认 true：批量回收只对 `FastThreadLocalThread` 生效
>
> 下文各处源码按旧实现记录，读的时候请对照这一节；原理层面"每线程一个本地池 + 跨线程异步归还 + 抽样入池"的结论仍然成立。

对象池包含四个核心组件：Stack、WeakOrderQueue、Link、DefaultHandle


Stack 是整个对象池的顶层数据结构，描述了整个对象池的构造，用于存储当前本线程回收的对象。
在多线程的场景下，Netty 为了避免锁竞争问题，每个线程都会持有各自的对象池，内部通过 [FastThreadLocal](/docs/CS/Framework/Netty/FastThreadLocal.md) 来实现每个线程的私有化



WeakOrderQueue 用于存储其他线程回收到当前线程所分配的对象，并且在合适的时机，Stack 会从异线程的 WeakOrderQueue 中收割对象

每个 WeakOrderQueue 中都包含一个 Link 链表，回收对象都会被存在 Link 链表中的节点上，每个 Link 节点默认存储 16 个对象，当每个 Link 节点存储满了会创建新的 Link 节点放入链表尾部

DefaultHandle 实例中保存了实际回收的对象，Stack 和 WeakOrderQueue 都使用 DefaultHandle 存储回收的对象。在 Stack 中包含一个 elements 数组，该数组保存的是 DefaultHandle 实例。
WeakOrderQueue 中每个 Link 节点所存储的 16 个对象也是使用 DefaultHandle 表示的

从对象池中获取对象的入口是在 Recycler#get() 方法



count

Chunk
Page
SubPage

```java
// PooledDirectByteBuf
final class PooledDirectByteBuf extends PooledByteBuf<ByteBuffer> {

    private static final Recycler<PooledDirectByteBuf> RECYCLER = new Recycler<PooledDirectByteBuf>() {
        @Override
        protected PooledDirectByteBuf newObject(Handle<PooledDirectByteBuf> handle) {
            return new PooledDirectByteBuf(handle, 0);
        }
    };
  

  private PooledDirectByteBuf(Recycler.Handle<PooledDirectByteBuf> recyclerHandle, int maxCapacity) {
    super(recyclerHandle, maxCapacity);
  }
 ... 
}
```

### get

```java
static PooledDirectByteBuf newInstance(int maxCapacity) {
    PooledDirectByteBuf buf = RECYCLER.get();
    buf.reuse(maxCapacity);
    return buf;
}
```

get from [FastThreadLocal](/docs/CS/Framework/Netty/FastThreadLocal.md)

```java
// Recycler
public final T get() {
    if (maxCapacityPerThread == 0) {
        return newObject((Handle<T>) NOOP_HANDLE);
    }
    Stack<T> stack = threadLocal.get(); // FastThreadLocal#get()
    DefaultHandle<T> handle = stack.pop();
    if (handle == null) {
        handle = stack.newHandle();
        handle.value = newObject(handle);
    }
    return (T) handle.value;
}


```

Method must be called before reuse this PooledByteBufAllocator

```java
final void reuse(int maxCapacity) {
    maxCapacity(maxCapacity);
    resetRefCnt();
    setIndex0(0, 0);
    discardMarks();
}
```

```java
// Recycler
private final FastThreadLocal<Stack<T>> threadLocal = new FastThreadLocal<Stack<T>>() {
    @Override
    protected Stack<T> initialValue() {
        return new Stack<T>(Recycler.this, Thread.currentThread(), maxCapacityPerThread, maxSharedCapacityFactor,
                interval, maxDelayedQueuesPerThread, delayedQueueInterval);
    }

    @Override
    protected void onRemoval(Stack<T> value) {
        // Let us remove the WeakOrderQueue from the WeakHashMap directly if its safe to remove some overhead
        if (value.threadRef.get() == Thread.currentThread()) {
           if (DELAYED_RECYCLED.isSet()) {
               DELAYED_RECYCLED.get().remove(value);
           }
        }
    }
};
```

### recycle

```java
protected final void deallocate() {
    if (handle >= 0) {
        final long handle = this.handle;
        this.handle = -1;
        memory = null;
        chunk.arena.free(chunk, tmpNioBuf, handle, maxLength, cache);
        tmpNioBuf = null;
        chunk = null;
        recycle();
    }
}

public void recycle(Object object) {
    if (object != value) {
        throw new IllegalArgumentException("object does not belong to handle");
    }

    Stack<?> stack = this.stack;
    if (lastRecycledId != recycleId || stack == null) {
        throw new IllegalStateException("recycled already");
    }

    stack.push(this);
}
```

### Stack

```java
private static final class Stack<T> {

    // we keep a queue of per-thread queues, which is appended to once only, each time a new thread other
    // than the stack owner recycles: when we run out of items in our stack we iterate this collection
    // to scavenge those that can be reused. this permits us to incur minimal thread synchronisation whilst
    // still recycling all items.
    final Recycler<T> parent;

    // We store the Thread in a WeakReference as otherwise we may be the only ones that still hold a strong
    // Reference to the Thread itself after it died because DefaultHandle will hold a reference to the Stack.
    //
    // The biggest issue is if we do not use a WeakReference the Thread may not be able to be collected at all if
    // the user will store a reference to the DefaultHandle somewhere and never clear this reference (or not clear
    // it in a timely manner).
    final WeakReference<Thread> threadRef;
    final AtomicInteger availableSharedCapacity;
    private final int maxDelayedQueues;

    private final int maxCapacity;
    private final int interval;
    private final int delayedQueueInterval;
    DefaultHandle<?>[] elements;	// handles
    int size;
    private int handleRecycleCount;
    private WeakOrderQueue cursor, prev;
    private volatile WeakOrderQueue head;

    Stack(Recycler<T> parent, Thread thread, int maxCapacity, int maxSharedCapacityFactor,
          int interval, int maxDelayedQueues, int delayedQueueInterval) {
        this.parent = parent;
        threadRef = new WeakReference<Thread>(thread);
        this.maxCapacity = maxCapacity;
        availableSharedCapacity = new AtomicInteger(max(maxCapacity / maxSharedCapacityFactor, LINK_CAPACITY));
        elements = new DefaultHandle[min(INITIAL_CAPACITY, maxCapacity)];
        this.interval = interval;
        this.delayedQueueInterval = delayedQueueInterval;
        handleRecycleCount = interval; // Start at interval so the first one will be recycled.
        this.maxDelayedQueues = maxDelayedQueues;
    }

    // Marked as synchronized to ensure this is serialized.
    synchronized void setHead(WeakOrderQueue queue) {
        queue.setNext(head);
        head = queue;
    }

    int increaseCapacity(int expectedCapacity) {
        int newCapacity = elements.length;
        int maxCapacity = this.maxCapacity;
        do {
            newCapacity <<= 1;
        } while (newCapacity < expectedCapacity && newCapacity < maxCapacity);

        newCapacity = min(newCapacity, maxCapacity);
        if (newCapacity != elements.length) {
            elements = Arrays.copyOf(elements, newCapacity);
        }

        return newCapacity;
    }

    @SuppressWarnings({ "unchecked", "rawtypes" })
    DefaultHandle<T> pop() {
        int size = this.size;
        if (size == 0) {
            if (!scavenge()) {
                return null;
            }
            size = this.size;
            if (size <= 0) {
                // double check, avoid races
                return null;
            }
        }
        size --;
        DefaultHandle ret = elements[size];
        elements[size] = null;
        // As we already set the element[size] to null we also need to store the updated size before we do
        // any validation. Otherwise we may see a null value when later try to pop again without a new element
        // added before.
        this.size = size;

        if (ret.lastRecycledId != ret.recycleId) {
            throw new IllegalStateException("recycled multiple times");
        }
        ret.recycleId = 0;
        ret.lastRecycledId = 0;
        return ret;
    }

    private boolean scavenge() {
        // continue an existing scavenge, if any
        if (scavengeSome()) {
            return true;
        }

        // reset our scavenge cursor
        prev = null;
        cursor = head;
        return false;
    }

    private boolean scavengeSome() {
        WeakOrderQueue prev;
        WeakOrderQueue cursor = this.cursor;
        if (cursor == null) {
            prev = null;
            cursor = head;
            if (cursor == null) {
                return false;
            }
        } else {
            prev = this.prev;
        }

        boolean success = false;
        do {
            if (cursor.transfer(this)) {
                success = true;
                break;
            }
            WeakOrderQueue next = cursor.getNext();
            if (cursor.get() == null) {
                // If the thread associated with the queue is gone, unlink it, after
                // performing a volatile read to confirm there is no data left to collect.
                // We never unlink the first queue, as we don't want to synchronize on updating the head.
                if (cursor.hasFinalData()) {
                    for (;;) {
                        if (cursor.transfer(this)) {
                            success = true;
                        } else {
                            break;
                        }
                    }
                }

                if (prev != null) {
                    // Ensure we reclaim all space before dropping the WeakOrderQueue to be GC'ed.
                    cursor.reclaimAllSpaceAndUnlink();
                    prev.setNext(next);
                }
            } else {
                prev = cursor;
            }

            cursor = next;

        } while (cursor != null && !success);

        this.prev = prev;
        this.cursor = cursor;
        return success;
    }

    void push(DefaultHandle<?> item) {
        Thread currentThread = Thread.currentThread();
        if (threadRef.get() == currentThread) {
            // The current Thread is the thread that belongs to the Stack, we can try to push the object now.
            pushNow(item);
        } else {
            // The current Thread is not the one that belongs to the Stack
            // (or the Thread that belonged to the Stack was collected already), we need to signal that the push
            // happens later.
            pushLater(item, currentThread);
        }
    }

    private void pushNow(DefaultHandle<?> item) {
        if ((item.recycleId | item.lastRecycledId) != 0) {
            throw new IllegalStateException("recycled already");
        }
        item.recycleId = item.lastRecycledId = OWN_THREAD_ID;

        int size = this.size;
        if (size >= maxCapacity || dropHandle(item)) {
            // Hit the maximum capacity or should drop - drop the possibly youngest object.
            return;
        }
        if (size == elements.length) {
            elements = Arrays.copyOf(elements, min(size << 1, maxCapacity));
        }

        elements[size] = item;
        this.size = size + 1;
    }

   

    /**
     * Allocate a new {@link WeakOrderQueue} or return {@code null} if not possible.
     */
    private WeakOrderQueue newWeakOrderQueue(Thread thread) {
        return WeakOrderQueue.newQueue(this, thread);
    }

    boolean dropHandle(DefaultHandle<?> handle) {
        if (!handle.hasBeenRecycled) {
            if (handleRecycleCount < interval) {
                handleRecycleCount++;
                // Drop the object.
                return true;
            }
            handleRecycleCount = 0;
            handle.hasBeenRecycled = true;
        }
        return false;
    }

    DefaultHandle<T> newHandle() {
        return new DefaultHandle<T>(this);
    }
}
```

### push

```java
// Stack
void push(DefaultHandle<?> item) {
  Thread currentThread = Thread.currentThread();
  if (threadRef.get() == currentThread) {
    // The current Thread is the thread that belongs to the Stack, we can try to push the object now.
    pushNow(item);
  } else {
    // The current Thread is not the one that belongs to the Stack
    // (or the Thread that belonged to the Stack was collected already), we need to signal that the push
    // happens later.
    pushLater(item, currentThread);
  }
}

private void pushNow(DefaultHandle<?> item) {
  if ((item.recycleId | item.lastRecycledId) != 0) {
    throw new IllegalStateException("recycled already");
  }
  item.recycleId = item.lastRecycledId = OWN_THREAD_ID;

  int size = this.size;
  if (size >= maxCapacity || dropHandle(item)) {
    // Hit the maximum capacity or should drop - drop the possibly youngest object.
    return;
  }
  if (size == elements.length) {
    elements = Arrays.copyOf(elements, min(size << 1, maxCapacity));
  }

  elements[size] = item;
  this.size = size + 1;
}
 
private void pushLater(DefaultHandle<?> item, Thread thread) {
  if (maxDelayedQueues == 0) {
    // We don't support recycling across threads and should just drop the item on the floor.
    return;
  }

  // we don't want to have a ref to the queue as the value in our weak map
  // so we null it out; to ensure there are no races with restoring it later
  // we impose a memory ordering here (no-op on x86)
  Map<Stack<?>, WeakOrderQueue> delayedRecycled = DELAYED_RECYCLED.get();
  WeakOrderQueue queue = delayedRecycled.get(this);
  if (queue == null) {
    if (delayedRecycled.size() >= maxDelayedQueues) {
      // Add a dummy queue so we know we should drop the object
      delayedRecycled.put(this, WeakOrderQueue.DUMMY);
      return;
    }
    // Check if we already reached the maximum number of delayed queues and if we can allocate at all.
    if ((queue = newWeakOrderQueue(thread)) == null) {
      // drop object
      return;
    }
    delayedRecycled.put(this, queue);
  } else if (queue == WeakOrderQueue.DUMMY) {
    // drop object
    return;
  }

  queue.add(item);
}
```

```java
// WeakOrderQueue
void add(DefaultHandle<?> handle) {
    handle.lastRecycledId = id;

    // While we also enforce the recycling ratio when we transfer objects from the WeakOrderQueue to the Stack
    // we better should enforce it as well early. Missing to do so may let the WeakOrderQueue grow very fast
    // without control
    if (handleRecycleCount < interval) {
        handleRecycleCount++;
        // Drop the item to prevent recycling to aggressive.
        return;
    }
    handleRecycleCount = 0;

    Link tail = this.tail;
    int writeIndex;
    if ((writeIndex = tail.get()) == LINK_CAPACITY) {
        Link link = head.newLink();
        if (link == null) {
            // Drop it.
            return;
        }
        // We allocate a Link so reserve the space
        this.tail = tail = tail.next = link;

        writeIndex = tail.get();
    }
    tail.elements[writeIndex] = handle;
    handle.stack = null;
    // we lazy set to ensure that setting stack to null appears before we unnull it in the owning thread;
    // this also means we guarantee visibility of an element in the queue if we see the index updated
    tail.lazySet(writeIndex + 1);
}
```

we keep a queue of per-thread queues, which is appended to once only, each time a new thread other than the stack owner recycles: when we run out of items in our stack we iterate this collection to scavenge those that can be reused. this permits us to incur minimal thread synchronisation whilst still recycling all items.

We store the Thread in a WeakReference as otherwise we may be the only ones that still hold a strong Reference to the Thread itself after it died because DefaultHandle will hold a reference to the Stack.
The biggest issue is if we do not use a WeakReference the Thread may not be able to be collected at all if the user will store a reference to the DefaultHandle somewhere and never clear this reference (or not clear it in a timely manner).

```java
// a queue that makes only moderate guarantees about visibility: items are seen in the correct order,
// but we aren't absolutely guaranteed to ever see anything at all, thereby keeping the queue cheap to maintain
private static final class WeakOrderQueue extends WeakReference<Thread> {

    static final WeakOrderQueue DUMMY = new WeakOrderQueue();

    // Let Link extend AtomicInteger for intrinsics. The Link itself will be used as writerIndex.
    @SuppressWarnings("serial")
    static final class Link extends AtomicInteger {
        final DefaultHandle<?>[] elements = new DefaultHandle[LINK_CAPACITY];

        int readIndex;
        Link next;
    }

    // Its important this does not hold any reference to either Stack or WeakOrderQueue.
    private static final class Head {
        private final AtomicInteger availableSharedCapacity;

        Link link;

        Head(AtomicInteger availableSharedCapacity) {
            this.availableSharedCapacity = availableSharedCapacity;
        }

        /**
         * Reclaim all used space and also unlink the nodes to prevent GC nepotism.
         */
        void reclaimAllSpaceAndUnlink() {
            Link head = link;
            link = null;
            int reclaimSpace = 0;
            while (head != null) {
                reclaimSpace += LINK_CAPACITY;
                Link next = head.next;
                // Unlink to help GC and guard against GC nepotism.
                head.next = null;
                head = next;
            }
            if (reclaimSpace > 0) {
                reclaimSpace(reclaimSpace);
            }
        }

        private void reclaimSpace(int space) {
            availableSharedCapacity.addAndGet(space);
        }

        void relink(Link link) {
            reclaimSpace(LINK_CAPACITY);
            this.link = link;
        }

        /**
         * Creates a new {@link} and returns it if we can reserve enough space for it, otherwise it
         * returns {@code null}.
         */
        Link newLink() {
            return reserveSpaceForLink(availableSharedCapacity) ? new Link() : null;
        }

        static boolean reserveSpaceForLink(AtomicInteger availableSharedCapacity) {
            for (;;) {
                int available = availableSharedCapacity.get();
                if (available < LINK_CAPACITY) {
                    return false;
                }
                if (availableSharedCapacity.compareAndSet(available, available - LINK_CAPACITY)) {
                    return true;
                }
            }
        }
    }

    // chain of data items
    private final Head head;
    private Link tail;
    // pointer to another queue of delayed items for the same stack
    private WeakOrderQueue next;
    private final int id = ID_GENERATOR.getAndIncrement();
    private final int interval;
    private int handleRecycleCount;

    private WeakOrderQueue() {
        super(null);
        head = new Head(null);
        interval = 0;
    }

    private WeakOrderQueue(Stack<?> stack, Thread thread) {
        super(thread);
        tail = new Link();

        // Its important that we not store the Stack itself in the WeakOrderQueue as the Stack also is used in
        // the WeakHashMap as key. So just store the enclosed AtomicInteger which should allow to have the
        // Stack itself GCed.
        head = new Head(stack.availableSharedCapacity);
        head.link = tail;
        interval = stack.delayedQueueInterval;
        handleRecycleCount = interval; // Start at interval so the first one will be recycled.
    }

    static WeakOrderQueue newQueue(Stack<?> stack, Thread thread) {
        // We allocated a Link so reserve the space
        if (!Head.reserveSpaceForLink(stack.availableSharedCapacity)) {
            return null;
        }
        final WeakOrderQueue queue = new WeakOrderQueue(stack, thread);
        // Done outside of the constructor to ensure WeakOrderQueue.this does not escape the constructor and so
        // may be accessed while its still constructed.
        stack.setHead(queue);

        return queue;
    }

    WeakOrderQueue getNext() {
        return next;
    }

    void setNext(WeakOrderQueue next) {
        assert next != this;
        this.next = next;
    }

    void reclaimAllSpaceAndUnlink() {
        head.reclaimAllSpaceAndUnlink();
        this.next = null;
    }

    void add(DefaultHandle<?> handle) {
        handle.lastRecycledId = id;

        // While we also enforce the recycling ratio when we transfer objects from the WeakOrderQueue to the Stack
        // we better should enforce it as well early. Missing to do so may let the WeakOrderQueue grow very fast
        // without control
        if (handleRecycleCount < interval) {
            handleRecycleCount++;
            // Drop the item to prevent recycling to aggressive.
            return;
        }
        handleRecycleCount = 0;

        Link tail = this.tail;
        int writeIndex;
        if ((writeIndex = tail.get()) == LINK_CAPACITY) {
            Link link = head.newLink();
            if (link == null) {
                // Drop it.
                return;
            }
            // We allocate a Link so reserve the space
            this.tail = tail = tail.next = link;

            writeIndex = tail.get();
        }
        tail.elements[writeIndex] = handle;
        handle.stack = null;
        // we lazy set to ensure that setting stack to null appears before we unnull it in the owning thread;
        // this also means we guarantee visibility of an element in the queue if we see the index updated
        tail.lazySet(writeIndex + 1);
    }

    boolean hasFinalData() {
        return tail.readIndex != tail.get();
    }

    // transfer as many items as we can from this queue to the stack, returning true if any were transferred
    @SuppressWarnings("rawtypes")
    boolean transfer(Stack<?> dst) {
        Link head = this.head.link;
        if (head == null) {
            return false;
        }

        if (head.readIndex == LINK_CAPACITY) {
            if (head.next == null) {
                return false;
            }
            head = head.next;
            this.head.relink(head);
        }

        final int srcStart = head.readIndex;
        int srcEnd = head.get();
        final int srcSize = srcEnd - srcStart;
        if (srcSize == 0) {
            return false;
        }

        final int dstSize = dst.size;
        final int expectedCapacity = dstSize + srcSize;

        if (expectedCapacity > dst.elements.length) {
            final int actualCapacity = dst.increaseCapacity(expectedCapacity);
            srcEnd = min(srcStart + actualCapacity - dstSize, srcEnd);
        }

        if (srcStart != srcEnd) {
            final DefaultHandle[] srcElems = head.elements;
            final DefaultHandle[] dstElems = dst.elements;
            int newDstSize = dstSize;
            for (int i = srcStart; i < srcEnd; i++) {
                DefaultHandle<?> element = srcElems[i];
                if (element.recycleId == 0) {
                    element.recycleId = element.lastRecycledId;
                } else if (element.recycleId != element.lastRecycledId) {
                    throw new IllegalStateException("recycled already");
                }
                srcElems[i] = null;

                if (dst.dropHandle(element)) {
                    // Drop the object.
                    continue;
                }
                element.stack = dst;
                dstElems[newDstSize ++] = element;
            }

            if (srcEnd == LINK_CAPACITY && head.next != null) {
                // Add capacity back as the Link is GCed.
                this.head.relink(head.next);
            }

            head.readIndex = srcEnd;
            if (dst.size == newDstSize) {
                return false;
            }
            dst.size = newDstSize;
            return true;
        } else {
            // The destination stack is full already.
            return false;
        }
    }
}
```

### Sample

*A 线程申请，A 线程回收的场景。*

- 显然，当对象的申请与回收是在一个线程中时，直接把对象放入到 A 线程的对象池中即可，不存在资源的竞争，简单轻松。

*A 线程申请，B 线程回收的场景。*

- 首先，当 A 线程通过其对象池申请了一个对象后，在 B 线程调用 recycle()方法回收该对象。显然，该对象是应该回收到 A 线程私有的对象池当中的，不然，该对象池也失去了其意义。
- 那么 B 线程中，并不会直接将该对象放入到 A 线程的对象池中，如果这样操作在多线程场景下存在资源的竞争，只有增加性能的开销，才能保证并发情况下的线程安全，显然不是 netty 想要看到的。
- 那么 B 线程会专门申请一个针对 A 线程回收的专属队列，在首次创建的时候会将该队列放入到 A 线程对象池的链表首节点（这里是唯一存在的资源竞争场景，需要加锁），并将被回收的对象放入到该专属队列中，宣告回收结束。
- 在 A 线程的对象池数组耗尽之后，将会尝试把各个别的线程针对 A 线程的专属队列里的对象重新放入到对象池数组中，以便下次继续使用。

## Allocator

```java
public class PooledByteBufAllocator extends AbstractByteBufAllocator implements ByteBufAllocatorMetricProvider {
    @Override
    protected ByteBuf newHeapBuffer(int initialCapacity, int maxCapacity) {
        PoolThreadCache cache = threadCache.get();
        PoolArena<byte[]> heapArena = cache.heapArena;

        final ByteBuf buf;
        if (heapArena != null) {
            buf = heapArena.allocate(cache, initialCapacity, maxCapacity);
        } else {
            buf = PlatformDependent.hasUnsafe() ?
                    new UnpooledUnsafeHeapByteBuf(this, initialCapacity, maxCapacity) :
                    new UnpooledHeapByteBuf(this, initialCapacity, maxCapacity);
        }

        return toLeakAwareBuffer(buf);
    }

    @Override
    protected ByteBuf newDirectBuffer(int initialCapacity, int maxCapacity) {
        PoolThreadCache cache = threadCache.get();
        PoolArena<ByteBuffer> directArena = cache.directArena;

        final ByteBuf buf;
        if (directArena != null) {
            buf = directArena.allocate(cache, initialCapacity, maxCapacity);
        } else {
            buf = PlatformDependent.hasUnsafe() ?
                    UnsafeByteBufUtil.newUnsafeDirectByteBuf(this, initialCapacity, maxCapacity) :
                    new UnpooledDirectByteBuf(this, initialCapacity, maxCapacity);
        }

        return toLeakAwareBuffer(buf);
    }

    protected static ByteBuf toLeakAwareBuffer(ByteBuf buf) {
        ResourceLeakTracker<ByteBuf> leak;
        switch (ResourceLeakDetector.getLevel()) {
            case SIMPLE:
                leak = AbstractByteBuf.leakDetector.track(buf);
                if (leak != null) {
                    buf = new SimpleLeakAwareByteBuf(buf, leak);
                }
                break;
            case ADVANCED:
            case PARANOID:
                leak = AbstractByteBuf.leakDetector.track(buf);
                if (leak != null) {
                    buf = new AdvancedLeakAwareByteBuf(buf, leak);
                }
                break;
            default:
                break;
        }
        return buf;
    }
}
```

外层入口只是「先建对象再填内存」的包装，真正按 sizeIdx 分流的是下面的 `allocate(cache, buf, reqCapacity)`：

```java
// PoolArena
PooledByteBuf<T> allocate(PoolThreadCache cache, int reqCapacity, int maxCapacity) {
    PooledByteBuf<T> buf = newByteBuf(maxCapacity);
    allocate(cache, buf, reqCapacity);
    return buf;
}
```

### Constructor

默认走池化 + 堆外，除非平台不可靠或显式关闭；`pageSize` / `chunkSize` / `nHeapArena` / `nDirectArena` 全部在这一步定下来。

```java
/**
 * Returns {@code true} if the platform has reliable low-level direct buffer access API and a user has not specified
 * {@code -Dio.netty.noPreferDirect} option.
 */
public static boolean directBufferPreferred() {
    return DIRECT_BUFFER_PREFERRED;
}
```

pageSize 8192

```java
public PooledByteBufAllocator(boolean preferDirect, int nHeapArena, int nDirectArena, int pageSize, int maxOrder,
                              int smallCacheSize, int normalCacheSize,
                              boolean useCacheForAllThreads, int directMemoryCacheAlignment) {
    super(preferDirect);
    threadCache = new PoolThreadLocalCache(useCacheForAllThreads);
    this.smallCacheSize = smallCacheSize;
    this.normalCacheSize = normalCacheSize;
    chunkSize = validateAndCalculateChunkSize(pageSize, maxOrder);

    checkPositiveOrZero(nHeapArena, "nHeapArena");
    checkPositiveOrZero(nDirectArena, "nDirectArena");

    checkPositiveOrZero(directMemoryCacheAlignment, "directMemoryCacheAlignment");
    if (directMemoryCacheAlignment > 0 && !isDirectMemoryCacheAlignmentSupported()) {
        throw new IllegalArgumentException("directMemoryCacheAlignment is not supported");
    }

    if ((directMemoryCacheAlignment & -directMemoryCacheAlignment) != directMemoryCacheAlignment) {
        throw new IllegalArgumentException("directMemoryCacheAlignment: "
                + directMemoryCacheAlignment + " (expected: power of two)");
    }

    int pageShifts = validateAndCalculatePageShifts(pageSize);

    if (nHeapArena > 0) {
        heapArenas = newArenaArray(nHeapArena);
        List<PoolArenaMetric> metrics = new ArrayList<PoolArenaMetric>(heapArenas.length);
        for (int i = 0; i < heapArenas.length; i ++) {
            PoolArena.HeapArena arena = new PoolArena.HeapArena(this,
                    pageSize, pageShifts, chunkSize,
                    directMemoryCacheAlignment);
            heapArenas[i] = arena;
            metrics.add(arena);
        }
        heapArenaMetrics = Collections.unmodifiableList(metrics);
    } else {
        heapArenas = null;
        heapArenaMetrics = Collections.emptyList();
    }

    if (nDirectArena > 0) {
        directArenas = newArenaArray(nDirectArena);
        List<PoolArenaMetric> metrics = new ArrayList<PoolArenaMetric>(directArenas.length);
        for (int i = 0; i < directArenas.length; i ++) {
            PoolArena.DirectArena arena = new PoolArena.DirectArena(
                    this, pageSize, pageShifts, chunkSize, directMemoryCacheAlignment);
            directArenas[i] = arena;
            metrics.add(arena);
        }
        directArenaMetrics = Collections.unmodifiableList(metrics);
    } else {
        directArenas = null;
        directArenaMetrics = Collections.emptyList();
    }
    metric = new PooledByteBufAllocatorMetric(this);
}
```

`PoolArena` 的字段布局与 `PoolChunkMetric` 契约见 [metrics](/docs/CS/Framework/Netty/memory.md?id=metrics)。

### Thread Cache Trim

线程本地缓存不能只进不出：`PoolThreadCache` 每个 size class 有 `freeSweepAllocationThreshold`（默认 8192）的配额，超过阈值仍没被用到的 `Entry` 会由 `trim()` 归还给 `PoolArena`，否则线程退出后缓存会一直占着 chunk。

```java

// 源码：buffer/src/main/java/io/netty/buffer/PoolThreadCache.java:411-426
// Free up cached {@link PoolChunk}s if not allocated frequently enough.
public final void trim() {
  int free = size - allocations;
  allocations = 0;

  // We not even allocated all the number that are
  if (free > 0) {
    free(free, false);
  }
}

private int free(int max, boolean finalizer) {
    int numFreed = 0;
    for (; numFreed < max; numFreed++) {
        Entry<T> entry = queue.poll();
        if (entry != null) {
            freeEntry(entry, finalizer);
        } else {
            // all cleared
            return numFreed;
        }
    }
    return numFreed;
}

private  void freeEntry(Entry entry, boolean finalizer) {
  PoolChunk chunk = entry.chunk;
  long handle = entry.handle;
  ByteBuffer nioBuffer = entry.nioBuffer;

  if (!finalizer) {
    // recycle now so PoolChunk can be GC'ed. This will only be done if this is not freed because of
    // a finalizer.
    entry.recycle();
  }

  chunk.arena.freeChunk(chunk, handle, entry.normCapacity, sizeClass, nioBuffer, finalizer);
}
```

`trim()` 的判据是 `size - allocations`：一个周期内分配次数没达到缓存容量，说明这些槽位是"死重量"，把差额个 `Entry` 还回去。`freeEntry()` 最终落到 `PoolArena.freeChunk()`，见 [free](/docs/CS/Framework/Netty/memory.md?id=free)。

注意 4.2 里 `freeEntry` 会**先把 `chunk` / `handle` / `nioBuffer` 三个字段读进局部变量再 `recycle()`**——因为 `recycle()` 会把 `handle` 置回 `-1`、`chunk` 置 `null`，顺序反了就会把无效数据传给 `freeChunk`（源码：`PoolThreadCache.java:411-426`，`Entry.recycle()` 见 `:439-444`）。

## Adaptive Allocator

Netty 4.2 把 [默认分配器](#introduction) 从 `PooledByteBufAllocator` 换成了 `AdaptiveByteBufAllocator`。这一节讲它是什么、为什么这样设计。

> 本节所有结论均以本仓库检出的 **4.2.19.Final** 为准（带 `源码：` 标注）。凡提及"早期版本 / 4.1"的对比，均来自本文件此前保留的旧片段，仓库内没有 4.1 源码可对照，仅供定性参考。

### AdaptiveByteBufAllocator

// 源码：buffer/src/main/java/io/netty/buffer/AdaptiveByteBufAllocator.java:23-32
```java
/**
 * An auto-tuning pooling {@link ByteBufAllocator}, that follows an anti-generational hypothesis.
 * <p>
 * <strong>Note:</strong> this allocator is <strong>experimental</strong>. It is recommended to roll out usage slowly,
 * and to carefully monitor application performance in the process.
 * <p>
 * See the {@link AdaptivePoolingAllocator} class documentation for implementation details.
 */
public final class AdaptiveByteBufAllocator extends AbstractByteBufAllocator
        implements ByteBufAllocatorMetricProvider, ByteBufAllocatorMetric {
```

它是 `final class`，**没有 `@UnstableApi` 注解**，"experimental" 只写在 Javadoc 里（反之，内部的 `AdaptivePoolingAllocator` 带 `@UnstableApi` 且是包级私有，源码：`AdaptivePoolingAllocator.java:84-85`）。三个构造器只有 `()`、`(boolean preferDirect)`、`(boolean preferDirect, boolean useCacheForNonEventLoopThreads)`，**没有 initial/min/max 容量参数**——容量默认值来自 `AbstractByteBufAllocator`（initial 256、max `Integer.MAX_VALUE`，源码：`AbstractByteBufAllocator.java:31-32`）。

无参构造器的 `preferDirect` 默认值是 `!PlatformDependent.isExplicitNoPreferDirect()`（源码：`AdaptiveByteBufAllocator.java:46-48`）——注意这里用的是 4.2 新增的 `isExplicitNoPreferDirect()`（只认显式 `-Dio.netty.noPreferDirect`），而不是 `PooledByteBufAllocator` 那条 `directBufferPreferred()` 的老路径。

内部持有**两个** `AdaptivePoolingAllocator` 实例：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptiveByteBufAllocator.java:54-68
```java
public AdaptiveByteBufAllocator(boolean preferDirect, boolean useCacheForNonEventLoopThreads) {
    super(preferDirect);
    direct = new AdaptivePoolingAllocator(new DirectChunkAllocator(this), useCacheForNonEventLoopThreads);
    heap = new AdaptivePoolingAllocator(new HeapChunkAllocator(this), useCacheForNonEventLoopThreads);
}

@Override
protected ByteBuf newHeapBuffer(int initialCapacity, int maxCapacity) {
    return toLeakAwareBuffer(heap.allocate(initialCapacity, maxCapacity));
}

@Override
protected ByteBuf newDirectBuffer(int initialCapacity, int maxCapacity) {
    return toLeakAwareBuffer(direct.allocate(initialCapacity, maxCapacity));
}
```

`ChunkAllocator` 是"chunk 从哪来"的回调：`HeapChunkAllocator` 产出 `UnpooledUnsafeHeapByteBuf` / `UnpooledHeapByteBuf`，`DirectChunkAllocator` 产出 `UnsafeByteBufUtil.newDirectByteBuf(...)`（源码：`AdaptiveByteBufAllocator.java:90-116`）——即**chunk 的最底层内存仍然是 unpooled 分配的，池化是在 chunk 之上做的切分**。

// 源码：buffer/src/main/java/io/netty/buffer/AdaptiveByteBufAllocator.java:34-41
```java
private static final boolean DEFAULT_USE_CACHED_MAGAZINES_FOR_NON_EVENT_LOOP_THREADS;

static {
    DEFAULT_USE_CACHED_MAGAZINES_FOR_NON_EVENT_LOOP_THREADS = SystemPropertyUtil.getBoolean(
            "io.netty.allocator.useCachedMagazinesForNonEventLoopThreads", false);
    logger.debug("-Dio.netty.allocator.useCachedMagazinesForNonEventLoopThreads: {}",
                 DEFAULT_USE_CACHED_MAGAZINES_FOR_NON_EVENT_LOOP_THREADS);
}
```

判断是否给当前线程建线程本地 magazine 的判据只有两个（源码：`AdaptivePoolingAllocator.java:233-238`）：`useCacheForNonEventLoopThreads || ThreadExecutorMap.currentExecutor() != null`。即只有 EventLoop 线程或显式打开该属性时才有线程本地 `MagazineGroup[]`；普通用户线程共用共享数组，避免虚拟线程场景下线程本地缓存爆炸。

4.2.19 还多一层"低内存"降级：`IS_LOW_MEM`（`Runtime.maxMemory() <= 512 MiB`，或 `-Dio.netty.allocator.lowMemory`）且 `DISABLE_THREAD_LOCAL_MAGAZINES_ON_LOW_MEM`（默认 `true`）时，`threadLocalGroup` 这个 `FastThreadLocal` 直接为 `null`，彻底不建线程本地组（源码：`AdaptivePoolingAllocator.java:87-96`、`:230-231`）。

> [!NOTE]
>
> 名字相近但层次完全不同的两个类：`AdaptiveByteBufAllocator`（`io.netty.buffer`，**内存分配器**）vs `AdaptiveRecvByteBufAllocator`（`io.netty.channel`，只**预测每次 read 该分配多少字节**）。别混。

### AdaptivePoolingAllocator

"anti-generational hypothesis（反代际假设）"是它与 jemalloc 风格池化最大的分歧点：传统池化假设"刚分配的对象很快会释放"，按对象生命周期分代；自适应分配器则假设**缓冲区的存活期与分配它的线程/任务绑定**，因此按 magazine 分片而不是按代回收。

结构自上而下是 `MagazineGroup[]` → `Magazine[]` → `Chunk` → `AdaptiveByteBuf`：

| 类                  | 声明                                                   | 关键字段                                                                                                        | 源码行号   |
| :----------------- | :--------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- | :----- |
| `MagazineGroup`    | `private static final class`                          | `threadLocalMagazine`、`volatile Magazine[] magazines`、`chunkCache`、`chunkManagementStrategy`、`StampedLock magazineExpandLock` | `:367` |
| `Magazine`         | `private static final class`                          | `Chunk current`、`volatile Chunk nextInLine`、`StampedLock allocationLock`、`AdaptiveRecycler recycler`       | `:1304` |
| `Chunk`            | `static class Chunk implements ChunkInfo`             | `AbstractByteBuf delegate`、`RefCnt refCnt`、`capacity`、`allocatedBytes`（bump pointer 游标）                  | `:1589` |
| `SizeClassedChunk` | `static class SizeClassedChunk extends Chunk`         | `segments`、`segmentSize`、`MpscIntQueue externalFreeList`、`IntStack localFreeList`、`ownerThread`、`volatile int state` | `:1793` |
| `BuddyChunk`       | `private static final class BuddyChunk extends Chunk` | `MIN_BUDDY_SIZE = 32768`、`byte[] buddies`、`MpscIntQueue freeList`                                         | `:1957` |

> `Chunk` 的引用计数用的正是 4.2 新增的 `io.netty.util.internal.RefCnt`（源码：`AdaptivePoolingAllocator.java:1594`），与 ByteBuf 同一个实现，详见 [ReferenceCounting](/docs/CS/Framework/Netty/ByteBuf.md?id=referencecounting)。

#### MagazineGroup per Size Class

一个容易看漏的关键点：**`AdaptivePoolingAllocator` 不是"一个 MagazineGroup 管所有尺寸"，而是每个 size class 各一个**，另有单独一组服务大 buffer：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:219-228
```java
private final ChunkAllocator chunkAllocator;
private final ChunkRegistry chunkRegistry;
private final MagazineGroup[] sizeClassedMagazineGroups;
private final MagazineGroup largeBufferMagazineGroup;
private final FastThreadLocal<MagazineGroup[]> threadLocalGroup;

AdaptivePoolingAllocator(ChunkAllocator chunkAllocator, boolean useCacheForNonEventLoopThreads) {
    this.chunkAllocator = ObjectUtil.checkNotNull(chunkAllocator, "chunkAllocator");
    chunkRegistry = new ChunkRegistry();
    sizeClassedMagazineGroups = createMagazineGroupSizeClasses(this, false);
    largeBufferMagazineGroup = new MagazineGroup(
            this, chunkAllocator, new BuddyChunkManagementStrategy(), false);
```

`createMagazineGroupSizeClasses()` 按 `SIZE_CLASSES` 逐档建组，每组配一个 `SizeClassChunkManagementStrategy(segmentSize)`（源码：`:251-260`）；`largeBufferMagazineGroup` 配 `BuddyChunkManagementStrategy`。于是分配入口就是"先定档、再定组"：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:266-286
```java
private AdaptiveByteBuf allocate(int size, int maxCapacity, Thread currentThread, AdaptiveByteBuf buf) {
    AdaptiveByteBuf allocated = null;
    if (size <= MAX_POOLED_BUF_SIZE) {
        final int index = sizeClassIndexOf(size);
        MagazineGroup[] magazineGroups;
        if (!FastThreadLocalThread.currentThreadWillCleanupFastThreadLocals() ||
                IS_LOW_MEM ||
                (magazineGroups = threadLocalGroup.get()) == null) {
            magazineGroups = sizeClassedMagazineGroups;
        }
        if (index < magazineGroups.length) {
            allocated = magazineGroups[index].allocate(size, maxCapacity, currentThread, buf);
        } else if (!IS_LOW_MEM) {
            allocated = largeBufferMagazineGroup.allocate(size, maxCapacity, currentThread, buf);
        }
    }
    if (allocated == null) {
        allocated = allocateFallback(size, maxCapacity, currentThread, buf);
    }
    return allocated;
}
```

三条路径的语义（默认 `MAX_CHUNK_SIZE = 8 MiB`，故 `MAX_POOLED_BUF_SIZE = 8 MiB / 8 = 1 MiB`）：

| 条件                                                                 | 走哪                                | 说明                                                 |
| :----------------------------------------------------------------- | :-------------------------------- | :------------------------------------------------- |
| `size <= MAX_POOLED_BUF_SIZE` 且 size class 命中（≤ 16896 B）               | 对应 size class 的 `MagazineGroup`    | 常规路径，chunk 按该档 `segmentSize` 切段                     |
| `size <= MAX_POOLED_BUF_SIZE` 但 `index == SIZE_CLASSES_COUNT`（> 16896 B） | `largeBufferMagazineGroup`（Buddy） | `IS_LOW_MEM` 时放弃此路、直接 fallback                      |
| `size > MAX_POOLED_BUF_SIZE`（> 1 MiB）                                | `allocateFallback()`              | 造一个一次性 chunk，**不池化**，等价于 `PooledByteBufAllocator` 的 Huge 路径 |

`sizeClassIndexOf` 不是线性查找，而是一张按 32 字节粒度预建的 `byte[] SIZE_INDEXES` 查找表（源码：`:288-299`，静态初始化在 `:201-215`），`O(1)` 命中。

#### ChunkManagementStrategy and ChunkController

切分策略被抽成两个接口，这也是 4.2 里"自适应"真正的落点：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:1161-1177
```java
private interface ChunkManagementStrategy {
    ChunkController createController(MagazineGroup group);

    ChunkCache createChunkCache(boolean isThreadLocal);
}

private interface ChunkController {
    /**
     * Compute the "fast max capacity" value for the buffer.
     */
    int computeBufferCapacity(int requestedSize, int maxCapacity, boolean isReallocation);

    /**
     * Allocate a new {@link Chunk} for the given {@link Magazine}.
     */
    Chunk newChunkAllocation(int promptingSize, Magazine magazine);
}
```

| 实现                                 | `computeBufferCapacity`                          | `newChunkAllocation`                                                                            | chunk 缓存                            |
| :--------------------------------- | :----------------------------------------------- | :---------------------------------------------------------------------------------------------- | :---------------------------------- |
| `SizeClassChunkController`（`:1203`） | `Math.min(segmentSize, maxCapacity)`             | 固定 `chunkSize = max(MIN_CHUNK_SIZE, segmentSize * 32)`                                           | `SizeClassedChunkCache`（线程本地 / 共享两种）  |
| `BuddyChunkController`（`:1273`）     | `safeFindNextPositivePowerOfTwo(requestedSize)`  | `min(MAX_CHUNK_SIZE, max(maxChunkSize, nextPow2(BUFS_PER_CHUNK * promptingSize)))`，并单调抬高 `maxChunkSize` | `ConcurrentSkipListChunkCache`      |

"记忆峰值"就是自适应的全部——`maxChunkSize` 是 `BuddyChunkManagementStrategy` 里的一个 `AtomicInteger`，只增不减：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:1290-1300
```java
public Chunk newChunkAllocation(int promptingSize, Magazine magazine) {
    int maxChunkSize = this.maxChunkSize.get();
    int proposedChunkSize = MathUtil.safeFindNextPositivePowerOfTwo(BUFS_PER_CHUNK * promptingSize);
    int chunkSize = Math.min(MAX_CHUNK_SIZE, Math.max(maxChunkSize, proposedChunkSize));
    if (chunkSize > maxChunkSize) {
        // Update our stored max chunk size. It's fine that this is racy.
        this.maxChunkSize.set(chunkSize);
    }
    BuddyChunk chunk = new BuddyChunk(chunkAllocator.allocate(chunkSize, chunkSize), magazine);
    chunkRegistry.add(chunk);
```

`MIN_SEGMENTS_PER_CHUNK = 32` 的注释解释了为什么是 32："To amortize activation/deactivation of chunks, we should have a minimum number of segments per chunk... For segments of 16 KiB, the chunks will be half a megabyte."（源码：`:1180-1183`）。

#### Magazine.tryAllocate

取 magazine 的方式不是简单轮转：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:416-441
```java
long threadId = currentThread.getId();
Magazine[] mags;
int expansions = 0;
do {
    mags = magazines;
    int mask = mags.length - 1;
    int index = (int) (threadId & mask);
    for (int i = 0, m = mags.length << 1; i < m; i++) {
        Magazine mag = mags[index + i & mask];
        if (buf == null) {
            buf = mag.newBuffer();
        }
        if (mag.tryAllocate(size, maxCapacity, buf, reallocate)) {
            // Was able to allocate.
            return buf;
        }
    }
    expansions++;
} while (expansions <= EXPANSION_ATTEMPTS && tryExpandMagazines(mags.length));
```

先按 `threadId & (length - 1)` 直接定位；失败才在数组内轮转最多 `2 * length` 次；仍失败则 `tryExpandMagazines()` 把数组翻倍（上限 `MAX_STRIPES`），最多 `EXPANSION_ATTEMPTS = 3` 次。初始长度 `INITIAL_MAGAZINES = 1`。

`MAX_STRIPES` 在 4.2.19 是 **`IS_LOW_MEM ? 1 : NettyRuntime.availableProcessors() * 2`**（源码：`:109`）——低内存机器上不做分片。另外线程本地 magazine 组走的完全是另一条路：它没有 `magazines` 数组竞争，直接 `threadLocalMagazine.tryAllocate(...)` 并 `assert allocated`（源码：`:405-414`）。

`Magazine.tryAllocate` 用 `StampedLock.tryWriteLock()`，拿不到锁时不阻塞、改走无锁回退，这是降低竞争的关键：

// 源码：buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:1363-1415
```java
public boolean tryAllocate(int size, int maxCapacity, AdaptiveByteBuf buf, boolean reallocate) {
    if (allocationLock == null) {
        // This magazine is not shared across threads, just allocate directly.
        return allocate(size, maxCapacity, buf, reallocate);
    }

    // Try to retrieve the lock and if successful allocate.
    long writeLock = allocationLock.tryWriteLock();
    if (writeLock != 0) {
        try {
            return allocate(size, maxCapacity, buf, reallocate);
        } finally {
            allocationLock.unlockWrite(writeLock);
        }
    }
    return allocateWithoutLock(size, maxCapacity, buf);
}

private boolean allocateWithoutLock(int size, int maxCapacity, AdaptiveByteBuf buf) {
    Chunk curr = NEXT_IN_LINE.getAndSet(this, null);
    if (curr == MAGAZINE_FREED) {
        // Allocation raced with a stripe-resize that freed this magazine.
        restoreMagazineFreed();
        return false;
    }
    if (curr == null) {
        curr = group.pollChunk(size);
        if (curr == null) {
            return false;
        }
        curr.attachToMagazine(this);
    }
    boolean allocated = false;
    int remainingCapacity = curr.remainingCapacity();
    int startingCapacity = chunkController.computeBufferCapacity(
            size, maxCapacity, true /* never update stats as we don't hold the magazine lock */);
    if (remainingCapacity >= size &&
            curr.readInitInto(buf, size, Math.min(remainingCapacity, startingCapacity), maxCapacity)) {
        allocated = true;
        remainingCapacity = curr.remainingCapacity();
    }
    try {
        if (remainingCapacity >= RETIRE_CAPACITY) {
            transferToNextInLineOrRelease(curr);
            curr = null;
        }
    } finally {
        if (curr != null) {
            curr.releaseFromMagazine();
        }
    }
    return allocated;
}
```

回退路径的语义要读清楚：**拿不到锁就只能借**——先 `getAndSet` 抢占 `nextInLine` 的"候补 chunk"，抢不到再向组的 `chunkCache` 要，两者都没有就直接返回 `false`（交给外层换下一个 magazine）。而且 `computeBufferCapacity(..., true)` 的第三个参数是 `isReallocation = true`，注释注明"never update stats as we don't hold the magazine lock"——即无锁路径**不参与自适应统计**。

持锁路径 `allocate(...)` 是"当前 chunk → nextInLine → chunkCache → 新 chunk"四级瀑布，并用 `RETIRE_CAPACITY = 256` 判定一个 chunk 是否还值得留在 `nextInLine`（源码：`:108`、`:1417-1514`）。

#### Chunk Splitting

切分算法有三套：

- 基类 `Chunk` 是朴素游标：`startIndex = allocatedBytes; allocatedBytes = startIndex + startingCapacity;`（源码：`AdaptivePoolingAllocator.java:1697-1699`）
- `SizeClassedChunk` 用**双空闲表**：owner 线程从 `IntStack localFreeList` pop，非 owner 线程 offer 到 `MpscIntQueue externalFreeList`（不是位图）。是否启用 `localFreeList` 取决于 `ownerThread` 是否为 `null`——非线程本地组只有 `externalFreeList`（源码：`:1808-1825`）
- `BuddyChunk` 走伙伴算法，最小粒度 `MIN_BUDDY_SIZE = 32768`，每 byte 编码 `[1: is claimed][1: has claimed children][30: MIN_BUDDY_SIZE shift to get size]`（源码：`:1958-1966`）

size class 共 **16 档**（源码：`buffer/src/main/java/io/netty/buffer/AdaptivePoolingAllocator.java:179-196`）：

```java
private static final int[] SIZE_CLASSES = {
        32,
        64,
        128,
        256,
        512,
        640, // 512 + 128
        1024,
        1152, // 1024 + 128
        2048,
        2304, // 2048 + 256
        4096,
        4352, // 4096 + 256
        8192,
        8704, // 8192 + 512
        16384,
        16896, // 16384 + 512
};
```

注意最小档是 **32 字节**（不是 `PooledByteBufAllocator` 的 16 字节），且静态初始化里断言每档都必须是 32 的倍数：`assert (sizeClass & 31) == 0`（源码：`:210`）。

设计注释原文（`:167-178`）："Most allocations, particularly ones above 256 bytes, aim to be a power-of-2... we seem to get a lot of mileage out of having both power-of-2 sizes, and power-of-2-plus-a-bit."——即在 2 的幂之外额外加一档"幂 + 一点"，覆盖带定长头的协议包。

关键常量（源码：`:105-165`）：

```java
static final int MIN_CHUNK_SIZE = 128 * 1024;
private static final int EXPANSION_ATTEMPTS = 3;
private static final int INITIAL_MAGAZINES = 1;
private static final int RETIRE_CAPACITY = 256;
private static final int MAX_STRIPES = IS_LOW_MEM ? 1 : NettyRuntime.availableProcessors() * 2;
private static final int BUFS_PER_CHUNK = 8; // For large buffers, aim to have about this many buffers per chunk.
private static final int MAX_CHUNK_SIZE = IS_LOW_MEM ?
        2 * 1024 * 1024 : // 2 MiB for systems with small heaps.
        8 * 1024 * 1024; // 8 MiB.
private static final int MAX_POOLED_BUF_SIZE = MAX_CHUNK_SIZE / BUFS_PER_CHUNK;
```

另外两个与缓存容量相关的开关（源码：`:127-165`）：`CHUNK_REUSE_QUEUE`（默认 `availableProcessors() * 2`，chunk 跨 magazine 共享的复用队列容量）、`THREAD_LOCAL_CACHE_MAX_BYTES`（默认 8 MiB，每 size class 线程本地 chunk 缓存的**上限**）与 `THREAD_LOCAL_CACHE_MIN_BYTES`（默认上限的一半，purge 的**保留下限**，写成"clamped to MAX if configured exceeds it"，两者相等时等于关掉 purge 驱逐）。magazine 本地的 buffer 对象队列容量是 `MAGAZINE_BUFFER_QUEUE_CAPACITY`（默认 1024，且 `< 2` 会在静态初始化里抛 `IllegalArgumentException`）。

`MIN_CHUNK_SIZE` 取 128 KiB 的注释理由是"encourage the system allocator to delegate to mmap for chunk allocations... glibc will do this"（源码：`:98-104`），即把 chunk 大小的碎片推给虚拟内存而不是物理内存。

内存还给 OS 的路径：`AdaptiveByteBuf.deallocate()` → `chunk.releaseSegment(...)` → 基类 `Chunk` 的实现就是 `release()`（源码：`:1660-1662`）→ `RefCnt.release` 减到 0 → `deallocate()` → `chunkRegistry.remove(this)` + `delegate.release()`（源码：`:1669-1674`）。`SizeClassedChunk` 另有 `DEALLOCATED = Integer.MIN_VALUE` 状态机（源码：`:1798`），保证迟到的跨线程 `releaseSegment` 在算术上无害。

此外还有 purge 机制：`CHUNK_PURGE_POLLS_THREAD_LOCAL=16` / `CHUNK_PURGE_POLLS_SHARED=128` 次 poll 后扫描，连续 `CHUNK_PURGE_THRESHOLD=3` 个周期空闲即驱逐空闲 chunk（保留 `purgeRetentionFloor` / `CHUNK_REUSE_QUEUE` 的保留下限）。缓存实现有三套，按是否线程本地分派：

| 缓存实现                                  | 用于                | 结构                                       | 源码行号   |
| :----------------------------------- | :---------------- | :--------------------------------------- | :----- |
| `ThreadLocalSizeClassedChunkCache`   | 线程本地 magazine 组   | SPSC 环形缓冲区，按 `purgeEpoch` 三路分区（荷兰旗）        | `:666` |
| `SharedSizeClassedChunkCache`        | 共享 size class 组   | FIFO 队列 + `AtomicLong purgeBudget`       | `:917` |
| `ConcurrentSkipListChunkCache`       | Buddy（大 buffer）组  | `ConcurrentSkipListMap`，按容量排序取最小可用 chunk | `:1069` |

### Difference from PooledByteBufAllocator

| 维度       | `AdaptivePoolingAllocator`（4.2）                              | `PooledByteBufAllocator`                     |
| :------- | :----------------------------------------------------------- | :------------------------------------------- |
| 规格划分     | 16 档固定 size class（32 B 起，32 的倍数）；1 MiB 以内走 size class / Buddy，超出不池化 | 68 档 size class（16 B 起）+ `PoolSubpage`；超出 chunkSize 为 Huge，不池化 |
| chunk 大小 | `max(128 KiB, segmentSize * 32)`；大 buffer 侧 `maxChunkSize` 单调增长记忆峰值 | 固定 `pageSize << maxOrder` = 8 KiB << 9 = 4 MiB |
| 线程缓存     | `ThreadLocalSizeClassedChunkCache`（每档上限 8 MiB，`threadLocalChunkCacheMaxBytes`）+ magazine 本地 buffer 队列（1024） | `PoolThreadCache`（`MemoryRegionCache` 队列 + `freeSweepAllocationThreshold`） |
| 竞争削减     | 每 size class 一组 magazine + `tryWriteLock` 无锁回退 + 数组按需翻倍（上限 `MAX_STRIPES`） | Arena 分片（`availableProcessors() * 2`）+ `PoolThreadCache` |
| 锁         | `StampedLock`（`allocationLock` / `magazineExpandLock`）、`AtomicIntegerFieldUpdater`、MPSC 队列 | `ReentrantLock`（`PoolArena.lock`、`PoolSubpage.head.lock`、`runsAvailLock`） |
| 引用计数     | `Chunk` 用 4.2 的 `RefCnt`（与 ByteBuf 同一实现）                       | `PooledByteBuf` 走 `AbstractReferenceCountedByteBuf` → `RefCnt` |
| 统计自适应    | 类 Javadoc 仍描述 histogram / 99-percentile，但**当前代码中已无 histogram**，自适应改由 `ChunkController` 与 `AtomicInteger maxChunkSize` 承担 | 固定策略，无自适应                                    |

> [!WARNING]
>
> 上面最后一行的"文档与实现脱节"在 **4.2.19.Final** 上实测仍然成立：`AdaptivePoolingAllocator` 的类 Javadoc 完整描述了 histogram 与"big enough to service 10 allocations of the 99-percentile size"（源码：`:70-72`），但全文件中 `histogram` 只出现 2 次，**都在这段 Javadoc 与 `MAX_CHUNK_SIZE` 的注释里**（`:70`、`:115`），没有任何对应的数据结构。读这段 Javadoc 时不要当真。
>
> 该类的实现在 4.2.x 迭代中变化很快（早期版本用位图分配，后来换成空闲表 + Buddy，4.2.19 又加了 per-size-class magazine 组、三种 chunk cache 与 purge 机制），本文以 **4.2.19.Final** 为准。

## Recv Allocator

guess size of buf, actual allocate using Allocator

## Type

- PoolThreadCache
- PoolArena
- PoolChunk

## PoolChunk

Notation: The following terms are important:

- page  - a page is the smallest unit of memory chunk that can be allocated
- run   - a run is a collection of pages
- chunk - a chunk is a collection of runs

chunkSize = maxPages * pageSize

To begin we allocate a byte array of size = chunkSize 
Whenever a ByteBuf of given size needs to be created we search for the first position in the byte array 
that has enough empty space to accommodate the requested size and return a (long) handle that encodes this offset information, 
(this memory segment is then marked as reserved so it is always used by exactly one ByteBuf and no more)

For simplicity all sizes are normalized according to PoolArena.size2SizeIdx(int) method. 
This ensures that when we request for memory segments of size > pageSize the normalizedCapacity equals the next nearest size in SizeClasses.

A chunk has the following layout:
```
    /-----------------\
    | run             |
    |                 |
    |                 |
    |-----------------|
    | run             |
    |                 |
    |-----------------|
    | unalloctated    |
    | (freed)         |
    |                 |
    |-----------------|
    | subpage         |
    |-----------------|
    | unallocated     |
    | (freed)         |
    | ...             |
    | ...             |
    | ...             |
    |                 |
    |                 |
    |                 |
    \-----------------/
```

handle:

a handle is a long number, the bit layout of a run looks like:
oooooooo ooooooos ssssssss ssssssue bbbbbbbb bbbbbbbb bbbbbbbb bbbbbbbb
o: runOffset (page offset in the chunk), 15bit
s: size (number of pages) of this run, 15bit
u: isUsed?, 1bit
e: isSubpage?, 1bit
b: bitmapIdx of subpage, zero if it's not subpage, 32bit



runsAvailMap:

a map which manages all runs (used and not in used).
For each run, the first runOffset and last runOffset are stored in runsAvailMap.
key: runOffset
value: handle

runsAvail:

an array of [PriorityQueue](/docs/CS/Java/JDK/Collection/Queue.md?id=priorityqueue).
Each queue manages same size of runs.
Runs are sorted by offset, so that we always allocate runs with smaller offset.


### Algorithm

As we allocate runs, we update values stored in runsAvailMap and runsAvail so that the property is maintained.
Initialization -
In the beginning we store the initial run which is the whole chunk.
The initial run:
- runOffset = 0
- size = chunkSize
- isUsed = no
- isSubpage = no
- bitmapIdx = 0

#### allocate

chunk 层的入口，按 sizeIdx 决定走 subpage 还是整 run：

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:325-368
```java
boolean allocate(PooledByteBuf<T> buf, int reqCapacity, int sizeIdx, PoolThreadCache cache) {
    final long handle;
    if (sizeIdx <= arena.sizeClass.smallMaxSizeIdx) {
        final PoolSubpage<T> nextSub;
        // small
        // Obtain the head of the PoolSubPage pool that is owned by the PoolArena and synchronize on it.
        // This is need as we may add it back and so alter the linked-list structure.
        PoolSubpage<T> head = arena.smallSubpagePools[sizeIdx];
        head.lock();
        try {
            nextSub = head.next;
            if (nextSub != head) {
                assert nextSub.doNotDestroy && nextSub.elemSize == arena.sizeClass.sizeIdx2size(sizeIdx) :
                        "doNotDestroy=" + nextSub.doNotDestroy + ", elemSize=" + nextSub.elemSize + ", sizeIdx=" +
                                sizeIdx;
                handle = nextSub.allocate();
                assert handle >= 0;
                assert isSubpage(handle);
                nextSub.chunk.initBufWithSubpage(buf, null, handle, reqCapacity, cache, false);
                return true;
            }
            handle = allocateSubpage(sizeIdx, head);
            if (handle < 0) {
                return false;
            }
            assert isSubpage(handle);
        } finally {
            head.unlock();
        }
    } else {
        // normal
        // runSize must be multiple of pageSize
        int runSize = arena.sizeClass.sizeIdx2size(sizeIdx);
        handle = allocateRun(runSize);
        if (handle < 0) {
            return false;
        }
        assert !isSubpage(handle);
    }

    ByteBuffer nioBuffer = cachedNioBuffers != null? cachedNioBuffers.pollLast() : null;
    initBuf(buf, nioBuffer, handle, reqCapacity, cache, false);
    return true;
}
```

> [!NOTE]
>
> 4.2 里 Small 分支**多了一条"链表非空就直接返回"的快路径**：`head.next != head` 时直接从那个 subpage 取槽位并 `return true`，只有链表为空（该 size class 在本 chunk 内尚无 subpage）才 `allocateSubpage(sizeIdx, head)`。4.1 的写法是无条件 `allocateSubpage(sizeIdx)`，由后者内部再判断。

#### allocateRun

1. find the first avail run using in runsAvails according to size
2. if pages of run is larger than request pages then split it, and save the tailing run for later using

> [!NOTE]
>
> 锁是显式的 `ReentrantLock runsAvailLock`（源码：`buffer/src/main/java/io/netty/buffer/PoolChunk.java:168`、`:213`）。另外 `runsAvail` 队列里存的是**去掉低 32 位 bitmapIdx 的 int**，取出后要 `handle <<= BITMAP_IDX_BIT_LENGTH` 还原成完整的 long handle，再 `removeAvailRun0(handle)` 从 `runsAvailMap` 摘掉首尾记录。

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:370-399
```java
private long allocateRun(int runSize) {
    int pages = runSize >> pageShifts;
    int pageIdx = arena.sizeClass.pages2pageIdx(pages);

    runsAvailLock.lock();
    try {
        //find first queue which has at least one big enough run
        int queueIdx = runFirstBestFit(pageIdx);
        if (queueIdx == -1) {
            return -1;
        }

        //get run with min offset in this queue
        IntPriorityQueue queue = runsAvail[queueIdx];
        long handle = queue.poll();
        assert handle != IntPriorityQueue.NO_VALUE;
        handle <<= BITMAP_IDX_BIT_LENGTH;
        assert !isUsed(handle) : "invalid handle: " + handle;

        removeAvailRun0(handle);

        handle = splitLargeRun(handle, pages);

        int pinnedSize = runSize(pageShifts, handle);
        freeBytes -= pinnedSize;
        return handle;
    } finally {
        runsAvailLock.unlock();
    }
}
```

"逐级向上找"的具体实现是 `runFirstBestFit`，它还有一个"整块空闲"的短路：

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:426-437
```java
private int runFirstBestFit(int pageIdx) {
    if (freeBytes == chunkSize) {
        return arena.sizeClass.nPSizes - 1;
    }
    for (int i = pageIdx; i < arena.sizeClass.nPSizes; i++) {
        IntPriorityQueue queue = runsAvail[i];
        if (queue != null && !queue.isEmpty()) {
            return i;
        }
    }
    return -1;
}
```

切分是**一次切到位**，不会像内核伙伴系统那样逐级减半——多余的尾部直接作为一个新的 avail run 插回去：

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:439-462
```java
private long splitLargeRun(long handle, int needPages) {
    assert needPages > 0;

    int totalPages = runPages(handle);
    assert needPages <= totalPages;

    int remPages = totalPages - needPages;

    if (remPages > 0) {
        int runOffset = runOffset(handle);

        // keep track of trailing unused pages for later use
        int availOffset = runOffset + needPages;
        long availRun = toRunHandle(availOffset, remPages, 0);
        insertAvailRun(availOffset, remPages, availRun);

        // not avail
        return toRunHandle(runOffset, needPages, 1);
    }

    //mark it as used
    handle |= 1L << IS_USED_SHIFT;
    return handle;
}
```

#### allocateSubpage

1. find a not full subpage according to size.
   if it already exists just return, otherwise allocate a new PoolSubpage and call init() note that this subpage object is added to subpagesPool in the PoolArena when we init() it
2. call subpage.allocate()

4.2 的签名是 `allocateSubpage(int sizeIdx, PoolSubpage<T> head)`——head 由调用方 `PoolChunk.allocate` 传入（调用方已持有 `head.lock()`），所以方法内**既不重新取 head、也不重复加锁**。

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:473-491
```java
private long allocateSubpage(int sizeIdx, PoolSubpage<T> head) {
    //allocate a new run
    int runSize = calculateRunSize(sizeIdx);
    //runSize must be multiples of pageSize
    long runHandle = allocateRun(runSize);
    if (runHandle < 0) {
        return -1;
    }

    int runOffset = runOffset(runHandle);
    assert subpages[runOffset] == null;
    int elemSize = arena.sizeClass.sizeIdx2size(sizeIdx);

    PoolSubpage<T> subpage = new PoolSubpage<T>(head, this, pageShifts, runOffset,
            runSize(pageShifts, runHandle), elemSize);

    subpages[runOffset] = subpage;
    return subpage.allocate();
}
```

runSize 取"pageSize 与 elemSize 的最小公倍数"，但受一个上限约束：槽位数不能超过 `1 << (pageShifts - LOG2_QUANTUM)`（默认 512），超过就往回收一页。这就是"16 B 规格拿 1 个 page 分成 512 份、28 KiB 规格拿 7 个 page 分成 2 份"的算法依据：

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:401-424
```java
private int calculateRunSize(int sizeIdx) {
    int maxElements = 1 << pageShifts - SizeClasses.LOG2_QUANTUM;
    int runSize = 0;
    int nElements;

    final int elemSize = arena.sizeClass.sizeIdx2size(sizeIdx);

    //find lowest common multiple of pageSize and elemSize
    do {
        runSize += pageSize;
        nElements = runSize / elemSize;
    } while (nElements < maxElements && runSize != nElements * elemSize);

    while (nElements > maxElements) {
        runSize -= pageSize;
        nElements = runSize / elemSize;
    }

    assert nElements > 0;
    assert runSize <= chunkSize;
    assert runSize >= elemSize;

    return runSize;
}
```

#### free

1. if it is a subpage, return the slab back into this subpage
2. if the subpage is not used or it is a run, then start free this run
3. merge continuous avail runs
4. save the merged run

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:500-546
```java
void free(long handle, int normCapacity, ByteBuffer nioBuffer) {
    if (isSubpage(handle)) {
        int sIdx = runOffset(handle);
        PoolSubpage<T> subpage = subpages[sIdx];
        assert subpage != null;
        PoolSubpage<T> head = subpage.chunk.arena.smallSubpagePools[subpage.headIndex];
        // Obtain the head of the PoolSubPage pool that is owned by the PoolArena and synchronize on it.
        // This is need as we may add it back and so alter the linked-list structure.
        head.lock();
        try {
            assert subpage.doNotDestroy;
            if (subpage.free(head, bitmapIdx(handle))) {
                //the subpage is still used, do not free it
                return;
            }
            assert !subpage.doNotDestroy;
            // Null out slot in the array as it was freed and we should not use it anymore.
            subpages[sIdx] = null;
        } finally {
            head.unlock();
        }
    }

    int runSize = runSize(pageShifts, handle);
    //start free run
    runsAvailLock.lock();
    try {
        // collapse continuous runs, successfully collapsed runs
        // will be removed from runsAvail and runsAvailMap
        long finalRun = collapseRuns(handle);

        //set run as not used
        finalRun &= ~(1L << IS_USED_SHIFT);
        //if it is a subpage, set it to run
        finalRun &= ~(1L << IS_SUBPAGE_SHIFT);

        insertAvailRun(runOffset(finalRun), runPages(finalRun), finalRun);
        freeBytes += runSize;
    } finally {
        runsAvailLock.unlock();
    }

    if (nioBuffer != null && cachedNioBuffers != null &&
        cachedNioBuffers.size() < PooledByteBufAllocator.DEFAULT_MAX_CACHED_BYTEBUFFERS_PER_CHUNK) {
        cachedNioBuffers.offer(nioBuffer);
    }
}
```

合并是双向的，`collapsePast` 向前吞、`collapseNext` 向后吞，两者都是循环直到不再连续：

// 源码：buffer/src/main/java/io/netty/buffer/PoolChunk.java:548-598
```java
private long collapseRuns(long handle) {
    return collapseNext(collapsePast(handle));
}

private long collapsePast(long handle) {
    for (;;) {
        int runOffset = runOffset(handle);
        int runPages = runPages(handle);

        long pastRun = getAvailRunByOffset(runOffset - 1);
        if (pastRun == -1) {
            return handle;
        }

        int pastOffset = runOffset(pastRun);
        int pastPages = runPages(pastRun);

        //is continuous
        if (pastRun != handle && pastOffset + pastPages == runOffset) {
            //remove past run
            removeAvailRun(pastRun);
            handle = toRunHandle(pastOffset, pastPages + runPages, 0);
        } else {
            return handle;
        }
    }
}

private long collapseNext(long handle) {
    for (;;) {
        int runOffset = runOffset(handle);
        int runPages = runPages(handle);

        long nextRun = getAvailRunByOffset(runOffset + runPages);
        if (nextRun == -1) {
            return handle;
        }

        int nextOffset = runOffset(nextRun);
        int nextPages = runPages(nextRun);

        //is continuous
        if (nextRun != handle && runOffset + runPages == nextOffset) {
            //remove next run
            removeAvailRun(nextRun);
            handle = toRunHandle(runOffset, runPages + nextPages, 0);
        } else {
            return handle;
        }
    }
}
```

`PoolArena.freeChunk()` 是归还的终点：先把 chunk 从 `PoolChunkList` 摘掉判断是否需要销毁，锁外再真正 `destroyChunk`，避免持锁期间触发 unmap。

// 源码：buffer/src/main/java/io/netty/buffer/PoolArena.java:259-290
```java
void freeChunk(PoolChunk<T> chunk, long handle, int normCapacity, SizeClass sizeClass, ByteBuffer nioBuffer,
               boolean finalizer) {
    final boolean destroyChunk;
    lock();
    try {
        // We only call this if freeChunk is not called because of the PoolThreadCache finalizer as otherwise this
        // may fail due lazy class-loading in for example tomcat.
        if (!finalizer) {
            switch (sizeClass) {
                case Normal:
                    ++deallocationsNormal;
                    break;
                case Small:
                    ++deallocationsSmall;
                    break;
                default:
                    throw new Error("Unexpected size class: " + sizeClass);
            }
        }
        destroyChunk = !chunk.parent.free(chunk, handle, normCapacity, nioBuffer);
        if (destroyChunk) {
            // all other destroyChunk calls come from the arena itself being finalized, so don't need to be counted
            ++pooledChunkDeallocations;
        }
    } finally {
        unlock();
    }
    if (destroyChunk) {
        // destroyChunk not need to be called while holding the synchronized lock.
        destroyChunk(chunk);
    }
}
```

> [!NOTE]
>
> 4.2 里这里是 `lock()` / `unlock()`（`PoolArena` 自己的 `ReentrantLock`），另外新增了 `++pooledChunkDeallocations` 计数，与 `allocateNormal` 里的 `++pooledChunkAllocations` 配成一对。

## PoolSubpage

一个 subpage 是「一页切成的等大槽位」，用 bitmap 记录哪个槽空闲，`allocate()` 返回的就是 handle 低位里那个 `bitmapIdx`。

字段布局（源码：`buffer/src/main/java/io/netty/buffer/PoolSubpage.java:30-45`）：`long[] bitmap`（每 bit 一个槽）、`bitmapLength`、`maxNumElems`、`numAvail`、`nextAvail`，以及把自己串进 `PoolArena.smallSubpagePools[headIndex]` 双向链表的 `prev` / `next`。

// 源码：buffer/src/main/java/io/netty/buffer/PoolSubpage.java:87-112
```java
/**
 * Returns the bitmap index of the subpage allocation.
 */
long allocate() {
    if (numAvail == 0 || !doNotDestroy) {
        return -1;
    }

    final int bitmapIdx = getNextAvail();
    if (bitmapIdx < 0) {
        removeFromPool(); // Subpage appear to be in an invalid state. Remove to prevent repeated errors.
        throw new AssertionError("No next available bitmap index found (bitmapIdx = " + bitmapIdx + "), " +
                "even though there are supposed to be (numAvail = " + numAvail + ") " +
                "out of (maxNumElems = " + maxNumElems + ") available indexes.");
    }
    int q = bitmapIdx >>> 6;
    int r = bitmapIdx & 63;
    assert (bitmap[q] >>> r & 1) == 0;
    bitmap[q] |= 1L << r;

    if (-- numAvail == 0) {
        removeFromPool();
    }

    return toHandle(bitmapIdx);
}
```

`numAvail` 减到 0 就 `removeFromPool()`——这就是"满了的 subpage 会离开链表"的实现，下一次该 size class 的分配便不会再遍历到它。

**局部性来自 `nextAvail` 这个字段**：`free()` 时把刚归还的槽位号记进 `nextAvail`，下一次 `getNextAvail()` 直接返回它；只有 `nextAvail < 0`（比如刚创建、或并发归还把槽位冲掉）才退化成线性扫描 bitmap。这正是文档里"优先获取刚刚释放回 PoolSubpage 的内存块"的依据：

// 源码：buffer/src/main/java/io/netty/buffer/PoolSubpage.java:169-206
```java
private void setNextAvail(int bitmapIdx) {
    nextAvail = bitmapIdx;
}

private int getNextAvail() {
    int nextAvail = this.nextAvail;
    if (nextAvail >= 0) {
        this.nextAvail = -1;
        return nextAvail;
    }
    return findNextAvail();
}

private int findNextAvail() {
    for (int i = 0; i < bitmapLength; i ++) {
        long bits = bitmap[i];
        if (~bits != 0) {
            return findNextAvail0(i, bits);
        }
    }
    return -1;
}

private int findNextAvail0(int i, long bits) {
    final int baseVal = i << 6;
    for (int j = 0; j < 64; j ++) {
        if ((bits & 1) == 0) {
            int val = baseVal | j;
            if (val < maxNumElems) {
                return val;
            } else {
                break;
            }
        }
        bits >>>= 1;
    }
    return -1;
}
```

释放侧 `free()` 的返回值是"这个 subpage 是否还被占用"：`true` 表示仍在使用（保留在链表中），`false` 表示所有槽都归还了、可以整个销毁：

// 源码：buffer/src/main/java/io/netty/buffer/PoolSubpage.java:118-151
```java
boolean free(PoolSubpage<T> head, int bitmapIdx) {
    int q = bitmapIdx >>> 6;
    int r = bitmapIdx & 63;
    assert (bitmap[q] >>> r & 1) != 0;
    bitmap[q] ^= 1L << r;

    setNextAvail(bitmapIdx);

    if (numAvail ++ == 0) {
        addToPool(head);
        /* When maxNumElems == 1, the maximum numAvail is also 1.
         * Each of these PoolSubpages will go in here when they do free operation.
         * If they return true directly from here, then the rest of the code will be unreachable
         * and they will not actually be recycled. So return true only on maxNumElems > 1. */
        if (maxNumElems > 1) {
            return true;
        }
    }

    if (numAvail != maxNumElems) {
        return true;
    } else {
        // Subpage not in use (numAvail == maxNumElems)
        if (prev == next) {
            // Do not remove if this subpage is the only one left in the pool.
            return true;
        }

        // Remove this subpage from the pool if there are other subpages left in the pool.
        doNotDestroy = false;
        removeFromPool();
        return false;
    }
}
```

注意最后的 `prev == next` 特判：如果该 size class 的链表里只剩这一个 subpage，即使它完全空闲也**不销毁**——避免"最后一个 subpage 被反复创建/销毁"的抖动。

## metrics

每个 chunk 对外暴露三个指标，`PoolChunk` 实现该接口，`PoolArena` 再把它们聚合成 `PoolArenaMetric`：

```java
/**
 * Metrics for a chunk.
 */
public interface PoolChunkMetric {

    /**
     * Return the percentage of the current usage of the chunk.
     */
    int usage();

    /**
     * Return the size of the chunk in bytes, this is the maximum of bytes that can be served out of the chunk.
     */
    int chunkSize();

    /**
     * Return the number of free bytes in the chunk.
     */
    int freeBytes();
}
```



为了更好的监控内存池的运行状态，Netty 为内存池中的每个组件都设计了一个对应的 Metrics 类，用于封装与该组件相关的 Metrics

PooledByteBufAllocator 提供的 Metrics

```java
public final class PooledByteBufAllocatorMetric implements ByteBufAllocatorMetric {

    private final PooledByteBufAllocator allocator;

    PooledByteBufAllocatorMetric(PooledByteBufAllocator allocator) {
        this.allocator = allocator;
    }

    /**
     * Return the number of heap arenas.
     */
    public int numHeapArenas() {
        return allocator.numHeapArenas();
    }

    /**
     * Return the number of direct arenas.
     */
    public int numDirectArenas() {
        return allocator.numDirectArenas();
    }

    /**
     * Return a {@link List} of all heap {@link PoolArenaMetric}s that are provided by this pool.
     */
    public List<PoolArenaMetric> heapArenas() {
        return allocator.heapArenas();
    }

    /**
     * Return a {@link List} of all direct {@link PoolArenaMetric}s that are provided by this pool.
     */
    public List<PoolArenaMetric> directArenas() {
        return allocator.directArenas();
    }

    /**
     * Return the number of thread local caches used by this {@link PooledByteBufAllocator}.
     */
    public int numThreadLocalCaches() {
        return allocator.numThreadLocalCaches();
    }

    /**
     * Return the size of the tiny cache.
     *
     * @deprecated Tiny caches have been merged into small caches.
     */
    @Deprecated
    public int tinyCacheSize() {
        return allocator.tinyCacheSize();
    }

    /**
     * Return the size of the small cache.
     */
    public int smallCacheSize() {
        return allocator.smallCacheSize();
    }

    /**
     * Return the size of the normal cache.
     */
    public int normalCacheSize() {
        return allocator.normalCacheSize();
    }

    /**
     * Return the chunk size for an arena.
     */
    public int chunkSize() {
        return allocator.chunkSize();
    }

    @Override
    public long usedHeapMemory() {
        return allocator.usedHeapMemory();
    }

    @Override
    public long usedDirectMemory() {
        return allocator.usedDirectMemory();
    }
}

```



## Links

- [Netty](/docs/CS/Framework/Netty/Netty.md)
- [ByteBuf](/docs/CS/Framework/Netty/ByteBuf.md)
- [FastThreadLocal](/docs/CS/Framework/Netty/FastThreadLocal.md)
- [MpscLinkedQueue](/docs/CS/Framework/Netty/MpscLinkedQueue.md)

## References

1. [Reference counted objects](https://netty.io/wiki/reference-counted-objects.html)
2. [PooledByteBufAllocator (Netty API Reference)](https://netty.io/4.2/api/io/netty/buffer/PooledByteBufAllocator.html)
3. [ByteBufAllocator (Netty API Reference)](https://netty.io/4.2/api/io/netty/buffer/ByteBufAllocator.html)
4. [Netty 4.2.0 release notes](https://netty.io/news/2025/04/30/4-2-0.html)
