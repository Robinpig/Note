## Introduction

[ElasticJob](https://shardingsphere.apache.org/elasticjob/current/cn/overview/) 通过弹性调度、资源管控、以及作业治理的功能，打造一个适用于互联网场景的分布式调度解决方案，并通过开放的架构设计，提供多元化的作业生态。 它的各个产品使用统一的作业 API，开发者仅需一次开发，即可随意部署。


## Architecture

使用 ElasticJob 能够让开发工程师不再担心任务的线性吞吐量提升等非功能需求，使他们能够更加专注于面向业务编码设计； 同时，它也能够解放运维工程师，使他们不必再担心任务的可用性和相关管理需求，只通过轻松的增加服务节点即可达到自动化运维的目的。

ElasticJob 定位为轻量级无中心化解决方案，使用 jar 的形式提供分布式任务的协调服务。

![](https://shardingsphere.apache.org/elasticjob/current/img/architecture/elasticjob_lite.png)

ElasticJob-Cloud uses Mesos to manage and isolate resources.

![](https://shardingsphere.apache.org/elasticjob/current/img/architecture/elasticjob_cloud.png)




|                   | *ElasticJob-Lite* | *ElasticJob-Cloud* |
| ------------------- | ------------------- | -------------------- |
| Decentralization  | Yes               | No                 |
| Resource Assign   | No                | Yes                |
| Job Execution     | Daemon            | Daemon + Transient |
| Deploy Dependency | ZooKeeper         | ZooKeeper + Mesos  |






## Links

- [xxl-job](/docs/CS/Job/xxl-job.md)
- [ElasticJob](/docs/CS/Job/ElasticJob.md)


## References
