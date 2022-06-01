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

### HTTP

One form of HOL blocking in HTTP/1.1 is when the number of allowed parallel requests in the browser is used up, and subsequent requests need to wait for the former ones to complete. 
This is mainly because the protocol is purely textual in nature and doesn’t use delimiters between resource chunks.
HTTP/1.1 introduced a feature called ["Pipelining"](/docs/CS/CN/HTTP.md?id=pipelining) which allowed a client sending several HTTP requests over the same TCP connection.
However HTTP/1.1 still required the responses to arrive in order so it didn't really solved the HOL issue and as of today it is not widely adopted.

As such, the goal for HTTP/2 was quite clear: **make it so that we can move back to a single TCP connection by solving the HOL blocking problem**.
HTTP/2 addresses this issue through request **multiplexing**, which eliminates HOL blocking at the application layer, but HOL still exists at the transport (TCP) layer.
Stated differently: we want to enable proper multiplexing of resource chunks.
This wasn’t possible in HTTP/1.1 because there was no way to discern to which resource a chunk belongs, or where it ends and another begins. 
HTTP/2 solves this quite elegantly by prepending small control messages, called **frames**, before the resource chunks.
By “framing” individual messages HTTP/2 is thus much more flexible than HTTP/1.1. 
It allows for many resources to be sent multiplexed on a single TCP connection by interleaving their chunks.



HTTP/3 uses QUIC instead of TCP which removes HOL blocking in the transport layer.

When a TCP packet gets lost in transit, the receiver can’t acknowledge incoming packages until the lost package is re-sent by a server.
Since TCP is by design oblivious to higher-level protocols like HTTP, a single lost packet will block the stream for all in-flight HTTP requests until the missing data is re-sent.
Put differently, there is a mismatch in perspective between the two Layers: HTTP/2 sees multiple, independent resource bytestreams, but TCP sees just a single, opaque bytestream.

> QUIC’s HOL blocking removal probably won’t actually help all that much for Web performance.



### TLS HOL blocking

the TLS protocol provides encryption (and other things) for Application Layer protocols, such as HTTP. 
It does this by wrapping the data it gets from HTTP into TLS records, which are conceptually similar to HTTP/2 frames or TCP packets. 
They for example include a bit of metadata at the start to indicate how long the record is. This record and its HTTP contents are then encrypted and passed to TCP for transport.

Crucially however, TLS can only decrypt a record in its entirety, which is why a form of TLS HOL blocking can occur.
Imagine that the TLS record was spread out over 11 TCP packets, and the last TCP packet is lost. 
Since the TLS record is incomplete, it cannot be decrypted, and is thus stuck waiting for the retransmission of the last TCP packet. 
Note that in this specific case there is no TCP HOL blocking: there are no packets after number 11 that are stuck waiting for the retransmit.

While this is a highly specific case that probably does not happen very frequently in practice, it was still something taken into account when designing the QUIC protocol. 
As there the goal was to eliminate HOL blocking in all its forms once and for all (or at least as much as possible), even this edge case had to be removed. This is part of the reason why, 
while QUIC integrates TLS, it will always encrypt data on a per-packet basis and it does not use TLS records directly. 
As we’ve seen, this is less efficient and requires more CPU than using larger blocks, and is one of the main reasons why QUIC can still be slower than TCP in current implementations.

> See [Optimizing TLS Record Size & Buffering Latency](https://www.igvita.com/2013/10/24/optimizing-tls-record-size-and-buffering-latency/)

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP.md)
- [QUIC](/docs/CS/CN/QUIC.md)

## References

1. [Head-of-line blocking - Wiki](https://en.wikipedia.org/wiki/Head-of-line_blocking)
2. [Making the Web Faster with HTTP 2.0 HTTP continues to evolve](https://queue.acm.org/detail.cfm?id=2555617)
3. [Head-of-Line Blocking in QUIC and HTTP/3: The Details](https://github.com/rmarx/holblocking-blogpost#sec_tls)