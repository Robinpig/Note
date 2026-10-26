# Iris Extensions and Ecosystem

## Introduction

Iris 的"全内置" Philosophy 意味着很多在 Gin 里要引 contrib 包的能力（视图渲染、WebSocket、i18n、服务端缓存、测试）在这里都是仓库自带。本文收这些子包，并给出 v14 的前瞻与迁移风险评估。

基于 tag **v12.2.11**。

## View Engines

`view/` 下的引擎构造签名统一为 `(fsOrDir interface{}, extension string)`：

| 引擎 | 构造 | 行号 | 说明 |
| :-- | :-- | :-- | :-- |
| HTML | `view.HTML(dirOrFS, ".html")` | `view/html.go:68` | 标准库 `html/template` |
| Django | `view.Django(dirOrFS, ".html")` | `view/django.go:121` | 底层是 `flosch/pongo2/v4` |
| Handlebars | `view.Handlebars(dirOrFS, ".hbs")` | `view/handlebars.go:47` | mailgun/raymond |
| Pug/Jade | `view.Pug(dirOrFS, ".jade")` | `view/pug.go:27` | 底层 Joker/jade，返回 `*HTMLEngine` |
| Jet | `view.Jet(dirOrFS, ".jet")` | `view/jet.go:63` | CloudyKit/jet |
| Ace | `view.Ace(dirOrFS, ".ace")` | `view/ace.go:39` | yosssi/ace |
| Blocks | `view.Blocks(dirOrFS, ".html")` | `view/blocks.go:47` | kataras/blocks；另有 `WrapBlocks`(:34) |

```go
app.RegisterView(view.HTML("./views", ".html"))   // iris.go:411

app.Get("/", func(ctx iris.Context) {
    ctx.View("index.html", iris.Map{"Title": "Home"})   // context.go:3939
})
```

> [!NOTE]
>
> **Pongo2 不是独立引擎**——它只是 Django 引擎的底层实现（`view/django.go:16`）。**也没有 Markdown 模板引擎**；要渲染 Markdown 用 `ctx.Markdown(...)`。

## WebSocket and Real-time

`websocket` 包是 `neffos` 的封装：

```go
// websocket/websocket.go:37
var New = neffos.New
var DefaultGorillaUpgrader = gorilla.DefaultUpgrader   // :27
var DefaultGobwasUpgrader = gobwas.DefaultUpgrader     // :29
```

```go
server := websocket.New(websocket.DefaultGorillaUpgrader, websocket.Namespaces{
    "default": websocket.Events{
        websocket.OnNativeMessage: func(ns *websocket.NSConn, msg websocket.Message) error { ... },
    },
})
app.Get("/ws", websocket.Handler(server))   // Handler(s *neffos.Server, idGenerator ...IDGenerator)，:156
```

- 依赖 `github.com/kataras/neffos`；gorilla / gobwas 是 neffos 的**子包**（`websocket.go:9-11`），`gobwas/ws` 在 go.mod 里是间接依赖。
- neffos 自带命名空间、房间、事件模型与断线重连语义，比裸 gorilla 更重，但也更完整。
- SSE 见 [Rendering](/docs/CS/Go/Framework/Iris/Rendering.md)：v12 无内建，需手写。

## Server-side Cache

```go
iris.Cache       = cache.Handler        // 简单缓存中间件（按 duration）
iris.NoCache     = cache.NoCache        // 强制不缓存（HTML 页面后退刷新场景）
iris.StaticCache = cache.StaticCache    // 静态资源缓存
```

更精细的用法是客户端缓存 handler：

```go
cacheHandler := cache.Cache(func(ctx iris.Context) time.Duration {  // cache/cache.go:77
    return 10 * time.Second
})
app.Get("/expensive", cacheHandler, expensiveHandler)
```

`cache.Handler(expiration)`（`:89`）是简版；`cache.WithKey`（`:42`）可自定义缓存键。

## Internationalization

```go
app.I18n = i18n.New()                                    // i18n/i18n.go:117
app.I18n.Load("./locales/*/*", "en-US", "zh-CN")          // :132，glob 加载
app.I18n.SetDefault("zh-CN")                             // :220
```

运行时取值：`Tr(lang, key, args...)`（`:369`）、`TrContext(ctx, key, args...)`（`:381`，按请求的 `Accept-Language` 推断）、`GetLocale(ctx)`（`:411`）。加载源还支持 `LoadFS`（`:150`）、`LoadKV`（`:161`）、`LoadAssets`（`:140`，go-bindata 风格）。

## Testing

