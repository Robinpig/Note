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

![tcp_shakehand](./images/tcp_shake.png)

three-way handshaking

| 类型    | Name            | 描述         |
| :------ | --------------- | ------------ |
| SYN     | synchronize     | 初始建立连接 |
| ACK     | acknowledgement | 确认SYN      |
| SYN-ACK |                 |              |
| FIN     |                 | 断开连接     |

`Synchronize Sequence Numbers`

`Acknowledge character`

SYN -> SYN + ACK ->ACK

 

syn fail

retry 

RTO 1 + 2 <<< (n-1)

n = tcp_syn_retries

```shell
#in linux
cat /proc/sys/net/ipv4/tcp_syn_retries #5
```

syn+ack fail

client retry syn, and server return syn+ack until tcp_syn_retries

server also will retry, return syn+ack until tcp_synack_retries

syn+ack失败达到tcp_synack_retries后，处于SYN_RECV状态的接收方主动关闭了连接

```shell
# in linux
cat /proc/sys/net/ipv4/tcp_synack_retries #2
```



连接未使用时，会等待tcp的keepalive机制触发才能发现一个已被关闭的连接 7875 sec

或者在试图发送数据包时失败，重传`tcp_retries2`次失败后关闭连接

default send  retries

```shell
# linux
cat /proc/sys/net/ipv4/tcp_retries2	#15
```





```shell
cat /proc/sys/net/ipv4/tcp_keepalive_time	#7200
cat /proc/sys/net/ipv4/tcp_keepalive_intvl	#75
cat /proc/sys/net/ipv4/tcp_keepalive_probes	#9
```

keepalive_time + ( keepalive_intvl * keepalive_probes ) = 7200 + ( 75 * 9 ) = 7875 seconds



#### `sack(Selective Acknowledgment)`

当发送方收到三个重复ack，立刻触发快速重传，立即重传丢失数据包

数据包丢失收到重复ack但其他包正常接受， 开启sack可只重传此包， 而不需重传丢失包之后的每一个包

需要双方都开启sack

```shell
#linux
cat /proc/sys/net/ipv4/tcp_sack	#1
```



RFC2883

#### fastopen

和HTTP的keepalive不相同，是为了尽可能热连接，减少RTT

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

#### 延迟确认

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

### 四次挥手

FIN -> ACK   FIN -> ACK

第三次握手方可携带数据



阻止重复历史连接端初始化

第三次连接可以通过seq num判断是否是历史连接， 是则返回RST终止



同步双方初始序列号

对双方对请求序列号都需要确认，四次握手可简化成三次，但两次握手不能确保初始序列号能被成功接受



减少资源消耗

两次握手时，服务端将在发送完ack+syn后直接进入establish

存在网络阻塞时，客户端未接受到服务端的响应，会试图多次重新建立连接，造成服务端建立连接过多，浪费资源

四次挥手

FIN -> ACK   FIN -> ACK

```shell
netstat -napt
```



初始序列号ISN生成基于时钟 RFC1948

客户端和服务端ISN不相同：

1. 安全性 防止接受伪造报文
2. 辨别历史报文以丢弃



MTU 和MSS

MTU 网络包最大长度 以太网为1500Byte

MSS 去除IP和TCP头部后 网络包容纳TCP内容最大长度



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



四次挥手

任意一方都有一个FIN 和一个ACK

主动发起的有TIME_WAIT状态 Linux里固定为60s = 2MSL

use tcpdump capture a tcp request and response

```shell
tcpdump -i any tcp and host xxx.xxx.xxx.xxx and port 80  -w http.pcap
```



use WireShark 

Statistics -> Flow Graph -> TCP Flows

