## Introduction

「在 etcd 源码里读 Raft 实现」这件事，在 3.7 已经不成立了。

etcd 3.6 之后，Raft 算法实现从主仓库**物理外置**为独立依赖 `go.etcd.io/raft/v3`。本文基线是 **etcd v3.7.2**（2026-09-22 发布的 latest），其 `go.mod:37` 与 `server/go.mod:30` 都声明 `go.etcd.io/raft/v3 v3.7.0`；主仓库里 `raft/` 与 `server/etcdserver/api/raft/` 两个目录**都不存在**，`find -type d -name raft` 零命中，`.go` 文件里 `tracker` 字符串零命中（含 metrics 层）。外置在 **3.6.5 就已完成**（该版本同样只有 `go.etcd.io/raft/v3 v3.6.0` 依赖，无 raft 源码目录）。

于是「Raft 状态机」这个符号集合——`raft`、`node`、`RawNode`、`Ready`、`MemoryStorage`、`Storage` 接口、`readOnly`、`log`/`unstable`、`tracker.*`、`StateType`——**全部属于外置仓库**。主仓库与 raft 之间的全部关系是「调用侧」：一个 `raftNode` 事件循环 + 一个 `EtcdServer` 状态机。

> [!NOTE]
>
> 本篇所有代码块、行号均取自 `/tmp/etcd-src/etcd-3.7.2` 解压源码，**只贴主仓库文件**。需要算法实现（`stepLeader`、`MaybeDecrTo`、`readOnly` 等）请去 `etcd-io/raft` 仓库；本库 [tracker.md](/docs/CS/Framework/etcd/tracker.md) 已把其中最关键的 `tracker` 部分单独抽出解析。

主仓库里 raft 相关的文件只有 4 个，且**没有 `raft_node.go`**（`raftNode` 定义在 `raft.go:81`）：

| 文件 | 作用 |
| :--- | :--- |
| `server/etcdserver/raft.go` | `raftNode` 事件循环，唯一消费 `Ready` 的地方 |
| `server/etcdserver/zap_raft.go` | 把 `*zap.Logger` 适配成外置库的 `raft.Logger` |
| `server/etcdserver/raft_test.go` | 上述两者的测试 |
| `server/etcdserver/zap_raft_test.go` | 同上 |

本文按这个边界组织：先说清哪些类型在哪边（第 1 节），再用 `raftexample` 这个官方最小示例对齐 3.7.2 的 API（第 2 节），然后逐行拆 `etcdserver` 的封装（第 3 节）与 `Ready` 的五步消费（第 4 节），最后是落盘（第 5 节）、线性读与客户端 Mutex（第 6 节）与陷阱清单。

## 共识层边界

下表逐类型列出归属。**「外置」意味着主仓库里既没有定义、也没有直接引用其内部字段**——主仓库只能通过接口与它交互。

| 符号 | 归属 | 主仓库接触点 |
| :--- | :--- | :--- |
| `raft`（状态机本体）、`StateType`、`StateLeader` 等 | 外置 | 只用常量 `raft.StateLeader`（`raft.go:199`） |
| `node`（`Node` 接口实现）、`Node` 接口 | 外置 | `raftNodeConfig` 内嵌 `raft.Node`（`raft.go:112`），直接调方法 |
| `RawNode`、`Peer`、`Config`、`Status`、`ReadState`、`SnapshotStatus` | 外置 | `raft.Config`、`raft.Status`、`raft.ReadState` |
| `Ready` 结构体 | 外置 | `rd := <-r.Ready()`（`raft.go:185`） |
| `MemoryStorage` | 外置 | `raftStorage *raft.MemoryStorage`（`raft.go:113`） |
| `Storage` 接口（`raft` 包的） | 外置 | **主仓库不引用**；etcd 另有一套自己的 `serverstorage.Storage`（见第 5 节） |
| `log` / `unstable` / `raftLog`、`committedEntryInCurrentTerm` | 外置 | 零引用 |
| `readOnly`（`addRequest`/`advance`/`recvAck`） | 外置 | 零引用，只经 `rd.ReadStates` 间接使用 |
| `tracker.Progress` / `ProgressMap` / `Inflights` / `JointConfig` / `quorum.VoteWon` | 外置 | 零引用（含 metrics 层） |
| `raftpb` 消息与条目类型（`Message`/`Entry`/`HardState`/`Snapshot`/`ConfChange`/`EntryNormal`/`EntryConfChange`） | 外置 | 大量使用，是主仓库与 raft 之间的数据契约 |
| `raftNode`、`raftNodeConfig`、`toApply` | **主仓库** | `raft.go:81` / `:107` / `:70` |
| `raftReadyHandler` | **主仓库** | `server.go:748`（5 个回调，解耦状态机与算法） |
| `apply` / `applyAll` / `applyEntries` / `applySnapshot` / `applyEntryNormal` / `applyConfChange` | **主仓库** | `server.go:1892` / `:972` / `:1945` / `:2007` |
| `configure`（`ProposeConfChange` 调用点） | **主仓库** | `server.go:1755`，`ProposeConfChange` 在 `:1760` |
| `WAL`、`Snapshotter` | **主仓库** | `server/storage/wal/`、`server/etcdserver/api/snap/` |
| `serverstorage.Storage`（etcd 自己的稳定存储接口） | **主仓库** | `server/storage/storage.go` |
| `contrib/raftexample` | **主仓库** | `package main`，**无独立 go.mod**，属主模块 |
| `Mutex`（客户端选主锁） | **主仓库** | `client/v3/concurrency/mutex.go` |

> [!WARNING]
>
> 表里最容易被忽略的一行是 `Storage` 接口。raft 包的 `Storage`（`InitialState`/`Entries`/`Term`/`LastIndex`）已随算法外置；etcd 主仓库在 `server/storage/storage.go` 定义的 `Storage` 是**另一个同名但完全不同的接口**，方法集是 `Save`/`SaveSnap`/`Close`/`Release`/`Sync`/`MinimalEtcdVersion`——它服务于 WAL，不服务于 raft 状态机恢复。两者不要混谈。

