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

> 社区 [discuss.elastic](https://discuss.elastic.co/) 和 [elastic中文社区](https://elasticsearch.cn/)



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







<!-- tabs:start -->



##### **Windows**




##### **Ubuntu**




##### **Docker**

[Install Elasticsearch with Docker](https://www.elastic.co/guide/en/elasticsearch/reference/current/docker.html)



<!-- tabs:end -->

验证

curl ’http://localhost:9200/?pretty‘




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

一个 Elasticsearch 集群可以包含多个 索引（数据库），也就是说其中包含了很多 类型（表）。这些类型中包含了很多的 文档（行），然后每个文档中又包含了很多的 字段（列）


Elasticsearch  ⇒ 索引   ⇒ 类型  ⇒ 文档  ⇒ 字段(Fields)




for example
```http
PUT /megacorp/employee/1
{
”first_name“ : ”John“,
”last_name“ :  ”Smith“,
”age“ :        25,
”about“ :      ”I love to go rock climbing“,
”interests“: [ ”sports“, ”music“ ]
}
```


获取内容包含元数据信息

```http
GET /megacorp/employee/1
```









## Cluster
Node是ES的实例 对于内存要求高 生产环境建议一台机器一个实例 每个node都有一个name node在启动之后会分配一个UUID存储在data目录



## Analyzer

通常说"ES分词器"指的其实是Analyzer，"分析器"也是指的Analyzer，但Tokenizer（中文翻译过来也是分词器）是Analyzer组成不可缺少的部分

 

分词是指将文本转换成一系列单词( term or token )的过程,也可以叫做文本分析,在es里面称为Analysis 



## Inverted Index



### KD Tree

The data-structure that underlies dimensional points is called a block KD tree,
which in the case of a single dimension is a simple binary search tree that stores blocks of values on the leaves rather than individual values.
Lucene currently defaults to having between 512 and 1024 values on the leaves.

This is quite similar to the b-trees that are used in most regular databases in order to index data.
In the case of Lucene, the fact that files are write-once makes the writing easy since we can build a perfectly balanced tree and then not worry about rebalancing since the tree will never be modified.
Merging is easy too since you can get a sorted iterator over the values that are stored in a segment,
then merge these iterators into a sorted iterator on the fly and build the tree of the merged segment from this sorted iterator.



## Issues

### OOM

Elastic Search 集群出现OOM
```
[---][ERROR][o.e.b.ElasticsearchUncaughtExceptionHandler] [master-172.16.0.135-9200] fatal error in thread [Thread-7], exiting
java.lang.OutOfMemoryError: Java heap space
	at io.netty.buffer.PoolArena$HeapArena.newChunk(PoolArena.java:656) ~[?:?]
	at io.netty.buffer.PoolArena.allocateNormal(PoolArena.java:237) ~[?:?]
	at io.netty.buffer.PoolArena.allocate(PoolArena.java:221) ~[?:?]
	at io.netty.buffer.PoolArena.allocate(PoolArena.java:141) ~[?:?]
	at io.netty.buffer.PooledByteBufAllocator.newHeapBuffer(PooledByteBufAllocator.java:272) ~[?:?]
	at io.netty.buffer.AbstractByteBufAllocator.heapBuffer(AbstractByteBufAllocator.java:160) ~[?:?]
	at io.netty.buffer.AbstractByteBufAllocator.heapBuffer(AbstractByteBufAllocator.java:151) ~[?:?]
	at io.netty.buffer.AbstractByteBufAllocator.ioBuffer(AbstractByteBufAllocator.java:133) ~[?:?]
	at io.netty.channel.DefaultMaxMessagesRecvByteBufAllocator$MaxMessageHandle.allocate(DefaultMaxMessagesRecvByteBufAllocator.java:73) ~[?:?]
	at io.netty.channel.nio.AbstractNioByteChannel$NioByteUnsafe.read(AbstractNioByteChannel.java:117) ~[?:?]
	at io.netty.channel.nio.NioEventLoop.processSelectedKey(NioEventLoop.java:642) ~[?:?]
	at io.netty.channel.nio.NioEventLoop.processSelectedKeysPlain(NioEventLoop.java:527) ~[?:?]
	at io.netty.channel.nio.NioEventLoop.processSelectedKeys(NioEventLoop.java:481) ~[?:?]
	at io.netty.channel.nio.NioEventLoop.run(NioEventLoop.java:441) ~[?:?]
	at io.netty.util.concurrent.SingleThreadEventExecutor$5.run(SingleThreadEventExecutor.java:858) ~[?:?]
	at java.lang.Thread.run(Thread.java:882) [?:1.8.0_152]
```


基本通过如下几种方式来解决OOM问题：
修改调用链保存时间。调用链默认保存7天，比如说修改为3天，这样可以降低集群的数据量。
调整shards的数据量，可以从默认的16调整到32或48。Elasticsearch中一个索引是由若干个shard组成的，通过增加shard数，可以降低每个shard的数据量，以达到降低节点内存占用的效果。
扩容节点内存和数量。

这几个优化的手段都尝试了，但现场反馈仍然存在OOM问题。截止第一阶段的优化，现场一共有16台机器，其中3台为master不作为datanode，13台为datanode。节点的内存配置为 72GB 或 48GB ，并且按照Elasticsearch官方建议，Elasticsearch进程的JVM堆最大已经调整到接近 32GB

副本冗余是需要的 当某节点损坏后清理掉数据 没有副本就会永久丢失部分数据 再重新启动后索引会变成red 节点状态正常 日志无报错 但是 读取shard情况 发现总会存在 shard unassign的状态
curl -POST '127.0.0.1:9200/_cat/shards?v'
此时无法忽略这个丢失的shard 只能清理掉 red index

一个本不需要做索引的大字段，被错误设置成了全文检索类型，导致高并发写入时数据无法及时索引落盘，最终引发堆溢出


错误定义了索引
"index":"not_analyzed" 并不是不做索引，而是不对内容进行全文索引，仅是作为一个keyword来索引。
```json
"spanEvents": {
    "type":"text",
    "index":"not_analyzed"
}
```
应该定义为

```json

"spanEvents": {
    "type":"text",
    "index": false
}
```


## References

1. [Searching numb3rs in 5.0](https://www.elastic.co/blog/searching-numb3rs-in-5-0)
2. [伴鱼数据库之慢日志系统](https://tech.ipalfish.com/blog/2020/07/21/tidb_slowlog/)
