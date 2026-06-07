## Introduction

https://github.com/tidwall/evio

evio 是一个快速且小巧的事件循环网络框架。它直接使用 epoll 和 kqueue 系统调用，而非标准的 Go net 包，其工作方式与 libuv 和 libevent 类似。
该项目旨在创建一个 Go 服务器框架，在数据包处理方面性能可与 Redis 和 Haproxy 相媲美。它是为 Tile38 和未来的 Go L7 代理而构建的。

请注意：Evio 不应被视为标准 Go net 或 net/http 包的替代品。

Installing
要开始使用 evio，安装 Go 并运行 go get:
$ go get -u github.com/tidwall/evio
这将获取库文件。
Usage
使用 evio 启动服务器非常简单。只需设置好事件处理函数，并将其与绑定地址一起传给 Serve 函数。每个连接都表示为一个 evio.Conn 对象，该对象被传递给各种事件以区分客户端。在任何时候，你都可以通过从事件处理函数返回 Close 或 Shutdown 操作来关闭客户端或关闭服务器。
绑定到端口 5000 的 Echo 服务器示例

```go
package main

import "github.com/tidwall/evio"

func main() {
	var events evio.Events
	events.Data = func(c evio.Conn, in []byte) (out []byte, action evio.Action) {
		out = in
		return
	}
	if err := evio.Serve(events, "tcp://localhost:5000"); err != nil {
		panic(err.Error())
	}
}
```

这里唯一使用的事件是 Data，它在服务器接收到客户端输入数据时触发。相同的输入数据通过输出返回值传回，然后发送回客户端。
连接到 echo 服务器:

telnet localhost 5000

## Links
