## Introduction

- Configuration Management
- Rendezvous
- Group Membership
- Simple Locks
- Read/Write Locks

The replicated database is an **in-memory** database containing the entire data tree.
Each znode in the tree stores a maximum of 1MB of data by default, but this maximum value is a configuration parameter that can be changed in specific cases.
For recoverability, we efficiently log updates to disk, and we force writes to be on the disk media before they are applied to the in-memory database.
In fact, as Chubby, we keep a replay log (a write-ahead log, in our case) of committed operations and generate periodic snapshots of the in-memory database.

Every ZooKeeper server services clients. Clients connect to exactly one server to submit its requests.
As we noted earlier, read requests are serviced from the local replica of each server database.
Requests that change the state of the service, write requests, are processed by an agreement protocol.

As part of the agreement protocol write requests are forwarded to a single server, called the leader1.
The rest of the ZooKeeper servers, called followers, receive message proposals consisting of state changes from the leader and agree upon state changes.

Since the messaging layer is atomic, we guarantee that the local replicas never diverge, although at any point in time some servers may have applied more transactions than others.
Unlike the requests sent from clients, the transactions are *idempotent*.
When the leader receives a write request, it calculates what the state of the system will be when the write is applied and transforms it into a transaction that captures this new state.
The future state must be calculated because there may be outstanding transactions that have not yet been applied to the database.
For example, if a client does a conditional setData and the version number in the request matches the future version number of the znode being updated, the service generates a setDataTXN that contains the new data, the new version number, and updated time stamps.
If an error occurs, such as mismatched version numbers or the znode to be updated does not exist, an errorTXN is generated instead.

During normal operation Zab does deliver all messages in order and exactly once, but since Zab does not
persistently record the id of every message delivered,
Zab may redeliver a message during recovery. Because
we use idempotent transactions, multiple delivery is acceptable as long as they are delivered in order. In fact,
ZooKeeper requires Zab to redeliver at least all messages
that were delivered after the start of the last snapshot.

### Barriers

Barriers are implemented in ZooKeeper by designating a barrier node. The barrier is in place if the barrier node exists. Here's the pseudo code:

1. Client calls the ZooKeeper API's **exists()** function on the barrier node, with *watch* set to true.
2. If **exists()** returns false, the barrier is gone and the client proceeds
3. Else, if **exists()** returns true, the clients wait for a watch event from ZooKeeper for the barrier node.
4. When the watch event is triggered, the client reissues the **exists( )** call, again waiting until the barrier node is removed.

#### Double Barriers

Double barriers enable clients to synchronize the beginning and the end of a computation.
When enough processes have joined the barrier, processes start their computation and leave the barrier once they have finished.

### Queues

To implement a distributed queue in ZooKeeper, first designate a znode to hold the queue, the queue node.
The distributed clients put something into the queue by calling create() with a pathname ending in "queue-", with the *sequence* and *ephemeral* flags in the create() call set to true.
Because the *sequence* flag is set, the new pathname will have the form  *path-to-queue-node* /queue-X, where X is a monotonic increasing number.
A client that wants to be removed from the queue calls ZooKeeper's **getChildren( )** function, with *watch* set to true on the queue node, and begins processing nodes with the lowest number.
The client does not need to issue another **getChildren( )** until it exhausts the list obtained from the first **getChildren( )** call.
If there are no children in the queue node, the reader waits for a watch notification to check the queue again.

#### Priority Queues

To implement a priority queue, you need only make two simple changes to the generic queue recipe.

- First, to add to a queue, the pathname ends with "queue-YY" where YY is the priority of the element with lower numbers representing higher priority (just like UNIX).
- Second, when removing from the queue, a client uses an up-to-date children list meaning that the client will invalidate previously obtained children lists if a watch notification triggers for the queue node.

### Locks

Fully distributed locks that are globally synchronous, meaning at any snapshot in time no two clients think they hold the same lock.
These can be implemented using ZooKeeper. As with priority queues, first define a lock node.

Here are a few things to notice:

