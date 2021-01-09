from sklearn import preprocessing  # 进行标准化数据时，需要引入个包
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.datasets import make_classification
from sklearn.svm import SVC
import matplotlib.pyplot as plt

X, y = make_classification(n_samples=300, n_features=2, n_redundant=0, n_informative=2, random_state=22,
                           n_clusters_per_class=1, scale=100)

# X=preprocessing.minmax_scale(X,feature_range=(-1,1))
X = preprocessing.scale(X)  # 0.966666666667 没有 0.477777777778
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3)
clf = SVC()
clf.fit(X_train, y_train)
print(clf.score(X_test, y_test))

plt.scatter(X[:, 0], X[:, 1], c=y)
plt.show()

a = np.array([[10, 2.7, 3.6],
              [-100, 5, -2],
              [120, 20, 40]], dtype=np.float64)  # 每一列代表一个属性
print(a)  # 标准化之前a　　　　　
print(preprocessing.scale(a))  # 标准化之后的a　
