## Introduction

并查集 (不相交集) 是一种描述不相交集合的数据结构「不相交」描述的是问题元素构成集合之后各个集合不相交的状态，「并查」描述的是处理问题时的操作

并查集是一颗森林，由多颗树组成，每一颗树代表一个集合 每个集合由树的根节点作为代表元，两个节点在同一个集合中（也就是连通）的话，它们的代表元（也就是根节点）是相同的

并查集主要是解决一些元素分组的问题

并查集支持两种操作：

- 合并（*Union*）：合并两个集合（将不同集合的根节点中一个节点的父节点赋值为另一个节点）
- 查找（*Find*）：判断两个元素是否在同一个集合中（查找根节点是否相同）





p[] 存储每个节点的父节点信息 根节点的值可以指向自己或者其它带有意义的值

```python
int Find(int x){
	if(p[x] == x)
    return x;
  else
    return p[x] = Find(p[x]); // 路径压缩
}
```



 按高度合并 矮树合并到高树 高度不变

```python
void Union(int x, int y){
  int rootx = Find(x);
  int rooty = Find(y);
  if(rootx != rooty){
    if(h[rootx] < h[rooty]){
    	p[rootx] = rooty;
    } else if(h[rootx] > h[rooty]){ 
    	p[rooty] = rootx;
    } else{
    	p[rootx] = rooty;
    	h[rooty]++;
    }
  }
}
```







```python
void Union(int x, int y){
  int rootx = Find(x);
  int rooty = Find(y);
  if(rootx != rooty){
    if(s[rootx] <= s[rooty]) {
    	p[rootx] = rooty;
      s[rooty] += s[rootx];
    } else { 
    	p[rooty] = rootx;
       s[rootx] += s[rooty];
    }
  }
}
```









## Links

- [Tree](/docs//Cs/Algorithms/Tree.md)