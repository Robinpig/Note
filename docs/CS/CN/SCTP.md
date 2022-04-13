## Introduction



SCTP provides *associations* between clients and servers.

2960 3309 3286

SCTP is message-oriented.

SCTP can provide multiple streams between connection endpoints, each with its own reliable sequenced delivery of messages.
A lost message in one of these streams does not block delivery of messages in any of the other streams.
This approach is in contrast to TCP, where a loss at any point in the single stream of bytes blocks delivery of all future data on the connection until the loss is repaired.

SCTP also provides a multihoming feature, which allows a single SCTP endpoint to support multiple IP addresses.

SCTP is connection-oriented like TCP, so it also has association establishment and termination handshakes. 
However, SCTP’s handshakes are different than TCP’s, so we describe them here.

### Four-Way Handshake

The following scenario, similar to TCP, occurs when an SCTP association is established:
1. The server must be prepared to accept an incoming association. This preparation is normally done by calling socket, bind, and listen and is called a passive open.
2. The client issues an active open by calling connect or by sending a message, which implicitly opens the association. 
   This causes the client SCTP to send an INIT message (which stands for ‘‘initialization’’) to tell the server the client’s list of IP addresses, initial sequence number, 
   initiation tag to identify all packets in this association, number of outbound streams the client is requesting, and number of inbound streams the client can support.
3. The server acknowledges the client’s INIT message with an INIT-ACK message, which contains the server’s list of IP addresses, 
   initial sequence number, initiation tag, number of outbound streams the server is requesting, number of inbound streams the server can support, and a state cookie. 
   The state cookie contains all of the state that the server needs to ensure that the association is valid, and is digitally signed to ensure its validity.
4. The client echos the server’s state cookie with a COOKIE-ECHO message. This message may also contain user data bundled within the same packet.
5. The server acknowledges that the cookie was correct and that the association was established with a COOKIE-ACK message. 
   This message may also contain user data bundled within the same packet.

The minimum number of packets required for this exchange is four; hence, this process is called SCTP’s *four-way handshake*.
The SCTP four-way handshake is similar in many ways to TCP’s three-way handshake, except for the cookie generation, which is an integral part. 

SCTP’s four-way handshake using Cookies formalizes a method of protection against denial-of-service attack.
Many TCP implementations use a similar method; the big difference is that in TCP, the cookie state must be encoded into the initial sequence number, which is only 32 bits.
SCTP provides an arbitrary-length field, and requires cryptographic security to prevent attacks.


### Association Termination

Unlike TCP, SCTP does not permit a ‘‘half-closed’’ association.
When one end shuts down an association, the other end must stop sending new data. The receiver of the shutdown request sends the data that was queued, if any, and then completes the shutdown.


SCTP does not have a TIME_WAIT state like TCP, due to its use of verification tags.
All chunks are tagged with the tag exchanged in the INIT chunks; a chunk from an old connection will arrive with an incorrect tag. 
Therefore, in lieu of keeping an entire connection in TIME_WAIT, SCTP instead places verification tag values in TIME_WAIT.




### State Transition Diagram






## Links
- [Computer Network](/docs/CS/CN/CN.md)


