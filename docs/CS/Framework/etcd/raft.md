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

`kvstore`是连接raft服务器与REST服务器的桥梁，是实现键值存储功能的重要组件 与键值对相关的请求都会通过`kvstore`提供的方法处理，而有关集群配置的请求则是会编码为`etcd/raft/v3/raftpb`中proto定义的消息格式，直接传入`confChangeC`信道。从`main.go`可以看出，该信道的消费者是raft模块



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

#### readCommits

readCommits方法会循环遍历`commitC`信道中raft模块传来的消息。从`commitC`中收到的消息可能为nil或非nil。因为raftexample功能简单，因此其通过nil表示raft模块完成重放日志的信号或用来通知`kvstore`从上一个快照恢复的信号

当`data`为nil时，该方法会通过`kvstore`的快照管理模块`snapshotter`尝试加载上一个快照。如果快照存在，说明这是通知其恢复快照的信号，接下来会调用`recoverFromSnapshot`方法从该快照中恢复，随后进入下一次循环，等待日志重放完成的信号；如果没找到快照，那么说明这是raft模块通知其日志重放完成的信号，因此直接返回

当`data`非nil时，说明这是raft模块发布的已经通过共识提交了的键值对。此时，先从字节数组数据中反序列化出键值对，并加锁修改map中的键值对

```go
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
```









### raftNode



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

#### newRaftNode

在创建raftNode时，需要提供节点`id`、对等节点url`peers`、是否是要加入已存在的集群`join`、获取快照的函数签名`getSnapshot`、提议信道`proposeC`、配置变更提议信道`confChangeC`这些参数

在`newRaftNode`函数中，仅初始化了`raftNode`的部分参数，其余的参数会在重放预写日志后配置。随后，该函数启动了一个协程，该协程调用了`raftNode`的`startRaft()`方法来启动raft节点。当前函数会将raft模块用来通知已提交的提议的信道、报错信道、和快照管理器加载完成信号的信道返回给调用者



首先，该方法从当前的快照的元数据设置`raftNode`的相关字段，并设置一个每100毫秒产生一个信号的循环定时器。`serveChannels`的循环会根据这个信号调用`Node`接口的`Tick()`方法，驱动`Node`执行

```go
func (rc *raftNode) serveChannels() {
    snap, err := rc.raftStorage.Snapshot()
    if err != nil {
        panic(err)
    }
    rc.confState = snap.Metadata.ConfState
    rc.snapshotIndex = snap.Metadata.Index
    rc.appliedIndex = snap.Metadata.Index

    defer rc.wal.Close()

    ticker := time.NewTicker(100 * time.Millisecond)
    defer ticker.Stop()
    // ...
}
```

在循环中，如果`proposeC`或`confChangeC`中的一个被关闭，程序会将其置为`nil`，所以只有二者均不是`nil`时才执行循环。每次循环会通过select选取一个有消息传入的信道，通过`Node`接口提交给raft服务器。当循环结束后，关闭`stopc`信道，即发送关闭信号

```go
func (rc *raftNode) serveChannels() {
    // ...
    // send proposals over raft
    go func() {
        confChangeCount := uint64(0)

        for rc.proposeC != nil && rc.confChangeC != nil {
            select {
            case prop, ok := <-rc.proposeC:
                if !ok {
                    rc.proposeC = nil
                } else {
                    // blocks until accepted by raft state machine
                    rc.node.Propose(context.TODO(), []byte(prop))
                }

            case cc, ok := <-rc.confChangeC:
                if !ok {
                    rc.confChangeC = nil
                } else {
                    confChangeCount++
                    cc.ID = confChangeCount
                    rc.node.ProposeConfChange(context.TODO(), cc)
                }
            }
        }
        // client closed channel; shutdown raft if not already
        close(rc.stopc)
    }()
    // ...
}
```

该循环同时监听4个信道：

1. 循环定时器的信道，每次收到信号后，调用`Node`接口的`Tick`函数驱动`Node`。
2. `Node.Ready()`返回的信道，每当`Node`准备好一批数据后，会将数据通过该信道发布。开发者需要对该信道收到的`Ready`结构体中的各字段进行处理。在处理完成一批数据后，开发者还需要调用`Node.Advance()`告知`Node`这批数据已处理完成，可以继续传入下一批数据。
3. 通信模块报错信道，收到来自该信道的错误后`raftNode`会继续上报该错误，并关闭节点。
4. 用来表示停止信号的信道，当该信道被关闭时，阻塞的逻辑会从该分支运行，关闭节点。

