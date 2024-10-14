## Introduction


## raftexample

raftexample 的目录位于 `etcd/contrib/raftexample/` ，这个目录是一个完整的 package，实现了一个极简的 kv 存储，就是为了专门理解 raft 的

> 回顾[Raft](/docs/CS/Distributed/Raft.md)协议



```shell
cd <directory>/src/go.etcd.io/etcd/contrib/raftexample
go build -o raftexample

# single node
raftexample —id 1 —cluster http://127.0.0.1:12379 —port 12380

# local cluster
goreman start

# test
curl -L http://127.0.0.1:12380/my-key -XPUT -d hello
curl -L http://127.0.0.1:12380/my-key

```



> The raftexample consists of three components: a raft-backed key-value store, a REST API server, and a raft consensus server based on etcd's raft implementation.
> 
> The raft-backed key-value store is a key-value map that holds all committed key-values.
> The store bridges communication between the raft server and the REST server.
> Key-value updates are issued through the store to the raft server.
> The store updates its map once raft reports the updates are committed.
> 
> The REST server exposes the current raft consensus by accessing the raft-backed key-value store.
> A GET command looks up a key in the store and returns the value, if any.
> A key-value PUT command issues an update proposal to the store.
> 
> The raft server participates in consensus with its cluster peers.
> When the REST server submits a proposal, the raft server transmits the proposal to its peers.
> When raft reaches a consensus, the server publishes all committed updates over a commit channel.
> For raftexample, this commit channel is consumed by the key-value store.



httpapi.go是REST服务器的实现

```go

func (h *httpKVAPI) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	key := r.RequestURI
	defer r.Body.Close()
	switch {
	case r.Method == "PUT":
		v, err := ioutil.ReadAll(r.Body)
		if err != nil {
			log.Printf("Failed to read on PUT (%v)\n", err)
			http.Error(w, "Failed on PUT", http.StatusBadRequest)
			return
		}

		h.store.Propose(key, string(v))

		// Optimistic-- no waiting for ack from raft. Value is not yet
		// committed so a subsequent GET on the key may return old value
		w.WriteHeader(http.StatusNoContent)
	case r.Method == "GET":
		if v, ok := h.store.Lookup(key); ok {
			w.Write([]byte(v))
		} else {
			http.Error(w, "Failed to GET", http.StatusNotFound)
		}
	case r.Method == "POST":
		url, err := ioutil.ReadAll(r.Body)
		if err != nil {
			log.Printf("Failed to read on POST (%v)\n", err)
			http.Error(w, "Failed on POST", http.StatusBadRequest)
			return
		}

		nodeId, err := strconv.ParseUint(key[1:], 0, 64)
		if err != nil {
			log.Printf("Failed to convert ID for conf change (%v)\n", err)
			http.Error(w, "Failed on POST", http.StatusBadRequest)
			return
		}

		cc := raftpb.ConfChange{
			Type:    raftpb.ConfChangeAddNode,
			NodeID:  nodeId,
			Context: url,
		}
		h.confChangeC <- cc

		// As above, optimistic that raft will apply the conf change
		w.WriteHeader(http.StatusNoContent)
	case r.Method == "DELETE":
		nodeId, err := strconv.ParseUint(key[1:], 0, 64)
		if err != nil {
			log.Printf("Failed to convert ID for conf change (%v)\n", err)
			http.Error(w, "Failed on DELETE", http.StatusBadRequest)
			return
		}

		cc := raftpb.ConfChange{
			Type:   raftpb.ConfChangeRemoveNode,
			NodeID: nodeId,
		}
		h.confChangeC <- cc

		// As above, optimistic that raft will apply the conf change
		w.WriteHeader(http.StatusNoContent)
	default:
		w.Header().Set("Allow", "PUT")
		w.Header().Add("Allow", "GET")
		w.Header().Add("Allow", "POST")
		w.Header().Add("Allow", "DELETE")
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}
```



| 请求方法 | 处理方式             | 功能             |
| -------- | -------------------- | ---------------- |
| PUT      | kvstore.Propose(k,v) | 更新键值对       |
| GET      | kvstore.Lookup(k)    | 查找键对应的值   |
| POST     | confChangeC <- cc    | 将新节点加入集群 |
| DELETE   | confChangeC <- cc    | 从集群中移除节点 |

`kvstore`是连接raft服务器与REST服务器的桥梁，是实现键值存储功能的重要组件



```go
// a key-value store backed by raft
type kvstore struct {
	proposeC    chan<- string // channel for proposing updates
	mu          sync.RWMutex
	kvStore     map[string]string // current committed key-value pairs
	snapshotter *snap.Snapshotter
}

type kv struct {
	Key string
	Val string
}
```

