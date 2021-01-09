import numpy as np

class CartClassificationTree:
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

    def __init__(self, gini_threshold=0.01, gini_dec_threshold=0., min_samples_split=2):
        '''构造器函数'''
        # 基尼系数的阈值
        self.gini_threshold = gini_threshold
        # 基尼系数降低的阈值
        self.gini_dec_threshold = gini_dec_threshold
        # 数据集还可继续分割的最小样本数量
        self.min_samples_split = min_samples_split

    def _gini(self, y):
        '''计算基尼指数'''
        values = np.unique(y)

        s = 0.
        for v in values:
            y_sub = y[y == v]
            s += (y_sub.size / y.size) ** 2

        return 1 - s

    def _gini_split(self, y, feature, value):
        '''计算根据特征切分后的基尼指数'''
        # 根据特征的值将数据集拆分成两个子集
        indices = feature > value
        y1 = y[indices]
        y2 = y[~indices]

        # 分别计算两个子集的基尼系数
        gini1 = self._gini(y1)
        gini2 = self._gini(y2)

        # 计算分割后的基尼系数
        # gini(y, feature) = (|y1| * gini(y1) + |y2| * gini(y2)) / |y|
        gini = (y1.size * gini1 + y2.size * gini2) / y.size

        return gini

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

        min_gini = np.inf
        _, n = X.shape
        for feature_index in range(n):
            # 迭代每一个特征
            feature = X[:, feature_index]
            # 获得一个特征的所有分割点
            split_points = self._get_split_points(feature)
            for value in split_points:
                # 迭代每一个分割点value, 计算使用value分割后的数据集基尼系数.
                gini = self._gini_split(y, feature, value)
                # 找到更小的gini, 则更新分割特征和.
                if gini < min_gini:
                    min_gini = gini 
                    best_feature_index = feature_index
                    best_split_value = value

        # 判断分割后基尼系数的降低是否超过阈值
        if self._gini(y) - min_gini < self.gini_dec_threshold:
            best_feature_index = None
            best_split_value = None

        return best_feature_index, best_split_value, min_gini

    def _node_value(self, y):
        '''计算节点的值'''
        # 统计数据集中样本类标记的个数
        labels_count = np.bincount(y)
        # 节点值等于数据集中样本最多的类标记.
        return np.argmax(np.bincount(y))

    def _create_tree(self, X, y):
        '''生成树递归算法'''
        # 创建节点
        node = self.Node()
        # 计算节点的值, 等于y的均值.
        node.value = self._node_value(y)

        # 若当前数据集样本数量小于最小分割数量min_samples_split, 则返回叶节点.
        if y.size < self.min_samples_split:
            return node

        # 若当前数据集的基尼系数小于阈值gini_threshold, 则返回叶节点.
        if self._gini(y) < self.gini_threshold:
            return node

        # 选择最佳分割特征
        feature_index, feature_value, min_gini = self._select_feature(X, y)
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
