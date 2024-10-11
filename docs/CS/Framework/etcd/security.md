# Introduction


etcd鉴权体系架构由控制面和数据面组成



AuthServer收到请求后，为了确保各节点间鉴权元数据一致性，会通过Raft模块进行数据同步。

当对应的Raft日志条目被集群半数以上节点确认后，Apply模块通过鉴权存储(AuthStore)模块，执行日志条目的内容，将规则存储到boltdb的一系列鉴权bucket中

数据面鉴权流程，由认证和授权流程组成。



## Authentication

认证的目的是检查client的身份是否合法、防止匿名用户访问等。目前etcd实现了两种认证机制，分别是密码认证和证书认证
认证通过后，为了提高密码认证性能，会分配一个Token（类似我们生活中的门票、通信证）给client，client后续其他请求携带此Token，server就可快速完成client的身份校验工作。

实现分配Token的服务也有多种，这是TokenProvider所负责的，目前支持SimpleToken和JWT两种。

通过认证后，在访问MVCC模块之前，还需要通过授权流程。授权的目的是检查client是否有权限操作你请求的数据路径，etcd实现了RBAC机制，支持为每个用户分配一个角色，为每个角色授予最小化的权限


用户密码认证。etcd支持为每个用户分配一个账号名称、密码。密码认证在我们生活中无处不在，从银行卡取款到微信、微博app登录，再到核武器发射，密码认证应用及其广泛，是最基础的鉴权的方式

但密码认证存在两大难点，它们分别是如何保障密码安全性和提升密码认证性能。

etcd的用户密码存储正是融合了高安全性hash函数（Blowfish encryption algorithm）、随机的加盐salt、可自定义的hash值计算迭代次数cost

可以通过如下的auth enable命令开启鉴权，注意etcd会先要求你创建一个root账号，它拥有集群的最高读写权限


```shell
$ etcdctl user add root:root
User root created
$ etcdctl auth enable —-user="root:root"
Authentication Enabled
```


通过鉴权模块的user命令，给etcd增加一个alice账号。我们一起来看看etcd鉴权模块是如何基于我上面介绍的技术方案，来安全存储alice账号信息。

```shell
$ etcdctl user add alice:alice --user root:root
User alice created
```

鉴权模块收到此命令后，它会使用bcrpt库的blowfish算法，基于明文密码、随机分配的salt、自定义的cost、迭代多次计算得到一个hash值，并将加密算法版本、salt值、cost、hash值组成一个字符串，作为加密后的密码。
最后，鉴权模块将用户名alice作为key，用户名、加密后的密码作为value，存储到boltdb的authUsers bucket里面，完成一个账号创建。
当你使用alice账号访问etcd的时候，你需要先调用鉴权模块的Authenticate接口，它会验证你的身份合法性
鉴权模块首先会根据你请求的用户名alice，从boltdb获取加密后的密码，因此hash值包含了算法版本、salt、cost等信息，因此可以根据你请求中的明文密码，计算出最终的hash值，若计算结果与存储一致，那么身份校验通过

当etcd server验证用户密码成功后，它就会返回一个Token字符串给client，用于表示用户的身份。后续请求携带此Token，就无需再次进行密码校验，实现了通信证的效果

Simple Token的核心原理是当一个用户身份验证通过后，生成一个随机的字符串值Token返回给client，并在内存中使用map存储用户和Token映射关系。当收到用户的请求时， etcd会从请求中获取Token值，转换成对应的用户名信息，返回给下层模块使用
etcd生成的每个Token，都有一个过期时间TTL属性，Token过期后client需再次验证身份，因此可显著缩小数据泄露的时间窗口，在性能上、安全性上实现平衡。
在etcd v3.4.9版本中，Token默认有效期是5分钟，etcd server会定时检查你的Token是否过期，若过期则从map数据结构中删除此Token。
不过你要注意的是，Simple Token字符串本身并未含任何有价值信息，因此client无法及时、准确获取到Token过期时间。所以client不容易提前去规避因Token失效导致的请求报错

为什么etcd社区仅建议在开发、测试环境中使用Simple Token呢？
首先它是有状态的，etcd server需要使用内存存储Token和用户名的映射关系。
其次，它的可描述性很弱，client无法通过Token获取到过期时间、用户名、签发者等信息

当对安全有更高要求的时候，你需要使用HTTPS协议加密通信数据，防止中间人攻击和数据被篡改等安全风险。
HTTPS是利用非对称加密实现身份认证和密钥协商，因此使用HTTPS协议的时候，你需要使用CA证书给client生成证书才能访问



## Authorization

开启鉴权后，put请求命令在应用到状态机前，etcd还会对发出此请求的用户进行权限检查， 判断其是否有权限操作请求的数据。常用的权限控制方法有ACL(Access Control List)、ABAC(Attribute-based access control)、RBAC(Role-based access control)，etcd实现的是RBAC机制
因为有可能一个用户拥有成百上千个权限列表，etcd为了提升权限检查的性能，引入了区间树，检查用户操作的key是否在已授权的区间，时间复杂度仅为O(logN)




## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

