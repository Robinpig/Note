## Introduction



无向连通图的 **最小生成树**（Minimum Spanning Tree，MST）为边权和最小的生成树



Prim算法是以顶点为基础,一点一点向外延申,直到所有的顶点都便利完成,算法结束,得到最小生成树,而Kruskal是以边为基础向外扩展,知道有n-1条边,算法结束,得到最小生成树.所以我们可以得到(**假如有两棵顶点树相同的树**)Prim更适用于边数较多的图(稠密图),而Kruskal更适用于边数较少的图 (稀疏图)





### Prim's Algorithm

prim算法的思想和Dijkstra很相似

### Kruskal's Algorithm

Kruskal算法的做法是：每次都从剩余边中选取权值最小的，当然，这条边不能使已有的边产生回路





## Links

- [graph](/docs/CS/Algorithms/graph/graph.md)