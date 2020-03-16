import numpy as np

class CartRegressionTree:
    class Node:
        '''树节点类'''

        def __init__(self):
            self.value = None

            # 内部叶节点属性
            self.feature_index = None
            self.feature_value = None
            self.left = None
            self.right = None

        def __str__(self):
            if self.left:
                s = '内部节点<%s>:\n' % self.feature_index
                ss = '[ >%s]-> %s' % (self.feature_value, self.left)
                s += '\t' + ss.replace('\n', '\n\t') + '\n'
                ss = '[<=%s]-> %s' % (self.feature_value, self.right)
                s += '\t' + ss.replace('\n', '\n\t')
            else:
                s = '叶节点(%s)' % self.value
            return s

    def __init__(self, mse_threshold=0.01, mse_dec_threshold=0., min_samples_split=2):
        '''构造器函数'''
        # mse的阈值
        self.mse_threshold = mse_threshold
        # mse降低的阈值
        self.mse_dec_threshold = mse_dec_threshold
        # 数据集还可继续分割的最小样本数量
        self.min_samples_split = min_samples_split

    def _mse(self, y):
        '''计算MSE'''
        # 估计值为y的均值, 因此均方误差即方差.
        return np.var(y)

    def _mse_split(self, y, feature, value):
        '''计算根据特征切分后的MSE'''
        # 根据特征的值将数据集拆分成两个子集
        indices = feature > value
        y1 = y[indices]
        y2 = y[~indices]

        # 分别计算两个子集的均方误差
        mse1 = self._mse(y1)
        mse2 = self._mse(y2)

        # 计算划分后的总均方误差
        return (y1.size * mse1 + y2.size * mse2) / y.size

    def _get_split_points(self, feature):
        '''获得一个连续值特征的所有分割点'''
        # 获得一个特征所有出现过的值, 并排序.
        values = np.unique(feature)
        # 分割点为values中相邻两个点的中点.
        split_points = [(v1 + v2) / 2 for v1, v2 in zip(values[:-1], values[1:])]

        return split_points

    def _select_feature(self, X, y):
        '''选择划分特征'''
        # 最佳分割特征的index
        best_feature_index = None
        # 最佳分割点
        best_split_value = None

        min_mse = np.inf
        _, n = X.shape
        for feature_index in range(n):
            # 迭代每一个特征
            feature = X[:, feature_index]
            # 获得一个特征的所有分割点
            split_points = self._get_split_points(feature)
            for value in split_points:
                # 迭代每一个分割点value, 计算使用value分割后的数据集mse.
                mse = self._mse_split(y, feature, value)
                # 找到更小的mse, 则更新分割特征和.
                if mse < min_mse:
                    min_mse = mse 
                    best_feature_index = feature_index
                    best_split_value = value

        # 判断分割后mse的降低是否超过阈值, 如果没有超过, 则找不到适合分割特征.
        if self._mse(y) - min_mse < self.mse_dec_threshold:
            best_feature_index = None
            best_split_value = None

        return best_feature_index, best_split_value, min_mse

    def _node_value(self, y):
        '''计算节点的值'''
        # 节点值等于样本均值
        return np.mean(y)

    def _create_tree(self, X, y):
        '''生成树递归算法'''
        # 创建节点
        node = self.Node()
        # 计算节点的值, 等于y的均值.
        node.value = self._node_value(y)

        # 若当前数据集样本数量小于最小分割数量min_samples_split, 则返回叶节点.
        if y.size < self.min_samples_split:
            return node

        # 若当前数据集的mse小于阈值mse_threshold, 则返回叶节点.
        if self._mse(y) < self.mse_threshold:
            return node

        # 选择最佳分割特征
        feature_index, feature_value, min_mse = self._select_feature(X, y)
        if feature_index is not None:
            # 如果存在适合分割特征, 当前节点为内部节点.
            node.feature_index = feature_index
            node.feature_value = feature_value

            # 根据已选特征及分割点将数据集划分成两个子集.
            feature = X[:, feature_index]
            indices = feature > feature_value
            X1, y1 = X[indices], y[indices]
            X2, y2 = X[~indices], y[~indices]

            # 使用数据子集创建左右子树.
            node.left = self._create_tree(X1, y1)
            node.right = self._create_tree(X2, y2)

        return node

    def _predict_one(self, x_test):
        '''对单个样本进行预测'''
        # 爬树一直爬到某叶节点为止, 返回叶节点的值.
        node = self.tree_
        while node.left:
            if x_test[node.feature_index] > node.feature_value:
                node = node.left
            else:
                node = node.right

        return node.value

    def train(self, X_train, y_train):
        '''训练决策树'''
        self.tree_ = self._create_tree(X_train, y_train)

    def predict(self, X_test):
        '''对测试集进行预测'''
        # 对每一个测试样本, 调用_predict_one, 将收集到的结果数组返回.
        return np.apply_along_axis(self._predict_one, axis=1, arr=X_test)
