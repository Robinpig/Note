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

默认情况下是使用pooled的 除非在 Android 中


```java
public interface ByteBufAllocator {

    ByteBufAllocator DEFAULT = ByteBufUtil.DEFAULT_ALLOCATOR;
}
```



```java

public final class ByteBufUtil {
    static final ByteBufAllocator DEFAULT_ALLOCATOR;

    static {
        String allocType = SystemPropertyUtil.get(
            "io.netty.allocator.type", PlatformDependent.isAndroid() ? "unpooled" : "pooled");

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
}
```


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

Netty 又将这 68 种内存规格分为了三类：
1. [16B , 28K] 这段范围内的规格被划分为 Small 规格。
2. [32K , 4M] 这段范围内的规格被划分为 Normal 规格。
3. 超过 4M 的内存规格被划分为 Huge 规格。


其中 Small 和 Normal 规格的内存块会被内存池（PoolArena）进行池化管理，Huge 规格的内存块不会被内存池管理，当我们向内存池申请 Huge 规格的内存块时，内存池是直接向 OS 申请内存，释放的时候也是直接释放回 OS ，内存池并不会缓存这些 Huge 规格的内存块



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
            current instanceof FastThreadLocalThread ||
            // The Thread is used by an EventExecutor, let's use the cache as the chances are good that we
            // will allocate a lot!
            executor != null) {
            final PoolThreadCache cache = new PoolThreadCache(
                heapArena, directArena, smallCacheSize, normalCacheSize,
                DEFAULT_MAX_CACHED_BUFFER_CAPACITY, DEFAULT_CACHE_TRIM_INTERVAL, useCacheFinalizers(current));

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
}
```

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
                s.chunk.initBufWithSubpage(buf, null, handle, reqCapacity, cache);
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
    boolean success = c.allocate(buf, reqCapacity, sizeIdx, threadCache);
    assert success;
    qInit.add(c);
}
```

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

#### allocateRun

1. find the first avail run using in runsAvails according to size
2. if pages of run is larger than request pages then split it, and save the tailing run for later using


#### allocateSubpage

1. find a not full subpage according to size.
   if it already exists just return, otherwise allocate a new PoolSubpage and call init() note that this subpage object is added to subpagesPool in the PoolArena when we init() it
2. call subpage.allocate()

#### free

1. if it is a subpage, return the slab back into this subpage
2. if the subpage is not used or it is a run, then start free this run
3. merge continuous avail runs
4. save the merged run



## metrics


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
