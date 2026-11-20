## Introduction

Consul 的成员发现不依赖静态 peer 列表，而是跑 **Serf**（SWIM 风格 gossip，底层是 memberlist）：每个 DC 一套 **LAN 池**（全体节点），全公司一套 **WAN 池**（仅 server）。Raft 管"状态一致"，Serf 管"谁还活着、谁新加入"，二者解耦是 Consul 与 etcd/ZooKeeper 最显著的架构差异。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 纠偏：server 端 serf 事件处理函数已从 1.x 的 `serfEventHandler` 改名 **`lanEventHandler`**（`agent/consul/server_serf.go`）；**WAN 事件不再有独立 handler**，而是交给 `router.HandleSerfEvents`（`agent/router/serf_adapter.go`）直接映射成路由表更新。`region` 概念已统一为 **area**。

## Two Pools: LAN and WAN

server 同时建立两套 serf，配置差异在 `setupSerf`（`agent/consul/server_serf.go`）里泾渭分明——WAN 节点名加 DC 后缀、merge 校验只收 server；LAN 校验同 DC + 节点 ID 唯一：

```go
	if opts.WAN {
		conf.NodeName = fmt.Sprintf("%s.%s", s.config.NodeName, s.config.Datacenter)
	} else {
		conf.NodeName = s.config.NodeName
		...
	}
	...
	if opts.WAN {
		conf.Merge = &wanMergeDelegate{
			localDatacenter: s.config.Datacenter,
		}
	} else {
		conf.Merge = &lanMergeDelegate{
			dc:        s.config.Datacenter,
			nodeID:    s.config.NodeID,
			nodeName:  s.config.NodeName,
			segment:   opts.Segment,
			partition: opts.Partition,
			server:    true,
		}
	}
```

`agent/consul/server_serf.go`

WAN merge 的守门逻辑——不是 server 直接拒绝合并，federation 禁用则拒绝外 DC 成员：

```go
func (md *wanMergeDelegate) NotifyMerge(members []*serf.Member) error {
	// Deliberately hold this lock during the entire merge so calls to
	// SetWANFederationDisabled returning immediately imply that the flag takes
	// effect for all future merges.
	md.federationDisabledLock.Lock()
	defer md.federationDisabledLock.Unlock()

	for _, m := range members {
		ok, srv := metadata.IsConsulServer(*m)
		if !ok {
			return fmt.Errorf("Member '%s' is not a server", m.Name)
		}

		if md.federationDisabled {
			if srv.Datacenter != md.localDatacenter {
				return fmt.Errorf("Member '%s' part of wrong datacenter '%s'; WAN federation is disabled", m.Name, srv.Datacenter)
			}
		}
	}
	return nil
}
```

`agent/consul/merge.go`

两套池的 timing 也不同：LAN 用 `memberlist.DefaultLANConfig`，WAN 用 `memberlist.DefaultWANConfig()`（探测更宽松，容忍跨机房 RTT）：

```go
	// WAN Serf should use the WAN timing, since we are using it
	// to communicate between DC's
	conf.SerfWANConfig.MemberlistConfig = memberlist.DefaultWANConfig()

	// Ensure we don't have port conflicts
	conf.SerfLANConfig.MemberlistConfig.BindPort = DefaultLANSerfPort
	conf.SerfWANConfig.MemberlistConfig.BindPort = DefaultWANSerfPort
```

`agent/consul/config.go`

Consul 对库默认值的覆盖只有两处值得注意：

```go
	// Increase our reap interval to 3 days instead of 24h.
	conf.SerfLANConfig.ReconnectTimeout = 3 * 24 * time.Hour
	conf.SerfWANConfig.ReconnectTimeout = 3 * 24 * time.Hour

	// Allow dead nodes to be replaced after 30 seconds.
	conf.SerfLANConfig.MemberlistConfig.DeadNodeReclaimTime = 30 * time.Second
	conf.SerfWANConfig.MemberlistConfig.DeadNodeReclaimTime = 30 * time.Second
```

`agent/consul/config.go`

client agent 只参与 LAN 池（`agent/consul/client_serf.go`，tag `role=node`）。端口：LAN 8301、WAN 8302（TCP+UDP），任一方向被防火墙拦截都会扰乱 gossip。

### Failure Detection (SWIM)

SWIM 探测：周期性向随机对端发 probe，未收到 ack 则进入 **suspicion**（怀疑）状态，经 `suspicion_mult` × 探测间隔仍无确认才标记 `failed`——先怀疑后删除，比"超时即删"更抗网络抖动。成员状态机 `alive → suspect → failed / left` 经 gossip 扩散到全池。

