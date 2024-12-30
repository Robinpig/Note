## Introduction



client-go` 支持四种客户端对象，分别是 `RESTClient`，`ClientSet`，`DynamicClient` 和 `DiscoveryClient



组件或者二次开发的应用可以通过这四种客户端对象和 `kube-apiserver` 交互。其中，`RESTClient` 是最基础的客户端对象，它封装了 `HTTP Request`，实现了 `RESTful` 风格的 `API`。`ClientSet` 基于 `RESTClient`，封装了对于 `Resource` 和 `Version` 的请求方法。`DynamicClient` 相比于 `ClientSet` 提供了全资源，包括自定义资源的请求方法。`DiscoveryClient` 用于发现 `kube-apiserver` 支持的资源组，资源版本和资源信息。

每种客户端适用的场景不同，主要是对 `HTTP Request` 做了层层封装



## informer



`informer` 机制的核心组件包括：

- ```
  Reflector
  ```

  : 主要负责两类任务：

  1. 通过 `client-go` 客户端对象 list `kube-apiserver` 资源，并且 watch `kube-apiserver` 资源变更。
  2. 作为生产者，将获取的资源放入 `Delta FIFO` 队列。

- ```
  Informer
  ```

  : 主要负责三类任务：

  1. 作为消费者，将 `Reflector` 放入队列的资源拿出来。
  2. 将资源交给 `indexer` 组件。
  3. 交给 `indexer` 组件之后触发回调函数，处理回调事件。

- `Indexer`: `indexer` 组件负责将资源信息存入到本地内存数据库（实际是 `map` 对象），该数据库作为缓存存在，其资源信息和 `ETCD` 中的资源信息完全一致（得益于 `watch` 机制）。因此，`client-go` 可以从本地 `indexer` 中读取相应的资源，而不用每次都从 `kube-apiserver` 中获取资源信息。这也实现了 `client-go` 对于实时性的要求。

```

```






## Links

- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

