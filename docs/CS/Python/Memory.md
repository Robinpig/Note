## Introduction

CPython 的内存管理由三件事咬合而成：**对象头里的引用计数**、**给循环引用兜底的分代循环回收器**、**把小对象切成 block 复用的分层分配器**。三者不是并列的三种 GC，而是有主次的流水线——绝大多数对象在计数归零那一刻就死了，`gc` 模块只负责捞那些永远归不了零的环，分配器则决定"逻辑上释放"和"RSS 真的下降"之间还隔着多远。分工：回收算法的理论对照（refcount vs tracing、分代假设、三色抽象）在 [GC](/docs/CS/memory/GC.md)，glibc ptmalloc 的 chunk / arena / bin 在 [malloc](/docs/CS/C/malloc.md)，并发三色与写屏障在 [Go GC](/docs/CS/Go/GC.md)。本页只写 Python 这一侧的实现与判断逻辑。

## Object Layout: PyObject and PyVarObject

CPython 里"一切皆对象"是有具体字节含义的：任何 Python 对象的开头都是一个 `PyObject`，即 `ob_refcnt`（8 字节）加 `ob_type`（8 字节）——`sys.getsizeof(object())` 实测正好 16。变长对象用 `PyVarObject`，多一个 `ob_size`（8 字节）记录元素个数。**"每个整数 28 字节"不是语言规定，而是这套头的算术结果**：16 + 8 + 每 30 bit 一个 4 字节 digit，换 32 位平台或多 digit 大数就变。被 GC 跟踪的对象头上还要再加 16 字节的双向链表头（`sys.getsizeof` 文档明说它会补上这部分开销），这解释了为什么空 `list` 是 56 而空 `tuple` 是 40。

| 对象 | `getsizeof` | 拆开的理由 |
| :---------------- | ---: | :--- |
| `object()` | 16 | 正好一个 `PyObject` 头 |
| `0` / `1` / `2**30` / `2**90` | 28 / 28 / 32 / 40 | 16 + `ob_size` 8 + 每多一个 30-bit digit 加 4 字节 |
| `''` / `'abc'` / `'中'` | 41 / 44 / 60 | ASCII 每字符 1 字节，非 ASCII 基底更大且每字符 2 字节（PEP 393） |
| `[]` / `[1, 2, 3]` | 56 / 88 | 40 + 16 字节 GC 头；3 元素却分配到 4 槽 |
| `list(range(10))` | 136 | 56 + 8 × 10，**只存指针** |
| `()` / `(1, 2, 3)` | 40 / 64 | 40 + 8 × n |
| `{}` / `{1: 2}` / 10 项 | 64 / 224 / 352 | 一插入就分配 keys / values 两块数组 |
| 普通实例（3 个属性） | 48 | 32 + 16 GC 头，**不含 `__dict__`** |

`# Python 3.12.5 实测`（macOS arm64 homebrew 构建）——换平台请重跑，尤其 `str` 那一行。`sys.getsizeof` 的官方定义写着"只算直接归属于该对象的内存，不算它引用的对象"，因此有三个系统性低估：容器不算元素、实例不算 `__dict__`、`__slots__` 不算槽里指向的对象。上面那个 48 字节的实例真实开销是 `48 + sys.getsizeof(obj.__dict__) = 344`（实测）。第三方用 `pympler.asizeof`，标准库没有对应物，自己写也不难：

```python
import sys
def deep_sizeof(obj, seen=None):
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0                                  # 同一对象只算一次
    seen.add(id(obj))
    total = sys.getsizeof(obj)
    if isinstance(obj, dict):
        total += sum(deep_sizeof(k, seen) + deep_sizeof(v, seen) for k, v in obj.items())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        total += sum(deep_sizeof(item, seen) for item in obj)
    elif hasattr(obj, '__dict__'):                # 实例：算上属性值，但仍不含 __dict__ 本身
        total += sum(deep_sizeof(v, seen) for v in vars(obj).values())
    return total
```