- The removal of a node will only cause one client to wake up since each node is watched by exactly one client. In this way, you avoid the *herd effect*.
- There is no polling or timeouts.
- Because of the way you implement locking, it is easy to see the amount of lock contention, break locks, debug locking problems, etc.

```java
public interface LockListener {
    void lockAcquired();

    void lockReleased();
}
```

Attempts to acquire the exclusive write lock returning whether or not it was acquired. Note that the exclusive lock may be acquired some time later after this method has been invoked due to the current lock owner going away.

```
public class WriteLock extends ProtocolSupport {
    public synchronized boolean lock() throws KeeperException, InterruptedException {
        if (isClosed()) {
            return false;
        }
        ensurePathExists(dir);

        return (Boolean) retryOperation(zop);
    }
}
```

the command that is run and retried for actually obtaining the lock.

delay =

```
attemptCount * 0.5s
```

```
RETRY_COUNT = 10
```

```
 @SuppressFBWarnings(
            value = "NP_NULL_PARAM_DEREF_NONVIRTUAL",
            justification = "findPrefixInChildren will assign a value to this.id")
        public boolean execute() throws KeeperException, InterruptedException {
            do {
                if (id == null) {
                    long sessionId = zookeeper.getSessionId();
                    String prefix = "x-" + sessionId + "-";
                    // lets try look up the current ID if we failed
                    // in the middle of creating the znode
                    findPrefixInChildren(prefix, zookeeper, dir);
                    idName = new ZNodeName(id);
                }
                List<String> names = zookeeper.getChildren(dir, false);
                if (names.isEmpty()) {
                    LOG.warn("No children in: {} when we've just created one! Lets recreate it...", dir);
                    // lets force the recreation of the id
                    id = null;
                } else {
                    // lets sort them explicitly (though they do seem to come back in order ususally :)
                    SortedSet<ZNodeName> sortedNames = new TreeSet<>();
                    for (String name : names) {
                        sortedNames.add(new ZNodeName(dir + "/" + name));
                    }
                    ownerId = sortedNames.first().getName();
                    SortedSet<ZNodeName> lessThanMe = sortedNames.headSet(idName);
                    if (!lessThanMe.isEmpty()) {
                        ZNodeName lastChildName = lessThanMe.last();
                        lastChildId = lastChildName.getName();
                        LOG.debug("Watching less than me node: {}", lastChildId);
                        Stat stat = zookeeper.exists(lastChildId, new LockWatcher());
                        if (stat != null) {
                            return Boolean.FALSE;
                        } else {
                            LOG.warn("Could not find the stats for less than me: {}", lastChildName.getName());
                        }
                    } else {
                        if (isOwner()) {
                            LockListener lockListener = getLockListener();
                            if (lockListener != null) {
                                lockListener.lockAcquired();
                            }
                            return Boolean.TRUE;
                        }
                    }
                }
            }
            while (id == null);
            return Boolean.FALSE;
        }
```

### Two-phased Commit

A two-phase commit protocol is an algorithm that lets all clients in a distributed system agree either to commit a transaction or abort.

In ZooKeeper, you can implement a two-phased commit by having a coordinator create a transaction node, say "/app/Tx", and one child node per participating site, say "/app/Tx/s_i".
When coordinator creates the child node, it leaves the content undefined. Once each site involved in the transaction receives the transaction from the coordinator, the site reads each child node and sets a watch.
Each site then processes the query and votes "commit" or "abort" by writing to its respective node.
Once the write completes, the other sites are notified, and as soon as all sites have all votes, they can decide either "abort" or "commit". Note that a node can decide "abort" earlier if some site votes for "abort".

An interesting aspect of this implementation is that the only role of the coordinator is to decide upon the group of sites, to create the ZooKeeper nodes, and to propagate the transaction to the corresponding sites.
In fact, even propagating the transaction can be done through ZooKeeper by writing it in the transaction node.

There are two important drawbacks of the approach described above. One is the message complexity, which is O(n²). The second is the impossibility of detecting failures of sites through ephemeral nodes.
To detect the failure of a site using ephemeral nodes, it is necessary that the site create the node.

