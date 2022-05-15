## Introduction

> [!NOTE]
> 
> Deadlock can be defined formally as follows:
> 
> A set of processes is deadlocked if each process in the set is waiting for an event that only another process in the set can cause.

A major class of deadlocks involves resources to which some process has been granted exclusive access.
In short, a resource is anything that must be acquired, used, and released over the course of time.

Resources come in two types: preemptable and nonpreemptable.

In general, deadlocks involve nonpreemptable resources.

In most cases, the event that each process is waiting for is the release of some resource currently possessed by another member of the set.
This kind of deadlock is called a resource deadlock.

### Necessary Conditions

A deadlock situation can arise if the following four conditions hold simultaneously in a system:
1. Mutual exclusion. 
   At least one resource must be held in a nonsharable mode; that is, only one thread at a time can use the resource. 
   If another thread requests that resource, the requesting thread must be delayed until the resource has been released.
2. Hold and wait. 
   A thread must be holding at least one resource and waiting to acquire additional resources that are currently being held by other threads.
3. No preemption. 
   Resources cannot be preempted; that is, a resource can be released only voluntarily by the thread holding it, after that thread has completed its task.
4. Circular wait.

All four of these conditions must be present for a resource deadlock to occur.
The circular-wait condition implies the hold-and-wait condition, so the four conditions are not completely independent.


### Handling Deadlocks

In general, four strategies are used for dealing with deadlocks.
1. Just ignore the problem. Maybe if you ignore it, it will ignore you.
2. Detection and recovery. Let them occur, detect them, and take action.
3. Dynamic avoidance by careful resource allocation.
4. Prevention, by structurally negating one of the four conditions.

The first solution is the one used by most operating systems, including Linux and Windows. 
It is then up to kernel and application developers to write programs that handle deadlocks.


## Deadlock Avoidance

Deadlock avoidance is essentially impossible, because it requires information about future requests, which is not known.

### Safe State


### Banker’s Algorithm

In practice, few, if any, existing systems use the banker’s algorithm for avoiding deadlocks. 
Some systems, however, use heuristics similar to those of the banker’s algorithm to prevent deadlock. 
For instance, networks may throttle traffic when buffer utilization reaches higher than, say, 70%—estimating that the remaining 30% will be sufficient for current users to complete their service and return their resources.


## Deadlock Prevention

### Mutual Exclusion

The mutual-exclusion condition must hold. That is, at least one resource must be nonsharable. Sharable resources do not require mutually exclusive access and thus cannot be involved in a deadlock.
> [!TIP]
> 
> Avoid assigning a resource unless absolutely necessary, and try to make sure that as few processes as possible may actually claim the resource.

### Hold and Wait

One protocol that we can use requires each thread to request and be allocated all its resources before it begins execution.

An alternative different way to break the hold-and-wait condition is to require a process requesting a resource to first temporarily release all the resources it currently holds. 
Then it tries to get everything it needs all at once.

Both these protocols have two main disadvantages. 
- First, resource utilization may be low, since resources may be allocated but unused for a long period.
- Second, starvation is possible.

### No Preemption

To ensure that this condition does not hold, we can use the following protocol. 
If a thread is holding some resources and requests another resource that cannot be immediately allocated to it (that is, the thread must wait), then all resources the thread is currently holding are preempted. 
In other words, these resources are implicitly released.

This protocol is often applied to resources whose state can be easily saved and restored later, such as CPU registers and database transactions. 
It cannot generally be applied to such resources as mutex locks and semaphores, precisely the type of resources where deadlock occurs most commonly.


### Circular Wait

One way to ensure that this condition never holds is to impose a total ordering of all resource types and to require that each thread requests resources in an increasing order of enumeration.

Keep in mind that developing an ordering, or hierarchy, does not in itself prevent deadlock. It is up to application developers to write programs that follow the ordering.

It is also important to note that imposing a lock ordering does not guarantee deadlock prevention if locks can be acquired dynamically.
For example, assume we have a function that transfers funds between two accounts.
```c
void transaction(Account from, Account to, double amount)
{
    mutex lock1, lock2;
    lock1 = get lock(from);
    lock2 = get lock(to);
    acquire(lock1);
    acquire(lock2);
    withdraw(from, amount);
    deposit(to, amount);
    release(lock2);
    release(lock1);
}
```
To prevent a race condition, each account has an associated mutex lock that is obtained from a get lock() function.
Deadlock is possible if two threads simultaneously invoke the transaction() function, transposing different accounts. 
That is, one thread might invoke
```c
transaction(checking account, savings account, 25.0)
```
and another might invoke
```c
transaction(savings account, checking account, 50.0)
```



