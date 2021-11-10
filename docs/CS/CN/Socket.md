## Introduction


### port
```shell
cat /proc/sys/net/ipv4/ip_local_port_range 
32768	60999
```

```shell
cat /proc/net/snmp

cat /proc/net/netstat

```


socket 套接字是一种数据结构。

## IO多路复用

IO多路复用只需要一个进程就能够处理多个套接字。IO多路复用这个名词看起来好像很复杂很高深的样子。实际上，这项技术所能带来的本质成果就是：**一个服务端进程可以同时处理多个套接字描述符**。

> - **多路**：多个客户端连接（连接就是套接字描述符）
> - **复用**：使用单进程就能够实现同时处理多个客户端的连接

在之前的讲述中，一个服务端进程，只能同时处理一个连接。如果想同时处理多个客户端连接，需要多进程或者多线程的帮助，免不了上下文切换的开销。IO多路复用技术就解决了上下文切换的问题。IO多路复用技术的发展可以分为select->poll->epoll三个阶段。

IO多路复用的核心就是添加了一个**套接字集合管理员**，它可以**同时监听多个套接字**。由于客户端连接以及读写事件到来的随机性，我们需要这个管理员在单进程内部对多个套接字的事件进行合理的调度。

### select

最早的**套接字集合管理员**是select()系统调用，它可以同时管理多个套接字。select()函数会在某个或某些套接字的状态从不可读变为可读、或不可写变为可写的时候通知服务器主进程。所以select()本身的调用是阻塞的。但是具体哪一个套接字或哪些套接字变为可读或可写我们是不知道的，所以我们需要遍历所有select()返回的套接字来判断哪些套接字可以进行处理了。而这些套接字中又可以分为**监听套接字**与**连接套接字**(上文提过)。我们可以使用PHP为我们提供的socket_select()函数。在select()的函数原型中，为套接字们分了个类：读、写与异常套接字集合，分别监听套接字的读、写与异常事件。：

```php
function socket_select (array &$read, array &$write, array &$except, $tv_sec, $tv_usec = 0) {}
```

举个例子，如果某个客户单通过调用connect()连接到了服务器的**监听套接字**（$listenSocket）上，这个监听套接字的状态就会从不可读变为可读。由于监听套接字只有一个，select()对于监听套接字上的处理仍然是阻塞的。一个监听套接字，存在于整个服务器的生命周期中，所以在select()的实现中并不能体现出其对监听套接字的优化管理。
在当一个服务器使用accept()接受多个客户端连接，并生成了多个**连接套接字**之后，select()的管理才能就会体现出来。这个时候，select()的监听列表中有**一个监听套接字**、和与**一堆**客户端建立连接后新创建的**连接套接字**。在这个时候，可能这一堆已建立连接的客户端，都会通过这个连接套接字发送数据，等待服务端接收。假设同时有5个连接套接字都有数据发送，那么这5个连接套接字的状态都会变成可读状态。由于已经有套接字变成了可读状态，select()函数解除阻塞，立即返回。具体哪一个套接字或哪些套接字变为可读或可写我们是不知道的，所以我们需要遍历所有select()返回的套接字，来判断哪些套接字已经就绪，可以进行读写处理。遍历完毕之后，就知道有5个连接套接字可以进行读写处理，这样就实现了同时对多个套接字的管理。使用PHP实现select()的代码如下：

