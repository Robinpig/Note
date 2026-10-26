# Apollo Portal

## Introduction

Portal 是 Apollo 唯一的管理面（默认端口 8070），也是 Open API 的入口。它承载的不是配置本身，而是**治理**：编辑与发布分离的双权限、灰度发布分支、回滚、审计。官方设计原话：「配置的修改需要点击灰度发布后才会生效，**规则的修改在规则点击完成后就会实时生效**」——这类「什么立即生效、什么要走发布」的区分，是 Portal 使用中最容易踩的坑。本文基线为 v3.0.0。

## Edit and Publish Separation

Apollo 把配置管理拆成两个独立权限环节：

| 权限 | 允许的操作 | 生效范围 |
| :-- | :-- | :-- |
| 编辑权限 | 创建、修改、删除配置项 | **只在 Apollo 界面上变化，不影响应用实际使用的配置** |
| 发布权限 | 发布、回滚 | **只有发布 / 回滚动作后才被应用真正使用** |

应用创建完**默认没有分配任何编辑和发布权限**，需项目管理员显式授权——这套「默认无权限」是把双权限机制落到实处的关键，避免了「谁都能改、改了就算」。

## RBAC Model

Portal 的权限链存在 ApolloPortalDB 里（表结构见 [Storage](/docs/CS/Framework/Apollo/Storage.md)）：

```
Users ──(UserRole)──> Role ──(RolePermission)──> Permission ──> TargetId + PermissionType
Consumer ──(ConsumerRole)──> Role              （Open API 的 consumer 授权）
Authorities（Username → Authority）            （Spring Security 粗粒度角色）
```

权限粒度阶梯：**namespace 是最小单元，App 是最大单元**，中间是 Env、Cluster。也就是说一个权限对象一定落在某个 namespace 或 App 上，PermissionType 表达「对这个对象能做什么」（修改 / 发布等）。

服务端侧相关开关（ApolloPortalDB.ServerConfig）：

| 配置项 | 语义 |
| :-- | :-- |
| `role.create-application.enabled` | 是否管控创建项目的权限（1.5.0+，默认 false） |
| `role.manage-app-master.enabled` | 项目管理员分配权限开关（1.5.0+） |
| `admin.createPrivateNamespace.switch` | 是否允许项目管理员创建私有 namespace |
| `configView.memberOnly.envs` | 仅项目成员可见配置信息的环境列表（1.1.0+） |
| `emergencyPublish.supported.envs` | 允许紧急发布的环境列表 |

「项目成员」的判定：项目管理员 + 具备该私有 namespace 在该环境下修改或发布权限的人。

## Gray Release

灰度发布用于「对程序有比较大影响的配置，先在一个或多个实例生效，观察没问题再全量」。完整七步（以对某实例灰度 `timeout=3000`、其余保持 `2000` 为例）：

1. **创建灰度**：点击 namespace 右上角「创建灰度」，页面切到「灰度版本」Tab。
2. **灰度配置**：在主版本配置里对 `timeout` 点「对此配置灰度」，填灰度值并提交。
3. **配置灰度规则**：切到「灰度规则」Tab 新增规则——
   - **按 IP**：下拉框默认列出当前正在使用配置的机器，找不到可手动输入 IP（手动输入说明该机器还没从 Apollo 取过配置）；
   - **按 Label**（2.0.0+）：适用于 IP 不固定的场景如 **Kubernetes**，客户端配 `apollo.label`，规则按标签匹配；
   - 公共 namespace 的灰度规则**需先指定 appId** 再选 IP / Label。
4. **灰度发布**：在「配置」Tab 检查后点「灰度发布」，确认对话框展示「主版本的值是 2000，灰度版本即将发布的值是 3000」。
5. **验证**：通过「灰度实例列表」与主版本的「实例列表」核对各实例实际使用的版本。
6. **全量发布**：效果是三件事——灰度版本配置**合并回主版本**、主版本**自动进行一次发布**、可选择是否保留灰度版本（默认不保留）。
7. **放弃灰度**：灰度不理想或不需要时点「放弃灰度」，灰度实例回退到主版本。