To solve the first problem, you can have only the coordinator notified of changes to the transaction nodes, and then notify the sites once coordinator reaches a decision.
Note that this approach is scalable, but it's is slower too, as it requires all communication to go through the coordinator.

To address the second problem, you can have the coordinator propagate the transaction to the sites, and have each site creating its own ephemeral node.

### Leader Election

A simple way of doing leader election with ZooKeeper is to use the *SEQUENCE|EPHEMERAL* flags when creating znodes that represent "proposals" of clients.
The idea is to have a znode, say "/election", such that each znode creates a child znode "/election/n_" with both flags SEQUENCE|EPHEMERAL.
With the sequence flag, ZooKeeper automatically appends a sequence number that is greater that any one previously appended to a child of "/election".
The process that created the znode with the smallest appended sequence number is the leader.

To avoid the herd effect, it is sufficient to watch for the next znode down on the sequence of znodes.
If a client receives a notification that the znode it is watching is gone, then it becomes the new leader in the case that there is no smaller znode.
Note that this avoids the herd effect by not having all clients watching the same znode.

Once configured, invoking start() will cause the client to connect to ZooKeeper and create a leader offer.

```java
 public synchronized void start() {
        state = State.START;
        dispatchEvent(EventType.START);

        LOG.info("Starting leader election support");

        if (zooKeeper == null) {
            throw new IllegalStateException(
                "No instance of zookeeper provided. Hint: use setZooKeeper()");
        }

        if (hostName == null) {
            throw new IllegalStateException(
                "No hostname provided. Hint: use setHostName()");
        }

        try {
            makeOffer();
            determineElectionStatus();
        } catch (KeeperException | InterruptedException e) {
            becomeFailed(e);
        }
    }
```

```java
private void makeOffer() throws KeeperException, InterruptedException {
        state = State.OFFER;
        dispatchEvent(EventType.OFFER_START);

        LeaderOffer newLeaderOffer = new LeaderOffer();
        byte[] hostnameBytes;
        synchronized (this) {
            newLeaderOffer.setHostName(hostName);
            hostnameBytes = hostName.getBytes();
            newLeaderOffer.setNodePath(zooKeeper.create(rootNodeName + "/" + "n_",
                                                        hostnameBytes, ZooDefs.Ids.OPEN_ACL_UNSAFE,
                                                        CreateMode.EPHEMERAL_SEQUENTIAL));
            leaderOffer = newLeaderOffer;
        }
        LOG.debug("Created leader offer {}", leaderOffer);

        dispatchEvent(EventType.OFFER_COMPLETE);
    }
```

```java
    private void determineElectionStatus() throws KeeperException, InterruptedException {

        state = State.DETERMINE;
        dispatchEvent(EventType.DETERMINE_START);

        LeaderOffer currentLeaderOffer = getLeaderOffer();

        String[] components = currentLeaderOffer.getNodePath().split("/");

        currentLeaderOffer.setId(Integer.valueOf(components[components.length - 1].substring("n_".length())));

        List<LeaderOffer> leaderOffers = toLeaderOffers(zooKeeper.getChildren(rootNodeName, false));

        /*
         * For each leader offer, find out where we fit in. If we're first, we
         * become the leader. If we're not elected the leader, attempt to stat the
         * offer just less than us. If they exist, watch for their failure, but if
         * they don't, become the leader.
         */
        for (int i = 0; i < leaderOffers.size(); i++) {
            LeaderOffer leaderOffer = leaderOffers.get(i);

            if (leaderOffer.getId().equals(currentLeaderOffer.getId())) {
                LOG.debug("There are {} leader offers. I am {} in line.", leaderOffers.size(), i);

                dispatchEvent(EventType.DETERMINE_COMPLETE);

                if (i == 0) {
                    becomeLeader();
                } else {
                    becomeReady(leaderOffers.get(i - 1));
                }

                /* Once we've figured out where we are, we're done. */
                break;
            }
        }
    }
```


## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Curator](/docs/CS/Framework/ZooKeeper/Curator.md)