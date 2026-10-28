# Silo Release Engineering

## Introduction

2025-10 上游停止发布预构建二进制与 Docker 镜像，只留源码，官方给的说法是"用 `go install` 自己编"。对开发者无所谓，对运维是灾难：Dockerfile 里写死了 `minio/minio:RELEASE.2025-09-07T16-13-09Z`，镜像一旦被删，这个 tag 就永远拉不到。

Silo 的应对不是"发几个镜像"，而是重建一整条**供应链**：从源码 commit 到可验证制品（镜像、原生包、Helm chart），每一步都有签名、SBOM 与自动化的质量门禁。本册讲这条链是怎么搭的，以及它对使用者的实际约束。

## Why Supply Chain Is the Product

维护者把这件事讲得很直白：

> For the vast majority of users, the value of open-source software isn't just a copy of the source — supply chain stability is what matters. You need a stable artifact you can put in a Dockerfile, an Ansible playbook, or a CI/CD pipeline — not a requirement to install a Go compiler before every deployment.

这段话点出了开源交付里常被忽略的一层：**用户要的是"可放进 Dockerfile / Ansible / CI 的稳定制品"**，而不是"一份能编译的源码"。源码是原材料，制品才是产品。

Silo 的做法是"让制品随 commit 自动再生"——每一次提交都重新构建并发布对应制品，制品与源码 commit 一一对应，不存在"某个 prebuilt binary 停在半年前的某个 commit"这种悬空状态。

## Artifact Matrix

| 制品 | 形态 | 说明 |
| :--- | :--- | :--- |
| 容器镜像 | `docker.io/pgsty/silo` | 多架构 linux/amd64、linux/arm64 |
| 原生二进制 | GitHub Releases | Linux / macOS / Windows，amd64 与 arm64 |
| 系统包 | RPM / DEB / APK | 匹配上游原始包规范；亦可经 `pig` / `pigsty-infra` 仓库安装 |
| Helm chart | `helm/silo/` | K8s 部署 |
| 客户端 | `pgsty/mc`（作为 `mcli`） | 随镜像内置 |

镜像内自带客户端这一点很重要——运维排障时不必再单独拉一个 mc 容器：

```bash
docker exec silo mcli alias set local http://127.0.0.1:9000 minioadmin change-me-long-password
docker exec silo mcli mb local/demo
```

## The CI Pipeline

`.github/workflows/` 下有 7 个 workflow，各自承担一段：

| Workflow | 职责 |
| :--- | :--- |
| `go.yml` | 构建与单元测试 |
| `vulncheck.yml` | 依赖漏洞扫描 |
| `test-release.yml` | 发布制品的安装/运行验证 |
| `release.yml` | 主发布流程（打包、签名、SBOM） |
| `docker-release.yml` | 镜像构建与推送 |
| `finalize-release.yml` | 发布收尾（校验和、Release 页整理） |
| `dco.yml` | DCO 签署检查（贡献者需签署） |

`buildscripts/` 里的脚本则是流水线各环节的"工序"，其中**质量门禁类脚本**最值得注意：

| 脚本 | 门禁内容 |
| :--- | :--- |
| `verify-rebrand.sh` | 交付面必须改名、协议面不许变 |
| `verify-helm-migration.sh` | Helm 升级前后资源身份必须一致 |
| `verify-build.sh` / `verify-build-provenance.sh` | 构建产物与来源可验证 |
| `verify-healing.sh` / `verify-healing-empty-erasure-set.sh` / `verify-healing-with-root-disks.sh` | 纠删码自愈行为（含空纠删集、根盘等边界） |
| `multipart-quorum-test.sh` | multipart 操作的 quorum 语义 |
| `minio-upgrade.sh` | 从 MinIO 升级路径 |
| `heal-inconsistent-versions.sh` / `resolve-right-versions.sh` | 混合版本集群的版本一致性修复 |
| `install-mcli.sh` | 客户端安装 |
| `sign-release-rpms.sh` | RPM 签名（配合 `pgsty-rpm-signing-key.asc`） |
| `rewrite-old-new.sh` | 标识符批量重写辅助 |
| `disable-root.sh` | 构建去 root 依赖 |

**几个门禁脚本的名字本身就说明了 fork 的测试重点**：`verify-healing-empty-erasure-set`（空纠删集）、`verify-healing-with-root-disks`（根盘）——这是纠删码实现最容易出错、也最难手工构造场景的两处。还有 `heal-inconsistent-versions.sh`：集群里节点版本不一致时的自愈，这是滚动升级期的真实痛点。

## Reproducibility and Attestation

每个发布版本附带：

- **checksum**——制品哈希；
- **SPDX SBOM**——软件物料清单；
- **Sigstore 签名 manifest**——无密钥签名；
- **GitHub build attestations**——构建来源证明。

配合 `buildscripts/verify-build-provenance.sh`，构成"制品 ↔ 源码 commit"的完整证据链。用 Sigstore（而不是 GPG 私钥）是有意的：无需分发密钥，验证方只需信任公开的透明日志。

## Version Number Semantics

版本号沿用 MinIO 风格：