## Deadlock Detection and Recovery


### Deadlock Detection


When to look for deadlocks comes up? 
- One possibility is to check every time a resource request is made. This is certain to detect them as early as possible, but it is potentially expensive in terms of CPU time. 
- An alternative strategy is to check every k minutes, or perhaps only when the CPU utilization has dropped below some threshold. 
  The reason for considering the CPU utilization is that if enough processes are deadlocked, there will be few runnable processes, and the CPU will often be idle.


### Deadlock Recovery

#### Recovery through Preemption

To eliminate deadlocks using resource preemption, we successively preempt some resources from processes and give these resources to other processes until the deadlock cycle is broken.

If preemption is required to deal with deadlocks, then three issues need to be addressed:
1. Selecting a victim
2. Rollback
3. Starvation


#### Recovery through Rollback

If the system designers and machine operators know that deadlocks are likely, they can arrange to have processes checkpointed periodically.

#### Recovery through Killing Processes

To eliminate deadlocks by aborting a process or thread, we use one of two methods. In both methods, the system reclaims all resources allocated to the terminated processes.
- Abort all deadlocked processes. This method clearly will break the deadlock cycle, but at great expense. 
  The deadlocked processes may have computed for a long time, and the results of these partial computations must be discarded and probably will have to be recomputed later.
- Abort one process at a time until the deadlock cycle is eliminated. 
  This method incurs considerable overhead, since after each process is aborted, a deadlock-detection algorithm must be invoked to determine whether any processes are still deadlocked.

If the partial termination method is used, then we must determine which deadlocked process (or processes) should be terminated. 
This determination is a policy decision, similar to CPU-scheduling decisions. The question is basically an economic one; we should abort those processes whose termination will incur the minimum cost. 
Unfortunately, the term minimum cost is not a precise one.


## Other Issues

### Two-Phase Locking

### Communication Deadlocks

Resource deadlock is a problem of *competition synchronization*.

Another kind of deadlock can occur in communication systems (e.g., networks), in which two or more processes communicate by sending messages. 
A common arrangement is that process A sends a request message to process B, and then blocks until B sends back a reply message. 
Suppose that the request message gets lost. A is blocked waiting for the reply. B is blocked waiting for a request asking it to do something. We have a deadlock.
This situation is called a *communication deadlock* to contrast it with the more common resource deadlock.
Communication deadlock is an anomaly of *cooperation synchronization*. The processes in this type of deadlock could not complete service if executed independently.

Communication deadlocks cannot be prevented by ordering the resources(since there are no resources) or avoided by careful scheduling (since there are no moments when a request could be postponed).
Fortunately, there is another technique that can usually be employed to break communication deadlocks: **timeouts**. 
In most network communication systems, whenever a message is sent to which a reply is expected, a timer is started. 
If the timer goes off before the reply arrives, the sender of the message assumes that the message has been lost and sends it again(and again and again if needed). 
In this way, the deadlock is broken. Phrased differently, the timeout serves as a heuristic to detect deadlocks and enables recovery. 
This heuristic is applicable to resource deadlock also and is relied upon by users with temperamental or buggy device drivers that can deadlock and freeze the system.

Not all deadlocks occurring in communication systems or networks are communication deadlocks. Resource deadlocks can also occur there.
No packet can move because there is no buffer at the receiver and we have a classical resource deadlock, albeit in the middle of a communications system.

### Livelock

Livelock is another form of liveness failure.
Livelock occurs when a thread continuously attempts an action that fails.
Livelock typically occurs when threads retry failing operations at the same time. 
It thus can generally be avoided by having each thread retry the failing operation at random times. This is precisely the approach taken by Ethernet networks when a network collision occurs. 
Rather than trying to retransmit a packet immediately after a collision occurs, a host involved in a collision will backoff a random period of time before attempting to transmit again.

Livelock is less common than deadlock but nonetheless is a challenging issue in designing concurrent applications, and like deadlock, it may only occur under specific scheduling circumstances.

### Starvation

A problem closely related to deadlock and livelock is starvation. In a dynamic system, requests for resources happen all the time. Some policy is needed to make a decision about who gets which resource when. 
This policy, although seemingly reasonable, may lead to some processes never getting service even though they are not deadlocked.

Starvation can be avoided by using a first-come, first-served resource allocation policy. With this approach, the process waiting the longest gets served next.
In due course of time, any giv en process will eventually become the oldest and thus get the needed resource.



## Links


- [Operating Systems](/docs/CS/OS/OS.md)
- [Processes and Threads](/docs/CS/OS/process.md)
