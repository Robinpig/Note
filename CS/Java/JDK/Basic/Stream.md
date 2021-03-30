# Stream



Lazy Traversal

1. 过滤器因为支持在迭代过程中结束处理，所以有很大的性能优势
2. 即使都要处理整个数据集，一个过滤器还是要比一个迭代器稍微快些
3. 多个过滤器有些开销，所以要确保编写好用的过滤器

返回值是否为stream

- 及早求值

- 惰性求值



How to create Stream?

Collection

Arrays

Stream of()

Stream empty()

Stream iterate() generate()



- distinct
- skip
- limit
- filter



### 结构

- 流获取
- 转换操作 : 可以有多个
- 终止操作 : 只能有一个

###  类型

- stream() : 单管道
- parallelStream()
  - 多管道，并行流式处理，底层使用 ForkJoinPool 实现
  - 强制要求有序 : forEachOrdered()



- collect(toList)
- map
- filter
- flatMap
- max/min
- reduce
- sort

End operation

- allMatch
- anyMatch
- noneMatch
- findFirst
- findAny
- count
- max/min
- forEach






