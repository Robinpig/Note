## Introduction

We have two kinds of locks:

- **Optimistic**: instead of blocking something potentially dangerous happens, we continue anyway, in the hope that everything will be ok.
- **Pessimistic**: block access to the resource before operating on it, and we release the lock at the end.

To use **optimistic** lock, we usually use a version field on the database record we have to handle, and when we update it, we check if the data we read has the same version of the data we are writing.

Database access libraries like [Hibernate](https://docs.jboss.org/hibernate/orm/current/userguide/html_single/Hibernate_User_Guide.html#locking-optimistic) usually provide facilities to use an optimistic lock.

The **pessimistic lock**, instead, will rely on an external system that will hold the lock for our microservices.

Locks are problematic by their very nature; perhaps we should seek to avoid using them unless we truly must.

## Evaluation Lcoks

- provide mutual exclusion
- fairness
  - starve
- performance
  - lock-free
  - MPSC
  - MPMC

Dekker

The simplest bit of hardware support to understand is known as a test-and-set (or atomic exchange1) instruction.
Each architecture that supports test-and-set calls it by a different name.
On SPARC it is called the load/store unsigned byte instruction (`ldstub`); on x86 it is the locked version of the atomic exchange (`xchg`).

Another hardware primitive that some systems provide is known as the compare-and-swap instruction (as it is called on SPARC, for example), or compare-and-exchange (as it called on x86).

## Spin Locks

To work correctly on a single processor, it requires a preemptive scheduler (i.e., one that will interrupt a thread via a timer, in order to run a different thread, from time to time).
Without preemption, spin locks don’t make much sense on a single CPU, as a thread spinning on a CPU will never relinquish it.

Spin locks don’t provide any fairness guarantees. Indeed, a thread spinning may spin forever, under contention. Simple spin locks (as discussed thus far) are not fair and may lead to starvation.

For spin locks, in the single CPU case, performance overheads can be quite painful; imagine the case where the thread holding the lock is preempted within a critical section.
The scheduler might then run every other thread (imagine there are N − 1 others), each of which tries to acquire the lock.
In this case, each of those threads will spin for the duration of a time slice before giving up the CPU, a waste of CPU cycles.
However, on multiple CPUs, spin locks work reasonably well (if the number of threads roughly equals the number of CPUs).
The thinking goes as follows: imagine Thread A on CPU 1 and Thread B on CPU 2, both contending for a lock. If Thread A (CPU 1) grabs the lock, and then Thread B tries to, B will spin (on CPU 2).
However, presumably the critical section is short, and thus soon the lock becomes available, and is acquired by Thread B.
Spinning to wait for a lock held on another processor doesn’t waste many cycles in this case, and thus can be effective.

## Two-Phase Locks

## Distributed Lock

Fault-tolerant consensus is expensive.
Exclusive access by a single process (also known as locking) is cheap, but it is not fault-tolerant—if a process fails while it is holding a lock, no one else can access the resource.
Adding a timeout to a lock makes a fault-tolerant lock or ‘lease’.
Thus a process holds a lease on a state component or ‘resource’ until an expiration time; we say that the process is the ‘master’ for the resource while it holds the lease.
No other process will touch the resource until the lease expires.
For this to work, of course, the processes must have synchronized clocks.
More precisely, if the maximum skew between the clocks of two processes is ε and process P’s lease expires at time t, then P knows that no other process will touch the resource before time t – ε on P’s clock.

While it holds the lease the master can read and write the resource freely.
Writes must take bounded time, so that they can be guaranteed either to fail or to precede any operation that starts after the lease expires;
this can be a serious problem for a resource such as a SCSI disk, which has weak ordering guarantees and a long upper bound on the time a write can take.

A process can keep control of a resource by renewing its lease before it expires.
It can also release its lease, perhaps on demand.
If you can’t talk to the process that holds the lease, however (perhaps because it has failed), you have to wait for the lease to expire before touching its resource.
So there is a tradeoff between the cost of renewing a lease and the time you have to wait for the lease to expire after a (possible) failure.
A short lease means a short wait during recovery but a higher cost to renew the lease.
A long lease means a long wait during recovery but a lower cost to renew.

As for optimistic lock, database access libraries like Hibernate usually provide facilities, but in a distributed scenario, we would use more specific solutions that are used to implement more complex algorithms like:

- [Redis](/docs/CS/DB/Redis/Lock.md) uses libraries that implement a lock algorithm like [ShedLock](https://github.com/lukas-krecan/ShedLock), and [Redisson](https://github.com/redisson/redisson/wiki/8.-Distributed-locks-and-synchronizers).
  The first one provides lock implementation using also other systems like MongoDB, DynamoDB, and more.
- [Zookeeper](/docs/CS/Java/Zookeeper/ZooKeeper.md?id=lock) provides some recipes about locking.
- [Hazelcast](https://hazelcast.com/blog/long-live-distributed-locks/) offers a lock system based on his [CP subsystem](https://docs.hazelcast.org/docs/3.12.3/manual/html-single/index.html#cp-subsystem).
- [有赞 Bond](https://tech.youzan.com/bond/)




数据库 select for update



Redisson lua based on Redis single thread model

RedissonLock#unlockInnerAsync

- delete whe decrement to zero
- broadcast to waiting

Implementing a pessimistic lock, we have a big issue; what happens if the lock owner doesn’t release it? The lock will be held forever and we could be in a **deadlock**.
To prevent this issue, we will set an **expiration time** on the lock, so the lock will be **auto-released**.

But if the time expires before the task is finished by the first lock holder, another microservice can acquire the lock, and both lock holders can now release the lock, causing inconsistency.
Remember, no timer assumption can be reliable in asynchronous networks.

We need to use a **fencing token,** which is incremented each time a microservice acquires a lock.
This token must be passed to the lock manager when we release the lock, so if the first owner releases the lock before the second owner, the system will refuse the second lock release.
Depending on the implementation, we can also decide to let win the second lock owner.

scenarios:

- lock timeout and retry
- exclusion unlock
- unlock gratefully before shutdown
- reentrant lock
- lock TTL
- hot key

## Lock-based Concurrent Data Structures

The approximate counter works by representing a single logical counter via numerous local physical counters, one per CPU core, as well as a single global counter.
Specifically, on a machine with four CPUs, there are four local counters and one global one.
In addition to these counters, there are also locks: one for each local counter, and one for the global counter.

The basic idea of approximate counting is as follows.
When a thread running on a given core wishes to increment the counter, it increments its local counter; access to this local counter is synchronized via the corresponding local lock.
Because each CPU has its own local counter, threads across CPUs can update local counters without contention, and thus updates to the counter are scalable.

However, to keep the global counter up to date (in case a thread wishes to read its value), the local values are periodically transferred to the global counter, by acquiring the global lock and incrementing it by the local counter’s value; the local counter is then reset to zero.

How often this local-to-global transfer occurs is determined by a threshold S.
The smaller S is, the more the counter behaves like the non-scalable counter above; the bigger S is, the more scalable the counter, but the further off the global value might be from the actual count.
One could simply acquire all the local locks and the global lock (in a specified order, to avoid deadlock) to get an exact value, but that is not scalable.

### Concurrent Linked List

Enable more concurrency within a list is something called **hand-over-hand locking** (a.k.a. **lock coupling**).
Instead of having a single lock for the entire list, you instead add a lock per node of the list.
When traversing the list, the code first grabs the next node’s lock and then releases the current node’s lock (which inspires the name hand-over-hand).

Conceptually, a hand-over-hand linked list makes some sense; it enables a high degree of concurrency in list operations.
However, in practice, it is hard to make such a structure faster than the simple single lock approach, as the overheads of acquiring and releasing locks for each node of a list traversal is prohibitive.
Even with very large lists, and a large number of threads, the concurrency enabled by allowing multiple ongoing traversals is unlikely to be faster than simply grabbing a single lock, performing an operation,
and releasing it. Perhaps some kind of hybrid (where you grab a new lock every so many nodes) would be worth investigating.

### Concurrent Queues

Instead of having a single lock, we use two locks, one for the head of the queue, and one for the tail.
The goal of these two locks is to enable concurrency of enqueue and dequeue operations.
In the common case, the enqueue routine will only access the tail lock, and dequeue only the head lock.

Add a dummy node (allocated in the queue initialization code); this dummy enables the separation of head and tail operations.

Queues are commonly used in multi-threaded applications.
However, the type of queue used here (with just locks) often does not completely meet the needs of such programs.
A more fully developed bounded queue, that enables a thread to wait if the queue is either empty or overly full(condition variables).

### Concurrent Hash Table

Instead of having a single lock for the entire structure, it uses a lock per hash bucket (each of which is represented by a list). Doing so enables many concurrent operations to take place.

## Condition Variables

A **condition variable** is an explicit queue that threads can put themselves on when some state of execution(i.e., some condition) is not as desired (by **waiting** on the condition);
some other thread, when it changes said state, can then wake one (or more) of those waiting threads and thus allow them to continue (by **signaling** on the condition).

> [!TIP]
>
> Always hold the lock when calling `signal` or `wait`.
>
> Remember with condition variables is to always use while loops.

A covering condition covers all the cases where a thread needs to wake up (conservatively).
In general, if you find that your program only works when you change your signals to broadcasts (but you don’t think it should need to), you probably have a bug; fix it!

## Semaphores

A semaphore is an object with an integer value that we can manipulate with two routines; in the POSIX standard, these routines are `sem_wait()` and `sem_post()`.

Because the initial value of the semaphore determines its behavior, before calling any other routine to interact with the semaphore, we must first initialize it to some value.

### Binary Semaphores (Locks)

We simply surround the critical section of interest with a sem wait()/sem post() pair.
The initial value should be 1.

```c
sem_t m;
sem_init(&m, 0, X); // initialize semaphore to X; what should X be?

sem_wait(&m);
// critical section here
sem_post(&m);
```

### Reader-Writer Locks

### Implement Semaphores

Implementing Zemaphores With Locks And CVs:

```c

typedef struct __Zem_t {
  int value;
  pthread_cond_t cond;
  pthread_mutex_t lock;
} Zem_t;

// only one thread can call this
void Zem_init(Zem_t *s, int value) {
  s->value = value;
  Cond_init(&s->cond);
  Mutex_init(&s->lock);
}

void Zem_wait(Zem_t *s) {
  Mutex_lock(&s->lock);
  while (s->value <= 0)
  Cond_wait(&s->cond, &s->lock);
  s->value--;
  Mutex_unlock(&s->lock);
}

void Zem_post(Zem_t *s) {
  Mutex_lock(&s->lock);
  s->value++;
  Cond_signal(&s->cond);
  Mutex_unlock(&s->lock);
}
```

We use just one lock and one condition variable, plus a state variable to track the value of the semaphore.
Curiously, building condition variables out of semaphores is a much trickier proposition.

## References

1. [Everything I Know About Distributed Locks](https://dzone.com/articles/everything-i-know-about-distributed-locks)
2. [Leases: an efficient fault-tolerant mechanism for distributed file cache consistency](https://dl.acm.org/doi/pdf/10.1145/74851.74870)
3. [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
4. [A simple distributed lock with memcached](https://bluxte.net/musings/2009/10/28/simple-distributed-lock-memcached/)
5. [Distributed resource locking using memcached](https://source.coveo.com/2014/12/29/distributed-resource-locking/)
6. [The Chubby lock service for loosely-coupled distributed systems]()
7. [Redis and Zookeeper for distributed lock](https://www.fatalerrors.org/a/redis-and-zookeeper-for-distributed-lock.html)
