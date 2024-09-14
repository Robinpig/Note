## Introduction



三种实现高可靠和高可用的方法优劣对比

Master/Slave，Based on ZooKeeper/Etcd 和 Raft，这三种是目前分布式系统中，做到高可靠和高可用的基本的实现方法，各有优劣。

- Master/Slave

优点：实现简单

缺点：不能自动控制节点切换，一旦出了问题，需要人为介入。

- Based on Zookeeper/Etcd

优点：可以自动切换节点

缺点：运维成本很高，因为 ZooKeeper 本身就很难运维。

- Raft

优点：可以自己协调，并且去除依赖。

缺点：实现 Raft，在编码上比较困难





Dledger 作为一个轻量级的 Java Library，它的作用就是将 Raft 有关于算法方面的内容全部抽象掉，开发人员只需要关心业务即可



