# Silo Security Advisories

## Introduction

MinIO 归档后，社区版披露的安全问题不会再有上游补丁。Silo 接管的正是这部分工作，但它的做法不是"顺手修几个 bug"，而是建立了一套**可审计的公告账本（security advisory ledger）**：每个漏洞有编号、有上游来源、有修复 commit、有受影响版本范围、有发布位置。

理解 Silo 的安全模型，需要先分清两个正交的维度：

- **漏洞从哪来**——继承自上游（upstream inherited）还是 fork 特有（fork-specific）；
- **修复落在哪**——代码修复（code fix）还是仅靠发布工程兜底（release-only）。

Silo 的 `SECURITY.md` 明确划了界：*"Upstream MinIO security contacts do not handle Silo-specific fixes or release notes."* 上游的安全联络渠道不接 Silo 的活儿——这不是不客气，而是事实：代码已经 fork 出去，漏洞不再在上游的修复范围里。

## The Advisory Ledger

公告账本托管在 <https://silo.pgsty.com/about/security-advisories/>，仓库里的 `SECURITY.md` 是它的索引与规则说明。账本里用 `SN-YYYY-NNN` 编号（Silo Notice），与 CVE 编号并行——一个 CVE 可能对应多个 SN（同一漏洞在不同组件上的多次修复），一个 SN 也可能涵盖多个 CVE。

`SECURITY.md` 里对"继承型修复"的记录方式很讲究，它把**同源 commit 的两个 SHA 并列写出来**：

```markdown
- [CVE-2025-62506](https://github.com/advisories/GHSA-jjjj-jwhf-8rgr):
  upstream [PR #21642](https://github.com/minio/minio/pull/21642) merged as
  [`minio/minio@c1a49490`](https://github.com/minio/minio/commit/c1a49490c78e9c3ebcad86ba0662319138ace190),
  inherited unchanged as
  [`pgsty/silo@c1a49490`](https://github.com/pgsty/silo/commit/c1a49490c78e9c3ebcad86ba0662319138ace190),
  and is present in every Silo community release beginning with
  [`RELEASE.2025-12-03T12-00-00Z`](...).
```

读法：同一个 commit 对象 `c1a49490` 在上游与 fork 里 SHA 相同（fork 保留了原始 commit object 与 SHA），因此可以逐字证明"这段修复原样继承、未被改写"。它还给出了**最早受影响的发布版**（`RELEASE.2025-12-03T12-00-00Z`）与**回归测试位置**：

```markdown
  The inherited [service-account](.../cmd/admin-handlers-users_test.go#L211-L212)
  and [STS](.../cmd/sts-handlers_test.go#L45-L46)
  regression groups remain part of `go test ./cmd`;
```

这种写法把"声称已修"变成"可验证已修"——给出测试文件与行号，读者能自己去跑。

## Backported CVE Ledger

下面是经公告账本与 release notes 交叉确认的核心条目。**"修复版本"列指包含完整修复的 Silo 发布版**。

| CVE | 类别 | 问题 | 修复版本 |
| :--- | :--- | :--- | :--- |
| CVE-2025-62506 | 继承 | 受限 session policy 可派生无限制子账号 | 早于 `RELEASE.2025-12-03T12-00-00Z` |
| CVE-2026-33322 | 继承 | OIDC STS JWT 算法混淆（HS256/384/512 可绕过 JWKS） | 见 release notes |
| CVE-2026-33419 | 继承 | LDAP STS 用户名枚举；限流与源 IP 记账缺陷 | 多轮 follow-up |
| CVE-2026-34204 | 继承 | 不可信 `X-Minio-Replication-*` 头被写入复制元数据 | 见 release notes |
| CVE-2026-39414 | 继承 | S3 Select 超大 CSV / JSON 记录缓冲导致内存耗尽 | `RELEASE.2026-04-17` 初修，`RELEASE.2026-06-18` 完整 |
| CVE-2026-40344 | fork | Snowball auto-extract 的 unsigned-trailer 上传跳过认证 | 见 release notes |
| CVE-2026-41145 | fork | unsigned-trailer 流式 `PUT` / `UploadPart` 跳过查询串签名校验 | 见 release notes |
| CVE-2026-42600 | fork | internode `ReadMultiple` 路径穿越（`/rmpl`） | 见 release notes |
| SN-2026-002 | fork | internode storage-REST 与 grid 载荷未收敛 | 见账本 |
| SN-2026-015 / 016 | fork | Object Lock 保留策略绕过 | `RELEASE.2026-10-18` |
| CVE-2026-34986 | 依赖 | `go-jose` JWT/JOSE 依赖链 | 随版本刷新 |
| CVE-2026-39883 | 依赖 | OpenTelemetry 依赖栈 PATH 劫持风险 | 随版本刷新 |
| CVE-2026-32952 | 依赖 | `Azure/go-ntlmssp` v0.1.0 畸形 NTLM challenge 触发 panic | 升 v0.1.1 |
| CVE-2026-41602 | 依赖 | `apache/thrift` v0.22.0 `TFramedTransport` 实现 | 升 v0.23.0 |
| CVE-2026-27889 等 | 依赖 | `nats-server/v2` v2.11.1 补丁线 | 升 v2.11.15 |
| CVE-2026-42154 等 | 依赖 | `prometheus` v0.310.0 补丁线 | 升 v0.311.3 |

