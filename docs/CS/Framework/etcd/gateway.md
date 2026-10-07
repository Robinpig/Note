## Introduction

`etcd` 这个二进制除了启动 server，还带三个与"对外网络"有关的东西。它们的层级、协议、启动方式各不相同，而**最常被搞混的是前两者**：

| 名称 | 层级 | 协议 | 启动方式 | 一句话定位 |
| :--- | :--- | :--- | :--- | :--- |
| `etcd gateway start` | **L4** | 纯 TCP 转发 | 子命令 | TCP 负载均衡器，**不解析任何 etcd 语义** |
| `etcd grpc-proxy start` | **L7** | gRPC | 子命令 | 无状态反向代理，做 watch/lease 合并与 namespace |
| `--enable-grpc-gateway` | **L7** | HTTP/JSON | **server 启动 flag** | gRPC→REST 协议翻译层 |

要打破的两个直觉：

- **`etcd gateway` 是 L4，不是 L7。** 这是 3.7.2 里最容易被旧资料误导的地方。3.5 时代常被理解为"L7 辅助服务"的那个 gateway，在当前代码里已被**重写成纯 TCP 代理**——`server/etcdmain/gateway.go:170` 直接构造 `tcpproxy.TCPProxy`，而 `server/proxy/tcpproxy/doc.go:15` 的包注释写得很明确：`// Package tcpproxy is an OSI level 4 proxy for routing etcd clients to etcd servers.`。它**不做** namespace 隔离、**不做** watch/lease 合并、**不理解**任何 Raft 消息。源码里 `gateway.go:108` 那行注释是作者自己的澄清：`// Strip the schema from the endpoints because we start just a TCP proxy`。
- **`etcd grpc-gateway` 这个子命令已经不存在。** 3.7.2 的 `server/etcdmain/main.go:31` 的 switch 只认两个值——`case "gateway", "grpc-proxy":`，两者都交给同一个 cobra `rootCmd`。REST 网关变成了 etcd server 的启动 **flag** `--enable-grpc-gateway`。按旧资料敲 `etcd grpc-gateway` 会直接报未知命令。

> [!NOTE]
> **版本基线**：全文行号取自 **etcd v3.7.2**（`server/etcdmain/`、`server/proxy/`、`server/embed/`、`cache/`）。三者的代码位置都变过：顶层**没有** `grpc-proxy/` 目录（3.5 时代的独立 Go module 已下线），代码在 `server/proxy/grpcproxy/`；`cache/` 是 3.7 新增的顶层独立 module。核对方式为逐条打开源码确认，结论均附 `文件:行号`。

三者都不是集群成员、不参与 Raft、不持久化数据，挂掉不影响 etcd 集群本身可用性。[etcd.md](/docs/CS/Framework/etcd/etcd.md) 的启动流程只把 server 本身讲完了，这三个入口在这里补全。

## etcd gateway: L4 TCP Proxy

### Commands and Flags

命令注册在 `server/etcdmain/gateway.go`：`newGatewayCommand()`（`:52`，`Use: "gateway <subcommand>"`）→ `newGatewayStartCommand()`（`:62`，`Short: "start the gateway"`），由 `init()`（`:47-49`）挂到 `rootCmd`。唯一子命令是 `start`。

flag 只有 7 个（`gateway.go:69-77`），**没有任何 L7 语义相关的选项**：

| flag | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--listen-addr` | `127.0.0.1:23790` | 监听地址 |
| `--endpoints` | `127.0.0.1:2379` | 后端 etcd 端点，逗号分隔 |
| `--retry-delay` | `1m` | 端点重试间隔（同时是 monitor 周期） |
| `--discovery-srv` | 空 | 用 DNS SRV 记录引导初始端点 |
| `--discovery-srv-name` | 空 | SRV 查询的服务名 |
| `--insecure-discovery` | `false` | 接受不安全 SRV 记录 |
| `--trusted-ca-file` | 空 | 校验发现到的端点时用的 CA |

```bash
etcd gateway start \
  --endpoints=infra0.example.com:2379,infra1.example.com:2379 \
  --listen-addr=0.0.0.0:23790
