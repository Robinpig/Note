# Iris Sessions and Authentication

## Introduction

Session 与鉴权是 Iris"全内置"定位的典型体现：Gin 需要引 `gin-contrib/sessions` 与第三方 JWT 库，Iris 直接在仓库里提供 `sessions` 包与 `middleware/jwt`、`middleware/basicauth`，并且 Session 还能直接作为 `hero` 容器的内建依赖注入到 handler。

本文基于 tag **v12.2.11**。

## Sessions

### Setup

```go
sess := sessions.New(sessions.Config{
    Cookie:  "mysessionid",            // 默认 "irissessionid"（sessions/config.go:10）
    Expires: 24 * time.Hour,
    AllowReclaim: true,                // 允许同一请求内 Destroy 后再 Start
    CookieSecureTLS: true,             // TLS 下置 Secure
})
app.Use(sess.Handler())                // sessions/sessions.go:182
```

`sessions.Config`（`sessions/config.go`）主要字段：`Logger`、`Cookie`、`CookieSecureTLS`、`AllowReclaim`、`Expires`、`Encoding`、`DisableSubdomainPersistence` 等。

### Session manager API

| 方法 | 行号 | 说明 |
| :-- | :-- | :-- |
| `New(cfg Config) *Sessions` | `sessions.go:30` | 构造管理器 |
| `UseDatabase(db Database)` | `:54` | 挂载持久化后端 |
| `Handler(requestOptions ...context.CookieOption) context.Handler` | `:182` | 中间件 |
| `Start(ctx, cookieOptions ...) *Session` | `:133` | 取（或建）会话 |
| `StartWithPath(ctx, path)` | `:214` | 指定 cookie path |
| `Get(ctx) *Session` | `:202` | 取已存在的会话，不新建 |
| `Destroy(ctx)` | `:263` | 销毁当前会话 |
| `DestroyByID(sid)` / `DestroyAll()` | `:283` / `:290` | 按 ID / 全部销毁 |
| `ShiftExpiration(ctx)` / `UpdateExpiration(ctx, d)` | `:221` / `:229` | 续期 |
| `OnDestroy(listeners ...DestroyListener)` | `:252` | 销毁回调 |

### Session values

```go
func login(ctx iris.Context) {
    s := sess.Start(ctx)
    s.Set("user", "makis")                    // session.go:526
    s.SetImmutable("uid", 42)                 // :536，写入后不再被后续修改覆盖

    name := s.GetString("user")               // :134
    uid  := s.GetIntDefault("uid", 0)         // :257
    s.Delete("user")                          // :572
}
```

取值家族（均在 `sessions/session.go`）：`Get`:62、`GetString`:134、`GetInt`:231、`GetInt64`:286、`GetUint64`:321、`GetFloat32/64`:361/:403、`GetBoolean`:441、`GetAll`:488，每个都有 `...Default` 变体。

**Flash message**（一次性消息，读后即销）：`SetFlash`:560、`GetFlash`:100、`GetFlashString`:164、`GetFlashes`:500、`DeleteFlash`:578。

### Persistence backends

`sessions/sessiondb/` 下只有三个后端：

| 包 | 底层 |
| :-- | :-- |
| `sessiondb/badger` | dgraph-io/badger |
| `sessiondb/boltdb` | `go.etcd.io/bbolt`（包内 import 名为 `bolt`） |
| `sessiondb/redis` | `github.com/redis/go-redis/v9` |

```go
db, _ := redis.New(redis.Config{Addr: "127.0.0.1:6379"})
sess.UseDatabase(db)
```

> [!WARNING]
>
> v12.2.11 的 `sessiondb/` 里**没有** `bbolt` 独立包（只有 `boltdb`，内部就是 bbolt），也**没有** leveldb。网上一些旧文档列的后端清单已过时。

### Session as a hero dependency

`*sessions.Session` 是 `hero` 的内建依赖之一，因此 mvc/hero handler 可直接声明：

```go
func dashboard(ctx iris.Context, s *sessions.Session) {
    user := s.GetString("user")
    ctx.WriteString("hello " + user)
}
```

## JWT

`middleware/jwt` 是 `github.com/kataras/jwt` 的封装（v12.2.11 依赖 `kataras/jwt` v0.1.12）。

### Signing