> "见 release notes"的条目表示修复随某版本发布，具体版本以 <https://silo.pgsty.com/about/security-advisories/> 账本为准。Silo 采用**下游升级（downstream upgrade）**模型——每个发布版都当作一次需要读 release notes 的升级，不存在"补丁自动到位"的假设。

## The Two-Round Fix Pattern: CVE-2026-39414

这个 CVE 值得单独拆开讲，因为它是理解 Silo 修复风格的最好样本——**两轮修复、两次自我审查**，且第二轮推翻了自己第一轮的一个隐含假设。

### Threat Model

攻击者提交或查询一个包含**超长单条记录**的对象。读取器为等待记录分隔符会持续缓冲，造成内存与 CPU 拒绝服务。更微妙的是：同一份输入在不同 CPU 上会走**不同实现**。

### Round One: Reuse the Existing Invariant

第一轮修复没有发明新配置项，而是**复用既有的 `maxCharsPerRecord = 1 MiB` 规则**：CSV splitter 与 line-delimited JSON 在超限时提前拒绝，不再继续缓冲或解析；保留最早发生的 splitter 错误而不是被部分解码覆盖；错误码映射为 `OverMaxRecordSize` 而不是塌缩成通用 `InternalError`。

这是一次**有意的兼容性收缩**：以前能接受 > 1 MiB 单行的客户端，现在必须自行切分。

### Round Two: The Hardware-Dependent Bypass

顺着调用链再走一遍，暴露出这样一条路径：

```
JSON Lines -> simdj.NewReader -> simdjson.ParseNDStream
```

当 `simdjson.SupportedCPU()` 返回 true 时，**JSON Lines 完全绕过了有界的 `json.PReader`**。第三方 parser 会越过 chunk 边界一直读到换行才停。

关键在于这一句判断：

> A generic reader wrapper could not simultaneously preserve already completed records and guarantee a bound on the next record.

——通用 wrapper 无法同时做到"保留已完成的记录"和"保证下一条记录有界"。所以最终方案**不是再加一层 wrapper**，而是：

> JSON Lines temporarily stopped using the SIMD path and always used the bounded PReader. If SIMD support returns, that implementation must enforce the same record limit itself and pass the same CPU-independent regression suite.

即**暂时放弃 SIMD 快路径，换取一致的安全语义**。同时附带修正了错误映射（用 `errors.As` 透传实现 `SelectError` 的错误）、parser 错误包装为 `JSONParsingError`、终止错误前 flush 已完成记录、以及按输入顺序保留错误优先级。

源码落点：`internal/s3select/json/preader.go`（有界读取器 `PReader`，用 `bpool` 池化输入缓冲与输出 KV 块）、`internal/s3select/simdj/reader.go`（SIMD 路径，依赖 `github.com/minio/simdjson-go`）。详见 [S3 Select Defense](/docs/CS/Distributed/Silo/S3_Select_Defense.md)。

### Deliberately Left Out

公告明确列出了**本次刻意不修**的部分：

- CSV `AllowQuotedRecordDelimiter` 与外层物理换行 splitter 的历史不一致；
- CRLF 中 `\r` 是否计入记录长度；
- 恢复 SIMD 性能但不设等价上限。

理由是：这些问题可能是真的，但需要独立的 AWS 兼容性证据或更复杂的引号感知 splitter，**不属于一个基于猜测的安全补丁**。

## The Internode Trust Boundary: CVE-2026-42600

这条修复展示了一种与 MinIO 上游代码风格明显不同的做法——**新增独立守卫文件，而不是在既有 handler 里打补丁**。

Silo 引入了上游没有的文件 `cmd/storage-rest-server-guard.go`，核心是一个包装器：

```go
// guardedStorage rejects filesystem paths that arrive from an internode
// payload and would resolve outside the volume they name.
//
// Why here and not in each handler: the global HTTP middleware validates only
// r.URL.Path and r.Form (query arguments), and r.Form is never populated from
// a request body. Paths carried in a msgpack body, or in a grid RPC frame on
// the long-lived /minio/grid/v1 websocket, therefore reach xlStorage
// unvalidated. Every storage-REST and grid handler obtains its StorageAPI from
// storageRESTServer.getStorage(), so wrapping that one call covers all of them
// at once, sees the nested struct fields a per-handler check tends to miss,
// and cannot drift out of sync as handlers are added.
```

