# Iris MVC and Dependency Injection

## Introduction

MVC 与依赖注入是 Iris 区别于 Gin/Echo/Hertz 最显著的一块：Gin 生态里"controller 层"是用户自己的事，Iris 直接内置了 `mvc` 包（把结构体方法映射成路由）与 `hero` 包（基于反射的 DI 容器），而且 `mvc` 本身就是用 `hero` 实现的。能力很香，代价是**反射发生在请求路径上**——除非依赖全部是静态值。

本文基于 tag **v12.2.11**。

## MVC Basics

```go
app := iris.New()

users := mvc.New(app.Party("/users"))   // mvc.New(party router.Party) *Application，mvc/mvc.go:81
users.Register(userRepo)                // 注册依赖，:167
users.Handle(new(UserController))       // 挂 controller，:262
```

`mvc.New` 内部做的是 `party.ConfigureContainer().Container.Clone()`——即**每个 mvc.Application 持有自己的 hero 容器副本**，依赖不跨 Party 泄漏。

`*mvc.Application` 的常用方法：

| 方法 | 行号 | 说明 |
| :-- | :-- | :-- |
| `Handle(controller interface{}, options ...Option) *Application` | :262 | 挂载 controller（结构体指针或值） |
| `Register(dependencies ...interface{}) *Application` | :167 | 注册依赖（值或 `func(ctx) T`） |
| `Configure(...func(*Application)) *Application` | :110 | 批量配置 |
| `HandleError(controller interface{}) *Application` | :342 | 挂错误处理 controller |
| `HandleWebsocket(controller interface{}) *Application` | :279 | WebSocket controller |
| `Party(relativePath string) *Application` | :365 | 子分组 |
| `Clone(party) *Application` | :354 | 复制容器 |

## Method-to-Route Mapping

规则在 `mvc/controller_method_parser.go`：

- 方法名**首词**必须匹配 `router.AllMethods` 或 `"ALL"` / `"ANY"`（`:146`）。
- 后续大写词转为小写路径段（`addPathWord`，`:153`）。
- `By` 表示路径参数，按顺序生成 `{paramN:type}`，N 从 1 计（`:188-284`）。
- `ByWildcard` 生成 trailing macro（`:239`）。

```go
type UserController struct{}

func (c *UserController) Get()                    // GET  /users
func (c *UserController) GetBy(id uint64)         // GET  /users/{param1:uint64}
func (c *UserController) GetProfileBy(name string, age int)
                                                  // GET  /users/profile/{param1:string}/{param2:int}
func (c *UserController) Post()                   // POST /users
func (c *UserController) Any()                    // 全部方法
```

> [!NOTE]
>
> 仓库里**没有** `AnyMethodName` 这个东西——"任意方法"就是方法名写成 `Any` 或 `ALL`。

## Lifecycle Hooks

```go
// mvc/controller.go:17
type BaseController interface {
    BeginRequest(*context.Context)
    EndRequest(*context.Context)
}
```

- `BeginRequest` / `EndRequest`：每请求前后；实现该接口即可自动被调用。
- `BeforeActivation(b mvc.BeforeActivation)`（`:31`）：路由解析**之前**，可改路由名、加中间件、改路径词转换函数。
- `AfterActivation(a mvc.AfterActivation)`（`:44`）：路由解析**之后**，可检查最终路由表。
- `HandleHTTPError`（`:461`）：controller 级错误处理入口。

```go
func (c *UserController) BeforeActivation(b mvc.BeforeActivation) {
    b.Handle("GET", "/custom", "CustomGet")   // 显式指定方法+路径+处理函数名
    b.Router().Use(authMiddleware)            // 给整个 controller 分组加中间件
}
```

## hero: Dependency Injection Container

```go
// hero/container.go
func New(dependencies ...interface{}) *Container          // :225
func (c *Container) Register(dependency interface{}) *Dependency  // :280
func Handler(fn interface{}) context.Handler              // :327（包级）
func (c *Container) Handler(fn interface{}) context.Handler        // :361
func (c *Container) HandlerWithParams(fn interface{}) context.Handler // :367
func (c *Container) Struct(ptr interface{}) error          // :374
func (c *Container) Inject(fn interface{}) error           // :397
func (c *Container) UseResultHandler(h func(...))          // :317
```

