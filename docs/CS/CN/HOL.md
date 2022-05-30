## Introduction


Head-of-line blocking (HOL blocking) in computer networking is a performance-limiting phenomenon that occurs when a line of packets is held up by the first packet.
Examples include input buffered network switches, out-of-order delivery and multiple requests in HTTP pipelining.

### Network switches

A switch may be composed of buffered input ports, a switch fabric and buffered output ports. If first-in first-out (FIFO) input buffers are used, only the oldest packet is available for forwarding. 
More recent arrivals cannot be forwarded if the oldest packet cannot be forwarded because its destination output is busy. The output may be busy if there is output contention.

Without HOL blocking, the new arrivals could potentially be forwarded around the stuck oldest packet to their respective destinations. HOL blocking can produce performance-degrading effects in input-buffered systems.

This phenomenon limits the throughput of switches. 
For FIFO input buffers, a simple model of fixed-sized cells to uniformly distributed destinations, causes the throughput to be limited to 58.6% of the total as the number of links becomes large.

One way to overcome this limitation is by using virtual output queues.

Only switches with input buffering can suffer HOL blocking. With sufficient internal bandwidth, input buffering is unnecessary; all buffering is handled at outputs and HOL blocking is avoided. 
This no-input-buffering architecture is common in small to medium-sized ethernet switches.


### Out-of-order delivery
Out-of-order delivery occurs when sequenced packets arrive out of order. This may happen due to different paths taken by the packets or from packets being dropped and resent. 
HOL blocking can significantly increase packet reordering.


Reliably broadcasting messages across a lossy network among a large number of peers is a difficult problem. 
While atomic broadcast algorithms solve the single point of failure problem of centralized servers, those algorithms introduce a head-of-line blocking problem.
The Bimodal Multicast algorithm, a randomized algorithm that uses a gossip protocol, avoids head-of-line blocking by allowing some messages to be received out-of-order.

### In HTTP

One form of HOL blocking in HTTP/1.1 is when the number of allowed parallel requests in the browser is used up, and subsequent requests need to wait for the former ones to complete. 
HTTP/2 addresses this issue through request multiplexing, which eliminates HOL blocking at the application layer, but HOL still exists at the transport (TCP) layer.
HTTP/3 uses QUIC instead of TCP which removes HOL blocking in the transport layer.

### TLS HOL blocking


### Transport Congestion Control



## Solutions




HTTP/1.1 introduced a feature called "Pipelining" which allowed a client sending several HTTP requests over the same TCP connection. 
However HTTP/1.1 still required the responses to arrive in order so it didn't really solved the HOL issue and as of today it is not widely adopted.


HTTP/2 does however still suffer from another type of HOL, as it runs over a TCP connection; and due to TCP's congestion control, one lost packet in the TCP stream makes all streams wait until that package is re-transmitted and received.


## Links

- [Computer Network](/docs/CS/CN/CN.md)


## References

1. [Head-of-line blocking - Wiki](https://en.wikipedia.org/wiki/Head-of-line_blocking)
2. [Making the Web Faster with HTTP 2.0 HTTP continues to evolve](https://queue.acm.org/detail.cfm?id=2555617)
3. [Head-of-Line Blocking in QUIC and HTTP/3: The Details](https://github.com/rmarx/holblocking-blogpost#sec_tls)