## raftexample 最小使用示例

`contrib/raftexample` 是理解「怎么用外置库」的最短路径，13 个文件、`package main`。**它没有自己的 `go.mod`**，属于主模块 `go.etcd.io/etcd/v3`，import 的是外部库：

```go
// contrib/raftexample/raft.go:38-39
"go.etcd.io/raft/v3"
"go.etcd.io/raft/v3/raftpb"
```

### 与 3.5 时代的 API 差异

3.7.2 的 raftexample 相对老资料有**一批指针化与语法现代化**改动，照着老文章抄代码是编不过的：

| 老写法 | 3.7.2 实际 | 位置 |
| :--- | :--- | :--- |
| `confChangeC <-chan raftpb.ConfChange` | `<-chan *raftpb.ConfChange` | `raft.go:50` |
| `confState raftpb.ConfState` | `confState *raftpb.ConfState` | `raft.go:61` |
| `cc.ID = confChangeCount` | `cc.Id = new(confChangeCount)`（泛型 `new`） | `raft.go:442` |
| `publishEntries(ents []raftpb.Entry)` | `[]*raftpb.Entry` | `raft.go:154` |
| `ioutil.ReadAll` | `io.ReadAll` | `httpapi.go:37,56` |
| `r.Method == "PUT"` | `switch r.Method` + `http.MethodPut` | `httpapi.go:35-36` |
| `nodeId` / `ConfChange{NodeID:}` | `nodeID` / `ConfChange{NodeId: new(nodeID)}` | `httpapi.go:63,72` |
| `raftpb.ConfChangeAddNode` | `raftpb.ConfChangeAddNode.Enum()` | `httpapi.go:71` |
| `h.confChangeC <- cc` | `h.confChangeC <- &cc` | `httpapi.go:75` |
| `os.Mkdir(dir, 0750)` | `os.Mkdir(dir, 0o750)` | `raft.go:225,280` |
| `snap.Metadata.Index` | `snap.Metadata.GetIndex()` | `raft.go:355,415-416` |
| `rc.raftStorage.CreateSnapshot(i, rc.confState, data)` | 同签名但 `confState` 已是指针，直接传 | `raft.go:386` |

### 入口：包级函数，不是方法

一个容易踩的点：**raftexample 的 `raftNode` 没有 `start()` 方法**。入口是包级构造函数 `newRaftNode()`，它在内部 `go rc.startRaft()`；`startRaft` 定义在 `raft.go:278`。

```go
// contrib/raftexample/raft.go:89-118（节选）
func newRaftNode(id int, peers []string, join bool, getSnapshot func() ([]byte, error), proposeC <-chan string,
	confChangeC <-chan *raftpb.ConfChange,
) (<-chan *commit, <-chan error, <-chan *snap.Snapshotter) {
	rc := &raftNode{
		proposeC:    proposeC,
		confChangeC: confChangeC,
		// ...
		snapshotterReady: make(chan *snap.Snapshotter, 1),
		// rest of structure populated after WAL replay
	}
	go rc.startRaft()
	return commitC, errorC, rc.snapshotterReady
}
```

`startRaft` 里创建 `Node` 的两行是「启动 vs 重启」的唯一分叉：

```go
// contrib/raftexample/raft.go:306-310
if oldwal || rc.join {
	rc.node = raft.RestartNode(c)
} else {
	rc.node = raft.StartNode(c, rpeers)
}
```

> [!TIP]
>
> **raftexample 完全不调用 `becomeLeader` / `becomeFollower`**——全仓库 grep 这两个符号零命中。角色切换由外置库内部在 `Bootstrap` / `Step` 过程中自行触发。老文章里「`raftNode.start()` 里调用 `becomeFollower()` 做初始化」的说法在 3.7 已经不存在了：主仓库唯一能碰到的角色入口是 `restartNode` 这类构造函数，状态机内部的 `step=stepFollower`、`r.tick=r.tickElection` 全部是外置库的私有细节。

`kvstore` 是 REST 层与 raft 之间的桥。`main.go:33-39` 展示了三个信道的完整闭环：

```go
// contrib/raftexample/main.go:33-39
confChangeC := make(chan *raftpb.ConfChange)
defer close(confChangeC)

// raft provides a commit stream for the proposals from the http api
var kvs *kvstore
getSnapshot := func() ([]byte, error) { return kvs.getSnapshot() }
commitC, errorC, snapshotterReady := newRaftNode(*id, strings.Split(*cluster, ","), *join, getSnapshot, proposeC, confChangeC)

kvs = newKVStore(<-snapshotterReady, proposeC, commitC, errorC)
```

`commitC` 上传的是 `*commit`（`raft.go:42-45`），`data` 为 `nil` 的 `*commit` 是**特殊信号**：既表示「WAL 重放完毕」，也表示「去加载快照」。`kvstore.readCommits` 靠 `commit == nil` 区分这两种语义：

```go
// contrib/raftexample/kvstore.go:75-88（节选）
func (s *kvstore) readCommits(commitC <-chan *commit, errorC <-chan error) {
	for commit := range commitC {
		if commit == nil {
			// signaled to load snapshot
			snapshot, err := s.loadSnapshot()
			if err != nil {
				log.Panic(err)
			}
			if snapshot != nil {
				log.Printf("loading snapshot at term %d and index %d", snapshot.Metadata.Term, snapshot.Metadata.Index)
				if err := s.recoverFromSnapshot(snapshot.Data); err != nil {
					log.Panic(err)
				}
			}
			continue
		}
```

### 构建与运行

