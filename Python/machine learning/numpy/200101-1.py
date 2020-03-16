
from sklearn.datasets import load_iris
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from numpy.linalg import eig

iris=load_iris()
X=iris.data
X=X-X.mean(axis=0)
#计算协方差矩阵
X_cov=np.cov(X.T,ddof=0)
#计算协方差矩阵特征值和特征向量
eigenvalues,eigenvectors=eig(X_cov)

tot=sum(eigenvalues)
var_exp=[(i/tot) for i in sorted(eigenvalues,reverse=True)]
cum_var_exp=np.cumsum(var_exp)
plt.bar(range(1,5),var_exp,alpha=0.5,align='center',label='individual var')
plt.step(range(1,5),cum_var_exp,where='mid',label='cumulative var')
plt.ylabel('variance rtion')
plt.xlabel('principal coponents')
plt.legend(loc='best')
plt.show()