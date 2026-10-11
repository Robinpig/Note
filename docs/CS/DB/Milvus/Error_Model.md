## Introduction

Milvus 的组件跨进程（Proxy / MixCoord / QueryNode / StreamingNode）、跨语言（Go 与 C++ segcore 之间隔着一层 cgo）、跨协议（gRPC 与 REST v2）。错误如果不能被当作公共契约统一管理，同一个故障就会在不同入口呈现出不同的码、不同的文案、甚至不同的可重试性。`pkg/util/merr` 就是这层契约：统一的错误分类、稳定的数字错误码、明确的可重试位，以及在 cgo 边界两侧的双向翻译。

错误在本库有三层载体：跨组件边界的 typed merr 哨兵（`pkg/util/merr/errors.go`），经 `commonpb.Status` 在 gRPC/REST 线路上传输；组件内部方言（只在组件边缘翻译成 typed merr）；进程内 `errors.New` 哨兵（只能被 `errors.Is` 捕获，必须在任何 gRPC 边界之前翻译）。三层都没兜住时，边界上得到 65535（`errUnexpected`）——含义是「有人忘了给错误分类」。

本篇讲契约本身：分类、码空间、可重试语义、Wire 投影、REST 映射、cgo 翻译与工程约定。各子系统的业务错误语义（索引构建失败、compaction 阻塞等）散在各自篇；限流相关的两个码 8/9 的机制展开见 [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)，本篇只做契约层面的引用。

## Error Classification

merr 的分类只有两档，回答的是「谁之过」：`SystemError`（0，默认）与 `InputError`（1）。判据是 blame test——**一个实现正确的 Milvus，面对当前请求，是否可能走到这个分支**：请求内容自身逼出的失败（参数非法、schema 不匹配）是 `InputError`；Milvus 的 bug、内部契约破坏或瞬时故障（not-ready、TOCTOU 竞态）是 `SystemError`。「看起来像校验」不是判据。

`milvusError` 是具体类型而非接口，核心字段：

| 字段 | 作用 |
| :--- | :--- |
| `msg` / `detail` | 客户端可见消息；`wrapFields` 在消息尾部追加 `[k=v]` 结构化字段 |
| `errCode` / `errType` | 数字错误码与 System/Input 分类 |
| `retriable` | 可重试位，见下文 |
| `inner` | 可选内层 error：relabel 后内层仍可 `errors.Is`；`Is` 只按 `errCode` 相等判定 |

分类不是装饰：`InputError` 会让最终投影强制 `Retriable=false`、打 `ExtraInfo["is_input_error"]`，让 Proxy 的换副本逻辑直接放弃（`lb_policy`）、让 `retry.Do` 立即返回、让访问日志按 `error_type` 区分归责。`GetErrorType` 沿链找最外层分类器，边界打的 `errorTypeMarker` 优先于哨兵自带分类。

## Code Allocation

所有码在 `errors.go` 里用 `newMilvusError(msg, code, retriable, opts...)` 注册；同码重复会在包 init 时 panic（`registeredCodes` 注册表），因为 `milvusError.Is` 只按码比较，「一码两哨兵」会让不相关的错误 `errors.Is` 语义串台。命名规则 `Err` + 语义前缀 + 名称；新增前先扫注册表，多数「新错误」要么落进既有族、要么该复用既有哨兵。

码按语义族分配（同为 `docs/dev/error_sentinel_convention.md` 的区间表）：

| Range | Family | Range | Family |
| :--- | :--- | :--- | :--- |
| 1–99 | service level（1 not-ready、2 unavailable、5 internal） | 1300–1399 | MQ |
| 100–199 | collection | 1400–1499 | privilege / RBAC |
| 200–299 | partition，250 例外为 `ErrGeneralCapacityExceeded` | 1600–1699 | alias |
| 300–399 | resource group | 1700–1799 | field |
| 400–499 | replica | 1800–1899 | HTTP / REST gateway，1807 属此段 |
| 500–599 | channel | 1900–1999 | replicate / CDC |
| 600–699 | segment | 2000–2099 | segcore + knowhere，由 cgo 转换表拥有 |
| 700–799 | index | 2100–2199 | import |
| 800–899 | database | 2200–2299 | query / requery plan |
| 901–999 | node | 2300–2399 | compaction |
| 1000–1099 | io / storage / serialization / data integrity | 2400–2499 | function pipeline，2401 例外为 `ErrDataNodeSlotExhausted` |
| 1100–1199 | request parameter | 2500–2599 | KMS |
| 1200–1299 | metrics | 2600–2699 | snapshot |
|  |  | 3000+ | misc |

