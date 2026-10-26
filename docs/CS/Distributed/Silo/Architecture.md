# Silo Architecture

## Introduction

Silo 不是"重写一个 S3 存储"，而是**在 MinIO 服务器源码上做外科手术式维护**。要理解它，必须先分清三条边界：

| 边界 | 内容 | 是否动 |
| :--- | :--- | :--- |
| **协议面** | S3 API、`MINIO_*` 环境变量、`minio_*` 指标、`x-minio-*` 头、`/minio/*` 路由、`.minio.sys` 磁盘布局 | 一律不动 |
| **交付面** | 可执行名、包名、systemd 服务名、镜像名、Helm chart | 全部改名 |
| **维护面** | CVE 修复、构建流水线、发布工程、兼容守卫 | 全新建设 |

本页只回答一个问题：**这三条边界在源码里究竟是怎么落地的**。协议面与交付面的运行时行为属于 [Compatibility Guard](/docs/CS/Distributed/Silo/Compatibility_Guard.md)，维护面的发布工程属于 [Release Engineering](/docs/CS/Distributed/Silo/Release_Engineering.md)，安全修复的落点属于 [Security Advisories](/docs/CS/Distributed/Silo/Security_Advisories.md)。

## Fork Baseline and Module Identity

Silo 的 `go.mod` 开头是这样的：

```go
module github.com/minio/minio

go 1.27.3
```

**模块路径刻意保持上游不变**——这不是省事，而是硬约束。Go 的 module path 决定 import 前缀；`minio/pkg`、`minio/console`、`minio/mc` 这些共享库互相之间的 import 都带着 `github.com/minio/...` 前缀，一旦改掉模块路径，与上游共享库的 import 关系就全部要改写。更关键的是，这个值被**写进了兼容基线**（`compat-baseline.json` 的 `module_path` 字段），任何改动都会被 `rebrand-guard` 判为失败。

入口 `main.go` 同样原封不动：

```go
package main // import "github.com/minio/minio"

import (
	"os"

	// MUST be first import.
	_ "github.com/minio/minio/internal/init"

	minio "github.com/minio/minio/cmd"
)

func main() {
	minio.Main(os.Args)
}
```

包名还是 `main`，导入别名还是 `minio`，调用的入口函数还是 `cmd.Main`。换句话说，**Silo 在类型层面完全就是 MinIO**，可执行文件名换成 `silo` 之后，运行时行为的一致性才有保证。

## The Replace Mechanism

Silo 恢复上游删掉的能力，用的不是"把上游文件拷回来"，而是 Go 的**依赖级替换**：

```go
// Console and MC retain their historical module paths for best-effort upstream
// compatibility. Pin the maintained PGSTY implementations used by SILO.
replace github.com/minio/console => github.com/pgsty/silo-console v0.0.0-20261017112417-ef2dd2c41d21

replace github.com/minio/mc => github.com/pgsty/mc v0.0.0-20261017101407-fa3b8bf72458

// v22.7.0 does not compile on NetBSD because its unix implementation uses
// CLOCK_MONOTONIC, which is unavailable there. Keep the last portable release
// until go-systemd ships the upstream fix.
replace github.com/coreos/go-systemd/v22 => github.com/coreos/go-systemd/v22 v22.6.0
```

三条 replace 各有分工：

- **`minio/console` → `pgsty/silo-console`**：这是"找回完整管理控制台"的真正机制。上游在 2025-05 把控制台换成精简版后，社区流传的说法是"把 `minio/console` 子模块 revert 回移除前的版本"；但从 `go.mod` 看，实际做法是**替换成一个持续维护的 fork**。两者的差别很实际：revert 只能钉死一个历史提交，拿不到后续修复，也加不进双语 UI；replace 到自维护分支则可以继续演进。
- **`minio/mc` → `pgsty/mc`**：客户端同理。运行时的 `mcli` 就是这个被替换的模块。
- **`coreos/go-systemd/v22` 降级到 v22.6.0**：与品牌无关，纯编译兼容性——v22.7.0 的 unix 实现用了 `CLOCK_MONOTONIC`，在 NetBSD 上不可用，注释写明"等 go-systemd 上游修复前先钉在最后可移植版本"。

共享库的分工则更微妙：

```go
	github.com/pgsty/silo-pkg/v3 v3.14.3
	...
	// Legacy minio/colorjson and minio/dperf code still imports pkg/console.
	// SILO source imports github.com/pgsty/silo-pkg/v3 directly instead.
	github.com/minio/pkg/v3 v3.11.0 // indirect
```