```

没有 `--namespace`、没有 `--resolver-prefix`——**那些是 grpc-proxy 的 flag，不是 gateway 的**。

### Implementation: Pure TCP Forwarding

`startGateway`（`gateway.go:93-181`）的流程是：DNS 发现端点 → `stripSchema`（`gateway.go:82`）去掉 URL scheme → 把 `host:port` 拼成 `net.SRV` → `net.Listen` → 构造 `tcpproxy.TCPProxy` → `tp.Run()`。核心只有这几行：

```go
// server/etcdmain/gateway.go:170
	tp := tcpproxy.TCPProxy{
		Logger:          lg,
		Listener:        l,
		Endpoints:       srvs.SRVs,
		MonitorInterval: gatewayRetryDelay,
	}

	// At this point, etcd gateway listener is initialized
	notifySystemd(lg)

	tp.Run()
```

`tcpproxy` 包只有两个源文件（`doc.go` + `userspace.go`），实现朴素：`Run()`（`userspace.go:72`）为每个 endpoint 建一个 `remote`（`:28`），起一个 `runMonitor()`（`:196`）定期尝试重新激活失效端点，然后 `Accept` 循环里每来一个连接 `go tp.serve(in)`（`:156`）。`serve` 只做一件事：挑一个活跃 remote，`net.Dial("tcp", remote.addr)`，然后**双向搬运字节**。

`pick()`（`userspace.go:99`）实现了 DNS SRV 的**优先级 + 权重**语义：先按 `srv.Priority` 选最低优先级组，组内按 `srv.Weight` 做加权随机；带权重的记录存在时，权重为 0 的只有约 1% 概率被选中。全部不可用时返回 `nil`，连接直接被关掉。

> [!WARNING]
> **这就是"纯 TCP"的全部含义。** 因为不解析 gRPC 帧，gateway **无法**做 watch 合并、lease 合并、namespace 隔离，也**无法**感知后端是否健康——`pick()` 只能靠 `net.Dial` 成功与否判断存活（`tryReactivate`，`userspace.go:41`，直接 Dial 一次再关掉）。同时它对**所有**流量一视同仁，包括 etcd 自己的 peer 流量（2380）与客户端流量（2379）——虽然实际部署不会这么用，但架构上它并不区分。把 L7 能力指望在它身上是最常见的误判。

## etcd grpc-proxy start: L7 Gateway

### Code Location

**不在顶层 `grpc-proxy/`**——3.7.2 顶层没有这个目录。实际位置是 `server/proxy/grpcproxy/`，属于 `go.etcd.io/etcd/server/v3` module，包注释（`server/proxy/grpcproxy/doc.go:15`）自报家门：`// Package grpcproxy is an OSI level 7 proxy for etcd v3 API requests.`

四项核心能力各对应一批文件：

| 能力 | 文件 |
| :--- | :--- |
| watch 合并 | `watch.go`、`watch_ranges.go`、`watch_broadcast.go`、`watch_broadcasts.go`、`watcher.go`、`adapter/watch_client_adapter.go` |
| lease 合并 | `lease.go`、`adapter/lease_client_adapter.go` |
| key-range 缓存 | `cache/store.go`、`kv.go` |
| 端点发现 / 成员过滤 | `cluster.go`、`leader.go`、`register.go`、`auth.go` |

另有 `election.go`、`lock.go`、`maintenance.go`、`metrics.go`、`health.go`、`util.go` 与 `adapter/` 子包（11 个文件，含 `chan_stream.go` 这个把 client 侧流"拍平"成 channel 的工具）。

命令注册：`newGRPCProxyCommand`（`server/etcdmain/grpc_proxy.go:122`，`Use: "grpc-proxy <subcommand>"`）→ `newGRPCProxyStartCommand`（`grpc_proxy.go:132-188`，`Run: startGRPCProxy`），同样由 `init()`（`grpc_proxy.go:117-119`）挂到 `rootCmd`。

```bash
etcd grpc-proxy start \
  --endpoints=infra0.example.com:2379,infra1.example.com:2379,infra2.example.com:2379 \
  --listen-addr=127.0.0.1:2379
```

客户端此后把请求打给 proxy 的 `--listen-addr`，proxy 转发到后端某一台 etcd。

### Four Capabilities

**1. Scalable watch（watch 合并）**

