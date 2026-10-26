# Gin Binding and Validation

## Introduction

"绑定"指把 HTTP 请求里的数据（JSON body、query、表单、路径参数、header、XML…）映射到 Go 结构体或基本类型；"校验"指在绑定的同时按规则检查字段合法性。Gin 把二者打包成 `ShouldBind` / `Bind` 系列方法，底层用 [go-playground/validator/v10](https://github.com/go-playground/validator)（v1.12.0 锁定 v10.30.1）做结构体校验。这是写业务 handler 最高频的动作。

## ShouldBind vs Bind

两者都按 `Content-Type` 自动选择绑定器（JSON / XML / form / query…），区别在于**出错时的行为**：

| 方法 | 底层 | 出错行为 |
| :-- | :-- | :-- |
| `c.ShouldBind(&obj)` | `ShouldBindWith`（不写响应） | 返回 `error`，**不**自动 abort，由调用方决定 |
| `c.Bind(&obj)` | `MustBindWith` | 出错时**写 400 并 `Abort()`**，且返回 error |
| `c.ShouldBindWith(&obj, binding.JSON)` | 指定绑定器 | 手动指定，不自动探测 Content-Type |
| `c.ShouldBindBodyWith(&obj, binding.JSON)` | 缓存 body | body 需被多次绑定时用（默认 body 只能读一次） |

> [!TIP]
>
> 想自己控制错误响应（如返回结构化错误、记日志），用 `ShouldBind`；想要"出错即 400 返回"的最小样板，用 `Bind`。

## Binding Tags

字段标签决定从哪里取值；标签名即绑定器名：

| 标签 | 来源 |
| :-- | :-- |
| `json:"name"` | JSON body |
| `form:"name"` | 表单 / URL-encoded body |
| `query:"name"` | URL query |
| `param:"name"` | 路径参数（`:name`） |
| `header:"X-Token"` | 请求头 |
| `xml:"name"` | XML body |
| `yaml:"name"` | YAML body |
| `uri:"name"` | 路由参数（与 `param` 类似，用于 `ShouldBindUri`） |
| `protobuf:"..."` / `msgpack:"..."` / `toml:"..."` | 对应编码格式（v1.12.0 增强 URI/Query 的 `encoding.UnmarshalText` 支持） |

```go
type CreateUserReq struct {
    Name  string `json:"name" binding:"required,min=2,max=32"`
    Email string `json:"email" binding:"required,email"`
    Age   int    `json:"age" binding:"gte=0,lte=150"`
    Role  string `json:"role" binding:"oneof=admin user guest"`
}
```

## Validator Tags

校验标签写在同一个 `binding:"..."` 里，由 validator/v10 解析：

- 存在性：`required`、`omitempty`（空值跳过校验）。
- 字符串：`min=N`、`max=N`、`len=N`、`contains=`、`startswith=`、`email`、`uuid`、`datetime=`。
- 数值：`gte=`、`lte=`、`gt=`、`lt=`、`eq=`、`ne=`。
- 枚举：`oneof=a b c`。
- 跨字段：`eqfield=Password`、`nefield=`、`required_with=`。
- 跳过：`binding:"-"`。

校验失败时，`ShouldBind` 返回的 error 可进一步用 `err.(validator.ValidationErrors)` 类型断言，拿到具体字段与规则做多语言翻译。

## Custom Validators

注册全局校验函数（在 `main` 早期、绑定前）：

```go
if v, ok := binding.Validator.Engine().(*validator.Validate); ok {
    v.RegisterValidation("phone", func(fl validator.FieldLevel) bool {
        return regexp.MustCompile(`^1[3-9]\d{9}$`).MatchString(fl.Field().String())
    })
}
// 之后即可 binding:"required,phone"
```

多语言错误信息可用 `validator` 的 `RegisterTranslation` + `universal-translator` 接入。

## ShouldBindUri and Path Params

路径参数单独绑定到结构体：

```go
type PathReq struct {
    ID uint `uri:"id" binding:"required,gt=0"`
}
func handler(c *gin.Context) {
    var p PathReq
    if err := c.ShouldBindUri(&p); err != nil { /* ... */ }
}
```

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Rendering](/docs/CS/Go/Framework/Gin/Rendering.md)
- [Middleware](/docs/CS/Go/Framework/Gin/Middleware.md)

## References

- <https://github.com/gin-gonic/gin/blob/master/binding/binding.go>
- <https://pkg.go.dev/github.com/gin-gonic/gin/binding>
- <https://github.com/go-playground/validator>