实测：`list(range(10))` 浅 136 → 深 416（136 + 10 × 28）；`{i: i for i in range(10)}` 浅 352 → 深 632，键与值是同一批小整数对象，`seen` 让它们只被算一次——去掉 `seen` 会得到 912，这是递归 sizeof 最常见的错法。

## Reference Counting as the Primary Mechanism

每次绑定、传参、放进容器都是 `Py_INCREF`，离开作用域、重新绑定、容器销毁都是 `Py_DECREF`；计数归零立刻调用 `tp_dealloc`，并递归地把这个动作传给它持有的对象。`sys.getrefcount(x)` 读数总比预期大 1，因为传参本身就是一次引用。值得记住的是**释放时机的确定性**：文件、锁、socket 在最后一个引用消失那一刻就被关掉。Go 的 `SetFinalizer` 与 Java 已废弃的 `finalize()` 都只承诺"最终会跑"，不保证时机与顺序（对照见 GC.md 的 refcounting 一节）——但这只是 CPython 的实现细节，跨解释器与跨版本不可依赖，`with` 仍然是唯一正确写法。代价有三条：

- **计数不是原子的**。一次 `x = y` 要改两块内存，多线程下必然竞态，这是 GIL 长期存在的理由之一。PEP 703 的 free-threaded 构建改用 biased reference counting（线程私有计数 + 共享计数按需合并），机制细节在 [GIL](/docs/CS/Python/GIL.md)。
- **处理不了循环引用**（`a.ref = b; b.ref = a` 之后计数永不归零），只能靠 `gc`。
- **写热点**：赋值即写内存，缓存行争用明显，这是它在多核下吞吐比不过追踪式回收器的原因。

## The Cyclic Garbage Collector

只有**可能持有其他对象引用的容器**才需要被跟踪——整数和字符串成不了环。下表是 `gc.is_tracked()` 的 3.12.5 实测：

| 对象 | 3.12.5 是否跟踪 | 说明 |
| :--- | :--- | :--- |
| `1` / `'a'` / `1.5` | False | 原子类型永不跟踪 |
| `[]` / `set()` / 函数 / 带 `__dict__` 的实例 | True | |
| `(1, 2)` / `([],)` | False / True | 全不可变内容的 tuple 会被 untrack，装进可变对象就重新跟踪 |
| `{}` / `{1: 2}` → `{'a': [1]}` | False → True | 3.12 对小 dict 的惰性 untrack；实测往已有 dict 里插入一个 list 会立刻回到跟踪状态 |

⚠️ 别把这张表当跨版本事实：3.14 的 internal docs 写着"dict 从创建起就被跟踪、不再惰性 untrack"，官方 `gc` 页示例也是 `gc.is_tracked({"a": 1}) is True`，而本机 3.12 是 `False`。

分代靠三个阈值驱动，`gc.get_threshold()` 本机实测 `(700, 10, 10)`，`gc.get_count()` 实测约 `(532, 8, 0)`：

- `threshold0`：净分配数（alloc − dealloc）超过它就扫第 0 代；设成 0 等于关掉自动回收。
- `threshold1`：第 0 代被扫了多少次还没惊动第 1 代，就带上第 1 代。
- `threshold2`：第 1 代扫完后按存活比例决定是否扫第 2 代（internal docs 给的判据是 `long_lived_pending / long_lived_total` 超过约 25%）。

三个阈值都是**对象分配计数**而非字节数，且 internal docs 的示例里 `threshold0` 出现过 `2000`——默认值会变，要判就读 `gc.get_threshold()`。

```python
import gc
print(gc.get_threshold(), gc.get_count(), gc.isenabled())   # 阈值 / 各代净分配数 / 是否开启
def observe(phase, info):                 # info: generation / collected / uncollectable
    if phase == 'stop':
        print('GC gen%s collected=%s' % (info['generation'], info['collected']))
gc.callbacks.append(observe)
print(gc.collect(2))                      # 无参 = 全量；返回值 = collected + uncollectable
```

