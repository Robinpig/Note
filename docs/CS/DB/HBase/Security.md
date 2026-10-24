## Introduction

HBase 的安全分三层：认证（Kerberos）、授权（表/列族/列 ACL + cell 级 Visibility Labels）、配额与多租户。本页要点是 2.x 起授权默认关闭这一反直觉事实，以及 cell 级可见性标签依赖 HFile v3 的 per-cell Tags（与 [HFile](/docs/CS/DB/HBase/HFile.md) 的 v3 分水岭同源）。

## Security and Quotas

- **认证**：集群对接 Kerberos；2.x 起授权开关 `hbase.security.authorization` **默认为 `false`**，只开认证不开授权时所有用户实际都是 superuser。
- **两层授权**：表/列族/列级 ACL 管「能不能读这张表」；cell 级 **Visibility Labels** 管「这个 cell 谁能看」（如打上 `top-secret` 标签、只授予特定组）。labels 的实现依赖 HFile v3 的 per-cell **Tags**——这也是 [HFile](/docs/CS/DB/HBase/HFile.md) 把 v3 当作 2.0+ 分水岭的原因。
- **配额**：`hbase.quota.enabled` 默认关闭，开启后可按用户/表/namespace 做 `THROTTLE`（区分 READ / WRITE 或合计），限流粒度到 sec / min / hour / day。
- **多租户**：namespace 隔离表组，配 ACL 与配额构成租户边界。

## Links

- [HBase](/docs/CS/DB/HBase.md)
- [HFile](/docs/CS/DB/HBase/HFile.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [Apache HBase Reference Guide](https://hbase.apache.org/book.html)
