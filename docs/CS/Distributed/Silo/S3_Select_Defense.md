# Silo S3 Select Defense

## Introduction

S3 Select 让客户端把 SQL 表达式下推到服务端，在对象存储上直接做筛选与投影。代价是**服务端要替客户端解析不可信数据**——这条路径历来是对象存储的安全重灾区。

CVE-2026-39414 是社区版 MinIO 里一个未修复的高危漏洞，而 Silo 对它的修复过程本身就是一份教科书级案例：**两轮修复、一次自我推翻、一个"暂时放弃性能换语义一致"的取舍**。本册从源码结构讲起，逐层还原这个过程。

## Where the Attack Surface Lives

S3 Select 的代码组织在 `internal/s3select/` 下：

| 路径 | 职责 |
| :--- | :--- |
| `internal/s3select/select.go` | Select 引擎主入口 |
| `internal/s3select/sql/` | SQL 表达式解析与求值 |
| `internal/s3select/csv/` | CSV 记录读取器 |
| `internal/s3select/json/` | JSON Lines 记录读取器（`preader.go` / `reader.go`） |
| `internal/s3select/simdj/` | JSON Lines 的 SIMD 快路径 |
| `internal/s3select/parquet/` | Parquet 读取器 |
| `internal/s3select/jstream/` | 行式 JSON 流式解析底层 |
| `internal/s3select/errors.go` | 错误类型（含 `OverMaxRecordSize`） |

漏洞的根因在于**记录边界判定与解析实现耦合**。CSV 有引号转义，JSON Lines 简单；如果解析器为了"读到分隔符为止"而无限缓冲，一条超长记录就能吃掉任意内存。

## The Bounded Reader: json.PReader

Silo 的解法是引入**有界读取器** `PReader`（`internal/s3select/json/preader.go`）。它的结构说明了设计意图：

```go
// PReader - JSON record reader for S3Select.
// Operates concurrently on line-delimited JSON.
type PReader struct {
	args        *ReaderArgs
	readCloser  io.ReadCloser             // raw input
	buf         *bufio.Reader             // input to the splitter
	current     []jstream.KVS             // current block of results to be returned
	recordsRead int                       // number of records read in current slice
	input       chan *queueItem           // input for workers
	queue       chan *queueItem           // output from workers in order
	err         error                     // global error state, only touched by Reader.Read
	bufferPool  bpool.Pool[[]byte]        // pool of []byte objects for input
	kvDstPool   bpool.Pool[[]jstream.KVS] // pool of []jstream.KVS used for output
	close       chan struct{}             // used for shutting down the splitter before end of stream
	readerWg    sync.WaitGroup            // used to keep track of async reader.
}
```

几个设计点：

- **两级 channel 流水线**：`input`（喂给 worker）与 `queue`（worker 按序输出）。解析并发进行，但**输出严格保序**——`Read` 消费的是 `queue`，不是 `input`。
- **`bpool` 池化**：`bufferPool` 与 `kvDstPool` 复用 `[]byte` 与 `[]jstream.KVS`。S3 Select 是高 QPS 路径，每次请求都新分配大块内存会造成 GC 压力；池化把分配成本摊平。
- **错误状态单点持有**：`err` 字段的注释写明 "only touched by Reader.Read"——错误只有一个写入点，避免并发写竞态。

`Read` 的实现体现了"先吐已有记录，再报错"的语义：

```go
func (r *PReader) Read(dst sql.Record) (sql.Record, error) {
	// If we have have any records left, return these before any error.
	for len(r.current) <= r.recordsRead {
		if r.err != nil {
			return nil, r.err
		}
		...
```

即：**已经解析成功的记录必须先返回，之后才报告错误**。这与公告里那句"flush completed records still waiting below the batch threshold before emitting a terminal error event"是同一件事——客户端不能因为最后一条记录超限就丢掉前面所有合法结果。

## The SIMD Fast Path: simdj.Reader

问题出在另一条路径。`internal/s3select/simdj/reader.go`：

```go
import (
	...
	"github.com/minio/minio/internal/s3select/json"
	"github.com/minio/minio/internal/s3select/sql"
	"github.com/minio/simdjson-go"
)

// Reader - JSON record reader for S3Select.
type Reader struct {
	args    *json.ReaderArgs
	input   chan simdjson.Stream
	decoded chan simdjson.Object
	...
}
```

它基于 `github.com/minio/simdjson-go`，用 `simdjson.Stream` / `simdjson.Object` 走 SIMD 加速的 JSON 解析。**性能显著更好**，但它的读取语义与 `PReader` 不同：`simdjson` 的流式解析器会跨 chunk 边界一直读到换行才停——它不知道"1 MiB 记录上限"这回事。

## Round One: Reuse the Existing Invariant

第一轮修复（commit `c5765dc`，发布于 `RELEASE.2026-04-17T00-00-00Z`）没有新增配置项，而是**复用既有的 `maxCharsPerRecord = 1 MiB` 规则**：

- CSV splitter 与 line-delimited JSON 在超限时提前拒绝，不再继续缓冲或解析；
- 保留最早发生的 splitter 错误，不被后续部分解码覆盖；
- 错误码映射为 `OverMaxRecordSize`，而不是塌缩成通用 `InternalError`。

公告里对这次取舍的措辞很明确：

> This was a deliberate compatibility contraction. Clients with lines or records larger than 1 MiB now had to split their input.

