## Introduction

Paxos is a family of distributed algorithms used to reach consensus.

## Basic Paxos

Assume a collection of processes that can propose values.
A consensus algorithm ensures that a single one among the proposed values is chosen.
If no value is proposed, then no value should be chosen.
If a value has been chosen, then processes should be able to learn the chosen value.

The safety requirements for consensus are:

- Only a value that has been proposed may be chosen,
- Only a single value is chosen, and
- A process never learns that a value has been chosen unless it actually has been.

Paxos defines three roles: *proposers*, *acceptors*, and *learners*.
Paxos nodes can take multiple roles, even all of them.

Paxos nodes must know how many acceptors a majority is.

Paxos nodes must be persistent: they can't forget what they accepted.

A Paxos run aims at reaching a single consensus.
Once a consensus is reached, it cannot progress to another consensus.

Assume that agents can communicate with one another by sending messages. We use the customary asynchronous, non-Byzantine model, in which:

- Agents operate at arbitrary speed, may fail by stopping, and may restart.
  Since all agents may fail after a value is chosen and then restart, a solution is impossible unless some information can be remembered by an agent that has failed and restarted.
- Messages can take arbitrarily long to be delivered, can be duplicated, and can be lost, but they are not corrupted.

This leads to the following algorithm for issuing proposals.

1. A proposer chooses a new proposal number n and sends a request to each member of some set of acceptors, asking it to respond with:
   1. A promise never again to accept a proposal numbered less than n, and
   2. The proposal with the highest number less than n that it has accepted, if any.
      I will call such a request a prepare request with number n.
2. If the proposer receives the requested responses from a majority of the acceptors, then it can issue a proposal with number n and value v,
   where v is the value of the highest-numbered proposal among the responses,
   or is any value selected by the proposer if the responders reported no proposals.

An acceptor can accept a proposal numbered n iff it has not responded
to a prepare request having a number greater than n.

we see that
the algorithm operates in the following two phases.
Phase 1. (a) A proposer selects a proposal number n and sends a prepare
request with number n to a majority of acceptors.
(b) If an acceptor receives a prepare request with number n greater
than that of any prepare request to which it has already responded,
then it responds to the request with a promise not to accept any more
proposals numbered less than n and with the highest-numbered proposal (if any) that it has accepted.

Phase 2. (a) If the proposer receives a response to its prepare requests
(numbered n) from a majority of acceptors, then it sends an accept
request to each of those acceptors for a proposal numbered n with a
value v, where v is the value of the highest-numbered proposal among
the responses, or is any value if the responses reported no proposals.
(b) If an acceptor receives an accept request for a proposal numbered
n, it accepts the proposal unless it has already responded to a prepare
request having a number greater than n.

[Revisiting the Paxos algorithm](http://citeseer.ist.psu.edu/viewdoc/download;jsessionid=C6EF80E450719CD5457C0E85CCDD0999?doi=10.1.1.44.5607&rep=rep1&type=pdf)

[Fast Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2005-112.pdf)

[Cheap Paxos](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/web-dsn-submission.pdf)

[How to Build a Highly Available System Using Consensus](https://www.microsoft.com/en-us/research/uploads/prod/1996/10/Acrobat-58-Copy.pdf)

[Consensus on Transaction Commit](https://www.microsoft.com/en-us/research/uploads/prod/2004/01/twophase-revised.pdf)

[Brewer’s conjecture and the feasibility of consistent, available, partition-tolerant web services](https://users.ece.cmu.edu/~adrian/731-sp04/readings/GL-cap.pdf)

## Multi-Paxos

- Disk Paxos
- Cheap Paxos
- Fast Paxos
- EPaxos
- Vertical Paxos
- Flexible Paxos
- CASPaxos
- Mencius

## References

1. [The Part-Time Parliament](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/The-Part-Time-Parliament.pdf)
2. [Paxos Made Simple](https://www.microsoft.com/en-us/research/uploads/prod/2016/12/paxos-simple-Copy.pdf)
3. [Paxos Made Live - An Engineering Perspective](https://www.cs.albany.edu/~jhh/courses/readings/chandra.podc07.paxos.pdf)
4. [The Paxos Algorithm](https://www.youtube.com/watch?v=d7nAGI_NZPk&ab_channel=GoogleTechTalks)