实测回调按 `('start', ...)` / `('stop', ...)` 成对触发，是不引第三方库量化 GC 停顿的唯一办法；`gc.get_stats()` 另给每代累计的 `collections / collected / uncollectable`。还有几条容易踩的：

- **`gc.collect()` 会清 free list**：官方写明全量或收第 2 代时清空内置类型的空闲链表（`float` 因为实现原因不一定清干净）。
- **`__del__` 可以让对象复活**：`__del__` 里把 `self` 塞进全局容器，对象就活了（实测复活成功，`gc.is_finalized()` 返回 True）。PEP 442（3.4）之后，带 `__del__` 的循环引用在 finalize 阶段处理，不再堆进 `gc.garbage`；`gc.garbage` 常态为空，非空说明你在对抗解释器。
- **`gc.disable()` 只关自动触发**，`collect()` 仍可手动调。异常链、闭包、traceback 都在制造环，长驻进程关掉 GC 等于选了慢性 OOM。合理场景只有两种：确认无环且极短的脚本，或 fork 前预加载——`gc.disable()` → `gc.freeze()` → `fork` → 子进程 `gc.enable()`，把常驻对象移出回收范围，免得子进程回收时写脏父进程页（gunicorn `--preload` 类做法的底层就是这个）。
- **free-threaded 是另一套**：internal docs 明说该构建**不做分代**，每次回收扫整个堆，且为线程安全会暂停其他线程。

## The 3.14 Incremental GC Detour

⚠️ 一条足以让所有"Python 3.14 是增量 GC"说法过时的时间线，逐条依据是 What's New 3.14 的 Garbage collection 一节：

| 版本 | cyclic GC 实际行为 |
| :--- | :--- |
| ≤ 3.13 | 分代 0 / 1 / 2 |
| 3.14.0 – 3.14.4 | 增量式：只剩 young / old 两代，`gc.collect(1)` 语义从"回收 1 代"变成"回收一个增量"，大堆最大停顿降低约一个数量级 |
| 3.14.5 起 | **回退到 3.13 的分代 GC**，原因是生产环境报告了明显内存压力 |

**当前实际行为 = 分代。** 而文档里旧条目还留着，形如三层叠加：`gc.collect` 写着 "Changed in version 3.14: generation=1 performs an increment of collection / Changed in version 3.14.5: ... middle generation"；`gc.get_objects` 写着 "Generation 1 is removed / reintroduced"；`gc.set_threshold` 写着 "threshold2 is ignored / restored to match Python 3.13"。**"存在" ≠ "生效"**。判断方法论（任何版本行为争议都适用）：

1. **先钉住精确版本**：`python -VV`、`sys.version_info`（含 micro）、`sys.implementation.version`；free-threaded 构建会在版本串里带 `experimental free-threading build`。谈 patch 级别的行为必须写到 `3.14.5` 这种粒度。
2. **再读运行时的实际形状**，而不是读文档句子：`gc.get_threshold()` 返回几元组、`gc.get_stats()` 有几个桶、`gc.get_objects(1)` 会不会 `ValueError`——这些"结构探测"比任何博客都可靠。
3. **找前向更正块，结论写成"版本 + 判据"**：What's New 里 `From Python 3.14.5 onwards:` 紧跟 `Previously in Python 3.14.0-3.14.4:` 的写法就是官方在标记过期正文；别把结论写成"Python 3.14 如何"。

## Allocator Layers

`PyObject_Malloc` 不等于 `malloc`。分层的意义是"小块不进 libc，大块才进"：

