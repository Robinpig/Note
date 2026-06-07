## Introduction


Jupyter 是一个大型伞状项目，涵盖许多不同的软件产品与工具，包括流行的 Jupyter Notebook 和 JupyterLab 基于 Web 的笔记本编写和编辑应用程序。

## Installation

### Notebook

### JupyterLab

使用 pip 安装 JupyterLab：

注意：如果用 conda 或 mamba 安装 JupyterLab，建议使用 conda-forge 频道。
安装后，使用以下命令启动 JupyterLab：
Jupyter Notebook
安装经典 Jupyter Notebook：
运行 notebook：

https://tanbro.github.io/pytorch-tutorials-notebooks-zhs/beginner/blitz/tensor_tutorial/
ARM mac install torch 和AMD显卡一样不支持CUDA
https://www.geeksforgeeks.org/learning-model-building-scikit-learn-python-machine-learning-library/

scikit-learn
# load the iris dataset as an example
from sklearn.datasets import load_iris
iris = load_iris()

# store the feature matrix (X) and response vector (y)
X = iris.data
y = iris.target

# splitting X and y into training and testing sets
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.4, random_state=1)

# printing the shapes of the new X objects
print("X_train Shape:",  X_train.shape)
print("X_test Shape:", X_test.shape)

# printing the shapes of the new y objects
print("Y_train Shape:", y_train.shape)
print("Y_test Shape: ",y_test.shape)
# load the iris dataset as an example
from sklearn.datasets import load_iris
iris = load_iris()

# store the feature matrix (X) and response vector (y)
X = iris.data
y = iris.target

# splitting X and y into training and testing sets
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.4, random_state=1)

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


## Links