把多个客户端 watcher（`c-watcher`）在**相同 key/range** 上合并成一个连到 etcd server 的 `s-watcher`，再把事件广播给所有 `c-watcher`（`watch.go` 的 `watchProxy`）。N 个客户端 watch 同一 key，核心集群只需 1 个 watcher。多布几个 proxy 可进一步分摊。

> [!WARNING]
> 合并后的 `s-watcher` 可能因网络延迟或缓冲的未投递事件与 server 不同步。watch revision 未指定时，proxy **不保证** `c-watcher` 从最新 store revision 开始——客户端直连 server 从 revision 1000 开始，经 proxy 可能从 990 开始。取消时也类似：server 的 revision 可能大于取消响应里的 revision。对绝大多数场景无碍，但要求精确 revision 的调用应直连 server 或绕过 proxy。

**2. Scalable lease（lease 流合并）**

N 个客户端的 lease keepalive stream 合并成 1 条到 server 的 `s-stream`（`lease.go` 的 `leaseProxy`）。重 lease 活动下可把核心集群的 stream 数从 N 降到 1。

**3. 防虐待缓存（key-range cache）**

`kv.go` 的 `kvProxy` 在 `Range` 请求里判断 `r.Serializable`（`kv.go:48`）：命中缓存直接返回（`cacheHits`），未命中则打到后端并把结果缓存（`cacheMisses`）。缓存后端是 `cache/store.go` 的 `NewCache(cache.DefaultMaxEntries)`（`kv.go:41`），默认 `DefaultMaxEntries = 2048`。

> [!TIP]
> 缓存只对 **serializable 读**生效，线性读（默认）永远走后端。`kv.go` 里还留着一条 TODO：把响应拷成 shadow copy 以免调用方改到共享对象。

**4. Namespacing（keyspace 隔离）**

`--namespace=my-prefix/` 给所有进 proxy 的请求 key 自动加前缀，响应再剥掉。多个应用共享一个 etcd 集群时，各自像拥有完整 keyspace。

```bash
etcd grpc-proxy start --endpoints=localhost:2379 \
  --listen-addr=127.0.0.1:23790 --namespace=my-prefix/
# 客户端无感：
etcdctl --endpoints=127.0.0.1:23790 put my-key abc   # 集群里实为 my-prefix/my-key
```

### Service Discovery and Observability

proxy 可以把自己注册进 etcd 供客户端发现，机制与 [naming.md](/docs/CS/Framework/etcd/naming.md) 同源（proxy 作为 consumer 去 Watch 一个 prefix）：

```bash
etcd grpc-proxy start --endpoints=localhost:2379 \
  --listen-addr=127.0.0.1:23790 \
  --advertise-client-url=127.0.0.1:23790 \
  --resolver-prefix="___grpc_proxy_endpoint" --resolver-ttl=60
```

没配 `--resolver-prefix` 时，`member list` 只返回它自己的 `advertise-client-url`。

两组 TLS flag 别搞混：`--cert-file` / `--key-file` / `--trusted-ca-file` / `--auto-tls` 是**对客户端**的（`grpc_proxy.go:168-172`），`--cert` / `--key` / `--cacert` 是**对 etcd** 的（`grpc_proxy.go:163-165`）。`--metrics-addr` 起独立接口同时服务 `/health` 与 `/metrics`。

> [!WARNING]
> 主接口同时服务 HTTP/2 与 HTTP/1.1。若按上面例子配了 TLS，用 `curl` 打 `/metrics`、`/health` 时需显式 `--http1.1`，否则协议协商失败拿不到响应。改用 `--metrics-addr` 起的独立接口则无此限制。

### 3.7 New Flags

| flag | 位置 | 作用 |
| :--- | :--- | :--- |
| `--experimental-serializable-ordering` | `grpc_proxy.go:179` | 保证 serializable 读在各 endpoint 上的 store revision 单调递增 |
| `--experimental-leasing-prefix` | `grpc_proxy.go:180` | 断连线性读所用的 leasing 元数据前缀 |
| `--experimental-enable-grpc-logging` | `grpc_proxy.go:181` | 打印所有 gRPC 请求与响应 |
| `--max-send-bytes` | `grpc_proxy.go:155` | 发送消息上限，默认 `defaultGRPCMaxCallSendMsgSize = 1.5 * 1024 * 1024`（`grpc_proxy.go:115`） |
| `--max-recv-bytes` | `grpc_proxy.go:156` | 接收消息上限，默认 `math.MaxInt32` |
| `--data-dir` | `grpc_proxy.go:154` | 默认 `default.proxy` |

