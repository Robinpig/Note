## Introduction

The Transmission Control Protocol (TCP) is intended for use as a highly reliable host-to-host protocol between hosts in packet-switched computer communication networks, and in interconnected systems of such networks.

```
                           Protocol Layering

                        +---------------------+
                        |     higher-level    |
                        +---------------------+
                        |        TCP          |
                        +---------------------+
                        |  internet protocol  |
                        +---------------------+
                        |communication network|
                        +---------------------+
```

see [Linux TCP](/docs/CS/OS/Linux/TCP.md)

### Purpose


The primary purpose of the TCP is to provide reliable, securable logical circuit or connection service between pairs of processes.
It provides reliable delivery of data or reliable notification of failure.
To provide this service on top of a less reliable internet communication system requires facilities in the following areas:

- Basic Data Transfer
- Reliability
- Flow Control
- Multiplexing
- Connections
- Precedence and Security



### Connections

To identify the separate data streams that a TCP may handle, the TCP provides a port identifier.  Since port identifiers are selected  independently by each TCP they might not be unique.  To provide for  unique addresses within each TCP, we concatenate an internet address  identifying the TCP with a port identifier to create a [socket]() which will be unique throughout all networks connected together.

A connection is fully specified by the pair of sockets at the ends.  A  local socket may participate in many connections to different foreign  sockets.  A connection can be used to carry data in both directions, that is, it is `"full duplex"`.





The procedures to establish connections utilize the synchronize (SYN)  control flag and involves an exchange of three messages.  This  exchange has been termed a `three-way hand shake `.



### Relation to Other Protocols

The following diagram illustrates the place of the TCP in the protocol  hierarchy:

```
                              
       +------+ +-----+ +-----+       +-----+                    
       |Telnet| | FTP | |Voice|  ...  |     |  Application Level 
       +------+ +-----+ +-----+       +-----+                    
             |   |         |             |                       
            +-----+     +-----+       +-----+                    
            | TCP |     | RTP |  ...  |     |  Host Level        
            +-----+     +-----+       +-----+                    
               |           |             |                       
            +-------------------------------+                    
            |    Internet Protocol & ICMP   |  Gateway Level     
            +-------------------------------+                    
                           |                                     
              +---------------------------+                      
              |   Local Network Protocol  |    Network Level     
              +---------------------------+                      

                         Protocol Relationships
```







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

| Name                  | Length   | Description                                                  |      |
| --------------------- | -------- | ------------------------------------------------------------ | ---- |
| Source Port           | 16 bits  | The source port number.                                      |      |
| Destination Port      | 16 bits  | The destination port number..                                |      |
| Sequence Number       | 32 bits  | The sequence number of the first data octet in this segment (except     when SYN is present). If SYN is present the sequence number is the     initial sequence number (ISN) and the first data octet is ISN+1. |      |
| Acknowledgment Number | 32 bits  | If the ACK control bit is set this field contains the value of the     next sequence number the sender of the segment is expecting to     receive.  Once a connection is established this is always sent. |      |
| Data Offset           | 4 bits   | The number of 32 bit words in the TCP Header.  This indicates where the data begins.  The TCP header (even one including options) is an     integral number of 32 bits long. |      |
| Reserved              | 6 bits   |                                                              |      |
| Control Bits          | 6 bits   | URG:  Urgent Pointer field significant     ACK:  Acknowledgment field significant     PSH:  Push Function     RST:  Reset the connection     SYN:  Synchronize sequence numbers     FIN:  No more data from sender |      |
| Window                | 16 bits  | The number of data octets beginning with the one indicated in the     acknowledgment field which the sender of this segment is willing to     accept. |      |
| Checksum              | 16 bits  |                                                              |      |
| Urgent Pointer        | 16 bits  |                                                              |      |
| Options               | variable |                                                              |      |
| Padding               | variable | The TCP header padding is used to ensure that the TCP header ends     and data begins on a 32 bit boundary.  The padding is composed of     zeros. |      |

#### Options

Options may occupy space at the end of the TCP header and are a multiple of 8 bits in length.  All options are included in the checksum.  An option may begin on any octet boundary.  There are two cases for the format of an option:

**Case 1:**  A single octet of option-kind.

```
       End of Option List
      
              +--------+
              |00000000|
              +--------+
               Kind=0
               
       No-Operation
      
              +--------+
              |00000001|
              +--------+
               Kind=1 
```

