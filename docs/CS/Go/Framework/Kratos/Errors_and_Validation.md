# Errors and Validation

本册讲 Kratos 的错误模型与请求校验。Kratos 的错误设计是整个框架里最值得单独说的一块：它**用一个 `errors.Error` 同时承载 HTTP 状态码、gRPC 状态码、业务 reason 与 metadata**，让同一份错误对象能无损地穿过多协议边界。这个设计很优雅，但中间藏着一张**不可逆的映射表**——使用不当会静默丢失语义。

## Error Model

```go
type Error struct {
	Status
	cause error
}

type Status struct {
	Code     int32             // HTTP 状态码
	Reason   string            // 业务语义标识
	Message  string            // 给人看的话
	Metadata map[string]string // 附加 KV
}
```

四个字段的分工要记清楚：

| 字段 | 承载什么 | 示例 |
| :-- | :-- | :-- |
| `Code` | **HTTP 状态码**（不是 gRPC code、不是业务码） | `400`、`500` |
| `Reason` | 机器可读的业务语义 | `"USER_NOT_FOUND"` |
| `Message` | 面向人的描述 | `"用户不存在"` |
| `Metadata` | 结构化附加信息 | `{"field": "email"}` |

> [!NOTE]
>
> `Code` 存的是 **HTTP 状态码**，这是 Kratos 错误模型最关键的一条。`UnknownCode = 500`，`errors.Code(nil)` 返回 `200`。框架从不发明自己的业务码体系——想表达业务语义请用 **`Reason`**。这个取舍让 HTTP 侧可以直接 `w.WriteHeader(int(se.Code))` 而不需要任何转换。

构造与增强：

```go
err := errors.BadRequest("USER_NAME_EMPTY", "用户名不得为空")
err = err.WithMetadata(map[string]string{"field": "name"})
err = err.WithCause(sqlErr)  // 保留底层错误，支持 errors.Is/As/Unwrap
```

`WithCause` / `WithMetadata` / `Clone` 都是**返回新对象**而非就地修改，`Is` 的实现是比较 `Code` 与 `Reason` 二者同时相等。

## Cross-Protocol Conversion

### HTTP → gRPC

当同一个 `*errors.Error` 需要以 gRPC 形式返回时，靠的是实现 grpc-go 的 `GRPCStatus()` 接口：

```go
func (e *Error) GRPCStatus() *status.Status {
	s, _ := status.New(httpstatus.ToGRPCCode(int(e.Code)), e.Message).
		WithDetails(&errdetails.ErrorInfo{
			Reason:   e.Reason,
			Metadata: e.Metadata,
		})
	return s
}
```

即：**HTTP 状态码 → gRPC code**，reason 与 metadata 塞进标准的 `errdetails.ErrorInfo` detail 里。所以 `Reason` 在跨协议后不会丢——这是选择带 detail 而不是拼字符串的重要原因。

### gRPC → HTTP

反向由 `FromError` 完成：

```go
func FromError(err error) *Error {
	if err == nil {
		return nil
	}
	if se := new(Error); errors.As(err, &se) {
		return se
	}
	gs, ok := status.FromError(err)
	if !ok {
		return New(UnknownCode, UnknownReason, err.Error())
	}
	ret := New(httpstatus.FromGRPCCode(gs.Code()), UnknownReason, gs.Message())
	for _, detail := range gs.Details() {
		switch d := detail.(type) {
		case *errdetails.ErrorInfo:
			ret.Reason = d.Reason
			return ret.WithMetadata(d.Metadata)
		}
	}
	return ret
}
```

先尝试 `errors.As` 直接取回原对象；拿不到才做 gRPC status 转换。这个方法支持 wrapped error，所以 `%w` 包装过的错误也能正确识别。

## The Mapping Table

底下那张映射表在 `transport/http/status/status.go`。它暴露成接口，可替换：

```go
type Converter interface {
	ToGRPCCode(code int) codes.Code
	FromGRPCCode(code codes.Code) int
}

var DefaultConverter Converter = statusConverter{}
```

