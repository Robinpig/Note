from numpy import *
import scipy.spatial.distance as dist

vector1 = mat([1, 2, 3])
vector2 = mat([4, 5, 6])
# 曼哈顿距离（城市街区距离）实现
print(sum(abs(vector1 - vector2)))

# 欧式距离（L2范数）
print(sqrt((vector1 - vector2) * (vector1 - vector2).T))

# 闵可夫斯基距离 为一组距离的定义

# 切比雪夫距离
print(sqrt(abs(vector1 - vector2).max))

# 夹角余弦
print(dot(vector1, vector2) / (linalg.norm(vector1) * linalg.norm(vector2)))

# 汉明距离
matV = mat([1, 1, 1, 1], [1, 0, 0, 1])
smstr = nonzero(matV[0] - matV[1])
print(smstr)

# 杰卡德相似系数

# 杰卡德距离
matV = mat([1, 1, 1, 1], [1, 0, 0, 1])
print(dist.pdist(matV, 'jaccard'))


