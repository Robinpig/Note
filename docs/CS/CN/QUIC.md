## Introduction

*Quick UDP Internet Connections*

TCP + TLS + HTTP2 = UDP + QUIC + HTTP2’s API

> QUIC retains ordering within a single resource stream.

0-RTT

QUIC encrypts and cryptographically authenticates both the transport data and the protocol itself, preventing middleboxes from inspecting or modifying the protocol header and future-proofing the protocol in the process.
QUIC also has versioning built in (yes, there is no versioning in TCP), which gives us the freedom to consider deep and wide changes as the future requires.
Versioning also allows us to consider alternative versions that we can build, tune, and deploy within our POPs, as we’ll now discuss.

We anticipated two major sources of computational cost for QUIC:

Acknowledgement processing: A large fraction of packets in a typical TCP connection carry only acknowledgements. TCP acknowledgements are processed within the kernel, both at the sender and the receiver. QUIC does these in user space, resulting in more data copies across the user-kernel boundary and more context switches. Additionally, TCP acknowledgements are in plaintext, while QUIC acknowledgements are encrypted, increasing the cost of sending and receiving acknowledgements in QUIC.

Per-packet sender overhead: The kernel knows about TCP connections, and can remember and reuse state that is expected to remain unchanged for all packets sent in a connection. For instance, the kernel needs to typically only look up the route for the destination address or apply firewall rules once at the start of the connection. Since the kernel has no connection state for QUIC connections, these kernel operations are performed on every outgoing QUIC packet.

Since QUIC runs in user space, these costs are higher with QUIC than with TCP. This is because every packet that is either sent or received by QUIC crosses the user-kernel boundary, which is known as a context switch.

This experiment showed a clear path forward for improving quicly’s efficiency: reducing acknowledgement frequency, coalescing packets with GSO, and using as large a packet size as possible.

## TLS



## Connection Migration

QUIC connections are not strictly bound to a single network path.
Connection migration uses connection identifiers to allow connections to transfer to a new network path.  
Only clients are able to migrate in this version of QUIC.  
This design also allows connections to continue after changes in network topology or address mappings, such as might be caused by NAT rebinding.

The use of a connection ID allows connections to survive changes to endpoint addresses (IP address and port), such as those caused by an endpoint migrating to a new network.  
This section describes the process by which an endpoint migrates to a new address.


The design of QUIC relies on endpoints retaining a stable address for the duration of the handshake.  
An endpoint MUST NOT initiate connection migration before the handshake is confirmed, as defined in [QUIC-TLS](/docs/CS/CN/QUIC.md?id=TLS).


If the peer sent the `disable_active_migration` transport parameter, an endpoint also MUST NOT send packets (including probing packets) from a different local address to the address the peer used during the handshake, 
unless the endpoint has acted on a `preferred_address` transport parameter from the peer.  
If the peer violates this requirement, the endpoint MUST either drop the incoming packets on that path without generating a *Stateless Reset* or proceed with path validation and allow the peer to migrate.  
Generating a *Stateless Reset* or closing the connection would allow third parties in the network to cause connections to close by spoofing or otherwise manipulating observed traffic.

Not all changes of peer address are intentional, or active, migrations.  
The peer could experience NAT rebinding: a change of address due to a middlebox, usually a NAT, allocating a new outgoing port or even a new outgoing IP address for a flow.  
An endpoint MUST perform path validation if it detects any change to a peer's address, unless it has previously validated that address.

When an endpoint has no validated path on which to send packets, it MAY discard connection state.  
An endpoint capable of connection migration MAY wait for a new path to become available before discarding connection state.

This document limits migration of connections to new client addresses, except as described in Section 9.6.  Clients are responsible for initiating all migrations.  
Servers do not send non-probing packets (see Section 9.1) toward a client address until they see a non-probing packet from that address.  If a client receives packets from an unknown server address, the client MUST discard these packets.


### Probing a New Path

An endpoint MAY probe for peer reachability from a new local address using path validation prior to migrating the connection to the new local address.  
Failure of path validation simply means that the new path is not usable for this connection.  
**Failure to validate a path does not cause the connection to end unless there are no valid alternative paths available.**

PATH_CHALLENGE, PATH_RESPONSE, NEW_CONNECTION_ID, and PADDING frames are "probing frames", and all other frames are "non-probing frames".
A packet containing only probing frames is a "probing packet", and a packet containing any other frame is a "non-probing packet".


### Initiating Connection Migration




```
  (Before connection migration)
   +--------------+   Non-probing Packet   +--------------+
   |    Client    |  ------------------->  |              |
   |(Source IP: 1)|  <-------------------  |              |
   +--------------+   Non-probing Packet   |              |
          |                                |              |
          |                                |              |
          |                                |              |
          v                                |              |
   +--------------+   Non-probing Packet   |              |
   |              |  ------------------->  |              |
   |              |  <-------------------  |              |
   |              |   Non-probing Packet   |              |
   |              |                        |              |
   |              |                        |    Server    |
   |              |     Probing Packet     |              |
   |              |    (PATH_CHALLENGE)    |              |
   |    Client    |  <-------------------  |              |
   |(Source IP: 2)|  ------------------->  |              |
   |              |     Probing Packet     |              |
   |              |     (PATH_RESPONSE)    |              |
   |              |                        |              |
   |              |     Probing Packet     |              |
   |              |    (PATH_CHALLENGE)    |              |
   |              |  ------------------->  |              |
   |              |  <-------------------  |              |
   |              |     Probing Packet     |              |
   |              |     (PATH_RESPONSE)    |              |
   +--------------+                        +--------------+
   (After connection migration)
```


## Bonus

### multplexing

If that’s the case, we might wonder why we would need multplexing at all? And by extension:
HTTP/2 and even HTTP/3, as multiplexing is one of the main features they have that HTTP/1.1 doesn’t.

- Firstly, some files that can be processed/rendered incrementally do profit from multiplexing.
  This is for example the case for progressive images.
- Secondly, as also discussed above, it can be useful if one of the files is much smaller than the others, as it will be downloaded earlier while not delaying the others by too much.
- Thirdly, multiplexing allows changing the order of responses and interrupting a low priority response for a higher priority one.

### Transport Congestion Control

QUIC and HTTP/3 will see similar challenges, as like HTTP/2, HTTP/3 will use a single underlying QUIC connection.
You might then say that a QUIC connection is conceptually a bit like multiple TCP connections, as each QUIC stream can be seen as one TCP connection, because loss detection is done on a per-stream basis.
Crucially however, QUIC’s congestion control is still done at the connection level, and not per-stream.
This means that even though the streams are conceptually independent, they all still impact QUIC’s singular, per-connection congestion controller, causing slowdowns if there is loss on any of the stream.
Put differently: the single HTTP/3+QUIC connection still won’t grow as fast as the 6 HTTP/1.1 connections, similar to how HTTP/2+TCP over one connection wasn’t faster.


[quicly](https://github.com/h2o/quicly)

## Links

- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [RFC 9000 - QUIC: A UDP-Based Multiplexed and Secure Transport](https://datatracker.ietf.org/doc/rfc9000/)
2. [知乎专栏 QUIC](https://www.zhihu.com/column/c_1303002298995113984)