> [!TIP]
> gossip 对延迟敏感：官方参考架构要求同 DC 内平均 RTT < 50ms。跨 AZ 部署 RTT 过高会频繁触发 suspicion，server 被误判 failed 进而牵连 Raft 重选。此时应调 `gossip_lan` 重传参数或收敛 server 到更近的 AZ（见 [Tuning](/docs/CS/Framework/consul/tuning.md)）。

## Event Handling: LAN vs WAN

LAN 事件由 server 的 `lanEventHandler` 处理：成员加入更新 serverLookup + router，并触发 `maybeBootstrap`（`bootstrap_expect` 引导）与 `FloodNotify`；leave/failed/reap 触发 catalog 注销（经 `V1ConsulRegistrator.HandleReapMember` → `Catalog.Deregister`）：

```go
		case e := <-s.eventChLAN:
			switch e.EventType() {
			case serf.EventMemberJoin:
				s.lanNodeJoin(e.(serf.MemberEvent))
				s.localMemberEvent(e.(serf.MemberEvent))

			case serf.EventMemberLeave, serf.EventMemberFailed, serf.EventMemberReap:
				s.lanNodeFailed(e.(serf.MemberEvent))
				s.localMemberEvent(e.(serf.MemberEvent))

			case serf.EventUser:
				s.localEvent(e.(serf.UserEvent))
			case serf.EventMemberUpdate:
				s.lanNodeUpdate(e.(serf.MemberEvent))
				s.localMemberEvent(e.(serf.MemberEvent))
			case serf.EventQuery: // Ignore
			default:
				s.logger.Warn("Unhandled LAN Serf Event", "event", e)
			}
```

`agent/consul/server_serf.go`

WAN 事件的消费方不是业务逻辑而是**路由表**——`router.HandleSerfEvents` 把 serf 成员事件一对一映射为跨 DC 路由的增删改，这是跨 DC RPC 选路的唯一数据源：

```go
		case e := <-eventCh:
			switch e.EventType() {
			case serf.EventMemberJoin:
				handleMemberEvent(logger, router.AddServer, areaID, e)
				notifyMembershipPossibleChange(membershipNotifyCh)

			case serf.EventMemberLeave, serf.EventMemberReap:
				handleMemberEvent(logger, router.RemoveServer, areaID, e)
				notifyMembershipPossibleChange(membershipNotifyCh)

			case serf.EventMemberFailed:
				handleMemberEvent(logger, router.FailServer, areaID, e)
				notifyMembershipPossibleChange(membershipNotifyCh)
```

`agent/router/serf_adapter.go`

## LAN <-> WAN Flooder

两套池成员如何互相感知？答案是 **flooder**：`server.go` 在 WAN serf 就绪后启动长循环，周期（`SerfFloodInterval` 默认 60s）或事件触发时，把 LAN 里已知的所有 server 逐个 join 进 WAN 池：

```go
		// Fire up the LAN <-> WAN join flooder.
		addrFn := func(s *metadata.Server) (string, error) {
			if s.WanJoinPort == 0 {
				return "", fmt.Errorf("no wan join  port for server: %s", s.Addr.String())
			}
			addr, _, err := net.SplitHostPort(s.Addr.String())
			if err != nil {
				return "", err
			}
			return net.JoinHostPort(addr, strconv.Itoa(s.WanJoinPort)), nil
		}
		go s.Flood(addrFn, s.serfWAN)
```

`agent/consul/server.go`

```go
// Flood is a long-running goroutine that floods servers from the LAN to the
// given global Serf instance, such as the WAN. This will exit once either of
// the Serf instances are shut down.
func (s *Server) Flood(addrFn router.FloodAddrFn, dstSerf *serf.Serf) {
	...
	for {
		select {
		case <-s.serfLAN.ShutdownCh():
			return

		case <-dstSerf.ShutdownCh():
			return

		case <-ticker.C:
			router.FloodJoins(s.logger, addrFn, s.config.Datacenter, s.serfLAN, dstSerf)

		case <-floodCh:
			router.FloodJoins(s.logger, addrFn, s.config.Datacenter, s.serfLAN, dstSerf)
		}
	}
```

`agent/consul/flood.go`

> [!TIP]
> 为什么需要 flooder？WAN 池成员不会自动同步 LAN 新增的 server——`retry_join` 只在启动时生效。flooder 让"新 server 加入 LAN"这一事件最终自动传播到全公司 WAN 池，不需要人工干预。