`newKVStore`函数的参数除了`snapshotter`外，`proposeC`、`commitC`、`errorC`均为信道。其中`propseC`为输入信道，`commitC`和`errorC`为输出信道。我们可以推断出，`kvstore`会通过`proposeC`与raft模块交互，并通过`commitC`与`errorC`接收来自raft模块的消息。（可以在`main.go`中证实，这里不再赘述。）这种方式在etcd的实现中随处可见，因此对于go语言和channel不是很熟悉的小伙伴建议预先学习一下相关概念与使用方法。（当熟悉了这种设计后，便会发现go语言并发编程的魅力所在。）

`newKVStore`中的逻辑也非常简单，将传入的参数写入`kvstore`结构体相应的字段中。然后先调用一次`kvstore`的`readCommits`方法，等待raft模块重放日志完成的信号；然后启动一个goroutine来循环处理来自raft模块发送过来的消息

```go
func newKVStore(snapshotter *snap.Snapshotter, proposeC chan<- string, commitC <-chan *commit, errorC <-chan error) *kvstore {
	s := &kvstore{proposeC: proposeC, kvStore: make(map[string]string), snapshotter: snapshotter}
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
	// read commits from raft into kvStore map until error
	go s.readCommits(commitC, errorC)
	return s
}
```



lookup`方法会通过读锁来访问其用来记录键值的map，防止查找时数据被修改返回错误的结果。`Propose`方法将要更新的键值对编码为string，并传入`proposeC`信道，交给raft模块处理。`getSnapshot`和`recoverFromSnapshot`方法分别将记录键值的map序列化与反序列化，并加锁防止争用

```go

func (s *kvstore) Lookup(key string) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	v, ok := s.kvStore[key]
	return v, ok
}

func (s *kvstore) Propose(k string, v string) {
	var buf bytes.Buffer
	if err := gob.NewEncoder(&buf).Encode(kv{k, v}); err != nil {
		log.Fatal(err)
	}
	s.proposeC <- buf.String()
}

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

		for _, data := range commit.data {
			var dataKv kv
			dec := gob.NewDecoder(bytes.NewBufferString(data))
			if err := dec.Decode(&dataKv); err != nil {
				log.Fatalf("raftexample: could not decode message (%v)", err)
			}
			s.mu.Lock()
			s.kvStore[dataKv.Key] = dataKv.Val
			s.mu.Unlock()
		}
		close(commit.applyDoneC)
	}
	if err, ok := <-errorC; ok {
		log.Fatal(err)
	}
}

func (s *kvstore) getSnapshot() ([]byte, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return json.Marshal(s.kvStore)
}

