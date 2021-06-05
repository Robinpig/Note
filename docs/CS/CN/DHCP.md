# DHCP



客户端监听68端口 服务端监听67端口



使用UDP广播

1. 客户端发起DHCP DISCOVER，UDP广播 （225.225.225.255:67/0.0.0.0:68）
2. 服务端 DHCP OFFER 还是广播发送
3. 客户端 DHCP REQUEST
4. 服务端 DHCP ACK



DHCP中继代理