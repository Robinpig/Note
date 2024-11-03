## Introduction

[Elasticsearch](https://www.elastic.co/cn/elasticsearch) is a distributed, RESTful search and analytics engine capable of addressing a growing number of use cases. 
As the heart of the Elastic Stack, it centrally stores your data for lightning fast search, fine‑tuned relevancy, and powerful analytics that scale with ease.

> ELK包括 Elasticsearch、[Kibana](/docs/CS/Framework/ES/Kibana.md)、[Beats](/docs/CS/Framework/ES/Beats.md) 和 [Logstash](/docs/CS/Framework/ES/Logstash.md)

日志采集系统

filebeat -> MQ -> Logstash -> ES -> Kibana

filebeat配置


Logstash负责解析转换日志



告警
规则设置与通知机制


Elasticsearch 在分布式架构中有两个最常见的应用场景，一个是宽表、解决跨库 Join，另一个就是全文搜索


订单join:
- 根据订单号分库可以把订单表和订单详细信息表或者订单物流表分配到同库join
- 当根据用户id去查询所有订单时就会出现跨库


## Install

Elastic7.13.7启动报错error updating geoip database

在配置文件elasticsearch.yml设置ingest.geoip.downloader.enabled: false


ES8开发环境配置
```properties
# disable other discovery configs
discovery.type: single-node

# disable security features
xpack.security.enabled: false

ingest.geoip.downloader.enabled: false
```

##### **Windows**




##### **Ubuntu**




##### **Docker**


### start

注意节点启动顺序 有Master选举
```shell
bin/elasticsearch -E node.name=node0 -E cluster.name=es -E path.data=node0_data -d
bin/elasticsearch -E node.name=node1 -E cluster.name=es -E path.data=node1_data -d
bin/elasticsearch -E node.name=node2 -E cluster.name=es -E path.data=node2_data -d
bin/elasticsearch -E node.name=node3 -E cluster.name=es -E path.data=node3_data -d
```
查看节点 `http://localhost:9200/_cat/nodes`


### Plugins

查看安装插件
```shell
bin/elasticsearch-plugin list
```


```shell
bin/elasticsearch-plugin install analysis-icu
```

## Data Model


Document会序列化成JSON格式

每个Document都会有一份metadata




## Cluster
Node是ES的实例 对于内存要求高 生产环境建议一台机器一个实例 每个node都有一个name node在启动之后会分配一个UUID存储在data目录

## Inverted Index



### KD Tree

The data-structure that underlies dimensional points is called a block KD tree,
which in the case of a single dimension is a simple binary search tree that stores blocks of values on the leaves rather than individual values.
Lucene currently defaults to having between 512 and 1024 values on the leaves.

This is quite similar to the b-trees that are used in most regular databases in order to index data.
In the case of Lucene, the fact that files are write-once makes the writing easy since we can build a perfectly balanced tree and then not worry about rebalancing since the tree will never be modified.
Merging is easy too since you can get a sorted iterator over the values that are stored in a segment,
then merge these iterators into a sorted iterator on the fly and build the tree of the merged segment from this sorted iterator.





## References

1. [Searching numb3rs in 5.0](https://www.elastic.co/blog/searching-numb3rs-in-5-0)
2. [伴鱼数据库之慢日志系统](https://tech.ipalfish.com/blog/2020/07/21/tidb_slowlog/)