| 层 | 负责 | 向谁要内存 |
| :--- | :--- | :--- |
| pymalloc | **≤ 512 字节**的对象；arena（64 位固定 1 MiB，32 位 256 KiB）切成 pool，pool 内切同规格 block（16 字节倍数） | `mmap` / `VirtualAlloc` |
| `PyMem_RawMalloc` | > 512 字节，以及 `list` 的 items 数组、`str` 的数据区 | 系统 `malloc` |
| glibc ptmalloc / macOS libmalloc | 上面的落点，chunk / arena / bin，再由它 `brk` / `mmap` 向内核要页 | — |

和 [malloc](/docs/CS/C/malloc.md) 是同一套思路（批量向内核要、用户态切小块缓存），所以"不归还"的问题会**两层叠加**：pymalloc 有空 arena 才 munmap，glibc 要过 `M_TRIM_THRESHOLD` 才 brk 收缩。512 这条线也解释了为什么大 `list` 的指针数组不受 pymalloc 管。可用的开关（全部来自官方 Memory Management 文档）：`PYTHONMALLOC=malloc` 运行时关掉 pymalloc（ASan 调试常用）、构建期 `--without-pymalloc`、3.13 起内置 **mimalloc** 且可用 `PYTHONMALLOC=mimalloc` 选择；**free-threaded 构建默认且强制 mimalloc**，用 per-thread heap 让多数分配无需加锁。本机是否在用 pymalloc 可查 `sysconfig.get_config_var('WITH_PYMALLOC')`（实测 `1`），运行时形状看 `sys._debugmallocstats()` 的 arena / pool 计数。

## Resident and Reused Objects

理解"为什么这两个字面量 `is` 为真"，要靠下面这些解释器常驻对象：

| 机制 | 范围 | 本机实测（Python 3.12.5） |
| :--- | :--- | :--- |
| 小整数缓存 | `-5 .. 256` 全局单例 | `256 is int("256")` True；`-5 is int("-5")` True；`257 is int("257")` False |
| 字符串 interning | 标识符形式的字面量编译期即 intern；`sys.intern` 显式 | 两个**独立编译单元**里的 `'abc_def'` 仍 `is` True；`'abc-def!'` 跨单元 False、同单元 True（那是常量合并，不是 interning） |
| 常量复用 | `tuple` 字面量进 `co_consts`，取的是同一个对象 | `def f(): return (1,2,3)` → `f() is f()` True。⚠️ 但 `frozenset({1, 2})` 在 3.12 **不再常量折叠**：`co_consts` 里只有 `1, 2`，每次执行都 `BUILD_SET` 新建一个（`f() is f()` False）——想共享就自己提到模块级常量或默认参数 |

## Reducing Memory Footprint

| 手段 | 实测收益 | 代价与坑 |
| :--- | :--- | :--- |
| `__slots__` | 3 字段实例 `48 + 296 = 344` → `56` | 子类不写 `__slots__` 就退回带 `__dict__`（实测子类 72 字节且有 `__dict__`）；每层祖先的槽都占位；与 `pickle` / `copy` 要额外配合；不能动态加属性；`@dataclass(slots=True)` 是等价省事写法（实测 56 且无 `__dict__`，普通 dataclass 48 + 296 = 344）。属性查找机制属 [Data Model](/docs/CS/Python/Data_Model.md) |
| 生成器替代列表 | 10 万元素的 genexpr 对象 192 字节 vs 列表 800056 字节 | 只能遍历一次；上游要 `len()` / 切片就不适用 |
| `array` / `memoryview` / `struct` | `array('q', range(100000))` 有效数据 800000 字节（`getsizeof` 报 816640，含增长策略预留容量）vs 同内容 `list` 约 3.6 MB | 只适合齐类型数值。多维与向量化走 [NumPy](/docs/CS/Python/NumPy.md) |
| `weakref` 打断缓存强引用 | `WeakValueDictionary` 让缓存不再是根 | `int` / `str` / `tuple` 不可 weakref（实测 `TypeError`）；`weakref.ref(x)()` 可能突然变 None |

**"释放了但 RSS 没降"的真相是 arena 粒度**。同一进程内用 `ps -o rss` 采样后换算成 MiB：

