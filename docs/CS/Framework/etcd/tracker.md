## Introduction

etcd-raft 里 `MsgCheckQuorum` 的语义是：检查活跃的节点数是否达到 quorum，如果无法达到，那么退位为 follower。它涉及的操作全部落在 ProgressTracker 上：

> 检查活跃的节点数是否达到 quorum，如果无法达到，那么退位为 follower（其相关操作涉及 ProgressTracker，笔者会在后续的文章中分析）

这一篇补上这个坑。ProgressTracker 是 etcd-raft 里**唯一以 follower 为中心的数据结构**——前面的 raft 状态机（Term、Vote、日志）都是 leader 视角的，而 ProgressTracker 站在 leader 视角，维护"每个跟班到什么程度了、还能不能给它发消息"。

理解它的关键在于**两个索引**：`Match`（follower 已确认的日志位置）和 `Next`（leader 认为下一个该发的位置）。这两个索引之间的差值就是"在途未确认"的量，所有流控、探测、回退逻辑都建立在这个差值上。

> [!NOTE]
>
> 本篇源码原基于 etcd **3.5.34** 的 `raft/tracker/`（`progress.go` 单 follower 状态、`inflights.go` 流控窗口、`state.go` 状态枚举、`tracker.go` 全体集合），代码片段保持原样，中文解释在块外。**3.7.2 起 tracker 已全部外置为 `go.etcd.io/raft/v3 v3.7.0`**（3.6.5 即完成外置），主仓库对 `tracker` **零引用**——`find -type d -name raft` 零命中，`.go` 文件里 `tracker` 字符串零命中（含 metrics 层）。因此下文的类型名、字段名、调用点均**无法在 etcd 主仓库中校验**，只以外置仓库为准；主仓库唯一与本篇相关的引用是 `server/etcdserver/raft.go:113` 的 `raftStorage *raft.MemoryStorage`（见 [raft.md](/docs/CS/Framework/etcd/raft.md)）。
>
> 术语统一说明：本篇代码块中，`Progress`（`tracker.go` 里的 map 类型，3.5.34 及之前叫 `ProgressMap`）与 `*Progress`（单个 follower 状态，`progress.go`）是两个不同层级的类型；正文若无特别说明，`Progress` 均指单个 follower 状态。

## Three States

leader 与某个 follower 之间的交互方式有且只有三种，定义在外置仓库的 `tracker/state.go`：

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
| `StateProbe` | 刚建联、日志位置未知、长时间未收到响应 | **每心跳周期最多 1 条** | `ProbeSent`（发过就停） |
| `StateReplicate` | 正常稳态 | **乐观批量**，不等 ack 就推进 `Next` | `Inflights.Full()` |
| `StateSnapshot` | follower 落后太多，leader 日志已截断 | 停发日志，**只发快照** | 恒为 true |

状态机大致这样流转：

```text
                   follower 落后超过日志长度
        ┌──────────────────────────────────────┐
        ↓                                      │
   ┌─────────┐   探测确认/回退    ┌─────────────┐   追平且需要日志   ┌──────────────┐
   │  Probe  │ ────────────────→ │  Replicate  │ ───────────────→ │   Snapshot   │
   │ 未知位置 │                   │   稳态批量   │                  │ 需要完整快照   │
   └─────────┘ ←──────────────── └─────────────┘                  └──────────────┘
        ↑  收到成功响应                                              │
        └──────────────────────────────────────────────────────────┘
                              快照发送完成，进回 Probe 从 pendingSnap+1 继续
```

几个设计意图值得单独指出：

- **Probe 是"每心跳一条"的节流模式**。follower 刚加入时 leader 不知道它的 `Match`，只能试探；官方注释说得很直接：*Followers that are probed over extended periods of time are often offline*（长时间停留在 Probe 的基本是掉线的）。
- **Replicate 是乐观的**。不等 ack 就把 `Next` 推到最新，这是吞吐量的来源；代价是可能发到 follower 并不需要的位置，所以有了 `MaybeDecrTo` 的回退逻辑。
- **Snapshot 是兜底**。一旦 leader 已经截断日志给不出 follower 需要的条目，只能传整份快照，此时 Progress 暂停一切日志发送。

