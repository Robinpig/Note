## Introduction

服务发现是 Consul 最核心的能力。服务注册并附带健康检查后，消费方有三种接入入口：**DNS**（无需 SDK，普通 `dig` 即可）、**HTTP API**、以及本地 **agent 缓存的 stale 读**。这比 etcd（必须 gRPC 客户端，见 [etcd client](/docs/CS/Framework/etcd/client.md)）和 ZooKeeper（Jute 私有协议）对业务更友好——也是 Consul "零改造接入"的来源。本文源码核自 **v2.1.0**。

## Health Check

健康检查实现集中在 `agent/checks/check.go`（2.x 纠偏：`agent/check.go` 只剩持久化结构，各类型检查的实现全部在 `checks/` 包）：

- `script`：agent 周期性执行脚本（需显式 `enable_script_checks=true`，建议配合 ACL）；
- `http` / `tcp` / `grpc` / `h2ping`（2.x 新增）/ `udp` / `docker`；
- `ttl`：服务自己周期性 `PUT /v1/agent/check/pass|warn|fail/<id>`，超时未报则判失败。

两类硬约束在源码里写死：**最小间隔 1 秒**（防 fork bomb）、**HTTP 检查默认超时 10 秒**：

```go
const (
	// MinInterval is the minimal interval between
	// two checks. Do not allow for a interval below this value.
	// Otherwise we risk fork bombing a system.
	MinInterval = time.Second

	// DefaultBufSize is the maximum size of the captured
	// check output by default. Prevents an enormous buffer
	// from being captured
	DefaultBufSize = 4 * 1024 // 4KB

	// UserAgent is the value of the User-Agent header
	// for HTTP health checks.
	UserAgent = "Consul Health Check"
)
```

```go
		// Create the HTTP client.
		c.httpClient = &http.Client{
			Timeout:   10 * time.Second,
			Transport: trans,
		}
```

`agent/checks/check.go`

TTL 检查的入口是 HTTP 端点 `AgentCheckPass` → `updateTTLCheck` → `CheckTTL.SetStatus`（重置 timer）：

```go
// run is used to handle TTL expiration and to update the check status
func (c *CheckTTL) run() {
	for {
		select {
		case <-c.timer.C:
			c.Logger.Warn("Check missed TTL, is now critical",
				"check", c.CheckID.String(),
			)
			c.Notify.UpdateCheck(c.CheckID, api.HealthCritical, c.getExpiredOutput())

		case <-c.stopCh:
			return
		}
	}
}
```

`agent/checks/check.go`

检查状态更新进本地状态时**标脏并立即触发同步**；状态没变、只变 output 的场景则延迟半周期批量回写（output 节流）：

```go
	// Update status and mark out of sync
	c.Check.Status = status
	c.Check.Output = output
	c.InSync = false
	l.TriggerSyncChanges()
```

`agent/local/state.go`

> [!TIP]
> 检查失败只影响"发现结果"，**不自动重启/隔离进程**。需要自愈要配合服务网格或外部编排。另外 2.x 的 `CheckState` 带 `CriticalFor()` critical 时长跟踪，可用于"进入 critical 超过 N 分钟才告警"的分级逻辑。

## Health Read Endpoint and Passing Filter

`/v1/health/service/<svc>` 的 server 端实现是 `Health.ServiceNodes`（`agent/consul/health_endpoint.go`）。健康聚合 = 节点级 check + 服务级 check 合并（见 [数据模型](/docs/CS/Framework/consul/data_model.md)），过滤在返回侧执行：

```go
				filteredNodes := raw.(structs.CheckServiceNodes)
				thisReply.Nodes = filteredNodes.Filter(structs.CheckServiceNodeFilterOptions{FilterType: arg.HealthFilterType})
```

`agent/consul/health_endpoint.go`

2.x 新增 **merge-hash 去重**：failover 场景下多次合并结果相同时，用内容哈希判断"没变化"并返回哨兵错误 `errNotChanged`，抑制阻塞查询的假唤醒：

```go
				if ranMergeOnce && priorMergeHash == newMergeHash {
					// the below assignment is not required as the if condition already validates equality,
					// but makes it more clear that prior value is being reset to the new hash on each run.
					priorMergeHash = newMergeHash
					reply.Index = index
					// NOTE: the prior response is still alive inside of *reply, which is desirable
					return errNotChanged
				} else {
					priorMergeHash = newMergeHash
					ranMergeOnce = true
				}
```

`agent/consul/health_endpoint.go`

## DNS Interface

2.x 纠偏：DNS 主体是**单文件 `agent/dns.go`**（约 2400 行），`agent/dns/` 目录只剩两个辅助文件——旧资料说的 `agent/dns/io.go` 不存在。端口 8600 定义在 `agent/config/default.go` 的 `ports.dns`。

- `<service>.service.consul`：返回健康实例的 A/AAAA 记录（多实例按 weights + 网络坐标就近）；
- `<service>.service.<dc>.consul`：限定数据中心；
- `<node>.node.consul`：按节点名解析；
- `<query>.query.consul`：prepared query；
- SRV 记录额外返回端口；2.x 支持多端口服务（`findPort(srv, portName)`）与 peering 服务的 FQDN 变形。