```text
RELEASE.YYYY-MM-DDT00-00-00Z
```

例如 `RELEASE.2026-10-18T00-00-00Z`。这个格式的好处是**排序即时间**，且与上游 MinIO 的 tag 形态一致——迁移脚本里按 tag 排序的逻辑可以直接沿用。

包版本另有一套（`20261018000000.0.0`），用于 RPM/DEB 等包管理器的版本比较。

`CHANGELOG.md` 里同时记录源码 commit 与前序版本 commit：

```markdown
## RELEASE.2026-10-18T00-00-00Z

Package version: `20261018000000.0.0`; published on 2026-10-18 from source
`0cd388c666f8211f552604ae73448a066e9c25ce`. This section covers the changes
after the public 20260916 source, `2a4d51406b7ed87af5fe6fe0f801f3290f96eb3c`.
```

**每个发布版都记录了它对应的源码 commit SHA，以及覆盖范围的起点**。这让"我跑的到底是哪个 commit"永远可回答。

## Unreleased vs Published

`CHANGELOG.md` 顶部的 Unreleased 段落是仓库的常态：

```markdown
## Unreleased

- Fix LDAP login for long normalized DNs without hiding unreadable IAM
  revocation records. ...
- Build the server and standalone debugging tools with Go 1.27.3 and refresh
  Go dependencies. Keep the published Console, mcli and silo-pkg references.
- Preserve Kafka's default broker protocol 2.1 and terminal-width behavior;
  fix legacy DARE v1 key unsealing and verify DARE v1/v2 and MinKMS TLS compatibility.
- Update bundled curl to 8.23.0 and require patched static libraries. Apply
  [Red Hat's compromised-CA mitigation](...);
  the root blocklist also rejects legitimate chains under the affected roots.

These source changes are not included in the published 20261018 artifacts.
```

最后一句是刻意写明的：**"这些源码改动不在已发布的 20261018 制品里"**。看到 `main` 分支就以为拿到了新版本，是使用 fork 时最常见的误判。

## Dependency Baseline Governance

依赖刷新是发布的固定动作，Silo 的做法是"整组对齐"而非单点升级：

```text
- 刷新 Go 运行时与模块基线：release、hotfix、goreleaser 与 old-CPU Docker 构建现在都使用 golang:1.26.4-alpine；
  go.mod 更新到 Go 1.26.4；依赖刷新覆盖 NATS、Prometheus、Azure SDK、Apache Thrift、gRPC、
  OpenTelemetry、Google API/auth、Go x/* 以及相关间接依赖。
```

"整组对齐"的收益是消除了"某个依赖单独升级、其它还在旧补丁线"的混合状态——后者在安全上等于"这批依赖的漏洞修复只生效了一半"。

值得注意的是 `old-CPU Docker 构建` 也用同一个基线：老 CPU 镜像不是为了跑 SIMD 加速，而是给没有 AVX-512 的环境提供兜底，这与 S3 Select 放弃 SIMD 路径的决定形成呼应——**兼容性是一等公民**。

## Release Cadence

约 1–2 个月一次发布。这个节奏对安全维护是关键：漏洞披露到补丁发布如果超过一个季度，实际暴露窗口就长得没意义了。

## Practical Constraints for Operators

从发布工程的角度，对使用者有三条硬约束：

1. **必须 pin 具体 tag，不能用 `latest`**。`latest` 在无人维护的 fork 里意味着"某个不确定时间的 commit"，与"供应链稳定"的目标背道而驰。
2. **每个版本都要读 release notes**。Silo 明确采用**下游升级模型**——不假设补丁自动到位。反过来，官方发布说明里会写"read the release notes before upgrading, especially the removal of strict multipart listing, coordinated server upgrades, and measured performance costs"，即**破坏性变更与性能成本都会被显式记录**。
3. **保留回滚路径**。每次升级前确认上一版本可回退，尤其是分布式集群——节点版本不一致的自愈逻辑虽有 `heal-inconsistent-versions.sh` 兜底，但主动避免混合版本更省事。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Architecture（模块身份与 replace 机制）](/docs/CS/Distributed/Silo/Architecture.md)
- [Compatibility Guard（CI 门禁的协议面守卫）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)
- [Security Advisories（公告账本与 backport 机制）](/docs/CS/Distributed/Silo/Security_Advisories.md)
- [Deployment and Migration（升级与迁移操作手册）](/docs/CS/Distributed/Silo/Deployment_and_Migration.md)

## References

1. [.github/workflows（7 个 CI workflow）](https://github.com/pgsty/silo/tree/main/.github/workflows)
2. [buildscripts（构建与门禁脚本）](https://github.com/pgsty/silo/tree/main/buildscripts)
3. [CHANGELOG.md（发布记录与 Unreleased 差异）](https://github.com/pgsty/silo/blob/main/CHANGELOG.md)
4. [pgsty/silo Releases](https://github.com/pgsty/silo/releases)
5. [Silo 20261018 发布说明](https://silo.pgsty.com/blog/release/silo-20261018/)
6. [MinIO Is Dead, Long Live MinIO（重建供应链的起因）](https://silo.pigsty.cc/blog/post/minio-resurrect/)
