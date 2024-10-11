## Introduction


可以通过client API发起人工的压缩(Compact)操作，也可以配置自动压缩策略。在自动压缩策略中，你可以根据你的业务场景选择合适的压缩模式。目前etcd支持两种压缩模式，分别是时间周期性压缩和版本号压缩

通过API发起一个Compact请求后，KV Server收到Compact请求提交到Raft模块处理，在Raft模块中提交后，Apply模块就会通过MVCC模块的Compact接口执行此压缩任务。

Compact接口首先会更新当前server已压缩的版本号，并将耗时昂贵的压缩任务保存到FIFO队列中异步执行。压缩任务执行时，它首先会压缩treeIndex模块中的keyIndex索引，其次会遍历boltdb中的key，删除已废弃的key

以先通过endpoint status命令获取etcd当前版本号，然后再通过etcdctl compact命令发起压缩操作即可。
```shell
# 获取etcd当前版本号
$ rev=$(etcdctl endpoint status --write-out="json" | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')
$ echo $rev
9
# 执行压缩操作，指定压缩的版本号为当前版本号
$ etcdctl compact $rev
Compacted revision 9
```
如果你压缩命令传递的版本号小于等于当前etcd server记录的压缩版本号，etcd server会返回已压缩错误(“mvcc: required revision has been compacted”)给client。如果版本号大于当前etcd server最新的版本号，etcd server则返回一个未来的版本号错误给client(“mvcc: required revision is a future revision”)
```shell
# 压缩一个已经压缩的版本号
$ etcdctl compact $rev
Error: etcdserver: mvcc: required revision has been compacted
# 压缩一个比当前最大版号大的版本号
$ etcdctl compact 12
Error: etcdserver: mvcc: required revision is a future revision
```

## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References
