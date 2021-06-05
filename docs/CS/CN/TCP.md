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



三次握手

| 类型 | 描述         |      |
| :--- | ------------ | ---- |
| SYN  | 初始建立连接 |      |
| ACK  | 确认SYN      |      |
| RST  |              |      |
| FIN  | 断开连接     |      |
| PSH  |              |      |
| URG  |              |      |

`Synchronize Sequence Numbers`

`Acknowledge character`

SYN -> SYN + ACK ->ACK

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

