## Introduction

NumPy 是 Python 数据与 AI 栈的数组地基：`pandas`、`scikit-learn`、`PyTorch` / `TensorFlow` 的输入管线，大多直接或间接消费 `ndarray`。本笔记只回答一个问题——**ndarray 为什么快，又为什么常常不知不觉地不**快。答案分两层：内存布局（一块连续 buffer + 一组元数据描述符）决定缓存行为与复制代价；执行模型（C 循环替代解释器逐元素循环，BLAS 自带线程池）决定计算真正发生在哪。看懂这两层，下面所有坑——为什么 `a.T` 免费、为什么 `a[mask][mask2] = 0` 不生效、为什么多进程里 numpy 越并行越慢——都能自行推出来。机器学习算法与数值计算选型见 [AI.md](/docs/CS/AI/AI.md)，本篇只讲数组抽象本身。

## The Anatomy of ndarray

`ndarray` 对象 = 一块连续内存 + 描述"如何解释这块内存"的元数据：

| 字段 | 含义 |
| :--- | :--- |
| `dtype` | 元素类型与字节宽度（`float64` 为 8 字节） |
| `shape` | 各维长度 |
| `strides` | 对应维索引加 1 时，在 buffer 中跳过的**字节数** |
| `flags` | 内存属性：`C_CONTIGUOUS`、`F_CONTIGUOUS`、`OWNDATA`、是否可写 |
| `base` | buffer 持有者；数组自己拥有 buffer 时为 `None` |

```python
# 概念示例（本机未安装 numpy，全文代码均未实测）
a = np.zeros((2, 3), dtype=np.float64)
a.strides      # (24, 8)：跳一行 = 3 个元素 * 8 字节，跳一列 = 8 字节
a.nbytes       # 48
a.flags['C_CONTIGUOUS']   # True
```

对照物是 Python `list`：它存的是**指针数组**，元素本体散落在堆上，每个元素还是完整的 `PyObject`（类型指针 + 引用计数 + 值）。`sum(list)` 每走一步都要追一次指针（缓存未命中）、查一次类型（运行时类型分派）、做一轮引用计数增减。向量化的三项收益恰好逐条对应：**缓存局部性**（连续遍历是硬件预取器最擅长的模式）、**单一已知类型**（ufunc 按 dtype 各有一个紧凑的 C 循环，循环体内没有逐元素分支）、**引用计数只作用于数组对象一次**。Python 对象在内存里的具体布局见 [Memory.md](/docs/CS/Python/Memory.md)。

## Strides Make Transposes Free

以下操作只改元数据、不动 buffer，因此是 O(1) 的视图：

- `a.T` / `np.swapaxes`：交换 shape 与 strides 的对应两轴，数据指针原封不动。转置快，但代价是后续沿内存遍历不再是顺序访问。
- 基础切片 `b = np.arange(10, dtype=np.float64); b[::2]`：strides 从 `(8,)` 变 `(16,)`，就地表达"隔一个取一个"。
- `np.broadcast_to`：新轴与长度为 1 的轴直接记成 **strides = 0**——无论索引取何值都落回同一地址，形状膨胀而内存为零。
- `reshape`：只要内存布局允许（源连续，或目标顺序可由现有 strides 组合出来）返回视图，否则**静默复制**。拿不准就检查 `r.base is a`。

反过来说，`np.ascontiguousarray`、`np.copy`，以及 `flatten()`（永远返回副本，区别于 `ravel()` 优先返回视图）是明确逼出复制的地方。`C` / `F` 顺序与 `order=` 参数决定的是"遍历顺序与内存布局是否对齐"，直接对应性能：对 C 连续数组，沿最后一根轴逐元素扫描是顺序访存，而按列遍历相邻元素间隔整整一行，数组一旦越过 L2 / L3，两种走法的差距就是数量级的（NumPy 内部对沿非连续轴的归约做了分块优化，差距会缩小，但 Python 层逐元素遍历仍会全额支付）。

## Views and Copies

基础索引（`a[:]`、`a[...]`、切片、`reshape` / 转置 / `broadcast_to` 的结果）与源共享 buffer；**高级索引（整数数组、布尔掩码）返回的一定是副本**。最常见的事故由此而来：

```python
# 概念示例
a[mask][mask2] = 0     # 错：a[mask] 已经是副本，赋值落在副本上，随后整个副本被丢弃
a[mask & mask2] = 0    # 对：一次布尔掩码赋值，直接写入原 buffer
np.copyto(a, 0, where=mask & mask2)   # 等价写法，意图更明确
```

