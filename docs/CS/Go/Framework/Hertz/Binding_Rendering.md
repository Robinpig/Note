# Hertz Binding and Rendering

## Introduction

Hertz 把「**把请求数据装进结构体**」与「**把结构体写回响应**」都收敛到 `*app.RequestContext` 上，并默认接入高性能 JSON 引擎 bytedance/sonic。绑定（binding）按 `Content-Type` 与结构体字段标签把请求的不同来源映射到字段；渲染（rendering）把 Go 值序列化成 JSON / 字符串 / HTML / 字节流。校验则叠加在绑定之上，借助 tagexpr / validator 完成。

这一层是 Hertz 四层架构里**应用层**面向业务最常用的一面对外接口——协议层解析出原始请求后，应用层在这里把它变成类型安全的 Go 结构体。

## Binding

`ctx.Bind(&req)` 会根据请求的 `Content-Type`（JSON / Protobuf / Form / XML 等）选择合适的解码器，把数据填进结构体；需要顺带校验时调用 `ctx.BindAndValidate(&req)`。

字段标签决定「请求里的哪一块」映射到「结构体的哪个字段」：

| 标签 | 含义 | 示例 |
| :-- | :-- | :-- |
| `query` | URL query 参数 | `query:"page"` |
| `path` | 路径参数段 | `path:"id"` |
| `header` | 请求头 | `header:"X-Token"` |
| `json` | JSON body 字段 | `json:"name"` |
| `form` | 表单字段 | `form:"age"` |
| `xml` | XML body 字段 | `xml:"item"` |
| `file` | 上传文件 | `file:"avatar"` |
| `cookie` | Cookie | `cookie:"sid"` |
| `default` | 默认值 | `default:"1"` |
| `raw_body` | 原始 body 字节 | `raw_body:"body"` |

```go
type CreateUserReq struct {
    Name  string `query:"name"`
    Age   int    `form:"age"  default:"18"`
    Token string `header:"X-Token"`
}

func createUser(c context.Context, ctx *app.RequestContext) {
    var req CreateUserReq
    if err := ctx.BindAndValidate(&req); err != nil {
        ctx.AbortWithStatusJSON(400, utils.H{"error": err.Error()})
        return
    }
    ctx.JSON(200, utils.H{"name": req.Name, "age": req.Age})
}
```

## Validation

Hertz 的校验构建在 **tagexpr**（`github.com/bytedance/go-tagexpr`）与 **validator**（`github.com/go-playground/validator`）之上：规则写在结构体字段的 `validate` 标签里，绑定阶段一并执行。

```go
type LoginReq struct {
    Email string `json:"email" validate:"required,email"`
    Pass  string `json:"pass"  validate:"required,min=6"`
}
```

> [!WARNING]
>
> v0.10.3 起 Hertz 对 tagexpr/validator 做了重构（移除了 `phonenumbers` 等重依赖、收紧 `FakeBool` 等边界），升级到 v0.10.x 时若自定义了校验规则，建议回归一遍原有校验用例，避免旧写法在新版行为漂移。

## Rendering

`*app.RequestContext` 提供一组渲染方法，JSON 默认走 bytedance/sonic（SIMD + JIT 加速，比标准库 `encoding/json` 更快，API 兼容）：

| 方法 | 用途 |
| :-- | :-- |
| `ctx.JSON(code, obj)` | 序列化为 JSON（默认 sonic），`Content-Type: application/json` |
| `ctx.String(code, format, args...)` | 格式化字符串 |
| `ctx.HTML(code, html)` | 直接写 HTML 字符串 |
| `ctx.Data(code, contentType, data)` | 写原始字节流（自定 contentType） |
| `ctx.File(path)` | 流式返回本地文件 |
| `ctx.Redirect(code, url)` | 302/301 重定向 |

```go
ctx.JSON(200, utils.H{"code": 0, "data": user})   // utils.H 是 map[string]interface{} 的别名
ctx.String(200, "hello %s", name)
ctx.HTML(200, "<h1>home</h1>")
```

`utils.H` 是 Hertz 提供的 `map[string]interface{}` 别名，写小响应体时比声明结构体更顺手；大响应体仍建议用具名结构体（sonic 对固定 schema 更快）。

## Error Handling

handler 返回 `error` 时由框架统一接管，可通过 `server.WithErrorHandler` 覆盖默认行为，把内部错误收敛成一致的 JSON 结构：

```go
h := server.New(server.WithErrorHandler(func(c context.Context, ctx *app.RequestContext, err error) {
    ctx.JSON(500, utils.H{"error": err.Error()})
}))
```

也可以不依赖返回值，直接在 handler 内 `ctx.AbortWithStatusJSON(...)` 主动给出错误响应——两者可以并存，主动返回优先。

## Links

- [Hertz](/docs/CS/Go/Framework/Hertz.md)
- [Middleware](/docs/CS/Go/Framework/Hertz/Middleware.md)
- [Client](/docs/CS/Go/Framework/Hertz/Client.md)

## References

- <https://github.com/cloudwego/hertz>
- <https://www.cloudwego.io/docs/hertz/tutorials/basic-feature/binding-and-validate/>
- <https://github.com/bytedance/sonic>
- <https://github.com/bytedance/go-tagexpr>