```php
<?php
if (($listenSocket = socket_create(AF_INET, SOCK_STREAM, SOL_TCP))=== false) {
    echo '套接字创建失败';
}
if (socket_bind($listenSocket, '127.0.0.1', 8888) === false) {
    echo '绑定地址与端口失败';
}
if (socket_listen($listenSocket) === false) {
    echo '转换主动套接字到被动套接字失败';
}

/* 要监听的三个sockets数组 */
$read_socks = array(); //读
$write_socks = array(); //写
$except_socks = NULL; //异常

$read_socks[] = $listenSocket; //将初始的监听套接字加入到select的读事件监听数组中

while (1) {
    /* 由于select()是引用传递，所以这两个数组会被改变，所以用两个临时变量 */
    $tmp_reads = $read_socks;
    $tmp_writes = $write_socks;
    $count = socket_select($tmp_reads, $tmp_writes, $except_socks, NULL);
    foreach ($tmp_reads as $read) { //不知道哪些套接字有变化，需要对全体套接字进行遍历来看谁变了
        if ($read == $listenSocket) { //监听套接字有变化，说明有新的客户端连接请求到来
            $connSocket = socket_accept($listenSocket);  //响应客户端连接， 此时一定不会阻塞
            if ($connSocket) {
                //把新建立的连接socket加入监听
                $read_socks[] = $connSocket;
                $write_socks[] = $connSocket;
            }
        } else { //新创建的连接套接字有变化
            /*客户端传输数据 */
            $data = socket_read($read, 1024);  //从客户端读取数据, 此时一定会读到数据，不会产生阻塞
            if ($data === '') { //已经无法从连接套接字中读到数据，需要移除对该socket的监听
                foreach ($read_socks as $key => $val) {
                    if ($val == $read) unset($read_socks[$key]); //移除失效的套接字
                }
                foreach ($write_socks as $key => $val) {
                    if ($val == $read) unset($write_socks[$key]);
                }
                socket_close($read);
            } else { //能够从连接套接字读到数据。此时$read是连接套接字
                if (in_array($read, $tmp_writes)) {
                    socket_write($read, $data);//如果该客户端可写 把数据写回到客户端
                }
            }
        }
    }
}
socket_close($listenSocket);
```

但是，select()函数本身的调用阻塞的。因为select()需要一直等到有状态变化的套接字之后（比如监听套接字或者连接套接字的状态由不可读变为可读），才能解除select()本身的阻塞，继续对读写就绪的套接字进行处理。虽然这里是阻塞的，但是它能够同时返回多个就绪的套接字，而不是之前单进程中只能够处理一个套接字，大大提升了效率
总结一下，select()的过人之处有以下几点：

> - 实现了对多个套接字的同时、集中管理
> - 通过遍历所有的套接字集合，能够获取所有已就绪的套接字，对这些就绪的套接字进行操作不会阻塞

但是，select()仍存在几个问题：

> - select管理的套接字描述符们存在数量限制。在Unix中，一个进程最多同时监听1024个套接字描述符
> - select返回的时候，并不知道具体是哪个套接字描述符已经就绪，所以需要遍历所有套接字来判断哪个已经就绪，可以继续进行读写
> - select 采用的是轮询机制，select被调用时fd_set会被遍历，导致其时间复杂度为O（n）。
> - 内核/用户空间拷贝问题：当有事件发生，且select轮询完后，fd_set会从内核态拷贝到用户态，当并发上来后，轮询的低效率和频繁的内核态用户态切换会导致select的性能急剧下降：

为了解决第一个套接字描述符数量限制的问题，聪明的开发者们想出了poll这个新套接字描述符管理员，用以替换select这个老管理员，select()就可以安心退休啦。

### poll

**poll解决了select带来的套接字描述符的最大数量限制问题**。由于PHP的socket扩展没有poll对应的实现，所以这里放一个Unix的C语言原型实现：

```c
int poll (struct pollfd *fds, unsigned int nfds, int timeout);
```

poll的fds参数集合了select的read、write和exception套接字数组，合三为一。poll中的fds没有了1024个的数量限制。当有些描述符状态发生变化并就绪之后，poll同select一样会返回。但是遗憾的是，我们同样不知道具体是哪个或哪些套接字已经就绪，我们仍需要遍历套接字集合去判断究竟是哪个套接字已经就绪，这一点并没有解决刚才提到select的第二个问题。
我们可以总结一下，select和poll这两种实现，都需要在返回后，通过遍历所有的套接字描述符来获取已经就绪的套接字描述符。事实上，同时连接的大量客户端在一时刻可能只有很少的处于就绪状态，因此随着监视的描述符数量的增长，其效率也会线性下降。
为了解决不知道返回之后究竟是哪个或哪些描述符已经就绪的问题，同时避免遍历所有的套接字描述符，聪明的开发者们又发明出了epoll机制，完美解决了select和poll所存在的问题。

### epoll

epoll是最先进的套接字们的管理员，解决了上述select和poll中所存在的问题。它将一个阻塞的select、poll系统调用拆分成了三个步骤。一次select或poll可以看作是由一次 epoll_create、若干次 epoll_ctl、若干次 epoll_wait构成：