func (s *kvstore) loadSnapshot() (*raftpb.Snapshot, error) {
	snapshot, err := s.snapshotter.Load()
	if err == snap.ErrNoSnapshot {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return snapshot, nil
}

func (s *kvstore) recoverFromSnapshot(snapshot []byte) error {
	var store map[string]string
	if err := json.Unmarshal(snapshot, &store); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.kvStore = store
	return nil
}
```



在raftexample中，raft服务器被封装成了一个`raftNode`结构体

```go

// A key-value stream backed by raft
type raftNode struct {
	proposeC    <-chan string            // proposed messages (k,v)
	confChangeC <-chan raftpb.ConfChange // proposed cluster config changes
	commitC     chan<- *commit           // entries committed to log (k,v)
	errorC      chan<- error             // errors from raft session

	id          int      // client ID for raft session
	peers       []string // raft peer URLs
	join        bool     // node is joining an existing cluster
	waldir      string   // path to WAL directory
	snapdir     string   // path to snapshot directory
	getSnapshot func() ([]byte, error)

	confState     raftpb.ConfState
	snapshotIndex uint64
	appliedIndex  uint64

	// raft backing for the commit/error channel
	node        raft.Node
	raftStorage *raft.MemoryStorage
	wal         *wal.WAL

	snapshotter      *snap.Snapshotter
	snapshotterReady chan *snap.Snapshotter // signals when snapshotter is ready

	snapCount uint64
	transport *rafthttp.Transport
	stopc     chan struct{} // signals proposal channel closed
	httpstopc chan struct{} // signals http server to shutdown
	httpdonec chan struct{} // signals http server shutdown complete

	logger *zap.Logger
}
```

在结构体中，有4个用于与其它组件交互的信道：

| 信道                                 | 描述                                                       |
| ------------------------------------ | ---------------------------------------------------------- |
| proposeC <-chan string               | 接收来自其它组件传入的需要通过raft达成共识的普通提议。     |
| confChangeC <-chan raftpb.ConfChange | 接收来自其它组件的需要通过raft达成共识的集群变更提议。     |
| commitC chan<- *string               | 用来已通过raft达成共识的已提交的提议通知给其它组件的信道。 |
| errorC chan<- error                  | 用来将错误报告给其它组件的信道。                           |

在结构体中，还保存了etcd/raft提供的接口与其所需的相关组件：

| 字段                                    | 描述                                                         |
| --------------------------------------- | ------------------------------------------------------------ |
| node raft.Node                          | etcd/raft的核心接口，对于一个最简单的实现来说，开发者只需要与该接口打交道即可实现基于raft的服务。 |
| raftStorage *raft.MemoryStorage         | 用来保存raft状态的接口，etcd/raft/storage.go中定义了etcd/raft模块所需的稳定存储接口，并提供了一个实现了该接口的内存存储`MemoryStorage`注1，raftexample中就使用了该实现。 |
| wal *wal.WAL                            | 预写日志实现，raftexample直接使用了etcd/wal模块中的实现。    |
| snapshotter *snap.Snapshotter           | 快照管理器的指针                                             |
| snapshotterReady chan *snap.Snapshotter | 一个用来发送snapshotter加载完毕的信号的“一次性”信道。因为snapshotter的创建对于新建raftNode来说是一个异步的过程，因此需要通过该信道来通知创建者snapshotter已经加载完成。 |
| snapCount uint64                        | 当wal中的日志超过该值时，触发快照操作并压缩日志。            |
| transport *rafthttp.Transport           | etcd/raft模块通信时使用的接口。同样，这里使用了基于http的默认实现。 |

### newRaftNode

```go

// newRaftNode initiates a raft instance and returns a committed log entry
// channel and error channel. Proposals for log updates are sent over the
// provided the proposal channel. All log entries are replayed over the
// commit channel, followed by a nil message (to indicate the channel is
// current), then new log entries. To shutdown, close proposeC and read errorC.
func newRaftNode(id int, peers []string, join bool, getSnapshot func() ([]byte, error), proposeC <-chan string,
	confChangeC <-chan raftpb.ConfChange) (<-chan *commit, <-chan error, <-chan *snap.Snapshotter) {

	commitC := make(chan *commit)
	errorC := make(chan error)

	rc := &raftNode{
		proposeC:    proposeC,
		confChangeC: confChangeC,
		commitC:     commitC,
		errorC:      errorC,
		id:          id,
		peers:       peers,
		join:        join,
		waldir:      fmt.Sprintf("raftexample-%d", id),
		snapdir:     fmt.Sprintf("raftexample-%d-snap", id),
		getSnapshot: getSnapshot,
		snapCount:   defaultSnapshotCount,
		stopc:       make(chan struct{}),
		httpstopc:   make(chan struct{}),
		httpdonec:   make(chan struct{}),

		logger: zap.NewExample(),

		snapshotterReady: make(chan *snap.Snapshotter, 1),
		// rest of structure populated after WAL replay
	}
	go rc.startRaft()
	return commitC, errorC, rc.snapshotterReady
}
```



`startRaft`方法虽然看上去很长，但是实现的功能很简单。

首先，`startRaft`方法检查快照目录是否存在，如果不存在为其创建目录。然后创建基于该目录的快照管理器。创建完成后，向`snapshotterReady`信道写入该快照管理器，通知其快照管理器已经创建完成。

接着，程序检查是否有旧的预写日志存在，并重放旧的预写日志，重放代码在下文中会进一步分析。

在重放完成后，程序设置了etcd/raft模块所需的配置，并从该配置上启动或重启节点（取决于有没有旧的预写日志文件）。`etcd/raft`中的`raft.StartNode`和`raft.RestartNode`函数分别会根据配置启动或重启raft服务器节点，并返回一个`Node`接口的实例。正如前文中提到的，`Node`接口是开发者依赖etcd/raft实现时唯一需要与其打交道的接口。程序将`Node`接口的实例记录在了`raftNode`的`node`字段中。

在`node`创建完成后，程序配置并开启了通信模块，开始与集群中的其它raft节点通信。

在一切接续后，程序启动了两个goroutine，分别是`raftNode.serveRaft()`和`raftNode.serveChannels()`。其中`raftNode.serveRaft()`用来监听来自其它raft节点的消息，消息的处理主要在`Transport`接口的实现中编写`raftNode.serveChannels()`用来处理`raftNode`中各种信道

```go

func (rc *raftNode) startRaft() {
	if !fileutil.Exist(rc.snapdir) {
		if err := os.Mkdir(rc.snapdir, 0750); err != nil {
			log.Fatalf("raftexample: cannot create dir for snapshot (%v)", err)
		}
	}
	rc.snapshotter = snap.New(zap.NewExample(), rc.snapdir)

	oldwal := wal.Exist(rc.waldir)
	rc.wal = rc.replayWAL()

	// signal replay has finished
	rc.snapshotterReady <- rc.snapshotter

	rpeers := make([]raft.Peer, len(rc.peers))
	for i := range rpeers {
		rpeers[i] = raft.Peer{ID: uint64(i + 1)}
	}
	c := &raft.Config{
		ID:                        uint64(rc.id),
		ElectionTick:              10,
		HeartbeatTick:             1,
		Storage:                   rc.raftStorage,
		MaxSizePerMsg:             1024 * 1024,
		MaxInflightMsgs:           256,
		MaxUncommittedEntriesSize: 1 << 30,
	}

	if oldwal || rc.join {
		rc.node = raft.RestartNode(c)
	} else {
		rc.node = raft.StartNode(c, rpeers)
	}

	rc.transport = &rafthttp.Transport{
		Logger:      rc.logger,
		ID:          types.ID(rc.id),
		ClusterID:   0x1000,
		Raft:        rc,
		ServerStats: stats.NewServerStats("", ""),
		LeaderStats: stats.NewLeaderStats(zap.NewExample(), strconv.Itoa(rc.id)),
		ErrorC:      make(chan error),
	}

	rc.transport.Start()
	for i := range rc.peers {
		if i+1 != rc.id {
			rc.transport.AddPeer(types.ID(i+1), []string{rc.peers[i]})
		}
	}

	go rc.serveRaft()
	go rc.serveChannels()
}
```

#### replayWAL

`replayWAL`方法为`raftNode`重放其预写日志并返回日志文件。首先该方法会通过`raftNode.loadSnapshot()`方法加载快照，如果快照该方法不存在会返回`nil`。接着，通过`raftNode.openWAL(snapshot)`方法打开预写日志。该方法会根据快照中的日志元数据（这里的元数据与论文中的一样，记录了快照覆盖的最后一个日志条目的index和term）打开相应的预写日志，如果快照不存在，则会为打开或创建一个从初始状态开始的预写日志（当节点第一次启动时，既没有快照文件又没有预写日志文件，此时会为其创建预写日志文件；而节点是重启但重启前没有记录过日志，则会为其打开已有的从初始状态开始的预写日志）。之后，程序将快照应用到raft的存储（`MemoryStorage`）中，并将预写日志中记录的硬状态（`HardState`）应用到存储中（硬状态是会被持久化的状态，etcd/raft对论文中的实现进行了优化，因此保存的状态稍有不同。本文目的是通过示例介绍etcd/raft模块的简单使用方式，给读者对etcd中raft实现的基本印象，其实现机制会在后续的文章中分析）。

除了快照之外，重放时还需要将预写日志中的日志条目应用到存储中（快照之后的持久化状态）。如果预写日志中没有条目，说明节点重启前的最终状态就是快照的状态（对于第一次启动的来说则为初始状态），此时会通过向`commitC`信道写入`nil`值通知`kvstore`已经完成日志的重放；而如果预写日志中有条目，则这些日志需要被重放，为了复用代码，这部分日志的重放逻辑没有在`replayWAL`中实现，在`replayWAL`中仅将这部分日志的最后一个日志条目的`Index`记录到`raftNode.lastIndex`中。在应用日志条目的代码中，程序会检查应用的日志的`Index`是否等于`raftNode.lastIndex`，如果相等，说明旧日志重放完毕，然后`commitC`信道写入`nil`值通知`kvstore`已经完成日志的重放



#### serveChannels

`raftNode.serveChannels()`是raft服务器用来处理各种信道的输入输出的方法，也是与etcd/raft模块中`Node`接口的实现交互的方法。

`serverChannels()`方法可以分为两个部分，该方法本身会循环处理raft有关的逻辑，如处理定时器信号驱动`Node`、处理`Node`传入的`Ready`结构体、处理通信模块报告的错误或停止信号灯等；该方法还启动了一个goroutine，该goroutine中循环处理来自`proposeC`和`confChangeC`两个信道的消息。



















## raft

etcd-raft 最大设计亮点就是抽离了网络、持久化、协程等逻辑，用一个纯粹的 raft StateMachine 来实现 raft 算法逻辑，充分的解耦，有助于 raft 算法本身的正确实现，而且更容易纯粹的去测试 raft 算法最本质的逻辑，而不需要考虑引入其他因素（各种异常）


etcd-raft StateMachine 封装在 raft struct 中，其状态如下



```go
type StateType uint64

var stmap = [...]string{
    “StateFollower”,
    “StateCandidate”,
    “StateLeader”,
    “StatePreCandidate”,
}

func (st StateType) String() string {
    return stmap[uint64(st)]
}
```

状态转换如下图

<div style="text-align: center;">

![Fig.1. Comparison of the five I/O models](img/StateMachine.svg)

</div>

<p style="text-align: center;">Fig.1. State Machine</p>



raft state 转换的调用接口

```go
func (r *raft) becomeFollower(term uint64, lead uint64)
func (r *raft) becomePreCandidate()
func (r *raft) becomeCandidate() 
func (r *raft) becomeLeader()
```




etcd 将 raft 相关的所以处理都抽象为了 Msg，通过 Step 接口处理
```go
func (r *raft) Step(m pb.Message) error {
    // ... Handle the message term, which may result in our stepping down to a follower.

    switch m.Type {
    // ...

    default:
        err := r.step(r, m)
    }
    return nil
}

```


其中 step 是一个回调函数，在不同的 state 会设置不同的回调函数来驱动 raft，这个回调函数 stepFunc 就是在 become* 函数完成的设置

```go
type raft struct {
    // ...
    step stepFunc
}

```


step 回调函数有如下几个值，其中 stepCandidate 会处理 PreCandidate 和 Candidate 两种状态

```go
func stepFollower(r *raft, m pb.Message) error 
func stepCandidate(r *raft, m pb.Message) error
func stepLeader(r *raft, m pb.Message) error
```



所有的外部处理请求经过 raft StateMachine 处理都会首先被转换成统一抽象的输入 Message（Msg），
Msg 会通过 raft.Step(m) 接口完成 raft StateMachine 的处理，Msg 分两类：

- 本地 Msg，term = 0，这种 Msg 并不会经过网络发送给 Peer，只是将 Node 接口的一些请求转换成 raft StateMachine 统一处理的抽象 Msg，这里以 Propose 接口为例，向 raft 提交一个 Op 操作，其会被转换成 MsgProp，通过 raft.Step() 传递给 raft StateMachine，最后可能被转换成给 Peer 复制 Op log 的 MsgApp Msg；（即发送给本地peer的消息）
- 非本地 Msg，term 非 0，这种 Msg 会经过网络发送给 Peer；这里以 Msgheartbeat 为例子，就是 Leader 给 Follower 发送的心跳包。但是这个 MsgHeartbeat Msg 是通过 Tick 接口传入的，这个接口会向 raft StateMachine 传递一个 MsgBeat Msg，raft StateMachine 处理这个 MsgBeat 就是向复制组其它 Peer 分别发送一个 MsgHeartbeat Msg





Ready

由于 etcd 的网络、持久化模块和 raft 核心是分离的，所以当 raft 处理到某一些阶段的时候，需要输出一些东西，给外部处理，例如 Op log entries 持久化，Op log entries 复制的 Msg 等；以 heartbeat 为例，输入是 MsgBeat Msg，经过状态机状态化之后，就变成了给复制组所有的 Peer 发送心跳的 MsgHeartbeat Msg；在 ectd 中就是通过一个 Ready 的数据结构来封装当前 Raft state machine 已经准备好的数据和 Msg 供外部处理。下面是 Ready 的数据结构






## Node

node启动时是启动了一个协程，处理node的里的多个通道，包括tickc，调用tick()方法
该方法会动态改变，对于follower和candidate，它就是tickElection，对于leader和，它就是tickHeartbeat。tick就像是一个etcd节点的心脏跳动，在follower这里，每次tick会去检查是不是leader的心跳是不是超时了。对于leader，每次tick都会检查是不是要发送心跳了



startNode -> NewRawNode -> newRaft


### run



## start


raft.newRaft


```go
func newRaft(c *Config) *raft {
   if err := c.validate(); err != nil {
      panic(err.Error())
   }
   raftlog := newLogWithSize(c.Storage, c.Logger, c.MaxCommittedSizePerReady)
   hs, cs, err := c.Storage.InitialState()

   r := &raft{
      id:                        c.ID,
      lead:                      None,
      isLearner:                 false,
      raftLog:                   raftlog,
      maxMsgSize:                c.MaxSizePerMsg,
      maxUncommittedSize:        c.MaxUncommittedEntriesSize,
      prs:                       tracker.MakeProgressTracker(c.MaxInflightMsgs),
      electionTimeout:           c.ElectionTick,
      heartbeatTimeout:          c.HeartbeatTick,
      logger:                    c.Logger,
      checkQuorum:               c.CheckQuorum,
      preVote:                   c.PreVote,
      readOnly:                  newReadOnly(c.ReadOnlyOption),
      disableProposalForwarding: c.DisableProposalForwarding,
   }

   cfg, prs, err := confchange.Restore(confchange.Changer{
      Tracker:   r.prs,
      LastIndex: raftlog.lastIndex(),
   }, cs)
   if err != nil {
      panic(err)
   }
   assertConfStatesEquivalent(r.logger, cs, r.switchToConfig(cfg, prs))

   if !IsEmptyHardState(hs) {
      r.loadState(hs)
   }
   if c.Applied > 0 {
      raftlog.appliedTo(c.Applied)
   }
   r.becomeFollower(r.Term, None)

   var nodesStrs []string
   for _, n := range r.prs.VoterNodes() {
      nodesStrs = append(nodesStrs, fmt.Sprintf("%x", n))
   }

   r.logger.Infof("newRaft %x [peers: [%s], term: %d, commit: %d, applied: %d, lastindex: %d, lastterm: %d]",
      r.id, strings.Join(nodesStrs, ","), r.Term, r.raftLog.committed, r.raftLog.applied, r.raftLog.lastIndex(), r.raftLog.lastTerm())
   return r
}
```





### folllower

```go
func (r *raft) becomeFollower(term uint64, lead uint64) {
   r.step = stepFollower
   r.reset(term)
   r.tick = r.tickElection
   r.lead = lead
   r.state = StateFollower
   r.logger.Infof("%x became follower at term %d", r.id, r.Term)
}
```



tick 其实是由外层业务定时驱动的，t.tickElection竞争Leader

```go
func (r *raft) tickElection() {
   r.electionElapsed++

   if r.promotable() && r.pastElectionTimeout() {
      r.electionElapsed = 0
      r.Step(pb.Message{From: r.id, Type: pb.MsgHup})
   }
}
```



如果Cluster开启PreVote模式 当Follower选举计时器timout后会调用becomePreCandidate切换state到PreCandidate



```go
func (r *raft) becomePreCandidate() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateLeader {
      panic("invalid transition [leader -> pre-candidate]")
   }
   // Becoming a pre-candidate changes our step functions and state,
   // but doesn't change anything else. In particular it does not increase
   // r.Term or change r.Vote.
   r.step = stepCandidate
   r.prs.ResetVotes()
   r.tick = r.tickElection
   r.lead = None
   r.state = StatePreCandidate
   r.logger.Infof("%x became pre-candidate at term %d", r.id, r.Term)
}
```

当节点可联系到半数以上节点后 调用

```go
func (r *raft) becomeCandidate() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateLeader {
      panic("invalid transition [leader -> candidate]")
   }
   r.step = stepCandidate
   r.reset(r.Term + 1)
   r.tick = r.tickElection
   r.Vote = r.id
   r.state = StateCandidate
   r.logger.Infof("%x became candidate at term %d", r.id, r.Term)
}
```



获取quorum后

### becomeLeader

当集群已经产生了leader，则leader会在固定间隔内给所有节点发送心跳。其他节点收到心跳以后重置心跳等待时间，只要心跳等待不超时，follower的状态就不会改变。
具体的过程如下：
1. 对于leader，tick被设置为tickHeartbeat，tickHeartbeat会产生增长递增心跳过期时间计数(heartbeatElapsed)，如果心跳过期时间超过了心跳超时时间计数(heartbeatTimeout)，它会产生一个MsgBeat消息。心跳超时时间计数是系统设置死的，就是1。也就是说只要1次tick时间过去，基本上会发送心跳消息。发送心跳首先是调用状态机的step方法
```go
func (r *raft) becomeLeader() {
   // TODO(xiangli) remove the panic when the raft implementation is stable
   if r.state == StateFollower {
      panic("invalid transition [follower -> leader]")
   }
   r.step = stepLeader
   r.reset(r.Term)
   r.tick = r.tickHeartbeat
   r.lead = r.id
   r.state = StateLeader
   // Followers enter replicate mode when they've been successfully probed
   // (perhaps after having received a snapshot as a result). The leader is
   // trivially in this state. Note that r.reset() has initialized this
   // progress with the last index already.
   r.prs.Progress[r.id].BecomeReplicate()

   // Conservatively set the pendingConfIndex to the last index in the
   // log. There may or may not be a pending config change, but it's
   // safe to delay any future proposals until we commit all our
   // pending log entries, and scanning the entire tail of the log
   // could be expensive.
   r.pendingConfIndex = r.raftLog.lastIndex()

   emptyEnt := pb.Entry{Data: nil}
   if !r.appendEntry(emptyEnt) {
      // This won't happen because we just called reset() above.
      r.logger.Panic("empty entry was dropped")
   }
   // As a special case, don't count the initial empty entry towards the
   // uncommitted log quota. This is because we want to preserve the
   // behavior of allowing one entry larger than quota if the current
   // usage is zero.
   r.reduceUncommittedSize([]pb.Entry{emptyEnt})
   r.logger.Infof("%x became leader at term %d", r.id, r.Term)
}
```



appendEntry

```go
func (r *raft) appendEntry(es ...pb.Entry) (accepted bool) {
   li := r.raftLog.lastIndex()
   for i := range es {
      es[i].Term = r.Term
      es[i].Index = li + 1 + uint64(i)
   }
   // Track the size of this uncommitted proposal.
   if !r.increaseUncommittedSize(es) {
      r.logger.Debugf(
         "%x appending new entries to log would exceed uncommitted entry size limit; dropping proposal",
         r.id,
      )
      // Drop the proposal.
      return false
   }
   // use latest "last" index after truncate/append
   li = r.raftLog.append(es...)
   r.prs.Progress[r.id].MaybeUpdate(li)
   // Regardless of maybeCommit's return, our caller will call bcastAppend.
   r.maybeCommit()
   return true
}
```





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
```



