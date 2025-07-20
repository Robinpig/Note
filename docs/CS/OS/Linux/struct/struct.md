## Introduction




## llist


多个生产者 和一个或者多个消费者的场景

多个消费者只可以使用llist_del_all ，只有单个消费者才能使用llist_del_first
Linux中断的上半部分需要关闭所有中断 使系统失去响应 为了减少失去响应的时间 上半部分不能加锁 这时可以使用llist 通过 cmpxchg 做 CAS处理




## Links


- [Linux](/docs/CS/OS/Linux/Linux.md)