## Network Coordinates

Serf 之外，agent 间还交换 **Vivaldi 网络坐标**用于就近选路（`near=_agent` 排序、prepared query failover）。client 侧按速率自适应间隔上报：

```go
// sendCoordinate is a long-running loop that periodically sends our coordinate
// to the server. Closing the agent's shutdownChannel will cause this to exit.
func (a *Agent) sendCoordinate() {
OUTER:
	for {
		rate := a.config.SyncCoordinateRateTarget
		min := a.config.SyncCoordinateIntervalMin
		intv := lib.RateScaledInterval(rate, min, len(a.LANMembersInAgentPartition()))
		intv = intv + lib.RandomStagger(intv)
```

`agent/agent.go`

server 侧并不逐条提交 Raft，而是先攒内存 map，由 `batchUpdate` 每 `CoordinateUpdatePeriod`（5s）批量 apply，总限速 `BatchSize(128) × MaxBatches(5)` = 640 条/周期（`agent/consul/coordinate_endpoint.go`）。更新命令带 `IgnoreUnknownTypeFlag`，老版本 server 可安全忽略：

```go
		// We set the "safe to ignore" flag on this update type so old
		// servers don't crash if they see one of these.
		t := structs.CoordinateBatchUpdateType | structs.IgnoreUnknownTypeFlag

		slice := updates[start:end]
		_, err := c.srv.raftApply(t, slice)
```

`agent/consul/coordinate_endpoint.go`

> [!NOTE]
> 坐标写入也走 Raft——这意味着"RTT 估算"这种弱一致数据被复制到了全集群，代价是每个 DC 每秒最多 128 条坐标更新的吞吐上限。集群规模大于 128 节点时，client 会按 `RateScaledInterval` 自动拉长上报间隔。

## Encryption

gossip 加密走 memberlist keyring（对称密钥环，支持轮换多钥）：agent 层在 `agent/keyring.go` 建立并挂到 serf config，LAN/WAN 各一个文件（`serf/local.keyring` / `serf/remote.keyring`）：

```go
const (
	SerfLANKeyring = "serf/local.keyring"
	SerfWANKeyring = "serf/remote.keyring"
)

// setupKeyrings in config.SerfLANConfig and config.SerfWANConfig.
func setupKeyrings(config *consul.Config, rtConfig *config.RuntimeConfig, logger hclog.Logger) error {
	// First set up the LAN and WAN keyrings.
	if err := setupBaseKeyrings(config, rtConfig, logger); err != nil {
		return err
	}
	...
```

`agent/keyring.go`

密钥轮换经 `consul keyring` CLI / keyring API 广播到全池（新增钥 → 全员切主钥 → 删旧钥），无需重启。传输层 RPC 的 TLS 是另一条线（见 [Security](/docs/CS/Framework/consul/security.md)）。

## Comparison with etcd / ZooKeeper / Nacos

| 维度 | Consul | etcd | ZooKeeper | Nacos |
| :--- | :--- | :--- | :--- | :--- |
| 成员发现 | Serf gossip（LAN+WAN 双池） | 无（静态 peer） | 无（静态 peer） | address server / Distro |
| 故障检测 | SWIM 探测 + suspicion | 心跳（Raft 内） | 会话心跳 | 心跳 + Distro |
| 跨 DC | WAN 池原生联邦 | 无 | 无 | 弱 |
| 坐标/就近 | Vivaldi 坐标（Raft 复制） | 无 | 无 | 无 |
| 加密 | keyring 对称 + TLS 可选 | TLS | TLS | TLS |

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [Discovery（服务发现，near 排序消费坐标）](/docs/CS/Framework/consul/discovery.md)
- [Security（ACL 与传输 TLS）](/docs/CS/Framework/consul/security.md)
- [Cluster（集群运维）](/docs/CS/Framework/consul/cluster.md)
- [Troubleshooting（gossip 分区排障）](/docs/CS/Framework/consul/troubleshooting.md)
- [Nacos](/docs/CS/Framework/nacos/Nacos.md)

## References

1. [Consul Gossip Protocol](https://developer.hashicorp.com/consul/docs/concept/gossip)
2. [hashicorp/serf](https://github.com/hashicorp/serf)
3. [hashicorp/memberlist (SWIM)](https://github.com/hashicorp/memberlist)
4. [hashicorp/consul v2.1.0 server_serf.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/server_serf.go)
