## Introduction

在图论中，欧拉路径（Eulerian path）是经过图中每条边恰好一次的路径，欧拉回路（Eulerian circuit）是经过图中每条边恰好一次的回路。 
如果一个图中存在欧拉回路，则这个图被称为欧拉图（Eulerian graph）；如果一个图中不存在欧拉回路但是存在欧拉路径，则这个图被称为半欧拉图（semi-Eulerian graph）

我们假设所讨论的图 G 中不存在孤立顶点。该假设不失一般性，因为对于存在孤立顶点的图 G ，以下性质对从 G 中删除孤立顶点后得到的图 G' 仍然成立。

对于连通图 G ，以下三个性质是互相等价的：

- G 是欧拉图；
- G 中所有顶点的度数都是偶数（对于有向图，每个顶点的入度等于出度）；
- G 可被分解为若干条不共边回路的并









## Links

- [graph](/docs/CS/Algorithms/graph/graph.md)
