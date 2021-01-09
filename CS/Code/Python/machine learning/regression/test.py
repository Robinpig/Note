import numpy as np
from sklearn.metrics import mean_squared_error
import OLSLinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error

data = np.genfromtxt('winequality-red.csv', delimiter=';', skip_header=True)
X=data[:,:-1]

X

y=data[:,:-1]

y


#创建模型
ols_lr=OLSLinearRegression()
#切分数据集为训练集和测试集，比例7：3
X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.3)
#训练模型
ols_lr.train(X_train,y_train)

y_pred=ols_lr.predict(X_test)

y_pred
#均方误差MSE
mse=mean_squared_error(y_train,y_pred)

mse

y_train_pred=ols_lr.predict(X_train)
mse_train=mean_squared_error(y_train,y_train_pred)
mse_train

#平均绝对误差MAE
mae=mean_absolute_error(y_test,y_pred)
mae
#---------------GDLinearRegression--------------------------