**Case 2:**  An octet of option-kind, an octet of option-length, and the actual option-data octets.

```
      Maximum Segment Size

        +--------+--------+---------+--------+
        |00000010|00000100|   max seg size   |
        +--------+--------+---------+--------+
         Kind=2   Length=4
```



## Connection Establishment and Termination

![tcp_shakehand](./images/tcp_shake.png)


### Three-Way Handshake

The following scenario occurs when a TCP connection is established:

1. The server must be prepared to accept an incoming connection. This is normally done by calling socket, bind, and listen and is called a passive open.
2. The client issues an active open by calling connect. 
   This causes the client TCP to send a ‘‘synchronize’’ (SYN) segment, which tells the server the client’s initial sequence number for the data that the client will send on the connection. 
   Normally, there is no data sent with the SYN; it just contains an IP header, a TCP header, and possible TCP options (which we will talk about shortly).
3. The server must acknowledge (ACK) the client’s SYN and the server must also send its own SYN containing the initial sequence number for the data that the server will send on the connection. 
   The server sends its SYN and the ACK of the client’s SYN in a single segment.
4. The client must acknowledge the server’s SYN.

The minimum number of packets required for this exchange is three; hence, this is called TCP’s *three-way handshake*.

Since a SYN occupies one byte of the sequence number space, the acknowledgment number in the ACK of each SYN is the initial sequence number plus one. 
Similarly, the ACK of each FIN is the sequence number of the FIN plus one.

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


- syn retry
- syn + ack retry
- syn queue
- accept queue
- fast open



### Connection Termination

While it takes three segments to establish a connection, it takes four to terminate a connection.
1. One application calls close first, and we say that this end performs the active
   close. This end’s TCP sends a FIN segment, which means it is finished sending
   data.
2. The other end that receives the FIN performs the passive close. The received FIN
   is acknowledged by TCP. The receipt of the FIN is also passed to the application
   as an end-of-file (after any data that may have already been queued for the
   application to receive), since the receipt of the FIN means the application will
   not receive any additional data on the connection.
3. Sometime later, the application that received the end-of-file will close its
   socket. This causes its TCP to send a FIN.
4. The TCP on the system that receives this final FIN (the end that did the active
   close) acknowledges the FIN.

Since a FIN and an ACK are required in each direction, four segments are normally required. 
We use the qualifier ‘‘normally’’ because in some scenarios, the FIN in Step 1 is sent with data. 
Also, the segments in Steps 2 and 3 are both from the end performing the passive close and could be combined into one segment.

Between Steps 2 and 3 it is possible for data to flow from the end doing the passive close to the end doing the active close. This is called a *half-close*.

The sending of each FIN occurs when a socket is closed. 
We indicated that the application calls close for this to happen, but realize that when a Unix process terminates, 
either voluntarily (calling exit or having the main function return) or involuntarily (receiving a signal that terminates the process), 
all open descriptors are closed, which will also cause a FIN to be sent on any TCP connection that is still open.

> [!NOTE]
> 
> Either the client or the server—can perform the active close. Often the client performs the active close, but with some protocols (notably HTTP/1.0), the server performs the active close.



- fin retry
- fin_wait2 wait time
- time_wait limit


#### Half Close

shutdown

- SHUT_RD
- SHUT_WR
- SHUT_RDWR


###  Connection State

A connection progresses through a series of states during its lifetime.  
The states are:  LISTEN, SYN-SENT, SYN-RECEIVED, ESTABLISHED, FIN-WAIT-1, FIN-WAIT-2, CLOSE-WAIT, CLOSING, LAST-ACK, TIME-WAIT, and the fictional state CLOSED.  
CLOSED is fictional because it represents the state when there is no TCB, and therefore, no connection.  
Briefly the meanings of the states are:

- LISTEN - represents waiting for a connection request from any remote TCP and port.
- SYN-SENT - represents waiting for a matching connection request after having sent a connection request.
- SYN-RECEIVED - represents waiting for a confirming connection request acknowledgment after having both received and sent a connection request.
- ESTABLISHED - represents an open connection, data received can be delivered to the user.  The normal state for the data transfer phase of the connection.
- FIN-WAIT-1 - represents waiting for a connection termination request from the remote TCP, or an acknowledgment of the connection termination request previously sent.
- FIN-WAIT-2 - represents waiting for a connection termination request from the remote TCP.
- CLOSE-WAIT - represents waiting for a connection termination request from the local user.
- CLOSING - represents waiting for a connection termination request acknowledgment from the remote TCP.
- LAST-ACK - represents waiting for an acknowledgment of the connection termination request previously sent to the remote TCP(which includes an acknowledgment of its connection termination request).
- TIME-WAIT - represents waiting for enough time to pass to be sure the remote TCP received the acknowledgment of its connection termination request.
- CLOSED - represents no connection state at all.

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

