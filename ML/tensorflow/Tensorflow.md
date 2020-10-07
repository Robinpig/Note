# Tensorflow

## 基本概念

- graphs表示计算任务
- 在Session的context执行graphs
- 使用tensor表示数据
- 通过Variable维护状态
- 使用feed和fetch为任意操作赋值或从中获取数据

### 计算模型——计算图

### 数据模型——张量

**tensor**-多维数组：

- 零阶-标量（scalar）
- 一阶-向量（vector）
- n阶-n维数组

 一个张量中主要保存了三个**属性**：

- 名字（name）

   唯一标识符 

- 维度（shape）

   描述了一个张量的维度信息 

- 类型（type） 

   每一个张量会有一个唯一的类型 

###  **运行模型——会话** 