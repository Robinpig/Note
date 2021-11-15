# TCP

`Transmission Control Protocol`

理论最大连接数 2<sup>48</sup>

文件描述符限制 ulimit

内存限制

面向连接



需要建立连接后发送数据

传输包有顺序控制

头部字节20

有错误校验和重传机制

握手协议

可靠传输

## Connection

![tcp_shakehand](./images/tcp_shake.png)

### three-way handshaking
check network and ack initial sequence number

| 类型    | Name            | 描述         |
| :------ | --------------- | ------------ |
| SYN     | synchronize     | 初始建立连接 |
| ACK     | acknowledgement | 确认SYN      |
| SYN-ACK |                 |              |
| FIN     |                 | 断开连接     |

`Synchronize Sequence Numbers`

`Acknowledge character`

SYN -> SYN + ACK ->ACK

 第三次握手方可携带数据



初始序列号ISN生成基于时钟 RFC1948


From [RFC793 - Transmission Control Protocol](https://datatracker.ietf.org/doc/rfc793/)

####  TCP Connection State

```
                                                
                                                
                              +---------+ ---------\      active OPEN
                              |  CLOSED |            \    -----------
                              +---------+<---------\   \   create TCB
                                |     ^              \   \  snd SYN
                   passive OPEN |     |   CLOSE        \   \
                   ------------ |     | ----------       \   \
                    create TCB  |     | delete TCB         \   \
                                V     |                      \   \
                              +---------+            CLOSE    |    \
                              |  LISTEN |          ---------- |     |
                              +---------+          delete TCB |     |
                   rcv SYN      |     |     SEND              |     |
                  -----------   |     |    -------            |     V
 +---------+      snd SYN,ACK  /       \   snd SYN          +---------+
 |         |<-----------------           ------------------>|         |
 |   SYN   |                    rcv SYN                     |   SYN   |
 |   RCVD  |<-----------------------------------------------|   SENT  |
 |         |                    snd ACK                     |         |
 |         |------------------           -------------------|         |
 +---------+   rcv ACK of SYN  \       /  rcv SYN,ACK       +---------+
   |           --------------   |     |   -----------
   |                  x         |     |     snd ACK
   |                            V     V
   |  CLOSE                   +---------+
   | -------                  |  ESTAB  |
   | snd FIN                  +---------+
   |                   CLOSE    |     |    rcv FIN
   V                  -------   |     |    -------
 +---------+          snd FIN  /       \   snd ACK          +---------+
 |  FIN    |<-----------------           ------------------>|  CLOSE  |
 | WAIT-1  |------------------                              |   WAIT  |
 +---------+          rcv FIN  \                            +---------+
   | rcv ACK of FIN   -------   |                            CLOSE  |
   | --------------   snd ACK   |                           ------- |
   V        x                   V                           snd FIN V
 +---------+                  +---------+                   +---------+
 |FINWAIT-2|                  | CLOSING |                   | LAST-ACK|
 +---------+                  +---------+                   +---------+
   |                rcv ACK of FIN |                 rcv ACK of FIN |
   |  rcv FIN       -------------- |    Timeout=2MSL -------------- |
   |  -------              x       V    ------------        x       V
    \ snd ACK                 +---------+delete TCB         +---------+
     ------------------------>|TIME WAIT|------------------>| CLOSED  |
                              +---------+                   +---------+
```
TCP Connection State Diagram


Connect：
client： closed - snd SYN -> SYN-SENT - rcv SYN+ACK and snd ACK -> ESTAB

sever： closed - listen -> Listen - rcv SYN - snd SYN+ACK -> SYN_RCV and rcv ACK -> ESTAB


disconnect：
ESTAB - snd FIN -> FINWAIT-1
- rcv ACK -> FINWAIT-2 - rcv FIN and snd ACK -> TIME_WAIT
- rcv FIN and snd ACK -> CLOSING -> rcv ACK -> TIME_WAIT
- 2MSL -> CLOSED

ESTAB - rcv FIN -> CLOSE WAIT - close and snd FIN -> LAST-ACK -> rcv ACK-> CLOSED



### Header Format

```
    0                   1                   2                   3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |          Source Port          |       Destination Port        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                        Sequence Number                        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                    Acknowledgment Number                      |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |  Data |           |U|A|P|R|S|F|                               |
   | Offset| Reserved  |R|C|S|S|Y|I|            Window             |
   |       |           |G|K|H|T|N|N|                               |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |           Checksum            |         Urgent Pointer        |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                    Options                    |    Padding    |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                             data                              |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

                            TCP Header Format

          Note that one tick mark represents one bit position.
```

​    

| Name                  | Length  | Description                                                  |      |
| --------------------- | ------- | ------------------------------------------------------------ | ---- |
| Source Port           | 16 bits | The source port number.                                      |      |
| Destination Port      | 16 bits | The destination port number..                                |      |
| Sequence Number       | 32 bits | The sequence number of the first data octet in this segment (except     when SYN is present). If SYN is present the sequence number is the     initial sequence number (ISN) and the first data octet is ISN+1. |      |
| Acknowledgment Number | 32 bits | If the ACK control bit is set this field contains the value of the     next sequence number the sender of the segment is expecting to     receive.  Once a connection is established this is always sent. |      |
| Data Offset           | 4 bits |                                                              |      |
| Reserved              | 6 bits |                                                              |      |
| Control Bits          | 6 bits |                                                              |      |
| Window                | 16 bits |                                                              |      |
| Checksum              | 16 bits |                                                              |      |
| Urgent Pointer              | 16 bits |                                                              |      |
| Options              | variable |                                                              |      |
| Padding              | variable |                                                              |      |





Window Scale

a window size 16 bits == 64K

Timestamps

RTTM(`Round Trip Time Measurement`), RTO(`Retransmission timeout`)

PAWS(`Protect Against Wrapped Sequences`)





客户端和服务端ISN不相同：

1. 安全性 防止接受伪造报文
2. 辨别历史报文以丢弃



MTU 和MSS

MTU 网络包最大长度 以太网为1500Byte

MSS 去除IP和TCP头部后 网络包容纳TCP内容最大长度



阻止重复历史连接端初始化

第三次连接可以通过seq num判断是否是历史连接， 是则返回RST终止



同步双方初始序列号

对双方对请求序列号都需要确认，四次握手可简化成三次，但两次握手不能确保初始序列号能被成功接受



减少资源消耗

两次握手时，服务端将在发送完ack+syn后直接进入establish

存在网络阻塞时，客户端未接受到服务端的响应，会试图多次重新建立连接，造成服务端建立连接过多，浪费资源



#### retry

##### syn fail

**scenario**: client send syn fail, server can not receive package

client retry send syn 

RTO(Retransmission Timeout) 1 + 2 <<< (n-1)

n = tcp_syn_retries

```shell
#in linux
cat /proc/sys/net/ipv4/tcp_syn_retries #5
```

##### syn+ack fail

**scenario**: client can not receive syn+ack from server

1. client retry syn until `tcp_syn_retries`, every trying will reset count of server syn+ack
2. server also will retry send syn+ack until `tcp_synack_retries`

syn+ack失败达到tcp_synack_retries后，处于SYN_RECV状态的接收方主动关闭了连接

```shell
# in linux
cat /proc/sys/net/ipv4/tcp_synack_retries #2
```

##### ack fail

**scenario**: client into ESTABLISH after send ack, server can not receive ack

server continue send syn+ack, syn+ack失败达到tcp_synack_retries后，处于SYN_RECV状态的接收方主动关闭了连接

客户端：

1. 连接未使用时，会等待tcp的keepalive机制触发才能发现一个已被关闭的连接 7875 sec

```shell
cat /proc/sys/net/ipv4/tcp_keepalive_time	#7200
cat /proc/sys/net/ipv4/tcp_keepalive_intvl	#75
cat /proc/sys/net/ipv4/tcp_keepalive_probes	#9
```

keepalive_time + ( keepalive_intvl * keepalive_probes ) = 7200 + ( 75 * 9 ) = 7875 seconds

keepalive 不足
   1. TCP Keepalive是扩展选项，不一定所有的设备都支持；
   2. TCP Keepalive报文可能被设备特意过滤或屏蔽，如运营商设备；
   3. TCP Keepalive无法检测应用层状态，如进程阻塞、死锁、TCP缓冲区满等情况；
   4. TCP Keepalive容易与TCP重传控制冲突，从而导致失效。
      

对于TCP状态无法反应应用层状态问题，这里稍微介绍几个场景。第一个是TCP连接成功建立，不代表对端应用感知到了该连接，因为TCP三次握手是内核中完成的，虽然连接已建立完成，但对端可能根本没有Accept；
因此，一些场景仅通过TCP连接能否建立成功来判断对端应用的健康状况是不准确的，这种方案仅能探测进程是否存活。另一个是，本地TCP写操作成功，但数据可能还在本地写缓冲区中、网络链路设备中、对端读缓冲区中，并不代表对端应用读取到了数据。



2. 在试图发送数据包时失败，重传`tcp_retries2`次失败后关闭连接
   RCF1122
```shell
# linux
cat /proc/sys/net/ipv4/tcp_retries2	#3
cat /proc/sys/net/ipv4/tcp_retries2	#15
```
RFC 1122建议对应的超时时间不低于100s 

default send  retries

`tcp_retries1` 失败后通知IP层进行MTU探测、刷新路由等流程而不是关闭连接

同样受timeout限制





#### `sack`

`sack (Selective Acknowledgment)`

当发送方收到三个重复ack，立刻触发快速重传，立即重传丢失数据包

数据包丢失收到重复ack但其他包正常接受， 开启sack可只重传此包， 而不需重传丢失包之后的每一个包

需要双方都开启sack

```shell
#linux
cat /proc/sys/net/ipv4/tcp_sack	#1
```



RFC2883

#### TPO

和HTTP的keepalive不相同，是为了尽可能热连接，减少RTT(Round Trip Time)

首次HTTP请求最快2RTT(第三次握手携带HTTP请求)，若fastopen开启，则生成cookie在下次请求时携带 无需三次握手，只需一次RTT就可以完成HTTP	-- [TCP Fast Open](http://conferences.sigcomm.org/co-next/2011/papers/1569470463.pdf)

```shell
#linux
cat /proc/sys/net/ipv4/tcp_fastopen	#1
```



窗口控制

window



#### Nagle

1. 没有已发送未确认的报文，立即发送
2. 存在已发送未确认的报文时，等待确认报文或者数据到达MSS再发送

第一次发送报文一般较小

在socket里使用TCP_NODELAY关闭Nagle



#### ack delay

1. 有响应数据发送时，ack被携带
2. 无响应数据发送时，等待固定时间发送ack
3. 在固定时间内收到第二次数据报，立刻发送ack

```shell
cat /boot/config-4.18.0-193.el8.x86_64 |grep 'CONFIG_HZ='
CONFIG_HZ=1000
```

最大延迟1000/5 = 200 ms

最小延迟1000/25 = 40 ms

在socket里使用TCP_QUICKACK关闭延时确认



Nagle和延迟确认都开启会互相等待到最大值，增加时延



#### connection queue

1. syn queue/半连接队列
2. accpet queue/全连接队列



##### syn queue

```shell
cat /proc/sys/net/ipv4/tcp_max_syn_backlog	#1024
```



```shell
 # get current syn queue size
 netstat -natp | grep SYN_RECV | wc -l
```



use [`hping3`] mock syn attack



**tcp_syncookies when syn queue is overflow**

```shell
cat /proc/sys/net/ipv4/tcp_syncookies	#1
```



check the syn sockets dropped

```shell
netstat -s|grep "SYNs to LISTEN"
```



**prevent syn attack**

1. expand syn queue and accept queue size
2. enable tcp_syncookies
3. reduce `tcp_synack_retries`to fast quit connection from SYN_RECV

##### accept queue

```shell
# -l show the listening socket
# -n no expain server name
# -t only tcp
ss -lnt
```

in listening

Recv-Q/Send-Q

|        | in Listening              | non-listening             |
| ------ | ------------------------- | ------------------------- |
| Recv-Q | current accept queue size | recv & not read byte size |
| Send-Q | max accept queue size     | send & not ack byte size  |



max accept queue size = `min(backlog,somaxconn)`

backlog are set in `listen(int socked,int backlog)`

```shell
cat /proc/sys/net/core/somaxconn #128
```





use[`wrk`](https://github.com/wg/wrk) to test accept queue overflow

```shell
# -t thread number
# -c connection count
# -d continue time
wrk -t 6 -c 30000 -d 60s http://xxx.xxx.xxx.xxx 
```



建议使用0以防止应用只是短暂的连接过多，利用客户端重试机制尽量可以得到响应而不是直接重置连接

if see `connection reset by peer`, might be accept queue overflow, default will be connection timeout

```shell
# 0 dicard, 1 dicard and return RST
cat /proc/sys/net/ipv4/tcp_abort_on_overflow
```



```shell
netstat -s|grep overflowed
```


### four-way handshaking

FIN -> ACK   FIN -> ACK

```shell
netstat -napt
```



任意一方都有一个FIN 和一个ACK

主动发起的有TIME_WAIT状态 Linux里固定为60s = 2MSL



关闭连接函数`close` |  `shutdown` , close关闭会使连接成为orphan 连接 无进程号





主动方/被动方发送FIN收不到ACK时会重发，重发次数受`tcp_orphan_retries`限制, 降低tcp_orphan_retries能快速关闭连接

```shell
cat /proc/sys/net/ipv4/tcp_orphan_retries	#0 in linux when set tcp_orphan_retries == 0, real 8
```

当恶意请求使得FIN无法发送时，orphan连接会在超过tcp_max_orphans后使用RST重置关闭连接：

1. 缓冲区还有数据未读取时，FIN不发送
2. 窗口大小为0时，只能发送保活探测报文

```shell
cat /proc/sys/net/ipv4/tcp_max_orphans	#8192
```



orphan connection(use close) FIN_WAIT2 timeout tcp_fin_timeout s

```shell
cat /proc/sys/net/ipv4/tcp_fin_timeout	#60
```



TIME_WAIT

1. 防止接收到旧连接的数据
2. 保证连接尽量正常关闭

TIME_WAIT数量超过`tcp_max_tw_buckets`后连接就不经过此状态而直接关闭

```shell
cat /proc/sys/net/ipv4/tcp_max_tw_buckets #5000
```



`tcp_tw_reuse`适用于发起连接的一方(Client use connect())，需结合`tcp_timestamps`使用, 1s后可复用（防止最后的ack丢失）
服务端若要复用，用于连接的socket(not listening socket)配置`SO_REUSEADDR`和`tcp_timestamps`使用，参考netty start
```shell
cat /proc/sys/net/ipv4/tcp_tw_reuse #3
cat /proc/sys/net/ipv4/tcp_timestamps #1 enable
```

[RFC 6191 - Reducing the TIME-WAIT State Using TCP Timestamps](https://datatracker.ietf.org/doc/html/rfc6191)

```shell
net.ipv4.tcp_tw_recycle # 1 enable quick recycle TIME_WAIT sockets

```

当双方都主动发FIN后接受到对方的FIN进入CLOSEING状态之后返回发送ack都进入TIME_WAIT后等待2MSL关闭

### TCP报文交由IP层分片

重传时由于是IP层分片 造成不必要的重传

协商MSS 

SYN攻击：

短时间伪造大量不同IP发来的SYN请求，占满SYN连接队列

策略

1. 配置Linux参数
   1. 设置backlog最大值
   2. 配置RST，丢弃连接
2. 对连接进行合法性验证，通过才加入到Accept队列





use tcpdump capture a tcp request and response

```shell
tcpdump -i any tcp and host xxx.xxx.xxx.xxx and port 80  -w http.pcap
```



use WireShark f

Statistics -> Flow Graph -> TCP Flows


## Examples

### How to optimize TCP

1. for client set syn_retries
2. for server
   1. prevent syn attacks
   2. improve accept queue
3. transport optimizing
   1. expand tcp_window_scaling



socket的SO_SNDBUF/SO_RCVBUF会关闭缓存区动态调整功能

### max connections

1. 文件描述符限制
   系统级：当前系统可打开的最大数量，通过fs.file-max参数可修改
   用户级：指定用户可打开的最大数量，修改/etc/security/limits.conf
   进程级：单个进程可打开的最大数量，通过fs.nr_open参数可修改
   

2 占用资源限制
```shell
sysctl -a | grep rmem
net.ipv4.tcp_rmem = 4096 87380 8388608
net.core.rmem_default = 212992
net.core.rmem_max = 8388608
```

ss

slabtop

### too many CLOSE_WAIT
cause:
1. forget invoke close/shutdown to send FIN
2. backlog too large
