# Iris Binding and Validation

## Introduction

Iris 的请求绑定与 Gin 走的是两条路：Gin 用统一的 `binding:"required"` 标签 + `validator/v10`；Iris 依赖 `github.com/iris-contrib/schema`，并且**按来源分派不同 tag**——表单认 `form`、查询串认 `url`、头认 `header`、路径参数认 `param`。更需要注意的是：Iris 的解绑方法失败时**只返回 error，不设置状态码**，响应码由你自己决定。这是从 Gin/echo 转过来最容易出问题的地方。

本文基于 tag **v12.2.11**，所有方法都在 `context/context.go`（Iris 没有独立的 binding/render 包）。

## Read Methods

| 方法 | 行号 | 来源 |
| :-- | :-- | :-- |
| `ReadJSON(outPtr interface{}, opts ...JSONReader) error` | :2803 | JSON body |
| `ReadJSONStream(onDecode func(DecodeFunc) error, opts ...JSONReader) error` | :2817 | JSON 流式（数组逐项解码） |
| `ReadXML(outPtr interface{}) error` | :2849 | XML body |
| `ReadYAML(outPtr interface{}) error` | :2856 | YAML body |
| `ReadForm(formObject interface{}) error` | :2970 | form / multipart |
| `ReadMultipartRelated() (MultipartRelated, error)` | :3047 | multipart/related |
| `ReadQuery(ptr interface{}) error` | :3127 | URL 查询串 |
| `ReadHeaders(ptr interface{}) error` | :3147 | 请求头 |
| `ReadParams(ptr interface{}) error` | :3159 | 路径参数 |
| `ReadURL(ptr interface{}) error` | :3186 | 查询串 + 路径参数 |
| `ReadProtobuf(ptr proto.Message) error` | :3207 | Protobuf |
| `ReadMsgPack(ptr interface{}) error` | :3238 | MsgPack |
| `ReadBody(ptr interface{}) error` | :3258 | **按 Content-Type 自动分派** |
| `UnmarshalBody(outPtr interface{}, unmarshaler Unmarshaler) error` | :2705 | 自定义 Unmarshaler |

`ReadBody` 的分派逻辑（`:3252-3321`）：

1. 目标为 `*string` / `*[]byte` → 直接取原始 body。
2. GET 且带 RawQuery → `ReadQuery`；否则 `ReadForm`。
3. 否则按 `Content-Type` 走 XML / YAML / form / multipart / JSON / protobuf / msgpack。
4. 都没匹配上 → 有 query 用 `ReadQuery`，否则 `ReadJSON`。

`ReadParams`（`:3159-3179`）会把 `{tail:path}` 这类参数按 `/` 切成 `[]string`，再交给 `schema.DecodeParams` 与 `app.Validate`。

`UnmarshalBody`（`:2705-2741`）的三级顺序：`BodyDecoderWithContext` → `BodyDecoder` → 传入的 `unmarshaler.Unmarshal` → 最后统一调 `ctx.app.Validate(outPtr)`。

## Parameter Access

```go
params := ctx.Params()          // *RequestParams，context.go:869
id, err := params.GetInt("id")  // memstore 提供，core/memstore/memstore.go:927
n := params.GetIntDefault("id", 0)  // :937
s := params.Get("name")
```

`RequestParams` 内嵌 `memstore.Store`（`context/request_params.go:17`），所以 `GetInt/GetInt64/GetBool/GetString` 一族都在 `core/memstore` 里查。

## Schema Tags

解码器是 `github.com/iris-contrib/schema` v0.0.6，默认 alias tag 集合为 `{"form","url","header","param","schema"}`，但每个入口只认自己的那一个：

| 入口 | 生效 tag | 未知 key 处理 |
| :-- | :-- | :-- |
| `ReadForm` | `form` | 会报错（`UnknownKeyError`） |
| `ReadQuery` | `url` | `IgnoreUnknownKeys(true)`，忽略 |
| `ReadHeaders` | `header` | 忽略 |
| `ReadParams` | `param` | 忽略 |

```go
type LoginForm struct {
    Username string `form:"username,required"`
    Password string `form:"password,required"`
}

func login(ctx iris.Context) {
    var f LoginForm
    if err := ctx.ReadForm(&f); err != nil {
        // Iris 不会替你设状态码！
        ctx.StopWithError(iris.StatusBadRequest, err)
        return
    }
    ctx.JSON(iris.Map{"ok": true})
}
```

错误类型（`schema/decoder.go`）：

- `EmptyFieldError`（`:480`）—— `required` 字段缺失。
- `UnknownKeyError`（`:489`）—— 出现未声明的 key（表单场景）。
- `MultiError`（`:500`）—— 上面两者的聚合容器，可遍历取全部字段错误。

> [!WARNING]
>
> 仓库里**没有** `ValidationError` 类型，也**没有** Gin 那种 `binding:"required"` 标签。写 `binding:"..."` 在 Iris 里是无效的——它根本不读这个 tag。

空表单默认返回 `nil`，只有把 `Configuration.FireEmptyFormError` 设为 true 才会报错。

## Struct Validation Hook

真正的结构体校验钩子是 `Application.Validator`：

```go
// iris.go:80
Validator context.Validator

// context/context.go:2694
type Validator interface {
    Struct(interface{}) error
}
```

```go
import "github.com/go-playground/validator/v10"

type CreateUserInput struct {
    Email string `json:"email" validate:"required,email"`
    Age   int    `json:"age"  validate:"gte=0,lte=120"`
}

func main() {
    app := iris.New()
    app.Validator = &myValidator{v: validator.New(validator.WithRequiredStructEnabled())}
    // app.Validate(ptr) 会在每次 Read* / UnmarshalBody 成功后自动调用（iris.go:342）
}
```

要点：`app.Validate`（`iris.go:342`）被 `UnmarshalBody` 与各 `Read*` 在解码成功后调用，因此**校验是挂在解码之后、handler 拿到数据之前**的；返回 error 时同样需要你自己决定状态码。

## File Uploads

```go
func upload(ctx iris.Context) {
    // 单文件
    f, header, err := ctx.FormFile("file")            // :2331

    // 同名字段多文件，before 可逐个过滤
    files, n, err := ctx.UploadFormFiles("./uploads", func(ctx iris.Context, fh *multipart.FileHeader) bool {
        return strings.HasSuffix(fh.Filename, ".png")  // 返回 false 则跳过
    })                                                 // :2469

    // 手动落盘
    n, err := ctx.SaveFormFile(header, "./uploads/"+header.Filename)  // :2514
}
```

`UploadFormFiles` 内部走 `ParseMultipartForm(GetPostMaxMemory())`（默认 32 MB，由 `Configuration.PostMaxMemory` 控制），文件名经 `SafeFilename` 处理；没有文件时返回 `http.ErrMissingFile`。`FormFiles`（`:2345`）返回同名字段的全部 `*multipart.FileHeader` 而不落盘。

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Rendering](/docs/CS/Go/Framework/Iris/Rendering.md)
- [Iris MVC and Dependency Injection](/docs/CS/Go/Framework/Iris/MVC_and_Dependency_Injection.md)
- [Gin Binding and Validation](/docs/CS/Go/Framework/Gin/Binding_Validation.md)
- [Hertz Binding and Rendering](/docs/CS/Go/Framework/Hertz/Binding_Rendering.md)

## References

- <https://github.com/kataras/iris/blob/main/context/context.go>
- <https://github.com/iris-contrib/schema>
- <https://github.com/kataras/iris/tree/main/_examples/request-body>
- <https://github.com/kataras/iris/tree/main/_examples/file-server>
- <https://github.com/go-playground/validator>