```c
int epoll_create(int size);
int epoll_ctl(int epfd, int op, int fd, struct epoll_event *event)；
int epoll_wait(int epfd, struct epoll_event * events, int maxevents, int timeout);
```

> - epoll_create()：创建一个epoll实例。后续操作会使用
> - epoll_ctl()：对套接字描述符集合进行增删改操作，并告诉内核需要监听套接字描述符的什么事件
> - epoll_wait()：等待监听列表中的**连接事件**（监听套接字描述符才会发生）或**读写事件**（连接套接字描述符才会发生）。如果有某个或某些套接字事件已经准备就绪，就会返回这些已就绪的套接字们

看起来，这三个函数明明就是从select、poll一个函数拆成三个函数了嘛。我们对某套接字描述符的添加、删除、修改操作由之前的代码实现变成了调用epoll_ctl()来实现。epoll_ctl()的参数含义如下：

> - epfd：epoll_create()的返回值
> - op：表示对下面套接字描述符fd所进行的操作。EPOLL_CTL_ADD：将描述符添加到监听列表；EPOLL_CTL_DEL：不再监听某描述符；EPOLL_CTL_MOD：修改某描述符
> - fd：上面op操作的套接字描述符对象（之前在PHP中是与connSocket两种套接字描述符）例如将某个套接字**添加**到监听列表中
> - event：告诉内核需要监听该套接字描述符的什么事件（如读写、连接等）

最后我们调用epoll_wait()等待连接或读写等事件，在某个套接字描述符上准备就绪。当有事件准备就绪之后，会存到第二个参数epoll_event结构体中。通过访问这个结构体就可以得到所有已经准备好事件的套接字描述符。这里就不用再像之前select和poll那样，遍历所有的套接字描述符之后才能知道究竟是哪个描述符已经准备就绪了，这样减少了一次O(n)的遍历，大大提高了效率。
在最后返回的所有套接字描述符中，同样存在之前说过的两种描述符：**监听套接字描述符**和**连接套接字描述符**。那么我们需要遍历所有准备就绪的描述符，然后去判断究竟是监听还是连接套接字描述符，然后视情况做做出accept（监听套接字）或者是read（连接套接字）的处理。一个使用C语言编写的epoll服务器的伪代码如下（重点关注代码注释）：

```c
int main(int argc, char *argv[]) {

    listenSocket = socket(AF_INET, SOCK_STREAM, 0); //同上，创建一个监听套接字描述符
    
    bind(listenSocket)  //同上，绑定地址与端口
    
    listen(listenSocket) //同上，由默认的主动套接字转换为服务器适用的被动套接字
    
    epfd = epoll_create(EPOLL_SIZE); //创建一个epoll实例
    
    ep_events = (epoll_event*)malloc(sizeof(epoll_event) * EPOLL_SIZE); //创建一个epoll_event结构存储套接字集合
    event.events = EPOLLIN;
    event.data.fd = listenSocket;
    
    epoll_ctl(epfd, EPOLL_CTL_ADD, listenSocket, &event); //将监听套接字加入到监听列表中
    
    while (1) {
    
        event_cnt = epoll_wait(epfd, ep_events, EPOLL_SIZE, -1); //等待返回已经就绪的套接字描述符们
        
        for (int i = 0; i < event_cnt; ++i) { //遍历所有就绪的套接字描述符
            if (ep_events[i].data.fd == listenSocket) { //如果是监听套接字描述符就绪了，说明有一个新客户端连接到来
            
                connSocket = accept(listenSocket); //调用accept()建立连接
                
                event.events = EPOLLIN;
                event.data.fd = connSocket;
                
                epoll_ctl(epfd, EPOLL_CTL_ADD, connSocket, &event); //添加对新建立的连接套接字描述符的监听，以监听后续在连接描述符上的读写事件
                
            } else { //如果是连接套接字描述符事件就绪，则可以进行读写
            
                strlen = read(ep_events[i].data.fd, buf, BUF_SIZE); //从连接套接字描述符中读取数据, 此时一定会读到数据，不会产生阻塞
                if (strlen == 0) { //已经无法从连接套接字中读到数据，需要移除对该socket的监听
                
                    epoll_ctl(epfd, EPOLL_CTL_DEL, ep_events[i].data.fd, NULL); //删除对这个描述符的监听
                    
                    close(ep_events[i].data.fd);
                } else {
                    write(ep_events[i].data.fd, buf, str_len); //如果该客户端可写 把数据写回到客户端
                }
            }
        }
    }
    close(listenSocket);
    close(epfd);
    return 0;
}
```

