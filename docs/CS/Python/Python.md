## Introduction

[Python](https://www.python.org/) is a programming language that lets you work quickly and integrate systems more effectively.

它是一台**动态类型 + 引用计数 + 字节码解释执行**的虚拟机：语言层几乎没有隐藏机制，性能与并发的上限则由解释器的三件事决定——GIL 决定并行边界，引用计数与分代回收决定内存行为，特化解释器决定单核速度。本目录的 [GIL](/docs/CS/Python/GIL.md)、[Memory](/docs/CS/Python/Memory.md)、[Bytecode](/docs/CS/Python/Bytecode.md) 三篇就是围绕这三件事展开的，横向对照见 [Languages](/docs/CS/Languages.md)。

当前稳定线是 3.14（free-threaded 构建自 3.14 起为官方支持，patch 级别的行为差异见 [Memory](/docs/CS/Python/Memory.md) 的增量 GC 一节）。

## Installation

发行版

- Anaconda
- Miniconda

包与项目管理工具推荐 [uv](/docs/CS/Python/uv.md)；科学计算栈与多版本 Python 共存用 [conda](/docs/CS/Python/conda.md)。两者的分工与混用风险在 [Packaging](/docs/CS/Python/Packaging.md)。

## Library

安装时使用 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 指定镜像

```shell
pip3 install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Standard Library

[标准库](https://docs.python.org/3/library/)

- binascii
- datetime
- gettext
- re
- time

### Third-Party Libraries

| 分类 | 库 |
|---|---|
| 工具 | jproperties、pangu |
| Web 框架 | Flask |
| 数据分析 | Pandas、SciPy、NumPy |
| 统计 | StatsModels |
| 爬虫 | Scrapy、lxml、requests |
| NLP | NLTK、Gensim |
| 机器学习 | Scikit-learn |
| 人工智能 | TensorFlow、Theano、Keras |
| 基本绘图 | Matplotlib、Seaborn、Bokeh、Plotly |
| 地图 | GeoplotLib、MapBox |
| 图像处理 | PIL |

生态层的选型判断（哪些还活着、按什么维度选）见 [Ecosystem](/docs/CS/Python/Ecosystem.md)。

### Notebook

嵌入 Markdown：iPython 创建好 .ipynb 文件后，在 markdown 使用 `<iframe>` 标签，就可以将完成嵌入

## Runtime

语言层看不到、但决定行为与性能的四件事，各有专篇：

对象一律带引用计数头，归零即释放，循环引用交给分代回收兜底，小对象由 pymalloc 复用——这套流水线与它带来的"释放了但 RSS 不降"是 [Memory](/docs/CS/Python/Memory.md) 的主题。源码不编译成机器码，而是走 AST → 字节码 → 特化自适应解释器，3.13/3.14 之上再加实验性 JIT，理解这条管线才能判断"哪种写法真的快"，见 [Bytecode](/docs/CS/Python/Bytecode.md)。

并行能力由 GIL 划界：`await` 与阻塞调用的取舍见 [Asyncio](/docs/CS/Python/Asyncio.md)，线程 / 进程 / 多解释器 / free-threaded 的选型见 [Concurrency](/docs/CS/Python/Concurrency.md) 与 [GIL](/docs/CS/Python/GIL.md)。

## Links

- [README](/docs/CS/Python/README.md)
- [Memory](/docs/CS/Python/Memory.md)
- [GIL](/docs/CS/Python/GIL.md)
- [Bytecode](/docs/CS/Python/Bytecode.md)
- [GC](/docs/CS/memory/GC.md)
- [Languages](/docs/CS/Languages.md)

## References

- [Python 官方文档](https://docs.python.org/3/)
- [The Python Tutorial](https://docs.python.org/3/tutorial/)
