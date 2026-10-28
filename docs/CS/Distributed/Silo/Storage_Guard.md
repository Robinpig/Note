# Silo Storage Guard

## Introduction

MinIO 的节点间通信有三条通道：HTTP 客户端面、peer-S3（节点间 S3 语义 RPC）、以及 **storage-REST / grid**（节点间裸存储访问）。最后这一条是整个系统里信任边界最模糊的地方——因为它传的不是"对象"，而是**路径**。

Silo 为修复 CVE-2026-42600（internode 路径穿越）引入了一个上游 MinIO 没有的文件：`cmd/storage-rest-server-guard.go`。本册讲清三件事：

1. 为什么路径参数能绕过常规 HTTP 校验；
2. 为什么守卫选在 `getStorage()` 这一层，而不是每个 handler；
3. 守卫的判定规则为什么这么"较真"（连空白符与反斜杠都要区分平台）。

## The Three Inter-node Channels

| 通道 | 载体 | 传什么 | 信任假设 |
| :--- | :--- | :--- | :--- |
| HTTP 客户端面 | S3 REST over TLS | 对象键 | 外部不可信，靠签名认证 |
| peer-S3 | 节点间 RPC | S3 语义请求 | 集群内节点互信，但有 IAM 约束 |
| storage-REST / grid | REST + 长连 websocket | **卷名 + 文件路径** | 曾经"内网即可信"，实际不安全 |

storage-REST 的存在是为了让纠删码层不必理解 S3 语义就能读写盘上的对象分片。典型调用是"在卷 `X` 上读路径 `a/b/c`"。只要路径能逃出卷目录，就是跨卷读写——**存储隔离被击穿**。

## Why the Global Middleware Does Not Cover It

Silo 在守卫文件里写下了这段判断（注释原文）：

```go
// Why here and not in each handler: the global HTTP middleware validates only
// r.URL.Path and r.Form (query arguments), and r.Form is never populated from
// a request body. Paths carried in a msgpack body, or in a grid RPC frame on
// the long-lived /minio/grid/v1 websocket, therefore reach xlStorage
// unvalidated.
```

拆开看：

- MinIO 的全局 HTTP 中间件做路径校验，依据是 `r.URL.Path` 与 `r.Form`（查询参数）。
- **但 `r.Form` 永远不会从请求体填充**——这是 Go `net/http` 的既定行为，表单解析只对 `application/x-www-form-urlencoded` 的 body 生效，且 `ParseForm` 不读 body。
- storage-REST 的路径是装在 **msgpack 请求体**里的，或在 **grid RPC 帧**里（`/minio/grid/v1` 上的长连 websocket）。两者都不经过 `r.Form`。
- 于是这些路径**未经验证直达 `xlStorage`**。

这就是 CVE-2026-42600 的根因：不是某个 handler 写错了，而是**校验层与数据层的错配**——校验在 HTTP 入口，危险数据在 body 里。

## The Wrapper: One Call Site, Full Coverage

守卫的类型定义很朴素：

```go
type guardedStorage struct {
	StorageAPI
}
```

嵌入 `StorageAPI` 接口后，只需实现一个方法就能拦截所有路径参数：

```go
func (g *guardedStorage) ReadFile(ctx context.Context, volume string, path string, offset int64) (io.ReadCloser, error) {
	// ... 校验 path ...
	return g.StorageAPI.ReadFile(ctx, volume, path, offset)
}
```

安装点只有一处：

```go
func (s *storageRESTServer) getStorage() StorageAPI {
	return &guardedStorage{s.storageAPI}
}
```

选这一层的四条理由，注释里列得清清楚楚：

1. **全覆盖**：所有 storage-REST 与 grid handler 都通过 `getStorage()` 拿 `StorageAPI`，包一处即覆盖全部。
2. **看得见嵌套字段**：入口处能看到逐 handler 检查容易漏掉的嵌套 struct 字段。
3. **不会失配**：随 handler 增加，守卫不会漂移出同步——这是"逐个 handler 打补丁"最常见的失效方式。
4. **不重复实现**：守卫逻辑单点存在，可单测。

上游风格是"在每个 handler 里校验参数"；Silo 选择"在分发点包一层"。这是**防守纵深**思路：把安全属性放在数据必经之路，而不是依赖每个调用方的自觉。

## Path Validation Rules

守卫的判定函数被命名为 `isVolumeRootAlias`，它要回答的是"**这个路径是否指向卷根本身，或会解析到卷根之外**"。注释里的边界讨论非常细致：

```go
// isVolumeRootAlias reports whether p addresses the volume directory itself
// rather than something inside it, i.e. whether pathJoin(volumeDir, p)
// collapses back to volumeDir. That happens only for the empty string and for
// strings made up entirely of separators.
```

即：只有**空字符串**与**全由分隔符组成**的字符串会被判为卷根别名。其它一律视为卷内路径。

### Whitespace Is Not a Separator

```go
// Whitespace must NOT be treated as a separator here, even though
// hasBadPathComponent trims it when comparing a segment against "."/"..".
// path.Clean does not touch spaces, so pathJoin(volumeDir, "  ") is
// "volumeDir/  " - a real directory named two spaces, not the volume root. A
// whitespace-only object key is legal in S3 (IsValidObjectName accepts it) and
// is committed through RenameData on the PutObject path, so rejecting it here
// would fail those writes on every remote drive at once. See
// TestGuardAcceptsEveryLegalObjectName.
```

这条推理链完整解释了"为什么不能顺手把空白当分隔符"：

