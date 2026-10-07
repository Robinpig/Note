## Introduction

Jupyter is a large umbrella project that covers many different software offerings and tools, including the popular Jupyter Notebook and JupyterLab web-based notebook authoring and editing applications.

技术栈上要分清四层，很多"装不上/打不开"的问题都是把它们混为一谈：

| 层 | 是什么 | 典型包 |
| :--- | :--- | :--- |
| 协议 | 消息格式与内核接口 | Jupyter protocol（kernel 侧靠 `ipykernel` 实现） |
| 服务端 | 跑在 localhost 的 Web 服务、鉴权、目录根 | `jupyter_server`（旧版 `notebook` 5/6 内自带） |
| 前端 | 界面 | `jupyterlab`（现代）/ `notebook`（classic） |
| 内核 | 真正执行代码的进程 | `ipykernel`(Python)、`xeus-cling`(C++)、IRkernel 等 |

内核与前端分离是 Jupyter 的核心设计：notebook 文件（`.ipynb`）是"代码 + 输出 + Markdown"的 JSON，输出由内核写入，所以**同一个 .ipynb 换内核结果可能不同**，也不能把它当可靠的版本控制对象（需要 `jupytext` 之类的文本化转换）。

## Installation

### JupyterLab

```shell
pip install jupyterlab
```

用 conda 或 mamba 时装 JupyterLab，官方建议走 conda-forge channel：

```shell
conda install -c conda-forge jupyterlab
```

### Notebook

classic Jupyter Notebook 是另一个包，与 JupyterLab 可共存：

```shell
pip install notebook
```

启动：`jupyter lab` 或 `jupyter notebook`。工作目录与配置键（`c.ServerApp.root_dir`）见 [conda](/docs/CS/Python/conda.md)；两个前端选哪个：新项目用 JupyterLab（多标签、可调面板、扩展体系），只需要"传统线性 notebook"时 classic 更轻。

## 与本地环境的关系

`jupyter lab` 用的 Python 解释器决定"`import` 得到哪些包"：在 conda 环境里 `pip install jupyterlab` 装的那份，看到的就是那个环境的包；base 里启动的 Jupyter 看不见项目环境的包。多环境正解是给每个环境装 `ipykernel` 后注册内核，从一个前端切换：

```shell
conda activate ML && pip install ipykernel
python -m ipykernel install --user --name ml --display-name "Python (ML)"
jupyter kernelspec list          # 查看已注册内核
```

比"每个环境各装一套 JupyterLab"更省心，也不会出现同名内核指向错解释器。

## ARM Mac 与 GPU

`pip install torch` 在 Apple Silicon 上装的是 MPS 后端版本，**不支持 CUDA**；AMD 显卡同样不支持 CUDA（ROCm 路线在 macOS 上不可用）。入门教程里的 `device = "cuda"` 片段在这两类机器上要改成 `mps`（Apple）或 `cpu`，且不少算子在 MPS 上仍未实现，回退到 CPU 时报错信息往往指向算子而不是设备。

## scikit-learn Quick Example

用 iris 数据集跑 KNN 的最小完整流程（加载 → 切分 → 训练 → 预测 → 评估 → 样本外预测）：

```python
# load the iris dataset as an example
from sklearn.datasets import load_iris
iris = load_iris()

# store the feature matrix (X) and response vector (y)
X = iris.data
y = iris.target

# splitting X and y into training and testing sets
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.4, random_state=1)

print("X_train Shape:", X_train.shape)
print("X_test Shape:", X_test.shape)
print("Y_train Shape:", y_train.shape)
print("Y_test Shape: ", y_test.shape)

# training the model on training set
from sklearn.neighbors import KNeighborsClassifier
knn = KNeighborsClassifier(n_neighbors=3)
knn.fit(X_train, y_train)

# making predictions on the testing set
y_pred = knn.predict(X_test)

# comparing actual response values (y_test) with predicted response values (y_pred)
from sklearn import metrics
print("KNN model accuracy", metrics.accuracy_score(y_test, y_pred))

# making prediction for out of sample data
sample = [[3, 5, 4, 2], [2, 3, 5, 4]]
preds = knn.predict(sample)
pred_species = [iris.target_names[p] for p in preds]
print("Predictions", pred_species)
```

值得记住的不是 API，而是 `train_test_split(..., random_state=1)`：不固定种子时同一份代码两次跑出的准确率不同，任何"我改了个特征所以变好了"的结论都不可信。多分类场景还应加 `stratify=y`，否则小类别可能在测试集里缺席。

## Notebook 作为文档

嵌入 Markdown：iPython 创建好 .ipynb 文件后，在 markdown 使用 `<iframe>` 标签，就可以将完成嵌入（docsify 站点里同理，见本仓库 `index.html` 的 remote-markdown 处理）。

需要把 notebook 当代码评审对象时，先把 JSON 里的 `outputs` 清掉（`jupyter nbconvert --clear-output` 或 `nbstripout`），否则每次运行都会产生巨大 diff。

## Links

- [Python](/docs/CS/Python/Python.md)
- [conda](/docs/CS/Python/conda.md)
- [uv](/docs/CS/Python/uv.md)
- [AI](/docs/CS/AI/AI.md)
- [README](/docs/CS/Python/README.md)

## References

- [Jupyter.org](https://jupyter.org/)
- [JupyterLab documentation](https://jupyterlab.readthedocs.io/en/stable/)
- [Jupyter Notebook documentation](https://jupyter-notebook.readthedocs.io/en/stable/)
- [Learning Model Building in scikit-learn](https://www.geeksforgeeks.org/learning-model-building-scikit-learn-python-machine-learning-library/)
- [PyTorch 教程（中文笔记）](https://tanbro.github.io/pytorch-tutorials-notebooks-zhs/beginner/blitz/tensor_tutorial/)
