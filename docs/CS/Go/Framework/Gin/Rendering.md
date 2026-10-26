# Gin Rendering

## Introduction

handler 通过 `gin.Context` 上的一组方法返回响应：JSON / XML / HTML / String / Data / File / Redirect / Negotiate。渲染逻辑集中在 `gin/render` 包，每种格式对应一个 `render.Render` 实现，JSON 默认走 `encoding/json`。本章讲清各方法语义、可替换点、模板渲染与内容协商变体。

## Response Methods

| 方法 | 用途 |
| :-- | :-- |
| `c.JSON(code, obj)` | 序列化为 JSON，`Content-Type: application/json`；底层 `json.Marshal` |
| `c.XML(code, obj)` | 序列化为 XML |
| `c.YAML(code, obj)` | 序列化为 YAML（需引入 `gopkg.in/yaml.v3`） |
| `c.HTML(code, tmpl, data)` | 用已加载的 `html/template` 渲染（先 `LoadHTMLGlob`） |
| `c.String(code, format, args...)` | 格式化纯文本 |
| `c.Data(code, contentType, bytes)` | 直接写原始字节（如文件内容、protobuf 响应） |
| `c.File(path)` | 以 `http.ServeContent` 流式返回文件，自动设置 `Content-Type` 与 `Last-Modified` |
| `c.FileAttachment(path, name)` | 同上并加 `Content-Disposition: attachment`（下载） |
| `c.Redirect(code, url)` | 301/302 重定向（`c.Redirect(301, "/new")`） |
| `c.Negotiate(code, cfg)` | 按 `Accept` 头在多格式间协商（v1.12.0 增加 Protobuf 支持） |

> [!NOTE]
>
> v1.12.0 起内容协商支持 Protobuf（`Offered` 含 `application/protobuf` 时按 `proto.Message` 编码），并在 `gin/render` 包新增 `render.BSON` 类型——表明 Gin 在朝多序列化格式扩展。

## Template Rendering

返回 HTML 需先加载模板，再在 handler 中渲染：

```go
r.LoadHTMLGlob("views/*.html")   // 或 LoadHTMLFiles("a.html","b.html")
r.GET("/", func(c *gin.Context) {
    c.HTML(200, "index.html", gin.H{"title": "Home"})
})
```

模板函数可通过 `r.SetHTMLTemplate(tmpl)` 注入自定义 `template.FuncMap`。Debug 模式下模板改动会被重新加载。

## JSON Variants

| 方法 | 行为 |
| :-- | :-- |
| `c.JSON` | 标准 JSON |
| `c.SecureJSON` | 输出前缀 `)]}',\n` 防 JSON 劫持 |
| `c.JSONP` | 支持 `callback` query 的 JSONP 包裹 |
| `c.AsciiJSON` | 把非 ASCII 转义为 `\uXXXX`，保证纯 ASCII 输出 |
| `c.PureJSON` | 不转义 HTML 字符（默认 `json.Marshal` 会把 `<`、`>`、`&` 转义，PureJSON 关闭该行为） |

## Replacing the JSON Engine

JSON 渲染由 `gin/render` 包的 `render.JSON` 完成，底层是标准库 `encoding/json`。Gin **没有**公开的"全局一键替换 JSON 序列化器"API；若要换 `jsoniter` 等更快实现，需自定义实现 `render.Render` 接口（提供 `Render(http.ResponseWriter, interface{})` 与 `WriteContentType`），再用 `c.Render(code, myRender)` 返回；或直接封装一个自己的 JSON 渲染器。

> [!WARNING]
>
> 文档层面"Gin 主打性能、JSON 快"容易让人误以为 Gin 自带高性能 JSON 引擎——其实**默认就是 `encoding/json`**，与 Hertz 默认 `bytedance/sonic` 不同。需要更快 JSON 得自行替换序列化器，否则 Gin 的 JSON 吞吐受标准库限制。

## Content Negotiation

`c.Negotiate` 根据请求 `Accept` 头选择渲染格式，适合同一路由既出 JSON 又出 XML/HTML/Protobuf：

```go
r.GET("/data", func(c *gin.Context) {
    c.Negotiate(200, gin.Negotiate{
        Offered: []string{"application/json", "application/xml", "application/protobuf"},
        Data:    myStruct, // 匹配到的格式用 Data（若为 proto.Message 则按 protobuf 编）
    })
})
```

## Links

- [Gin](/docs/CS/Go/Framework/Gin.md)
- [Binding and Validation](/docs/CS/Go/Framework/Gin/Binding_Validation.md)
- [Hertz Binding and Rendering](/docs/CS/Go/Framework/Hertz/Binding_Rendering.md)

## References

- <https://github.com/gin-gonic/gin/tree/master/render>
- <https://pkg.go.dev/github.com/gin-gonic/gin#Context.JSON>