commit

```go
func (r *raft) maybeCommit() bool {
   mci := r.prs.Committed()
   return r.raftLog.maybeCommit(mci, r.Term)
}
```







## Log



```go
type Entry struct {
	Term  uint64    `protobuf:"varint,2,opt,name=Term" json:"Term"`
	Index uint64    `protobuf:"varint,3,opt,name=Index" json:"Index"`
	Type  EntryType `protobuf:"varint,1,opt,name=Type,enum=raftpb.EntryType" json:"Type"`
	Data  []byte    `protobuf:"bytes,4,opt,name=Data" json:"Data,omitempty"`
}
```





里面有两个存储位置，一个是storage是保存已经持久化过的日志条目。unstable是保存的尚未持久化的日志条目

```go

type raftLog struct {
	// storage contains all stable entries since the last snapshot.
	storage Storage

	// unstable contains all unstable entries and snapshot.
	// they will be saved into storage.
	unstable unstable

	// committed is the highest log position that is known to be in
	// stable storage on a quorum of nodes.
	committed uint64
	// applied is the highest log position that the application has
	// been instructed to apply to its state machine.
	// Invariant: applied <= committed
	applied uint64

	logger Logger

	// maxNextEntsSize is the maximum number aggregate byte size of the messages
	// returned from calls to nextEnts.
	maxNextEntsSize uint64
}
```



