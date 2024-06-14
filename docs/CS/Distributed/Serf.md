## Introduction

[Serf]([Serf by HashiCorp](https://www.serf.io/)) relies on an efficient and lightweight gossip protocol to communicate with nodes. 
The Serf agents periodically exchange messages with each other in much the same way that a zombie apocalypse would occur: it starts with one zombie but soon infects everyone. 
In practice, the gossip is [very fast and extremely efficient.](https://www.serf.io/docs/internals/simulator.html)

The gossip protocol used by Serf is based on a modified version of the [SWIM (Scalable Weakly-consistent Infection-style Process Group Membership)](https://www.cs.cornell.edu/projects/Quicksilver/public_pdfs/SWIM.pdf) protocol.

Serf vs. Consul


Consul is a tool for service discovery and configuration. It provides high level features such as service discovery, health checking and key/value storage. It makes use of a group of strongly consistent servers to manage the datacenter.

Serf can also be used for service discovery and orchestration, but it is built on an eventually consistent gossip model, with no centralized servers. It provides a number of features, including group membership, failure detection, event broadcasts and a query mechanism. However, Serf does not provide any of the high-level features of Consul.