前两个带 `experimental` 前缀的选项默认**关闭**，语义随版本变，别写死在运维脚本里当稳定契约。

### Relationship with Cluster Operations

proxy 不参与 Raft、不持有数据，因此**不计入 quorum**，挂掉不影响集群可用性，可随意水平扩缩。但它也是单点：所有经它的客户端请求都收敛到 proxy 选中的那一台 etcd，所以更适合"大量 watch/lease、读多写少"的扇出场景，而非替代多 endpoint 直连。成员变更、配额、备份恢复仍见 [cluster.md](/docs/CS/Framework/etcd/cluster.md)，客户端侧重试与一致性读语义见 [client.md](/docs/CS/Framework/etcd/client.md)。

## grpc-gateway (REST Gateway) Changed to Flag

### Subcommand Form No Longer Exists

3.7.2 的 `server/etcdmain/` 只有 9 个非测试文件（`config.go` / `doc.go` / `etcd.go` / `gateway.go` / `grpc_proxy.go` / `grpc_proxy_logger.go` / `help.go` / `main.go` / `util.go`），**没有** `grpc_gateway.go`。分发逻辑在 `main.go:31`：

```go
// server/etcdmain/main.go:24
	if len(args) > 1 {
		cmd := args[1]
		switch cmd {
		case "gateway", "grpc-proxy":
			if err := rootCmd.Execute(); err != nil {
				fmt.Fprint(os.Stderr, err)
				os.Exit(1)
			}
			return
		}
	}

	startEtcdOrProxyV2(args)
```

`grpc-gateway` 不在 case 列表里，会掉到 `startEtcdOrProxyV2`——被当成启动 server 的参数解析，结果是启动失败或报未知 flag，不会启动任何网关。

### Current Form: etcd server Startup Flags

配置字段在 `server/embed/config.go:438`：

```go
// server/embed/config.go:436
	// EnableGRPCGateway enables grpc gateway.
	// The gateway translates a RESTful HTTP API into gRPC.
	EnableGRPCGateway bool `json:"enable-grpc-gateway"`
```

flag 注册在 `config.go:751`（`fs.BoolVar(&cfg.EnableGRPCGateway, "enable-grpc-gateway", cfg.EnableGRPCGateway, "Enable GRPC gateway.")`），帮助文本在 `server/etcdmain/help.go:107-108`。所以正确用法是：

```bash
etcd --enable-grpc-gateway \
  --listen-client-urls=http://127.0.0.1:2379 \
  --advertise-client-urls=http://127.0.0.1:2379
```

**没有独立的端口**——REST 端点与客户端 gRPC 端点共用同一个监听地址（`serve.go` 里 `gwmux` 被塞进 `createMux`）。这是与旧形态最大的操作差异：以前要起两个进程、两个端口，现在只是一个开关。

运行时实现在 `server/embed/serve.go:333` 的 `registerGateway`，由 `serve()` 在 `serve.go:154-155` 按 `s.Cfg.EnableGRPCGateway` 决定是否装配。它 import 官方的 `gw "github.com/grpc-ecosystem/grpc-gateway/v2/runtime"`（`serve.go:29`），先 dial 自己的 gRPC 端口，再把 8 个 handler 注册到 `gw.NewServeMux`：

```go
// server/embed/serve.go:359
	handlers := []registerHandlerFunc{
		etcdservergw.RegisterKVHandler,
		etcdservergw.RegisterWatchHandler,
		etcdservergw.RegisterLeaseHandler,
		etcdservergw.RegisterClusterHandler,
		etcdservergw.RegisterMaintenanceHandler,
		etcdservergw.RegisterAuthHandler,
		v3lockgw.RegisterLockHandler,
		v3electiongw.RegisterElectionHandler,
	}
```

