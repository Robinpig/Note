# ProgressTracker

## Introduction

`MsgCheckQuorum` 的语义是：检查活跃节点数是否达到 quorum，达不到就退位为 follower。相关操作全部落在 `ProgressTracker` 上。它是 raft 里**唯一以 follower 为中心的数据结构**——Term、Vote、日志都是 leader 视角的状态机，而 `ProgressTracker` 站在 leader 视角维护"每个 follower 到什么程度了、还能不能给它发消息"。

理解它的关键在于**两个索引**：`Match`（follower 已确认的日志位置）与 `Next`（leader 认为下一个该发的位置），差值就是"在途未确认"的量，所有流控、探测、回退逻辑都建立在这个差值上。

> 版本基线：etcd 3.7.4（commit 2e8a5c99，Go 1.26）。raft 自 3.6.5 起外置为独立 module `go.etcd.io/raft/v3` v3.7.0，主仓库对 `tracker` 零引用；下列 `tracker/` 源码片段取自外置仓库 v3.7.0。主仓库唯一相关处是 `server/etcdserver/raft.go` 里的 `raftStorage *raft.MemoryStorage`（见 [raft](/docs/CS/Framework/etcd/raft.md)）。

> [!NOTE]
> 术语统一：`Progress`（`tracker.go` 里的 map 字段，3.5.34 及之前叫 `ProgressMap`）与 `*Progress`（单个 follower 状态，`progress.go`）是两个层级的类型；正文若无特别说明均指单个 follower 状态。外置后类型名/字段名保持稳定。

## Three States

leader 与某个 follower 的交互有且只有三种，定义在外置仓库的 `tracker/state.go`：

```go
const (
	// StateProbe indicates a follower whose last index isn't known. Such a
	// follower is "probed" (i.e. an append sent periodically) to narrow down
	// its last index. In the ideal (and common) case, only one round of probing
	// is necessary as the follower will react with a hint. Followers that are
	// probed over extended periods of time are often offline.
	StateProbe StateType = iota
	// StateReplicate is the state steady in which a follower eagerly receives
	// log entries to append to its log.
	StateReplicate
	// StateSnapshot indicates a follower that needs log entries not available
	// from the leader's Raft log. Such a follower needs a full snapshot to
	// return to StateReplicate.
	StateSnapshot
)
```

| State | 触发场景 | 发送策略 | 流控依据 |
| :--- | :--- | :--- | :--- |
| `StateProbe` | 刚建联、日志位置未知、长时间无响应 | **每心跳周期最多 1 条** | `ProbeSent`（发过就停） |
| `StateReplicate` | 正常稳态 | **乐观批量**，不等 ack 就推进 `Next` | `Inflights.Full()` |
| `StateSnapshot` | follower 落后太多、leader 日志已截断 | 停发日志，只发快照 | 恒为 true |

- **Probe 是"每心跳一条"的节流模式**：官方注释很直接——*Followers that are probed over extended periods of time are often offline*（长时间停留 Probe 的基本掉线）。
- **Replicate 是乐观的**：不等 ack 就把 `Next` 推到最新，这是吞吐来源；代价是可能发到 follower 并不需要的位置，所以有 `MaybeDecrTo` 回退。
- **Snapshot 是兜底**：leader 给不出 follower 需要的条目时只能传整份快照，此时暂停一切日志发送。

## Progress Structure

单个 follower 的状态定义在 `tracker/progress.go`，每个字段对应一类交互决策：

```go
type Progress struct {
	Match, Next uint64
	// State defines how the leader should interact with the follower.
	State StateType

	// PendingSnapshot is used in StateSnapshot. If there is a pending snapshot,
	// the replication process of this Progress will be paused.
	PendingSnapshot uint64

	// RecentActive is true if the progress is recently active. Receiving any messages
	// from the corresponding follower indicates the progress is active.
	RecentActive bool

	// ProbeSent is used while this follower is in StateProbe. When ProbeSent is
	// true, raft should pause sending replication message to this peer.
	ProbeSent bool

	// Inflights is a sliding window for the inflight messages. When inflights
	// is Full, no more message should be sent.
	Inflights *Inflights

	// IsLearner is true if this progress is tracked for a learner.
	IsLearner bool
}
```

官方还留了一句自我批评，值得原样引出：

```go
// NB(tbg): Progress is basically a state machine whose transitions are mostly
// strewn around `*raft.raft`. Additionally, some fields are only used when in a
// certain State. All of this isn't ideal.
```

即 Progress 是状态机，但**状态转移散落在 `raft.go` 的各个 step 函数里**，部分字段只在特定状态有意义——所以很难从 Progress 本身看出全貌，必须结合调用点。