生效时机的两条铁律：

- **配置**的修改必须点「灰度发布」才生效；
- **规则**的修改点完成就实时生效。

分支状态机存在 `GrayReleaseRule` 表：`BranchStatus` = 0 删除分支 / 1 正在使用的规则 / 2 全量发布。`ReleaseHistory.Operation` 则记录全部发布类型：0 普通发布、1 回滚、2 灰度发布、3 灰度规则更新、4 灰度合并回主分支发布、5 主分支发布灰度自动发布、6 主分支回滚灰度自动发布、7 放弃灰度——**灰度不是旁路记录，而是与主分支发布联动的状态机**（主分支一动，灰度自动跟着发布或回滚）。

## Rollback

回滚的语义官方用了一个贴切的类比：**回滚只回滚「发布到客户端的配置」，不回滚页面上编辑中的配置**——如同发布系统把部署到机器上的安装包回退到上一个版本，而代码仓库里的代码不会回退。因此修复流程是：回滚（先止血）→ 在编辑态修配置 → 重新发布。回滚目标永远是**上一个已发布版本**。

## Audit

v3.0.0 的审计是**链路化 + 字段级**的：

- `AuditLog`：带 `TraceId` / `SpanId` / `ParentSpanId` / `FollowsFromSpanId`，记录 `Operator`、`OpType` / `OpName`、`Description`——一次操作涉及的多步变更挂在同一条 trace 下；
- `AuditLogDataInfluence`：字段级旧值 / 新值（`FieldOldValue` / `FieldNewValue`），精确到「哪个表的哪个字段从什么改成了什么」；
- Open API 侧另有 `ConsumerAudit`（consumer 的 API 调用记录）与 `UserTokenAudit`（用户 token 的访问记录）；
- 旧版 `Audit` 表仍在 schema 中，作为历史兼容。

配套的还有 `NamespaceLock`——namespace 级编辑锁，防止多人同时修改同一份配置。

## Open API

Open API 经 Portal（默认 8070）暴露，非 JVM 语言（Go / Python / NodeJS 等）主要靠它 + 各语言 SDK 接入：

- 调用方需在 Portal 创建应用并取得 token（`Consumer` / `ConsumerToken`，带 `RateLimit` 与 `Expires`），token 盐值 `consumer.token.salt` 建议用 `openssl rand -hex 32` 生成，修改后约一分钟生效；
- 2.5.0 新增：`configfiles` API（直接返回配置文件原始内容）、组织列表 API、按 namespace 统计实例数 API；
- **3.0.0 起 Portal 管理流全面 OpenAPI-first**，配置项、namespace、发布、灰度分支、权限、导入导出都走生成的 OpenAPI 契约；
- 3.0.0 新增**用户访问 token**（`UserToken`：`TokenPrefix` + `TokenHash` 不存明文、`Scopes` JSON 描述 operations/appIds/envs/namespaces 范围、`RateLimit`、`RevokedAt`），面向 AI agent 与自动化；配套官方推出 `apollo-cli`（OpenAPI 命令行）与 `apollo-evals`（agent 任务评估）两个独立仓库。

## Links

- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)
- [Namespace](/docs/CS/Framework/Apollo/Namespace.md)
- [Storage](/docs/CS/Framework/Apollo/Storage.md)
- [Client](/docs/CS/Framework/Apollo/Client.md)
- [Dubbo Auth](/docs/CS/Framework/Dubbo/Auth.md)

## References

- <https://www.apolloconfig.com/#/zh/portal/apollo-user-guide>
- <https://www.apolloconfig.com/#/en/deployment/distributed-deployment-guide>
- <https://github.com/apolloconfig/apollo/releases>