## Progress Structure

外置仓库 `tracker/progress.go` 的结构体定义，每个字段都对应一类交互决策：

```go
type Progress struct {
	Match, Next uint64
	// State defines how the leader should interact with the follower.
	//
	// When in StateProbe, leader sends at most one replication message
	// per heartbeat interval. It also probes actual progress of the follower.
	//
	// When in StateReplicate, leader optimistically increases next
	// to the latest entry sent after sending replication message. This is
	// an optimized state for fast replicating log entries to the follower.
	//
	// When in StateSnapshot, leader should have sent out snapshot
	// before and stops sending any replication message.
	State StateType

	// PendingSnapshot is used in StateSnapshot.
	// If there is a pending snapshot, the pendingSnapshot will be set to
	// the index of the snapshot. If pendingSnapshot is set, the replication process of
	// this Progress will be paused. raft will not resend snapshot until the pending one
	// is reported to be failed.
	PendingSnapshot uint64

	// RecentActive is true if the progress is recently active. Receiving any messages
	// from the corresponding follower indicates the progress is active.
	// RecentActive can be reset to false after an election timeout.
	//
	// TODO(tbg): the leader should always have this set to true.
	RecentActive bool

	// ProbeSent is used while this follower is in StateProbe. When ProbeSent is
	// true, raft should pause sending replication message to this peer until
	// ProbeSent is reset. See ProbeAcked() and IsPaused().
	ProbeSent bool

	// Inflights is a sliding window for the inflight messages.
	// Each inflight message contains one or more log entries.
	// The max number of entries per message is defined in raft config as MaxSizePerMsg.
	// Thus inflight effectively limits both the number of inflight messages
	// and the bandwidth each Progress can use.
	// When inflights is Full, no more message should be sent.
	// When a leader sends out a message, the index of the last
	// entry should be added to inflights. The index MUST be added
	// into inflights in order.
	// When a leader receives a reply, the previous inflights should
	// be freed by calling inflights.FreeLE with the index of the last
	// received entry.
	Inflights *Inflights

	// IsLearner is true if this progress is tracked for a learner.
	IsLearner bool
}
```

官方在注释里留了一句自我批评，值得原样引出：

```go
// NB(tbg): Progress is basically a state machine whose transitions are mostly
// strewn around `*raft.raft`. Additionally, some fields are only used when in a
// certain State. All of this isn't ideal.
```

即 Progress 是个状态机，但**状态转移散落在 `raft.go` 的各个 step 函数里**，且部分字段只在特定状态下才有意义——所以读代码时很难从 Progress 本身看出全貌，必须结合 `raft.go` 的调用点。这也解释了为什么 `IsPaused()` 要写成 switch。

`Match` 与 `Next` 的语义区别是这一节的重点：

- `Match`：**follower 明确确认已持久化**的日志位置。
- `Next`：leader 下一条要发的位置，正常情况下 `Next >= Match + 1`，差值就是**在途未确认**的条目数。

三者的关系在 `MaybeUpdate`（收到 `MsgAppResp`）和 `OptimisticUpdate`（发出 MsgApp 时）里体现得最清楚：

