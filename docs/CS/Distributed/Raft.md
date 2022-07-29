## Introduction

[Raft](https://raft.github.io/) is a consensus algorithm that is designed to be easy to understand.
It's equivalent to [Paxos](/docs/CS/Distributed/Paxos.md) in fault-tolerance and performance.
The difference is that it's decomposed into relatively independent subproblems, and it cleanly addresses all major pieces needed for practical systems.

In contrast to Paxos, which is leaderless, Raft is a leader-based log replication protocol.
In simplified terms, a Raft implementation elects a leader once, and then the leader is responsible for making all the decisions about the state of the database.
This helps avoid extra communication between replicas during individual reads and writes. Each node tracks the current leader and forwards requests to that leader.

Raft is built around the concept of a replicated log. When the leader receives a request, it first stores an entry for it in its durable local log.
This local log is then replicated to all of the followers, or replicas.
Once the majority of replicas confirm they have persisted with the log, the leader applies the entry and instructs the replicas to do the same.
In the event of leader failure, a replica with the most up-to-date log becomes the leader.

Raft defines not only how the group makes a decision, but also the protocol for adding new members and removing members from the group.
This feature makes Raft a natural fit for managing topology changes in distributed systems.

Raft decomposes the consensus problem into three relatively independent subproblems:

- Leader election
- Log replication
- Safety

## Leader election

Raft uses a heartbeat mechanism to trigger leader election.
When servers start up, they begin as followers.
A server remains in follower state as long as it receives valid RPCs from a leader or candidate.
Leaders send periodic heartbeats (AppendEntries RPCs that carry no log entries) to all followers in order to maintain their authority.
If a follower receives no communication over a period of time called the election timeout, then it assumes there is no viable leader and begins an election to choose a new leader

To begin an election, a follower increments its current term and transitions to candidate state.
It then votes for itself and issues RequestVote RPCs in parallel to each of the other servers in the cluster.
A candidate continues in this state until one of three things happens:

- it wins the election,
- another server establishes itself as leader, or
- a period of time goes by with no winner.

A candidate wins an election if it receives votes from a majority of the servers in the full cluster for the same term.
Each server will vote for at most one candidate in a given term, on a first-come-first-served basis (note: Section 5.4 adds an additional restriction on votes).
The majority rule ensures that at most one candidate can win the election for a particular term (the Election Safety Property in Figure 3).
Once a candidate wins an election, it becomes leader.
It then sends heartbeat messages to all of the other servers to establish its authority and prevent new elections.

While waiting for votes, a candidate may receive an AppendEntries RPC from another server claiming to be leader.
If the leader’s term (included in its RPC) is at least as large as the candidate’s current term, then the candidate recognizes the leader as legitimate and returns to follower state.
If the term in the RPC is smaller than the candidate’s current term, then the candidate rejects the RPC and continues in candidate state.

The third possible outcome is that a candidate neither wins nor loses the election: if many followers become candidates at the same time, votes could be split so that no candidate obtains a majority.
When this happens, each candidate will time out and start a new election by incrementing its term and initiating another round of RequestVote RPCs.
However, without extra measures split votes could repeat indefinitely.

Raft uses randomized election timeouts to ensure that split votes are rare and that they are resolved quickly.
To prevent split votes in the first place, election timeouts are chosen randomly from a fixed interval (e.g., 150–300ms).
This spreads out the servers so that in most cases only a single server will time out; it wins the election and sends heartbeats before any other servers time out.
The same mechanism is used to handle split votes.
Each candidate restarts its randomized election timeout at the start of an election, and it waits for that timeout to elapse before starting the next election; this reduces the likelihood of another split vote in the new election.

Elections are an example of how understandability guided our choice between design alternatives.
Initially we planned to use a ranking system: each candidate was assigned a unique rank, which was used to select between competing candidates.
If a candidate discovered another candidate with higher rank, it would return to follower state so that the higher ranking candidate could more easily win the next election.
We found that this approach created subtle issues around availability (a lower-ranked server might need to time out and become a candidate again if a higher-ranked server fails, but if it does so too soon, it can reset progress towards electing a leader).
We made adjustments to the algorithm several times, but after each adjustment new corner cases appeared.
Eventually we concluded that the randomized retry approach is more obvious and understandable.

## Log replication

Once a leader has been elected, it begins servicing client requests. Each client request contains a command to be executed by the replicated state machines.
The leader appends the command to its log as a new entry, then issues AppendEntries RPCs in parallel to each of the other servers to replicate the entry.
When the entry has been safely replicated, the leader applies the entry to its state machine and returns the result of that execution to the client.
If followers crash or run slowly, or if network packets are lost, the leader retries AppendEntries RPCs indefinitely (**even after it has responded to the client**) until all followers eventually store all log entries.

Logs are composed of entries, which are numbered sequentially. 
**Each entry contains the term in which it was created (the number in each box) and a command for the state machine.**
An entry is considered committed if it is safe for that entry to be applied to state machines.
Each log entry also has an integer index identifying its position in the log.

We designed the Raft log mechanism to maintain a high level of coherency between the logs on different servers.
Not only does this simplify the system’s behavior and make it more predictable, but it is an important component of ensuring safety.
Raft maintains the following properties:

- If two entries in different logs have the same index and term, then they store the same command.
- If two entries in different logs have the same index and term, then the logs are identical in all preceding entries.

no-op log

[On the Parallels between Paxos and Raft, and how to Port Optimizations](https://ipads.se.sjtu.edu.cn/_media/publications/wang_podc19.pdf)

[Paxos vs Raft: Have we reached consensus on distributed consensus?](https://www.ics.uci.edu/~cs237/reading/Paxos_vs_Raft.pdf)

## Safety

## Links

- [Consensus](/docs/CS/Distributed/Consensus.md)
- [Paxos](/docs/CS/Distributed/Paxos.md)

## References

1. [The Raft Consensus Algorithm](https://raft.github.io/)
2. [Raft - 论文导读与ETCD源码解读 - 硬核课堂](https://hardcore.feishu.cn/docs/doccnMRVFcMWn1zsEYBrbsDf8De)
3. [In Search of an Understandable Consensus Algorithm(Extended Version)](https://raft.github.io/raft.pdf)
4. [CONSENSUS: BRIDGING THEORY AND PRACTICE](https://web.stanford.edu/~ouster/cgi-bin/papers/OngaroPhD.pdf)
5. [Implementing Linearizability at Large Scale and Low Latency](https://web.stanford.edu/~ouster/cgi-bin/papers/rifl.pdf)
6. [Coracle: Evaluating Consensus at the Internet Edge](https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p85.pdf)