## Introduction

ReactiveX is a combination of the best ideas from
the Observer pattern, the Iterator pattern, and functional programming


The `java.util.Observable` and `java.util.Observer` interface have been deprecated. 
The event model supported by Observer and Observable is quite limited, the order of notifications delivered by Observable is unspecified, and state changes are not in one-for-one correspondence with notifications. 

- For a richer event model, consider using the java.beans package. 
- For reliable and ordered messaging among threads, consider using one of the concurrent data structures in the java.util.concurrent package. 
- For reactive streams style programming, see the java.util.concurrent.Flow API.


Flow

Interrelated interfaces and static methods for establishing flow-controlled components in which Publishers produce items consumed by one or more Subscribers, 
each managed by a Subscription.

## References
1. [ReactiveX](http://reactivex.io/)