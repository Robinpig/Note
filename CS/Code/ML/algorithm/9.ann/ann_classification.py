import numpy as np

class ANNClassifier:
    def __init__(self, hidden_layer_sizes=(30, 30), eta=0.01, max_iter=500, tol=0.001):
        '''构造器方法'''
        # 各隐藏层节点个数
        self.hidden_layer_sizes = hidden_layer_sizes
        # 随机梯度下降的学习率
        self.eta = eta
        # 随机梯度下降最大迭代次数
        self.max_iter = max_iter
        # 误差阈值
        self.tol = tol

    def _sigmoid(self, z):
        '''激活函数, 计算节点输出.'''
        return 1. / (1. + np.exp(-z))

    def _z(self, x, W):
        '''加权求和, 计算节点净输入.'''
        return np.matmul(x, W)

    def _error(self, y, y_predict):
        '''计算误差(mse)'''
        return np.sum((y - y_predict) ** 2) / len(y)
        
    def _backpropagation(self, X, y):
        '''反向传播算法(基于随机梯度下降)'''
        m, n = X.shape
        _, n_out = y.shape

        # 获得各层节点个数元组layer_sizes, 以及总层数layer_n.
        layer_sizes = self.hidden_layer_sizes + (n_out,)
        layer_n = len(layer_sizes)

        # 对于每一层, 将所有节点的权向量(以列向量形式)存为一个矩阵, 保存至W_list.
        W_list = []
        li_size = n
        for lj_size in layer_sizes:
            W = np.random.rand(li_size + 1, lj_size) * 0.03
            W_list.append(W)
            li_size = lj_size

        # 创建运行梯度下降时所使用的列表
        in_list      = [None] * layer_n
        z_list       = [None] * layer_n
        out_list     = [None] * layer_n
        delta_list   = [None] * layer_n

        # 随机梯度下降
        idx = np.arange(m)
        for _ in range(self.max_iter):
            # 随机打乱训练集
            np.random.shuffle(idx)
            X, y = X[idx], y[idx]

            for x, t in zip(X, y):
                # 单个样本作为输入, 运行神经网络.
                out = x
                for i in range(layer_n):
                    # 第i-1层输出添加x0=1, 作为第i层输入.
                    in_ = np.ones(out.size + 1)
                    in_[1:] = out 
                    # 计算第i层所有节点的净输入
                    z = self._z(in_, W_list[i])
                    # 计算第i层各节点输出值
                    out = self._sigmoid(z)
                    # 保存第i层各节点的输入, 净输入, 输出.
                    in_list[i], z_list[i], out_list[i] = in_, z, out

                # 反向传播计算各层节点delta
                # 输出层
                delta_list[-1] = out * (1. - out) * (t - out)
                # 隐藏层
                for i in range(layer_n - 2, -1, -1):
                    out_i, W_j, delta_j = out_list[i], W_list[i+1], delta_list[i+1]
                    delta_list[i] = out_i * (1. - out_i) * np.matmul(W_j[1:], delta_j[:, None]).T[0]

                # 更新所有节点的权
                for i in range(layer_n):
                    in_i, delta_i = in_list[i], delta_list[i]
                    W_list[i] += in_i[:, None] * delta_i * self.eta

            # 计算训练误差.
            y_pred = self._predict(X, W_list)
            err = self._error(y, y_pred)

            # 判断收敛(误差是否小于阈值)
            if err < self.tol:
                break

            print('%4s. err: %s' % (_+1, err))

        # 返回训练好的权矩阵列表
        return W_list

    def train(self, X, y):
        '''训练'''
        # 调用反向传播算法, 训练神经网络中所有节点的权.
        self.W_list = self._backpropagation(X, y)

    def _predict(self, X, W_list, return_int=False):
        '''预测内部接口'''
        layer_n = len(W_list)

        out = X
        for i in range(layer_n):
            # 第i-1层输出添加x0=1, 作为第i层输入.
            m, n = out.shape
            in_ = np.ones((m, n + 1))
            in_[:, 1:] = out
            # 计算第i层所有节点的净输入
            z = self._z(in_, W_list[i])
            # 计算第i层所有节点输出值
            out = self._sigmoid(z)

        # 是否返回int型的二进制编码(类标记)
        if return_int:
            # 将输出最大的节点输出置为1, 其他节点输出置为0.
            idx = np.argmax(out, axis=1)
            out_int = np.zeros_like(out)
            out_int[range(len(idx)), idx] = 1
            return out_int

        return out

    def predict(self, X):
        '''预测'''
        return self._predict(X, self.W_list, return_int=True)
