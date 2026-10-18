## Introduction

Higress 的插件开发以 Go 为主路径（`wasm-go` SDK 封装了 higress-group 自己维护的 proxy-wasm-go-sdk）。这一页只收**能照着写的准确名字**：钩子函数的真实 API 名、外部调用的寻址方式、以及 Go 1.24 编译换代带来的三处改动。插件体系、作用域与优先级不在这里，见 [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)。

## SDK Surface

`wrapper.SetCtx(pluginName, ...)` 可挂的选项，全部取自 [Go SDK 与处理流程](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm16/)与 [使用 GO 语言开发 WASM 插件](https://higress.ai/docs/latest/user/wasm-go/)的原文：

| 选项函数 | 回调签名 | 用途 |
| --- | --- | --- |
| `wrapper.ParseConfigBy(parseConfig)` | `func(json gjson.Result, cfg *PluginConfig, log) error` | 全局与各级配置结构相同 |
| `wrapper.ParseOverrideConfigBy(parseConfig, parseRuleConfig)` | 第二个回调 `func(json gjson.Result, global PluginConfig, cfg *PluginConfig, log) error` | 全局与路由/域名/服务级**结构不同**时用（basic-auth 即典型：`defaultConfig` 放 `consumers`，`matchRules.config` 放 `allow`） |
| `wrapper.ProcessRequestHeadersBy` | `onHttpRequestHeaders(ctx, config, log) types.Action` | 请求头 |
| `wrapper.ProcessRequestBodyBy` | `onHttpRequestBody` | 请求体（缓冲） |
| `wrapper.ProcessStreamingRequestBodyBy` | `onHttpStreamingRequestBody` | 流式请求体 |
| `wrapper.ProcessResponseHeadersBy` / `ProcessResponseBodyBy` | `onHttpResponseHeaders` / `onHttpResponseBody` | 响应侧 |
| `wrapper.ProcessStreamingResponseBodyBy` | `onHttpStreamingResponseBody` | 流式响应体，SSE 在途处理靠它 |
| `wrapper.ProcessStreamDoneBy(onHttpStreamDone)` | — | 流式 / 请求结束回调 |

> [!WARNING]
> **`ProcessStreamDone` 与 `ProcessStreamDoneBy` 两个名字都真实存在**，用途不同：`*By` 系列是文档 Go SDK 原理页给出的形态（配 `ParseConfigBy` / `ProcessRequestBodyBy` 一起用），而**主仓自带的 MCP 插件走的是不带 `By` 的 `wrapper.ProcessStreamDone(onHttpStreamDone)`**（`plugins/wasm-go/pkg/mcp/server/plugin.go:910`）。`wrapper` 包来自外部模块 `github.com/higress-group/wasm-go`（不在本仓 `plugins/wasm-go/pkg/` 下，那里只有 `mcp` 与 `pathutil`），因此本机无法枚举它的全部导出项——**照抄文档示例时以 `*By` 系列为准，读主仓插件源码时会看到两种写法混用**。另注意文档示例里有一处 `wrappper.ProcessStreamDoneBy`（三个 p）是**页面笔误**。

最小可编译骨架，注意 Go 1.24 形态下 `main()` 是空的、注册在 `init()`：

```go
package main

import (
  "github.com/higress-group/wasm-go/pkg/wrapper"
  logs "github.com/higress-group/wasm-go/pkg/log"
  "github.com/higress-group/proxy-wasm-go-sdk/proxywasm"
  "github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
  "github.com/tidwall/gjson"
)

func main() {}

func init() {
  wrapper.SetCtx(
    "my-plugin",
    wrapper.ParseConfigBy(parseConfig),
    wrapper.ProcessRequestHeadersBy(onHttpRequestHeaders),
  )
}

type MyConfig struct{ mockEnable bool }

func parseConfig(json gjson.Result, config *MyConfig, log logs.Log) error {
  config.mockEnable = json.Get("mockEnable").Bool()
  return nil
}

func onHttpRequestHeaders(ctx wrapper.HttpContext, config MyConfig, log logs.Log) types.Action {
  proxywasm.AddHttpRequestHeader("hello", "world")
  if config.mockEnable {
    proxywasm.SendHttpResponse(200, nil, []byte("hello world"), -1)
  }
  return types.HeaderContinue
}
```

依赖与代理：`go get github.com/higress-group/proxy-wasm-go-sdk@go-1.24`、`go get github.com/higress-group/wasm-go@main`、`github.com/tidwall/gjson`；国内可 `go env -w GOPROXY=https://proxy.golang.com.cn,direct`。控制台下发的 YAML 会**自动转成 JSON**，`parseConfig` 直接按 JSON 解析。

SDK 帮你做的三件自动行为：注册了 body / streaming 回调才会置 `needRequestBody` / `needResponseBody`；请求 `content-type` 为 octet-stream、grpc 或带 `content-encoding` 时**跳过 body 处理**；没注册 body 回调时 `OnHttpRequestBody` 直接 `ActionContinue`。上下文分三层：`CommonVmCtx`（`SetCtx` 创建，内部 `proxywasm.SetVMContext`）→ `CommonPluginCtx`（`OnPluginStart` 里取插件配置并 `ParseRuleConfig`）→ `CommonHttpCtx`（`NewHttpContext`，`OnHttpRequestHeaders` 里 `GetMatchConfig` 取当前请求生效配置）。

常用工具方法：`GetHttpRequestHeader(s)`、`Add`/`Remove`/`ReplaceHttpRequestHeader(s)`、`Get`/`Append`/`Prepend`/`ReplaceHttpRequestBody`（响应侧同名）、`DispatchHttpCall`、`GetHttpCallResponseHeaders/Body/Trailers`、`SendHttpResponse`、`SendHttpResponseWithDetail`、`ResumeHttpRequest` / `ResumeHttpResponse`。

## Compile Generation Shift

编译方案已经换过一次代，两页文档分属不同时间层，引用时必须分清。Go SDK 原理页仍按 TinyGo 叙述（Proxy-Wasm Go SDK 依赖 TinyGo，理由是当时官方 Go 编译器不适合出 wasm，页面列了 golang/go issues 25612 / 31105 / 38248）；而 wasm-go 页的注意块原话是：

> go 1.24 已经原生支持编译 wasm 文件，目前 higress 已从之前的 tinygo 0.29 + go 1.20 编译方案完整迁移为 go 1.24 原生编译 wasm 文件，Higress 版本需要 >= 2.1.4。

当前命令：

```bash
go mod tidy && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o main.wasm ./
```

这条在源码里能直接对上：**主仓的插件构建用的就是同一行**（`plugins/wasm-go/Makefile:68`，`GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o ./main.wasm .`），该模块 `go.mod:3` 要求 `go 1.24.1`，`grep tinygo` 在 `plugins/wasm-go/Makefile` 中零命中，SDK 依赖 pin 在 `github.com/higress-group/proxy-wasm-go-sdk v0.0.0-20250611100342-...`（`plugins/wasm-go/go.mod:7`）。旧写法 `tinygo build -o plugin.wasm -scheduler=none -target=wasi ...` 已不是当前口径。

迁移带来三处必须改的代码，这是老插件升级时的清单：① 初始化逻辑从 `main()` 挪到 `init()`；② Header 阶段需要暂停等待外部回调时，`types.ActionPause` 要改成 **`types.HeaderStopAllIterationAndWatermark`**（官方注明"0.2.1 ABI 中的 `types.ActionPause` 实际上对应就是这个状态"）；③ `go-re2` 换回官方 `regexp`。

Header 阶段的三个状态语义要分清，选错会丢包：`HeaderContinue` 正常继续；`HeaderStopIteration` 暂停后续 header 迭代但**允许 body 继续缓冲**；`HeaderStopAllIterationAndBuffer` 停掉整个迭代、body 继续缓冲（**超过缓冲上限会丢包**）。暂停后必须显式恢复：`proxywasm.ResumeHttpRequest()` / `ResumeHttpResponse()`，或直接用 `SendHttpResponseWithDetail()` 回响应。

## Cluster Addressing

**外部调用按 Envoy cluster 名寻址，不是任意 URL**。这意味着被调用的服务必须先出现在 Higress 的服务发现里（McpBridge 或 K8s Service），SDK 才能按名字把它包装成 cluster——"插件里 Post 一个公网 URL 却总是连不上"通常是这个原因。`Cluster` 接口两个方法：`ClusterName()`（Envoy 集群名）与 `HostName()`（HTTP 调用时的 host / authority 头）。

| 构造函数 | 生成的 cluster 名 |
| --- | --- |
| `FQDNCluster{FQDN, Host, Port}` | `outbound|<Port>||<FQDN>`，FQDN 如 `foo.default.svc.cluster.local`、`my-cluster.static` |
| `RouteCluster{Host}` | 直接取 `proxywasm.GetProperty([]string{"cluster_name"})`，即当前路由的目标服务 |
| `StaticIpCluster` | `outbound|<port>||<service_name>.static` |
| `DnsCluster` | `outbound|<Port>||<ServiceName>.dns` |
| `K8sCluster` | `outbound|<Port>|<Version>|<ServiceName>.<Namespace>.svc.cluster.local` |
| `NacosCluster` | `outbound|<Port>|<Version>|<ServiceName>.<Group>.<NamespaceID>.nacos` |
| `ConsulCluster` | `outbound|<Port>||<ServiceName>.<Datacenter>.consul` |

HTTP 侧 `wrapper.HttpClient` 的方法集是 `Get/Head/Options/Post/Put/Patch/Delete/Connect/Trace/Call`，签名统一为 `method, rawURL string, headers [][2]string, [body []byte,] cb ResponseCallback, timeoutMillisecond ...uint32`；回调 `func ResponseCallback(statusCode int, responseHeaders http.Header, responseBody []byte)`。构造与调用：

```go
config.client = wrapper.NewClusterClient(wrapper.FQDNCluster{FQDN: "ext-auth.default.svc.cluster.local", Port: 8080})
// 底层收敛到 HttpCall() -> proxywasm.DispatchHttpCall(cluster.ClusterName(), ...)
```

三个已知行为要提前知道：**`HttpCall` 默认超时 500ms**（比直觉短得多，外部鉴权服务稍慢就会失败）；headers 参数里用户塞的 `:method` / `:path` / `:authority` **会被 SDK 静默剔除**；URL 的 host 会覆盖 `cluster.HostName()` 作为 authority；非 2xx 时 code 默认 `http.StatusBadGateway`。

Redis 侧**必须先初始化再调用**：`wrapper.NewRedisClusterClient(wrapper.FQDNCluster{...})` 之后要 `client.Init(username, password string, timeout int64) error`（内部走 `proxywasm.RedisInit(cluster.ClusterName(), ...)`）。命令接口含 `Eval(script, numkeys, keys, args, callback)` 与 `Del` / `Exists` / `Expire` / `Persist` 等，底层是 `RedisCall(cluster, respQuery []byte, callback)`；官方示例即用 `Eval` 实现令牌桶集群限流。这也是 `cluster-key-rate-limit` 这类有状态插件的实现基础。

## Wasm Runtime Model

数据面为什么是"沙箱隔离 + 内存安全"，答案在 VM 模型里：Wasm VM 是加载 Wasm 程序的实例，**在 Envoy 中通常每个工作线程创建一个、相互隔离**，Wasm 程序被复制进各线程执行。规范允许一个 VM 内配置多个插件，**完全相同 `vm_config` 的多个插件共享同一个 VM**（要求 `vm_config.vm_id`、`runtime`、`configuration`、`code` 全部相同），从而省内存、降启动延迟。`vm_config` 字段：`vm_id`（跨 VM 通信的语义隔离）、`runtime`（默认 `envoy.wasm.runtime.v8`，可选 `null` / `v8` / `wamr` / `wasmtime`）、`configuration`（VM 级配置）、`code`（wasm 二进制位置）；此外还有插件实例级 `configuration`。

Envoy 侧的插件类型有三种，Higress 网关逻辑用的是第一种：Http Filter（`envoy.filters.http.wasm`，处理 HTTP）、Network Filter（`envoy.filters.network.wasm`，处理 TCP）、Wasm Service（`envoy.bootstrap.wasm`，`singleton: true` 时在主线程跑单例 VM，适合指标与日志聚合这类不该阻塞工作线程的活）。

## Unverified

四项本次**核不到一手出处**，不要写成事实：Rust / JS SDK 的现状与 API 名（文档站在 `user/plugins/**` 与 `llms.txt` 索引里没有对应页面，本次只核实到 Go 路径）；`wasm-image-spec` 第 4 节镜像构建用的具体 CLI 工具名；`hgctl plugin` 子命令组的二级动作（只核实到存在这一节标题）；以及 wasm17 示例在发起外部调用后**确切返回哪个 Action**——该页可见代码只印出 `types.ActionContinue`，暂停 / 恢复的权威表述在 wasm-go 页，引用要引后者。

## Links

- [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)
- [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)

## References

- [使用 GO 语言开发 WASM 插件](https://higress.ai/docs/latest/user/wasm-go/)
- [Higress 插件 Go SDK 与处理流程](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm16/)
- [HTTP 调用](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm17/)
- [Redis 调用](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm18/)
- [Wasm 插件原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm15/)
- [自定义插件](https://higress.ai/docs/latest/user/plugins/custom/)
