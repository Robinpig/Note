## Introduction

A [computer network](https://en.wikipedia.org/wiki/Computer_network) is a set of computers sharing resources located on or provided by network nodes.
The computers use common communication protocols over digital interconnections to communicate with each other.
These interconnections are made up of telecommunication network technologies, based on physically wired, optical,
and wireless radio-frequency methods that may be arranged in a variety of network topologies.

### OSI Model

A common way to describe the layers in a network is to use the International Organization for Standardization (ISO) open systems interconnection (OSI) model for computer communications.

> [!TIP]
>
> See [科来-网络通信协议图-2020](http://www.colasoft.com.cn/download/network-protocol-map-2020.pdf)

It is possible for an application to bypass the transport layer and use IPv4 or IPv6 directly. This is called a *raw socket*.

The upper three layers of the OSI model are combined into a single layer called the application.
This is the Web client (browser), Telnet client, Web server, FTP server, or whatever application we are using.
With the Internet protocols, there is rarely any distinction between the upper three layers of the OSI model.

The sockets programming interfaces described in this book are interfaces from the upper three layers (the ‘‘application’’) into the transport layer.
Why do sockets provide the interface from the upper three layers of the OSI model into the transport layer?

- First, the upper three layers handle all the details of the application (FTP, Telnet, or HTTP, for example) and know little about the communication details.
  The lower four layers know little about the application, but handle all the communication details: sending data, waiting for acknowledgments, sequencing data that arrives out of order, calculating and verifying checksums, and so on.
- The second reason is that the upper three layers often form what is called a user process while the lower four layers are normally provided as part of the operating system (OS) kernel.
  Unix provides this separation between the user process and the kernel, as do many other contemporary operating systems.

Therefore, the interface between layers 4 and 5 is the natural place to build the API.

- [WebSocket](/docs/CS/CN/WebSocket.md)


## Computer Networks and the Internet

## Application Layer

[HTTP](/docs/CS/CN/HTTP.md)、FTP、SMTP、DNS

## Transport Layer

A transport-layer protocol provides for logical communication between application processes running on different hosts.
By logical communication, we mean that from an application’s perspective, it is as if the hosts running the processes were directly connected; in reality, the hosts may be on opposite sides of the planet, connected via numerous routers and a wide range of link types.
Application processes use the logical communication provided by the transport layer to send messages to each other, free from the worry of the details of the physical infrastructure used to carry these messages.


|              | TCP                                                                             | UDP            |
| -------------- | --------------------------------------------------------------------------------- | ---------------- |
| Connection   | connections                                                                     | connectionless |
| Reliability  | acknowledgments, sequence numbers, RTT estimation, timeouts, or retransmissions | no             |
| Flow Control | yes                                                                             | no             |
| Full-duplex  | yes                                                                             | can be         |

At any given time, multiple processes can be using any given transport: UDP, SCTP, or TCP. All three transport layers use 16-bit integer port numbers to differentiate between these processes.


The socket pair for a TCP connection is the four-tuple that defines the two endpoints of the connection: the local IP address, local port, foreign IP address, and foreign port. 
A socket pair uniquely identifies every TCP connection on a network.
For SCTP, an association is identified by a set of local IP addresses, a local port, a set of foreign IP addresses, and a foreign port. 
In its simplest form, where neither endpoint is multihomed, this results in the same four-tuple socket pair used with TCP. 
However, when either of the endpoints of an association are multihomed, then multiple four-tuple sets(with different IP addresses but the same port numbers) may identify the same association.

The two values that identify each endpoint, an IP address and a port number, are often called a *socket*.

We can extend the concept of a socket pair to UDP, even though UDP is connectionless. 
When we describe the socket functions (bind, connect, getpeername, etc.), we will note which functions specify which values in the socket pair. 
For example, bind lets the application specify the local IP address and local port for TCP, UDP, and SCTP sockets.


[I/O Multiplexing](/docs/CS/CN/MultiIO.md)

## Protocol

[Internet Protocol(IP)](/docs/CS/CN/IP.md)

[Dynamic Host Configuration Protocol](/docs/CS/CN/DHCP.md)

[Internet Control Message Protocol](/docs/CS/CN/ICMP.md)

[ARP: Address Resolution Protocol](/docs/CS/CN/ARP.md)

[Transmission Control Protocol](/docs/CS/CN/TCP.md)

encapsulate

[User Datagram Protocol](/docs/CS/CN/UDP.md)

File Transfer Protocol

Domain Name System

Simple Mail Transfer Protocol

Serial Line Internet Protocol

Point to Point Protocol

## Tools

[WireShark](/docs/CS/CN/Tools/WireShark.md)

## Links

- [CS](/docs/CS/CS.md)
- [Operating Systems](/docs/CS/OS/OS.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Organization](/docs/CS/CO/CO.md)
- [Internet Assigned Numbers Authority](https://www.iana.org/)
