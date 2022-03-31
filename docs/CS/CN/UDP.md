## Introduction

UDP is a simple, datagram-oriented, transport-layer protocol that preserves message boundaries.
It can provide error detection, and it includes the first true end-to-end checksum at the transport layer that we have encountered. 
Generally, each UDP output operation requested by an application produces exactly one UDP datagram, which causes one IP datagram to be sent.
















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