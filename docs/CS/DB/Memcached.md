## Introduction

[Memcached](https://www.memcached.org/) is an in-memory key-value store for small chunks of arbitrary data (strings, objects) from results of database calls, API calls, or page rendering.
Free & open source, high-performance, distributed memory object caching system, generic in nature, but intended for use in speeding up dynamic web applications by alleviating database load.



## Architecture

- main thread
- cthread pool




worker thread
- notiofy_receive_fd
- notiofy_send_fd


thread_libevent_process



## Distributed

Memcached Server不互相通信

客户端实现分布式

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Cache](/docs/CS/SE/Cache.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- Twemcache
- Twemproxy
- MemcacheDB
- MemcacheQ


## References
1. [Scaling Memcached at Facebook](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf) 
2. 