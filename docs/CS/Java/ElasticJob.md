## Introduction

[ElasticJob](https://shardingsphere.apache.org/elasticjob/current/en/overview/) is a distributed scheduling solution consisting of two separate projects, ElasticJob-Lite and ElasticJob-Cloud.

Through the functions of flexible scheduling, resource management and job management, it creates a distributed scheduling solution suitable for Internet scenarios, and provides a diversified job ecosystem through open architecture design.
It uses a unified job API for each project. Developers only need code one time and can deploy at will.

ElasticJob-Lite is a lightweight, decentralized solution that provides distributed task sharding services.

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

## References