我们看这个通过epoll实现一个IO多路复用服务器的代码结构，除了由一个函数拆分成三个函数，其余的执行流程基本同select、poll相似。只是epoll会只返回已经就绪的套接字描述符集合，而不是所有描述符的集合，IO的效率不会随着监视fd的数量的增长而下降，大大提升了效率。同时它细化并规范了对每个套接字描述符的管理（如增删改的过程）。此外，它监听的套接字描述符是没有限制的，这样，之前select、poll的遗留问题就全部解决啦。

#### epoll的内部调用流程

![图 2. epoll的内部调用流程](https://upload-images.jianshu.io/upload_images/14368201-d95003f50adb77ec.png?imageMogr2/auto-orient/strip%7CimageView2/2/w/1240)

(0) 红黑树是在mmap出的内存上的，减少了用户空间和内核空间的拷贝
(1) epoll_wait调用ep_poll，当rdlist为空（无就绪fd）时挂起当前进程，知道rdlist不空时进程才被唤醒。
(2) 文件fd状态改变（buffer由不可读变为可读或由不可写变为可写），导致相应fd上的回调函数ep_poll_callback()被调用。
(3) ep_poll_callback将相应fd对应epitem加入rdlist，导致rdlist不空，进程被唤醒，epoll_wait得以继续执行。
(4) ep_events_transfer函数将rdlist中的epitem拷贝到txlist中，并将rdlist清空。
(5) ep_send_events函数，它扫描txlist中的每个epitem，调用其关联fd对用的poll方法。之后将取得的events和相应的fd发送到用户空间（封装在struct epoll_event，从epoll_wait返回）。
(6) 如果这个epitem对应的fd是LT模式监听且取得的events是用户所关心的，则将其重新加入回rdlist。否则（ET模式）不在加入rdlist。

#### ET模式与LT模式的不同

ET和LT模式下的epitem都可以通过插入红黑树时的回调（ep_poll_callback）方式加入rdlist从而唤醒epoll_wait，但LT模式下的epitem还可以通过txlist（ep_send_events）重新加入rdlist唤醒epoll_wait。所以ET模式下，fd就绪，只会被通知一次，而LT模式下只要满足相应读写条件就返回就绪（通过txlist加入rdlist）。

####  直接回调插入

直接回调插入：fd状态改变才会触发。

对于读取操作：

(1) 当buffer由不可读状态变为可读的时候，即由空变为不空的时候。

(2) 当有新数据到达时，即buffer中的待读内容变多的时候。

对于写操作：

(1) 当buffer由不可写变为可写的时候，即由满状态变为不满状态的时候。

(2) 当有旧数据被发送走时，即buffer中待写的内容变少得时候。

#### txlist

txlist（ep_send_events）：fd的events中有相应的事件（位置1）即会触发。

对于读操作：

(1) buffer中有数据可读的时候，即buffer不空的时候fd的events的可读为就置1。

对于写操作：

(1) buffer中有空间可写的时候，即buffer不满的时候fd的events的可写位就置1。

### 总结

与select相比，epoll的回调机制使得资源能够直接使用在有活动的事件上，而不用线性轮询所有的事件。同时 epoll通过内核与用户空间mmap同一块内存，减少了用户空间和内核空间的数据交换，解决了select的重要痛点。

另一方面，LT是epoll的默认操作模式，当epoll_wait函数检测到有事件发生并将通知应用程序，而应用程序不一定必须立即进行处理，这样epoll_wait函数再次检测到此事件的时候还会通知应用程序，直到事件被处理。

而ET模式，只要epoll_wait函数检测到事件发生，通知应用程序立即进行处理，后续的epoll_wait函数将不再检测此事件。因此ET模式在很大程度上降低了同一个事件被epoll触发的次数，因此效率比LT模式高。