## Introduction

[Elasticsearch](https://www.elastic.co/cn/elasticsearch) is a distributed, RESTful search and analytics engine capable of addressing a growing number of use cases. 
As the heart of the Elastic Stack, it centrally stores your data for lightning fast search, fine‑tuned relevancy, and powerful analytics that scale with ease.

Elasticsearch 在分布式架构中有两个最常见的应用场景，一个是宽表、解决跨库 Join，另一个就是全文搜索


订单join:
- 根据订单号分库可以把订单表和订单详细信息表或者订单物流表分配到同库join
- 当根据用户id去查询所有订单时就会出现跨库


## Inverted Index



### KD Tree

The data-structure that underlies dimensional points is called a block KD tree,
which in the case of a single dimension is a simple binary search tree that stores blocks of values on the leaves rather than individual values.
Lucene currently defaults to having between 512 and 1024 values on the leaves.

This is quite similar to the b-trees that are used in most regular databases in order to index data.
In the case of Lucene, the fact that files are write-once makes the writing easy since we can build a perfectly balanced tree and then not worry about rebalancing since the tree will never be modified.
Merging is easy too since you can get a sorted iterator over the values that are stored in a segment,
then merge these iterators into a sorted iterator on the fly and build the tree of the merged segment from this sorted iterator.

## ELK

file beats -> MQ -> Logstash -> ES -> Kibana


## References

1. [Searching numb3rs in 5.0](https://www.elastic.co/blog/searching-numb3rs-in-5-0)