注意命令行参数是**两个半角连字符** `--id`（老笔记里写成 em dash `—id` 是错的，官方 `contrib/raftexample/README.md:24` 为准）：

```shell
cd <directory>/src/go.etcd.io/etcd/contrib/raftexample
go build -o raftexample

# single node
raftexample --id 1 --cluster http://127.0.0.1:12379 --port 12380

# local cluster（goreman 拉起三个实例）
goreman start

# test
curl -L http://127.0.0.1:12380/my-key -XPUT -d hello
curl -L http://127.0.0.1:12380/my-key
```

`httpapi.go` 的四个方法映射（`:32-101`）：

| 请求方法 | 处理方式 | 功能 |
| :--- | :--- | :--- |
| `http.MethodPut` | `kvstore.Propose(k, v)` | 更新键值对 |
| `http.MethodGet` | `kvstore.Lookup(k)` | 查找键对应的值 |
| `http.MethodPost` | `confChangeC <- &cc`（`ConfChangeAddNode`） | 将新节点加入集群 |
| `http.MethodDelete` | `confChangeC <- &cc`（`ConfChangeRemoveNode`） | 从集群中移除节点 |

```go
// contrib/raftexample/httpapi.go:70-77
cc := raftpb.ConfChange{
	Type:    raftpb.ConfChangeAddNode.Enum(),
	NodeId:  new(nodeID),
	Context: url,
}
h.confChangeC <- &cc
// As above, optimistic that raft will apply the conf change
w.WriteHeader(http.StatusNoContent)
```

POST/DELETE 都是**乐观返回**（`204 No Content` 不等 apply 完成）；DELETE 若移除的是自己，`publishEntries` 会 `log.Println("I've been removed from the cluster! Shutting down.")` 并返回 `false`，进而 `rc.stop()`（`raft.go:180-186`）。

## etcdserver 的 raft 封装

主仓库的封装与 raftexample 是两套完全不同的东西：raftexample 是**教学用的最小示例**（一个 goroutine 全包），etcdserver 是**生产用的双循环架构**——`raftNode` 只负责「持久化 + 发消息 + 投喂 toApply」，状态机由 `EtcdServer.run()` 的调度器异步消费。两者不要混读。

### toApply：跨循环的数据包

```go
// server/etcdserver/raft.go:66-79
// toApply contains entries, snapshot to be applied. Once
// an toApply is consumed, the entries will be persisted to
// raft storage concurrently; the application must read
// notifyc before assuming the raft messages are stable.
type toApply struct {
	entries  []*raftpb.Entry
	snapshot *raftpb.Snapshot
	// notifyc synchronizes etcd server applies with the raft node
	notifyc chan struct{}
	// raftAdvancedC notifies EtcdServer.apply that
	// 'raftLog.applied' has advanced by r.Advance
	// it should be used only when entries contain raftpb.EntryConfChange
	raftAdvancedC <-chan struct{}
}
```

两个 channel 各管一件事，这是全文最容易被忽略的设计：

- `notifyc`（容量 1，raft 循环写、apply 循环读）：**落盘完成信号**。`applyAll` 在 `<-apply.notifyc` 之后才敢触发快照，否则 applied index 可能超过 raft storage 的 last index。
- `raftAdvancedC`：**只在含 `EntryConfChange` 时使用**。`r.Advance()` 之后才写（`raft.go:333-336`），`applyConfChange` 里 `<-resp.raftAdvanceC` 等它，保证回应客户端前 raft 层已确认（对应 issue #15528）。

### raftNode 与 raftNodeConfig

`raftNodeConfig` 用**内嵌 `raft.Node`** 而不是具名字段——这是主仓库能省略大量转发代码的原因，`r.Tick()`、`r.Ready()`、`r.Advance()`、`r.Step()` 都是内嵌接口方法的直接调用：

```go
// server/etcdserver/raft.go:107-121
type raftNodeConfig struct {
	lg *zap.Logger

	// to check if msg receiver is removed from cluster
	isIDRemoved func(id uint64) bool
	raft.Node
	raftStorage *raft.MemoryStorage
	storage     serverstorage.Storage
	heartbeat   time.Duration // for logging
	// transport specifies the transport to send and receive msgs to members.
	// Sending messages MUST NOT block. It is okay to drop messages, since
	// clients should timeout and reissue their messages.
	// If transport is nil, server will panic.
	transport rafthttp.Transporter
}
```

`raftNode` 本体只加了三类东西：apply/readState/msgSnap 三个信道、`tickMu` 保护的 tick 时间戳、心跳超时检测器 `td`。

```go
// server/etcdserver/raft.go:81-105
type raftNode struct {
	lg *zap.Logger

	tickMu *sync.RWMutex
	// timestamp of the latest tick
	latestTickTs time.Time
	raftNodeConfig

	// a chan to send/receive snapshot
	msgSnapC chan *raftpb.Message

	// a chan to send out apply
	applyc chan toApply

	// a chan to send out read state
	readStateC chan raft.ReadState

	// utility
	ticker *time.Ticker
	// contention detectors for raft heartbeat message
	td *contention.TimeoutDetector

	stopped chan struct{}
	done    chan struct{}
}
```

`newRaftNode`（`:123`）做三件事：建 logger 并 `raft.SetLogger(lg)` 全局注册、按 `heartbeat` 建 ticker（**为 0 时建零值 `time.Ticker{}`，其 `C` 为 nil channel，于是 tick 分支永不触发**）、按 `2 * heartbeat` 建 `TimeoutDetector`。

`tick()` 有一把独立的锁，注释说明了原因：

```go
// server/etcdserver/raft.go:158-170
// raft.Node does not have locks in Raft package
func (r *raftNode) tick() {
	r.tickMu.Lock()
	r.Tick()
	r.latestTickTs = time.Now()
	r.tickMu.Unlock()
}

func (r *raftNode) getLatestTickTs() time.Time {
	r.tickMu.RLock()
	defer r.tickMu.RUnlock()
	return r.latestTickTs
}
```