`Match` 与 `Next` 的语义区别是本节重点：`Match` 是 follower **明确确认已持久化**的位置；`Next` 是 leader 下一条要发的位置，正常 `Next >= Match + 1`，差值是**在途未确认**条目数。两者关系在 `MaybeUpdate`（收到 `MsgAppResp`）与 `OptimisticUpdate`（发出 MsgApp）里最清楚：

```go
func (pr *Progress) MaybeUpdate(n uint64) bool {
	var updated bool
	if pr.Match < n {
		pr.Match = n
		updated = true
		pr.ProbeAcked()
	}
	pr.Next = max(pr.Next, n+1)
	return updated
}

// OptimisticUpdate signals that appends all the way up to and including index n
// are in-flight. As a result, Next is increased to n+1.
func (pr *Progress) OptimisticUpdate(n uint64) { pr.Next = n + 1 }
```

`OptimisticUpdate` 只有一行——发出消息后不等 ack 直接推进 `Next`，这就是"乐观复制"的落点。

## IsPaused and Flow Control

leader 判断"能不能给这个 follower 发消息"只有一个入口：

```go
func (pr *Progress) IsPaused() bool {
	switch pr.State {
	case StateProbe:
		return pr.ProbeSent
	case StateReplicate:
		return pr.Inflights.Full()
	case StateSnapshot:
		return true
	default:
		panic("unexpected state")
	}
}
```

三种状态对应三种节流理由，一个慢 follower 会被"越来越疏远"而不是"拖垮整个复制"：

| 状态 | 暂停条件 | 恢复时机 |
| :--- | :--- | :--- |
| Probe | 上条探测消息还没确认 | 收到响应 → `ProbeAcked()` 清 `ProbeSent` |
| Replicate | 在途消息数达到 `MaxInflightMsgs` | 收到 ack → `FreeLE()` 释放窗口 |
| Snapshot | 恒为 true | 快照失败或完成后转出 Snapshot 状态 |

> [!TIP]
> `IsPaused()` 是理解 etcd **为什么不会因一个慢节点拖垮整个集群**的关键：慢节点只让自己进入暂停状态，leader 照常给其他节点批量复制。整机吞吐受最慢节点影响，但不会被它阻塞。

## Inflights

`Inflights` 是**环形缓冲区**实现的滑动窗口（`tracker/inflights.go`）：

```go
type Inflights struct {
	start int   // the starting index in the buffer
	count int   // number of inflights in the buffer
	size  int   // the size of the buffer
	// buffer contains the index of the last entry inside one message.
	buffer []uint64
}
```

`size` 即配置的 `MaxInflightMsgs`，**同时限制在途消息数与每个 Progress 能用的带宽**（每条消息按 `MaxSizePerMsg` 打包，两者相乘即带宽上限）。添加消息时有溢出保护：

```go
func (in *Inflights) Add(inflight uint64) {
	if in.Full() {
		panic("cannot add into a Full inflights")
	}
	next := in.start + in.count
	size := in.size
	if next >= size {
		next -= size
	}
	if next >= len(in.buffer) {
		in.grow()
	}
	in.buffer[next] = inflight
	in.count++
}
```

缓冲区**按需增长**而非预分配，理由写在 `grow()` 注释里：

```go
// grow the inflight buffer by doubling up to inflights.size. We grow on demand
// instead of preallocating to inflights.size to handle systems which have
// thousands of Raft groups per process.
func (in *Inflights) grow() {
	newSize := len(in.buffer) * 2
	if newSize == 0 {
		newSize = 1
	} else if newSize > in.size {
		newSize = in.size
	}
	newBuffer := make([]uint64, newSize)
	copy(newBuffer, in.buffer)
	in.buffer = newBuffer
}
```

> [!NOTE]
> 这条注释很有信息量：**一个进程里可能有成千上万个 Raft group**（每个 gRPC session、每个 raft-node 都是一组）。若每个都预分配 `MaxInflightMsgs` 大小的切片，内存会爆炸。按需倍增是唯一合理选择。

释放用 `FreeLE`（free less-or-equal），收到 ack 后一次性释放所有 ≤ 该 index 的槽位；`Full()` / `Count()` 很直接：

```go
func (in *Inflights) FreeLE(to uint64) {
	if in.count == 0 || to < in.buffer[in.start] {
		return
	}
	// ... 环形遍历找到第一个大于 to 的槽位
	in.count -= i
	in.start = idx
	if in.count == 0 {
		in.start = 0   // 窗口空时归零，避免缓冲区无谓增长
	}
}

func (in *Inflights) Full() bool { return in.count == in.size }
func (in *Inflights) Count() int { return in.count }
```

## Rollback Logic

follower 拒绝日志时 leader 要把 `Next` 调回去，`MaybeDecrTo` 必须区分**真拒绝**与**假拒绝**：

