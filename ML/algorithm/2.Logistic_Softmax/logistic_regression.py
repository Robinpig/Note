import numpy as np

class LogisticRegression:
    def __init__(self, n_iter=200, eta=1e-3, tol=None):
        # 训练迭代次数
        self.n_iter = n_iter
        # 学习率
        self.eta = eta
        # 误差变化阈值
        self.tol = tol
        # 模型参数w(训练时初始化)
        self.w = None

    def _z(self, X, w):
        '''g(x)函数: 计算x与w的内积.'''
        return np.dot(X, w) 

    def _sigmoid(self, z):
        '''Logistic函数'''
        return 1. / (1. + np.exp(-z))

    def _predict_proba(self, X, w):
        '''h(x)函数: 预测y为1的概率.'''
        z = self._z(X, w)
        return self._sigmoid(z)

    def _loss(self, y, y_proba):
        '''计算损失'''
        m = y.size
        p = y_proba * (2 * y - 1) + (1 - y)
        return -np.sum(np.log(p)) / m

    def _gradient(self, X, y, y_proba):
        '''计算梯度'''
        return np.matmul(y_proba - y, X) / y.size

    def _gradient_descent(self, w, X, y):
        '''梯度下降算法'''

        # 若用户指定tol, 则启用早期停止法.
        if self.tol is not None:
            loss_old = np.inf

        self.loss_list = []

        # 使用梯度下降至多迭代n_iter次, 更新w.
        for step_i in range(self.n_iter):
            # 预测所有点为1的概率
            y_proba = self._predict_proba(X, w)
            # 计算损失
            loss = self._loss(y, y_proba)
            self.loss_list.append(loss)
            #print('%4i Loss: %s' % (step_i, loss))

            # 早期停止法
            if self.tol is not None:
                # 如果损失下降不足阈值, 则终止迭代.
                if loss_old - loss < self.tol:
                    break
                loss_old = loss

            # 计算梯度
            grad = self._gradient(X, y, y_proba)
            # 更新参数w
            w -= self.eta * grad

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

        # 初始化参数向量w
        _, n = X_train.shape
        self.w = np.random.random(n) * 0.05

        # 执行梯度下降训练w
        self._gradient_descent(self.w, X_train, y_train)

    def predict(self, X):
        '''预测'''

        # 预处理X_test(添加x0=1)
        X = self._preprocess_data_X(X)  

        # 预测y=1的概率
        y_pred = self._predict_proba(X, self.w)

        # 根据概率预测类别
        return np.where(y_pred >= 0.5, 1, 0)