```go
// MaybeUpdate is called when a MsgAppResp arrives from the follower, with the
// index acked by it. The method returns false if the given n index comes from
// an outdated message. Otherwise it updates the progress and returns true.
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

`OptimisticUpdate` 只有一行——发出消息后不等 ack，直接推进 `Next`。这就是"乐观复制"这个词的落点。

## IsPaused and Flow Control

leader 判断"能不能给这个 follower 发消息"只有一个入口：

```go
// IsPaused returns whether sending log entries to this node has been throttled.
// This is done when a node has rejected recent MsgApps, is currently waiting
// for a snapshot, or has reached the MaxInflightMsgs limit. In normal
// operation, this is false. A throttled node will be contacted less frequently
// until it has reached a state in which it's able to accept a steady stream of
// log entries again.
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
| Probe | 上条探测消息还没被确认 | 收到响应 → `ProbeAcked()` 清 `ProbeSent` |
| Replicate | 在途消息数达到 `MaxInflightMsgs` | 收到 ack → `FreeLE()` 释放窗口 |
| Snapshot | 恒为 true | 快照失败或完成后转出 Snapshot 状态 |

> [!TIP]
> `IsPaused()` 是理解 etcd **为什么不会因为一个慢节点而拖垮整个集群**的关键：慢节点只让自己进入暂停状态，leader 照常给其他节点批量复制。整机吞吐受最慢节点影响，但不会被它阻塞。

## Inflights

`Inflights` 是一个**环形缓冲区**实现的滑动窗口（外置仓库 `tracker/inflights.go`）：

```go
type Inflights struct {
	// the starting index in the buffer
	start int
	// number of inflights in the buffer
	count int

	// the size of the buffer
	size int

	// buffer contains the index of the last entry
	// inside one message.
	buffer []uint64
}
```

`size` 即 Raft 配置里的 `MaxInflightMsgs`。**它同时限制了两个东西**——按结构体注释：*inflight effectively limits both the number of inflight messages and the bandwidth each Progress can use*（在途消息数，以及每个 Progress 能用的带宽）。因为每条消息按 `MaxSizePerMsg` 打包，两者相乘就是单个 follower 的带宽上限。

添加消息时做了溢出保护：

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

缓冲区是**按需增长**而非预分配的，理由写在 `grow()` 的注释里：

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
> 这条注释很有信息量：**一个进程里可能有成千上万个 Raft group**（每个 gRPC session、每个 raft-node 都是一组）。若每个都预分配 `MaxInflightMsgs` 大小的切片，内存开销会爆炸。按需倍增是这里唯一合理的选择。

释放用 `FreeLE`（free less-or-equal），收到 ack 后一次性释放所有 ≤ 该 index 的窗口槽位：

```go
// FreeLE frees the inflights smaller or equal to the given `to` flight.
func (in *Inflights) FreeLE(to uint64) {
	if in.count == 0 || to < in.buffer[in.start] {
		// out of the left side of the window
		return
	}
	// ... 环形遍历找到第一个大于 to 的槽位
	in.count -= i
	in.start = idx
	if in.count == 0 {
		// inflights is empty, reset the start index so that we don't grow the
		// buffer unnecessarily.
		in.start = 0
	}
}
```

`Full()` 与 `Count()` 都很直接：

```go
// Full returns true if no more messages can be sent at the moment.
func (in *Inflights) Full() bool {
	return in.count == in.size
}

// Count returns the number of inflight messages.
func (in *Inflights) Count() int { return in.count }
```

`FreeLE` 里那个"窗口空时把 `start` 归零"的细节也是内存优化：否则长期运行的 group 缓冲区会停在偏移位置，白占空间。

## Rollback Logic

follower 拒绝日志时，leader 要把 `Next` 调回去。`MaybeDecrTo` 处理的正是这件事，它必须区分**真拒绝**和**假拒绝**：

