## Introduction

Follow-Replicas not supported read/write.


Read-your-writes

Monotonic Reads

In-sync Replicas(ISR)

replica.lag.time.max.ms



### Unclean Leader Election


When the leader for a partition is no longer available, one of the in-sync replicas (ISR) will be chosen as the new leader. This leader election is "clean" in the sense that it guarantees no loss of committed data - by definition, committed data exists on all ISRs.

But what to do when no ISR exists except for the leader that just became unavailable?

Wait for an ISR to come back online. This is the default behavior, and this makes you run the risk of the topic becoming unavailable.

Enable unclean.leader.election.enable=true and start producing to non-ISR partitions. We are going to lose all messages that were written to the old leader while that replica was out of sync and also cause some inconsistencies in consumers.

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)