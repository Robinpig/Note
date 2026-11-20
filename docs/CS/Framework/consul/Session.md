## Introduction

session 是 Consul 协调能力的载体：把一组 key 与一个**持有者身份**绑定，session 失效时绑定的 key 自动被释放或删除。它对应 etcd 的 lease（见 [etcd lease](/docs/CS/Framework/etcd/lease.md)），但语义更丰富——`Behavior` 决定失效动作、`LockDelay` 防锁抖动、健康检查绑定决定存活判定。分布式锁与信号量都构建在它之上。本文源码核自 **v2.1.0**。

> [!WARNING]
> 2.x 纠偏：server 端 RPC 是 `Session.Apply`（`agent/consul/session_endpoint.go`），HTTP 层才是 `SessionCreate` 等函数。session TTL invalidator **不是 1.x 资料描述的 channel 机制**，而是 leader 维护的 **`sessionTimers` map + timer 回调 `invalidateSession`**。2.x 还新增了独立的 `session_checks` 表，session 绑定的检查在 create 时被置 passing、invalidate 时置 critical。

## Fields

server 端 `Session.Apply` 对字段做如下校验与默认化：

| 字段 | 取值 / 默认 | 说明 |
| :--- | :--- | :--- |
| `LockDelay` | 默认 **15s**（HTTP 层默认值；上限 `MaxLockDelay`） | 锁释放后的"冷静期"，期间该 key 不可被立即重新 acquire |
| `TTL` | 区间 **10s（`SessionTTLMin`）– 86400s**；不指定则无 TTL | 心跳上限；leader 按 TTL 建计时器，超时 `invalidateSession` |
| `Behavior` | `release`（默认）/ `delete` | 失效时绑定 key 是"解绑保留"还是"删除" |
| `Checks` / `NodeChecks` | 默认绑定 `serfHealth` | session 与健康检查联动，检查 critical 则 session 失效 |

```go
	// Ensure that the specified behavior is allowed
	switch args.Session.Behavior {
	case "":
		// Default behavior to Release for backwards compatibility
		args.Session.Behavior = structs.SessionKeysRelease
	case structs.SessionKeysRelease:
	case structs.SessionKeysDelete:
	default:
		return fmt.Errorf("Invalid Behavior setting '%s'", args.Session.Behavior)
	}

	// Ensure the Session TTL is valid if provided
	if args.Session.TTL != "" {
		ttl, err := time.ParseDuration(args.Session.TTL)
		if err != nil {
			return fmt.Errorf("Session TTL '%s' invalid: %v", args.Session.TTL, err)
		}

		if ttl != 0 && (ttl < s.srv.config.SessionTTLMin || ttl > structs.SessionTTLMax) {
			return fmt.Errorf("Invalid Session TTL '%d', must be between [%v=%v]",
				ttl, s.srv.config.SessionTTLMin, structs.SessionTTLMax)
		}
	}
```

`agent/consul/session_endpoint.go`

## TTL Invalidation

session 创建走 `raftApply` 正常复制；带 TTL 的 session 在 **leader 侧**额外登记计时器：

```go
	if args.Op == structs.SessionCreate && args.Session.TTL != "" {
		// If we created a session with a TTL, reset the expiration timer
		s.srv.resetSessionTimer(&args.Session)
	} else if args.Op == structs.SessionDestroy {
		// If we destroyed a session, it might potentially have a TTL,
		// and we need to clear the timer
		s.srv.clearSessionTimer(args.Session.ID)
	}
```

`agent/consul/session_endpoint.go`

```go
func (s *Server) createSessionTimer(id string, ttl time.Duration, entMeta *acl.EnterpriseMeta) {
	// Reset the session timer
	// Adjust the given TTL by the TTL multiplier. This is done
	// to give a client a grace period and to compensate for network
	// and processing delays. The contract is that a session is not expired
	// before the TTL, but there is no explicit promise about the upper
	// bound so this is allowable.
	ttl = ttl * structs.SessionTTLMultiplier
	s.sessionTimers.ResetOrCreate(id, ttl, func() { s.invalidateSession(id, entMeta) })
}
```

`agent/consul/session_ttl.go`

两个关键点：① 实际过期时间是 `TTL × SessionTTLMultiplier`（宽松上界——契约是"不会早于 TTL 过期"，晚一点是允许的）；② 计时器随 leader 切换整体重建（`establishLeadership` 里 `initializeSessionTimers`，先 barrier 确保读到最新 session 再建 timer）。超时回调 `invalidateSession` 再发一条 `SessionDestroy` 走 Raft，把失效本身也变成一致操作。

## Invalidation Behavior

失效落库在 `agent/consul/state/session.go` 的 `deleteSessionTxn`：按 `Behavior` 分支处理所有持有中的 key，锁延迟同时登记：

```go
	// Invalidate any held locks.
	switch session.Behavior {
	case structs.SessionKeysRelease:
		for _, obj := range kvs {
			// Note that we clone here since we are modifying the
			// returned object and want to make sure our set op
			// respects the transaction we are in.
			e := obj.(*structs.DirEntry).Clone()
			e.Session = ""
			if err := kvsSetTxn(tx, idx, e, true); err != nil {
				return fmt.Errorf("failed kvs update: %s", err)
			}

			// Apply the lock delay if present.
			if delay > 0 {
				s.lockDelay.SetExpiration(e.Key, now, delay, entMeta)
			}
		}
	case structs.SessionKeysDelete:
		for _, obj := range kvs {
			e := obj.(*structs.DirEntry)
			if err := s.kvsDeleteTxn(tx, idx, e.Key, entMeta); err != nil {
				return fmt.Errorf("failed kvs delete: %s", err)
			}

			// Apply the lock delay if present.
			if delay > 0 {
				s.lockDelay.SetExpiration(e.Key, now, delay, entMeta)
			}
		}
```