`latestTickTs` 供监控判断「leader 是否在按节奏发心跳」；`advanceTicks(ticks int)`（`:445`）则用于多机房部署快进选举 tick。

### raftStatus 与 expvar

`raft.status` 这个 expvar 用了一个**函数间接层**，原因写在注释里：expvar 发布后不能删除、重复发布同名会 panic，所以只能注册一个固定 func，内部转调可替换的变量。

```go
// server/etcdserver/raft.go:44-64
var (
	// protects raftStatus
	raftStatusMu sync.Mutex
	// indirection for expvar func interface
	// expvar panics when publishing duplicate name
	// expvar does not support remove a registered name
	// so only register a func that calls raftStatus
	// and change raftStatus as we need.
	raftStatus func() raft.Status
)

func init() {
	expvar.Publish("raft.status", expvar.Func(func() any {
		raftStatusMu.Lock()
		defer raftStatusMu.Unlock()
		if raftStatus == nil {
			return nil
		}
		return raftStatus()
	}))
}
```

赋值点在 `bootstrap.go:561-563`（`raftStatus = n.Status`），读取点有两处：`EtcdServer.raftStatus()`（`server.go:2447`，转发给 `s.r.Node.Status()`）被 `server.go:933`（找新 leader）与 `server.go:1565`（`MemberHandler` 组装 `Status` 响应）使用。

### raftReadyHandler：解耦状态机与算法

raft 循环需要回调状态机，但不该知道状态机的存在。`raftReadyHandler`（`server.go:748`）就是这层薄接口，5 个回调全部在 `EtcdServer.run()` 里用闭包实现（`server.go:766`）：

| 回调 | 触发时机 | 作用 |
| :--- | :--- | :--- |
| `getLead()` | `rd.SoftState != nil` | 读当前 lead，用于判「换 leader」 |
| `updateLead(lead)` | 同上 | 写 `s.setLead` |
| `updateLeadership(newLeader)` | 同上 | 降级时 `lessor.Demote()` + `compactor.Pause()`；升级时 `compactor.Resume()`；换人时 `leaderChanged.Notify()` |
| `updateCommittedIndex(ci)` | 每批 `Ready`（`updateCommittedIndex`，`raft.go:344`） | 单调推进 `committedIndex` |

### 日志适配：zap_raft.go

外置库要求一个 `raft.Logger` 接口，etcd 用 `zap_raft.go` 做适配。三个构造器对应三种已有 logger 形态：

```go
// server/etcdserver/zap_raft.go:26-50
// NewRaftLogger builds "raft.Logger" from "*zap.Config".
func NewRaftLogger(lcfg *zap.Config) (raft.Logger, error) {
	if lcfg == nil {
		return nil, errors.New("nil zap.Config")
	}
	lg, err := lcfg.Build(zap.AddCallerSkip(1)) // to annotate caller outside of "logutil"
	if err != nil {
		return nil, err
	}
	return &zapRaftLogger{lg: lg, sugar: lg.Sugar()}, nil
}

// NewRaftLoggerZap converts "*zap.Logger" to "raft.Logger".
func NewRaftLoggerZap(lg *zap.Logger) raft.Logger {
	skipCallerLg := lg.WithOptions(zap.AddCallerSkip(1))
	return &zapRaftLogger{lg: skipCallerLg, sugar: skipCallerLg.Sugar()}
}
```

`AddCallerSkip(1)` 是必需的：调用方是 `logutil` 的包装层，多跳一层才能报到真正的 raft 代码位置。`zapRaftLogger`（`:52`）逐个转发 12 个方法到 `sugar`，注意 `Warning`/`Warningf` 映射到 zap 的 `Warn`/`Warnf`（`raft.Logger` 用的是 etcd 早期 zap 之前的 `Warning` 命名）。

## Ready 的五个处理步骤

外置库的 `Ready` 结构体定义在 `go.etcd.io/raft/v3`，本篇**不贴**（它已不属于 etcd 主仓库）。这里只讲 etcdserver 如何消费它——全部在 `raft.go:185-243` 及其延伸。

关键前提：`Ready` 里的字段**全部只读**，且处理顺序有强约束（先落盘、再发消息、最后 apply）。etcd 把这个顺序改了一处：**先投 applyc，再落盘**。

### 第 1 步：SoftState —— 认领导权

```go
// server/etcdserver/raft.go:185-207
case rd := <-r.Ready():
	if rd.SoftState != nil {
		newLeader := rd.SoftState.Lead != raft.None && rh.getLead() != rd.SoftState.Lead
		if newLeader {
			leaderChanges.Inc()
		}

		if rd.SoftState.Lead == raft.None {
			hasLeader.Set(0)
		} else {
			hasLeader.Set(1)
		}

		rh.updateLead(rd.SoftState.Lead)
		islead = rd.RaftState == raft.StateLeader
		if islead {
			isLeader.Set(1)
		} else {
			isLeader.Set(0)
		}
		rh.updateLeadership(newLeader)
		r.td.Reset()
	}
```

`islead` 是本轮循环的局部变量，**第 4 步的「leader 先发消息」完全依赖它**。`newLeader` 的判定是「有 leader 且与上次不同」——同一个 leader 反复当选不算变更。

### 第 2 步：ReadStates —— 喂给线性读

```go
// server/etcdserver/raft.go:209-217
if len(rd.ReadStates) != 0 {
	select {
	case r.readStateC <- rd.ReadStates[len(rd.ReadStates)-1]:
	case <-time.After(internalTimeout):
		r.lg.Warn("timed out sending read state", zap.Duration("timeout", internalTimeout))
	case <-r.stopped:
		return
	}
}
```

