# Silo Deployment and Migration

## Introduction

Silo 的部署形态与 MinIO 完全同构——单二进制、无独立元数据服务、纠删码、server pool 横向扩展。**架构部分的通用内容在 [MinIO](/docs/CS/Distributed/MinIO.md) 笔记里已经展开，本册不重复**，只讲 Silo 特有的部分：交付面改名带来的差异、迁移的具体步骤、以及每个步骤的验证点。

迁移的核心结论先说：**不需要迁移数据**。磁盘格式 `xl.meta` 兼容、S3 API 不变、`MINIO_*` 环境变量不变，应用侧几乎零改动。

## The Compatibility Contract

### Preserved Exactly

| 面 | 内容 |
| :--- | :--- |
| S3 API | AWS SigV4 签名语义、错误码、XML 响应格式 |
| 环境变量 | 全部 `MINIO_*`（`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`MINIO_OPTS`、`MINIO_VOLUMES`…） |
| 指标 | `minio_*` 全量（`minio_bucket`、`minio_heal`、`minio_inter_node`…） |
| HTTP 头 | `x-minio-*` 全量（`x-minio-deployment-id`、`x-minio-internal`…） |
| 路由 | `/minio/*` 与 S3 路由 |
| 磁盘数据 | `xl.meta` 布局、`.minio.sys` 目录（`.minio.sys/format.json`、`.minio.sys/config/config.json`…） |
| IAM 策略 | `arn:minio:...` / `minio:s3:...` 形式的 ARN 与策略值 |
| 桶与对象 | 原有桶、对象、版本、Object Lock 状态全部可见可改 |

这套清单不是口头承诺——它被 `buildscripts/rebrand-guard/compat-baseline.json` 冻结在 CI 里，具体见 [Compatibility Guard](/docs/CS/Distributed/Silo/Compatibility_Guard.md)。

### Renamed

| 交付面 | 上游 | Silo |
| :--- | :--- | :--- |
| 可执行文件 | `minio` | `silo`（**不安装 `minio` 别名**） |
| 客户端 | `mc` | `mcli`（来自 `pgsty/mc`） |
| 容器镜像 | `minio/minio` | `pgsty/silo` |
| 包 | `minio` | `silo`（RPM/DEB/APK） |
| systemd 服务 | `minio.service` | `silo.service` |
| Helm chart | `minio/minio` | `helm/silo` |
| 文档站 | `min.io/docs` | `silo.pgsty.com` |

> **诚实边界**：对未修改上游 MinIO / MC 的兼容是 *best effort*；官方支持的发布栈是 `pgsty/silo + pgsty/silo-console + pgsty/mc + pgsty/silo-pkg`。除此之外的组合（尤其是自己改了上游源码再混用）不在支持范围内。

## Migration Path One: Docker

最简单的一条。环境变量、命令参数、挂载卷全都不动，只换镜像名：

```bash
docker run -d --name silo -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=change-me-long-password \
  -v "$PWD/data:/data" \
  docker.io/pgsty/silo:RELEASE.2026-10-18T00-00-00Z server /data --console-address ":9001"
```

**必须 pin 具体 tag，不要用 `latest`**。理由见 [Release Engineering](/docs/CS/Distributed/Silo/Release_Engineering.md)：无人维护的 fork 里 `latest` 指向不确定 commit。

镜像自带客户端，排障不用另拉容器：

```bash
docker exec silo mcli alias set local http://127.0.0.1:9000 minioadmin change-me-long-password
docker exec silo mcli mb local/demo
docker exec silo mcli ls local
```

**验证点**：控制台 `http://localhost:9001` 应当出现**完整的管理界面**（用户管理、桶策略、访问控制、生命周期），而不是社区版被砍剩的对象浏览器——这是 Silo 恢复 console 的直观体现。

## Migration Path Two: systemd

从 `minio.service` 切到 `silo.service`。Silo 自带的 unit 文件已经处理好了兼容细节：

```ini
[Unit]
Description=Silo Object Storage Server
After=network-online.target minio.service
Conflicts=minio.service
AssertFileIsExecutable=/usr/bin/silo

[Service]
Type=notify
User=silo
Group=silo
ProtectProc=invisible

EnvironmentFile=-/etc/default/minio
EnvironmentFile=-/etc/default/silo
ExecStart=/usr/bin/silo server $MINIO_OPTS $MINIO_VOLUMES
```

迁移步骤：

1. 安装 `silo` 包（不卸载 `minio` 也可以，两个包可并存）。
2. `systemctl stop minio && systemctl disable minio`。
3. `systemctl enable --now silo`。
4. 若旧服务以特定 UID/GID 运行（如 `minio:minio`），用 drop-in 保持一致：

```ini
# /etc/systemd/system/silo.service.d/10-legacy-user.conf
[Service]
User=minio
Group=minio
```

5. `systemctl daemon-reload` 后重启。

**为什么能并存与切换**：`EnvironmentFile=-/etc/default/minio` 的前导减号表示"文件不存在也不报错"，所以旧配置可以原样沿用；`ExecStart` 里的变量名仍是 `$MINIO_OPTS` / `$MINIO_VOLUMES`；而 `Conflicts=minio.service` + `After=... minio.service` 保证同一台机器上两者不会同时抢盘。

配套的 `/etc/default/silo` 模板**故意不含生效赋值**（只有注释示例），目的是让旧配置默认继承、想覆盖时再显式写：

```sh
# MINIO_VOLUMES="/data"
# MINIO_OPTS="--console-address :9001"
# MINIO_ROOT_USER="silo-admin"
# MINIO_ROOT_PASSWORD="replace-with-a-long-random-secret"
```

**验证点**：`systemctl status silo` 处于 `active (running)`，且 `mc admin info`（用 `mcli`）能正常返回集群信息。

## Migration Path Three: Kubernetes / Helm

Silo 自带 chart，覆盖上游 chart 的 image 值即可：

```bash
helm install minio minio/minio --namespace minio \
  --set image.repository=pgsty/silo,image.tag=RELEASE.2026-10-18T00-00-00Z \
  --set mcImage.repository=pgsty/mc,mcImage.tag=RELEASE.2026-10-18T00-00-00Z \
  --create-namespace
```

已有部署升级（`mcImage` 对已完成的安装无效，post-install job 已跑过）：

```bash
helm upgrade minio minio/minio --namespace minio \
  --set image.repository=pgsty/silo \
  --set image.tag=RELEASE.2026-10-18T00-00-00Z
```

**Helm 升级有一条硬约束**：资源身份不能变。selector、PVC、storage mount、port、secret、serviceAccount 引用都必须保持——否则升级会导致 StatefulSet 挂不上旧 PVC、数据"看起来消失"。Silo 用 `buildscripts/helm-migration-guard` 在 CI 里强制这条约束（渲染旧 chart 与新 chart 逐资源比对），机制见 [Compatibility Guard](/docs/CS/Distributed/Silo/Compatibility_Guard.md)。

**验证点**：`kubectl get pvc` 的 `STATUS` 应保持 `Bound`；若变成 `Pending`，说明 PVC 身份被改动了。

## Migration Path Four: Binary

直接换二进制最省事：

```bash
# 下载并校验（每版附带 checksum 与 SBOM）
# 放置到 /usr/bin/silo
export MINIO_ROOT_USER=admin
export MINIO_ROOT_PASSWORD=change-me-please
silo server /data{1...4} --console-address ":9001"
```

多节点分布式部署的拓扑与 MinIO 相同（`http://node{1...4}/data{1...4}`），只是二进制名换成 `silo`：

```bash
silo server http://node{1...4}/data{1...4} --console-address ":9001"
```

**注意**：S3 API 端口仍是 **9000**，控制台端口仍是 **9001**。

## Rolling Upgrade in a Distributed Cluster

分布式集群的升级顺序有讲究：

1. **先升一个节点**，观察其重新加入纠删集、开始承接读写；
2. 确认该节点 `mc admin heal` 无异常、指标无缺口；
3. **逐个升其余节点**，每次升完等该节点 heal 完成再动下一个；
4. 全员升完后，确认集群处于满纠删集状态。

Silo 提供了 `buildscripts/heal-inconsistent-versions.sh` 与 `heal-inconsistent-versions` 相关的修复流程来处理版本不一致，但**主动避免混合版本状态**比事后修复省事得多。

## Operational Notes

- **控制台**：完整管理界面已在 9001 端口恢复，用户管理 / 桶策略 / 访问控制 / 生命周期管理都可用，不必退回到纯 `mc` 命令行。
- **可观测性**：指标名仍是 `minio_*`，所以原有的 Prometheus 抓取配置、Grafana 看板、告警规则**全部不用改**——这是"协议面不动"最直接的生产收益。
- **自愈**：驱动失效后换盘即可，纠删码按对象级别校验重建，读写互不阻塞，语义与 MinIO 一致。
- **备份**：升级前对 `.minio.sys` 与桶数据做独立备份；Silo 官方也把"keep independent backups"与"test recovery"列为生产前置条件。

## Who Should Choose Silo

| 场景 | 建议 |
| :--- | :--- |
| 已在跑 MinIO 社区版，暂不能换存储 | **Silo**——改动最小、风险可控、数据原地接管 |
| 从零新建，能接受 Apache-2.0 | 评估 RustFS / SeaweedFS / Garage，许可证负担更轻 |
| 需要块 + 文件 + 对象统一底座 | Ceph RGW——不是 MinIO 的 drop-in 替代 |
| 需要厂商 SLA 与商业支持 | AIStor |
| 嵌入式产品、把对象存储作为网络服务提供 | 慎用 AGPL-3.0（Silo 与 MinIO 同许可）；自用不触发源码提供义务 |

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Compatibility Guard（兼容契约的 CI 强制）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)
- [Release Engineering（发布与制品矩阵）](/docs/CS/Distributed/Silo/Release_Engineering.md)
- [Architecture（模块身份与 replace 机制）](/docs/CS/Distributed/Silo/Architecture.md)
- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)
- [Distributed Storage（对象存储分类枢纽）](/docs/CS/Distributed/Distributed_Storage.md)

## References

1. [pgsty/silo 仓库](https://github.com/pgsty/silo)
2. [Silo 文档站（Download & Install / 迁移指南）](https://silo.pgsty.com)
3. [silo.service（systemd unit）](https://github.com/pgsty/silo/blob/main/silo.service)
4. [silo.env（环境文件模板）](https://github.com/pgsty/silo/blob/main/silo.env)
5. [helm/silo（Helm chart）](https://github.com/pgsty/silo/tree/main/helm/silo)
6. [OSCAR 文档的 Silo 迁移示例](https://docs.oscar.grycap.net/silo-usage)
