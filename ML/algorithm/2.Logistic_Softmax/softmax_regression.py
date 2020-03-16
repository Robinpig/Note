import numpy as np

class SoftmaxRegression:
    def __init__(self, n_iter=200, eta=1e-3, tol=None):
        # 训练迭代次数
        self.n_iter = n_iter
        # 学习率
        self.eta = eta
        # 误差变化阈值
        self.tol = tol
        # 模型参数W(训练时初始化)
        self.W = None

    def _z(self, X, W):
        '''g(x)函数: 计算x与w的内积.'''
        if X.ndim == 1:
            return np.dot(W, X) 
        return np.matmul(X, W.T)

    def _softmax(self, Z):
        '''softmax函数'''
        E = np.exp(Z)
        if Z.ndim == 1:
            return E / np.sum(E)
        return E / np.sum(E, axis=1, keepdims=True)

    def _predict_proba(self, X, W):
        '''h(x)函数: 预测y为各个类别的概率.'''
        Z = self._z(X, W)
        return self._softmax(Z)

    def _loss(self, y, y_proba):
        '''计算损失'''
        m = y.size
        p = y_proba[range(m), y]
        return -np.sum(np.log(p)) / m

    def _gradient(self, xi, yi, yi_proba):
        '''计算梯度'''
        K = yi_proba.size
        y_bin = np.zeros(K)
        y_bin[yi] = 1

        return (yi_proba - y_bin)[:, None] * xi

    def _stochastic_gradient_descent(self, W, X, y):
        '''随机梯度下降算法'''

        # 若用户指定tol, 则启用早期停止法.
        if self.tol is not None:
            loss_old = np.inf
            end_count = 0

        # 使用随机梯度下降至多迭代n_iter次, 更新w.
        m = y.size
        idx = np.arange(m)
        for step_i in range(self.n_iter):
            # 计算损失
            y_proba = self._predict_proba(X, W)
            loss = self._loss(y, y_proba)
            print('%4i Loss: %s' % (step_i, loss))

            # 早期停止法
            if self.tol is not None:
                # 随机梯度下降的loss曲线不像批量梯度下降那么平滑(上下起伏),
                # 因此连续多次(而非一次)下降不足阈值, 才终止迭代.
                if loss_old - loss < self.tol:
                    print('haha')
                    end_count += 1
                    if end_count == 5:
                        break
                else:
                    end_count = 0

                loss_old = loss

            # 每一轮迭代之前, 随机打乱训练集.
            np.random.shuffle(idx)
            for i in idx:
                # 预测xi为各类别概率
                yi_proba = self._predict_proba(X[i], W)
                # 计算梯度
                grad = self._gradient(X[i], y[i], yi_proba)
                # 更新参数w
                W -= self.eta * grad


    def _preprocess_data_X(self, X):
        '''数据预处理'''

        # 扩展X, 添加x0列并置1.
        m, n = X.shape
        X_ = np.empty((m, n + 1))
        X_[:, 0] = 1
        X_[:, 1:] = X

        return X_

    def train(self, X_train, y_train):
        '''训练'''

        # 预处理X_train(添加x0=1)
        X_train = self._preprocess_data_X(X_train)  

        # 初始化参数向量W
        k = np.unique(y_train).size
        _, n = X_train.shape
        self.W = np.random.random((k, n)) * 0.05

        # 执行随机梯度下降训练W
        self._stochastic_gradient_descent(self.W, X_train, y_train)

    def predict(self, X):
        '''预测'''

        # 预处理X_test(添加x0=1)
        X = self._preprocess_data_X(X)  

        # 对每个实例计算向量z.
        Z = self._z(X, self.W)

        # 向量z中最大分量的索引即为预测的类别.
        return np.argmax(Z, axis=1)
