## Introduction

Go Module 是 Go 1.11（2018）引入的依赖管理单元，终结了 `$GOPATH` 时代。一个 module 由根目录的 `go.mod` 声明，包含其依赖的精确版本与校验。`go` 命令通过 **最小版本选择（MVS）** 决定每个依赖最终采用的版本。

## go.mod Directives

```
module github.com/you/app        // 模块路径（也是包导入前缀）
go 1.22                          // 语言版本（影响语法与标准库行为）
require (                        // 直接 / 间接依赖
    github.com/foo/bar v1.3.0
    golang.org/x/sync v0.7.0
)
replace github.com/foo/bar => ./local-fork   // 重定向（本地调试 / 换源）
exclude github.com/foo/bar v1.2.0            // 排除某版本
retract v1.4.0                                // 声明某版本已撤回（Go 1.16+）
```

- `go` 指令设定本模块使用的语言版本；标准库行为随其变化（如 `errors.Join` 需要 `go 1.20`）。
- `replace` / `exclude` 只影响当前 module 的构建，不传递给依赖方。

## Semantic Versioning and v2+ Import Paths

- 版本号 `vMAJOR.MINOR.PATCH` 遵循 SemVer；`v0.x` / `v1.x` 不保证向后兼容，`v2+` 必须且应当兼容前序次版本。
- **v2 及以上**必须在模块路径末尾带 `/vN`（如 `module github.com/you/app/v2`），否则会与 v1 视为同一模块冲突——这是 Go 处理不兼容大版本的机制。

## Pseudo-version

当依赖某个尚未打 tag 的提交时，Go 用伪版本表达：

```
vX.Y.Z-pre.0.YYYYMMDDHHMMSS-abcdef123456   // 基于某个 prerelease 之后
vX.Y.Z-0.YYYYMMDDHHMMSS-abcdef123456       // 基于某次普通提交
vX.0.0-YYYYMMDDHHMMSS-abcdef123456         // 该模块从未打过任何 tag
```

格式固定为 `基础版本-时间戳-提交短哈希`，保证可排序、可复现。

## go.sum and Verification

`go.sum` 记录每个依赖模块（及其 `go.mod`）的加密哈希，工具链在下载后校验，防止中间篡改。`go mod verify` 可离线复核已下载模块的完整性。`GOPROXY`（默认 `proxy.golang.org`）、`GOSUMDB`、`GOPRIVATE`（跳过私有模块校验）控制拉取与校验来源。

## Common Commands

| 命令 | 作用 |
|------|------|
| `go mod tidy` | 增删依赖，使 `go.mod` / `go.sum` 与代码实际 import 一致 |
| `go mod download` | 下载依赖到模块缓存 |
| `go mod graph` | 输出依赖关系图（排查冲突） |
| `go mod vendor` | 把依赖拷贝进 `vendor/`，配合 `-mod=vendor` 离线构建 |
| `go list -m all` | 列出当前解析到的全部模块版本 |

## vendor and workspace

- `vendor/`：把依赖固化进仓库，适合离线 / 可复现构建；CI 常用 `-mod=vendor`。
- **Workspace**（Go 1.18+，`go.work`）：在本地同时开发多个相互依赖的 module，无需为每个都改 `replace`。

## Minimal Version Selection (MVS)

构建时，Go 搜集所有 `require` 中声明的版本，对每个依赖取**能满足所有约束的最大值**（而非最新版）。这保证：升级一个依赖不会悄悄把另一个依赖也拉到更新的（可能不兼容的）版本。因此 `go.mod` 里写的是"下限"，实际版本由 MVS 计算。

## Links

- [Go 语言总览（Config）](/docs/CS/Go/Go.md)
- [编译过程](/docs/CS/Go/compile.md)
- [Packaging](/docs/CS/Python/Packaging.md)

## References

1. [Go Modules Reference](https://go.dev/ref/mod)
1. [Using Go Modules](https://go.dev/blog/using-go-modules)
1. [Minimal version selection](https://research.swtch.com/vgo-mvs)
