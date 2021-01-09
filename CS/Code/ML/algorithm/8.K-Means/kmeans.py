import numpy as np

class KMeans:
    def __init__(self, k_clusters, tol=1e-4, max_iter=300, n_init=10):
        # 分为k簇
        self.k_clusters = k_clusters
        # 用于判断算法是否收敛的阈值
        self.tol = tol
        # 最大迭代次数
        self.max_iter = max_iter
        # 重新初始化中心点运行kmeans的次数
        self.n_init = n_init

    def _init_centers_kpp(self, X, n_clusters):
        '''K-Means++初始化簇质心算法'''

        m, n = X.shape
        distances = np.empty((m, n_clusters - 1))
        centers = np.empty((n_clusters, n))

        # 随机选择第一个簇中心
        np.copyto(centers[0], X[np.random.randint(m)])

        # 循环产生k-1个簇中心
        for j in range(1, n_clusters):
            # 计算各点到当前各簇中心的距离的平方
            for i in range(j):
                np.sum((X - centers[i]) ** 2, axis=1, out=distances[:, i])

            # 计算各点到最近中心的距离的平方
            nds = np.min(distances[:, :j], axis=1)

            # 以各点到最近中心的距离的平方构成的加权概率分布, 产生下一个簇中心:
            # 1.以[0, sum(nds))的均匀分布产生一个随机值
            r = np.sum(nds) * np.random.random()
            # 2.判断随机值r落于哪个区域, 对应实例被选为簇中心.
            for k in range(m):
                r -= nds[k]
                if r < 0:
                    break
            np.copyto(centers[j], X[k])

        return centers

    def _kmeans(self, X):
        '''K-Means核心算法'''

        m, n = X.shape
        # labels用于存储对m个实例划分簇的标记
        labels = np.zeros(m, dtype=np.int)
        # distances为m * k矩阵, 存储m个实例分别到k个中心的距离.
        distances = np.empty((m, self.k_clusters))
        # centers_old用于存储之前的簇中心
        centers_old = np.empty((self.k_clusters, n))
        
        # 初始化簇中心
        centers = self._init_centers_kpp(X, self.k_clusters)

        for _ in range(self.max_iter):
            # 1.分配标签
            # ==========
            for i in range(self.k_clusters):
                # 计算m个实例到各中心距离
                np.sum((X - centers[i]) ** 2, axis=1, out=distances[:, i])
            # 将m个实例划分到, 距离最近那个中心代表的簇.
            np.argmin(distances, axis=1, out=labels)

            # 2.计算重心
            # ==========
            # 保存之前簇中心
            np.copyto(centers_old, centers)
            for i in range(self.k_clusters):
                # 得到某簇所有数据 
                cluster = X[labels == i]
                # 注意: 如果某个初始中心离所有数据都很远, 可能导致没有实例被划入该簇, 
                # 则无法分为k簇, 返回None表示失败.
                if cluster.size == 0:
                    return None
                # 使用重新划分的簇计算簇中心
                np.mean(cluster, axis=0, out=centers[i])

            # 3.判断收敛
            # ==========
            # 计算新中心和旧中心的距离
            delta_centers = np.sqrt(np.sum((centers - centers_old) ** 2, axis=1))
            # 距离低于容忍度则判为算法收敛, 结束迭代.
            if np.all(delta_centers < self.tol):
                break

        # 计算簇内sse
        sse = np.sum(distances[range(m), labels])
        return labels, centers, sse

    def predict(self, X):
        '''分簇'''

        # 用于存储多次运行_kmeans的结果
        result = np.empty((self.n_init, 3), dtype=np.object)

        # 运行self.n_init次_kmeans
        for i in range(self.n_init):
            # 调用self._kmeans直到成功划分
            res = None
            while res is None:
                res = self._kmeans(X)
            result[i] = res
        
        # 选择最优模型的分簇结果(sse最低), 作为最终结果返回.
        k = np.argmin(result[:, -1])
        labels, self.centers_, self.sse_ = result[k]

        return labels