storage包含一个WAL来保存日志条目，一个Snapshotter负责保存日志快照的

```go
type storage struct {
	*wal.WAL
	*snap.Snapshotter
}

type Storage interface {
	// Save function saves ents and state to the underlying stable storage.
	// Save MUST block until st and ents are on stable storage.
	Save(st raftpb.HardState, ents []raftpb.Entry) error
	// SaveSnap function saves snapshot to the underlying stable storage.
	SaveSnap(snap raftpb.Snapshot) error
	// Close closes the Storage and performs finalization.
	Close() error
	// Release releases the locked wal files older than the provided snapshot.
	Release(snap raftpb.Snapshot) error
	// Sync WAL
	Sync() error
}
```





WAL是一种追加的方式将日志条目一条一条顺序存放在文件中。存放在WAL的记录都是walpb.Record形式的结构。Type代表数据的类型，Crc是生成的Crc校验字段。Data是真正的数据。v3版本中，有如下几种Type：
- metadataType：元数据类型，元数据会保存当前的node id和cluster id。
- entryType：日志条目
- stateType：存放的是集群当前的状态HardState，如果集群的状态有变化，就会在WAL中存放一个新集群状态数据。里面包括当前Term，当前竞选者、当前已经commit的日志。
- crcType：存放crc校验字段。读取数据是，会根据这个记录里的crc字段对前面已经读出来的数据进行校验。
- snapshotType：存放snapshot的日志点。包括日志的Index和Term