`errUnexpected = 65535` 不导出，仅作把无码错误转成 milvusError 的兜底；`Code(err)` 对 `context.Canceled` / `context.DeadlineExceeded` 分别返回 `CanceledCode = 10000` / `TimeoutCode = 10001`（两个常量不是注册哨兵）。`ErrorTypeOfCode(code)` 能从 wire 码反查哨兵烤死的分类，但运行期在边界补打的 InputError 标记无法从码恢复。2000–2099 段由 cgo 转换表拥有，不要手工挑号。

## Retriable Semantics

`retriable` 是 `newMilvusError` 的第三个参数，含义是「重试、或换一个副本/节点重试，可能成功」的瞬时故障位。投影层有一条硬不变量：**InputError 一定 Retriable=false**——`Status()` 即使拿到可重试的底层哨兵也会强制清零，避免给客户端「你的输入是错的但可以重试」的自相矛盾信号。

v3.0.1 中真正消费这个位的边界（它并非处处生效的全局开关）：

| 消费点 | 行为 |
| :--- | :--- |
| `internal/util/grpcclient` | `merr.Error(status)` 后按 `IsRetryableErr` 决定 RPC 是否重试，默认上限 10 次 |
| Proxy `lb_policy` | `InputError` 立即放弃且不拉黑节点；`IsRetryableErr` 只做本次请求的节点排除；否则加入 shard 黑名单 |
| `retry.Do` | `InputError` 直接返回；调用方显式传 RetryErr 谓词时由谓词接管 |
| datacoord compaction | `IsRetryableErr` 且未超过 `maxRetryTimes` 才重试任务 |
| 存储 / import 侧 | 反向消费 `IsNonRetryableErr` 的 denylist，只有 IO 永久错误与客户端校验类不可重试 |
| Go SDK（`client/`） | `RPCError` 携带 retriable 位，`milvusclient.IsRetryableError` 直接暴露 |

有些码的 retriable 是给「调用方重新解析路由」用的（如 507 `ErrChannelMisrouted`：shard map 过期导致投递到错误节点，重解析后可成功）。大量子系统重试用的是自己的策略而非这个位，别把它当全局重试开关。限流码 8（`ErrServiceRateLimit`，retriable）与 9（`ErrServiceQuotaExceeded`，非重试）的机制见 Deployment 篇。

## Wire Projection to gRPC Status

`merr.Status(err)` 是 Go error 到线路表示的投影点，产出 `commonpb.Status`：

| Status 字段 | 内容 |
| :--- | :--- |
| `Code` | `merr.Code(err)`：沿链找到第一个 milvusError 的码；relabel 后的错误上报外层码 |
| `Reason` / `Detail` | 完整错误链文本，外层语境在前、根因在后 |
| `ErrorCode` | 废弃字段，`oldCode(code)` 做旧 SDK 兼容映射（1100/1101/1102 → IllegalArgument，100 → CollectionNotExists，600 → SegmentNotFound，8 → RateLimit，9 → ForceDeny，1/110 → NotReadyServe，未命中 → UnexpectedError） |
| `Retriable` | 投影自 error；InputError 强制 false |
| `ExtraInfo` | InputError 时带 `is_input_error=true` |

反方向 `merr.Error(status)` 以 `ErrorCode_Success && Code==0` 判成功；`Code==0` 的历史报文经 `OldCodeToMerr` 降级还原粗粒度哨兵；Input 标记从 `ExtraInfo` 恢复。重建出的是 `makeMilvusError` 普通值（不再注册），`errors.Is` 命中靠码相等。Milvus 内部 RPC 的错误走「响应体内嵌 Status」而不是 gRPC 传输层 error，客户端统一用 `merr.CheckRPCCall(resp, err)` / `merr.Error(status)` 还原为 Go error。跨组件两跳（Proxy → coord → Proxy）的 roundtrip 被 `error_classification_test.go` 钉死：码、Input 标记、强制不可重试必须两跳存活。