这 8 个 handler 的 `gw/` 子目录在各 pb 包内（如 `server/etcdserver/api/v3election/v3electionpb/gw/`），由 proto 里的 `google.api.http` 注解生成——`server/etcdserver/api/v3rpc/` 下**没有** `gw/` 子目录。

marshaler 的选项值得注意（`serve.go:344-355`）：`UseProtoNames: true` + `EmitUnpopulated: false` + `DiscardUnknown: true`。也就是 **JSON 字段名用 proto 的原始下划线命名**（`range_end` 而非 `rangeEnd`），未知字段静默忽略。`server/embed/etcd.go:837` 那处是给 gateway 反向 dial 后端用的连接工厂。

### REST Path

路径前缀 `/v3/`，与 gRPC method 一一对应：

| gRPC method | REST 路径 |
| :--- | :--- |
| `KV.Range` | `POST /v3/kv/range` |
| `KV.Put` | `POST /v3/kv/put` |
| `KV.Txn` | `POST /v3/kv/txn` |
| `KV.DeleteRange` | `POST /v3/kv/delete_range` |
| `Watch.Watch` | `POST /v3/watch/watch` |
| `Lease.LeaseGrant` | `POST /v3/lease/lease_grant` |
| `Cluster.MemberList` | `POST /v3/cluster/member/list` |
| `Auth.Authenticate` | `POST /v3/auth/authenticate` |

字节字段（`key`、`value`、`range_end`）用 **base64**：

```bash
# "foo" 的 base64 是 "Zm9v"
curl -L http://localhost:2379/v3/kv/range \
  -X POST -d '{"key":"Zm9v","range_end":"","limit":10}'
```

> [!WARNING]
> 走网关的写请求与直连 gRPC 走**同一条 Raft 链路**，一致性语义不变；但多一跳序列化，且 JSON 的 base64 心智负担大（做前缀扫描要自己算 `range_end` 的 base64）。**生产路径仍推荐直连 gRPC 客户端**。网关更适合调试与异构客户端接入。

## Tension Between the cache Module and This Narrative

3.7 顶层新增了独立 Go module `cache/`（`cache/go.mod:1` 是 `module go.etcd.io/etcd/cache/v3`，并登记在 `go.work` 的 `use` 列表里）。它是一个**客户端侧**的实验性缓存库：`Cache` 类型（`cache/cache.go:44`）为某个 key-prefix 维护一份 watch，把事件通过 `demux` 扇出给本地多个 watcher，并维护 `store`（最近一次观测到的快照）。

按第一直觉，它看起来像是"客户端版的小型 proxy"，甚至像能替代 grpc-proxy 的 watch 合并。**但它明确不能与 grpc-proxy 配合**，而且这句话被写进了源码注释里、重复了两次（`cache/cache.go:41` 与 `:61`，紧跟 `Cache` 类型与 `New` 构造函数）：

> Note: gRPC proxy is not supported. Cache relies on `RequestProgress` RPCs, which the gRPC proxy does not forward.

原因是 cache 的就绪判定依赖 `RequestProgress` RPC（`cache/cache.go:109` 的 `RequestProgress`、单独抽出的 `progress_requestor.go`），而 grpc-proxy 不转发这个 RPC——两者叠加会让 cache 永远等不到 ready。

> [!TIP]
> 选型上：要在**客户端进程内**省掉 watch 的重复与序列化开销，用 `cache/`（注意它标了 Experimental）；要在**网络层**做多客户端的 watch/lease 合并与 namespace 隔离，用 `etcd grpc-proxy start`。两者不是替代关系，且**不能叠加使用**。

## Pitfall List

> [!WARNING]
> 每一条都对应"按旧版印象操作 3.7.2 会踩的坑"。