TCP State Transition Diagram


Connect：
client： closed - snd SYN -> SYN-SENT - rcv SYN+ACK and snd ACK -> ESTAB

sever： closed - listen -> Listen - rcv SYN - snd SYN+ACK -> SYN_RCV and rcv ACK -> ESTAB

disconnect：
ESTAB - snd FIN -> FIN-WAIT-1

- rcv ACK -> FIN-WAIT-2 - rcv FIN and snd ACK -> TIME_WAIT
- rcv FIN and snd ACK -> CLOSING -> rcv ACK -> TIME_WAIT
- 2MSL -> CLOSED

ESTAB - rcv FIN -> CLOSE WAIT - close and snd FIN -> LAST-ACK -> rcv ACK-> CLOSED

#### TIME_WAIT State

The way in which a packet gets ‘‘lost’’ in a network is usually the result of routing anomalies.
This original packet is called a lost duplicate or a wandering duplicate. TCP must handle these duplicates.

There are two reasons for the TIME_WAIT state:
1. To implement TCP’s full-duplex connection termination reliably
2. To allow old duplicate segments to expire in the network

The first reason can be explained by assuming that the final ACK is lost. The server will resend its final FIN, so the client must maintain state information, allowing it to resend the final ACK.
If it did not maintain this information, it would respond with an RST (a different type of TCP segment), which would be interpreted by the server as an error.

The connection is closed and then sometime later, we establish another connection between the same IP addresses and ports.
This latter connection is called an incarnation of the previous connection since the IP addresses and ports are the same. 
TCP must prevent old duplicates from a connection from reappearing at some later time and being misinterpreted as belonging to a new incarnation of the same connection.
To do this, TCP will not initiate a new incarnation of a connection that is currently in the TIME_WAIT state.

> There is an exception to this rule. 
> Berkeley-derived implementations will initiate a new incarnation of a connection that is currently in the TIME_WAIT state if the arriving SYN has a sequence number that is ‘‘greater than’’ the ending sequence number from the previous incarnation.

### Window Scale

