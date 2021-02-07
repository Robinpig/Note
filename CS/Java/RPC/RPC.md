##RPC
Remote Procedure Call

与REST比较：

都是网络交互的协议规范。通常用于多个微服务之间的通信协议。

| 比较项 | REST | RPC |
| :---: | :---: | :---: |
| 通信协议 | HTTP | 一般使用TCP |
| 性能 | 低 | 高 |
| 灵活度 | 高 | 低 |

多系统之间的内部调用采用RPC；对外提供的服务，Rest更加合适

RPC框架要做到的最基本的三件事：

- 服务端如何确定客户端要调用的函数；

    - 在远程调用中，客户端和服务端分别维护一个【ID->函数】的对应表， ID在所有进程中都是唯一确定的。客户端在做远程过程调用时，附上这个ID，服务端通过查表，来确定客户端需要调用的函数，然后执行相应函数的代码。

- 如何进行序列化和反序列化；

    - 客户端和服务端交互时将参数或结果转化为字节流在网络中传输，那么数据转化为字节流的或者将字节流转换成能读取的固定格式时就需要进行序列化和反序列化，序列化和反序列化的速度也会影响远程调用的效率。

- 如何进行网络传输（选择何种网络协议）；

    - 多数RPC框架选择TCP作为传输协议，也有部分选择HTTP。如gRPC使用HTTP2。不同的协议各有利弊。TCP更加高效，而HTTP在实际应用中更加的灵活。