权重按聚合健康状态选择 passing/warning 权重：

```go
func findWeight(node structs.CheckServiceNode) int {
	// By default, when only_passing is false, warning and passing nodes are returned
	// Those values will be used if using a client with support while server has no
	// support for weights
	weightPassing := 1
	weightWarning := 1
	if node.Service.Weights != nil {
		weightPassing = node.Service.Weights.Passing
		weightWarning = node.Service.Weights.Warning
	}
	...
	status := serviceChecks.AggregatedStatus()
	switch status {
	case api.HealthWarning:
		return weightWarning
	case api.HealthPassing:
		return weightPassing
	case api.HealthMaint:
		// Not used in theory
		return 0
	...
}
```

`agent/dns.go`

SOA 记录的 NS/Mbox 固定为 `ns.<domain>` / `hostmaster.<domain>`，TTL 与 MinTTL 一致以免缓存失效错乱。DNS 查询结果走 agent cache（`UseCache` 配置），`addr` 类查询会忽略 `serfHealth` 检查（`IgnoreCheckIDs`）。

## HTTP API

| 端点 | 视角 | 用途 |
| :--- | :--- | :--- |
| `/v1/catalog/...` | 全量目录（server 权威） | 列出所有节点/服务，**不含健康检查过滤** |
| `/v1/health/...` | 带健康过滤 | `health/service/<svc>` 按三档 `HealthFilterType` 过滤 |
| `/v1/agent/...` | 本 agent 视角 | 注册/反注册本节点服务、读本节点已知信息 |
| `/v1/agent/health` | 本 agent 健康检查 | 本地健康状态，不依赖 leader |

`/v1/health/service/<svc>?passing` 是最常用的查询。catalog 与 health 的分工要记牢：**catalog 回答"注册了什么"，health 回答"现在谁活着"**——只查 catalog 会把 critical 实例也拿回来。

## Agent Cache and Stale Reads

client agent 对发现类查询有完整的 **agent cache** 层（`agent/cache` + `agent/cache-types/`）：类型在 `agent/agent.go` 的 `registerCache()` 注册（`HealthServices`、`ConnectCARoot` 等），`RegisterOptions` 声明三类行为——`SupportsBlocking`（承接长轮询）、`Refresh`（后台周期刷新）、`LastGetTTL`（空闲驱逐）。刷新失败走指数退避：

```go
		// If refresh is enabled, run the refresh in due time. The refresh
		// above might block, but saves us from spawning another goroutine.
		...
		if tEntry.Opts.Refresh && !preventRefresh {
			...
			// If we're over the attempt minimum, start an exponential backoff.
			wait := backOffWait(attempt)

			// If we have a timer, wait for it
			wait += tEntry.Opts.RefreshTimer

			select {
			case <-time.After(wait):
			case <-ctx.Done():
				return
			case <-handle.stopCh:
				return
			}
```

`agent/cache/cache.go`

一致性语义（与 etcd 的 `linearizable`/`serializable` 对照，见 [etcd read](/docs/CS/Framework/etcd/read.md)）：默认 stale/leader 读走缓存高可用，`?consistent` 绕过缓存强制 VerifyLeader——Consul 把"发现优先于严格一致"作为主路径，强一致是可选项。

## Prepared Query

prepared query 是**带过滤逻辑的命名查询**：预存"查某服务 + tag + DC + 失败 failover 到邻近 DC + `near` 就近排序 + `Limit` 截断"的规则，业务用 `<query>.query.consul` 调用。server 端 `PreparedQuery.Execute` 先 `state.PreparedQueryResolve`（ID 或名字），本地执行、必要时 `queryFailover` 跨 DC。2.x 差异：结果集先 `Shuffle` 再距离排序（避免同 RTT 实例固定次序）；新增 SamenessGroup 执行路径。编译缓存不在 server 端，而在 **agent cache**（DNS 侧 `lookupPreparedQuery` 走 cache）。

## Blocking Query

阻塞查询细节已统一收进 `agent/blockingquery` 包（memdb `WatchSet`、`AbandonCh`、300s/600s 超时），完整实现剖析见 [数据模型](/docs/CS/Framework/consul/data_model.md)。Consul 不保留历史 revision，阻塞查询只给"当前最新状态 + 触发索引"，回溯需客户端自维护游标。

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [数据模型](/docs/CS/Framework/consul/data_model.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Serf（成员发现与网络坐标）](/docs/CS/Framework/consul/serf.md)
- [Client（客户端与 Agent RPC）](/docs/CS/Framework/consul/client.md)
- [Mesh（服务网格）](/docs/CS/Framework/consul/mesh.md)
- [etcd read](/docs/CS/Framework/etcd/read.md)

## References

1. [Consul Service Discovery](https://developer.hashicorp.com/consul/docs/discovery)
2. [Consul DNS](https://developer.hashicorp.com/consul/docs/discovery/dns)
3. [Consul Prepared Query](https://developer.hashicorp.com/consul/api-docs/query)
4. [hashicorp/consul v2.1.0 checks/check.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/checks/check.go)