```go
signer := jwt.NewSigner(jwt.HS256, []byte("secret"), 15*time.Minute)  // signer.go:36
token, err := signer.Sign(claims)                                     // :69

// 双 token（access + refresh）
pair, err := signer.NewTokenPair(accessClaims, refreshClaims, 24*time.Hour)  // :82
```

可选：`WithEncryption(key, additionalData)`（`:58`）对载荷再加密。算法常量从 `kataras/jwt` 别名而来（`aliases.go:24` 起：`HS256`、`RS256`、`ES256`…）。

### Verifying

```go
verifier := jwt.NewVerifier(jwt.HS256, []byte("secret"))   // verifier.go:89
verifier.WithDefaultBlocklist()                            // :122，启用默认黑名单
verifier.WithDecryption(key, aad)                          // :109，配合 WithEncryption

app.Get("/protected", verifier.Verify(func() interface{} {
    return new(myClaims)                                   // :186，claims 工厂
}), protectedHandler)

// handler 内取 claims
claims := jwt.Get(ctx)                                     // :18
vt := jwt.GetVerifiedToken(ctx)                            // :29
```

其它能力：

- token 提取器（`extractor.go`）：`FromHeader`:17、`FromQuery`:34、`FromJSON(jsonKey)`:42。
- 校验器：`jwt.Expected`（`aliases.go:65`，实现 `TokenValidator`）做 issuer/audience 等简单校验；`jwt.TokenValidator` 是接口别名。
- 黑名单：`Blocklist` 接口（`blocklist.go:15`），内存默认实现 + `blocklist/redis` 实现，用于登出后使 token 失效。
- 解密与签名分离：`VerifyToken(token []byte, validators...) (*VerifiedToken, error)`（`:165`）可手工校验任意 token。

## Basic Authentication

```go
// middleware/basicauth/basicauth.go:191
func New(opts Options) context.Handler
```

`Options`（`:58`）字段：`Realm`、`Proxy`、`HTTPSOnly`、`Allow`（唯一必填，`AuthFunc`）、`MaxAge`、`MaxTries`、`MaxTriesCookie`、`MaxTriesSession`、`ErrorHandler`、`GC`。

```go
app.Use(basicauth.New(basicauth.Options{
    Realm: basicauth.DefaultRealm,
    Allow: basicauth.AllowUsers(iris.Map{"admin": "p@ss"}, false),  // 第二参为 BCRYPT
}))
```

内置 `Allow` 实现：`AllowUsers(map, bcrypt bool)`、`AllowUsersFile("users.yml", bcrypt)`（`:58` 注释）；自定义时实现 `AuthFunc`，可查库并返回 user 对象。`MaxTries` 配合 `MaxTriesCookie`（默认 `"basicmaxtries"`）或 `MaxTriesSession`（需已注册 session）实现失败次数限制；`GC: basicauth.GC{Every: 2 * time.Hour}` 清理过期凭据缓存。

## Choosing an Approach

| 场景 | 建议 |
| :-- | :-- |
| 传统服务端渲染页面、需要登录态 | `sessions` + 后端（redis） |
| 前后端分离 API | `middleware/jwt`（signer + verifier + blocklist） |
| 内网工具、简单保护 | `middleware/basicauth`（配 `HTTPSOnly`） |
| 需要 OAuth2 / 细粒度 RBAC | Iris 无内置，需外接（如 `goth`、`casbin`） |

## Links

- [Iris](/docs/CS/Go/Framework/Iris.md)
- [Iris Middleware](/docs/CS/Go/Framework/Iris/Middleware.md)
- [Iris MVC and Dependency Injection](/docs/CS/Go/Framework/Iris/MVC_and_Dependency_Injection.md)
- [Iris Extensions](/docs/CS/Go/Framework/Iris/Extensions.md)
- [Iris Rendering](/docs/CS/Go/Framework/Iris/Rendering.md)

## References

- <https://github.com/kataras/iris/blob/main/sessions/sessions.go>
- <https://github.com/kataras/iris/blob/main/middleware/jwt/verifier.go>
- <https://github.com/kataras/iris/blob/main/middleware/basicauth/basicauth.go>
- <https://github.com/kataras/jwt>
- <https://github.com/kataras/iris/tree/main/_examples/auth>