```go
// MaybeDecrTo adjusts the Progress to the receipt of a MsgApp rejection. The
// arguments are the index of the append message rejected by the follower, and
// the hint that we want to decrease to.
//
// Rejections can happen spuriously as messages are sent out of order or
// duplicated. In such cases, the rejection pertains to an index that the
// Progress already knows were previously acknowledged, and false is returned
// without changing the Progress.
//
// If the rejection is genuine, Next is lowered sensibly, and the Progress is
// cleared for sending log entries.
func (pr *Progress) MaybeDecrTo(rejected, matchHint uint64) bool {
	if pr.State == StateReplicate {
		// The rejection must be stale if the progress has matched and "rejected"
		// is smaller than "match".
		if rejected <= pr.Match {
			return false
		}
		// Directly decrease next to match + 1.
		//
		// TODO(tbg): why not use matchHint if it's larger?
		pr.Next = pr.Match + 1
		return true
	}

	// The rejection must be stale if "rejected" does not match next - 1. This
	// is because non-replicating followers are probed one entry at a time.
	if pr.Next-1 != rejected {
		return false
	}

	pr.Next = max(min(rejected, matchHint+1), 1)
	pr.ProbeSent = false
	return true
}
```

两个分支的判据不同，值得展开：

- **Replicate 模式**下乐观发送，`rejected <= pr.Match` 意味着这条拒绝指向一个 follower **早就确认过**的位置——是乱序或重复消息造成的假拒绝，直接忽略。否则退回 `Match + 1`。
- **非 Replicate 模式**是"一次探一条"，所以只有 `rejected == Next - 1` 才是有效拒绝，否则同样忽略；有效时用 `matchHint`（follower 附带的提示）来定位，并**清掉 `ProbeSent` 允许立即重发**。

```go
// TODO(tbg): why not use matchHint if it's larger?
```

这行 TODO 很有意思：Replicate 分支里明明拿到了 `matchHint` 却没用，理由没写。合理推测是 `Match+1` 已经是最安全的选择（不会越过 follower 确认的边界），而 `matchHint` 来自对端、未必可信。

## State Transition

三个 `Become*` 方法对应状态机的三条边，都走 `ResetState` 统一重置辅助字段：

```go
// ResetState moves the Progress into the specified State, resetting ProbeSent,
// PendingSnapshot, and Inflights.
func (pr *Progress) ResetState(state StateType) {
	pr.ProbeSent = false
	pr.PendingSnapshot = 0
	pr.State = state
	pr.Inflights.reset()
}

// ProbeAcked is called when this peer has accepted an append. It resets
// ProbeSent to signal that additional append messages should be sent without
// further delay.
func (pr *Progress) ProbeAcked() {
	pr.ProbeSent = false
}

// BecomeProbe transitions into StateProbe. Next is reset to Match+1 or,
// optionally and if larger, the index of the pending snapshot.
func (pr *Progress) BecomeProbe() {
	// If the original state is StateSnapshot, progress knows that
	// the pending snapshot has been sent to this peer successfully, then
	// probes from pendingSnapshot + 1.
	if pr.State == StateSnapshot {
		pendingSnapshot := pr.PendingSnapshot
		pr.ResetState(StateProbe)
		pr.Next = max(pr.Match+1, pendingSnapshot+1)
	} else {
		pr.ResetState(StateProbe)
		pr.Next = pr.Match + 1
	}
}

// BecomeReplicate transitions into StateReplicate, resetting Next to Match+1.
func (pr *Progress) BecomeReplicate() {
	pr.ResetState(StateReplicate)
	pr.Next = pr.Match + 1
}

// BecomeSnapshot moves the Progress to StateSnapshot with the specified pending
// snapshot index.
func (pr *Progress) BecomeSnapshot(snapshoti uint64) {
	pr.ResetState(StateSnapshot)
	pr.PendingSnapshot = snapshoti
}
```

`BecomeProbe` 的分支最容易漏看：**从 Snapshot 退回时，探测起点是 `pendingSnapshot + 1` 而不是 `Match + 1`**——因为快照已成功送达，那个位置之后的日志才是 follower 真正缺的。

这三个方法在 raft 状态机 `becomeLeader` 的 `reset()` 里被集中调用（代码已随算法外置，不在 etcd 主仓库），那是角色切换时的初始化：

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

`ProgressTracker` 持有全体 Progress（外置仓库 `tracker/tracker.go`），核心是 `Progress` 与 `Voters`（`JointConfig`）两部分：

