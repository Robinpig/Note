# Silo

## Introduction

2026 年 4 月，MinIO 的仓库归档变成只读，README 顶上一行 "THIS REPOSITORY IS NO LONGER MAINTAINED"。这个项目服务了十一年，是被部署最多的开源对象存储之一；它死的方式很典型——不是代码不行，是公司决定把它变成付费产品。2025 年 5 月完整管理控制台从社区版移除，10 月停止发布二进制与 Docker 镜像，12 月进入维护模式，次年 2 月宣告不再维护，4 月归档，9 月官方镜像 `minio/minio` 与 `minio/mc` 从 Docker Hub 删除。

留下的是一片沉默：几十万个仍在跑的集群，环境变量写的是 `MINIO_*`，Prometheus 抓的是 `minio_*` 指标，磁盘上是 `xl.meta` 格式，桶里是生产数据。它们跑在**永不再补丁**的软件上——`CVE-2026-39414`（S3 Select 内存耗尽）这类高危漏洞对所有社区版本都未修复。

Silo 就是在这片沉默里出现的。**PGSTY Silo**（`pgsty/silo`）由 Pigsty 的作者冯若航维护，是 MinIO 的 AGPL-3.0 社区 fork。它的价值不在于"又一个 S3 实现"，而在于**让已冻结的那套 MinIO 继续能跑**——把删掉的控制台找回来、把停发的二进制重新发出来、把未修的 CVE 反向移植回来。

本专题由六册组成，从"这个 fork 到底是什么"一路走到"它的源码里怎么实现"：

- [Architecture](/docs/CS/Distributed/Silo/Architecture.md)——fork 在源码层面到底改了什么？模块路径、replace 指令、目录结构、构建基线。
- [Compatibility Guard](/docs/CS/Distributed/Silo/Compatibility_Guard.md)——"改名不改协议"如何被 CI 强制执行而非口头承诺。
- [Security Advisories](/docs/CS/Distributed/Silo/Security_Advisories.md)——安全公告账本怎么运作，哪些 CVE 被 backport、怎么验证。
- [Storage Guard](/docs/CS/Distributed/Silo/Storage_Guard.md)——节点间路径穿越漏洞的根因与守卫实现。
- [S3 Select Defense](/docs/CS/Distributed/Silo/S3_Select_Defense.md)——有界读取与 SIMD 快路径的冲突，以及两轮修复的取舍。
- [Release Engineering](/docs/CS/Distributed/Silo/Release_Engineering.md)——供应链怎么重建：制品矩阵、CI 门禁、签名与 SBOM。
- [Deployment and Migration](/docs/CS/Distributed/Silo/Deployment_and_Migration.md)——四条迁移路径的具体步骤与验证点。

## What Actually Happened

上游的收尾是分阶段的，每一步都在削减社区版的价值：

- **2025-05** 完整管理控制台被替换为裸对象浏览器。用户管理、桶策略、访问控制、生命周期管理全部搬到了 AIStor 付费墙之后。
- **2025-10** 停止发布预构建二进制与 Docker 镜像，只留源码——"用 `go install` 自己编"。对开发者无所谓，对运维是 Dockerfile 里的 tag 永久失效。
- **2025-12** 仓库进入 Maintenance Mode，社区开始寻找出路。
- **2026-02-12** README 改为 "NO LONGER MAINTAINED"。
- **2026-04-25** 仓库归档只读。
- **2026-09-11** `minio/minio` 与 `minio/mc` 从 Docker Hub 删除，匿名拉取返回 401/404。

值得强调一个容易被误读的事实：**社区版服务器代码自 2021-05 起就是 GNU AGPLv3，从未"重新许可为专有"**。代码一直公开、一直可 fork。真正终止的是**维护与分发**，不是著作权。这正是 Silo 能够存在、且不构成侵权争议的法律基础——AGPL 恰恰是 MinIO 自己选的许可证。

## The Fork's Three Moves

Silo 的工作可以归为三件事，每一件都对应上游失去的一样东西。

**找回控制台。** 上游的"阉割"只是把 `minio/console` 依赖换成了精简版。而 Silo 在 `go.mod` 里做的是：

```go
replace github.com/minio/console => github.com/pgsty/silo-console v0.0.0-20261017112417-ef2dd2c41d21
replace github.com/minio/mc => github.com/pgsty/mc v0.0.0-20261017101407-fa3b8bf72458
```

社区流传的说法是"revert 一下 console 子模块"，但从代码看，实际做法是**替换成一个持续维护的 fork**——差别很实际：revert 只能钉死一个历史提交，replace 才能继续演进、加双语 UI、跟住后续修复。细节见 [Compatibility Guard](/docs/CS/Distributed/Silo/Compatibility_Guard.md)。

**重建分发。** 镜像、RPM/DEB/APK、Helm chart、跨平台二进制，每版附带 checksum、SPDX SBOM 与 Sigstore 签名。维护者的判断很清醒：用户需要的是"能放进 Dockerfile 和 CI 的稳定制品"，而不是"一份能编译的源码"。