其中，`Node.Ready()`返回的信道逻辑最为复杂。因为其需要处理raft状态机传入的各种数据，并交付给相应的模块处理

```go
func (rc *raftNode) serveChannels() {
    // ...
    // event loop on raft state machine updates
    for {
        select {
        case <-ticker.C:
            rc.node.Tick()

        // store raft entries to wal, then publish over commit channel
        case rd := <-rc.node.Ready():
            rc.wal.Save(rd.HardState, rd.Entries)
            if !raft.IsEmptySnap(rd.Snapshot) {
                rc.saveSnap(rd.Snapshot)
                rc.raftStorage.ApplySnapshot(rd.Snapshot)
                rc.publishSnapshot(rd.Snapshot)
            }
            rc.raftStorage.Append(rd.Entries)
            rc.transport.Send(rd.Messages)
            applyDoneC, ok := rc.publishEntries(rc.entriesToApply(rd.CommittedEntries))
            if !ok {
                rc.stop()
                return
            }
            rc.maybeTriggerSnapshot(applyDoneC)
            rc.node.Advance()

        case err := <-rc.transport.ErrorC:
            rc.writeError(err)
            return

        case <-rc.stopc:
            rc.stop()
            return
        }
    }
}
```



#### startRaft

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





etcd/raft的`Ready`结构体中包含如下数据：



```go
// Ready encapsulates the entries and messages that are ready to read,
// be saved to stable storage, committed or sent to other peers.
// All fields in Ready are read-only.
type Ready struct {
    // The current volatile state of a Node.
    // SoftState will be nil if there is no update.
    // It is not required to consume or store SoftState.
    *SoftState

    // The current state of a Node to be saved to stable storage BEFORE
    // Messages are sent.
    // HardState will be equal to empty state if there is no update.
    pb.HardState

    // ReadStates can be used for node to serve linearizable read requests locally
    // when its applied index is greater than the index in ReadState.
    // Note that the readState will be returned when raft receives msgReadIndex.
    // The returned is only valid for the request that requested to read.
    ReadStates []ReadState

    // Entries specifies entries to be saved to stable storage BEFORE
    // Messages are sent.
    Entries []pb.Entry

    // Snapshot specifies the snapshot to be saved to stable storage.
    Snapshot pb.Snapshot

    // CommittedEntries specifies entries to be committed to a
    // store/state-machine. These have previously been committed to stable
    // store.
    CommittedEntries []pb.Entry

    // Messages specifies outbound messages to be sent AFTER Entries are
    // committed to stable storage.
    // If it contains a MsgSnap message, the application MUST report back to raft
    // when the snapshot has been received or has failed by calling ReportSnapshot.
    Messages []pb.Message

    // MustSync indicates whether the HardState and Entries must be synchronously
    // written to disk or if an asynchronous write is permissible.
    MustSync bool
}
```

`Ready`结构体中各个字段的注释已经很好地说明了其处理方式，这很有助于我们理解raftexample中对`Ready`信道的处理方式：

1. 将`HardState`和`Entries`写入预写日志，将其保存在稳定存储上。
2. 如果有快照，现将快照保存到稳定存储中，然后应用快照，最后通过向`commitC`写入`nil`值通知`kvstore`加载快照。（省略的一些细节。）
3. 将`Entries`追加到`MemoryStorage`中（第1步仅写入到了预写日志中）。
4. 通过通信模块将`Messages`中的消息分发给其它raft节点。
5. 通过`publishEntries`方法发布新增的日志条目。
6. 通过`maybeTriggerSnapshot`方法检查`MemoryStorage`中日志条目长度，如果超过设定的最大长度，则触发快照机制并压缩日志。



虽然看上去步骤较多，但是处理逻辑都很简单。这里我们仅看一下第5步的逻辑。

在第5步中，首先通过`entriesToApply`方法，从`Ready`结构体的`Entries`字段中找到还没有应用到本地状态机中的日志起点即后续日志条目。然后通过`publishEntries`方法发布这些日志条目。





