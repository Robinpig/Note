import numpy as np
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.ensemble import VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures
import torch

# load iris dataset
from sklearn.tree import DecisionTreeClassifier

iris = datasets.load_iris()
print(len(iris.data))  # the length of iris data is 150
X = iris["data"][:, (2, 3)]  # petal length, petal width
y = (iris["target"] == 2).astype(np.float64)  # Iris-Virginica
svm_clf = Pipeline((("scaler", StandardScaler()), ("linear_svc", LinearSVC(C=1, loss="hinge")),))
svm_clf.fit(X, y)
print(svm_clf.predict([[5.5, 1.7]]))

# transform narray to tensor
X = torch.tensor(X)
print(X.shape)
y = torch.tensor(y)
print(y.shape)
polynomial_svm_clf = Pipeline((("poly_features", PolynomialFeatures(degree=3)),
                               ("scaler", StandardScaler()),
                               ("svm_clf", LinearSVC(C=10, loss="hinge"))))
polynomial_svm_clf.fit(X, y)



log_clf = LogisticRegression()
rnd_clf = RandomForestClassifier()
svm_clf = SVC()
voting_clf = VotingClassifier(estimators=[('lr', log_clf), ('rf', rnd_clf), ('svc', svm_clf)],voting='hard')
voting_clf.fit(X, y)

from sklearn.ensemble import AdaBoostClassifier

ada_clf=AdaBoostClassifier(
    DecisionTreeClassifier(max_depth=2),n_estimators=200,
    algorithm="SAMME.R",learning_rate=0.04
)
ada_clf.fit(X,y)
print("importances: ",ada_clf.feature_importances_)

import tensorflow as tf
print(tf.version)