Silo 自己的代码直接 import `github.com/pgsty/silo-pkg/v3`（fork 出来的共享库），但 `minio/pkg/v3` 仍以 indirect 形式留在依赖图里——因为 `minio/colorjson` 和 `minio/dperf` 这两个上游库还在 import `pkg/console`，而那两个库又还是上游版本。源码里能直接看到这种"半迁移"状态，例如 `internal/config/identity/openid/jwt.go`：

```go
	xnet "github.com/pgsty/silo-pkg/v3/net"
	"github.com/pgsty/silo-pkg/v3/policy"
```

而同一文件里 `github.com/minio/minio/internal/arn`、`internal/auth` 仍是上游路径。**同一个文件里两种 import 前缀并存**，正是"fork 处于过渡态"最直白的证据。

## Repository Layout

仓库约 1258 个文件，目录职责与上游几乎一一对应，多出来的部分集中在三处：

| 路径 | 职责 | 与上游关系 |
| :--- | :--- | :--- |
| `cmd/` | HTTP handlers、S3 语义、IAM、站点复制、网关等 | 沿用上游，叠加 Silo 修复 |
| `internal/` | `s3select/`、`grid/`、`config/identity/`、`jwt/`、`hash/` 等 | 沿用上游，含 Silo 新增文件 |
| `docs/` | 上游文档目录（`erasure/`、`sts/`、`iam/`、`select/`…） | 基本原样 |
| `buildscripts/` | 打包、校验、守卫脚本 | **Silo 大幅扩展** |
| `helm/silo/` | 自有 Helm chart（替代上游 `minio/minio` chart） | **新增** |
| `.github/workflows/` | 7 个 workflow（dco / go / vulncheck / release / test-release / docker-release / finalize-release） | **新增** |
| `silo.service`、`silo.env`、`silo.sysusers` | systemd 交付面 | **新增** |
| `buildscripts/rebrand-guard/`、`buildscripts/helm-migration-guard/` | 兼容守卫 | **新增** |
| `cmd/storage-rest-server-guard.go` | 节点间路径守卫 | **新增** |

`internal/` 下值得单独指出的新增文件是 `cmd/storage-rest-server-guard.go`——上游 MinIO 没有这个文件，它是 Silo 为修复节点间路径穿越而引入的独立守卫，机制见 [Storage Guard](/docs/CS/Distributed/Silo/Storage_Guard.md)。

## Build Baseline

- `go.mod` 声明 `go 1.27.3`（main 分支当前值）。
- 已发布的 `RELEASE.2026-10-18T00-00-00Z` 制品用 **Go 1.27.2** 构建。
- `CHANGELOG.md` 的 Unreleased 段写明："Build the server and standalone debugging tools with Go 1.27.3… These source changes are not included in the published 20261018 artifacts."

也就是说 **main 分支领先于最新发布版一个工具链版本**，这是"源码仓库"与"发布制品"两条轨道的正常状态，不应把 main 的数字直接当成线上版本号。

## A Source Reading Order

想把 Silo 当教材读，下面这个顺序最短路径覆盖了 fork 的全部自研面：

1. `go.mod`——看三条 replace，理解"依赖替换"而非"文件拷贝"。
2. `buildscripts/rebrand-guard/main.go` + `compat-baseline.json`——看"改名不改协议"如何被机器强制。
3. `cmd/storage-rest-server-guard.go`——看安全修复如何选对拦截层（注释里写清了为什么选在这一层）。
4. `internal/s3select/json/preader.go` 与 `internal/s3select/simdj/reader.go`——看有界读取与 SIMD 快路径的冲突及取舍。
5. `internal/config/identity/openid/jwt.go`——看 OIDC 验证路径如何被收紧到 JWKS-only。
6. `buildscripts/helm-migration-guard/main.go`——看"升级不能改资源身份"这条约束如何落地。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Compatibility Guard（改名不改协议的守卫体系）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)
- [Security Advisories（安全公告账本与 backport 机制）](/docs/CS/Distributed/Silo/Security_Advisories.md)
- [Release Engineering（构建与发布工程）](/docs/CS/Distributed/Silo/Release_Engineering.md)
- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)

## References

1. [pgsty/silo 仓库](https://github.com/pgsty/silo)
2. [go.mod（module path 与 replace 指令）](https://github.com/pgsty/silo/blob/main/go.mod)
3. [main.go（入口与模块身份）](https://github.com/pgsty/silo/blob/main/main.go)
4. [CHANGELOG.md（发布与 Unreleased 差异）](https://github.com/pgsty/silo/blob/main/CHANGELOG.md)
5. [Silo 文档站](https://silo.pgsty.com)
