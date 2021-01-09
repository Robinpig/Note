import numpy as np


class OLSLinearRegression:
    def _ols(self, X, y):
        tmp = np.linalg.inv(np.matmul(X.T, X))
        tmp = np.matmul(tmp, X.T)
        return np.matmul(tmp, y)
        #也可使用如下实现
        #return np.linalg.inv(X.T @ X) @ X.T @ y
    def _preprocess_data_X(self,X):

        m,n=X.shape
        X_=np.empty((m,n+1))