```go
func (pr *Progress) MaybeDecrTo(rejected, matchHint uint64) bool {
	if pr.State == StateReplicate {
		// The rejection must be stale if the progress has matched and "rejected"
		// is smaller than "match".
		if rejected <= pr.Match {
			return false
		}
		// Directly decrease next to match + 1.
		// TODO(tbg): why not use matchHint if it's larger?
		pr.Next = pr.Match + 1
		return true
	}
	// The rejection must be stale if "rejected" does not match next - 1.
	if pr.Next-1 != rejected {
		return false
	}
	pr.Next = max(min(rejected, matchHint+1), 1)
	pr.ProbeSent = false
	return true
}
```

- **Replicate 模式**：`rejected <= pr.Match` 意味着拒绝指向 follower 早就确认过的位置——乱序/重复造成的假拒绝，直接忽略；否则退回 `Match + 1`。
- **非 Replicate 模式**是"一次探一条"，只有 `rejected == Next - 1` 才有效；有效时用 `matchHint` 定位并**清 `ProbeSent` 允许立即重发**。

那行 `TODO(tbg): why not use matchHint if it's larger?` 很意思：Replicate 分支拿到 `matchHint` 却没用，合理推测是 `Match+1` 已是最安全选择（不越过 follower 确认边界），而 `matchHint` 来自对端未必可信。

## State Transition

三个 `Become*` 方法都走 `ResetState` 统一重置辅助字段：

```go
func (pr *Progress) ResetState(state StateType) {
	pr.ProbeSent = false
	pr.PendingSnapshot = 0
	pr.State = state
	pr.Inflights.reset()
}

func (pr *Progress) BecomeProbe() {
	// If the original state is StateSnapshot, progress knows that the pending
	// snapshot has been sent successfully, then probes from pendingSnapshot + 1.
	if pr.State == StateSnapshot {
		pendingSnapshot := pr.PendingSnapshot
		pr.ResetState(StateProbe)
		pr.Next = max(pr.Match+1, pendingSnapshot+1)
	} else {
		pr.ResetState(StateProbe)
		pr.Next = pr.Match + 1
	}
}

func (pr *Progress) BecomeReplicate() {
	pr.ResetState(StateReplicate)
	pr.Next = pr.Match + 1
}

func (pr *Progress) BecomeSnapshot(snapshoti uint64) {
	pr.ResetState(StateSnapshot)
	pr.PendingSnapshot = snapshoti
}
```

`BecomeProbe` 的分支最容易漏看：**从 Snapshot 退回时，探测起点是 `pendingSnapshot + 1` 而非 `Match + 1`**——快照已成功送达，那之后的日志才是 follower 真正缺的。

这三个方法在 `becomeLeader` 的 `reset()` 里集中调用（算法已外置，不在 etcd 主仓库）：

```go
r.prs.Visit(func(id uint64, pr *tracker.Progress) {
	*pr = tracker.Progress{
		Match:     0,
		Next:      r.raftLog.lastIndex() + 1,
		Inflights: tracker.NewInflights(r.prs.MaxInflight),
		IsLearner: pr.IsLearner,
	}
	if id == r.id {
		pr.Match = r.raftLog.lastIndex()
	}
})
```

注意 `IsLearner: pr.IsLearner` 被特意保留——**角色切换不改变 learner 身份**，只有 `ConfChange` 能改。

## ProgressTracker

`ProgressTracker` 持有全体 Progress（`tracker/tracker.go`），核心是 `Progress` 与 `Voters`（`JointConfig`）两部分：

```go
type ProgressTracker struct {
	Progress map[uint64]*Progress

	Voters   JointConfig
	Learners map[uint64]struct{}
	// maxInflight is the maximum number of in-flight requests per peer.
	MaxInflight int
}
```

> [!NOTE]
> learner 被**单独存放**（`Learners` map），不混在 `Progress` 里——learner 语义是"追踪进度但不参与投票"，而 `Committed()` 只按 `Voters` 算。

### Commit Watermark and Quorum

回到埋的坑，quorum 判定就是 `Committed()`：

```go
func (p *ProgressTracker) Committed() uint64 {
	return uint64(p.Voters.CommittedIndex(matchAckIndexer(p.Progress)))
}
```

把全体 voter 的 `Match` 排序，取**多数派位置的最小值**——Raft 论文的 commit rule。调用点：

```go
func (r *raft) maybeCommit() bool {
	mci := r.prs.Committed()
	return r.raftLog.maybeCommit(mci, r.Term)
}
```

> [!TIP]
> `Committed()` 只统计 **Voters**，Learners 不在范围——learner 无论落后多少都不影响提交水位，这正是它作为"安全加入集群手段"的价值（见 [cluster](/docs/CS/Framework/etcd/cluster.md) 的 learner 三步法）。

### Liveness Detection

`MsgCheckQuorum` 依赖的活跃判定同样在这里：

