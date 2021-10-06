## Introduction

We have two kinds of locks:

- **Optimistic**: instead of blocking something potentially dangerous happens, we continue anyway, in the hope that everything will be ok.
- **Pessimistic**: block access to the resource before operating on it, and we release the lock at the end.

To use **optimistic** lock, we usually use a version field on the database record we have to handle, and when we update it, we check if the data we read has the same version of the data we are writing.

Database access libraries like [Hibernate](https://docs.jboss.org/hibernate/orm/current/userguide/html_single/Hibernate_User_Guide.html#locking-optimistic) usually provide facilities to use an optimistic lock.

The **pessimistic lock**, instead, will rely on an external system that will hold the lock for our microservices.

## Distributed Lock



As for optimistic lock, database access libraries like [Hibernate](https://docs.jboss.org/hibernate/orm/current/userguide/html_single/Hibernate_User_Guide.html#locking-pessimistic) usually provide facilities, but in a distributed scenario, we would use more specific solutions that are used to implement more complex algorithms like:

- [**Redis**](https://redis.io/topics/distlock) uses libraries that implement a lock algorithm like [ShedLock](https://github.com/lukas-krecan/ShedLock), and [Redisson](https://github.com/redisson/redisson/wiki/8.-Distributed-locks-and-synchronizers). The first one provides lock implementation using also other systems like MongoDB, DynamoDB, and more.
- [**Zookeeper**](https://zookeeper.apache.org/doc/r3.5.5/recipes.html#sc_recipes_Locks) provides some recipes about locking.
- [**Hazelcast**](https://hazelcast.com/blog/long-live-distributed-locks/) offers a lock system based on his [CP subsystem](https://docs.hazelcast.org/docs/3.12.3/manual/html-single/index.html#cp-subsystem).

Implementing a pessimistic lock, we have a big issue; what happens if the lock owner doesn’t release it? The lock will be held forever and we could be in a **deadlock**. To prevent this issue, we will set an **expiration time** on the lock, so the lock will be **auto-released**.

But if the time expires before the task is finished by the first lock holder, another microservice can acquire the lock, and both lock holders can now release the lock, causing inconsistency. Remember, no timer assumption can be reliable in asynchronous networks.

We need to use a **fencing token,** which is incremented each time a microservice acquires a lock. This token must be passed to the lock manager when we release the lock, so if the first owner releases the lock before the second owner, the system will refuse the second lock release. Depending on the implementation, we can also decide to let win the second lock owner.



## References

1. [Everything I Know About Distributed Locks](https://dzone.com/articles/everything-i-know-about-distributed-locks)