## REST v2 Mapping

REST 网关复用同一批 merr 码作为业务码，但投射方式与 gRPC 不同：业务失败返回 **HTTP 200**，merr 码放在响应体的 `code` 字段（`HTTPReturnCode`），文案进 `message`。认证/鉴权是这条规则的两处窄例外：缺身份 → HTTP 401，body code 固定 1800（`ErrNeedAuthenticate`）；RBAC 拒绝 → HTTP 403，body code 取自 `merr.Code(authErr)`——拒绝本身由 `PrivilegeInterceptor` 以 gRPC `codes.PermissionDenied` 的状态错误抛出，错误链中没有 milvusError，所以这个 403 的 body code 实际是 65535，而不是 1400/1401。`ErrPrivilegeNotAuthenticated`（1400）与 `ErrPrivilegeNotPermitted`（1401）不在鉴权出口上：它们是普通 typed merr（口令校验失败、内置角色保护一类业务错误），仍走通用路径返回 HTTP 200 + body code 1400/1401。

限流是这条规则的样本：REST 侧 limiter 拒绝时返回 HTTP 200 + body `code=1807`（`ErrHTTPRateLimit`），而不是 HTTP 429。另一个差异：REST 错误响应体只带 code 与 message，没有 retriable 位——可重试语义是 gRPC `Status` 才有的能力。

## cgo Boundary to Segcore

C++ 侧不使用 merr。分类裁决发生在 C++ 的异常构造点（`SegcoreError` / `ThrowInfo` / `AssertInfo`；错误码 `ErrorCode` 定义在外部依赖 milvus-common，值域 2000–2099），异常经 cgo 的 `CStatus{error_code, error_msg}` 到达 Go 侧；异步 futures 也从 `SegcoreError` 基类取码，驱动层的 `ExecOperatorException` 特意继承它以免二次包装丢分类。

Go 侧的统一入口是 `HandleCStatus`：读出 code 与 message 后调用 `merr.SegcoreError(code, msg)`，进入 `classifySegcoreError` 查 `segcoreCodeTable`：

- 命中：把 C++ 码映射到 merr 哨兵（保住 `errors.Is` 身份），按表打 `inputError` / `retriable` 旗标，原始 C++ 码写进 `segcoreCode` 字段并在消息里渲染成 `[segcoreCode=N]`；
- 未命中：兜底 `ErrSegcore`（2000，非重试 system 错误），永远不会因为「没登记」而丢错误。

表内三类语义：`inputError`（2020 FieldIDInvalid、2028 ExprInvalid、2032 DimNotMatch、2042 rescorer 参数等，调用方之过）；`retriable`（2012/2013/2014/2015 文件 IO、2018 S3、2027 FieldNotLoaded、2034 OOM、2043 InsufficientResource、2045 StorageTransient 等，换副本重试可能成功）；`signal`（2033 ClusterSkip → `ErrSegcorePretendFinished`，控制流信号而非失败）。

两个反直觉点。其一，客户端拿到的 `Code` 是**映射后哨兵的 merr 码**，不是 C++ 原始码，而且并不总是 2000：**多数**码映射落在通用 `ErrSegcore`，客户端看到 2000——全部 input 旗标码与未登记码的兜底都如此；登记了专名哨兵的少数码各见其码——C++ 2046 → 110（`ErrCollectionSchemaVersionNotReady`）、2003 → 2001（`ErrSegcoreUnsupported`）、2033 → 2002（`ErrSegcorePretendFinished`），而 2037–2040 与 2099 的哨兵 merr 码与 C++ 码同值（`ErrSegcoreFollyOtherException` 至 `ErrSegcoreGCPNativeError` 与 `KnowhereError`），这些码的客户端 Code 数值与原始码一致。原始 C++ 码始终由 `segcoreErrorCode` 携带、与哨兵同链，也渲染进消息文本，需要精确判定时用 `IsSegcoreDataFormatBroken` 这类按码检查的函数（走 `errors.As` 而非码相等）。其二，merr 码与 C++ 码存在巧合同号不同义：表里刻意把 C++ 的 `UnexpectedError`（2001）与 `NotImplemented`（2002）保持在通用 `ErrSegcore`，避免调度器按 `ErrSegcoreUnsupported` / `ErrSegcorePretendFinished` 的槽位语义把任务永久失败或误报完成。