**backport 安全修复。** 这是与"永不再补丁"最本质的区别。Silo 维护一份安全公告账本，把上游归档后披露、影响社区版的 CVE 逐条反向移植，并保留可审计的证据链——同一个 commit 在上游与 fork 里 SHA 相同，回归测试位置精确到文件与行号。

## The Interesting Part: How It Holds Its Shape

多数 fork 死于同一个原因：改名改到一半，协议面被侵蚀了。指标名改了，Prometheus 告警全断；`x-minio-*` 头改成 `x-silo-*`，第三方客户端全挂；`.minio.sys` 目录改名，旧数据盘读不出来。

Silo 的解法是**把这条原则编译成 CI 门禁**。`buildscripts/rebrand-guard/` 用 Go AST 解析 + 正则扫描全仓，抽出 428 个环境变量、225 条路由、119 个 import、86 个 HTTP 头、59 个策略 ARN、16 个存储标记、27 个指标名，与 `compat-baseline.json` 逐项比对，偏离即构建失败。基线里还有一份 181 条的 **brand allowlist**——规定哪些位置的 `minio` 字样是接口名而非品牌残留，必须豁免。没有这份 allowlist，"故意保留"与"无意漏改"根本无法区分，守卫要么噪声淹没要么被整体关掉。

还有一条边界同样值得学：**守卫锁的是标识符的存在性，不是行为等价性**。它能把"意外的破坏"变成"显式的、可 review 的决定"，但保证不了"改得对"——那属于协议变更，得靠 release notes 披露。这是诚实的边界陈述。

## Two Case Studies in Security Engineering

Silo 的安全修复里有两例特别值得读，因为它们展示的不是"怎么打补丁"，而是**怎么判断该修什么、不该修什么**。

**CVE-2026-39414**（S3 Select 内存耗尽）的修复分两轮。第一轮复用既有的 1 MiB 记录上限，干净利落。第二轮顺着调用链再走一遍，发现支持 SIMD 的 CPU 上 JSON Lines 会走 `simdjson` 快路径、**完全绕过有界读取器**——"测试在快路径机器上跑绿，不能证明慢路径机器安全"。最终方案不是加一层 wrapper（通用 wrapper 无法同时保住"已完成的记录"与"下一条记录的有界性"），而是**暂时放弃 SIMD 路径**，并规定未来任何要恢复的快路径必须自己实现同等上限、通过与 CPU 无关的同一套回归测试。代价是 JSON Lines 性能下降，官方照实写明"没有量化 benchmark"。

**CVE-2026-42600**（节点间路径穿越）的修复方式更反直觉：Silo 新增了上游根本没有的 `cmd/storage-rest-server-guard.go`，用 `guardedStorage` 包装器在 `storageRESTServer.getStorage()` 这一处分发点拦截所有 storage-REST 与 grid handler。注释里解释了为什么不能逐个 handler 打补丁：全局 HTTP 中间件只校验 `r.URL.Path` 与 `r.Form`，而 **`r.Form` 永远不会从请求体填充**——路径装在 msgpack body 或 grid RPC 帧里，直接绕过中间件抵达 `xlStorage`。守卫的判定规则细到区分空白符与反斜杠在 Windows 与 Unix 上的语义差异，因为"统一规则"会导致"单节点接受、分布式集群拒绝"。

## Where It Stands

截至 2026-10-25，Silo 最新发布为 `RELEASE.2026-10-18T00-00-00Z`（Go 1.27.2、Console v2.4.2、silo-pkg v3.14.3、mcli 20261018），发布节奏约 1–2 个月一次。RAGFlow、Dokploy、Grafana Loki 的 Helm chart 与 nixpkgs 都已切换；Pigsty v4.5 的对象存储模块默认只部署 Silo（`minio_type` 仅接受 `silo`）。

风险也必须说清楚：**仍是 AGPL-3.0**（内部自用不触发源码提供义务，嵌入产品作网络服务则需提供对应源码）；**单一组织维护、无基金会治理**，长期可持续性仍然系于维护者一人——这与当年 MinIO "单一公司"结构是同源的风险，只是当下代码公开、可 fork，风险有底。

## Links

- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)
- [Distributed Storage（对象存储分类枢纽）](/docs/CS/Distributed/Distributed_Storage.md)
- [Ceph（RGW 对照）](/docs/CS/Distributed/Ceph.md)
- [Architecture（fork 基线与模块替换）](/docs/CS/Distributed/Silo/Architecture.md)
- [Compatibility Guard（改名不改协议的守卫体系）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)
- [Security Advisories（安全公告账本与 backport 机制）](/docs/CS/Distributed/Silo/Security_Advisories.md)

## References

1. [PGSTY Silo GitHub 仓库](https://github.com/pgsty/silo)
2. [PGSTY Silo 文档站](https://silo.pigsty.com)
3. [MinIO Is Dead, Long Live MinIO（fork 起因与三项恢复）](https://silo.pigsty.cc/blog/post/minio-resurrect/)
4. [MinIO GitHub（社区版已归档，只读）](https://github.com/minio/minio)
5. [Silo 安全公告账本](https://silo.pgsty.com/about/security-advisories/)
6. [CVE-2026-39414 修复分析](https://silo.pigsty.cc/blog/security/cve-2026-39414)
