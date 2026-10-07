## Introduction

`testing` 包是 Go 自带的测试框架，与 `go test` 命令深度集成，无需第三方依赖即可覆盖单元测试、基准测试与（Go 1.18+）模糊测试。`go test -race` 还能直接复用竞争检测（见 race detector）。

## Basics: *testing.T

- 测试函数签名 `func TestXxx(t *testing.T)`、`BenchmarkXxx(b *testing.B)`、`FuzzXxx(f *testing.F)`（首字母大写、Xxx 为可导出名）。
- `t.Errorf` / `t.Fatalf`：记录失败（Fatal 立即终止本测试）；`t.Log` 输出（仅 `-v` 显示）。
- `t.Helper()`：标记函数为"测试辅助函数"，失败时文件：行定位到调用方而非辅助函数内部。
- `t.Cleanup(f)`（Go 1.14+）：注册退出时的清理回调，多个按 LIFO 执行。

## Table-Driven Tests

Go 社区主流写法：用一组 case 切片 + `t.Run(name, fn)`，每个 case 独立子测试、可单独 `-run`：

```go
tests := []struct{ in, want int }{{1, 2}, {2, 4}}
for _, tt := range tests {
    t.Run(fmt.Sprintf("in=%d", tt.in), func(t *testing.T) {
        if got := Double(tt.in); got != tt.want {
            t.Errorf("got %d want %d", got, tt.want)
        }
    })
}
```

- `t.Parallel()`：标记子测试 / 测试可并行，需在 `t.Run` 内调用，且应放在 setup 完成之后。
- `-shuffle` 可打乱用例顺序，暴露对执行次序的隐式依赖（参见 Issues #84）。

## Benchmarking: *testing.B

```go
func BenchmarkParse(b *testing.B) {
    b.ReportAllocs()       // 报告每次迭代的堆分配
    data := setup()        // 准备数据（不计入计时）
    b.ResetTimer()         // 之后才开始计时
    for i := 0; i < b.N; i++ {
        Parse(data)
    }
}
```

- `b.N` 由框架自动调整直到测量稳定；`-benchmem` 看 allocs/op，`-benchtime`、`-cpu`、`-count` 控制时长 / 核数 / 重复。
- 防止编译器把无副作用的被测代码优化掉（如把结果赋给包级变量 `result`）。

## Fuzz Testing: *testing.F (Go 1.18+)

```go
func FuzzParse(f *testing.F) {
    f.Add("42")                        // 种子语料
    f.Fuzz(func(t *testing.T, in string) {
        Parse(in)                     // 只要求不 panic / 不崩溃
    })
}
```

`go test -fuzz=FuzzParse` 让引擎在种子基础上自动变异输入，发掘越界、panic 等意外行为；发现的失败语料会落盘供复现。

## httptest and Coverage

- `httptest.NewServer` / `NewRecorder` 用于 HTTP handler 的端到端 / 单元验证，避免起真实端口。
- `-cover` / `-coverprofile=cover.out` 收集覆盖率，`go tool cover -func=cover.out -html=cover.out` 可视化。
- `-short` 跳过耗时用例（用例内用 `testing.Short()` 判断）。

## Links

- [竞争检测 race detector](/docs/CS/Go/Concurrency/RaceDetector.md)
- [Go 语言总览](/docs/CS/Go/Go.md)
- [Issues：常见错误](/docs/CS/Go/Issues.md)

## References

1. [testing package](https://pkg.go.dev/testing)
1. [Testing flagged examples](https://go.dev/doc/code#Testing)
1. [Go 1.18 Release Notes（fuzzing）](https://go.dev/doc/go1.18#fuzzing)
