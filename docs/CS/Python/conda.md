## Introduction

[Miniconda](https://docs.anaconda.com/miniconda/install/) / Anaconda 是"连 Python 解释器本身一起管"的发行版：`conda` 解析的是**带原生依赖的软件包**（BLAS、CUDA、`libstdc++`、Python 版本），`pip` 解析的是 Python 包。它适合科学计算栈与多版本共存，也决定了它和 `pip` 混用时的经典事故。纯 Python 项目与现代工作流更推荐 [uv](/docs/CS/Python/uv.md)，取舍见 [Packaging](/docs/CS/Python/Packaging.md)。

## Installation

安装教程见 [Miniconda install](https://docs.anaconda.com/miniconda/install/)。装完先做两件事：

```shell
conda config --set auto_activate_base false   # 别让每个 shell 都落在 base
conda --version && python -V                  # 确认用的是 conda 的 python
```

`auto_activate_base` 关掉之后，进入环境要显式 `conda activate <name>`；IDE 里解释器路径要指到 `envs/<name>/bin/python`，否则会出现"终端能 import、IDE 报红"的错位。

## Environments

**不要在 base 环境上装项目依赖**，每个项目单独建环境：

```shell
conda create -n ML python=3.7 numpy pandas
conda activate ML
conda env list                    # 列出全部环境与路径
conda remove -n ML --all          # 删除整个环境
```

环境要显式创建，原因有两个：base 一旦污染就很难再判断哪个包是谁装的；`conda` 与 `pip` 混装时，`conda` 不会察觉 `pip` 装了什么，删环境是唯一干净的回退方式。

导出与复现：

```shell
conda env export -n ML > environment.yml     # 含 build 串，跨平台复现性差
conda env export -n ML --no-builds > environment.yml
conda env export -n ML --from-history > environment.yml   # 只记你显式装过的，最可移植
conda env create -f environment.yml
```

`environment.yml` 里的 `pip:` 段是二等公民——`conda` 只是转手调用 `pip`，不做跨解析器的一致性检查。所以同一个包的同一个依赖，**只该由一个工具负责**。

## Mixing conda and pip

推荐顺序：**先用 conda 装能装的一切，剩下的缺口才用 pip**，且一旦对某个包用了 `pip` 就不要再让 `conda` 升级它的依赖。反序（先 `pip install` 再 `conda install`）会让 conda 覆盖 pip 装的文件却不清理元数据，结果是 `import` 到的版本与 `pip list` 显示的不一致。

排查时确认包究竟来自哪一层：

```shell
python -c "import numpy, sys; print(numpy.__file__, sys.executable)"
conda list --revisions          # conda 侧的安装历史
```

现代替代：用 `conda` 只管 Python 版本与原生库，项目依赖全部交给 [uv](/docs/CS/Python/uv.md)（`uv venv` + `uv sync`），两者边界清晰。

## Jupyter

修改 working directory。配置文件位置随安装方式与版本而变，先确认实际使用的配置目录：`~/.jupyter`（Windows 下通常是 `C:\Users\{user}\.jupyter`），里面可能是 `jupyter_notebook_config.py` 或 `jupyter_server_config.py`；`jupyter --help` 列出本机可用的子命令，`--generate-config` 由具体子命令提供。

查找键：

```python
c.ServerApp.root_dir = "/path/to/workdir"
```

⚠️ 键名是 `c.ServerApp.root_dir`（下划线），不是 `c.ServerApp.root.dir`：Jupyter 从 7 起把服务端配置交给 `jupyter_server`，`ServerApp` 的 trait 名用下划线；写成点号分割的旧形式不会被识别，改完不报错也不生效。新版还有 `c.ServerApp.preferred_dir`（进入时默认打开的目录）。两者都能在 [Jupyter Server configuration reference](https://jupyter-server.readthedocs.io/en/latest/other/full-config.html) 里查到——**改完去那张表里核对键名，比猜有效**。

经典 Notebook 与 JupyterLab 的分别见 [Jupyter](/docs/CS/Python/Jupyter.md)。

## Links

- [Python](/docs/CS/Python/Python.md)
- [uv](/docs/CS/Python/uv.md)
- [Jupyter](/docs/CS/Python/Jupyter.md)
- [Packaging](/docs/CS/Python/Packaging.md)
- [README](/docs/CS/Python/README.md)

## References

- [Installing Miniconda](https://docs.anaconda.com/miniconda/install/)
- [conda user guide](https://docs.conda.io/projects/conda/en/latest/user-guide/index.html)
- [jupyter_server configuration](https://jupyter-server.readthedocs.io/en/latest/other/full-config.html)