`internalTimeout` 硬编码为 `time.Second`（`:175`）。只取**最后一个** `ReadState`：`readStateC` 容量为 1，前面的要么已被消费、要么被覆盖——线性读要的是「当前已确认的最新 read index」，早的那些已无意义。消费方见第 6 节。

### 第 3 步：打包 toApply 并投给状态机

```go
// server/etcdserver/raft.go:218-235
committedEntries := rd.CommittedEntries
notifyc := make(chan struct{}, 1)
raftAdvancedC := make(chan struct{}, 1)
raftSnap := proto.Clone(rd.Snapshot).(*raftpb.Snapshot)
ap := toApply{
	entries:       committedEntries,
	snapshot:      proto.Clone(rd.Snapshot).(*raftpb.Snapshot),
	notifyc:       notifyc,
	raftAdvancedC: raftAdvancedC,
}

updateCommittedIndex(&ap, rh)

select {
case r.applyc <- ap:
case <-r.stopped:
	return
}
```

三点值得注意：

- **两次 `proto.Clone`**：一份给 `raftSnap` 供本循环落盘，一份进 `ap`。因为 `Ready` 只在当前批次有效，而 `ap` 要跨 goroutine 活到 `applyAll` 执行完。
- **`notifyc`/`raftAdvancedC` 容量都是 1**：整个设计依赖「至多一次写入、至多一次读取」，所以第 4 步里 `confChanged` 时才做第二次 `notifyc <- struct{}{}`（`:317`）。
- **`updateCommittedIndex`（`:344`）** 取 `entries` 末条与 snapshot index 的较大者，只在非 0 时回调——snapshot 的 index 可能远大于本批 entries。

`applyc` 是**无缓冲**信道（`raft.go:146`），所以这一步会阻塞直到 `EtcdServer.run()` 的调度器接走：

```go
// server/etcdserver/server.go:843-845
case ap := <-s.r.apply():
	f := schedule.NewJob("server_applyAll", func(context.Context) { s.applyAll(&ep, &ap) })
	sched.Schedule(f)
```

FIFO 调度器保证 apply 严格按 raft 产出顺序执行。`applyAll` 的第一行是 `s.applySnapshot(ep, apply)`，第二行 `s.applyEntries(ep, apply)`（`server.go:972-973`）。

> [!NOTE]
>
> `applyAll` 的第二个参数类型是 `*toApply`（不是老笔记里的 `*apply`）：
>
> ```go
> // server/etcdserver/server.go:972
> func (s *EtcdServer) applyAll(ep *etcdProgress, apply *toApply) {
> ```
>
> 同理 `applySnapshot(ep *etcdProgress, toApply *toApply)`。`apply` 只是形参名，容易和 `EtcdServer.apply()` 方法（`server.go:1892`）混淆。

### 第 4 步：落盘

顺序被一条注释严格约束（`:245-246`）：

```go
// server/etcdserver/raft.go:245-262
// Must save the snapshot file and WAL snapshot entry before saving any other entries or hardstate to
// ensure that recovery after a snapshot restore is possible.
if !raft.IsEmptySnap(raftSnap) {
	// gofail: var raftBeforeSaveSnap struct{}
	if err := r.storage.SaveSnap(raftSnap); err != nil {
		r.lg.Fatal("failed to save Raft snapshot", zap.Error(err))
	}
	// gofail: var raftAfterSaveSnap struct{}
}

// gofail: var raftBeforeSave struct{}
if err := r.storage.Save(rd.HardState, rd.Entries); err != nil {
	r.lg.Fatal("failed to save Raft hard state and entries", zap.Error(err))
}
if !raft.IsEmptyHardState(rd.HardState) {
	proposalsCommitted.Set(float64(rd.HardState.GetCommit()))
}
```

快照分支之后还有一段 `Sync` + `ApplySnapshot` + `Release`（`:264-285`），其中 `Sync` 的注释直接引用了 issue #10219——不强制 fsync hard state 就 `Release` 旧 WAL，会触发 `panic: tocommit(107) is out of range [lastIndex(84)]`。最后 `r.raftStorage.Append(rd.Entries)`（`:287`）更新内存态。

### 第 5 步：发消息 + Advance

leader 与 follower 的路径**故意不同**：

```go
// server/etcdserver/raft.go:237-243
// the leader can write to its disk in parallel with replicating to the followers and then
// writing to their disks.
// For more details, check raft thesis 10.2.1
if islead {
	// gofail: var raftBeforeLeaderSend struct{}
	r.transport.Send(r.processMessages(rd.Messages))
}
```

leader 在**投完 applyc 之后立刻发**（不等落盘），这就是论文 10.2.1 的并行优化——注释里 `// ...` 的省略部分正是 follower 路径的完整实现，follower 必须等 `notifyc`（落盘完成）再发，且若本批含 ConfChange 还要**再等一次 apply 完成**：

```go
// server/etcdserver/raft.go:304-321
// Candidate or follower needs to wait for all pending configuration
// changes to be applied before sending messages.
// Otherwise we might incorrectly count votes (e.g. votes from removed members).
// Also slow machine's follower raft-layer could proceed to become the leader
// on its own single-node cluster, before toApply-layer applies the config change.
// We simply wait for ALL pending entries to be applied for now.
// We might improve this later on if it causes unnecessary long blocking issues.

if confChanged {
	// blocks until 'applyAll' calls 'applyWait.Trigger'
	// to be in sync with scheduled config-change job
	// (assume notifyc has cap of 1)
	select {
	case notifyc <- struct{}{}:
	case <-r.stopped:
		return
	}
}

// gofail: var raftBeforeFollowerSend struct{}
r.transport.Send(msgs)
```

最后 `r.Advance()`（`:331`），再在 `confChanged` 时补 `raftAdvancedC <- struct{}{}`（`:333-336`）。

### processMessages：三条过滤规则

发出去之前每条消息过一遍筛（`:357-402`）：

