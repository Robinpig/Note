## Introduction


In the terminology of [the Go memory model], the n'th call to [Mutex.Unlock] “synchronizes before” the m'th call to [Mutex.Lock] for any n < m.
A successful call to [Mutex.TryLock] is equivalent to a call to Lock.
A failed call to TryLock does not establish any “synchronizes before”relation at all.


## Links

- [Golang](/docs/CS/Go/Go.md)