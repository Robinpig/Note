# Iris Rendering

## Introduction

Iris 的响应方法全部集中在 `context/context.go` 一个文件里（**没有** Gin 那样独立的 `render` 包），方法数量也是同类框架里最多的：从常规的 JSON/XML 到 Markdown、Protobuf、MsgPack、流式输出一应俱全。两点需要先纠正常见误解：JSON 编码器就是标准库 `encoding/json`（不是 jsoniter），并且 **v12 没有内置 SSE 支持**（那是 v14 才引入的能力）。

本文基于 tag **v12.2.11**。

## Response Methods

| 方法 | 行号 | 说明 |
| :-- | :-- | :-- |
| `JSON(v interface{}, opts ...JSON) (int, error)` | :4346 | JSON，见下方编码细节 |
| `JSONP(v interface{}, opts ...JSONP) (int, error)` | :4409 | JSONP（回调名取自 query） |
| `XML(v interface{}, opts ...XML) (int, error)` | :4498 | XML |
| `YAML(v interface{}) (int, error)` | :4624 | YAML（带 `---` 文档分隔） |
| `TextYAML(v interface{}) (int, error)` | :4637 | YAML（纯文本 Content-Type） |
| `Markdown(markdownB []byte, opts ...Markdown) (int, error)` | :4589 | Markdown 转 HTML 输出 |
| `Protobuf(v proto.Message) (int, error)` | :4654 | 注意是 `Protobuf` 不是 `ProtoBuf` |
| `MsgPack(v interface{}) (int, error)` | :4675 | MessagePack |
| `Text(format string, args ...interface{}) (int, error)` | :4037 | 纯文本（`Printf` 风格） |
| `HTML(format string, args ...interface{}) (int, error)` | :4043 | HTML |
| `Binary(data []byte) (int, error)` | :4031 | 原始字节 |
| `Write(p []byte) (int, error)` / `WriteString(s string)` | :3349 / :3369 | 直接写响应体 |
| `View(filename string, optionalViewModel ...interface{}) error` | :3939 | 模板渲染（需先 `RegisterView`） |
| `Negotiate(v interface{}) (int, error)` | :4845 | 内容协商 |
| `Redirect(urlToRedirect string, statusHeader ...int)` | :2601 | 重定向 |
| `ServeFile(filename string) error` | :5472 | 直接伺服本地文件 |
| `SendFile(src, destName string) error` | :5513 | 以附件形式下载（`MakeDisposition` :5524 生成 RFC 5987 头） |
| `StreamWriter(writer func(w io.Writer) error) error` | :3534 | 流式输出 |

> [!WARNING]
>
> 根包**没有** `ctx.Attachment()` 方法，只有 `MakeDisposition`（`context.go:5524`），它被 `SendFile` 内部使用。要做附件下载请用 `ctx.SendFile(src, destName)`。

## JSON Encoding

**默认编码器是标准库 `encoding/json`**：

```go
// context/context.go:4176
enc := json.NewEncoder(ctx.writer)
```

`github.com/json-iterator/go` 只在一处真正被 import：`middleware/accesslog/json.go:9`，且仅在 `Indent` 含空格时启用。也就是说，**不要指望 Iris 自动用 jsoniter 加速业务 JSON 响应**。

可选加速路径有两个开关（默认都关闭）：

- `EnableProtoJSON`（`configuration.go:798`，默认 false）——影响 Protobuf 的 JSON 表示。
- `EnableEasyJSON`（`configuration.go:807`，默认 false）——`writeJSON`（`context.go:4145`）判断该开关**且**目标值实现了 `easyjson.Marshaler` 时才走 easyjson 分支。

> [!TIP]
>
> `EnableOptimizations` 常被误传为"启用 jsoniter"。源码里它的释义是 *enables dynamic request handler*（`configuration.go:759`），与 JSON 编码无关，`GetEnableOptimizations()` 在全仓没有调用点。

## Content Negotiation

Iris 的内容协商是 builder 风格：

```go
// context/context.go:4785 取 builder；:4845 执行协商
ctx.Negotiation().JSON().XML().YAML().HTML().Text().Markdown().Binary().Charset("utf-8")
n, err := ctx.Negotiate(iris.Map{"hello": "world"})
```

builder 上的可选方法（`context.go:4977` 起）：`JSON / XML / YAML / TextYAML / Text / HTML / Markdown / Binary / JSONP / Problem / MIME / Charset / Encoding / Compress` 等。

> [!NOTE]
>
> 网上有些旧示例写 `ctx.Negotiate(context.Negotiation{JSON: true, ...})` 或 `context.NegotiationJSON()`——v12.2.11 **没有** `context.Negotiation` 结构体，也没有 `NegotiationJSON()` 函数，全仓 0 命中。请用 `ctx.Negotiation()` builder。

## Streaming and SSE

```go
err := ctx.StreamWriter(func(w io.Writer) error {
    for i := 0; i < 10; i++ {
        fmt.Fprintf(w, "chunk %d\n", i)
        // 每次回调结束框架自动 Flush()
    }
    return nil
})
```

`StreamWriter`（`:3534`）循环调用传入函数并 `Flush()`，同时监听 `request.Context().Done()` 以便客户端断开时退出。

**v12.2.11 没有内建 SSE**。全仓找不到 `text/event-stream` 常量；官方示例（`_examples/response-writer/sse/main.go:85`）是手工实现的：

```go
ctx.ContentType("application/json, text/event-stream")
flusher := ctx.ResponseWriter().Flusher()
for {
    ctx.Writef("data: %s\n\n", payload)
    flusher.Flush()
}
```

一等公民的 SSE 包是 **v14** 才有的能力（作者 2026-08 的说明）。

## View Rendering

```go
app.RegisterView(view.HTML("./views", ".html"))   // iris.go:411
// 或 APIBuilder 层：core/router/api_builder.go:1758

app.Get("/", func(ctx iris.Context) {
    ctx.View("index.html", iris.Map{"Title": "Home"})   // context.go:3939
})
```

引擎清单见 [Extensions](/docs/CS/Go/Framework/Iris/Extensions.md)。

## Status and Headers

Iris 把"停止 + 写响应"合成了一批方法，比先 `StopExecution()` 再手写更常用：

```go
ctx.StopWithStatus(iris.StatusNoContent)
ctx.StopWithText(iris.StatusForbidden, "denied")
ctx.StopWithJSON(iris.StatusBadRequest, iris.Map{"error": "bad input"})
ctx.StopWithError(iris.StatusInternalServerError, err)
ctx.StopWithPlainError(iris.StatusInternalServerError, err)  // 不经过错误码 handler
```

状态码常量沿用 `iris.StatusXxx`（对 `net/http` 常量的别名）。`ctx.StatusCode(n)` 只设状态码不写 body。

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Binding and Validation](/docs/CS/Go/Framework/Iris/Binding_Validation.md)
- [Iris Extensions](/docs/CS/Go/Framework/Iris/Extensions.md)
- [Gin Rendering](/docs/CS/Go/Framework/Gin/Rendering.md)

## References

- <https://github.com/kataras/iris/blob/main/context/context.go>
- <https://github.com/kataras/iris/tree/main/_examples/response-writer>
- <https://github.com/kataras/iris/tree/main/_examples/response-writer/sse>
- <https://github.com/kataras/iris/blob/main/configuration.go>
