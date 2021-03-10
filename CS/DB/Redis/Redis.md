# Redis

[Redis](https://redis.io)

> Redis is an open source (BSD licensed), in-memory data structure store, used as a database, cache, and message broker. Redis provides data structures such as strings, hashes, lists, sets, sorted sets with range queries, bitmaps, hyperloglogs, geospatial indexes, and streams. Redis has built-in replication, Lua scripting, LRU eviction, transactions, and different levels of on-disk persistence, and provides high availability via Redis Sentinel and automatic partitioning with Redis Cluster.

## Install

- Docker

- make source
- apt-get(Ubuntu) yum(RedHat) brew(Mac)



## 数据类型

### 键管理

- 获取所有的键应采用SCAN而非KEYS（易阻塞）
- 删除键（较大）时使用UNLINK较DEL性能更好
- RENAME时可先EXISTS判断存在时先使用UNLINK



### 字符串

Redis里所有键都为字符串

Redis**不直接使用**C中的字符串类型，而是作为字面量。

字符串主要使用SDS （**Simple Dynamic String** ）：

```c
struct  sdshdr{
//记录buf中已保存字符的长度
//等于SDS所保存的字符串的长度
int  len;
//记录buf数组中未使用字节的数量
int free;
//字节数组，用于保存字符串
char buf[];
};
```

 SDS为了能够**使用部分C字符串函数**，遵循了C字符串以空字符结尾的惯例，保存空字符的1字节不计算在SDSlen属性中，并且为空字符分配额外的1字节空间，以及添加空字符到字符串末尾等操作，都是由SDS函数自动完成的，可以说**空字符对使用者是透明的** 。

- 常数复杂度获取字符串长度

  len属性获取长度

- 杜绝缓冲区溢出

  可以在超过free空间时自动动态扩展内存

- 减少修改字符串时带来的内存重分配次数

  -  空间预分配

     当字符串长度小于 **1M** 时，扩容都是加倍现有的空间，如果超过 1M，扩容时一次只会多扩 1M 的空间。(字符串最大长度为 **512M**) 

  -  惰性空间释放 

    free可以用以记录未被使用的空间，不需重新构建新的字符串对象。

- 二进制安全

  **字节数组**，不同于C语言的字符数组。

### 列表

双向链表

### 哈希

### 集合

### 有序集合

### HLL

HyperLogLog 实质是当作字符串存储

### Geo

实质存储为有序集合

## 数据特性

### 位图

底层数据类型为字符串，

### 键过期时间

键的过期时间为存储为一绝对UNIX时间戳

### 管道

使用管道将多个命令放入同一个执行队列中，减少往返时延消耗。

### 事务

使用WATCH对键设置标志，使用MULTI启动事务，若发生非期待状态，放弃该事务。Redis事务无回滚功能

## 持久化机制

### RDB

快照snapshot，SAVE使用主线程同步转储，BGSAVEfork()出子进程转储。文件名默认为dump.rdb。但数据一致性不高，但转储恢复速度更快，占用存储空间更少。

### AOF

写入操作的日志，fsync()将写缓冲区中内容刷新到磁盘，写入AOF文件。

AOF重写可压缩AOF文件，对键过期时间有变动的数据按情况处理。

## 集群演变

### 单机 

持久化技术  可用性不强

### 主从复制

备份数据，减轻读压力；缺陷是故障恢复无法自动化 写操作无法负载均衡 

### 哨兵

故障恢复自动化，故障恢复时服务不可用

### 集群

## 缓存

缓存能极大减小数据库压力，读走缓存，写不走缓存。

### 缓存分类

#### CDN 缓存

**CDN**(Content Delivery Network 内容分发网络)的基本原理是广泛采用各种缓存服务器，将这些缓存服务器分布到用户访问相对集中的地区或网络中。

在用户访问网站时，利用全局负载技术将用户的访问指向距离最近的工作正常的缓存服务器上，由缓存服务器直接响应用户请求。

**应用场景**：主要用于缓存静态资源，例如图片，视频。

#### 反向代理缓存

 

反向代理位于应用服务器机房，处理所有对 Web 服务器的请求。

如果用户请求的页面在代理服务器上有缓冲的话，代理服务器直接将缓冲内容发送给用户。

如果没有缓冲则先向 Web 服务器发出请求，取回数据，本地缓存后再发送给用户。通过降低向 Web 服务器的请求数，从而降低了 Web 服务器的负载。

**应用场景**:一般只缓存体积较小静态文件资源，如 css、js、图片。

 

#### 本地缓存

Encache,Guava

客户端：浏览器缓存 页面缓存

#### 分布式缓存

Redis Memcached

### 缓存失效策略

一般而言，缓存系统中都会对缓存的对象设置一个超时时间，避免浪费相对比较稀缺的缓存资源。对于缓存时间的处理有两种，分别是主动失效和被动失效。

#### 主动失效

主动失效是指系统有一个主动检查缓存是否失效的机制，比如通过定时任务或者单独的线程不断的去检查缓存队列中的对象是否失效，如果失效就把他们清除掉，避免浪费。主动失效的好处是能够避免内存的浪费，但是会占用额外的CPU时间。

#### 被动失效

被动失效是通过访问缓存对象的时候才去检查缓存对象是否失效，这样的好处是系统占用的CPU时间更少，但是风险是长期不被访问的缓存对象不会被系统清除。

### 缓存淘汰策略

缓存淘汰，又称为缓存逐出(cache replacement algorithms或者cache replacement policies)，是指在存储空间不足的情况下，缓存系统主动释放一些缓存对象获取更多的存储空间。

对于大部分内存型的分布式缓存（非持久化），淘汰策略优先于失效策略，一旦空间不足，缓存对象即使没有过期也会被释放。这里只是简单介绍一下，相关的资料都很多，一般LRU用的比较多，可以重点了解一下。

#### FIFO

先进先出（First In First Out）是一种简单的淘汰策略，缓存对象以队列的形式存在，如果空间不足，就释放队列头部的（先缓存）对象。一般用链表实现。

#### LRU

最近最久未使用（Least Recently Used），这种策略是根据访问的时间先后来进行淘汰的，如果空间不足，会释放最久没有访问的对象（上次访问时间最早的对象）。比较常见的是通过优先队列来实现。

#### LFU

最近最少使用（Least Frequently Used），这种策略根据最近访问的频率来进行淘汰，如果空间不足，会释放最近访问频率最低的对象。这个算法也是用优先队列实现的比较常见。

### 分布式缓存的常见问题

#### 数据一致性问题

缓存数据和数据库数据不一致，

#### 缓存穿透

DB中不存在数据，每次都穿过缓存查DB，造成DB的压力。一般是对Key-Value进行网络攻击。

**解决方案**：

- 对结果为空的数据也进行缓存，当此 Key 有数据后，清理缓存。
- 一定不存在的 Key，采用布隆过滤器，建立一个大的 Bitmap 中，查询时通过该 Bitmap 过滤。

#### 缓存击穿

- 在缓存失效的瞬间大量请求，造成DB的压力瞬间增大
- 解决方案：更新缓存时使用分布式锁锁住服务，防止请求穿透直达DB

#### 缓存雪崩

- 大量缓存设置了相同的失效时间，同一时间失效，造成服务瞬间性能急剧下降
- 解决方案：缓存时间使用基本时间加上随机时间

## 分布式锁

### 实现方案

- 基于数据库实现分布式锁
- 基于缓存，实现分布式锁，如redis
- 基于Zookeeper实现分布式锁

#### 基于数据库

基于数据库的锁实现也有两种方式，一是基于数据库表，另一种是基于数据库排他锁。

##### 基于数据库表的增删

##### 基于数据库排他锁

 存在的问题主要是性能不高和sql超时的异常。 

##### 基于数据库锁的优缺点

上面两种方式都是依赖数据库的一张表，一种是通过表中的记录的存在情况确定当前是否有锁存在，另外一种是通过数据库的排他锁来实现分布式锁。

- 优点是直接借助数据库，简单容易理解。
- 缺点是操作数据库需要一定的开销，性能问题需要考虑。

#### 基于Zookeeper

基于zookeeper**临时有序节点**可以实现的分布式锁。每个客户端对某个方法加锁时，在zookeeper上的与该方法对应的指定节点的目录下，生成一个唯一的瞬时有序节点。 判断是否获取锁的方式很简单，只需要判断有序节点中序号最小的一个。 当释放锁的时候，只需将这个瞬时节点删除即可。同时，其可以避免服务宕机导致的锁无法释放，而产生的死锁问题。

提供的第三方库有[curator](https://curator.apache.org/)，具体使用读者可以自行去看一下。Curator提供的InterProcessMutex是分布式锁的实现。acquire方法获取锁，release方法释放锁。另外，锁释放、阻塞锁、可重入锁等问题都可以有有效解决。讲下阻塞锁的实现，客户端可以通过在ZK中创建顺序节点，并且在节点上绑定监听器，一旦节点有变化，Zookeeper会通知客户端，客户端可以检查自己创建的节点是不是当前所有节点中序号最小的，如果是就获取到锁，便可以执行业务逻辑。

最后，Zookeeper实现的分布式锁其实存在一个缺点，那就是性能上可能并没有缓存服务那么高。因为每次在创建锁和释放锁的过程中，都要动态创建、销毁瞬时节点来实现锁功能。ZK中创建和删除节点只能通过Leader服务器来执行，然后将数据同不到所有的Follower机器上。并发问题，可能存在网络抖动，客户端和ZK集群的session连接断了，zk集群以为客户端挂了，就会删除临时节点，这时候其他客户端就可以获取到分布式锁了。

#### 基于缓存

相对于基于数据库实现分布式锁的方案来说，基于缓存来实现在性能方面会表现的更好一点，存取速度快很多。而且很多缓存是可以集群部署的，可以解决单点问题。基于缓存的锁有好几种，如memcached、redis、本文下面主要讲解基于redis的分布式实现。

## 基于redis的分布式锁实现

### SETNX

使用redis的SETNX实现分布式锁，多个进程执行以下Redis命令：

```
SETNX lock.id <current Unix time + lock timeout + 1>
```

SETNX是将 key 的值设为 value，当且仅当 key 不存在。若给定的 key 已经存在，则 SETNX 不做任何动作。

- 返回1，说明该进程获得锁，SETNX将键 lock.id 的值设置为锁的超时时间，当前时间 +加上锁的有效时间。
- 返回0，说明其他进程已经获得了锁，进程不能进入临界区。进程可以在一个循环中不断地尝试 SETNX 操作，以获得锁。

### 存在死锁的问题

SETNX实现分布式锁，可能会存在死锁的情况。与单机模式下的锁相比，分布式环境下不仅需要保证进程可见，还需要考虑进程与锁之间的网络问题。某个线程获取了锁之后，断开了与Redis 的连接，锁没有及时释放，竞争该锁的其他线程都会hung，产生死锁的情况。

在使用 SETNX 获得锁时，我们将键 lock.id 的值设置为锁的有效时间，线程获得锁后，其他线程还会不断的检测锁是否已超时，如果超时，等待的线程也将有机会获得锁。然而，锁超时，我们不能简单地使用 DEL 命令删除键 lock.id 以释放锁。

考虑以下情况:

> 1. A已经首先获得了锁 lock.id，然后线A断线。B,C都在等待竞争该锁；
> 2. B,C读取lock.id的值，比较当前时间和键 lock.id 的值来判断是否超时，发现超时；
> 3. B执行 DEL lock.id命令，并执行 SETNX lock.id 命令，并返回1，B获得锁；
> 4. C由于各刚刚检测到锁已超时，执行 DEL lock.id命令，将B刚刚设置的键 lock.id 删除，执行 SETNX lock.id命令，并返回1，即C获得锁。

上面的步骤很明显出现了问题，导致B,C同时获取了锁。在检测到锁超时后，线程不能直接简单地执行 DEL 删除键的操作以获得锁。

对于上面的步骤进行改进，问题是出在删除键的操作上面，那么获取锁之后应该怎么改进呢？
首先看一下redis的GETSET这个操作，`GETSET key value`，将给定 key 的值设为 value ，并返回 key 的旧值(old value)。利用这个操作指令，我们改进一下上述的步骤。

> 1. A已经首先获得了锁 lock.id，然后线A断线。B,C都在等待竞争该锁；
> 2. B,C读取lock.id的值，比较当前时间和键 lock.id 的值来判断是否超时，发现超时；
> 3. B检测到锁已超时，即当前的时间大于键 lock.id 的值，B会执行
>    `GETSET lock.id `设置时间戳，通过比较键 lock.id 的旧值是否小于当前时间，判断进程是否已获得锁；
> 4. B发现GETSET返回的值小于当前时间，则执行 DEL lock.id命令，并执行 SETNX lock.id 命令，并返回1，B获得锁；
> 5. C执行GETSET得到的时间大于当前时间，则继续等待。

在线程释放锁，即执行 DEL lock.id 操作前，需要先判断锁是否已超时。如果锁已超时，那么锁可能已由其他线程获得，这时直接执行 DEL lock.id 操作会导致把其他线程已获得的锁释放掉。

### 一种实现方式

#### 获取锁

```java
public boolean lock(long acquireTimeout, TimeUnit timeUnit) throws InterruptedException { 
    acquireTimeout = timeUnit.toMillis(acquireTimeout);    
    long acquireTime = acquireTimeout + System.currentTimeMillis();    
    //使用J.U.C的ReentrantLock   
    threadLock.tryLock(acquireTimeout, timeUnit);   
    try {    	
        //循环尝试       
        while (true) {        	
            //调用tryLock           
            boolean hasLock = tryLock();            
            if (hasLock) {               
                //获取锁成功               
                return true;           
            } else if (acquireTime < System.currentTimeMillis()) {  
                break;           
            }            
            Thread.sleep(sleepTime);      
        }   
    } finally {     
        if (threadLock.isHeldByCurrentThread()) {             
        threadLock.unlock();       
        }   
    }    
    return false;}public boolean tryLock() {    
    long currentTime = System.currentTimeMillis();   
    String expires = String.valueOf(timeout + currentTime);                              
    //设置互斥量    
    if (redisHelper.setNx(mutex, expires) > 0) {   
        //获取锁，设置超时时间       
        setLockStatus(expires);       
        return true;   
    } else {        
        String currentLockTime = redisUtil.get(mutex);       
        //检查锁是否超时        
        if (Objects.nonNull(currentLockTime) && Long.parseLong(currentLockTime) < currentTime) {            
            //获取旧的锁时间并设置互斥量            
            String oldLockTime = redisHelper.getSet(mutex, expires);            
            //旧值与当前时间比较           
            if (Objects.nonNull(oldLockTime) && Objects.equals(oldLockTime, currentLockTime)) {                                                                                          //获取锁，设置超时时间                                            
                setLockStatus(expires);                                          
                return true;            
            }       
        }       
        return false;   
    }
}
```

lock调用tryLock方法，参数为获取的超时时间与单位，线程在超时时间内，获取锁操作将自旋在那里，直到该自旋锁的保持者释放了锁。

tryLock方法中，主要逻辑如下：

- setnx(lockkey, 当前时间+过期超时时间) ，如果返回1，则获取锁成功；如果返回0则没有获取到锁
- get(lockkey)获取值oldExpireTime ，并将这个value值与当前的系统时间进行比较，如果小于当前系统时间，则认为这个锁已经超时，可以允许别的请求重新获取
- 计算newExpireTime=当前时间+过期超时时间，然后getset(lockkey, newExpireTime) 会返回当前lockkey的值currentExpireTime
- 判断currentExpireTime与oldExpireTime 是否相等，如果相等，说明当前getset设置成功，获取到了锁。如果不相等，说明这个锁又被别的请求获取走了，那么当前请求可以直接返回失败，或者继续重试

#### 释放锁

```java
public boolean unlock() {    
    //只有锁的持有线程才能解锁    
    if (lockHolder == Thread.currentThread()) {        
        //判断锁是否超时，没有超时才将互斥量删除        
        if (lockExpiresTime > System.currentTimeMillis()) { 
            redisHelper.del(mutex);            
            logger.info("删除互斥量[{}]", mutex);        
        }        
        lockHolder = null;        
        logger.info("释放[{}]锁成功", mutex);        
        return true;    
    } else {       
        throw new IllegalMonitorStateException("没有获取到锁的线程无法执行解锁操作");   
    }
}
```