```go
// WAL is a logical representation of the stable storage.
// WAL is either in read mode or append mode but not both.
// A newly created WAL is in append mode, and ready for appending records.
// A just opened WAL is in read mode, and ready for reading records.
// The WAL will be ready for appending after reading out all the previous records.
type WAL struct {
	lg *zap.Logger

	dir string // the living directory of the underlay files

	// dirFile is a fd for the wal directory for syncing on Rename
	dirFile *os.File

	metadata []byte           // metadata recorded at the head of each WAL
	state    raftpb.HardState // hardstate recorded at the head of WAL

	start     walpb.Snapshot // snapshot to start reading
	decoder   *decoder       // decoder to decode records
	readClose func() error   // closer for decode reader

	unsafeNoSync bool // if set, do not fsync

	mu      sync.Mutex
	enti    uint64   // index of the last entry saved to the wal
	encoder *encoder // encoder to encode records

	locks []*fileutil.LockedFile // the locked files the WAL holds (the name is increasing)
	f
```

WAL有read模式和write模式，区别是write模式会使用文件锁开启独占文件模式。read模式不会独占文件



Snapshotter 提供保存快照的SaveSnap方法。在v2中，快照实际就是storage中存的那个node组成的树结构。它是将整个树给序列化成了json。在v3中，快照是boltdb数据库的数据文件，通常就是一个叫db的文件。v3的处理实际代码比较混乱，并没有真正走snapshotter





