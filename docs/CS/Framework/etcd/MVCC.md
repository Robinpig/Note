## Introduction

多版本并发控制 (Multiversion concurrency control) 模块是为了解决etcd v2 不支持保存 key 的历史版本、不支持多 key 事务等问题而产生的
它核心由内存树形索引模块 (treeIndex) 和嵌入式的 KV 持久化存储库 boltdb 组成。



## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)
