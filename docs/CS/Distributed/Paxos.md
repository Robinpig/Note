## Introduction

Paxos is a family of distributed algorithms used to reach consensus.

## Basic Paxos

Paxos defines three roles: *proposers*, *acceptors*, and *learners*.
Paxos nodes can take multiple roles, even all of them.

Assume that nodes can communicate with one another by sending messages.
We use the customary asynchronous, non-Byzantine model, in which:

- Agents operate at arbitrary speed, may fail by stopping, and may restart.
  Since all agents may fail after a value is chosen and then restart, a solution is impossible unless some information can be remembered by an agent that has failed and restarted.
- Messages can take arbitrarily long to be delivered, can be duplicated, and can be lost, but they are not corrupted.

Assume a collection of processes that can propose values.
A consensus algorithm ensures that a single one among the proposed values is chosen.
If no value is proposed, then no value should be chosen.
If a value has been chosen, then processes should be able to learn the chosen value.

The safety requirements for consensus are:

- Only a value that has been proposed may be chosen,
- Only a single value is chosen, and
- A process never learns that a value has been chosen unless it actually has been.

Single acceptor is unsatisfactory because the failure of the acceptor makes any further progress impossible.
Instead of a single acceptor, let’s use multiple acceptor agents.
A proposer sends a proposed value to a set of acceptors.
To ensure that only a single value is chosen, we can let a large enough set consist of any majority of the agents.

Paxos nodes must know how many acceptors a majority is.

We see that the algorithm operates in the following two phases.

Phase 1.

- A proposer selects a proposal number n and sends a prepare request with number n to a majority of acceptors.
- If an acceptor receives a prepare request with number n greater than that of any prepare request to which it has already responded,
  then it responds to the request with a promise not to accept any more proposals numbered less than n and with the highest-numbered proposal (if any) that it has accepted.

Phase 2

- If the proposer receives a response to its prepare requests(numbered n) from a majority of acceptors, then it sends an accept request to each of those acceptors for a proposal numbered n with a value v,
  where v is the value of the highest-numbered proposal among the responses, or is any value if the responses reported no proposals.
- If an acceptor receives an accept request for a proposal numbered n, it accepts the proposal unless it has already responded to a prepare request having a number greater than n.

To learn that a value has been chosen, a learner must find out that a proposal has been accepted by a majority of acceptors.

The acceptors could respond with their acceptances to some set of distinguished learners, each of which can then inform all the learners when a value has been chosen.
Using a larger set of distinguished learners provides greater reliability at the cost of greater communication complexity.

Because of message loss, a value could be chosen with no learner ever finding out.
The learner could ask the acceptors what proposals they have accepted, but failure of an acceptor could make it impossible to know whether or not a majority had accepted a particular proposal.
In that case, learners will find out what value is chosen only when a new proposal is chosen.
If a learner needs to know whether a value has been chosen, it can have a proposer issue a proposal, using the algorithm described above.

If enough of the system (proposer, acceptors, and communication network) is working properly, liveness can therefore be achieved by electing a single distinguished proposer.
FLP implies that a reliable algorithm for electing a proposer must use either randomness or real time—for example, by using timeouts.
However, safety is ensured regardless of the success or failure of the election.

In normal operation, a single server is elected to be the leader, which acts as the distinguished proposer (the only one that tries to issue proposals) in all instances of the consensus algorithm.

In the Paxos consensus algorithm, the value to be proposed is not chosen until phase 2.
After completing phase 1 of the proposer’s algorithm, either the value to be proposed is determined or else the proposer is free to propose any value.

This discussion of the normal operation of the system assumes that there is always a single leader, except for a brief period between the failure of the current leader and the election of a new one.
In abnormal circumstances, the leader election might fail.
If no server is acting as leader, then no new commands will be proposed. If multiple servers think they are leaders, then they can all propose values in the same instance of the consensus algorithm, which could prevent any value from being chosen.
However, safety is preserved—two different servers will never disagree on the value chosen as the i th state machine command. Election of a single leader is needed only to ensure progress.

Since failure of the leader and election of a new one should be rare events, the effective cost of executing a state machine command—that is, of achieving consensus on the command/value—is the cost of executing only phase 2 of the consensus algorithm.
It can be shown that phase 2 of the Paxos consensus algorithm has the minimum possible cost of any algorithm for reaching agreement in the presence of faults.
Hence, the Paxos algorithm is essentially optimal.

Paxos nodes must be persistent: they can't forget what they accepted.

A Paxos run aims at reaching a single consensus.
Once a consensus is reached, it cannot progress to another consensus.

If the set of servers can change, then there must be some way of determining what servers implement what instances of the consensus algorithm.
The easiest way to do this is through the state machine itself.
The current set of servers can be made part of the state and can be changed with ordinary state-machine commands.
We can allow a leader to get α commands ahead by letting the set of servers that execute instance $i + \alpha$ of the consensus algorithm be specified by the state after execution of the i th state machine command.
This permits a simple implementation of an arbitrarily sophisticated reconfiguration algorithm.

[Revisiting the Paxos algorithm](http://citeseer.ist.psu.edu/viewdoc/download;jsessionid=C6EF80E450719CD5457C0E85CCDD0999?doi=10.1.1.44.5607&rep=rep1&type=pdf)

[Fast Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2005-112.pdf)

[Cheap Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/web-dsn-submission.pdf)

[How to Build a Highly Available System Using Consensus](https://www.microsoft.com/en-us/research/uploads/prod/1996/10/Acrobat-58-Copy.pdf)

[Consensus on Transaction Commit](https://www.microsoft.com/en-us/research/uploads/prod/2004/01/twophase-revised.pdf)

[Brewer’s conjecture and the feasibility of consistent, available, partition-tolerant web services](https://users.ece.cmu.edu/~adrian/731-sp04/readings/GL-cap.pdf)

## Multi-Paxos



Algorithmic Challenges

Dick corruption

Master leases

Epoch numbers

Group membership

Snapshots

Database transactions


- Disk Paxos
- Cheap Paxos
- Fast Paxos
- EPaxos
- Vertical Paxos
- Flexible Paxos
- CASPaxos
- Mencius


## Links

- [Consensus](/docs/CS/Distributed/Consensus.md)

## References

1. [The Part-Time Parliament](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Part-Time-Parliament.pdf)
2. [Paxos Made Simple](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/paxos-simple-Copy.pdf)
3. [Paxos Made Live - An Engineering Perspective](https://www.cs.albany.edu/~jhh/courses/readings/chandra.podc07.paxos.pdf)
4. [The Paxos Algorithm](https://www.youtube.com/watch?v=d7nAGI_NZPk&ab_channel=GoogleTechTalks)
5. [Consensus Protocols: Paxos](https://www.the-paper-trail.org/post/2009-02-03-consensus-protocols-paxos/)
6. [Viewstamped Replication: A New Primary Copy Method to Support Highly-Available Distributed Systems](https://pmg.csail.mit.edu/papers/vr.pdf)