1. **`etcd gateway` 是 L4 TCP 代理，没有任何 L7 能力。** 别指望它做 namespace 隔离、watch 合并、lease 合并或健康检查——它连 gRPC 帧都不解析。`tcpproxy/doc.go:15` 的 "OSI level 4" 是权威表述。旧资料把它当 L7 是**最容易误导运维的一处**。
2. **`etcd gateway` 与 `etcd grpc-proxy` 是两个都在的子命令，不是替代关系。** 3.5 引入 grpc-proxy 时并没有"取代"旧 gateway 命令——`main.go:31` 同一个 case 分支里两个都注册。真实变化是旧 gateway 被**降级重写**为 L4，L7 语义全部由 grpc-proxy 承担。
3. **`etcd grpc-gateway` 子命令已不存在。** 3.7.2 的 `main.go:31` switch 只认 `"gateway"` 与 `"grpc-proxy"`。按旧资料敲这个命令不会启动网关，而是被当成 server 启动参数。
4. **REST 网关现在是 flag 且没有独立端口。** `--enable-grpc-gateway`（`embed/config.go:751`）与 gRPC 共用 `--listen-client-urls`。旧资料里"另起一个进程监听另一个端口"的模型已完全失效。
5. **顶层没有 `grpc-proxy/` 目录。** 代码在 `server/proxy/grpcproxy/`（含 `adapter/` 子包）。去顶层找会扑空。
6. **别把 grpc-proxy 的 flag 套到 gateway 上。** `--namespace`、`--resolver-prefix`、`--resolver-ttl`、`--advertise-client-url`、`--metrics-addr` 全是 grpc-proxy 的；gateway 只有 7 个 flag（见上文表格）。
7. **grpc-proxy 的两组 TLS flag 方向相反。** `--cert-file`/`--key-file`/`--trusted-ca-file`/`--auto-tls` 是对**客户端**；`--cert`/`--key`/`--cacert` 是对 **etcd**。填反的表现是"proxy 起来但连不上后端"或"客户端连不上 proxy"。
8. **实验性 flag 不要写死。** `--experimental-serializable-ordering` 与 `--experimental-leasing-prefix` 默认关闭且语义随版本变；`--experimental-enable-grpc-logging` 会打印全部 gRPC 流量，生产环境慎开。
9. **`cache/` 模块与 grpc-proxy 不兼容。** 见上文那一节：`RequestProgress` RPC 不被 proxy 转发，两者叠加会让 cache 卡在 never-ready。源码注释里已明确写了这一点。
10. **grpc-proxy 的 watch 合并不保证 revision 连续。** 精确 revision 要求的调用要直连 server 或绕过 proxy；这条限制在 3.7 没有变化。
11. **`member list` 的返回内容取决于是否配了 `--resolver-prefix`。** 没配时只返回自己的 `advertise-client-url`，不是集群成员列表。
12. **主接口上用 `curl` 打 `/metrics`、`/health` 需要 `--http1.1`**（当配了 TLS 时），否则协议协商失败；或改用 `--metrics-addr` 的独立接口。
13. **peer 流量不要过 gateway。** gateway 不区分 2379/2380，把 peer 流量也转发会破坏每个成员直连对端的模型（每个成员必须能直连所有其他成员的 peer URL，这是 [net.md](/docs/CS/Framework/etcd/net.md) 里 `peer` 建立的前提）。

## Links

- [etcd（server 启动流程与监听端口）](/docs/CS/Framework/etcd/etcd.md)
- [naming（--resolver-prefix 背后的机制）](/docs/CS/Framework/etcd/naming.md)
- [client（gRPC 客户端与重试语义）](/docs/CS/Framework/etcd/client.md)
- [cluster（成员变更与备份恢复）](/docs/CS/Framework/etcd/cluster.md)
- [security（auth 与 TLS）](/docs/CS/Framework/etcd/security.md)
- [net（peer 端口上的 rafthttp）](/docs/CS/Framework/etcd/net.md)

## References

1. [etcd Documentation - gRPC proxy](https://etcd.io/docs/v3.5/op-guide/grpc_proxy/)
2. [etcd Documentation - gRPC gateway (REST/JSON)](https://etcd.io/docs/v3.5/dev-guide/api_grpc_gateway/)
3. [etcd Documentation - gRPC naming](https://etcd.io/docs/v3.5/dev-guide/grpc_naming/)
4. [etcd v3.7.2 server/etcdmain/gateway.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/etcdmain/gateway.go)
5. [etcd v3.7.2 server/proxy/tcpproxy/userspace.go](https://github.com/etcd-io/etcd/blob/v3.7.2/server/proxy/tcpproxy/userspace.go)
6. [etcd v3.7.2 cache/README.md](https://github.com/etcd-io/etcd/blob/v3.7.2/cache/README.md)
