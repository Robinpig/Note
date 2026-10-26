# Apollo Namespace

## Introduction

Namespace 是 Apollo 数据模型里最容易被低估的一层：它既是**配置的分组单位**（可以简单类比为一个文件），也是**权限的最小单元**。官方原文：「Namespace 是一个权限的最小单元，而 App 是一个权限的最大单元」，中间依次是 Env、Cluster。本文讲四维坐标的语义、私有与公共 namespace 的分野、配置格式规则，基线为 v3.0.0。

## Four-dimensional Coordinate

Apollo 用四个维度管理 Key-Value 配置：**application → environment → cluster → namespace**。每一维的「该不该跟着代码走」都有明确答案，这是 Apollo 与「一个配置文件打天下」方案的分界：

| 维度 | 语义 | 与代码的关系 |
| :-- | :-- | :-- |
| application（appId） | 应用身份 | **跟代码走**——同一份代码在任何地方跑都是同一个 appId |
| environment | DEV / FAT / UAT / PRO | **不跟代码走**——同一份代码部署在不同环境应读到不同配置 |
| cluster | 实例分组（典型按机房 / IDC） | 与部署位置绑定，默认 `default` |
| namespace | 配置分组（类比文件） | 按用途切分：数据库配置、RPC 配置、应用自身配置 |

- **env 的指定**：默认读机器上的 `server.properties`（`/opt/settings/server.properties`）的 `env` 属性，也可运行时 System Property 指定。内置 DEV / FAT / UAT / PRO（大小写不敏感）；自定义环境名有强制转换，`PROD` → `PRO`、`FWS` → `FAT`。
- **cluster 的指定**：优先级 `apollo.cluster` > `idc` > `default`。集群支持**父子集群**（`Cluster.ParentClusterId`，0 表示无父），用于表达「大部分配置继承某集群、个别项覆盖」的部署形态。
- **namespace 的命名**：名称即格式标识（见下文），且**公共 namespace 名称全局唯一**——创建时 Apollo 会自动把部门代号加在最前面。

## Private and Public Namespace

| 类型 | 归属 | 典型用途 |
| :-- | :-- | :-- |
| 私有 namespace | 只被所属应用使用 | 应用专属配置（数据源、开关、阈值） |
| 公共 namespace | 可被其它应用**关联**使用 | 公共组件 / 中间件配置（RPC 框架、监控组件、注册中心地址） |

官方对「公共组件」的定义：发布的类库、客户端程序，**不会自己独立运行**（如 Java 的 jar 包）——它们的配置运行时寄生在业务应用里，所以需要独立的 namespace 与独立的发布节奏。

**关联与覆盖**：应用通过「关联公共 namespace」把公共配置读进来（需项目管理员权限），关联后可以**覆盖**其中部分配置项——因为「实际应用的运行时、环境各不一样」。官方给的例子：关联 hermes producer 的公共 namespace 后，在本应用下覆盖 `sender.batchSize=1000`，发布后该应用运行时读到的就是 1000。

**多 AppId 共享一份配置**的通用模式：在一个 AppId 下建公共 namespace 写公共配置，各项目读取；需要覆盖的应用关联后写覆盖值即可。公共 namespace 的灰度规则需**先指定 appId** 再选 IP / label（见 [Portal](/docs/CS/Framework/Apollo/Portal.md)）。

创建权限注意：私有 namespace 的创建受 `admin.createPrivateNamespace.switch` 控制（ApolloPortalDB.ServerConfig），公共 namespace 只有项目管理员能创建。

## Config Formats

格式由 **namespace 名称的后缀**决定：

| 格式 | namespace 示例 | 客户端读取方式 |
| :-- | :-- | :-- |
| properties（默认） | `application` | `ConfigService.getConfig(...)`，表格模式逐项 key-value |
| yml / yaml | `application.yml` | 同 properties（1.3.0 起对 yaml 支持完善） |
| xml / json / txt | `test.xml` 等 | `ConfigService.getConfigFile("test", ConfigFileFormat.XML)` |

- properties 格式可以直接对 key / value 检索；xml / json / yml / yaml / txt 存储时以 **content-value** 成对存储，即一个 key 对应整份文件内容。
- 除表格模式外还提供**文本模式**批量编辑——从已有 properties 文件迁移尤其有用。
- **非 properties、非 yaml 的 namespace 不支持和 Spring 整合**（`@Value` / `spring.config.import` 只吃这两种形态）。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Client](/docs/CS/Framework/Apollo/Client.md)
- [Portal](/docs/CS/Framework/Apollo/Portal.md)
- [Storage](/docs/CS/Framework/Apollo/Storage.md)
- [Nacos](/docs/CS/Framework/nacos/README.md)

## References

- <https://www.apolloconfig.com/#/zh/portal/apollo-user-guide>
- <https://www.apolloconfig.com/#/zh/client/java-sdk-user-guide>