`agent/consul/state/session.go`

`release` 保留 key 只清 session 绑定（`kvsSetTxn` 的 `updateSession=true` 路径）；`delete` 直接删 key。prepared query 若以 session 命名注册，session 销毁时级联删除。

> [!NOTE]
> session 的 `TTL` 不是"过期即删"的硬保证——它只是检测死客户端的手段。真正的锁安全由 `LockDelay` 承担：即便 TTL 检测延迟导致旧持有者的请求还在飞，新持有者在 lock-delay 窗口内也抢不到锁。

## Lock Delay

lock-delay 是 Consul 锁设计里最容易被误解的部分，v2.1.0 的实现有三层：

**① 存储是 leader 内存 map，不进 Raft**（`agent/consul/state/delay_ce.go`）：

```go
// SetExpiration sets the expiration time for the lock delay to the given
// delay from the given now time.
func (d *Delay) SetExpiration(key string, now time.Time, delay time.Duration, entMeta *acl.EnterpriseMeta) {
	d.lock.Lock()
	defer d.lock.Unlock()

	d.delay[key] = now.Add(delay)
	time.AfterFunc(delay, func() {
		d.lock.Lock()
		delete(d.delay, key)
		d.lock.Unlock()
	})
}
```

`agent/consul/state/delay_ce.go`

**② 拒绝点在 Raft 提交之前、只在 leader 上检查**（`agent/consul/kvs_endpoint.go` 的 `kvsPreApply`）：

```go
	// If this is a lock, we must check for a lock-delay. Since lock-delay
	// is based on wall-time, each peer would expire the lock-delay at a slightly
	// different time. This means the enforcement of lock-delay cannot be done
	// after the raft log is committed as it would lead to inconsistent FSMs.
	// Instead, the lock-delay must be enforced before commit. This means that
	// only the wall-time of the leader node is used, preventing any inconsistencies.
	if op == api.KVLock {
		state := srv.fsm.State()
		expires := state.KVSLockDelay(dirEnt.Key, &dirEnt.EnterpriseMeta)
		if expires.After(time.Now()) {
			logger.Warn("Rejecting lock of key due to lock-delay",
				"key", dirEnt.Key,
				"expire_time", expires.String(),
			)
			return false, nil
		}
	}
```

`agent/consul/kvs_endpoint.go`

源码注释把因果讲得很直白：lock-delay 基于墙钟，若放在 commit 之后由各 peer 的 FSM 各自判断，不同节点时钟略有差异会导致 FSM 状态分叉；所以只在 leader 上用 leader 的时钟预判。代价是 leader 切换瞬间 lock-delay 状态丢失（新 leader 内存是空的）。

**③ acquire 失败的返回值是 `false` 不是 HTTP 409**：state 层 `kvsLockTxn` 返回 `false`，RPC 层 `*reply=false`，HTTP 层返回 200 + body `false`。等待锁的惯用法是对该 key 做阻塞查询，看到 `LockIndex` 变化后再尝试 acquire。

## Semaphore

信号量（`consul semaphore` / [API](https://developer.hashicorp.com/consul/api-docs/semaphore)）在 session 之上构建："至多 N 个持有者"通过一组带序号的 key（prefix + `.locks/<slot>`）实现，各持有者抢不同 slot 的 key。注意：Consul **没有 etcd concurrency 包里的 STM**——复杂事务要业务自己编排，Consul 的协调原语刻意保持薄。

## Distributed Lock Recipe

- `consul kv put -acquire=<session>` 在 key 上取锁；`-release=<session>` 释放；session 失效自动释放（`Behavior=delete` 时 key 一并消失）。
- 等锁的正确姿势：对该 key 做 blocking query，观察 `LockIndex` 与 `Session` 字段变化，空出来后再 acquire。
- 选主常见模式：每个候选者创建 session 后对 `lock/leader` 竞争 acquire，成为持有者者即 leader；leader 持续对 session 续约（`renew`），失联后 TTL 到期 → session 失效 → lock 自动释放 → 其余候选者被 blocking query 唤醒。

## Links

- [Consul（枢纽与架构）](/docs/CS/Framework/consul/Consul.md)
- [KV（存储）](/docs/CS/Framework/consul/kv.md)
- [Raft（共识）](/docs/CS/Framework/consul/raft.md)
- [数据模型](/docs/CS/Framework/consul/data_model.md)
- [Discovery（服务发现，blocking query 复用同一机制）](/docs/CS/Framework/consul/discovery.md)
- [etcd lease](/docs/CS/Framework/etcd/lease.md)

## References

1. [Consul Sessions](https://developer.hashicorp.com/consul/api-docs/sessions)
2. [Consul Lock](https://developer.hashicorp.com/consul/api-docs/lock)
3. [Consul Semaphore](https://developer.hashicorp.com/consul/api-docs/semaphore)
4. [hashicorp/consul v2.1.0 session_ttl.go](https://github.com/hashicorp/consul/blob/v2.1.0/agent/consul/session_ttl.go)
