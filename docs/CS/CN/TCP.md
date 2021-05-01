# TCP

`Transmission Control Protocol`



面向连接



需要建立连接后发送数据

传输包有顺序控制

头部字节20

有错误校验和重传机制

握手协议

可靠传输



三次握手

| 类型    | 描述         |      |
| :------ | ------------ | ---- |
| SYN     | 初始建立连接 |      |
| ACK     | 确认SYN      |      |
| SYN-ACK |              |      |
| FIN     | 断开连接     |      |

`Synchronize Sequence Numbers`

`Acknowledge character`

SYN -> SYN + ACK ->ACK

 

四次挥手

FIN -> ACK   FIN -> ACK