```go
type ProgressTracker struct {
	Progress map[uint64]*Progress

	Voters   JointConfig
	Learners map[uint64]struct{}
	// maxInflight is the maximum number of in-flight requests that can be
	// sent per peer.
	// ...
	MaxInflight int
}
```

> [!NOTE]
> 这里能看到 **learner 被单独存放**（`Learners` map），不混在 `Progress` 里——因为 learner 的语义是"要追踪进度但不参与投票"，而 `Committed()` 只按 `Voters` 算。

### Commit Watermark and Quorum

回到之前埋的坑，quorum 的判定就是 `Committed()`：

```go
// Committed returns the largest log index known to be committed based on what
// the voting members of the group have acknowledged.
func (p *ProgressTracker) Committed() uint64 {
	return uint64(p.Voters.CommittedIndex(matchAckIndexer(p.Progress)))
}
```

把全体 voter 的 `Match` 排序，取**多数派位置的最小值**——这就是 Raft 论文里的 commit rule。调用点在 `raft.go`：

```go
// maybeCommit attempts to advance the commit index. Returns true if
// the commit index changed (in which case the caller should call
// r.bcastAppend).
func (r *raft) maybeCommit() bool {
	mci := r.prs.Committed()
	return r.raftLog.maybeCommit(mci, r.Term)
}
```

> [!TIP]
> `Committed()` 只统计 **Voters**，`Learners` 不在计算范围内。所以 learner 无论落后多少，都不会影响提交水位——这正是它作为"安全加入集群手段"的价值所在（见 [cluster.md](/docs/CS/Framework/etcd/cluster.md) 的 learner 三步法）。

### Liveness Detection

`MsgCheckQuorum` 依赖的活跃判定同样在这里：

