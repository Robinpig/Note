# Config

本册讲 Kratos 的配置抽象（`config` 包）。它解决的是「一份应用配置，可能来自本地文件、环境变量、Apollo、Nacos、K8s ConfigMap，且要支持热更新」这个问题——做法是定义极小的 `Source` / `Watcher` 接口，把配置中心的适配全部外置到 `contrib/config/`。

## Core Interfaces

```go
type KeyValue struct {
	Key    string
	Value  []byte
	Format string
}

type Source interface {
	Load() ([]*KeyValue, error)
	Watch() (Watcher, error)
}

type Watcher interface {
	Next() ([]*KeyValue, error)
	Stop() error
}

type Config interface {
	Load() error
	Scan(v any) error
	Value(key string) Value
	Watch(key string, o Observer) error
	Close() error
}
```

设计要点：

- **`Source` 是拉（`Load`）与推（`Watch`）两件事**。一个 Source 必须同时实现两者——不支持热更新的源（如 env）用一个 `Next()` 直接阻塞到 `Stop()` 的空 Watcher 顶上。
- **`KeyValue.Format` 决定怎么反序列化**。带 format 的走 `encoding.GetCodec(Format)`；不带 format 的按 `aaa.bbb` 展开成嵌套 map，叶子值是 `[]byte`。这就是为什么 file Source 会把扩展名当作 format。
- **`Config.Watch(key, observer)` 是键级的**，不是全局回调：`Observer = func(string, Value)`。

## Load Pipeline

```go
func (c *config) Load() error {
	for _, src := range c.opts.sources {
		kvs, err := src.Load()
		...
		if err = c.reader.Merge(kvs...); err != nil {
			return err
		}
		w, err := src.Watch()
		...
		c.watchers = append(c.watchers, w)
		go c.watch(w)
	}
	if err := c.reader.Resolve(); err != nil {
		return err
	}
	return nil
}
```

顺序是：逐个 Source `Load` → 立刻 `Merge` → 启动该 Source 的 watch goroutine → 全部处理完后**统一做一次 `Resolve()`**。

**多源覆盖顺序就是 `WithSource` 的传参顺序**：后加载的 Source 同名 key 覆盖先前的。约定俗成的写法是 `file` 在前、`env` 在后——让环境变量能覆盖本地文件。

> [!WARNING]
>
> `Resolve()` 只在 `Load()` 末尾执行一次，但 watch 循环里每次热更新也会 Merge 后再 Resolve。这意味着占位符在热重载时会被重新求值，而**求值所用的上下文是当时的全量配置**——如果占位符指向的值本身也在变，结果可能出乎意料。

## Merge Semantics

`defaultMerge` 递归合并两个 map：

- map 与 map → 继续递归；
- 其它类型（含 **slice**）→ **直接整体替换**。

slice 整体替换这一点容易踩：想给 `server.middlewares` 追加一项，在另一个 Source 里覆盖时必须写全整个列表，写单项会直接替换掉原列表。

## Resolver

`defaultResolver`（`config/options.go`）递归替换字符串、map、slice 里的 `${key:default}` 占位符：

- key 支持点路径；
- 找不到且没给 default → 替换成空字符串；
- 给了 default → 用 default。

```yaml
data:
  database:
    dsn: "root:${DB_PASSWORD:123456}@tcp(127.0.0.1:3306)/test"
```

默认 resolver 保留**字符串类型**。`WithResolveActualTypes(true)` 可以把完整占位的结果转成 `bool` / `float64` / `int64` 或带引号字符串——需要 typed 输出时才开。

## Value Interface

```go
type Value interface {
	Bool() (bool, error)
	Int() (int64, error)
	Float() (float64, error)
	String() (string, error)
	Duration() (time.Duration, error)
	Slice() ([]Value, error)
	Map() (map[string]Value, error)
	Scan(any) error
	Load() any
	Store(any)
}
```

`Config.Value(key)` 返回的就是它。两个行为要留意：

> [!WARNING]
>
> **`Duration()` 不是 `time.ParseDuration`**，它先 `Int()` 再直接转成 `time.Duration`（纳秒）。所以配置文件里必须写纳秒整数，写 `"1s"` 这种字符串会失败——这是 Kratos 特有的坑。
>
> 找不到 key 时 `Config.Value` 返回 `&errValue{err: ErrNotFound}`，而不是 nil。所以判断是否存在的正确写法是调用其方法拿 error，而不是判 nil。

`Scan` 的行为按目标类型分叉：普通结构体走 `encoding/json`；目标是 `proto.Message` 时走 `protojson` 且 `DiscardUnknown=true`。后者正是 `layout` 里 `internal/conf/conf.pb.go` 能被 `c.Scan(&bc)` 直接填充的原因。

v3.0.0 新增了泛型便捷 API（`feat(config): add generic config Get support`，#3778）：

```go
// Get retrieves a config value by key and scans it into the target type.
func Get[T any](c Config, key string) (T, error)
```

内部对 `bool` / `int64` / `int` / `float64` / `string` 走了特化分支，其它类型退化为 `v.Scan(&t)`。

## Built-in Sources

### file

```go
c := config.New(config.WithSource(file.NewSource("configs/config.yaml")))
```

