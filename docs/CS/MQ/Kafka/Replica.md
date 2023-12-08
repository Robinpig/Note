## Introduction

Follow-Replicas not supported read/write.


Read-your-writes

Monotonic Reads

In-sync Replicas(ISR)

replica.lag.time.max.ms



### Unclean Leader Election


When the leader for a partition is no longer available, one of the in-sync replicas (ISR) will be chosen as the new leader. 
This leader election is "clean" in the sense that it guarantees no loss of committed data - by definition, committed data exists on all ISRs.

But what to do when no ISR exists except for the leader that just became unavailable?

- Wait for an ISR to come back online. 
  This is the default behavior, and this makes you run the risk of the topic becoming unavailable.
- Enable unclean.leader.election.enable=true and start producing to non-ISR partitions.
  We are going to lose all messages that were written to the old leader while that replica was out of sync and also cause some inconsistencies in consumers.

These unclean leader elections can help improve the availability of your cluster, 
but they could result in data loss if you do not duplicate the data to another cluster or other storage destination.
Here’s how that might play out:

1. The broker that is the leader for Partition A goes offline. 
   None of the followers of Partition A are caught up to the leader (ISR=0).
2. If unclean leader elections are enabled, one of the follower brokers will get elected as the new leader for the partition,
   even though it is “unclean.” This allows consumers and producers to continue sending requests to Partition A.
3. If the previous leader comes back online, it will reset its offset to match the new leader’s offset, resulting in data loss. 
   For example, if the previous leader processed messages up to offset=7, and the new, 
   unclean leader was slightly behind (offset=4) at the time it was elected leader, 
   some messages (offsets 5–7) will get deleted after the first leader comes back online and rejoins the cluster as a replica/follower.



## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)