| 时刻 | RSS |
| :--- | --- |
| 分配 200 万个 tuple 后 | 327 |
| 只保留稀疏的 2000 个存活者（99.9 % 已释放） | 326（几乎不动） |
| 全部释放 | 22 |

只要每个 1 MiB arena 里还剩一个被引用的 block，整个 arena 就不能还给内核。所以**别把 pymalloc 写成"永不归还"**——空 arena 是会被释放的（表格最后一行）；真正的问题是每个 arena 都被零星存活者钉住。Linux 上还要再叠一层 glibc 的不收缩，见 malloc.md。

## Measuring and Typical Leaks

```python
import tracemalloc

tracemalloc.start(10)                       # 10 = 记录 10 层栈
snap1 = tracemalloc.take_snapshot()
data = [{'id': i, 'name': 'user%d' % i} for i in range(20000)]
snap2 = tracemalloc.take_snapshot()
for st in snap2.compare_to(snap1, 'lineno')[:3]:
    print(st)                               # 行号级增量，直接定位分配点
```

实测输出形如 `size=5344 KiB (+5344 KiB), count=79726 (+79726)`，聚合键用 `lineno` / `filename` / `traceback`；`tracemalloc.get_traced_memory()` 给当前 / 峰值。它只记 Python 层分配，C 扩展里的 `malloc` 看不见——那种场景用 memray（原生栈 + flamegraph）或 objgraph（可视化引用环与 `show_cycles()`）。`resource.getrusage().ru_maxrss` 是**峰值**，拿它验证"释放后回落"必然徒劳。

| 泄漏模式 | 为什么留 | 处理 |
| :--- | :--- | :--- |
| 全局缓存无上限 | 模块级 dict / list 永远是 GC 根 | `lru_cache(maxsize=...)`；`WeakValueDictionary`；进程级上限 |
| `__del__` 里把 self 注册回容器 | 回收时对象复活，且每次复活多一层引用 | 改显式 `close()` + `with`；用 `gc.callbacks` 看 `collected` 是否长期为 0 |
| 闭包 / traceback 钉住整帧 | `tb_frame` 持有帧，帧里所有局部变量都活着 | 别长期存 exception 对象；需要文本就 `traceback.format_exc()` 后扔掉 |
| 回调注册未注销 | `atexit`、`signal`、`logging.addHandler`、事件总线持绑定方法 → `self` 永生 | 注册表用 `WeakMethod`；提供反注册并在析构里调用 |
| pandas / numpy 切片 | 视图的 `base` 指向原始大 buffer，改一个值也整块留存 | 需要独立副本就 `.copy()`（数组布局与视图细节在 NumPy.md 一侧） |
| 环堆积（不是泄漏） | 阈值按**对象数**触发，海量小对象时 GC 追不上分配，RSS 单调爬 | 用 `gc.callbacks` 量化 `collected`，再决定是调 `gc.set_threshold` 还是在关键路径后手动 `gc.collect()` |

## Links

- [Python](/docs/CS/Python/Python.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [Import](/docs/CS/Python/Import.md)
- [memory](/docs/CS/memory/memory.md)

## References

- [gc — Garbage Collector interface](https://docs.python.org/3/library/gc.html)
- [Memory Management — Python/C API](https://docs.python.org/3/c-api/memory.html)
- [tracemalloc — Trace memory allocations](https://docs.python.org/3/library/tracemalloc.html)
- [PEP 393 — Flexible String Representation](https://peps.python.org/pep-0393/)
- [sys — System-specific parameters and functions](https://docs.python.org/3/library/sys.html)
- [Object Structure — Python/C API](https://docs.python.org/3/c-api/structures.html)
- [What's New In Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)
- [CPython InternalDocs: Garbage collector design](https://github.com/python/cpython/blob/3.14/InternalDocs/garbage_collector.md)
- [PEP 442 — Safe object finalization](https://peps.python.org/pep-0442/)
- [PEP 703 — Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