**用兼容性收缩换安全边界**，并且是显式声明的——这是负责任的补丁写法。

## Round Two: The Hardware-Dependent Bypass

第二轮（commit `fd69c89`，发布于 `RELEASE.2026-06-18T00-00-00Z`）顺着调用链再走一遍，发现了这样一条路径：

```
JSON Lines -> simdj.NewReader -> simdjson.ParseNDStream
```

当 `simdjson.SupportedCPU()` 返回 true 时，**JSON Lines 走的是 SIMD 路径，绕过了有界的 `json.PReader`**。第三方 parser 越过 chunk 边界继续读，直到找到换行——上限根本不生效。

这里有一个值得单独记住的工程判断：

> The final choice was not another wrapper. JSON Lines temporarily stopped using the SIMD path and always used the bounded PReader.

为什么不能再加一层 wrapper？因为：

> A generic reader wrapper could not simultaneously preserve already completed records and guarantee a bound on the next record.

**通用 wrapper 无法同时做到"保留已完成记录"与"保证下一条记录有界"**——这是流式解析的根本矛盾，不是实现技巧问题。所以只能做取舍：放弃 SIMD 路径。

公告对未来的约束也写死了：

> If SIMD support returns, that implementation must enforce the same record limit itself and pass the same CPU-independent regression suite.

即：**任何未来要恢复的 CPU 特定快路径，必须自己实现同等上限，并通过与本机 CPU 无关的同一套回归测试**。

## Error Semantics as Part of the Fix

第二轮同时修正了几处"错误语义"问题，这些看起来是细节，实际是客户端可观测契约：

| 修正 | 内容 |
| :--- | :--- |
| 错误透传 | 用 `errors.As` 透传实现 `SelectError` 的错误，而不只是某一个具体类型 |
| 错误包装 | JSON worker 把 parser 失败包装为 `JSONParsingError` |
| 记录 flush | 终止错误事件发出前，先 flush 掉已达批次阈值但仍在等待的记录 |
| 错误优先级 | 按输入顺序保留错误优先级，不让后出现的超限记录覆盖先前的解析错误 |

最后一条尤其重要：**错误优先级 = 输入顺序**。客户端提交的查询里若第 3 条记录解析失败、第 7 条记录超限，报告的必须是第 3 条那个错误，否则客户端排障方向会被带偏。

## Verification and Trade-offs

验证方式：

```bash
go test ./internal/s3select/... -count=1
git diff --check
```

且测试**不依赖本机 SIMD 能力**——这正是上面那句"CPU-independent regression suite"的落地。

代价，公告里也照实写了：

> JSON Lines performance may decrease; this incident did not produce a benchmark that quantifies it.

性能会降，但**没有量化 benchmark**。这是诚实的表述：知道有代价，但没测出具体数字。对比之下，某些项目会含糊地说"性能影响可忽略"。

## Deliberately Not Fixed

公告明确列出本次**刻意不碰**的部分：

- CSV `AllowQuotedRecordDelimiter` 与外层物理换行 splitter 之间的历史不一致；
- CRLF 中的 `\r` 是否计入记录长度；
- 在没有等价上限的前提下恢复 SIMD 性能。

理由：

> These questions may be real, but they require independent AWS-compatibility evidence or a more complex quote-aware splitter. They did not belong in a security patch based on guesses.

**"这些问题可能是真的，但需要独立的 AWS 兼容性证据……不属于一个基于猜测的安全补丁。"** 这句话划清了安全修复与协议兼容性修复的边界：后者需要独立证据，前者只需要可利用性。

## Lessons

把这一轮修复抽出来，有四条可复用的经验：

1. **安全不变量必须跨硬件路径成立**。测试在支持 SIMD 的机器上跑绿，不能证明不支持 SIMD 的机器安全——反过来亦然。
2. **性能快路径是安全债的常见藏身处**。慢路径有界、快路径无界，这类差异往往在上游引入优化时才暴露。
3. **错误码是 API 契约的一部分**。把 `OverMaxRecordSize` 塌缩成 `InternalError`，会让客户端与监控无法区分"安全限制"与"服务故障"。
4. **放弃性能比堆补丁更诚实**。承认"这条快路径现在不安全，先关掉"，比加一层"应该能挡住"的 wrapper 可靠得多。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Security Advisories（公告账本与 CVE 条目）](/docs/CS/Distributed/Silo/Security_Advisories.md)
- [Storage Guard（节点间信任边界）](/docs/CS/Distributed/Silo/Storage_Guard.md)
- [Architecture（fork 基线与模块替换）](/docs/CS/Distributed/Silo/Architecture.md)
- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)

## References

1. [CVE-2026-39414 修复分析（官方两轮复盘）](https://silo.pigsty.cc/blog/security/cve-2026-39414)
2. [internal/s3select/json/preader.go（有界读取器）](https://github.com/pgsty/silo/blob/main/internal/s3select/json/preader.go)
3. [internal/s3select/simdj/reader.go（SIMD 快路径）](https://github.com/pgsty/silo/blob/main/internal/s3select/simdj/reader.go)
4. [Silo 20260618 发布说明（CVE-2026-39414 完整修复）](https://silo.pgsty.com/zh/blog/release/20260618)
5. [Silo 安全公告账本](https://silo.pgsty.com/about/security-advisories/)