```go
// QuorumActive returns true if the quorum is active from the view of the local
// raft state machine. Otherwise, it returns false.
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

`RecentActive` 由 Progress 结构体注释定义：*Receiving any messages from the corresponding follower indicates the progress is active. RecentActive can be reset to false after an election timeout*（收到该 follower 的任何消息即视为活跃，一个选举超时后可被重置为 false）。

同样**跳过 learner**。连上这两个坑就通了：`MsgCheckQuorum` 检查活跃 voter 数量不足 quorum → leader 主动退位为 follower → 触发新一轮选举。

### Unassigned Traversal

`Visit` 是个性能敏感函数，注释直说了：*We need to sort the IDs and don't want to allocate since this is hot code*。实现用栈上数组兜底，只有成员数超过 7 才真正分配：

```go
// Visit invokes the supplied closure for all tracked progresses in stable order.
func (p *ProgressTracker) Visit(f func(id uint64, pr *Progress)) {
	n := len(p.Progress)
	// We need to sort the IDs and don't want to allocate since this is hot code.
	// The optimization here mirrors that in `(MajorityConfig).CommittedIndex`,
	// see there for details.
	var sl [7]uint64
	var ids []uint64
	if len(sl) >= n {
		ids = sl[:n]
	} else {
		ids = make([]uint64, n)
	}
	for id := range p.Progress {
		n--
		ids[n] = id
	}
	insertionSort(ids)
	for _, id := range ids {
		f(id, p.Progress[id])
	}
}
```

> [!WARNING]
> 注意最后用了**插入排序**而非 `sort.Slice`。这是刻意的——`ids` 此时已经是"倒序填满"的排列（从尾部往前写），插入排序对接近有序的数据是O(n) 的；换成通用排序反而更慢。这类微观优化在共识实现里很常见，因为选举心跳路径每 100ms 就走一遍。

### Observability

`Progress` 与 `ProgressTracker` 都实现了 `String()`，这是**排查线上状态最实用的手段**。注意术语：3.5.34 里 `tracker.go` 的那个 map 类型叫 `ProgressMap`，后续版本已改名为 `Progress`（字段名），而单个 follower 状态始终是 `*Progress`——两个层级同名，读代码时要看接收者是 `map[uint64]*Progress` 还是 `*Progress`：

```go
func (pr *Progress) String() string {
	var buf strings.Builder
	fmt.Fprintf(&buf, "%s match=%d next=%d", pr.State, pr.Match, pr.Next)
	if pr.IsLearner {
		fmt.Fprint(&buf, " learner")
	}
	if pr.IsPaused() {
		fmt.Fprint(&buf, " paused")
	}
	if pr.PendingSnapshot > 0 {
		fmt.Fprintf(&buf, " pendingSnap=%d", pr.PendingSnapshot)
	}
	if !pr.RecentActive {
		fmt.Fprint(&buf, " inactive")
	}
	if n := pr.Inflights.Count(); n > 0 {
		fmt.Fprintf(&buf, " inflight=%d", n)
		if pr.Inflights.Full() {
			fmt.Fprint(&buf, "[full]")
		}
	}
	return buf.String()
}
```

打印形态大致是：

```text
StateReplicate match=1024 next=1088 inflight=3
StateProbe match=1000 next=1001 paused
StateSnapshot match=900 next=0 pendingSnap=2048 learner
StateReplicate match=1024 next=1025 inactive
```

`paused`、`[full]`、`inactive`、learner 尾标都是排查线索：

| 现象 | 含义 |
| :--- | :--- |
| `inactive` | 长时间没收到该 follower 任何消息 |
| `inflight=[full]` | 被 `MaxInflightMsgs` 卡住，接收侧处理不过来 |
| 长期 `StateProbe` | 基本可判定该节点离线（官方注释同此） |
| `pendingSnap` 长期不消 | 快照传输卡住，见 [net.md](/docs/CS/Framework/etcd/net.md) 的 snapshotHandler |

## ConfChange

成员变更是通过 Raft 日志下发的（`MsgProp` → `ConfChangeV2`），leader 应用时调用 `ProgressTracker` 的调整方法。核心约束写在 `ProgressTracker.ConfState()` 里——**learner 身份要单独导出**：

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
> `Voters` 与 `VotersOutgoing` **分两套**：成员变更生效是两阶段的（joint config），变更期间两套都参与 quorum 计算，全部确认后提交 `LearnersNext`。这与 [cluster.md](/docs/CS/Framework/etcd/cluster.md) 里"成员变更必须串行"的要求同源——joint config 期间 quorum 计算规则更复杂，一次改太多会让状态难以推理。

应用 ConfChange 后 `IsLearner` 会被改写，这正是 `becomeLeader` 的 `reset()` 里唯一保留的字段的原因——身份变更与角色切换是两条独立的路径。

## Links

- [raft（共识模块）](/docs/CS/Framework/etcd/raft.md)
- [net（网络层与 Pipeline/Stream）](/docs/CS/Framework/etcd/net.md)
- [cluster（集群运维与成员变更）](/docs/CS/Framework/etcd/cluster.md)
- [monitoring（监控与指标阈值）](/docs/CS/Framework/etcd/monitoring.md)
- [Raft 论文精读](/docs/CS/Distributed/Consensus/Raft.md)

## References

1. [etcd-io/raft：tracker/progress.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/progress.go)
2. [etcd-io/raft：tracker/inflights.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/inflights.go)
3. [etcd-io/raft：tracker/state.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/state.go)
4. [etcd-io/raft：tracker/tracker.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/tracker/tracker.go)
5. [etcd-io/raft：raft.go（外置仓库）](https://github.com/etcd-io/raft/blob/main/raft.go)
6. [In Search of an Understandable Consensus Algorithm (Extended Version)](https://github.com/ongardie/dissertation/blob/master/etcd/extended_paper.pdf)
7. [etcd Documentation - Raft](https://etcd.io/docs/v3.5/architecture/raft/)
