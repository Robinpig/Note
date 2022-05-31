## Introduction

A [computer network](https://en.wikipedia.org/wiki/Computer_network) is a set of computers sharing resources located on or provided by network nodes.
The computers use common communication protocols over digital interconnections to communicate with each other.
These interconnections are made up of telecommunication network technologies, based on physically wired, optical,
and wireless radio-frequency methods that may be arranged in a variety of network topologies.

## Computer Networks and the Internet

### Network Protocols

> A protocol defines the format and the order of messages exchanged between two or more communicating entities, as well as the actions taken on the transmission and/or receipt of a message or other event

Protocol Data Unit(PDU)

SDU

### The Network Edge

Furthermore, an increasing number of non-traditional “things” are being attached to the Internet as end systems.
End systems are also referred to as *hosts*.
Hosts are sometimes further divided into two categories: *clients* and *servers*.

### The Network Core

The network core — the mesh of packet switches and links that interconnects the Internet’s end systems.

Circuit Switching

- low delay
- ordering
- no conflict

Packet Switching

- connectionless
- high reliable
- forward delay

### Group Switching

A packet starts in a host (the source), passes through a series of routers, and ends its journey in another host (the destination).
As a packet travels from one node (host or router) to the subsequent node (host or router) along this path, the packet suffers from several types of delays at each node along the path.
The most important of these delays are the nodal processing delay, queuing delay, transmission delay, and propagation delay; together, these delays accumulate to give a total nodal delay.

- The time required to examine the packet’s header and determine where to direct the packet is part of the processing delay.
- At the queue, the packet experiences a queuing delay as it waits to be transmitted onto the link.
  The length of the queuing delay of a specific packet will depend on the number of earlier-arriving packets that are queued and waiting for transmission onto the link.
- The transmission delay is the amount of time required for the router to push out the packet;
  it is a function of the packet’s length and the transmission rate of the link, but has nothing to do with the distance between the two routers.
- The propagation delay, on the other hand, is the time it takes a bit to propagate from one router to the next;
  it is a function of the distance between the two routers, but has nothing to do with the packet’s length or the transmission rate of the link.

If we let $d_{proc}$ , $d_{queue}$ , $d_{trans}$ , and $d_{prop}$ denote the processing, queuing, transmission, and propagation delays, then the total nodal delay is given by

$$
d_{nodal}=d_{proc}+d_{queue}+d_{trans}+d_{prop}

$$

The most complicated and interesting component of nodal delay is the queuing delay, $d_{queue}$ .

> [!TIP]
>
> Design your system so that the traffic intensity is no greater than 1.

As the traffic intensity approaches 1, the average queuing delay increases rapidly.
A small percentage increase in the intensity will result in a much larger percentage-wise increase in delay.

The fraction of lost packets increases as the traffic intensity increases.
Therefore, performance at a node is often measured not only in terms of delay, but also in terms of the probability of packet loss.

- connectionless
- forward delay

### Performance

- Speed
- Bandwidth
- Throughput
- Delay
- RTT

### Network Model

#### OSI Model

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

## Application Layer

Network applications are the raisons exist of a computer network.

An application-layer protocol is distributed over multiple end systems, with the application in one end system using the protocol to exchange packets of information with the application in another end system.
We’ll refer to this packet of information at the application layer as a **message**.

[Dynamic Host Configuration Protocol](/docs/CS/CN/DHCP.md)

FTP、[SMTP](/docs/CS/CN/SMTP.md)

### HTTP

The [Hypertext Transfer Protocol (HTTP)](/docs/CS/CN/HTTP.md) is an application-level protocol with the lightness and speed necessary for distributed, collaborative, hypermedia information systems.

### DNS

[DNS](/docs/CS/CN/DNS.md) is a distributed client/server networked database that is used by TCP/IP applications to map between host names and IP addresses (and vice versa),
to provide electronic mail routing information, service naming, and other capabilities.

### Websocket

[WebSocket](/docs/CS/CN/WebSocket.md)

## Transport Layer

A transport-layer protocol provides for logical communication between application processes running on different hosts.
By logical communication, we mean that from an application’s perspective, it is as if the hosts running the processes were directly connected;
in reality, the hosts may be on opposite sides of the planet, connected via numerous routers and a wide range of link types.
Application processes use the logical communication provided by the transport layer to send messages to each other, free from the worry of the details of the physical infrastructure used to carry these messages.
We’ll refer to a transport-layer packet as a **segment**.

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


|                    | [TCP](/docs/CS/CN/TCP.md)                                                       | [UDP](/docs/CS/CN/UDP.md)    |
| -------------------- | --------------------------------------------------------------------------------- | ------------------------------ |
| Connection         | connections                                                                     | connectionless               |
| Reliability        | acknowledgments, sequence numbers, RTT estimation, timeouts, or retransmissions | no                           |
| Flow Control       | yes                                                                             | no                           |
| Congestion Control | yes                                                                             | no                           |
| Full-duplex        | yes                                                                             | can be                       |
|                    | one to one                                                                      | one to one / one to multiple |

At any given time, multiple processes can be using any given transport: [UDP](/docs/CS/CN/UDP.md), SCTP, or [TCP](/docs/CS/CN/TCP.md).
All three transport layers use 16-bit integer port numbers to differentiate between these processes.

### Multiplexing and Demultiplexing

Now let’s consider how a receiving host directs an incoming transport-layer segment to the appropriate socket.
Each transport-layer segment has a set of fields in the segment for this purpose.
At the receiving end, the transport layer examines these fields to identify the receiving socket and then directs the segment to that socket.
This job of delivering the data in a transport-layer segment to the correct socket is called *demultiplexing*.
The job of gathering data chunks at the source host from different sockets, encapsulating each data chunk with header information (that will later be used in demultiplexing) to create segments,
and passing the segments to the network layer is called *multiplexing*.

How the transport layer could implement the demultiplexing service:
Each socket in the host could be assigned a **port number**, and when a segment arrives at the host, the transport layer examines the destination port number in the segment and directs the segment to the corresponding socket.
The segment’s data then passes through the socket into the attached process.
As we’ll see, this is basically how UDP does it.
However, we’ll also see that multiplexing/demultiplexing in TCP is yet more subtle.

### Reliable Data Transfer

Checksums, sequence numbers, timers, and positive and negative acknowledgment packets each play a crucial and necessary role in the operation of the protocol.

Rather than operate in a stop-and-wait manner, the sender is allowed to send multiple packets without waiting for acknowledgments.
Since the many in-transit sender-to-receiver packets can be visualized as filling a pipeline, this technique is known as **pipelining**.
Pipelining has the following consequences for reliable data transfer protocols:

- The range of sequence numbers must be increased, since each in-transit packet (not counting retransmissions) must have a unique sequence number and there may be multiple, in-transit, unacknowledged packets.
- The sender and receiver sides of the protocols may have to buffer more than one packet.
  Minimally, the sender will have to buffer packets that have been transmitted but not yet acknowledged.
  Buffering of correctly received packets may also be needed at the receiver, as discussed below.
- The range of sequence numbers needed and the buffering requirements will depend on the manner in which a data transfer protocol responds to lost, corrupted, and overly delayed packets.
  Two basic approaches toward pipelined error recovery can be identified: **Go-Back-N** and **selective repeat**.

In a Go-Back-N (GBN) protocol, the sender is allowed to transmit multiple packets (when available) without waiting for an acknowledgment, but is constrained to have no more than some maximum allowable number, N, of unacknowledged packets in the pipeline.
N is often referred to as the **window size** and the GBN protocol itself as a **sliding-window protocol**.

Why not allow an unlimited number of such packets?
We’ll see that flow control is one reason to impose a limit on the sender.
We’ll examine another reason to do so in TCP congestion control.

The GBN sender must respond to three types of events:

- Invocation from above.
- Receipt of an ACK.
  In our GBN protocol, an acknowledgment for a packet with sequence number n will be taken to be a cumulative acknowledgment, indicating that all packets with a sequence number up to and including n have been correctly received at the receiver.
- A timeout event.

The GBN protocol allows the sender to potentially “fill the pipeline” with packets, thus avoiding the channel utilization problems we noted with stop-and-wait protocols.
There are, however, scenarios in which GBN itself suffers from performance problems.
In particular, when the window size and bandwidth-delay product are both large, many packets can be in the pipeline.
A single packet error can thus cause GBN to retransmit a large number of packets, many unnecessarily.
As the probability of channel errors increases, the pipeline can become filled with these unnecessary retransmissions.

**Summary of reliable data transfer mechanisms and their use**


| Mechanism               | Use, Comments                                                                                                                                                                                                                                                                                     |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Checksum                | Used to detect bit errors in a transmitted packet.                                                                                                                                                                                                                                                |
| Timer                   | Used to timeout/retransmit a packet, possibly because the packet (or its ACK) was lost within the channel.                                                                                                                                                                                        |
| Sequence number         | Used for sequential numbering of packets of data flowing from sender to receiver.<br />Gaps in the sequence numbers of received packets allow the receiver to detect a lost packet. <br />Packets with duplicate sequence numbers allow the receiver to detect duplicate copies of a packet.      |
| Acknowledgment          | Used by the receiver to tell the sender that a packet or set of packets has been received correctly.<br />Acknowledgments will typically carry the sequence number of the packet or packets being acknowledged. <br />Acknowledgments may be individual or cumulative, depending on the protocol. |
| Negative acknowledgment | Used by the receiver to tell the sender that a packet has not been received correctly.<br />Negative acknowledgments will typically carry the sequence number of the packet that was not received correctly.                                                                                      |
| Window, pipelining      | The sender may be restricted to sending only packets with sequence numbersthat fall within a given range.<br />By allowing multiple packets to be transmitted but not yet acknowledged, sender utilization can be increased over a stop-and-wait mode of operation.                               |

### Connection

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

There is a piece of the network layer in each and every host and router in the network.
We’ll see that the network layer can be decomposed into two interacting parts, the **data-plane** and the **control-plane**.

We’ll first cover the data plane functions of the network layer—the perrouter functions in the network layer that determine how a datagram (that is, a network-layer packet) arriving on one of a router’s input links is forwarded to one of that router’s output links.
We’ll cover both traditional IP forwarding (where forwarding is based on a datagram’s destination address) and generalized forwarding (where forwarding and other functions may be performed using values in several different fields in the datagram’s header).

We’ll cover the control plane functions of the network layer—the network-wide logic that controls how a datagram is routed among routers along an end-to-end path from the source host to the destination host.
We’ll cover routing algorithms, as well as routing protocols, such as OSPF and BGP, that are in widespread use in today’s Internet.
Traditionally, these control-plane routing protocols and data-plane forwarding functions have been implemented together, monolithically, within a router.
Software-defined networking (SDN) explicitly separates the data plane and control plane by implementing these control plane functions as a separate service, typically in a remote “controller.”

The primary role of the network layer is deceptively simple—to move packets from a sending host to a receiving host.
To do so, two important network-layer functions can be identified:

- **Forwarding.**
  Forwarding refers to the router-local action of transferring a packet from an input link interface to the appropriate output link interface.
  Forwarding takes place at very short timescales (typically a few nanoseconds), and thus is typically implemented in hardware.
  Forwarding is the key function performed by the data-plane functionality of the network layer
- **Routing.**
  Routing refers to the network-wide process that determines the end-to-end paths that packets take from source to destination.
  Routing takes place on much longer timescales(typically seconds), and as we will see is often implemented in software.

A key element in every network router is its *forwarding table*.
A router forwards a packet by examining the value of one or more fields in the arriving packet’s header, and then using these header values to index into its forwarding table.
The value stored in the forwarding table entry for those values indicates the outgoing link interface at that router to which that packet is to be forwarded.

### Routing Algorithms

The network layer must determine the route or path taken by packets as they flow from a sender to a receiver.
The algorithms that calculate these paths are referred to as **routing algorithms**.

Broadly, one way in which we can classify routing algorithms is according to whether they are centralized or decentralized.

- A **centralized routing algorithm** computes the least-cost path between a source and destination using complete, global knowledge about the network.
  Algorithms with global state information are often referred to as **link-state (LS) algorithms**, since the algorithm must be aware of the cost of each link in the network.
- In a **decentralized routing algorithm**, the calculation of the least-cost path is carried out in an iterative, distributed manner by the routers.

A second broad way to classify routing algorithms is according to whether they are static or dynamic.

A third way to classify routing algorithms is according to whether they are load-sensitive or loadinsensitive.

#### The Link-State (LS) Routing Algorithm

Recall that in a link-state algorithm, the network topology and all link costs are known, that is, available as input to the LS algorithm.

#### The Distance-Vector (DV) Routing Algorithm

Whereas the LS algorithm is an algorithm using global information, the distance-vector (DV) algorithm is iterative, asynchronous, and distributed.
It is distributed in that each node receives some information from one or more of its directly attached neighbors, performs a calculation, and then distributes the results of its calculation back to its neighbors.
It is iterative in that this process continues on until no more information is exchanged between neighbors. (Interestingly, the algorithm is also self-terminating—there is no signal that the computation should stop; it just stops.)
The algorithm is asynchronous in that it does not require all of the nodes to operate in lockstep with each other.

#### OSPF

#### BGP

### IP

[Internet Protocol(IP)](/docs/CS/CN/IP.md)

[I/O Multiplexing](/docs/CS/CN/MultiIO.md)

In essence, the NAT-enabled router is hiding the details of the home network from the outside world.

### ICMP

[Internet Control Message Protocol](/docs/CS/CN/ICMP.md)

## Data Link Layer

We’ll find it convenient in this chapter to refer to any device that runs a link-layer (i.e., layer 2) protocol as a **node**.
Nodes include hosts, routers, switches, and WiFi access points.
We will also refer to the communication channels that connect adjacent nodes along the communication path as **links**.
Over a given link, a transmitting node encapsulates the datagram in a **link-layer frame** and transmits the frame into the link.

Possible services that can be offered by a link-layer protocol include:

- **Framing.**
  Almost all link-layer protocols encapsulate each network-layer datagram within a link-layer frame before transmission over the link.
- **Link access.**
  A medium access control (MAC) protocol specifies the rules by which a frame is transmitted onto the link.
- **Reliable delivery.**
  When a link-layer protocol provides reliable delivery service, it guarantees to move each network-layer datagram across the link without error.
  A link-layer reliable delivery service is often used for links that are prone to high error rates, such as a wireless link,
  with the goal of correcting an error locally—on the link where the error occurs—rather than forcing an end-to-end retransmission of the data by a transport- or application-layer protocol.
  However, link-layer reliable delivery can be considered an unnecessary overhead for low bit-error links, including fiber, coax, and many twisted-pair copper links.
  For this reason, many wired link-layer protocols do not provide a reliable delivery service.
- **Error detection and correction.**
  Such bit errors are introduced by signal attenuation and electromagnetic noise.
  The Internet’s transport layer and network layer also provide a limited form of error detection—the Internet checksum.
  Error detection in the link layer is usually more sophisticated and is implemented in hardware.
  Error correction is similar to error detection, except that a receiver not only detects when bit errors have occurred in the frame but also determines exactly where in the frame the errors have occurred (and then corrects these errors).

For the most part, the link layer is implemented in a **network adapter**, also sometimes known as a **network interface card (NIC)**.

### Error-Detection and Correction

Generally, more sophisticated error-detection and-correction techniques (that is, those that have a smaller probability of allowing undetected bit errors) incur a larger overhead—more computation is needed to compute and transmit a larger number of error-detection and -correction bits.

Let’s now examine three techniques for detecting errors in the transmitted data:

- parity checks (to illustrate the basic ideas behind error detection and correction),
- checksumming methods (which are more typically used in the transport layer), and
- cyclic redundancy checks (which are more typically used in the link layer in an adapter).

#### CRC

An error-detection technique used widely in today’s computer networks is based on **cyclic redundancy check (CRC) codes**.
CRC codes are also known as **polynomial codes**, since it is possible to view the bit string to be sent as a polynomial whose coefficients are the 0 and 1 values in the bit string, with operations on the bit string interpreted as polynomial arithmetic.

### Multiple Access Links and Protocols

How to coordinate the access of multiple sending and receiving nodes to a shared broadcast channel—the **multiple access problem**.
Computer networks similarly have protocols—so-called **multiple access protocols**—by which nodes regulate their transmission into the shared broadcast channel.

We can classify just about any multiple access protocol as belonging to one of three categories: **channel partitioning protocols**, **random access protocols**, and **taking-turns protocols**.

Ideally, a multiple access protocol for a broadcast channel of rate R bits per second should have the following desirable characteristics:

1. When only one node has data to send, that node has a throughput of R bps.
2. When M nodes have data to send, each of these nodes has a throughput of R/M bps.
   This need not necessarily imply that each of the M nodes always has an instantaneous rate of R/M, but rather that each node should have an average transmission rate of R/M over some suitably defined interval of time.
3. The protocol is decentralized; that is, there is no master node that represents a single point of failure for the network.
4. The protocol is simple, so that it is inexpensive to implement.

#### Channel Partitioning Protocols

**Time-division multiplexing (TDM)** and **frequency-division multiplexing (FDM)** are two techniques that can be used to partition a broadcast channel’s bandwidth among all nodes sharing that channel.
A third channel partitioning protocol is **code division multiple access (CDMA)**.
While TDM and FDM assign time slots and frequencies, respectively, to the nodes, CDMA assigns a different code to each node.

#### Random Access Protocols

In a random access protocol, a transmitting node always transmits at the full rate of the channel, namely, *R* bps.
When there is a collision, each node involved in the collision repeatedly retransmits its frame (that is, packet) until its frame gets through without a collision.
But when a node experiences a collision, it doesn’t necessarily retransmit the frame right away. Instead it waits a random delay before retransmitting the frame.
**Each node involved in a collision chooses independent random delays.**
Because the random delays are independently chosen, it is possible that one of the nodes will pick a delay that is sufficiently less than the delays of the other colliding nodes and will therefore be able to sneak its frame into the channel without a collision.

ALOHA

CSMA

#### Taking-Turns Protocols

The **polling protocol** eliminates the collisions and empty slots that plague random access protocols.
This allows polling to achieve a much higher efficiency. But it also has a few drawbacks.

- The first drawback is that the protocol introduces a polling delay—the amount of time required to notify a node that it can transmit.
- The second drawback, which is potentially more serious, is that if the master node fails, the entire channel becomes inoperative.

The second taking-turns protocol is the **token-passing protocol**. In this protocol there is no master node.
A small, special-purpose frame known as a token is exchanged among the nodes in some fixed order.

### Link-Layer Addressing

[ARP: Address Resolution Protocol](/docs/CS/CN/ARP.md)

## Physical Layer

serial
parallel

Byte
synchronization
async

### Signal

### Encoding

## Wireless and Mobile Networks

We can identify the following elements in a wireless network:

- Wireless hosts.
- Wireless links.

We can find a number of important differences between a wired link and a wireless link:

- **Decreasing signal strength.**
  Electromagnetic radiation attenuates as it passes through matter (e.g., a radio signal passing through a wall).
  Even in free space, the signal will disperse, resulting in decreased signal strength (sometimes referred to as path loss) as the distance between sender and receiver increases.
- **Interference from other sources.**
  Radio sources transmitting in the same frequency band will interfere with each other.
  In addition to interference from transmitting sources, electromagnetic noise within the environment(e.g., a nearby motor, a microwave) can result in interference.
- **Multipath propagation.**
  Multipath propagation occurs when portions of the electromagnetic wave reflect off objects and the ground, taking paths of different lengths between a sender and receiver.
  This results in the blurring of the received signal at the receiver.
  Moving objects between the sender and receiver can cause multipath propagation to change over time.

The **signal-to-noise ratio(SNR)** is a relative measure of the strength of the received signal (i.e., the information being transmitted) and this noise.
The SNR is typically measured in units of decibels (dB).

The **bit error rate(BER)** —roughly speaking, the probability that a transmitted bit is received in error at the receiver.

Several physical-layer characteristics that are important in understanding higher-layer wireless communication protocols:

- For a given modulation scheme, the higher the SNR, the lower the BER.
- For a given SNR, a modulation technique with a higher bit transmission rate (whether in error or not) will have a higher BER.
- Dynamic selection of the physical-layer modulation technique can be used to adapt the modulation technique to channel conditions.

**Code division multiple access (CDMA)** belongs to the family of channel partitioning protocols. It is prevalent in wirelzess LAN and cellular technologies

### WiFi

The **IEEE 802.11 wireless LAN**, also known as **WiFi**.

## Networks Under Attack

### Malware

Viruses

Worms

#### Attack Servers and Network Infrastructure

Another broad class of security threats are known as denial-of-service (DoS) attacks.

- Vulnerability attack.
- Bandwidth flooding.
- Connection flooding.

### Sniff Packets

The basic tool for observing the messages exchanged between executing protocol entities is called a *packet sniffer*.
Sniffed packets can then be analyzed offline for sensitive information.

Indeed, the [Wireshark](/docs/CS/CN/Tools/WireShark.md) is a packet sniffer.

#### Masquerade as Someone You Trust

The ability to inject packets into the Internet with a false source address is known as IP spoofing, and is but one of many ways in which one user can masquerade as another user.

## Tools

[WireShark](/docs/CS/CN/Tools/WireShark.md)

[nginx](/docs/CS/CN/nginx/nginx.md)

[Caddy](/docs/CS/CN/Caddy.md)

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Data Structures and Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computer Organization](/docs/CS/CO/CO.md)
- [Internet Assigned Numbers Authority](https://www.iana.org/)

## References

1. [Computer Networking: A Top-Down Approach 8 edition](https://gaia.cs.umass.edu/kurose_ross/interactive/)