### 入口 ToGRPCCode（HTTP → gRPC）

| HTTP | gRPC code |
| :-- | :-- |
| 200 OK | `OK` |
| 400 Bad Request | `InvalidArgument` |
| 401 Unauthorized | `Unauthenticated` |
| 403 Forbidden | `PermissionDenied` |
| 404 Not Found | `NotFound` |
| **409 Conflict** | **`Aborted`** |
| 412 Precondition Failed | `FailedPrecondition` |
| 429 Too Many Requests | `ResourceExhausted` |
| **499 Client Closed** | `Canceled` |
| 500 Internal Server Error | `Internal` |
| 501 Not Implemented | `Unimplemented` |
| 503 Service Unavailable | `Unavailable` |
| 504 Gateway Timeout | `DeadlineExceeded` |
| 其他 | `Unknown` |

`499` 是 nginx 定义的非标准状态码，用于「客户端提前关闭连接」，映射到 `Canceled`。

### 出口 FromGRPCCode（gRPC → HTTP）

| gRPC code | HTTP |
| :-- | :-- |
| `OK` | 200 |
| `Canceled` | **499** |
| `Unknown` | 500 |
| `InvalidArgument` | 400 |
| `DeadlineExceeded` | 504 |
| `NotFound` | 404 |
| **`AlreadyExists`** | **409** |
| `PermissionDenied` | 403 |
| `Unauthenticated` | 401 |
| `ResourceExhausted` | 429 |
| **`Aborted`** | **409** |
| **`OutOfRange`** | **400** |
| `Unimplemented` | 501 |
| `Internal` | 500 |
| `Unavailable` | 503 |
| **`DataLoss`** | **500** |
| `FailedPrecondition` | 412 |
| 其他 | 500 |

> [!WARNING]
>
> **这张表不可逆——往返一定丢失语义。** 源码级的不对称点：
>
> 1. `AlreadyExists → 409`，但入口是 `409 → Aborted`。所以 HTTP 世界里根本没有办法表达 `AlreadyExists`：一个 `AlreadyExists` 出口成 409，再进口回来就变成 `Aborted` 了。
> 2. `Unknown → 500` 与 `DataLoss → 500`，但入口 `500 → Internal`。二者出口后都坍缩成 `Internal`，不可逆。
> 3. `OutOfRange → 400`，但入口 `400 → InvalidArgument`，同样丢失。
> 4. `409` 同时被 `AlreadyExists` 和 `Aborted` 占用（多对一）。
>
> **实践结论**：不要把 gRPC code 当成可无损跨协议传输的信封。`AlreadyExists`、`OutOfRange`、`Unknown`、`DataLoss` 这四个 code 一旦经过 HTTP 边界就回不来了。跨服务传递业务语义请用 `Reason` 字符串，它是唯一全程无损的字段。

## HTTP Error Encoding

回到 HTTP 侧，`DefaultErrorEncoder` 做的事非常少（`transport/http/codec.go`）：

```go
w.WriteHeader(int(se.Code))
```

然后按 `Accept` 选 codec 把 `Status` 序列化出去。两个特殊分支：

- **redirect errors**：v3.0.0 新增（#3783），实现了 `Redirector` 接口的错误会被转成 HTTP 重定向而不是错误响应。
- **`httpbody.HttpBody`** 类型的响应有专门短路路径。

因为 `Code` 就是 HTTP 状态码，**自定义 `ErrorEncoder` 是全局改造错误响应体的唯一正确位置**（比如统一包成 `{"code":xx,"message":xx}` 的网关统一响应格式）。

## Generated Errors

手写 `errors.BadRequest("XXX", ...)` 容易让 reason 失控，所以 Kratos 提供了 `protoc-gen-go-errors`：在 proto 里用 enum 定义错误，标注 code，生成 Go 侧的构造器。它读的是两个自定义扩展：

| 扩展 | 挂载目标 |
| :-- | :-- |
| `errors.default_code` | `google.protobuf.EnumOptions` |
| `errors.code` | `google.protobuf.EnumValueOptions` |