| 规则 | 动作 | 理由 |
| :--- | :--- | :--- |
| `r.isIDRemoved(m.GetTo())` | 丢弃 | 收件人已被移出集群 |
| 多个 `MsgAppResp` | 只留最后一个（`sentAppResp` 标记） | 同一批里的多个 ack 冗余 |
| `MsgSnap` | 转投 `r.msgSnapC`（容量 16，满则丢） | 需要与 v2 store / v3 KV 快照合并，不能由 raft 层直接处理 |
| `MsgHeartbeat` | `r.td.Observe(m.GetTo())`，超时则 `heartbeatSendFailures.Inc()` + WARN | 检测 leader 磁盘过慢 |

`MsgSnap` 的注释解释得很清楚：`raft.go:374-377` —— v2 store 与 v3 KV 是两套数据，`msgSnap` 只含不含 KV 的那部分，必须交给 etcdserver 主循环合并。合并发生在 `applyAll` 尾部（`server.go:988-992`）：`<-s.r.msgSnapC` → `createMergedSnapshotMessage` → `sendMergedSnap`。

> [!TIP]
>
> `maxInFlightMsgSnap = 16`（`server.go:98`）是个背压设计：`select` + `default` 意味着**满了就丢快照消息**而不是阻塞 raft 循环。这是有意的——快照可以由后续 `MsgApp` 重新触发，阻塞 raft 循环的代价更高。

## 日志与快照的落盘

raft 算法外置了，但**持久化全在主仓库**。etcd 的稳定存储是两层：`WAL`（追加日志）+ `Snapshotter`（快照文件）。

### 目录与职责

| 路径 | 内容 |
| :--- | :--- |
| `server/storage/wal/` | WAL 实现（`wal.go` 15 个 Go 文件 + `walpb/`），另有 `server/storage/storage.go` 定义 etcd 自己的 `Storage` 接口 |
| `server/etcdserver/api/snap/` | `snapshotter.go`（文件型快照）、`db.go`（后端 KV 快照）、`snappb/` |

WAL 的公开入口（`server/storage/wal/wal.go`）：

| 函数 | 用途 |
| :--- | :--- |
| `Create`（`:101`）/ `Open`（`:346`）/ `OpenForRead`（`:359`） | 创建 / 打开 / 只读打开 |
| `ReadAll`（`:472`） | 读全量，返回 `([]byte, *raftpb.HardState, []*raftpb.Entry, error)` |
| `Save`（`:995`）/ `SaveSnapshot`（`:1039`）/ `ReleaseLockTo`（`:904`） | 写日志 / 写快照记录 / 释放旧锁 |
| `cut`（`:785`）/ `sync`（`:869`）/ `Sync`（`:896`） | 切段（64MB）/ fsync |
| `ValidSnapshotEntries`（`:608`）/ `LatestSnapshotEntry`（`:597`） | 快照记录查询 |

`server/storage/storage.go` 的 `Storage` 接口只有 6 个方法，注意它服务的是 WAL 而非 raft 状态机：

```go
// server/storage/storage.go
type Storage interface {
	// Save function saves ents and state to the underlying stable storage.
	// Save MUST block until st and ents are on stable storage.
	Save(st *raftpb.HardState, ents []*raftpb.Entry) error
	// SaveSnap function saves snapshot to the underlying stable storage.
	SaveSnap(snap *raftpb.Snapshot) error
	// Close closes the Storage and performs finalization.
	Close() error
	// Release releases the locked wal files older than the provided snapshot.
	Release(snap *raftpb.Snapshot) error
	// Sync WAL
	Sync() error
	// MinimalEtcdVersion returns minimal etcd storage able to interpret WAL log.
	MinimalEtcdVersion() *semver.Version
}
```

> [!WARNING]
>
> 这个接口签名里出现 `*raftpb.HardState` / `[]*raftpb.Entry`，看起来像 raft 包的类型——**它们确实来自外置库**。所以「raft 的 `Storage` 接口已外置」和「etcd 的 WAL 还在主仓库」两件事同时成立：主仓库通过 `raftpb`（数据契约）而不是通过 `raft.Storage`（算法接口）与 raft 相连。

`Snapshotter` 的关键方法（`server/etcdserver/api/snap/snapshotter.go`）：`New`（`:60`）、`SaveSnap`（`:72`）、`Load`（`:112`）、`LoadNewestAvailable`（`:117`）、`ReleaseSnapDBs`（`:259`）、包级 `Read`（`:160`）。

### 启动时的顺序

`EtcdServer.run()`（`server.go:756` 起）第一件事就是从 raft storage 读快照，读不到直接 `lg.Panic`：

```go
// server/etcdserver/server.go:757-762
sn, err := s.r.raftStorage.Snapshot()
if err != nil {
	lg.Panic("failed to get snapshot from Raft storage", zap.Error(err))
}

// asynchronously accept toApply packets, dispatch progress in-order
sched := schedule.NewFIFOScheduler(lg)
```

`Node` 本身在 `bootstrap.go:555-570` 创建（有 peers 走 `StartNode`，否则 `RestartNode`），紧接着把 `n.Status` 挂到 expvar，再构造 `raftNode`。

### 停止顺序有硬约束

`EtcdServer.run()` 的 defer 块（`server.go:826-833`）：

```go
// server/etcdserver/server.go:826-833
// must stop raft after scheduler-- etcdserver can leak rafthttp pipelines
// by adding a peer after raft stops the transport
s.r.stop()

s.Cleanup()

close(s.done)
```

`raftNode.stop()`（`:408`）是**双向握手**——发信号后必须等 `onStop()` 关闭 `done` 才返回。`onStop()`（`:420`）的顺序同样固定：`r.Stop()` → `ticker.Stop()` → `transport.Stop()` → `storage.Close()` → `close(r.done)`。`transport.Stop()` 必须在 `storage.Close()` 之前，否则 rafthttp 可能还在写已关闭的 WAL。