用法：handler 直接按类型声明入参，容器负责填充。

```go
func getUser(ctx iris.Context, id uint64, repo UserRepository) {
    // id 来自路径参数 {id:uint64}，repo 来自容器
    ctx.JSON(repo.Find(id))
}

app.Get("/users/{id:uint64}", hero.Handler(getUser))
```

内建可直接声明的依赖（`container.go` 的 `BuiltinDependencies`）：`*iris.Context`、`context.Context`、`*sessions.Session`、`*golog.Logger`、`time.Time`、`*http.Request`、`http.ResponseWriter`、`http.Header`、`net.IP` 等。

参数来源三类（`hero/binding.go`）：

1. **路径参数** —— 经 `context.ParamResolvers`（`hero/binding.go:149`，注册在 `context/request_params.go` 的 `ParamResolvers`）。
2. **容器中的服务/依赖** —— 静态值，或形如 `func(ctx) T` 的请求级工厂。
3. **结构体自动绑请求体** —— `hero/binding.go:421` 会 `ctx.ReadBody(ptr)`；可用 `DisablePayloadAutoBinding` 关闭。

`Dependency` 是一个结构体（`hero/dependency.go`），字段含 `OriginalValue / Source / Handle / DestType / Static / Explicit / Match / StructDependents`，用于精细控制匹配行为。

> [!WARNING]
>
> `hero` 里**没有** `hero.Get(...)` 这个函数（只有 `GetCaller()`，`hero/dependency_source.go:70`）。网上旧示例里的 `hero.Get` 是虚构的。

## Performance Characteristics

源码里对性能的说明很直白：

- `Container.Handler` 的文档（`container.go:339`）：若所有依赖都是**静态依赖**，则**请求路径上不涉及反射**；一旦有 request-scoped 依赖（`func(ctx) T`），就要走反射调用。
- `hero/handler.go:96` 的 `makeHandler` 走 `reflect.Value.Call`，是反射开销的来源。
- `Inject` 的注释（`container.go:382`）：*"SHOULD only be used outside of HTTP handlers (performance is not priority)"*——不要在热路径上用。

实践建议：把依赖尽量注册成静态值（连接池、配置、repo 实例），只让"每请求才确定"的东西走工厂函数；极热路径直接写 `func(ctx iris.Context)` 原生 handler。

## Relationship Between mvc and hero

`mvc` 是 `hero` 的上层封装，证据链：

- `mvc/mvc.go:81` 直接构造 `hero.Container`。
- `ControllerActivator.injector *hero.Struct`（`mvc/controller.go:77`），`attachInjector` 调 `c.app.container.Struct(...)`（`:379`）。
- `mvc/aliases.go` 把 `Result` / `Response` / `View` / `Code` 等类型别名为 `hero.*`。

因此 mvc handler 的返回值处理（`hero.FuncResult`）与 hero 完全一致：返回 `(int, error)`、`(string)`、`(mvc.Result)` 等形态都有预置的结果处理器。

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Binding and Validation](/docs/CS/Go/Framework/Iris/Binding_Validation.md)
- [Iris Routing](/docs/CS/Go/Framework/Iris/Routing.md)
- [Iris Sessions and Authentication](/docs/CS/Go/Framework/Iris/Sessions_and_Auth.md)
- [Go Reflection](/docs/CS/Go/Reflection.md)

## References

- <https://github.com/kataras/iris/blob/main/mvc/mvc.go>
- <https://github.com/kataras/iris/blob/main/mvc/controller_method_parser.go>
- <https://github.com/kataras/iris/blob/main/hero/container.go>
- <https://github.com/kataras/iris/tree/main/_examples/mvc>
- <https://github.com/kataras/iris/tree/main/_examples/dependency-injection>