```protobuf
enum ErrorReason {
  option (errors.default_code) = 500;

  USER_NOT_FOUND = 0 [(errors.code) = 404];
  CONTENT_MISSING = 1 [(errors.code) = 404];
}
```

生成产物是两类函数，而不是常量：

```go
func IsUserNotFound(err error) bool {
	if err == nil { return false }
	e := errors.FromError(err)
	return e.Reason == ErrorReason_USER_NOT_FOUND.String() && e.Code == 404
}

func ErrorUserNotFound(format string, args ...interface{}) *errors.Error {
	return errors.New(404, ErrorReason_USER_NOT_FOUND.String(), fmt.Sprintf(format, args...))
}
```

即：`IsX(err)` 做判断（同时比较 Reason 与 Code），`ErrorX(format, args...)` 做构造。两者都以 **HTTP 状态码**为第二维度，这与上面说的错误模型完全对齐。

> [!NOTE]
>
> code 的有效范围是 **1–600**：大于 600 或小于 0 时生成器**直接 panic**；code 为 0 的值会被跳过。

CLI 与生成流程见 [Protobuf_and_Codegen](/docs/CS/Go/Framework/Kratos/Protobuf_and_Codegen.md)。

## Validation

Kratos 的校验是**双层**的：`middleware/validate` 负责「什么时候调」，`contrib/middleware/validate` 负责「用什么查」。

### 内置 middleware/validate

极简的 duck-typing：

```go
type ValidatorFunc func(any) error

func Validator(validators ...ValidatorFunc) middleware.Middleware
```

它额外内置一条：如果请求对象实现了 `interface{ Validate() error }`，会自动调用该方法，失败则包装成 `errors.BadRequest("VALIDATOR", ...).WithCause(err)`。

也就是说：**它本身不依赖任何校验库**。老的 `protoc-gen-validate` 生成的代码自带 `Validate() error`，所以天然兼容；但新项目推荐直接用 `bufbuild/protovalidate`。

### contrib/middleware/validate

这里才是真正干活的：

```go
import "github.com/go-kratos/kratos/contrib/middleware/validate/v3"

srv.Use("/", validate.ProtoValidate())
```

依赖 **`buf.build/go/protovalidate v1.2.0`**（v3 把主力从 PGV 换成了 protovalidate，老的 `envoyproxy/protoc-gen-validate v1.3.3` 仍作为兼容层挂在 go.mod 里）。protovalidate 直接在运行时用 CEL 表达式解释 proto 里的 `buf/validate` 约束规则，**不需要生成额外的 validate 代码**——这是相对 PGV 的最大改进。

### v3 的新变化

release note #3780 `feat(validate): add custom validator support and improve flexibility` 让 `ValidatorFunc` 的自定义能力更强：不想用 protovalidate 的话，可以直接注入任意 `ValidatorFunc`，比如 go-playground/validator：

```go
srv.Use("/", validate.Validator(func(v any) error {
	return myValidator.Struct(v)
}))
```

> [!NOTE]
>
> 校验必须注册为**业务中间件**才会跑（`srv.Use(...)`）。回顾 [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md) 里的警告：业务中间件只有在 handler 显式调用 `ctx.Middleware(...)` 时才生效——手写路由常被这一条坑到，表现为「明明注册了 validate 却完全不生效」。生成的代码会自动调用，自己写的 handler 要记得补。

## Links

- [Kratos](/docs/CS/Go/Framework/Kratos.md)
- [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md)
- [Transport_gRPC](/docs/CS/Go/Framework/Kratos/Transport_gRPC.md)
- [Protobuf_and_Codegen](/docs/CS/Go/Framework/Kratos/Protobuf_and_Codegen.md)
- [Middleware_and_Observability](/docs/CS/Go/Framework/Kratos/Middleware_and_Observability.md)

## References

- <https://github.com/googleapis/googleapis/blob/master/google/rpc/code.proto>
- <https://github.com/bufbuild/protovalidate>
- <https://pkg.go.dev/github.com/go-kratos/kratos/v3/errors>