支持单文件或单层目录。**加载目录时忽略子目录与隐藏文件**，`Format` 取文件扩展名。Watcher 基于 `fsnotify v1.10.1`。

### env

```go
c := config.New(config.WithSource(env.NewSource("KRATOS_")))
```

遍历 `os.Environ()` 匹配前缀，去除前缀及紧随的一个 `_`。

> [!WARNING]
>
> env Source **不会把 `_` 自动转成 `.`**——`KRATOS_DATA_DATABASE_DSN` 会变成 key `DATA_DATABASE_DSN` 而不是 `data.database.dsn`。想要嵌套结构，得自己在其基础上再加工。另外 env 的 watcher 不轮询，`Next()` 会一直阻塞到 `Stop()`，环境变量的热更新**根本不支持**。

## Contrib Sources

配置中心适配全部在 `contrib/config/` 下，共 6 个：

| 子模块 | 关键依赖 |
| :-- | :-- |
| `apollo` | `github.com/apolloconfig/agollo/v4 v4.4.0` |
| `consul` | `github.com/hashicorp/consul/api v1.34.2` |
| `etcd` | `go.etcd.io/etcd/client/v3 v3.6.11` |
| `kubernetes` | `k8s.io/api` / `client-go` v0.36.1 |
| `nacos` | **`nacos-sdk-go v1.1.6`（v1）** |
| `polaris` | `github.com/polarismesh/polaris-go v1.7.0` |

> [!NOTE]
>
> 一个版本错配值得留意：**`contrib/config/nacos` 用的是 `nacos-sdk-go` v1，而 `contrib/registry/nacos` 用的是 v2（`nacos-sdk-go/v2 v2.3.5`）**。同一个进程里同时用 Nacos 做配置源和注册中心时，两套 SDK 会并存。这是历史遗留，升级时别把它们当同一个依赖处理。

## Hot Reload

热更新的完整链路（`config.watch`）：

1. goroutine 循环 `w.Next()`；
2. 出错时：若为 `context.Canceled` 则退出，否则**sleep 1 秒继续**；
3. 成功则 `reader.Merge(kvs...)` → `reader.Resolve()`；
4. 遍历 `cached` 里已取过的 key，逐一取新值，**仅当新旧值的 `reflect.Type` 相同且 `!reflect.DeepEqual` 时**才 `Store` 并触发对应 observer。

```go
if n, ok := c.reader.Value(k); ok &&
	reflect.TypeOf(n.Load()) == reflect.TypeOf(v.Load()) &&
	!reflect.DeepEqual(n.Load(), v.Load()) {
	v.Store(n.Load())
	if o, ok := c.observers.Load(k); ok {
		o.(Observer)(k, v)
	}
}
```

第 4 步的**类型相同**条件很重要：如果你 `Watch` 了某个 key 但从未 `Value()` 过，它就不在 `cached` 里，也就收不到通知；反之如果热更新后类型变了（比如从 int 变成 string），改动会被**静默忽略**。

另外 `Config.Watch(key, o)` 自身的语义：它会先 `c.Value(key)`，**若 `Load()` 返回 nil 则直接返回 `ErrNotFound`**，也就是 Watch 一个当前不存在的 key 会失败而不是静默等待。

## Encoding Registry

Codec 的选择由 `encoding` 包的全局注册表决定：

| Codec | MIME（`application/<name>`） | 实现 |
| :-- | :-- | :-- |
| `form` | `application/x-www-form-urlencoded` | `go-playground/form/v4 v4.3.0` |
| `json` | `application/json` | 标准库 `encoding/json` |
| `proto` | `application/proto` | protobuf 二进制 |
| `protojson` | `application/protojson` | `protojson`（要求 `proto.Message`） |
| `xml` | `application/xml` | 标准库 `encoding/xml` |
| `yaml` | `application/yaml` | `gopkg.in/yaml.v3 v3.0.1` |

```go
// RegisterCodec 的行为约束
if codec == nil { panic("cannot register a nil Codec") }
if n := codec.Name(); n == "" { panic("cannot register Codec with empty string result for Name()") }
// 且必须以小写名称注册
```

> [!WARNING]
>
> 各 codec 靠自己包的 `init()` 注册，**只 import 顶层 `encoding` 不会注册任何实现**。`transport` 包空白导入了全部六个，但 `config` 包只导入了 json / proto / xml / yaml——**config 里没有 form 和 protojson**。想在这两处用它们得自己补 import。

`contrib/encoding/` 下还有 `json`（另一种实现）和 `msgpack`（`vmihailenco/msgpack/v5 v5.4.1`）。

## Links

- [Kratos](/docs/CS/Go/Framework/Kratos.md)
- [Architecture](/docs/CS/Go/Framework/Kratos/Architecture.md)
- [Transport_HTTP](/docs/CS/Go/Framework/Kratos/Transport_HTTP.md)
- [Protobuf_and_Codegen](/docs/CS/Go/Framework/Kratos/Protobuf_and_Codegen.md)
- [Apollo](/docs/CS/Framework/Apollo/Apollo.md)

## References

- <https://go-kratos.dev/docs/component/config>
- <https://pkg.go.dev/github.com/go-kratos/kratos/v3/config>
- <https://github.com/fsnotify/fsnotify>