## 线性读与客户端 Mutex

这两个主题都曾写在 raft.md 里，且都属于**主仓库**。

### 线性读已迁 read 包并导出大写

ReadIndex 算法本身在外置库，但 etcdserver 侧的实现已从 `etcdserver` 迁到独立包 `server/etcdserver/read/`，且两个关键方法**导出为大写**：

| 3.5 时代 | 3.7.2 实际 | 位置 |
| :--- | :--- | :--- |
| `s.linearizableReadLoop()` | `read.LinearizableReadLoop` | `read/read.go:96` |
| `s.linearizableReadNotify(ctx)` | `read.LinearizableReadNotify` | `read/read.go:74` |

启动点在 `EtcdServer.Start()`（`server.go:537`）：`s.GoAttach(s.read.LinearizableReadLoop)`。这一版 `Start()` 的内容与旧笔记差异明显：

```go
// server/etcdserver/server.go:529-541
func (s *EtcdServer) Start() {
	s.start()
	s.GoAttach(func() { s.adjustTicks() })
	s.GoAttach(func() { s.publishV3(s.Cfg.ReqTimeout()) })
	s.GoAttach(s.purgeFile)
	s.GoAttach(func() { monitorFileDescriptor(s.Logger(), s.stopping) })
	s.GoAttach(s.monitorClusterVersions)
	s.GoAttach(s.monitorStorageVersion)
	s.GoAttach(s.read.LinearizableReadLoop)
	s.GoAttach(s.monitorKVHash)
	s.GoAttach(s.monitorCompactHash)
	s.GoAttach(s.monitorDowngrade)
}
```

对照旧记录：`goAttach` → `GoAttach`、`publish` → `publishV3`、`monitorVersions` → `monitorClusterVersions`，并新增了 `monitorStorageVersion` / `monitorCompactHash` / `monitorDowngrade` / `adjustTicks`。

`read` 包通过 `raftInterface`（`read/read.go:69-72`）拿 raft 能力，**只暴露两个方法**——与算法相关的接触面被压到最小：

```go
// server/etcdserver/read/read.go:69-72
type raftInterface interface {
	ReadState() <-chan raft.ReadState
	ReadIndex(ctx context.Context, rctx []byte) error
}
```

对应 `raftNode.ReadState()`（`raft.go:451`，返回 `r.readStateC`）与内嵌的 `raft.Node.ReadIndex`。

批量聚合是这一层的设计核心：`LinearizableReadNotify` 只往 `r.waitC` 塞一个信号（**非阻塞 `select` + `default`**），由唯一的 `LinearizableReadLoop` 合并处理：

```go
// server/etcdserver/read/read.go:74-93
func (r *Read) LinearizableReadNotify(ctx context.Context) error {
	r.mux.RLock()
	nc := r.notifier
	r.mux.RUnlock()

	// signal linearizable loop for current notify if it hasn't been already
	select {
	case r.waitC <- struct{}{}:
	default:
	}

	// wait for read state notification
	select {
	case <-nc.c:
		return nc.err
	case <-ctx.Done():
		return ctx.Err()
	case <-r.server.Done():
		return errors.ErrStopped
	}
}
```

循环体（`:96` 起）每次先换一个新 notifier，再 `requestCurrentIndex` 拿 read index，等 `appliedIndex >= confirmedIndex` 后 `nr.notify(nil)` 一次性放行所有等在这个 notifier 上的读。细节见 [read.md](/docs/CS/Framework/etcd/read.md)。

### 客户端 Mutex.TryLock

`client/v3/concurrency/mutex.go` 是纯客户端代码，**与 raft 无关**——它用一条 Txn 的比较-写入实现分布式锁，靠 `CreateRevision` 判所有权：

```go
// client/v3/concurrency/mutex.go:50-70
// TryLock locks the mutex if not already locked by another session.
// If lock is held by another session, return immediately after attempting necessary cleanup
// The ctx argument is used for the sending/receiving Txn RPC.
func (m *Mutex) TryLock(ctx context.Context) error {
	resp, err := m.tryAcquire(ctx)
	if err != nil {
		return err
	}
	// if no key on prefix / the minimum rev is key, already hold the lock
	ownerKey := resp.Responses[1].GetResponseRange().Kvs
	if len(ownerKey) == 0 || ownerKey[0].CreateRevision == m.myRev {
		m.hdr = resp.Header
		return nil
	}
	client := m.s.Client()
	// Cannot lock, so delete the key
	if _, err := client.Delete(ctx, m.myKey); err != nil {
		return err
	}
	m.myKey = "\x00"
	m.myRev = -1
	return ErrLocked
}
```

「获取失败也要删 key」是**清理自己的残留**：`tryAcquire` 里若 `create` 分支成功（key 已存在且 rev 匹配）说明是自己上一轮的锁，若 `create` 成功但 rev 不匹配说明 key 已被别人重建，此时必须删掉自己刚写的那个 key，否则会留下一条永远占位的僵尸锁。`m.myKey = "\x00"` / `m.myRev = -1` 是把本地状态重置到「无锁」。

## 陷阱清单

按「写错就编不过 / 排查跑偏」分类：

**API 与签名（照抄老笔记必错）**

