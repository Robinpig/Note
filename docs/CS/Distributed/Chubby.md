## Introduction

Chubby provide coarse-grained locking as well as reliable storage for a loosely-coupled distributed system.
Chubby provides an interface much like a distributed file system with advisory locks, but the design emphasis is on availability and reliability, as opposed to high performance. 

Google File System uses a Chubby lock to appoint a GFS master server, and Bigtable uses Chubby in several ways: to elect a master, to allow the master to discover the servers it controls, and to permit clients to find the master. 
In addition, both GFS and Bigtable use Chubby as a well-known and available location to store a small amount of meta-data; in effect they use Chubby as the root of their distributed data structures.

Asynchronous consensus is solved by the [Paxos](/docs/CS/Distributed/Paxos.md) protocol.





## Caching


- Since all requests go through the master, caching is done to alleviate this load.
- The caches at each client are right through and the caches at all clients are kept consistent.
- All caches are maintained only till the “lease period”.


## KeepAlive




## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)


## References

1. [The Chubby lock service for loosely-coupled distributed systems](https://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf)
2. [Reiew of Paxos Made Simple and The Chubby Lock Service for Loosely-Coupled Distributed Systems](https://www.cs.colostate.edu/~cs670/CR7_AndyStone_PaxosChubby.pdf)