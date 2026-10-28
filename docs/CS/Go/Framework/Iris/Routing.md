# Iris Routing

## Introduction

Iris 的路由有两件事与其它 Go 框架不一样：一是 trie 是**自研的**（`kataras/muxie` 的同构版本，不是 httprouter 系的压缩前缀 radix tree）；二是路径参数带**类型系统**（macro），`:uint64 min(1)` 这种写法在路由层就把非法输入挡掉。这两点决定了 Iris 路由层的表达能力明显强于 Gin/Echo，代价是概念更多。

本文基于 tag **v12.2.11** 源码。

## Trie Implementation

`core/router/` 下只有 `trie.go`（没有 `tree.go`/`node.go`）。文件头注释直接写明出处：

```go
// core/router/trie.go:21
// An iris-specific identical version of the https://github.com/kataras/muxie version 1.0.0
```

节点结构 `trieNode`（`trie.go:22-39`）用 `children map[string]*trieNode` 加两个特殊指针 `childNamedParameter`（`:` 开头）与 `childWildcardParameter`（`*` 开头），参数起止符常量在 `trie.go:9-19`（`ParamStart=":"`、`WildcardParamStart="*"`）。与 httprouter 的 radix 压缩不同，它按路径段展开。

路由表本身是**按 method × subdomain 分树**：`trees []*trie` 与 `errorTrees []*trie`（`core/router/handler.go:64-65`），检索时由 `getTree` 定位（`handler.go:207-226`）。

## Macro: Typed Path Parameters

内置宏定义在 `macro/macros.go`，`Defaults` 列表见 `:517-538`，共 20 个：

| 宏（变量） | 定义行 | 语义 | 支持的内联函数 |
| :-- | :-- | :-- | :-- |
| `String`（master） | :22 | 任意单段；其余类型可借用它的函数 | `regexp` `prefix` `suffix` `contains` `min`(长度) `max`(长度) `eq` `eqor` |
| `Int`（别名 `number`） | :84 | 有符号整数（int64/int32 依架构） | `min` `max` `range` |
| `Int8` / `Int16` / `Int32` / `Int64` | :116 / :141 / :166 / :191 | 定宽有符号整数 | `min` `max` `range` |
| `Uint` / `Uint8` / `Uint16` / `Uint32` / `Uint64` | :224 / :255 / :286 / :311 / :336 | 无符号整数 | `min` `max` `range` |
| `Bool`（别名 `boolean`） | :368 | `strconv.ParseBool` | 无 |
| `Alphabetical` | :383 | `^[a-zA-Z ]+$` | 无 |
| `File` | :400 | `^[a-zA-Z0-9_.-]*$` | 无 |
| `Path` | :413 | 任意，**必须是末段**（trailing=true） | 无 |
| `UUID`（别名 `uuidv4`） | :417 | `uuid.Parse` | 无 |
| `Mail` | :428 | `mail.ParseAddress` | 无 |
| `Email` | :440 | 在 Mail 之上额外做 `net.LookupMX` 域名校验 | 无 |
| `Date` | :463 | 布局 `2006/01/02`，trailing=true | 无 |
| `Weekday` | :495 | 0-6 或星期名 | 无 |

写法与效果：

```go
app.Get("/users/{id:uint64 min(1)}", getUser)      // 类型不符/越界 → 路由层直接 404
app.Get("/files/{p:path}", serveFile)              // 通配，必须末段
app.Get("/mail/{addr:email}", checkMail)           // 含 MX 校验
app.Get("/date/{d:date}/edit", editByDate)         // 2006/01/02
app.Get("/profile/{name:alphabetical}", profile)   // 纯字母
```

> [!WARNING]
>
> `min`/`max` 在 `String` 上是**长度**语义，在数值类型上是**大小**语义——同一个名字两套含义，这是最容易踩的坑。

`core/router/handler.go:380` 的 `bindMultiParamTypesHandler` 配合 `macro/handler` 做"同一路径段多类型候选"的分派（例如 `/{id:int}` 与 `/{id:string}` 同时注册）。

## Registration API

注册方法实现在 `core/router/api_builder.go`，接口声明在 `core/router/party.go:300-380`，由 `iris.Application` 内嵌 `*router.APIBuilder` 直接暴露：

```go
app.Get("/ping", h)          // api_builder.go:1485
app.Post("/users", h)        // :1492
app.Any("/x", h)             // :1555，全部 method
app.Handle("GET", "/y", h)   // :540，显式 method
app.HandleMany("GET POST", "/z", h)  // :589，一次注册多 method
```

## Party (Route Grouping)

```go
func (api *APIBuilder) Party(relativePath string, middleware ...context.Handler) Party // api_builder.go:839
// 接口声明：core/router/party.go:155；iris.Party = router.Party（aliases.go:146）
```

用法与继承规则：

```go
api := app.Party("/api", authMiddleware)
{
    v1 := api.Party("/v1")          // 继承 authMiddleware
    v1.Get("/users", listUsers)
    v1.Party("/admin", adminOnly)   // 可无限嵌套
}
```

- 子 Party 复用父的 begin/done handler 链；`Reset()` 可清除继承（`party.go:249`）。
- 另有 `PartyFunc(relativePath, func(p Party))`（`party.go:172`）与 `PartyConfigure`（`:198`）两种写法糖。
- `Subdomain`（`party.go:204`）是 Iris 特色：子域名路由，嵌套时前缀反向拼接（如 `panel.admin.`）。

## Route Naming and Reverse Routing

```go
r := app.Get("/users/{id:uint64}", getUser)
r.SetName("user-by-id")                     // core/router/route.go:303

route := app.GetRoute("user-by-id")         // api_builder.go:1097（只读版 :1131）
```