### newLog

初始化storage字段

```go
func newLog(storage Storage, logger Logger) *raftLog {
   return newLogWithSize(storage, logger, noLimit)
}

// newLogWithSize returns a log using the given storage and max message size.
func newLogWithSize(storage Storage, logger Logger, maxNextEntsSize uint64) *raftLog {
   if storage == nil {
      log.Panic("storage must not be nil")
   }
   log := &raftLog{
      storage:         storage,
      logger:          logger,
      maxNextEntsSize: maxNextEntsSize,
   }
   firstIndex, err := storage.FirstIndex()
   if err != nil {
      panic(err) // TODO(bdarnell)
   }
   lastIndex, err := storage.LastIndex()
   if err != nil {
      panic(err) // TODO(bdarnell)
   }
   log.unstable.offset = lastIndex + 1
   log.unstable.logger = logger
   // Initialize our committed and applied pointers to the time of the last compaction.
   log.committed = firstIndex - 1
   log.applied = firstIndex - 1

   return log
}
```



### append

```go
func (l *raftLog) maybeAppend(index, logTerm, committed uint64, ents ...pb.Entry) (lastnewi uint64, ok bool) {
   if l.matchTerm(index, logTerm) {
      lastnewi = index + uint64(len(ents))
      ci := l.findConflict(ents)
      switch {
      case ci == 0:
      case ci <= l.committed:
         l.logger.Panicf("entry %d conflict with committed entry [committed(%d)]", ci, l.committed)
      default:
         offset := index + 1
         l.append(ents[ci-offset:]...)
      }
      l.commitTo(min(committed, lastnewi))
      return lastnewi, true
   }
   return 0, false
}
```



