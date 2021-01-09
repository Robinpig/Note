from sklearn import datasets
from sklearn.linear_model import LinearRegression

# 使用以后的数据集进行线性回归
loaded_data = datasets.load_boston()
data_X = loaded_data.data
data_y = loaded_data.target

model = LinearRegression()
model.fit(data_X, data_y)

print(model.predict(data_X[:4, :]))
print(data_y[:4])

# 参数
print(model.coef_)  # 如果y=0.1x+0.3   则此行输出的结果为0.1
print(model.intercept_)  # 此行输出的结果为0.3
print(model.get_params())  # 模型定义时定义的参数，如果没有定义则返回默认值
print(model.score(data_X, data_y))  # 给训练模型打分，注意用在LinearR中使用R^2 conefficient of determination打分


