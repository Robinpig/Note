## Introduction

[Python](https://www.python.org/) is a programming language that lets you work quickly and integrate systems more effectively.

## Installation

发行版

- Anaconda
- Miniconda

## Library

安装时使用 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 指定镜像

```shell
pip3 install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 标准库

[标准库](https://docs.python.org/3/library/)

- binascii
- datetime
- gettext
- re
- time

### 第三方库

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

### Notebook

嵌入 Markdown：iPython 创建好 .ipynb 文件后，在 markdown 使用 `<iframe>` 标签，就可以将完成嵌入

## GC

CPython 的内存回收以引用计数为主，辅以分代垃圾回收处理循环引用：

- **引用计数**：对象引用数归零立即释放，实时性好；缺点是无法处理循环引用。
- **分代回收**（`gc` 模块）：将容器类对象（list、dict、set 等）按存活时间分为 0/1/2 三代，新对象在 0 代，越老的对象扫描越少；通过遍历引用关系检测并回收循环引用。

跨语言对照见 [GC](/docs/CS/memory/GC.md)。

## Links

- [Python 目录首页](/docs/CS/Python/README.md)
- [conda](/docs/CS/Python/conda.md) — Anaconda 环境管理
- [uv](/docs/CS/Python/uv.md) — 极速包与项目管理工具
- [Jupyter](/docs/CS/Python/Jupyter.md) — Notebook 开发环境
- [FastAPI](/docs/CS/Framework/FastAPI.md) — Python Web 框架
- [GC](/docs/CS/memory/GC.md) — 跨语言内存管理对照

## References

- [Python 官方文档](https://docs.python.org/3/)
- [The Python Tutorial](https://docs.python.org/3/tutorial/)