#### matchTerm

```go
func (l *raftLog) matchTerm(i, term uint64) bool {
   t, err := l.term(i)
   if err != nil {
      return false
   }
   return t == term
}
```

先去unstable查询 否则去storage里查询

```go
func (l *raftLog) term(i uint64) (uint64, error) {
   // the valid term range is [index of dummy entry, last index]
   dummyIndex := l.firstIndex() - 1
   if i < dummyIndex || i > l.lastIndex() {
      // TODO: return an error instead?
      return 0, nil
   }

   if t, ok := l.unstable.maybeTerm(i); ok {
      return t, nil
   }

   t, err := l.storage.Term(i)
   if err == nil {
      return t, nil
   }
   if err == ErrCompacted || err == ErrUnavailable {
      return 0, err
   }
   panic(err) // TODO(bdarnell)
}
```



#### findConflict

```go
func (l *raftLog) findConflict(ents []pb.Entry) uint64 {
   for _, ne := range ents {
      if !l.matchTerm(ne.Index, ne.Term) {
         if ne.Index <= l.lastIndex() {
            l.logger.Infof("found conflict at index %d [existing term: %d, conflicting term: %d]",
               ne.Index, l.zeroTermOnErrCompacted(l.term(ne.Index)), ne.Term)
         }
         return ne.Index
      }
   }
   return 0
}
```









## ReadIndex

当收到一个线性读请求时，被请求的server首先会从Leader获取集群最新的已提交的日志索引(committed index)

Leader收到ReadIndex请求时，为防止脑裂等异常场景，会向Follower节点发送心跳确认，一半以上节点确认Leader身份后才能将已提交的索引(committed index)返回给节点C

被请求节点则会等待，直到状态机已应用索引(applied index)大于等于Leader的已提交索引时(committed Index)(上图中的流程四)，然后去通知读请求，数据已赶上Leader，你可以去状态机中访问数据了

以上就是线性读通过ReadIndex机制保证数据一致性原理， 当然还有其它机制也能实现线性读，如在早期etcd 3.0中读请求通过走一遍Raft协议保证一致性， 这种Raft log read机制依赖磁盘IO， 性能相比ReadIndex较差











## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

