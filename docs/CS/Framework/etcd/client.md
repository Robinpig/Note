## Introduction







## v3

相对于v2来说，v3由于默认采用grpc作为client和server之间的通信方式，并且提供的api也丰富很多，因此，client v3相对v2更复杂

rpc服务都定义在etcdserver/etcdserverpb/rpc.proto文件中，grpc框架根据proto文件生成rpc.pb.go文件，go文件中定义了grpc的接口、注册函数和client代码











## Links

- [etcd](/docs/CS/Framework/etcd/etcd.md)



## References

1. [【深入浅出etcd系列】4. 客户端](https://bbs.huaweicloud.com/blogs/100128)