see [RFC 1323 - TCP Extensions for High Performance](https://datatracker.ietf.org/doc/rfc1323/).



**Window Size Limit:** 

The TCP header uses a 16 bit field to report the receive window size to the sender.  Therefore, the largest window that can be used is 2**16 = 65K bytes.

```
TCP Window Scale Option (WSopt):

         Kind: 3 Length: 3 bytes

                +---------+---------+---------+
                | Kind=3  |Length=3 |shift.cnt|
                +---------+---------+---------+
```

The window field (SEG.WND) in the header of every incoming segment, with the exception of SYN segments, is left-shifted by Snd.Wind.Scale bits before updating SND.WND:
              `SND.WND = SEG.WND << Snd.Wind.Scale`

The window field (SEG.WND) of every outgoing segment, with the exception of SYN segments, is right-shifted by Rcv.Wind.Scale bits:
              `SEG.WND = RCV.WND >> Rcv.Wind.Scale`



**Recovery from Losses:**



**Round-Trip Measurement:**

TCP implements reliable data delivery by retransmitting segments that are not acknowledged within some retransmission timeout (RTO) interval.

New TCP option, `"Timestamps"`, and then defines a mechanism using this option that allows nearly every segment, including retransmissions, to be timed at negligible computational cost.  We use the mnemonic RTTM(`Round Trip Time Measurement)` for this mechanism, to distinguish it from other uses of the `Timestamps` option.

#### RTTM



#### PAWS

We call PAWS(`Protect Against Wrapped Sequence numbers`), to extend TCP reliability to transfer rates well beyond the foreseeable upper limit of network bandwidths.



The PAWS algorithm requires the following processing to be performed on all incoming segments for a synchronized connection:


- If there is a Timestamps option in the arriving segment and SEG.TSval < TS.Recent and if TS.Recent is valid (see later discussion), then treat the arriving segment as not acceptable:

  - Send an acknowledgement in reply as specified in RFC-793 page 69 and drop the segment.

  - Note: it is necessary to send an ACK segment in order to retain TCP's mechanisms for detecting and recovering from half-open connections.  For example, see Figure 10 of RFC-793.

- If the segment is outside the window, reject it (normal TCP processing)

- If an arriving segment satisfies: SEG.SEQ <= Last.ACK.sent (see Section 3.4), then record its timestamp in TS.Recent.

- If an arriving segment is in-sequence (i.e., at the left window edge), then accept it normally.
  
- Otherwise, treat the segment as a normal in-window, out-of-sequence TCP segment (e.g., queue it for later delivery to the user).



### Fast Open




The key component of TFO is the Fast Open Cookie (cookie), a message authentication code (MAC) tag generated by the server.  The client requests a cookie in one regular TCP connection, then uses it for future TCP connections to exchange data during the 3WHS:

   Requesting a Fast Open Cookie:

   1. The client sends a SYN with a Fast Open option with an empty
      cookie field to request a cookie.
   2. The server generates a cookie and sends it through the Fast Open
      option of a SYN-ACK packet.
   3. The client caches the cookie for future TCP Fast Open connections
      (see below).



Requesting Fast Open Cookie in connection 1:

```
   TCP A (Client)                                      TCP B (Server)
   ______________                                      ______________
   CLOSED                                                      LISTEN

   #1 SYN-SENT       ----- <SYN,CookieOpt=NIL>  ---------->  SYN-RCVD

   #2 ESTABLISHED    <---- <SYN,ACK,CookieOpt=C> ----------  SYN-RCVD
```

Performing TCP Fast Open in connection 2:

```
   TCP A (Client)                                      TCP B (Server)
   ______________                                      ______________
   CLOSED                                                      LISTEN

   #1 SYN-SENT       ----- <SYN=x,CookieOpt=C,DATA_A> ---->  SYN-RCVD

   #2 ESTABLISHED    <---- <SYN=y,ACK=x+len(DATA_A)+1> ----  SYN-RCVD

   #3 ESTABLISHED    <---- <ACK=x+len(DATA_A)+1,DATA_B>----  SYN-RCVD

   #4 ESTABLISHED    ----- <ACK=y+1>--------------------> ESTABLISHED

   #5 ESTABLISHED    --- <ACK=y+len(DATA_B)+1>----------> ESTABLISHED
```





```
                                   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
                                   |      Kind     |    Length     |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                                                               |
   ~                            Cookie                             ~
   |                                                               |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

   Kind            1 byte: value = 34
   Length          1 byte: range 6 to 18 (bytes); limited by
                           remaining space in the options field.
                           The number MUST be even.
   Cookie          0, or 4 to 16 bytes (Length - 2)
```


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
# This is how many retries are done when active opening a connection.
# RFC1122 says the minimum retry MUST be at least 180secs.  
# Nevertheless this value is corresponding to 63secs of retransmission with the current initial RTO.
cat /proc/sys/net/ipv4/tcp_syn_retries #5
```

##### syn+ack fail

**scenario**: client can not receive syn+ack from server

1. client retry syn until `tcp_syn_retries`, every trying will reset count of server syn+ack
2. server also will retry send syn+ack until `tcp_synack_retries`


Number of times SYNACKs for a passive TCP connection attempt will be retransmitted. 
Should not be higher than 255. Default value is 5, which corresponds to 31seconds till the last retransmission with the current initial RTO of 1second. 
With this the final timeout for a passive TCP connection will happen after 63seconds.

```shell
cat /proc/sys/net/ipv4/tcp_synack_retries #5
```

##### ack fail

**scenario**: client into ESTABLISH after send ack, server can not receive ack

server continue send syn+ack, syn+ack失败达到tcp_synack_retries后，处于SYN_RECV状态的接收方主动关闭了连接


### Options

#### SO_REUSEADDR


#### TCP_NODELAY

If set, disable the Nagle algorithm. This means that segments are always sent as soon as possible, even if there is only a small amount of data. 
When not set, data is buffered until there is a sufficient amount to send out, thereby avoiding the frequent sending of small packets, which results in poor utilization of the network.
This option is overridden by TCP_CORK; however, setting this option forces an explicit flush of pending output, even if TCP_CORK is currently set.
As currently implemented, there is a 200 millisecond ceiling on the time for which output is corked by *TCP_CORK*.


[Nagle's algorithm](https://en.wikipedia.org/wiki/Nagle's_algorithm) is a means of improving the efficiency of TCP/IP networks by reducing the number of packets that need to be sent over the network.

What Nagle's algorithm does is says: 
- if there is unacked data sent, and if the write buffer in the kernel is smaller than the MTU, then wait a little to see if the application writes more data. 
- If the write buffer reaches the MTU size then the data will be transmitted. If the in flight data is acked then the data will also be transmitted, even if it is smaller than the MTU.

Where MSS is the maximum segment size, the largest segment that can be sent on this connection, and the window size is the currently acceptable window of unacknowledged data, this can be written in pseudocode as

```
if there is new data to send then
    if the window size ≥ MSS and available data is ≥ MSS then
        send complete MSS segment now
    else
        if there is unconfirmed data still in the pipe then
            enqueue data in the buffer until an acknowledge is received
        else
            send data immediately
        end if
    end if
end if
```

> [!NOTE]
> 
> The user-level solution is to avoid write–write–read sequences on sockets. Write–read–write–read is fine. Write–write–write is fine. But write–write–read is a killer. 
> So, if you can, buffer up your little writes to TCP and send them all at once. Using the standard UNIX I/O package and flushing write before each read usually works.

The TCP delayed ack feature is again an attempt to minimize the number of small packets sent. 
The way it works is a TCP packet can ack multiple data packets at once. 
Therefore a TCP stack implementing the delayed ack feature may wait up to some amount of time before acking packets in the hope that it will be able to ack more packets at once. 
On Linux this can cause up to a 40 ms delay when acking packets. 
Again, this is usually a good thing since it decreases the number of packets that have to be sent (which is usually the limiting factor in network performance).


An application that is very latency sensitive, particularly if it doesn't transmit a lot of data, can safely use TCP_NODELAY.


#### keepalive

When the keep-alive option is set for a TCP socket and no data has been exchanged across the socket in either direction for two hours, TCP automatically sends a keep-alive probe to the peer. 
This probe is a TCP segment to which the peer must respond. One of three scenarios results:
1. The peer responds with the expected ACK. The application is not notified (since everything is okay). TCP will send another probe following another two hours of inactivity.
2. The peer responds with an RST, which tells the local TCP that the peer host has crashed and rebooted. The socket’s pending error is set to ECONNRESET and the socket is closed.
3. There is no response from the peer to the keep-alive probe. Berkeley-derived TCPs send 8 additional probes, 75 seconds apart, trying to elicit a response.
   TCP will give up if there is no response within 11 minutes and 15 seconds after sending the first probe.


```shell
cat /proc/sys/net/ipv4/tcp_keepalive_time	#7200
cat /proc/sys/net/ipv4/tcp_keepalive_intvl	#75
cat /proc/sys/net/ipv4/tcp_keepalive_probes	#9
```


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
# This is how many retries it does before it tries to figure out if the gateway is down. 
# Minimal RFC value is 3; it corresponds to ~3sec-8min depending on RTO.
cat /proc/sys/net/ipv4/tcp_retries1	#3

# This should take at least 90 minutes to time out.
# RFC1122 says that the limit is 100 sec. 15 is ~13-30min depending on RTO.
cat /proc/sys/net/ipv4/tcp_retries2	#15


```

### retry
retries are using to calculate timeout(about RTO)
if RTO very large, the actual reties will < setting retries

```c
#define TCP_RTO_MAX	((unsigned)(120*HZ))
#define TCP_RTO_MIN	((unsigned)(HZ/5))
```


From [ip-sysctl.txt](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
> tcp_retries1 - INTEGER
> 
> This value influences the time, after which TCP decides, that
something is wrong due to unacknowledged RTO retransmissions,
and reports this suspicion to the network layer.
See tcp_retries2 for more details.
>
> RFC 1122 recommends at least 3 retransmissions, which is the
	default.
>
> tcp_retries2 - INTEGER
> 
> This value influences the timeout of an alive TCP connection,
when RTO retransmissions remain unacknowledged.
Given a value of N, a hypothetical TCP connection following
exponential backoff with an initial RTO of TCP_RTO_MIN would
retransmit N times before killing the connection at the (N+1)th RTO.
>
> The default value of 15 yields a hypothetical timeout of **924.6
	seconds** and is a lower bound for the effective timeout.
	TCP will effectively time out at the first RTO which exceeds the
	hypothetical timeout.
> 
>RFC 1122 recommends at least 100 seconds for the timeout,
	which corresponds to a value of at least 8.


```c
void tcp_retransmit_timer(struct sock *sk)
{
    ...
    
	if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1 + 1, 0))
		__sk_dst_reset(sk);
}

/* A write timeout has occurred. Process the after effects. */
static int tcp_write_timeout(struct sock *sk)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	bool expired = false, do_reset;
	int retry_until;

	if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV)) {
		if (icsk->icsk_retransmits)
			__dst_negative_advice(sk);
		retry_until = icsk->icsk_syn_retries ? : net->ipv4.sysctl_tcp_syn_retries;
		expired = icsk->icsk_retransmits >= retry_until;
	} else {
		if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1, 0)) {
			/* Black hole detection */
			tcp_mtu_probing(icsk, sk);

			__dst_negative_advice(sk);
		}
		}
```
#### tcp_write_timeout

- if in TCPF_SYN_SENT | TCPF_SYN_RECV,  see `tcp_syn_retries`
- else , `tcp_retries1` tcp_mtu_probing, __dst_negative_advice
- `tcp_retries2`
- if SOCK_DEAD, see`tcp_orphan_retries`
```c

/* A write timeout has occurred. Process the after effects. */
static int tcp_write_timeout(struct sock *sk)
{
	struct inet_connection_sock *icsk = inet_csk(sk);
	struct tcp_sock *tp = tcp_sk(sk);
	struct net *net = sock_net(sk);
	bool expired = false, do_reset;
	int retry_until;

	if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV)) {
		if (icsk->icsk_retransmits)
			__dst_negative_advice(sk);
		retry_until = icsk->icsk_syn_retries ? : net->ipv4.sysctl_tcp_syn_retries;
		expired = icsk->icsk_retransmits >= retry_until;
	} else {
		if (retransmits_timed_out(sk, net->ipv4.sysctl_tcp_retries1, 0)) {
			/* Black hole detection */
			tcp_mtu_probing(icsk, sk);

			__dst_negative_advice(sk);
		}

		retry_until = net->ipv4.sysctl_tcp_retries2;
		if (sock_flag(sk, SOCK_DEAD)) {
			const bool alive = icsk->icsk_rto < TCP_RTO_MAX;

			retry_until = tcp_orphan_retries(sk, alive);
			do_reset = alive ||
				!retransmits_timed_out(sk, retry_until, 0);

			if (tcp_out_of_resources(sk, do_reset))
				return 1;
		}
	}
	if (!expired)
		expired = retransmits_timed_out(sk, retry_until,
						icsk->icsk_user_timeout);
	tcp_fastopen_active_detect_blackhole(sk, expired);

	if (BPF_SOCK_OPS_TEST_FLAG(tp, BPF_SOCK_OPS_RTO_CB_FLAG))
		tcp_call_bpf_3arg(sk, BPF_SOCK_OPS_RTO_CB,
				  icsk->icsk_retransmits,
				  icsk->icsk_rto, (int)expired);

	if (expired) {
		/* Has it gone just too far? */
		tcp_write_err(sk);
		return 1;
	}

	if (sk_rethink_txhash(sk)) {
		tp->timeout_rehash++;
		__NET_INC_STATS(sock_net(sk), LINUX_MIB_TCPTIMEOUTREHASH);
	}

	return 0;
}
```
##### retransmits_timed_out
retransmits_timed_out() - returns true if this connection has timed out
- sk:       The current socket
- boundary: max number of retransmissions
- timeout:  A custom timeout value. If set to 0 the default timeout is calculated and used. Using TCP_RTO_MIN and the number of unsuccessful retransmits.

The default "timeout" value this function can calculate and use
is equivalent to the timeout of a TCP Connection
after "boundary" unsuccessful, exponentially backed-off
retransmissions with an initial RTO of TCP_RTO_MIN.

```c
//
static bool retransmits_timed_out(struct sock *sk,
				  unsigned int boundary,
				  unsigned int timeout)
{
	unsigned int start_ts;

	if (!inet_csk(sk)->icsk_retransmits)
		return false;

	start_ts = tcp_sk(sk)->retrans_stamp;
	if (likely(timeout == 0)) {
		unsigned int rto_base = TCP_RTO_MIN;

		if ((1 << sk->sk_state) & (TCPF_SYN_SENT | TCPF_SYN_RECV))
			rto_base = tcp_timeout_init(sk);
		timeout = tcp_model_timeout(sk, boundary, rto_base);
	}

	return (s32)(tcp_time_stamp(tcp_sk(sk)) - start_ts - timeout) >= 0;
}


static unsigned int tcp_model_timeout(struct sock *sk,
				      unsigned int boundary,
				      unsigned int rto_base)
{
	unsigned int linear_backoff_thresh, timeout;

	linear_backoff_thresh = ilog2(TCP_RTO_MAX / rto_base);
	if (boundary <= linear_backoff_thresh)
		timeout = ((2 << boundary) - 1) * rto_base;
	else
		timeout = ((2 << linear_backoff_thresh) - 1) * rto_base +
			(boundary - linear_backoff_thresh) * TCP_RTO_MAX;
	return jiffies_to_msecs(timeout);
}
```


RFC 1122建议对应的超时时间不低于100s 

default send  retries

`tcp_retries1` 失败后通知IP层进行MTU探测、刷新路由等流程而不是关闭连接

同样受timeout限制



### Sack

`sack (Selective Acknowledgment)`



```
       TCP Sack-Permitted Option:
       Kind: 4
       +---------+---------+
       | Kind=4  | Length=2|
       +---------+---------+
```



Sack Option Format

```
       TCP SACK Option:
       Kind: 5
       Length: Variable

                         +--------+--------+
                         | Kind=5 | Length |
       +--------+--------+--------+--------+
       |      Left Edge of 1st Block       |
       +--------+--------+--------+--------+
       |      Right Edge of 1st Block      |
       +--------+--------+--------+--------+
       |                                   |
       /            . . .                  /
       |                                   |
       +--------+--------+--------+--------+
       |      Left Edge of nth Block       |
       +--------+--------+--------+--------+
       |      Right Edge of nth Block      |
       +--------+--------+--------+--------+
```



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

[Netty TPO](/docs/CS/Java/Netty/TPO.md)


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



### connection queue

1. syn queue/半连接队列
2. accpet queue/全连接队列



#### syn queue

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

#### accept queue

```shell
# -l show the listening socket
# -n no expain server name
# -t only tcp
ss -lnt
```

|        | in Listening              | non-listening             |
| ------ | ------------------------- | ------------------------- |
| Recv-Q | current accept queue size | recv & not read byte size |
| Send-Q | max accept queue size     | send & not ack byte size  |






use[`wrk`](https://github.com/wg/wrk) to test accept queue overflow

```shell
# -t thread number
# -c connection count
# -d continue time
wrk -t 6 -c 30000 -d 60s http://xxx.xxx.xxx.xxx 
```



建议使用0以防止应用只是短暂的连接过多，利用客户端重试机制尽量可以得到响应而不是直接重置连接

if see `connection reset by peer`, might be accept queue overflow, default will be connection timeout


> If listening service is too slow to accept new connections, reset them. 
> Default state is FALSE. It means that if overflow occurred due to a burst, connection will recover. E
> nable this option _only_ if you are really sure that listening daemon cannot be tuned to accept connections faster. 
> Enabling this option can harm clients of your server.

```shell
# 0 dicard, 1 dicard and return RST
cat /proc/sys/net/ipv4/tcp_abort_on_overflow
```



```shell
netstat -s|grep overflowed
```


### Close Connection

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



### TIME_WAIT

make sure packets are received(even if ACK lost)

how long to wait to destroy TIME state, about 60 seconds

```c
#define TCP_TIMEWAIT_LEN (60*HZ)
```

tcp_tw_reuse - INTEGER

Enable reuse of TIME-WAIT sockets for new connections when it is
safe from protocol viewpoint.

	- 0 - disable
	- 1 - global enable
	- 2 - enable for loopback traffic only

	It should not be changed without advice/request of technical
	experts.

	Default: 2

#### TWA

The TCP mechanisms to protect against old duplicate segments, below if in TIME_WAIT:

**Unreliable:** TIME-WAIT state removes the hazard of old duplicates for "fast" or "long" connections, in which clock-driven ISN selection is unable to prevent overlap of the old and new sequence spaces. The TIME-WAIT delay allows all old duplicate segments time enough to die in the Internet before the connection is reopened.

TIME-WAIT state can be prematurely terminated ("assassinated") by an old duplicate data or ACK segment from the current or an earlier incarnation of the same connection.  We refer to this as "`TIME-WAIT Assassination`" (**TWA**).

```
       TCP A                                                TCP B

   1.  ESTABLISHED                                          ESTABLISHED

       (Close)
   2.  FIN-WAIT-1  --> <SEQ=100><ACK=300><CTL=FIN,ACK>  --> CLOSE-WAIT

   3.  FIN-WAIT-2  <-- <SEQ=300><ACK=101><CTL=ACK>      <-- CLOSE-WAIT

                                                            (Close)
   4.  TIME-WAIT   <-- <SEQ=300><ACK=101><CTL=FIN,ACK>  <-- LAST-ACK

   5.  TIME-WAIT   --> <SEQ=101><ACK=301><CTL=ACK>      --> CLOSED

  - - - - - - - - - - - - - - - - - - - - - - - - - - - -

   5.1. TIME-WAIT   <--  <SEQ=255><ACK=33> ... old duplicate

   5.2  TIME-WAIT   --> <SEQ=101><ACK=301><CTL=ACK>    -->  ????

   5.3  CLOSED      <-- <SEQ=301><CTL=RST>             <--  ????
      (prematurely)

                         TWA Example
```


 If the connection is immediately reopened after a TWA event, the new incarnation will be exposed to old duplicate segments (except for the initial <SYN> segment, which is handled by the 3-way handshake).  There are three possible hazards that result:

-   Old duplicate data may be accepted erroneously.
- The new connection may be de-synchronized, with the two ends in permanent disagreement on the state.  Following the spec of RFC-793, this desynchronization results in an infinite ACK loop.  (It might be reasonable to change this aspect of RFC- 793 and kill the connection instead.) This hazard results from acknowledging something that was not sent.  This may result from an old duplicate ACK or as a side-effect of hazard H1.
- The new connection may die. A duplicate segment (data or ACK) arriving in SYN-SENT state may kill the new connection after it has apparently opened successfully.

##### Fixes for TWA Hazards


We discuss three possible fixes to TCP to avoid these hazards.
- Ignore RST segments in TIME-WAIT state. If the 2 minute MSL is enforced, this fix avoids all three hazards.
 This is the simplest fix.  One could also argue that it is formally the correct thing to do; since allowing time for old duplicate segments to die is one of TIME-WAIT state's functions, the state should not be truncated by a RST segment. [see Linux](/d)
- Use PAWS to avoid the hazards.
- Use 64-bit Sequence Numbers




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

see [RFC 6191 - Reducing the TIME-WAIT State Using TCP Timestamps](https://datatracker.ietf.org/doc/html/rfc6191)

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



## Congestion Control

Active Queue Management



### ECN

Explicit Congestion Notification in IP



## Links
- [Computer Network](/docs/CS/CN/CN.md)

## References

1. [RFC 793 - Transmission Control Protocol](https://datatracker.ietf.org/doc/rfc793/)
2. [RFC 1122 - Requirements for Internet Hosts - Communication Layers](https://datatracker.ietf.org/doc/rfc1122/)
3. [RFC 1323 - TCP Extensions for High Performance](https://datatracker.ietf.org/doc/rfc1323/)
3. [RFC 1337 - TIME-WAIT Assassination Hazards in TCP](https://datatracker.ietf.org/doc/rfc1337/)
4. [RFC 2018 - TCP Selective Acknowledgment Options](https://datatracker.ietf.org/doc/rfc2018/)
6. [RFC 2525 - Known TCP Implementation Problems](https://datatracker.ietf.org/doc/rfc2525/)
7. [RFC 3168 - The Addition of Explicit Congestion Notification (ECN) to IP](https://datatracker.ietf.org/doc/rfc3168/)
8. [RFC 6191 - Reducing the TIME-WAIT State Using TCP Timestamps](https://datatracker.ietf.org/doc/html/rfc6191)
9. [RFC 6937 - Proportional Rate Reduction for TCP](https://datatracker.ietf.org/doc/html/rfc6937)
10. [RFC 7413 - TCP Fast Open](https://datatracker.ietf.org/doc/html/rfc7413)