`publishEntries`会遍历传入的日志列表，对于普通的日志条目，先将其反序列化，通过`commitC`信道传给`kvstore`处理；对于用于变更集群配置的日志，则根据变更的内容（如增加或删除集群中的某个节点），修改通信模块中的相关记录。然后修改`appliedIndex`为当前日志的`Index`。除此之外，`publishEntries`还判断了日志`Index`是否为前文中提到的`lastIndex`。如果当前`Index`等于`lastIndex`，则说明之前的操作是在重放日志，且此时日志重放完成，因此需要向`commitC`信道写入`nil`以通知`kvstore`日志重放完成



```go
// publishEntries writes committed log entries to commit channel and returns
// whether all entries could be published.
func (rc *raftNode) publishEntries(ents []raftpb.Entry) (<-chan struct{}, bool) {
    if len(ents) == 0 {
        return nil, true
    }

    data := make([]string, 0, len(ents))
    for i := range ents {
        switch ents[i].Type {
        case raftpb.EntryNormal:
            if len(ents[i].Data) == 0 {
                // ignore empty messages
                break
            }
            s := string(ents[i].Data)
            data = append(data, s)
        case raftpb.EntryConfChange:
            var cc raftpb.ConfChange
            cc.Unmarshal(ents[i].Data)
            rc.confState = *rc.node.ApplyConfChange(cc)
            switch cc.Type {
            case raftpb.ConfChangeAddNode:
                if len(cc.Context) > 0 {
                    rc.transport.AddPeer(types.ID(cc.NodeID), []string{string(cc.Context)})
                }
            case raftpb.ConfChangeRemoveNode:
                if cc.NodeID == uint64(rc.id) {
                    log.Println("I've been removed from the cluster! Shutting down.")
                    return nil, false
                }
                rc.transport.RemovePeer(types.ID(cc.NodeID))
            }
        }
    }

    var applyDoneC chan struct{}

    if len(data) > 0 {
        applyDoneC = make(chan struct{}, 1)
        select {
        case rc.commitC <- &commit{data, applyDoneC}:
        case <-rc.stopc:
            return nil, false
        }
    }

    // after commit, update appliedIndex
    rc.appliedIndex = ents[len(ents)-1].Index

    return applyDoneC, true
}
```

propc channel 由 node 启动时运行的一个协程处理，调用 raft 的 Step()方法，如果当前节点是 follower，实际就是调用 stepFollower()。而 stepFollower 对 MsgProp 消息的处理就是：直接转发给 leader

leader 在接收到 MsgProp 消息以后，会调用 appendEntries()将日志 append 到 raftLog 中。这时候日志已经保存到了 leader 的缓存中



leader 在 append 日志以后会调用 bcastAppend()广播日志给所有其他节点。raft 结构中有一个 Progress 数组，这个数组是 leader 用来保存各个 follower 当前的同步状态的，由于不同实例运行的硬件环境、网络等条件不同，各 follower 同步日志的快慢不一样，因此 leader 会在本地记录每个 follower 当前同步到哪了，才能在每次同步日志的时候知道需要发送那些日志过去。Progress 中有一个 Match 字段，代表其中一个 follower 当前已经同步过的最新的 index。而 Next 字段是需要 leader 发送给它的下一条日志的 index



