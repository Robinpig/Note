## Introduction

[A simple totally ordered broadcast protocol](https://www.datadoghq.com/pdf/zab.totally-ordered-broadcast-protocol.2008.pdf)

[ZooKeeper’s atomic broadcast protocol:Theory and practice](http://www.tcs.hut.fi/Studies/T-79.5001/reports/2012-deSouzaMedeiros.pdf)

[Zab: High-performance broadcast for primary-backup systems](https://marcoserafini.github.io/papers/zab.pdf)

Zab is very similar to Paxos [15], with one crucial difference – the agreement is reached on full history prefixes rather than on individual operations.
This difference allows Zab to preserve primary order, which may be violated by Paxos.

## Links

- [ZooKeeper](/docs/CS/Java/ZooKeeper/ZooKeeper.md)
- [Consensus](/docs/CS/Distributed/Consensus.md)
