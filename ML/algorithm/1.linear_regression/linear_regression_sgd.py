import numpy as np

class SGDLinearRegression:

    def __init__(self, n_iter=1000, eta=0.01):
        # 训练迭代次数
        self.n_iter = n_iter
        # 学习率
        self.eta = eta
        # 模型参数theta (训练时根据数据特征数量初始化)
        self.theta = None

    def _gradient(self, xi, yi, theta):
        # 计算当前梯度
        return -xi * (yi - np.dot(xi, theta))

    def _stochastic_gradient_descent(self, X, y, eta, n_iter):
        # 复制X（避免随机乱序时改变原X）
        X = X.copy()
        m, _ = X.shape

        eta0 = eta
        step_i = 0

        for j in range(n_iter):
            # 随机乱序
            np.random.shuffle(X)
            for i in range(m):
                # 计算梯度(每次只使用其中一个样本)
                grad = self._gradient(X[i], y[i], self.theta)
                # 更新参数theta
                step_i += 1
                #eta = 4.0 / (1.0 + i + j) + 0.000000001
                eta = eta0 / np.power(step_i, 0.25)
                self.theta += eta * -grad

    def train(self, X, y):
        if self.theta is None:
            _, n = X.shape
            self.theta = np.zeros(n)

        self._stochastic_gradient_descent(X, y, self.eta, self.n_iter)

    def predict(self, X):
        return np.dot(X, self.theta)
