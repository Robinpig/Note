## Introduction

对于源文本 A 和目标文本 B，我们一定可以通过不断执行删除行和插入行两种操作，使得 A 转化成 B，这样的一系列插入和删除操作的序列就被称作编辑脚本

文本差分算法，可以定义为用于求出输入源文本和目标文本之间的编辑脚本的算法，广泛运用于各种需要进行文本对比的地方



如何评估一个文件差分算法

编辑脚本长度 求最短编辑长度(SES Shortest Edit Script) 长度越短越好

类似于多次求最长公共子序列(不唯一)

可读性 尽可能地保留整段文本 删除和插入操作减少交叉 同时通常删除操作在插入前面



git diff 的实现里，其实就内置有多个不同的 diff 算法

git diff 默认算法：Myers 差分算法

## Myers









## Links

- [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

