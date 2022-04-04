## Introduction

A [computer network](https://en.wikipedia.org/wiki/Computer_network) is a set of computers sharing resources located on or provided by network nodes.
The computers use common communication protocols over digital interconnections to communicate with each other.
These interconnections are made up of telecommunication network technologies, based on physically wired, optical,
and wireless radio-frequency methods that may be arranged in a variety of network topologies.


## Computer Networks and the Internet

### Network Protocols

> A protocol defines the format and the order of messages exchanged between two or more communicating entities, as well as the actions taken on the transmission and/or receipt of a message or other event

### The Network Edge

Furthermore, an increasing number of non-traditional “things” are being attached to the Internet as end systems.


### The Network Core


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



### Networks Under Attack

#### Put Malware into Your Host Via the Internet

#### Attack Servers and Network Infrastructure

Another broad class of security threats are known as denial-of-service (DoS) attacks.
- Vulnerability attack.
- Bandwidth flooding.
- Connection flooding.

#### Sniff Packets

The basic tool for observing the messages exchanged between executing protocol entities is called a *packet sniffer*.
Sniffed packets can then be analyzed offline for sensitive information.

Indeed, the [Wireshark](/docs/CS/CN/Tools/WireShark.md) is a packet sniffer.

#### Masquerade as Someone You Trust

The ability to inject packets into the Internet with a false source address is known as IP spoofing, and is but one of many ways in which one user can masquerade as another user.

## Application Layer

Network applications are the raisons exist of a computer network.



[HTTP](/docs/CS/CN/HTTP.md)、FTP、SMTP、DNS

[WebSocket](/docs/CS/CN/WebSocket.md)

## Transport Layer

A transport-layer protocol provides for logical communication between application processes running on different hosts.
By logical communication, we mean that from an application’s perspective, it is as if the hosts running the processes were directly connected; 
in reality, the hosts may be on opposite sides of the planet, connected via numerous routers and a wide range of link types.
Application processes use the logical communication provided by the transport layer to send messages to each other, free from the worry of the details of the physical infrastructure used to carry these messages.

Transport-layer protocols are implemented in the end systems but not in network routers. 
On the sending side, the transport layer converts the application-layer messages it receives from a sending application process into transport-layer packets, known as transport-layer segments in Internet terminology. 
This is done by (possibly) breaking the application messages into smaller chunks and adding a transport-layer header to each chunk to create the transport-layer segment. 
The transport layer then passes the segment to the network layer at the sending end system, where the segment is encapsulated within a network-layer packet (a datagram) and sent to the destination. 
It’s important to note that network routers act only on the network-layer fields of the datagram; that is, they do not examine the fields of the transport-layer segment encapsulated with the datagram. 
On the receiving side, the network layer extracts the transport-layer segment from the datagram and passes the segment up to the transport layer. 
The transport layer then processes the received segment, making the data in the segment available to the receiving application.

The services that a transport protocol can provide are often constrained by the service model of the underlying network-layer protocol. 
If the network-layer protocol cannot provide delay or bandwidth guarantees for transport-layer segments sent between hosts, 
then the transport-layer protocol cannot provide delay or bandwidth guarantees for application messages sent between processes.

Nevertheless, certain services can be offered by a transport protocol even when the underlying network protocol doesn’t offer the corresponding service at the network layer. 
For example, a transport protocol can offer reliable data transfer service to an application even when the underlying network protocol is unreliable, that is, even when the network protocol loses, garbles, or duplicates packets. 
As another example, a transport protocol can use encryption to guarantee that application messages are not read by intruders, 
even when the network layer cannot guarantee the confidentiality of transport-layer segments.





|              | TCP                                                                             | UDP            |
| -------------- | --------------------------------------------------------------------------------- | ---------------- |
| Connection   | connections                                                                     | connectionless |
| Reliability  | acknowledgments, sequence numbers, RTT estimation, timeouts, or retransmissions | no             |
| Flow Control | yes                                                                             | no             |
| Full-duplex  | yes                                                                             | can be         |

At any given time, multiple processes can be using any given transport: UDP, SCTP, or TCP. 
All three transport layers use 16-bit integer port numbers to differentiate between these processes.

### Multiplexing and Demultiplexing

Now let’s consider how a receiving host directs an incoming transport-layer segment to the appropriate socket. 
Each transport-layer segment has a set of fields in the segment for this purpose. At the receiving end, the transport layer examines these fields to identify the receiving socket and then directs the segment to that socket. 
This job of delivering the data in a transport-layer segment to the correct socket is called demultiplexing. 
The job of gathering data chunks at the source host from different sockets, encapsulating each data chunk with header information (that will later be used in demultiplexing) to create segments, 
and passing the segments to the network layer is called multiplexing.

#### Connectionless

It is important to note that a [UDP](/docs/CS/CN/UDP.md) socket is fully identified by a two-tuple consisting of a destination IP address and a destination port number. 
As a consequence, if two UDP segments have different source IP addresses and/or source port numbers, but have the same destination IP address and destination port number, 
then the two segments will be directed to the same destination process via the same destination socket.

#### Connection-Oriented

The socket pair for a [TCP](/docs/CS/CN/TCP.md) connection is the four-tuple that defines the two endpoints of the connection: the local IP address, local port, foreign IP address, and foreign port.
A socket pair uniquely identifies every TCP connection on a network.
For SCTP, an association is identified by a set of local IP addresses, a local port, a set of foreign IP addresses, and a foreign port.
In its simplest form, where neither endpoint is multihomed, this results in the same four-tuple socket pair used with TCP.
However, when either of the endpoints of an association are multihomed, then multiple four-tuple sets(with different IP addresses but the same port numbers) may identify the same association.

The two values that identify each endpoint, an IP address and a port number, are often called a *socket*.

We can extend the concept of a socket pair to UDP, even though UDP is connectionless.
When we describe the socket functions (bind, connect, getpeername, etc.), we will note which functions specify which values in the socket pair.
For example, bind lets the application specify the local IP address and local port for TCP, UDP, and SCTP sockets.



## Network Layer

The primary role of the network layer is deceptively simple—to move packets from a sending host to a receiving host. To do so, two important network-layer functions can be identified:
- Forwarding
- Routing

Forwarding refers to the router-local action of transferring a packet from an input link interface to the appropriate output link interface. 
Forwarding takes place at very short timescales (typically a few nanoseconds), and thus is typically implemented in hardware. Routing refers to the network-wide process that determines the end-to-end paths that packets take from source to destination. 

Routing takes place on much longer timescales(typically seconds), and as we will see is often implemented in software.
The network layer must determine the route or path taken by packets as they flow from a sender to a receiver. The algorithms that calculate these paths are referred to as routing algorithms.

A key element in every network router is its *forwarding table*. 
A router forwards a packet by examining the value of one or more fields in the arriving packet’s header, and then using these header values to index into its forwarding table. 
The value stored in the forwarding table entry for those values indicates the outgoing link interface at that router to which that packet is to be forwarded.


[I/O Multiplexing](/docs/CS/CN/MultiIO.md)

## Protocol

[Internet Protocol(IP)](/docs/CS/CN/IP.md)

[Dynamic Host Configuration Protocol](/docs/CS/CN/DHCP.md)

[Internet Control Message Protocol](/docs/CS/CN/ICMP.md)

[ARP: Address Resolution Protocol](/docs/CS/CN/ARP.md)


encapsulate


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
