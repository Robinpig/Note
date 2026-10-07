## Introduction

`io` 包定义了一组极简、可组合的 I/O 原语接口，是 Go 标准库的基石：`net/http`、`os.File`、`bytes.Buffer`、压缩 / 编码包全都围绕 `io.Reader` / `io.Writer` 构建。掌握这几个接口与它们的装饰器（adapter），就能以"流"的方式零拷贝地拼接任意数据源与目的地。

## Core Interface

```go
type Reader interface { Read(p []byte) (n int, err error) }
type Writer interface { Write(p []byte) (n int, err error) }
type Closer interface { Close() error }
type Seeker interface { Seek(offset int64, whence int) (int64, error) }
```

- 组合接口也存在：`ReadWriter` = `Reader + Writer`、`ReadCloser`、`ReadWriteCloser`、`ReadSeeker` 等。
- `Read` 契约：把数据填入 `p`，返回读到的字节数 `n`；`n < len(p)` 时**未必**是 EOF；只有在**没有更多数据**时才返回 `n == 0, err == io.EOF`。调用方必须循环调用 `Read` 直到 `io.EOF`。
- `Write` 契约：尽量写完全部 `p`，返回已写字节数；若 `n < len(p)` 必须返回非-nil 错误。

## io.EOF

`io.EOF` 是哨兵错误，表示"流已到末尾"，**不是异常**——正常读取循环以它作为结束信号，不应当作错误去中断流程。

## io.Copy and Full Read

- `io.Copy(dst Writer, src Reader)` 内部循环 `Read` / `Write`，并对实现了 `io.ReaderFrom` / `io.WriterTo` 的类型走快捷路径（如 `*os.File`、`*bytes.Buffer` 可零拷贝搬运）。
- `io.CopyBuffer` 允许传入复用缓冲区；`io.CopyN` 只搬前 N 字节。
- `io.ReadAll(r)` 一次性读完整个流到 `[]byte`；`io.ReadFull` 精确读取指定长度。

## Decorator (Composing Streams Without Allocation)

| 适配器 | 作用 |
|--------|------|
| `io.TeeReader(r, w)` | 从 `r` 读的同时把数据镜像写给 `w`（不消费 `r`） |
| `io.MultiReader(rs...)` | 把多个 `Reader` 首尾拼接成一个 |
| `io.MultiWriter(ws...)` | 一次写同时 fan-out 到多个 `Writer` |
| `io.LimitReader(r, n)` | 把 `r` 截断到最多 `n` 字节 |
| `io.SectionReader(r, off, n)` | 取 `r` 的 `[off, off+n)` 子段 |
| `io.Pipe()` | 同步内存管道：`Read` 阻塞直到 `Write` 写入，常用于把"写"适配成"读"（如 HTTP body） |
| `io.Discard` | 永不报错地丢弃所有写入（空 `Writer`） |

这些适配器本身也是 `Reader` / `Writer`，可继续嵌套，无需中间分配。

## Boundary with bytes.Buffer

`bytes.Buffer` 同时实现 `Reader` 与 `Writer`，但**不是 `Closer`**（没有 `Close`，也不需要关闭）。需要"又读又写的内存缓冲"时用它；把它当作 `Reader` 耗尽后返回 `io.EOF` 而非阻塞。参见 Issues（#79 关闭实现 `io.Closer` 的资源）。

## Links

- [Go 语言总览](/docs/CS/Go/Go.md)
- [Issues：常见错误](/docs/CS/Go/Issues.md)
- [net 网络模型](/docs/CS/Go/net.md)

## References

1. [pkg.go.dev/io](https://pkg.go.dev/io)
1. [Effective Go: io](https://go.dev/doc/effective_go#io)