`a[...] = expr` 与 `a = expr` 的语义差异：前者向原 buffer 做广播赋值，所有视图同步可见；后者只是把名字 `a` 重新绑定到别的对象，原数组纹丝不动。`out=` 参数（`np.multiply(x, y, out=z)`）则把结果直接写进既有 buffer，省掉临时数组——大数组场景这是最廉价的优化。

高级索引还藏着更隐蔽的一层：`a[idx] += 1` 走"复制 → 计算 → 写回"，`idx` 中有重复下标时同一位置的累加不会正确合并；要精确语义用 `np.add.at(a, idx, 1)`（慢但正确）或 `np.bincount`（快路径）。排查共享关系用 `np.shares_memory(a, b)`。

## Broadcasting

广播规则：两个 shape **从尾部开始对齐**，每个轴要么相等、要么其中一侧为 1（含该轴缺失）。

```python
# 概念示例
np.ones((3, 1)) * np.ones((1, 4))   # (3, 1) 与 (1, 4) -> (3, 4)，列向量乘行向量，外积形状
np.ones((8, 1, 3)) + np.ones((7, 1, 5))   # ValueError：尾部轴 3 与 5 既不相等也非 1
```

聚合默认降维：`a.sum(axis=-1)` 让结果与 `a` 不再广播。`keepdims=True` 把被聚合的轴保留为长度 1，"每行除以本行和"这类运算一行写完，不必手工 reshape。

```python
# 概念示例
a / a.sum(axis=-1, keepdims=True)   # 广播回来，无需任何 reshape
```

`np.einsum('ij,jk->ik', a, b)` 是广播的显式对偶：把矩阵乘、迹、转置、张量缩并统一成下标记法，下标本身就是自检文档；多因子缩并时 `optimize=True` 让 NumPy 搜索 contraction 顺序，代价可以从指数级降到多项式级。定位：当链式 `dot` / `transpose` 的意图写不清晰时，换 einsum。

## Memory Ownership and Lifecycle

视图通过 `base` 链持有整个 buffer：从数百 MB 的数组切出的单元素视图，会把原始数组整块钉在内存里，从进程 RSS 完全看不出是谁在拖。排查方法是顺着 `b.base` 链往上走，解法是找到那个还活着的视图、`b.copy()` 断链。

`del a` 只做一次引用计数减一；只要还有视图、C 层引用或缓存槽位挂着，buffer 就不会消失。释放后的块还可能进入 NumPy 内部的小块缓存，进程 RSS 不降不等于泄漏。

零拷贝的边界由协议划定：对象暴露 **buffer protocol** 或 `__array_interface__`（`data` 字段是 `(指针地址, 是否只读)`），`np.asarray` 就能包住它而不复制——`memoryview`、`array` 模块、C 扩展导出的内存都走这条路；实现 `__array__` 方法的对象可被 `np.asarray` 转换；GPU 侧的对应物是 `__cuda_array_interface__`（cuPy / cuDF / PyTorch 之间）与 DLPack 标准。`pandas` 的数值列内部就是 ndarray，所以 pandas 与 numpy 之间常是视图或浅拷贝。Apache Arrow 与 buffer protocol 解决同一类问题——跨组件零拷贝共享列式内存——只是它是可持久化、跨语言的规范，本篇不展开。

## GIL, BLAS Threads, and Oversubscription

numpy 重活能绕开 GIL，原因有两层：ufunc 的循环体是纯 C，数值类型的 inner loop 执行期间通常释放 GIL；更关键的是矩阵乘等运算分派给 BLAS（OpenBLAS / MKL），它们维护**自己的 OpenMP / pthread 线程池**——线程由原生库创建，GIL 根本拦不住它们。GIL 本身的机制见 [GIL.md](/docs/CS/Python/GIL.md)。