sendAppend 先根据 Progress 中的 Next 字段获取前一条日志的 term，这个是为了给 follower 校验用的，待会我们会讲到。然后获取本地的日志条目到 ents。获取的时候是从 Next 字段开始往后取，直到达到单条消息承载的最大日志条数(如果没有达到最大日志条数，就取到最新的日志结束，细节可以看 raftLog 的 entries 方法

1. 如果获取日志有问题，说明 Next 字段标示的日志可能已经过期，需要同步 snapshot，这个就是上图的 if 语句里面的内容。这部分我们等 snapshot 的时候再细讲。
2. 正常获取到日志以后，就把日志塞到 Message 的 Entries 字段中，Message 的 Type 为 MsgApp，表示这是一条同步日志的消息。Index 设置为 Next-1，和 LogTerm 一样，都是为了给 follower 校验用的，下面会详细讲述。设置 commit 为 raftLog 的 commited 字段，这个是给 follower 设置它的本地缓存里面的 commited 用的。最后的那个"switch pr.State"是一个优化措施，它在 send 之前就将 pr 的 Next 值设置为准备发送的日志的最大 index+1。意思是我还没有发出去，就认为它发完了，后面比如 leader 接收到 heartbeat response 以后也可以直接发送 entries。
3. follower 接收到 MsgApp 以后会调用 handleAppendEntries()方法处理。处理逻辑是：如果 index 小于已经确认为 commited 的 index，说明这些日志已经过期了，则直接回复 commited 的 index。否则，调用 maybeAppend()把日志 append 到 raftLog 里面。maybeAppend 的处理比较重要。首先它通过判断消息中的 Index 和 LogTerm 来判断发来的这批日志的前一条日志和本地存的是不是一样，如果不一样，说明 leader 和 follower 的日志在 Index 这个地方就没有对上号了，直接返回不能 append。如果是一样的，再进去判断发来的日志里面有没有和本地有冲突（有可能有些日志前面已经发过来同步过，所以会出现 leader 发来的日志已经在 follower 这里存了）。如果有冲突，就从第一个冲突的地方开始覆盖本地的日志



follower 调用完 maybeAppend 以后会调用 send 发送 MsgAppResp，把当前已经 append 的日志最新 index 告诉给 leader。如果是 maybeAppend 返回了 false 说明不能 append，会回复 Reject 消息给 leader。消息和日志最后都是在 raftNode.start()启动的协程里面处理的。它会先持久化日志，然后发送消息

follower 调用完 maybeAppend 以后会调用 send 发送 MsgAppResp，把当前已经 append 的日志最新 index 告诉给 leader。如果是 maybeAppend 返回了 false 说明不能 append，会回复 Reject 消息给 leader。消息和日志最后都是在 raftNode.start()启动的协程里面处理的。它会先持久化日志，然后发送消息



leader 收到 follower 回复的 MsgAppResp 以后，首先判断如果 follower reject 了日志，就把 Progress 的 Next 减回到 Match+1，从已经确定同步的日志开始从新发送日志。如果没有 reject 日志，就用刚刚已经发送的日志 index 更新 Progess 的 Match 和 Next，下一次发送日志就可以从新的 Next 开始了。然后调用 maybeCommit 把多数节点同步的日志设置为 commited



commited 会随着 MsgHeartbeat 或者 MsgApp 同步给 follower。随后 leader 和 follower 都会将 commited 的日志 apply 到状态机中，也就是会更新 kv 存储





日志的持久化是调用 WAL 的 Save 完成的，同时如果有 raft 状态变更也会写到 WAL 中(作为 stateType)。日志会顺序地写入文件。同时使用 MustSync 判断是不是要调用操作系统的系统调用 fsync，fsync 是一次真正的 io 调用。从 MustSync 函数可以看到，只要有 log 条目，或者 raft 状态有变更，都会调用 fsync 持久化。最后我们看到如果写得太多超过了一个段大小的话(一个段是 64MB，就是 wal 一个文件的大小)。会调用 cut()拆分文件


propc channel 由 node 启动时运行的一个协程处理，调用 raft 的 Step()方法，如果当前节点是 follower，实际就是调用 stepFollower()。而 stepFollower 对 MsgProp 消息的处理就是：直接转发给 leader
leader 在接收到 MsgProp 消息以后，会调用 appendEntries()将日志 append 到 raftLog 中。这时候日志已经保存到了 leader 的缓存中

leader 在 append 日志以后会调用 bcastAppend()广播日志给所有其他节点。raft 结构中有一个 Progress 数组，这个数组是 leader 用来保存各个 follower 当前的同步状态的，由于不同实例运行的硬件环境、网络等条件不同，各 follower 同步日志的快慢不一样，因此 leader 会在本地记录每个 follower 当前同步到哪了，才能在每次同步日志的时候知道需要发送那些日志过去。Progress 中有一个 Match 字段，代表其中一个 follower 当前已经同步过的最新的 index。而 Next 字段是需要 leader 发送给它的下一条日志的 index

sendAppend 先根据 Progress 中的 Next 字段获取前一条日志的 term，这个是为了给 follower 校验用的，待会我们会讲到。然后获取本地的日志条目到 ents。获取的时候是从 Next 字段开始往后取，直到达到单条消息承载的最大日志条数(如果没有达到最大日志条数，就取到最新的日志结束，细节可以看 raftLog 的 entries 方法
1. 如果获取日志有问题，说明 Next 字段标示的日志可能已经过期，需要同步 snapshot，这个就是上图的 if 语句里面的内容。这部分我们等 snapshot 的时候再细讲。
2. 正常获取到日志以后，就把日志塞到 Message 的 Entries 字段中，Message 的 Type 为 MsgApp，表示这是一条同步日志的消息。Index 设置为 Next-1，和 LogTerm 一样，都是为了给 follower 校验用的，下面会详细讲述。设置 commit 为 raftLog 的 commited 字段，这个是给 follower 设置它的本地缓存里面的 commited 用的。最后的那个"switch pr.State"是一个优化措施，它在 send 之前就将 pr 的 Next 值设置为准备发送的日志的最大 index+1。意思是我还没有发出去，就认为它发完了，后面比如 leader 接收到 heartbeat response 以后也可以直接发送 entries。
3. follower 接收到 MsgApp 以后会调用 handleAppendEntries()方法处理。处理逻辑是：如果 index 小于已经确认为 commited 的 index，说明这些日志已经过期了，则直接回复 commited 的 index。否则，调用 maybeAppend()把日志 append 到 raftLog 里面。maybeAppend 的处理比较重要。首先它通过判断消息中的 Index 和 LogTerm 来判断发来的这批日志的前一条日志和本地存的是不是一样，如果不一样，说明 leader 和 follower 的日志在 Index 这个地方就没有对上号了，直接返回不能 append。如果是一样的，再进去判断发来的日志里面有没有和本地有冲突（有可能有些日志前面已经发过来同步过，所以会出现 leader 发来的日志已经在 follower 这里存了）。如果有冲突，就从第一个冲突的地方开始覆盖本地的日志

 follower 调用完 maybeAppend 以后会调用 send 发送 MsgAppResp，把当前已经 append 的日志最新 index 告诉给 leader。如果是 maybeAppend 返回了 false 说明不能 append，会回复 Reject 消息给 leader。消息和日志最后都是在 raftNode.start()启动的协程里面处理的。它会先持久化日志，然后发送消息
follower 调用完 maybeAppend 以后会调用 send 发送 MsgAppResp，把当前已经 append 的日志最新 index 告诉给 leader。如果是 maybeAppend 返回了 false 说明不能 append，会回复 Reject 消息给 leader。消息和日志最后都是在 raftNode.start()启动的协程里面处理的。它会先持久化日志，然后发送消息

leader 收到 follower 回复的 MsgAppResp 以后，首先判断如果 follower reject 了日志，就把 Progress 的 Next 减回到 Match+1，从已经确定同步的日志开始从新发送日志。如果没有 reject 日志，就用刚刚已经发送的日志 index 更新 Progess 的 Match 和 Next，下一次发送日志就可以从新的 Next 开始了。然后调用 maybeCommit 把多数节点同步的日志设置为 commited

commited 会随着 MsgHeartbeat 或者 MsgApp 同步给 follower。随后 leader 和 follower 都会将 commited 的日志 apply 到状态机中，也就是会更新 kv 存储


日志的持久化是调用 WAL 的 Save 完成的，同时如果有 raft 状态变更也会写到 WAL 中(作为 stateType)。日志会顺序地写入文件。同时使用 MustSync 判断是不是要调用操作系统的系统调用 fsync，fsync 是一次真正的 io 调用。从 MustSync 函数可以看到，只要有 log 条目，或者 raft 状态有变更，都会调用 fsync 持久化。最后我们看到如果写得太多超过了一个段大小的话(一个段是 64MB，就是 wal 一个文件的大小)。会调用 cut()拆分文件















## raft

etcd-raft 最大设计亮点就是抽离了网络、持久化、协程等逻辑，用一个纯粹的 raft StateMachine 来实现 raft 算法逻辑，充分的解耦，有助于 raft 算法本身的正确实现，而且更容易纯粹的去测试 raft 算法最本质的逻辑，而不需要考虑引入其他因素（各种异常）



### Node

`Node`接口是开发者仅有的操作etcd/raft的方式

```go

// Node represents a node in a raft cluster.
type Node interface {
	// Tick increments the internal logical clock for the Node by a single tick. Election
	// timeouts and heartbeat timeouts are in units of ticks.
	Tick()
	// Campaign causes the Node to transition to candidate state and start campaigning to become leader.
	Campaign(ctx context.Context) error
	// Propose proposes that data be appended to the log. Note that proposals can be lost without
	// notice, therefore it is user's job to ensure proposal retries.
	Propose(ctx context.Context, data []byte) error
	// ProposeConfChange proposes a configuration change. Like any proposal, the
	// configuration change may be dropped with or without an error being
	// returned. In particular, configuration changes are dropped unless the
	// leader has certainty that there is no prior unapplied configuration
	// change in its log.
	//
	// The method accepts either a pb.ConfChange (deprecated) or pb.ConfChangeV2
	// message. The latter allows arbitrary configuration changes via joint
	// consensus, notably including replacing a voter. Passing a ConfChangeV2
	// message is only allowed if all Nodes participating in the cluster run a
	// version of this library aware of the V2 API. See pb.ConfChangeV2 for
	// usage details and semantics.
	ProposeConfChange(ctx context.Context, cc pb.ConfChangeI) error

	// Step advances the state machine using the given message. ctx.Err() will be returned, if any.
	Step(ctx context.Context, msg pb.Message) error

	// Ready returns a channel that returns the current point-in-time state.
	// Users of the Node must call Advance after retrieving the state returned by Ready.
	//
	// NOTE: No committed entries from the next Ready may be applied until all committed entries
	// and snapshots from the previous one have finished.
	Ready() <-chan Ready

	// Advance notifies the Node that the application has saved progress up to the last Ready.
	// It prepares the node to return the next available Ready.
	//
	// The application should generally call Advance after it applies the entries in last Ready.
	//
	// However, as an optimization, the application may call Advance while it is applying the
	// commands. For example. when the last Ready contains a snapshot, the application might take
	// a long time to apply the snapshot data. To continue receiving Ready without blocking raft
	// progress, it can call Advance before finishing applying the last ready.
	Advance()
	// ApplyConfChange applies a config change (previously passed to
	// ProposeConfChange) to the node. This must be called whenever a config
	// change is observed in Ready.CommittedEntries, except when the app decides
	// to reject the configuration change (i.e. treats it as a noop instead), in
	// which case it must not be called.
	//
	// Returns an opaque non-nil ConfState protobuf which must be recorded in
	// snapshots.
	ApplyConfChange(cc pb.ConfChangeI) *pb.ConfState

	// TransferLeadership attempts to transfer leadership to the given transferee.
	TransferLeadership(ctx context.Context, lead, transferee uint64)

	// ReadIndex request a read state. The read state will be set in the ready.
	// Read state has a read index. Once the application advances further than the read
	// index, any linearizable read requests issued before the read request can be
	// processed safely. The read state will have the same rctx attached.
	// Note that request can be lost without notice, therefore it is user's job
	// to ensure read index retries.
	ReadIndex(ctx context.Context, rctx []byte) error

	// Status returns the current status of the raft state machine.
	Status() Status
	// ReportUnreachable reports the given node is not reachable for the last send.
	ReportUnreachable(id uint64)
	// ReportSnapshot reports the status of the sent snapshot. The id is the raft ID of the follower
	// who is meant to receive the snapshot, and the status is SnapshotFinish or SnapshotFailure.
	// Calling ReportSnapshot with SnapshotFinish is a no-op. But, any failure in applying a
	// snapshot (for e.g., while streaming it from leader to follower), should be reported to the
	// leader with SnapshotFailure. When leader sends a snapshot to a follower, it pauses any raft
	// log probes until the follower can apply the snapshot and advance its state. If the follower
	// can't do that, for e.g., due to a crash, it could end up in a limbo, never getting any
	// updates from the leader. Therefore, it is crucial that the application ensures that any
	// failure in snapshot sending is caught and reported back to the leader; so it can resume raft
	// log probing in the follower.
	ReportSnapshot(id uint64, status SnapshotStatus)
	// Stop performs any necessary termination of the Node.
	Stop()
}
```



`Node`结构中的方法按调用时机可以分为三类：

|        方法        | 描述                                                         |
| :----------------: | :----------------------------------------------------------- |
|       `Tick`       | 由时钟（循环定时器）驱动，每隔一定时间调用一次，驱动`raft`结构体的内部时钟运行。 |
| `Ready`、`Advance` | 这两个方法往往成对出现。准确的说，是`Ready`方法返回的`Ready`结构体信道的信号与`Advance`方法成对出现。每当从`Ready`结构体信道中收到来自`raft`的消息时，用户需要按照一定顺序对`Ready`结构体中的字段进行处理。在完成对`Ready`的处理后，需要调用`Advance`方法，通知`raft`这批数据已经处理完成，可以继续传入下一批。 |
|      其它方法      | 需要时随时调用。                                             |



Now that you are holding onto a Node you have a few responsibilities:

First, you must read from the Node.Ready() channel and process the updates it contains. These steps may be performed in parallel, except as noted in step
2.

1. Write HardState, Entries, and Snapshot to persistent storage if they are
   not empty. Note that when writing an Entry with Index i, any
   previously-persisted entries with Index >= i must be discarded.

2. Send all Messages to the nodes named in the To field. 
   It is important that no messages be sent until the latest HardState has been persisted to disk, and all Entries written by any previous Ready batch (Messages may be sent while entries from the same batch are being persisted). 
   To reduce the I/O latency, an optimization can be applied to make leader write to disk in parallel with its followers (as explained at section 10.2.1 in Raft thesis). 
   If any Message has type MsgSnap, call Node.ReportSnapshot() after it has been sent (these messages may be large).

Note: Marshalling messages is not thread-safe; it is important that you
make sure that no new entries are persisted while marshalling.
The easiest way to achieve this is to serialize the messages directly inside
your main raft loop.

3. Apply Snapshot (if any) and CommittedEntries to the state machine.
   If any committed Entry has Type EntryConfChange, call Node.ApplyConfChange()
   to apply it to the node. The configuration change may be cancelled at this point
   by setting the NodeID field to zero before calling ApplyConfChange
   (but ApplyConfChange must be called one way or the other, and the decision to cancel
   must be based solely on the state machine and not external information such as
   the observed health of the node).

4. Call Node.Advance() to signal readiness for the next batch of updates.
   This may be done at any time after step 1, although all updates must be processed
   in the order they were returned by Ready.

Second, all persisted log entries must be made available via an
implementation of the Storage interface. The provided MemoryStorage
type can be used for this (if you repopulate its state upon a
restart), or you can supply your own disk-backed implementation.

Third, when you receive a message from another node, pass it to Node.Step:
```go
	func recvRaftRPC(ctx context.Context, m raftpb.Message) {
		n.Step(ctx, m)
	}
```

Finally, you need to call Node.Tick() at regular intervals (probably
via a time.Ticker). Raft has two important timeouts: heartbeat and the
election timeout. However, internally to the raft package time is
represented by an abstract "tick".

The total state machine handling loop will look something like this:
```go
	for {
	  select {
	  case <-s.Ticker:
	    n.Tick()
	  case rd := <-s.Node.Ready():
	    saveToStorage(rd.State, rd.Entries, rd.Snapshot)
	    send(rd.Messages)
	    if !raft.IsEmptySnap(rd.Snapshot) {
	      processSnapshot(rd.Snapshot)
	    }
	    for _, entry := range rd.CommittedEntries {
	      process(entry)
	      if entry.Type == raftpb.EntryConfChange {
	        var cc raftpb.ConfChange
	        cc.Unmarshal(entry.Data)
	        s.Node.ApplyConfChange(cc)
	      }
	    }
	    s.Node.Advance()
	  case <-s.done:
	    return
	  }
	}
```



node启动时是启动了一个协程，处理node的里的多个通道，包括tickc，调用tick()方法
该方法会动态改变，对于follower和candidate，它就是tickElection，对于leader和，它就是tickHeartbeat。tick就像是一个etcd节点的心脏跳动，在follower这里，每次tick会去检查是不是leader的心跳是不是超时了。对于leader，每次tick都会检查是不是要发送心跳了



startNode -> NewRawNode -> newRaft



### state


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

1. [raft 工程化案例之 etcd 源码实现](https://zhuanlan.zhihu.com/p/600893553)
2. [etcd 源码分析](https://www.zhihu.com/column/c_1574793366772060162)
