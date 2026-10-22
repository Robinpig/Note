## Introduction

ZooKeeper 的 ACL 控制 znode 的访问权限，沿用类 Unix 的"三段式"思路，但三段含义不同：ZK 是 **`scheme : id : permission`**——分别表述"权限机制 / 被允许的身份 / 具体权限位"。它挂在 znode 上（见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 的数据模型），与 Linux 的 owner / group / other 不同。

> **范围界定：** 本页只讲 ACL 的**数据模型与版本语义**。认证源（digest / ip / sasl / x509 / super 如何配置）与 TLS 见 [安全 security](/docs/CS/Framework/ZooKeeper/security.md)；客户端 `addAuth` 用法见 [客户端 client](/docs/CS/Framework/ZooKeeper/client.md)。

## 三段式：scheme : id : permission

- **scheme**：身份来源机制（who 的解析方式）。常见有 `world`、`auth`、`digest`、`ip`、`super`、`sasl`、`x509`。
- **id**：在该 scheme 下的具体身份，如 digest 的 `user:BASE64(SHA1(user:password))`、ip 的 `192.168.1.0/24`、`world` 的 `anyone`。
- **permission**：权限位，见下。

## 权限位 Permission Bits

与 [security](/docs/CS/Framework/ZooKeeper/security.md) 一致，标准位为：

- `CREATE (c)`：创建子节点
- `READ (r)`：读取数据 / 子节点列表
- `WRITE (w)`：写数据 / 设置 ACL
- `DELETE (d)`：删除子节点（注意不等于写数据）
- `ADMIN (a)`：设置 ACL

预定义便捷集（见 `ZooDefs.Ids`）：`OPEN_ACL_UNSAFE`（全开放）、`CREATOR_ALL_ACL`（创建者全权）、`READ_ACL_UNSAFE`（只读）。

## ACL 如何挂在 znode 上

- `DataNode` 持有 `acl`（`long` 引用，指向 ACL 缓存中的实际列表，复用计数）；`StatPersisted` 维护 `aversion`——每次 `setACL` 自增，用于 CAS 防止并发覆盖。
- 创建节点时通过 `CreateMode` + ACL 列表一并写入；`setACL(path, acl, version)` 支持带版本的条件更新（版本不符抛 `BadVersionException`，与数据版本的 CAS 机制同源，见 [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md) 的 Data Model）。
- 权限校验发生在请求处理链前段：[pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md) 的 `PrepRequestProcessor.checkAcl()` 遍历节点 ACL，无权限抛 `NoAuthException`。

## 校验链路：从客户端到 NoAuthException

一次带权限的写请求要通过三道关：

1. **客户端**先 `addAuthInfo(scheme, auth)` 把身份注入当前**会话**（见 [client](/docs/CS/Framework/ZooKeeper/client.md)）；会话失效后身份不保留，需重新注入。
2. **服务端**收到请求时由对应 scheme 的 `AuthenticationProvider` 校验身份（如 `DigestAuthenticationProvider.handleAuthentication`），把通过的 scheme 加入连接的 `authInfo` 集合。
3. **请求预处理** `PrepRequestProcessor.checkAcl()` 拿节点的 ACL 列表逐条比对连接已认证的 scheme，无匹配权限则抛 `NoAuth` 中断——**请求不会进入提案/提交阶段**。

```java
// PrepRequestProcessor.checkAcl 的核心逻辑（简化）
void checkACL(Request request, List<ACL> acl, List<ACL> authInfo) throws KeeperException.NoAuthException {
    if (acl == null || acl.size() == 0) return;          // 节点无 ACL 限制，直接放行
    for (ACL a : acl) {
        if (authInfo.contains(a)) return;                 // 命中任一条即通过
    }
    throw new KeeperException.NoAuthException();
}
```

## 陷阱：ACL 不继承

> [!WARNING]
> ZooKeeper 的 ACL 是**节点级、不继承**的：子节点**不会**自动获得父节点的 ACL。创建子节点时若不带 ACL，则采用 `world:anyone:cdrwa`（除非沿用父的策略）。这是"以为加了 ACL 实际裸奔"的高发点——给父节点 `/app` 加了 ACL，不会自动保护 `/app/config`。**创建关键节点时必须显式带 ACL。**

其他高频坑：

| 坑 | 说明 |
| :--- | :--- |
| `delete` 权限在**父节点** | 删子节点看的是**父节点**的 `d` 位，不是子节点自身的权限。"删不掉子节点"多因父节点缺 `d` |
| digest 存的是散列 | `id` 是 `user:base64(sha1(user:password))`，不是明文；但 `addAuthInfo` 传的是**明文**，须配合 TLS/SASL 保护传输 |
| 身份绑会话 | 会话过期/重建后 `authInfo` 丢失，需重新 `addAuthInfo`（见 [Session](/docs/CS/Framework/ZooKeeper/Session.md)） |
| `auth` scheme 的含义 | `auth` 表示"匹配任何已通过认证的身份"，常用于"登录后放开全部"的场景 |

## 与 etcd / Chubby 的对照

- **etcd**：RBAC + mTLS，角色 / 绑定模型，无 per-key 的 `scheme:id` 粒度；
- **Chubby**：文件级 ACL + 客户端身份认证；
- **ZooKeeper**：per-znode 的 `scheme:id:permission`，灵活但需业务自行管理身份分发（digest 密码散列、ip 段、Kerberos）。

## Links

- [ZooKeeper 枢纽](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [安全 security（认证源与 TLS 配置）](/docs/CS/Framework/ZooKeeper/security.md)
- [客户端 client（addAuthInfo 用法）](/docs/CS/Framework/ZooKeeper/client.md)
- [请求处理链 pipeline](/docs/CS/Framework/ZooKeeper/pipeline.md)
- [Session（身份绑会话）](/docs/CS/Framework/ZooKeeper/Session.md)
- [Curator（生产级 ACL 处理）](/docs/CS/Framework/ZooKeeper/Curator.md)

## References

1. [ZooKeeper Programmer's Guide — ACLs](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html#sc_ZooKeeperACLs)
2. [ZooKeeper 3.9.0 Release Notes](https://zookeeper.apache.org/doc/r3.9.0/releaseNotes.html)