运行时读当前路由：`ctx.RouteName()`（`context/context.go:660`）；只读视图接口 `context.RouteReadOnly`（`context/route.go:14-60`）含 `Name/Method/Path/IsOnline/Trace/Tmpl/MainHandlerName`。

反向生成 URL 由 `RoutePathReverser` 承担（`core/router/path.go`）：

```go
rev := router.NewRoutePathReverser(app.APIBuilder, router.WithScheme("https"), router.WithHost("example.com"))
path, err := rev.Path("user-by-id", 42)   // /users/42       (:338)
url,  err := rev.URL("user-by-id", 42)    // https://...     (:379)
```

## Static Files and SPA

v12.2.11 的静态资源 API 是 **`HandleDir`**：

```go
// core/router/party.go:341；实现 api_builder.go:639
HandleDir(requestPath string, fileSystem interface{}, opts ...DirOptions) []*Route
```

```go
app.HandleDir("/static", iris.Dir("./assets"))
app.HandleDir("/public", iris.Dir("./assets"), iris.DirOptions{
    IndexName: "/index.html",
    SPA:       true,   // 单页应用兜底到 index.html
    Compress:  true,
    ShowList:  false,
})
```

底层是 `FileServer(fs, DirOptions)`（`core/router/fs.go:165`），SPA 只是 `DirOptions.SPA bool`（`fs.go:125`）——**没有 `app.SPA()` 这个方法**，也没有 `StaticWeb`（那是很早以前的旧名，v12.2.11 已完全移除）。

## Path Correction and Fallbacks

行为开关用 Configurator，不是 app 方法：

| 开关 | 位置 | 默认 | 行为 |
| :-- | :-- | :-- | :-- |
| `WithoutPathCorrection` | `configuration.go:270` | 开启修正 | 去掉尾部多余斜杠；POST/PUT 用 **307** 重定向（`handler.go:456-483`） |
| `WithPathIntelligence` | `:277`（字段 `:743`） | 关闭 | 仅 GET，301 到 `ctx.FindClosest(1)`（`handler.go:521-529`） |
| `WithFireMethodNotAllowed` | `:350`（字段 `:770`） | 关闭 | 405 时写 `Allow` 头（`handler.go:506-519`） |
| `WithoutPathCorrectionRedirection` | `:284` | — | 修正时不发重定向，直接内部改写 |

错误兜底：`OnErrorCode(statusCode, handlers...)`（`party.go:141`，实现 `api_builder.go:1725`）、`OnAnyErrorCode`（`party.go:145`）、`UseError`（`api_builder.go:1294`）；未命中最终落到 `ctx.StatusCode(404)`（`handler.go:531`）。

`app.WrapRouter(wrapperFunc WrapperFunc)`（`core/router/router.go:305`）是最高优先级的包装层，能在 trie 匹配之前改写 `w/r`——`rewrite` 与 `methodoverride` 都靠它。

## API Versioning

`versioning` 包的关键 API（注意与常见误记不同，这里**没有** `Accept`/`Header` 函数）：

```go
// versioning/group.go:86
func NewGroup(r API, version string) *Group
```

第二参是 **semver 区间**，不是路径：

```go
api := app.Party("/api")
v1 := versioning.NewGroup(api, ">=1.0.0 <2.0.0")
v1.Get("/users", listUsersV1)

v2 := versioning.NewGroup(api, ">=2.0.0 <3.0.0")
v2.Get("/users", listUsersV2)
```

- 内部会 `SetRegisterRule(RouteOverlap)` + `UseOnce(...)` + `UseError(...)`（`group.go:102-109`），让同路径多版本共存。
- 弃用声明：`Group.Deprecated(options)`（`group.go:119`）、`Deprecated(handler, options)`（`deprecation.go:62`）、`DefaultDeprecationOptions`（`:33`）。
- 版本取值：`GetVersion(ctx)`（`version.go:145`）、`SetVersion`（`:198`）、`Match`（`:94`）、`If`（`:78`）、`FromQuery(name, default)`（`:60`）、`Aliases`（`:228`）、`GetVersionAlias`（`:259`）、`NotFoundHandler`（`:41`）、`ErrNotFound`（`:37`）。

## Rewrite Engine

```go
func New(opts Options) (*Engine, error)   // middleware/rewrite/rewrite.go:99
type Options struct {
    RedirectMatch   []string  // "301 /seo/(.*) /$1"
    PrimarySubdomain string
}
```

两种接入方式，性能特征不同：

```go
app.UseRouter(engine.Handler)   // Engine.Handler:158 —— 走中间件链
app.WrapRouter(engine.Rewrite)  // Engine.Rewrite:173 —— 命中即止，更快
```

配置可从文件加载：`rewrite.Load(filename)` 返回 `router.WrapperFunc`（`:86`），支持 yml/json（`LoadOptions:38`）。

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Architecture](/docs/CS/Go/Framework/Iris/Architecture.md)
- [Iris Middleware](/docs/CS/Go/Framework/Iris/Middleware.md)
- [Gin Routing](/docs/CS/Go/Framework/Gin/Routing.md)
- [Hertz Routing](/docs/CS/Go/Framework/Hertz/Routing.md)

## References

- <https://github.com/kataras/iris/blob/main/core/router/trie.go>
- <https://github.com/kataras/iris/blob/main/macro/macros.go>
- <https://github.com/kataras/iris/blob/main/core/router/api_builder.go>
- <https://github.com/kataras/iris/blob/main/versioning/group.go>
- <https://github.com/kataras/muxie>