信息丢失的层：cgo 边界只剩 code 与 message 两个字段，异常类型与堆栈全丢；某些嵌套 FFI 边界（如 loon FFI）连 `err_code` 都不保留，源码注释直陈会把失败塌缩为单一分类。因此新加的 C++ 码在登记进表之前一律落为非重试的未分类 system 错误——安全但粗糙，表本身带防漂移意图，新增码应当让测试出声。

## Example Journeys

- **DimNotMatch（C++ 2032）到用户**：QueryNode 的 segcore 查询抛 DimNotMatch → `CStatus(2032, msg)` → Go 侧 `classifySegcoreError` 判为 InputError → RPC 响应 `Status{Code: 2000, ExtraInfo:{is_input_error:true}, Reason:"<C++ 消息>: segcore error[segcoreCode=2032]"}` → Proxy 换副本逻辑见到 InputError 直接放弃 → gRPC 客户端看到码 2000 加 input 标记，REST 客户端看到 HTTP 200 + body `code=2000` 的同一段文本。
- **CollectionNotFound（100）的两副面孔**：哨兵默认 SystemError，好让 datacoord 的 `retry.Do` 恢复流程继续重试瞬时 not-found；到 Proxy 的用户入口（按名字查找的 chokepoint）被 `WrapErrAsInputErrorWhen` 改判 InputError，用户侧拿到 100 加 input 标记，并被重试/换副本逻辑当作「重试无意义」处理。
- **限流进入 REST**：`CheckLimiter` 拒绝 → `ErrHTTPRateLimit`（1807）→ HTTP 200 + body code 1807，机制见 Deployment 篇。

## Engineering Conventions

- 加语境用 `merr.Wrap` / `Wrapf`，保留内层码与分类（客户端看到的码不变）。
- `WrapErrXxxErr` 是**有意换标签**：外层哨兵的 code / errType / retriable 覆盖内层，内层仍可 `errors.Is`（经 `Unwrap`）；只在确实要断言新分类时使用。
- cause 必须走错误参数，绝不塞进格式串——`fmt.Sprintf` 不认 `%w`，塞进字符串会让 `errors.Is` 断链。
- 边界改判用 `WrapErrAsInputError` 与 `WrapErrAsInputErrorWhen`：前者无条件标，后者按码白名单标（Proxy 用它把「用户提供的名字找不到」从 system 改判 input，而按 ID 的内部查找保持 system）。
- 内部 `errors.New` 哨兵只能在同进程被 `errors.Is` 捕获；跨任何 gRPC 边界之前必须翻译成 typed merr 或 `Success`，否则对端只剩 65535。
- 判读统一走 `merr.Code` / `errors.Is(err, ErrXxx)` / `GetErrorType` / `IsRetryableErr`，不要做 `err.Error()` 字符串匹配。
- 测试固化：`error_classification_test.go` 用注册表做 closed-world 校验，InputError 哨兵码恰好 25 个，增删一处 `WithErrorType(InputError)` 就会红；两跳 roundtrip 与 relabel 的 `errors.Is` 几何各有专项测试。

## Links

- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [Query Path](/docs/CS/DB/Milvus/Query_Path.md)
- [Index and Vector Engine](/docs/CS/DB/Milvus/Index_and_Vector_Engine.md)
- [Deployment and Ops](/docs/CS/DB/Milvus/Deployment_and_Ops.md)

## References

- [merr errors.go](https://cdn.jsdelivr.net/gh/milvus-io/milvus@v3.0.1/pkg/util/merr/errors.go)
- [merr utils.go](https://cdn.jsdelivr.net/gh/milvus-io/milvus@v3.0.1/pkg/util/merr/utils.go)
- [merr segcore.go](https://cdn.jsdelivr.net/gh/milvus-io/milvus@v3.0.1/pkg/util/merr/segcore.go)
- [merr error_classification_test.go](https://cdn.jsdelivr.net/gh/milvus-io/milvus@v3.0.1/pkg/util/merr/error_classification_test.go)
