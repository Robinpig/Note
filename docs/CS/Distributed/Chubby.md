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

When file data or meta-data is to be changed, the modification is blocked while the master sends invalidations for the data to every client that may have cached it; this mechanism sits on top of KeepAlive RPCs.

The caching protocol is simple: it invalidates cached data on a change, and never updates it.

Clients see a Chubby handle as a pointer to an opaque structure that supports various operations.
Handles are created only by Open(), and destroyed with Close().

## KeepAlive

A Chubby session is a relationship between a Chubby cell and a Chubby client; it exists for some interval of time, and is maintained by periodic handshakes called KeepAlives.
Unless a Chubby client informs the master otherwise, the client’s handles, locks, and cached data all remain valid provided its session remains valid.

A client requests a new session on first contacting the master of a Chubby cell.
It ends the session explicitly either when it terminates, or if the session has been idle(with no open handles and no calls for a minute).

Each session has an associated lease—an interval of time extending into the future during which the master guarantees not to terminate the session unilaterally.
The end of this interval is called the session lease timeout.
The master is free to advance this timeout further into the future, but may not move it backwards in time.

The master advances the lease timeout in three circumstances: on creation of the session, when a master fail-over occurs (see below), and when it responds to a KeepAlive RPC from the client.

As well as extending the client’s lease, the KeepAlive reply is used to transmit events and cache invalidations back to the client. The master allows a KeepAlive to return early when an event or invalidation is to be delivered.

TCP’s back off policies pay no attention to higher-level timeouts such as Chubby leases, so TCP-based KeepAlives led to many lost sessions at times of high network congestion.
We were forced to send KeepAlive RPCs via UDP rather than TCP; UDP has no congestion avoidance mechanisms, so we would prefer to use UDP only when high-level timebounds must be met.

## Failover

When a master fails or otherwise loses mastership, it discards its in-memory state about sessions, handles, and locks.

Because Chubby does not use path-based permissions, a single lookup in the database suffices for each file access.

Every few hours, the master of each Chubby cell writes a snapshot of its database to a GFS file server in a different building.
The use of a separate building ensures both that the backup will survive building damage, and that the backups introduce no cyclic dependencies in the system; a GFS cell in the same building potentially might rely on the Chubby cell for electing its master.

Backups provide both disaster recovery and a means for initializing the database of a newly replaced replica without placing load on replicas that are in service.

Chubby allows a collection of files to be mirrored from one cell to another.
Mirroring is fast because the files are small and the event mechanism informs the mirroring code immediately if a file is added, deleted, or modified.
Provided there are no network problems, changes are reflected in dozens of mirrors world-wide in well under a second.
If a mirror is unreachable, it remains unchanged until connectivity is restored.
Updated files are then identified by comparing their checksums.

Mirroring is used most commonly to copy configuration files to various computing clusters distributed around the world.

## Scaling

Two familiar mechanisms, proxies and partitioning, that they expect will allow Chubby to scale further.

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)

## References

1. [The Chubby lock service for loosely-coupled distributed systems](https://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf)
2. [Reiew of Paxos Made Simple and The Chubby Lock Service for Loosely-Coupled Distributed Systems](https://www.cs.colostate.edu/~cs670/CR7_AndyStone_PaxosChubby.pdf)