```go
func (p *ProgressTracker) QuorumActive() bool {
	votes := map[uint64]bool{}
	p.Visit(func(id uint64, pr *Progress) {
		if pr.IsLearner {
			return
		}
		votes[id] = pr.RecentActive
	})
	return p.Voters.VoteResult(votes) == quorum.VoteWon
}
```

`RecentActive`：收到该 follower 的任何消息即视为活跃，一个选举超时后可被重置为 false。同样**跳过 learner**。连上两个坑：`MsgCheckQuorum` 检查活跃 voter 不足 quorum → leader 主动退位 → 触发新一轮选举。

### Observability

`Progress.String()` 是**排查线上状态最实用的手段**：

```go
func (pr *Progress) String() string {
	var buf strings.Builder
	fmt.Fprintf(&buf, "%s match=%d next=%d", pr.State, pr.Match, pr.Next)
	if pr.IsLearner { fmt.Fprint(&buf, " learner") }
	if pr.IsPaused() { fmt.Fprint(&buf, " paused") }
	if pr.PendingSnapshot > 0 {
		fmt.Fprintf(&buf, " pendingSnap=%d", pr.PendingSnapshot)
	}
	if !pr.RecentActive { fmt.Fprint(&buf, " inactive") }
	if n := pr.Inflights.Count(); n > 0 {
		fmt.Fprintf(&buf, " inflight=%d", n)
		if pr.Inflights.Full() { fmt.Fprint(&buf, "[full]") }
	}
	return buf.String()
}
```

```text
StateReplicate match=1024 next=1088 inflight=3
StateProbe match=1000 next=1001 paused
StateSnapshot match=900 next=0 pendingSnap=2048 learner
```

| 现象 | 含义 |
| :--- | :--- |
| `inactive` | 长时间没收到该 follower 任何消息 |
| `inflight=[full]` | 被 `MaxInflightMsgs` 卡住，接收侧处理不过来 |
| 长期 `StateProbe` | 基本可判定该节点离线（官方注释同此） |
| `pendingSnap` 长期不消 | 快照传输卡住，见 [net](/docs/CS/Framework/etcd/net.md) 的 snapshotHandler |

## ConfChange

成员变更通过 Raft 日志下发（`MsgProp` → `ConfChangeV2`），leader 应用时调 `ProgressTracker` 的调整方法。核心约束在 `ConfState()`——**learner 身份单独导出**：

```go
func (p *ProgressTracker) ConfState() pb.ConfState {
	return pb.ConfState{
		Voters:         p.Voters.IDs(),
		VotersOutgoing: p.Voters.Outgoing.IDs(),
		Learners:       p.LearnerNodes(),
		LearnersNext:   nil,
		AutoLeave:      true,
	}
}
```

> [!NOTE]
> `Voters` 与 `VotersOutgoing` **分两套**：成员变更生效是两阶段的（joint config），变更期间两套都参与 quorum 计算，全部确认后提交 `LearnersNext`。这与 [cluster.md](/docs/CS/Framework/etcd/cluster.md) "成员变更必须串行"同源——joint config 期间 quorum 计算更复杂，一次改太多会让状态难以推理。

## Links

- [monitoring（监控与指标阈值）](/docs/CS/Framework/etcd/monitoring.md)
- [raft](/docs/CS/Framework/etcd/raft.md)
- [net](/docs/CS/Framework/etcd/net.md)
- [cluster](/docs/CS/Framework/etcd/cluster.md)
- [monitoring](/docs/CS/Framework/etcd/monitoring.md)
- [Raft 论文精读](/docs/CS/Distributed/Consensus/Raft.md)

## References

1. [etcd-io/raft：tracker/progress.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/progress.go)
2. [etcd-io/raft：tracker/inflights.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/inflights.go)
3. [etcd-io/raft：tracker/state.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/state.go)
4. [etcd-io/raft：tracker/tracker.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/tracker.go)
5. [etcd-io/raft：raft.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/raft.go)
6. [In Search of an Understandable Consensus Algorithm (Extended Version)](https://ongardie.net/var/blurbs/pubs/raft-tr14.pdf)
7. [etcd Raft implementation](https://github.com/etcd-io/raft)
1. [etcd-io/raft v3.7.0：tracker/progress.go](https://github.com/etcd-io/raft/blob/v3.7.0/tracker/progress.go)
2. [etcd-io/raft v3.7.0：tracker/inflights.go](https://github.com/etcd-io/raft/blob/v3.7.0/tracker/inflights.go)
3. [etcd-io/raft v3.7.0：tracker/tracker.go](https://github.com/etcd-io/raft/blob/v3.7.0/tracker/tracker.go)
4. [etcd-io/raft v3.7.0：raft.go](https://github.com/etcd-io/raft/blob/v3.7.0/raft.go)
5. [In Search of an Understandable Consensus Algorithm](https://raft.github.io/raft.pdf)
