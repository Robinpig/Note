## Introduction


https://github.com/tidwall/evio

evio is an event loop networking framework that is fast and small. It makes direct epoll and kqueue syscalls rather than using the standard Go net package, and works in a similar manner as libuv and libevent.
The goal of this project is to create a server framework for Go that performs on par with Redis and Haproxy for packet handling. It was built to be the foundation for Tile38 and a future L7 proxy for Go.

请注意：Evio 不应被视为标准 Go net 或 net/http 包的替代品。


Installing
To start using evio, install Go and run go get:
$ go get -u github.com/tidwall/evio
This will retrieve the library.
Usage
Starting a server is easy with evio. Just set up your events and pass them to the Serve function along with the binding address(es). Each connections is represented as an evio.Conn object that is passed to various events to differentiate the clients. At any point you can close a client or shutdown the server by return a Close or Shutdown action from an event.
Example echo server that binds to port 5000

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

Here the only event being used is Data, which fires when the server receives input data from a client. The exact same input data is then passed through the output return value, which is then sent back to the client.
Connect to the echo server:

telnet localhost 5000



## Links