1. `applyAll` / `applySnapshot` 的参数是 `*toApply`，**不是 `*apply`**（`server.go:972`）。
2. 命令行参数是 `--id`（两个半角连字符），老笔记里的 `—id` 是错的。
3. `confChangeC` 通道类型是 `<-chan *raftpb.ConfChange`（`raft.go:50`、`main.go:33`），发送时 `h.confChangeC <- &cc`——`httpapi.go:75`。
4. `raftpb` 字段名是 `NodeId`（生成器 camelCase），不是 `NodeID`；枚举要 `.Enum()`：`raftpb.ConfChangeAddNode.Enum()`。
5. `cc.Id = new(confChangeCount)` 用的是**泛型 `new`**（`raft.go:442`），`etcdserver` 侧同款写法在 `server.go:1757`（`cc.Id = new(s.reqIDGen.Next())`）。
6. `ioutil.ReadAll` 已全部换成 `io.ReadAll`（`httpapi.go:37,56`）。
7. `os.Mkdir` 权限字面量是 `0o750`（`raft.go:225,280`）。
8. protobuf 生成字段一律走 getter：`snap.Metadata.GetIndex()`（`raft.go:355,415-416`）。

**结构性事实（最容易导致整篇分析跑偏）**

9. **raft 算法已外置**为 `go.etcd.io/raft/v3 v3.7.0`（`go.mod:37`、`server/go.mod:30`），3.6.5 即完成。主仓库无 `raft/` 目录、无 `raft_node.go`、无 `tracker` 字符串（含 metrics 层）。
10. **`raftNode` 定义在 `server/etcdserver/raft.go:81`**，不是 `raft_node.go`。
11. **raftexample 的入口是包级 `newRaftNode()`（`raft.go:89`）**，不是 `raftNode.start()` 方法；它内部 `go rc.startRaft()`（`:116`），`startRaft` 在 `:278`。
12. **raftexample 不调用 `becomeLeader` / `becomeFollower`**（全仓库零命中），角色切换由外置库内部触发。
13. **主仓库 `campaign` 零命中**（`etcdserver` 不主动 campaign，靠 `MsgHup` 触发）。`server/etcdserver/api/v3election/` 里的 `Campaign` 是 gRPC 选主接口，与 raft 无关。
14. **raftexample 没有独立 `go.mod`**，属主模块 `go.etcd.io/etcd/v3`。
15. raft 的 `Storage` 接口与 etcd 的 `serverstorage.Storage` **同名不同物**：前者已外置（`InitialState`/`Entries`/`Term`），后者在 `server/storage/storage.go`（`Save`/`SaveSnap`/`Close`/`Release`/`Sync`/`MinimalEtcdVersion`）。

**时序与并发**

16. `ReadState` 每次只取 `rd.ReadStates` 的**最后一个**（`raft.go:211`），前面的会被丢弃。
17. `notifyc` / `raftAdvancedC` 容量均为 1，`raftAdvancedC` **只在含 `EntryConfChange` 时**才写（`raft.go:333-336`）。
18. leader 在**投完 `applyc` 之后、落盘之前**就发消息（`raft.go:237-243`）；follower 必须等落盘，且含 ConfChange 时还要再等 apply（`:304-321`）。把这两条写反是 3.7 笔记的高频错误。
19. `SaveSnap` 必须早于 `Save`（`raft.go:245-246`）；快照分支里的 `Sync()` 早于 `Release()`，否则会触发 issue #10219 的 `tocommit is out of range` panic。
20. `msgSnapC` 容量 16，**满了丢而不是阻塞**（`raft.go:378-383`）。
21. 停机顺序 `r.stop()` → `Cleanup()` 不能反（`server.go:826-829`）；`onStop` 里 `transport.Stop()` 必须早于 `storage.Close()`（`raft.go:420-428`）。

**命名迁移**

22. 线性读两方法已迁 `read` 包并**导出大写**：`LinearizableReadLoop`（`read/read.go:96`）、`LinearizableReadNotify`（`:74`）；调用点 `server.go:537`。
23. `EtcdServer.Start()` 的 `goAttach`/`publish`/`monitorVersions` 已更名 `GoAttach`/`publishV3`/`monitorClusterVersions`，并新增 `monitorStorageVersion`/`monitorCompactHash`/`monitorDowngrade`/`adjustTicks`（`server.go:529-541`）。
24. `zap_raft.go` 的 `NewRaftLoggerFromZapCore` 在 `:46`（旧记 `:45`）；三个构造器都带 `AddCallerSkip(1)`。

**笔记自身的历史缺陷（本篇已修）**

25. 旧版 1650-1778 的 `### raft struct` 标题下贴的其实是 rafthttp 的 `snapshotHandler.ServeHTTP`（真实位置 `server/etcdserver/api/rafthttp/http.go:208`），标题与内容错位。
26. 旧版 Introduction 空白、全文无版本锚点。
27. 旧版把 `readyc` 写成 `case rd := <-rc.node.Ready()` 之外的 `raftNode.start()` 协程（raftexample 语境）并称其处理 `Ready`——在 etcdserver 语境下处理 `Ready` 的是 `raftNode.start(rh *raftReadyHandler)`（`raft.go:174`），两者不要混。

## Links

- [etcd（总览与架构）](/docs/CS/Framework/etcd/etcd.md)
- [tracker（ProgressTracker 与流控）](/docs/CS/Framework/etcd/tracker.md)
- [net（网络层与 Pipeline/Stream）](/docs/CS/Framework/etcd/net.md)
- [read（etcdserver 如何把 ReadIndex 接到 Range 请求）](/docs/CS/Framework/etcd/read.md)
- [Raft 论文精读](/docs/CS/Distributed/Consensus/Raft.md)

## References

1. [etcd-io/raft（外置的 Raft 算法实现仓库）](https://github.com/etcd-io/raft)
2. [etcd v3.7.2 Release Notes](https://github.com/etcd-io/etcd/blob/main/CHANGELOG/CHANGELOG-3.7.md)
3. [In Search of an Understandable Consensus Algorithm (Extended Version)](https://github.com/ongardie/dissertation/blob/master/etcd/extended_paper.pdf)
4. [etcd 源码分析（知乎专栏）](https://www.zhihu.com/column/c_1574793366772060162)
5. [etcd Raft 库解析](https://www.codedump.info/post/20180922-etcd-raft/)