这段注释把**为什么选在这一层**讲得比补丁本身更有价值：

1. 全局 HTTP 中间件只校验 `r.URL.Path` 与 `r.Form`，而 `r.Form` **永远不会从请求体填充**——所以 body 里携带的路径（msgpack body、grid RPC 帧）能绕过中间件直达 `xlStorage`。
2. 所有 storage-REST 与 grid handler 都通过 `storageRESTServer.getStorage()` 拿 `StorageAPI`，**包住这一个调用**就覆盖全部 handler。
3. 包在入口处还能看到"逐 handler 检查容易漏掉的嵌套 struct 字段"，且**不会随 handler 增加而失配**。

守卫的作用域被刻意收窄，注释同样写明：

```go
// Scope, deliberately narrow:
//
//   - Only *path* arguments are checked here. Volume arguments are validated
//     at the sink by xlStorage.getVolDir, which additionally covers callers
//     that bypass this wrapper entirely (the peer-S3 bucket RPCs).
//
//   - Local callers - the erasure layer talking to its own drives - are not
//     wrapped. Their object names already passed IsValidObjectName at the S3
//     boundary, so wrapping them would add cost and regression risk without
//     adding a control.
```

配套的 CVE-2026-42600 修复则是**直接移除废弃的 `ReadMultiple` storage-REST API**，关掉 `/rmpl` 暴露的旧节点间文件读取路径——在 `cmd/storage-rest-server.go` 与 `cmd/storage-rest-common.go` 中已检索不到 `ReadMultiple` 的处理分支。回归测试放在 `cmd/storage-rest-traversal_test.go` 与 `cmd/storage-rest-server-guard_test.go`。

## Trust Configuration Hardening

CVE-2026-33419 的修复牵涉到受信代理与限流配置，`RELEASE.2026-06-18` 的说明写得很细：

> 加固 LDAP STS 限流源地址分桶：限流现在仅按源 IP 分桶，避免按用户名共享的 bucket 被单一客户端耗尽并锁定合法用户。受信代理处理现在从右到左解析 `X-Forwarded-For`，拒绝全网段 trusted-proxy CIDR，忽略 RFC 7239 `Forwarded`，并明确记录 `X-Real-IP` 的部署约定。

四个要点：

- **限流键从"源 IP + 用户名"改为"仅源 IP"**——原来的组合键让攻击者可以用同一个用户名占满整个 bucket，导致合法用户被锁在门外（自我 DoS）。
- **从右到左解析 `X-Forwarded-For`**——这是代理链的标准解析方向，防止客户端伪造左侧 `X-Forwarded-For` 冒充可信来源。
- **拒绝全网段 trusted-proxy CIDR**——`0.0.0.0/0` 之类的配置等于"信任所有人"，必须拒绝。
- **忽略 RFC 7239 `Forwarded`**——避免两套 header 语义不一致带来的绕过。

## Reporting and Disclosure

Silo 的漏洞披露流程写在 `SECURITY.md` 与 `VULNERABILITY_REPORT.md` 里：

1. 优先使用仓库的 **private GitHub security advisory** 通道（`/security/advisories/new`）；
2. 私有通道不可用时，通过仓库联系维护者，**在建立私有通道前不公开利用细节**；
3. 若确认同样影响上游 `minio/minio`，**另行向上游报告**。

第 3 条是 fork 的基本礼仪：不能因为自己修了就当作上游的问题不存在。

CI 侧有 `vulncheck` workflow 做依赖漏洞扫描，配合 `buildscripts/resolve-right-versions.sh` 等脚本刷新依赖基线。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Architecture（fork 基线与模块替换）](/docs/CS/Distributed/Silo/Architecture.md)
- [Storage Guard（节点间信任边界实现）](/docs/CS/Distributed/Silo/Storage_Guard.md)
- [S3 Select Defense（有界读取与 SIMD 路径）](/docs/CS/Distributed/Silo/S3_Select_Defense.md)
- [Compatibility Guard（协议标识符冻结）](/docs/CS/Distributed/Silo/Compatibility_Guard.md)

## References

1. [Silo 安全公告账本](https://silo.pgsty.com/about/security-advisories/)
2. [SECURITY.md（安全策略与继承修复证据）](https://github.com/pgsty/silo/blob/main/SECURITY.md)
3. [VULNERABILITY_REPORT.md（披露流程）](https://github.com/pgsty/silo/blob/main/VULNERABILITY_REPORT.md)
4. [CVE-2026-39414 修复分析（两轮修复）](https://silo.pigsty.cc/blog/security/cve-2026-39414)
5. [Silo 20260618 发布说明（LDAP STS 与依赖刷新）](https://silo.pgsty.com/zh/blog/release/20260618)
6. [pgsty/minio RELEASE.2026-04-17T00-00-00Z（初修）](https://github.com/pgsty/silo/releases/tag/RELEASE.2026-04-17T00-00-00Z)
