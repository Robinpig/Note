## Introduction

[Gin](https://github.com/gin-gonic/gin) 是一个 go 写的 web 框架，具有高性能的优点

Gin 是在 Golang HTTP 标准库 net/http 基础之上的再封装
在 net/http 的既定框架下，gin 所做的是提供了一个 gin.Engine 对象作为 Handler 注入其中，从而实现路由注册/匹配、请求处理链路的优化



一键启动 Engine.Run 方法后，底层会将 gin.Engine 本身作为 net/http 包下 Handler interface 的实现类，并调用 http.ListenAndServe 方法启动服

在服务端接收到 http 请求时，会通过 Handler.ServeHTTP 方法进行处理.
而此处的 Handler 正是 gin.Engine，其处理请求的核心步骤如下：
- 对于每笔 http 请求，会为其分配一个 gin.Context，在 handlers 链路中持续向下传递
- 调用 Engine.handleHTTPRequest 方法，从路由树中获取 handlers 链，然后遍历调用
- 处理完 http 请求后，会将 gin.Context 进行回收. 整个回收复用的流程基于对象池管理


Engine.handleHTTPRequest 方法核心步骤分为三步：
- 根据 http method 取得对应的 methodTree
- 根据 path 从 methodTree 中找到对应的 handlers 链
- 将 handlers 链注入到 gin.Context 中，通过 Context.Next 方法按照顺序遍历调用 handler


···
type methodTree struct {
method string
root   *node
}


gin.Context 作为处理 http 请求的通用数据结构，不可避免地会被频繁创建和销毁. 为了缓解 GC 压力，gin 中采用对象池 sync.Pool 进行 Context 的缓存复用，处理流程如下：http 请求到达时，从 pool 中获取 Context，倘若池子已空，通过 pool.New 方法构造新的 Context 补上空缺http 请求处理完成后，将 Context 放回 pool 中，用以后续复用sync.Pool 并不是真正意义上的缓存，将其称为回收站或许更加合适，放入其中的数据在逻辑意义上都是已经被删除的，但在物理意义上数据是仍然存在的，这些数据可以存活两轮 GC 的时间，在此期间倘若有被获取的需求，则可以被重新复用.

在 Engine.handleHTTPRequest 方法处理请求时，会通过 path 从 methodTree 中获取到对应的 handlers 链，然后将 handlers 注入到 Context.handlers 中，然后启动 Context.Next 方法开启 handlers 链的遍历调用流程




## Links

- [Golang](/docs/CS/Go/Go.md)