- `path.Clean` **不处理空格**，所以 `pathJoin(volumeDir, "  ")` 得到 `volumeDir/  `——那是一个名叫"两个空格"的真实目录，不是卷根。
- S3 规范**允许纯空白对象键**（`IsValidObjectName` 接受它），且这类键在 `PutObject` 路径上会经 `RenameData` 落盘。
- 如果守卫把空白当分隔符拒绝，**每次远端盘写入都会失败**——一个安全守卫变成了数据面事故。
- 回归测试因此叫 `TestGuardAcceptsEveryLegalObjectName`：**守卫的测试目标是"不误伤任何合法对象名"**。

这是安全补丁里极少见的一类测试断言：不是"挡住攻击"，而是"证明没挡住合法流量"。

### Platform-Split Rules

```go
// Three characters collapse a component on Windows but not on Unix, so the
// rule is platform-split and exercised from either platform through
// isVolumeRootAliasOn:
//
//   - Backslash is a separator on Windows only. path.Clean never treats it as
//     one, so on Unix "\\" names an ordinary file and is a legal S3 object key;
//     refusing it there would make a distributed cluster reject a write that a
//     single-node server accepts.
//
//   - Space and period are stripped from the end of a path component by the
//     Win32 normalisation layer. A component made only of those characters
```

Windows 的 `Win32` 规范化层会剥掉路径分量末尾的空格与点，所以 `foo.` 与 `foo ` 在 Windows 上会塌陷成 `foo`；而 `path.Clean`（Go 的纯逻辑清理）不认这套规则。**如果守卫用一套跨平台统一规则，就会出现"单节点接受、分布式集群拒绝"的不一致**——而分布式部署恰恰是这套守卫存在的意义。

所以规则按平台拆开实现（`isVolumeRootAliasOn`），并从两个平台各自触发测试。

## Scope Discipline

守卫的作用域被刻意写得很窄，注释是理解设计意图的关键：

```go
// Scope, deliberately narrow:
//
//   - Only *path* arguments are checked here. Volume arguments are validated
//     at the sink by xlStorage.getVolDir, which additionally covers callers
//     that bypass this wrapper entirely (the peer-S3 bucket RPCs). Do not
//     conclude from the absence of a volume check here that volumes are inert.
//
//   - Local callers - the erasure layer talking to its own drives - are not
//     wrapped. Their object names already passed IsValidObjectName at the S3
//     boundary, so wrapping them would add cost and regression risk without
//     adding a control.
```

两条边界：

1. **只查 path，不查 volume**。卷名在数据汇（sink）处的 `xlStorage.getVolDir` 里校验，那里还能覆盖绕过本包装器的调用者（比如 peer-S3 的 bucket RPC）。注释特意提醒：**不要因为这里没查 volume 就推断 volume 是惰性的**——这正是"防守纵深"的分层。
2. **本地调用者不包装**。纠删码层访问自己的盘时，对象名已在 S3 边界过了 `IsValidObjectName`；再包一层只增加成本与回归风险，不增加控制力。

**"不增加控制力的包装一律不做"**——这是安全工程里少见但重要的克制。

## CVE-2026-42600: Removing the Legacy Path

与守卫并行，Silo 对 CVE-2026-42600 还做了一件事：**直接移除废弃的 `ReadMultiple` storage-REST API**，关掉 `/rmpl` 暴露的旧节点间文件读取路径。

在当前 `main` 分支的 `cmd/storage-rest-server.go` 与 `cmd/storage-rest-common.go` 中已检索不到 `ReadMultiple` 的处理分支。移除而非加固的理由是可推断的：`ReadMultiple` 是旧设计遗留，功能上已被更新的路径覆盖，留着只是攻击面。

回归测试：

- `cmd/storage-rest-traversal_test.go`——路径穿越用例；
- `cmd/storage-rest-server-guard_test.go`——守卫行为用例（含 `TestGuardAcceptsEveryLegalObjectName` 这类"不误伤"断言）。

## Grid Route Identity

节点间 grid 通道的路由也被兼容基线冻结——`compat-baseline.json` 的 `grid_routes` 只有三条：

```json
  "grid_routes": [
    "/",
    "/minio/grid/",
    "/minio/grid/lock/"
  ]
```

这三条是从 `internal/grid/manager.go` 单独收集的（守卫工具里对这一个文件做了特殊处理），说明 grid 的对外路径面极小且稳定，与客户端面的 225 条路由形成鲜明对比——**节点间接口面越窄，信任边界越容易守**。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Security Advisories（公告账本与 CVE 修复）](/docs/CS/Distributed/Silo/Security_Advisories.md)
- [Architecture（fork 基线与 replace 机制）](/docs/CS/Distributed/Silo/Architecture.md)
- [Compatibility Guard（协议标识符冻结）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)
- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)

## References

1. [cmd/storage-rest-server-guard.go（节点间路径守卫）](https://github.com/pgsty/silo/blob/main/cmd/storage-rest-server-guard.go)
2. [cmd/storage-rest-traversal_test.go（路径穿越回归测试）](https://github.com/pgsty/silo/blob/main/cmd/storage-rest-traversal_test.go)
3. [cmd/storage-rest-server-guard_test.go（守卫行为测试）](https://github.com/pgsty/silo/blob/main/cmd/storage-rest-server-guard_test.go)
4. [Silo 20260618 发布说明（CVE-2026-42600）](https://silo.pgsty.com/zh/blog/release/20260618)
5. [Silo 安全公告账本](https://silo.pgsty.com/about/security-advisories/)