既然线程池在原生库手里，控制它的就是 `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`MKL_NUM_THREADS` 这类环境变量，且必须在导入 numpy **之前**设置（原生库加载时读一次）；要运行期调节用 `threadpoolctl`。真正会踩的坑是**过度订阅**（oversubscription）：用 `multiprocessing` 起 N 个 worker，每个进程里的 BLAS 又各自默认开"每核一线程"，于是 N × 核数个线程争抢核数，上下文切换风暴，总吞吐反而低于单线程。通行做法：worker 内把 BLAS 压回 1 线程，让进程层承担并行；或反过来单进程、靠 BLAS 自己的池。

## Common Misuses

| 误用 | 为什么慢 / 错 | 正确姿势 |
| :--- | :--- | :--- |
| Python 层 `for` 逐行处理数组 | 每元素付类型分派 + 解释器开销，常慢千倍 | ufunc、掩码、布尔运算整体表达 |
| `np.array(形状不齐的嵌套序列)` | NumPy 1.24 起直接 `ValueError`；当年静默造出 object 数组 | 先统一形状，或明确意识到这不该是 ndarray |
| `dtype=object` 当通用容器 | 退化成指针数组，向量化收益全部归零 | 容器需求交回 `list` / `dict` |
| 循环里 `np.append` | 每次全量复制，O(n²) | 收集进 list，最后一次 `np.concatenate` |
| `x in arr` | 线性扫描 O(n) | 排序 + `np.searchsorted`，或集合 / `np.isin` |
| 依赖 np.float64 与 float 的隐式提升 | `np.float64` 是 `float` 的子类，但 NEP 50 改了标量与数组的提升规则：Python 标量不再按"值"降型数组（`uint8` 数组 + Python int 结果仍是 `uint8`，溢出按回绕处理） | NumPy 2.x 迁移必读 NEP 50，勿凭旧直觉 |
| 多线程 / 多进程里用 `np.random.*` 全局函数 | 共享同一个全局 `RandomState`；fork 出的 worker 状态相同、产出相同序列，交错调用后无法复现 | 每路一个显式 `np.random.default_rng(seed)` 的 `Generator`，多进程用 `SeedSequence.spawn` 派生 |

## Where the In-Memory Model Ends

超出单机内存的数值计算不再是 numpy 的主场：分布式数组与惰性计算图归 Dask / Spark 一类，列式内存与跨引擎零拷贝归 Arrow 生态，GPU 常驻归 JAX / PyTorch / cuDF；分界见 [BigData.md](/docs/CS/BigData/BigData.md)。本篇的选型表只回答"单机内存内，什么时候该跳出 NumPy"。

## When to Leave NumPy

| 库 | 解决什么 | 内存模型 | 什么时候该跳出 NumPy |
| :--- | :--- | :--- | :--- |
| [NumPy](https://numpy.org/) | 同构数值数组 | 全内存，连续 buffer | 基线，问题在内存内时不必离开 |
| [Pandas](https://pandas.pydata.org/docs/) | 带标签表格、混合 dtype、join / 缺失值语义 | 全内存，底层块是 ndarray | 需要表格语义而非纯数值时 |
| [Polars](https://pola.rs/) | 表达式优化的 DataFrame | 全内存，Apache Arrow 布局 | 单机大表，嫌 pandas 慢或内存失控 |
| [Dask](https://docs.dask.org/en/stable/) | 惰性任务图、arrays / dataframes | 内存 + 溢写磁盘，可分布式 | 数据超内存，想要 numpy 风格 API |
| [JAX](https://jax.readthedocs.io/en/latest/) | 自动微分、XLA 编译、多设备 | 设备内存，函数式更新 | 需要 `grad` / `vmap` 或加速卡 |
| [PyTorch](https://pytorch.org/docs/stable/) | 动态图 autograd、GPU 生态 | 设备内存，tensor 即 ndarray 近亲 | 训练、推理或任意 GPU 计算 |
| [numba](https://numba.pydata.org/) | 把逐元素 Python 逻辑 JIT 成机器码 | 与 NumPy 共享 buffer | 向量化表达不出的循环（指针追踪、提前 break） |

**Array API standard**：[Python array API standard](https://data-apis.org/array-api/latest/) 定义了数组库的公共子集，目标是让库代码在 numpy / PyTorch / cuDF 间可移植。NumPy 自 2.0 起以主命名空间通过该标准的符合性测试，旧的实验性子包 `numpy.array_api` 已弃用并计划移除；PyTorch 与 cuDF 各自提供兼容层。写需要换后端的库代码时，按标准的函数面取用即可。

## Links

- [memory](/docs/CS/memory/memory.md)
- [malloc](/docs/CS/C/malloc.md)

## References

- [The NumPy array object — ndarray reference](https://numpy.org/doc/stable/reference/arrays.ndarray.html)
- [Basics of indexing — NumPy](https://numpy.org/doc/stable/user/basics.indexing.html)
- [Broadcasting — NumPy](https://numpy.org/doc/stable/user/basics.broadcasting.html)
- [The Numpy array interface](https://numpy.org/doc/stable/reference/arrays.interface.html)
- [NEP 50 — Promotion rules for Python scalars](https://numpy.org/neps/nep-0050-scalar-promotion.html)
- [Generator (Random number generation) — NumPy](https://numpy.org/doc/stable/reference/random/generator.html)
- [numpy.einsum — NumPy](https://numpy.org/doc/stable/reference/generated/numpy.einsum.html)
- [Array API standard compatibility — NumPy](https://numpy.org/doc/stable/reference/array_api.html)
- [Python array API standard](https://data-apis.org/array-api/latest/)
- [threadpoolctl — joblib](https://github.com/joblib/threadpoolctl)