`httptest` 包把 `iris-contrib/httpexpect/v2` 接到 Iris 应用上：

```go
func TestPing(t *testing.T) {
    app := newApp()

    e := httptest.New(t, app)                 // httptest/httptest.go:109
    e.GET("/ping").Expect().Status(httptest.StatusOK).JSON().Object().
        ValueEqual("message", "pong")

    e.POST("/users").WithJSON(map[string]any{"name": "a"}).
        Expect().Status(httptest.StatusCreated)
}
```

要点：

- 签名 `httptest.New(t IrisTesty, app *iris.Application, setters ...OptionSetter) *httpexpect.Expect`（`:109`）；内部用 `httpexpect.NewBinder(app)`（`:137`），**不需要真的起端口**。
- `IrisTesty` 接口（`httptest.go:211`）要求 `Cleanup/Errorf/Fatalf/Helper/Name/...`，`*testing.T` 天然满足；第三方测试框架需自己适配。
- reporter 默认 `NewAssertReporter`（失败继续），`Strict(true)` 切到 `NewRequireReporter`（失败即停）。
- 链式断言的 `Expect().Status(...)` 属于 httpexpect v2 自身 API，不在 Iris 仓库里定义。

## Tunnel and CLI

- `kataras/tunnel`：内置 ngrok 支持，把本地 Iris 服务直接暴露到公网，用于演示/联调（`app.Tunnel(...)` 一族）。
- `cli.go`：Iris 自带命令行工具骨架，便于把自己的应用包装成带子命令的 CLI。

## Looking Ahead: v14

据作者 2026-08 的说明（尚未发布，代码在私有仓库）：

| 项 | 说明 |
| :-- | :-- |
| 模块路径 | `github.com/kataras/iris/v14`（**新路径**，v12 不中断） |
| Go 版本 | 要求 **Go 1.27** |
| 应用构建 | `iris.NewBuilder()` 链式构建，编译器强制步骤顺序 |
| 请求处理 | `rest.ReadJSON[T]` 泛型解码 + 类型自带 `Validate() error` + 集中错误映射 |
| 新能力 | 一等公民 SSE 包、`ai` 包（对接模型后端）、compress 支持 zstd |
| 中间件 | 内置数量提升到 30 |
| 随包文档 | 仓库内 e-book + Claude Code skill/插件 |

> [!WARNING]
>
> 这些都是**未发布**特性：截至 2026-10-26，GitHub 上最新的 tag 仍是 v12.2.11（2024-04-24），模块代理查不到 `iris/v14` 的任何版本，**不要**按 v14 的 API 写生产代码。另外 v12 分支最后一条提交名为 `last version of v12`，等于官方宣布冻结——新版用户需要评估"停在 v12"与"等 v14"的取舍。

## Ecosystem Reality Check

| 维度 | 现状 |
| :-- | :-- |
| 维护节奏 | v12 自 2024-04 起无新 release；`main` 分支仍在滚动（已升 Go 1.26）但无发布 |
| 生态组织 | 没有 Gin 那种庞大的 `gin-contrib` 组织，扩展主要靠仓库自带 + `iris-contrib`（schema、httpexpect） |
| 文档 | 官方站点 + 仓库 `_examples` 非常全，但**文档滞后于代码**（如根 `VERSION` 文件仍写 v12.2.0） |
| 迁移成本 | v12 → v14 是新模块路径 + 大量重命名 API，官方承诺提供迁移指南 |

选型建议：**新项目若看重长期维护活跃度，优先考虑 Gin/Echo；若确实需要 Iris 的 macro 路由、MVC/DI、内置 Session/视图/WS 全套，且能接受"锁定 v12 两年多、未来需要一次性迁移到 v14"，再用 Iris。**

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Rendering](/docs/CS/Go/Framework/Iris/Rendering.md)
- [Iris Sessions and Authentication](/docs/CS/Go/Framework/Iris/Sessions_and_Auth.md)
- [Gin Extensions](/docs/CS/Go/Framework/Gin/Extensions.md)
- [Hertz Extensions](/docs/CS/Go/Framework/Hertz/Extensions.md)

## References

- <https://github.com/kataras/iris/tree/main/_examples>
- <https://github.com/kataras/iris/blob/main/view/html.go>
- <https://github.com/kataras/neffos>
- <https://github.com/kataras/iris/blob/main/httptest/httptest.go>
- <https://github.com/iris-contrib/httpexpect>
- <https://dev.to/kataras/i-ran-24000-of-claude-through-my-terminal-in-august-here-is-what-it-built-37h5>
