## Introduction

UDP is a simple, datagram-oriented, transport-layer protocol that preserves message boundaries.
It can provide error detection, and it includes the first true end-to-end checksum at the transport layer that we have encountered. 
Generally, each UDP output operation requested by an application produces exactly one UDP datagram, which causes one IP datagram to be sent.

> UDP can be full-duplex.

Some applications are better suited for UDP for the following reasons:

- Finer application-level control over what data is sent, and when.
- No connection establishment.
- No connection state.
- Small packet header overhead.
The TCP segment has 20 bytes of header overhead in every segment, whereas UDP has only 8 bytes of overhead.

### Checksum

Why UDP provides a checksum in the first place, as many link-layer protocols(including the popular Ethernet protocol) also provide error checking. 
The reason is that there is no guarantee that all the links between source and destination provide error checking; that is, one of the links may use a link-layer protocol that does not provide error checking.
Furthermore, even if segments are correctly transferred across a link, it’s possible that bit errors could be introduced when a segment is stored in a router’s memory. 
Given that neither link-by-link reliability nor in-memory error detection is guaranteed, UDP must provide error detection at the transport layer, on an end-end basis, if the endend data transfer service is to provide error detection. 
This is an example of the celebrated end-end principle in system design, which states that since certain functionality (error detection, in this case) must be implemented on an end-end basis: 
“functions placed at the lower levels may be redundant or of little value when compared to the cost of providing them at the higher level.”

Because IP is supposed to run over just about any layer-2 protocol, it is useful for the transport layer to provide error checking as a safety measure. 
Although UDP provides error checking, it does not do anything to recover from an error. 
Some implementations of UDP simply discard the damaged segment; others pass the damaged segment to the application with a warning.


## Congestion Control





## Attacks Involving UDP and IP Fragmentation

Most attacks involving UDP relate to exhaustion of some shared resource (buffers, link capacity, etc.) or exploitation of bugs in protocol implementations causing system crashes or other undesired behavior. 
Both fall into the broad category of DoS attacks: the successful attacker is able to cause services to be made unavailable to legitimate users. 
The most straightforward DoS attack with UDP is simply generating massive amounts of traffic as fast as possible. 
Because UDP does not regulate its sending traffic rate, this can negatively impact the performance of other applications sharing the same network path. 
This can happen even without malicious intent.

A more sophisticated form of DoS attack frequently associated with UDP is a magnification attack. 
This type of attack generally involves an attacker sending a small amount of traffic that induces other systems to generate much more.







## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Linux UDP](/docs/CS/OS/Linux/UDP.md)

## References

1. [RFC 768 - User Datagram Protocol](https://www.rfc-editor.org/info/rfc768)
1. [RFC 4340 - Datagram Congestion Control Protocol (DCCP)](https://www.rfc-editor.org/info/rfc4340)