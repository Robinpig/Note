# Introduction


etcd鉴权体系架构由控制面和数据面组成



AuthServer收到请求后，为了确保各节点间鉴权元数据一致性，会通过Raft模块进行数据同步。

当对应的Raft日志条目被集群半数以上节点确认后，Apply模块通过鉴权存储(AuthStore)模块，执行日志条目的内容，将规则存储到boltdb的一系列鉴权bucket中


数据面鉴权流程，由认证和授权流程组成。

认证的目的是检查client的身份是否合法、防止匿名用户访问等。目前etcd实现了两种认证机制，分别是密码认证和证书认证
认证通过后，为了提高密码认证性能，会分配一个Token（类似我们生活中的门票、通信证）给client，client后续其他请求携带此Token，server就可快速完成client的身份校验工作。

实现分配Token的服务也有多种，这是TokenProvider所负责的，目前支持SimpleToken和JWT两种。

通过认证后，在访问MVCC模块之前，还需要通过授权流程。授权的目的是检查client是否有权限操作你请求的数据路径，etcd实现了RBAC机制，支持为每个用户分配一个角色，为每个角色授予最小化的权限


用户密码认证。etcd支持为每个用户分配一个账号名称、密码。密码认证在我们生活中无处不在，从银行卡取款到微信、微博app登录，再到核武器发射，密码认证应用及其广泛，是最基础的鉴权的方式

但密码认证存在两大难点，它们分别是如何保障密码安全性和提升密码认证性能。

etcd的用户密码存储正是融合了高安全性hash函数（Blowfish encryption algorithm）、随机的加盐salt、可自定义的hash值计算迭代次数cost

可以通过如下的auth enable命令开启鉴权，注意etcd会先要求你创建一个root账号，它拥有集群的最高读写权限


$ etcdctl user add root:root
User root created
$ etcdctl auth enable —-user="root:root"
Authentication Enabled








## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References


