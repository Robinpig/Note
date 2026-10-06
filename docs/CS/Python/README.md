# Python

## Introduction

[Python](https://www.python.org/) 相关笔记的知识地图：语言本身 → 环境与包管理 → 开发工具 → 生态。

## 目录索引

| 笔记 | 主题 | 一句话要点 |
|---|---|---|
| [Python](/docs/CS/Python/Python.md) | 语言总览 | 语言简介、发行版、常用库清单、GC |
| [conda](/docs/CS/Python/conda.md) | 环境管理 | Miniconda 安装、conda 环境创建、Jupyter 工作目录配置 |
| [uv](/docs/CS/Python/uv.md) | 包管理 | Rust 编写的极速 Python 包与项目管理工具 |
| [Jupyter](/docs/CS/Python/Jupyter.md) | Notebook | Jupyter Notebook / JupyterLab 与 scikit-learn 上手示例 |

## 工具链选型

| 场景 | 传统方案 | 现代方案 |
|---|---|---|
| 环境管理 | conda / virtualenv | uv |
| 包安装 | pip | uv pip / uv add |
| 交互开发 | IPython | JupyterLab |

## 生态关联

- Web 框架：[FastAPI](/docs/CS/Framework/FastAPI.md)
- LLM 应用开发：[LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)、[LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- 向量数据库：[Milvus](/docs/CS/DB/Milvus/Milvus.md)
- 内存管理对照：[GC](/docs/CS/memory/GC.md)（引用计数与分代回收在各语言运行时中的实现）

## Links

- [CS](/docs/CS/CS.md)
- [FastAPI](/docs/CS/Framework/FastAPI.md)

## References

- [Python 官方文档](https://docs.python.org/3/)
