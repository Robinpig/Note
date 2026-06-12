## Introduction

The WebSocket Protocol enables two-way communication between a client running untrusted code in a controlled environment to a remote host that has opted-in to communications from that code.
The security model used for this is the origin-based security model commonly used by web browsers.
The protocol consists of an opening handshake followed by basic message framing, layered over [TCP](/docs/CS/CN/TCP/TCP.md).
The goal of this technology is to provide a mechanism for browser-based applications that need two-way communication with servers that does not rely on opening multiple [HTTP](/docs/CS/CN/HTTP/HTTP.md) connections (e.g., using XMLHttpRequest or `<iframe>`s and long polling).

### Background

Historically, creating web applications that need bidirectional communication between a client and a server (e.g., instant messaging and gaming applications) has required an abuse of HTTP to poll the server for updates while sending upstream notifications as distinct HTTP calls.

This results in a variety of problems:

- The server is forced to use a number of different underlying TCP connections for each client: one for sending information to the client and a new one for each incoming message.
- The wire protocol has a high overhead, with each client-to-server message having an HTTP header.
- The client-side script is forced to maintain a mapping from the outgoing connections to the incoming connection to track replies

A simpler solution would be to use a single TCP connection for traffic in both directions. This is what the WebSocket Protocol provides.
Combined with the WebSocket API, it provides an alternative to HTTP polling for two-way communication from a web page to a remote server.

The same technique can be used for a variety of web applications: games, stock tickers, multiuser applications with simultaneous editing, user interfaces exposing server-side services in real time, etc.

The WebSocket Protocol is designed to supersede existing bidirectional communication technologies that use HTTP as a transport layer to benefit from existing infrastructure (proxies, filtering, authentication).
Such technologies were implemented as trade-offs between efficiency and reliability because HTTP was not initially meant to be used for bidirectional communication (see [RFC6202](https://datatracker.ietf.org/doc/html/rfc6202) for further discussion).
The WebSocket Protocol attempts to address the goals of existing bidirectional HTTP technologies in the context of the existing HTTP infrastructure;
as such, it is designed to work over HTTP ports 80 and 443 as well as to support HTTP proxies and intermediaries, even if this implies some complexity specific to the current environment.
However, the design does not limit WebSocket to HTTP, and future implementations could use a simpler handshake over a dedicated port without reinventing the entire protocol.
This last point is important because the traffic patterns of interactive messaging do not closely match standard HTTP traffic and can induce unusual loads on some components.

### Protocol Overview

The protocol has two parts: a handshake and the data transfer.
The handshake from the client looks as follows:

```http
GET /chat HTTP/1.1
Host: server.example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Origin: http://example.com
Sec-WebSocket-Protocol: chat, superchat
Sec-WebSocket-Version: 13
```

The handshake from the server looks as follows:

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
Sec-WebSocket-Protocol: chat
```

Once the client and server have both sent their handshakes, and if the handshake was successful, then the data transfer part starts.
This is a two-way communication channel where each side can, independently from the other, send data at will.

After a successful handshake, clients and servers transfer data back and forth in conceptual units referred to in this specification as "messages".
On the wire, a message is composed of one or more frames. 
The WebSocket message does not necessarily correspond to a particular network layer framing, as a fragmented message may be coalesced or split by an intermediary.

A frame has an associated type. 
Each frame belonging to the same message contains the same type of data. Broadly speaking, 
there are types for textual data (which is interpreted as UTF-8 text), 
binary data (whose interpretation is left up to the application),
and control frames (which are not intended to carry data for the application but instead for protocol-level signaling, 
such as to signal that the connection should be closed). 
This version of the protocol defines six frame types and leaves ten reserved for future use.

The WebSocket Protocol is designed on the principle that there should be minimal framing 
(the only framing that exists is to make the protocol frame-based instead of stream-based and to support a distinction between Unicode text and binary frames).
It is expected that metadata would be layered on top of WebSocket by the application layer, in the same way that metadata is layered on top of TCP by the application layer (e.g., HTTP).

Conceptually, WebSocket is really just a layer on top of TCP that does the following:

- adds a web origin-based security model for browsers
- adds an addressing and protocol naming mechanism to support multiple services on one port and multiple host names on one IP address
- layers a framing mechanism on top of TCP to get back to the IP packet mechanism that TCP is built on, but without length limits
- includes an additional closing handshake in-band that is designed to work in the presence of proxies and other intermediaries

Other than that, WebSocket adds nothing.
Basically it is intended to be as close to just exposing raw TCP to script as possible given the constraints of the Web.
It's also designed in such a way that its servers can share a port with HTTP servers, by having its handshake be a valid HTTP Upgrade request.
One could conceptually use other protocols to establish client-server messaging, but the intent of WebSockets is to provide a relatively simple protocol that can coexist with HTTP and deployed HTTP infrastructure (such as proxies)
and that is as close to TCP as is safe for use with such infrastructure given security considerations, with targeted additions to simplify usage and keep simple things simple (such as the addition of message semantics).

The protocol is intended to be extensible; future versions will likely introduce additional concepts such as multiplexing.

The WebSocket Protocol is an independent TCP-based protocol.
Its only relationship to HTTP is that its handshake is interpreted by HTTP servers as an Upgrade request.

By default, the WebSocket Protocol uses port 80 for regular WebSocket connections and port 443 for WebSocket connections tunneled over Transport Layer Security (TLS).

## Data Framing

In the WebSocket Protocol, data is transmitted using a sequence of frames.
The base framing protocol defines a frame type with an opcode, a payload length, and designated locations for "Extension data" and "Application data", which together define the "Payload data".
Certain bits and opcodes are reserved for future expansion of the protocol.
A data frame MAY be transmitted by either the client or the server at any time after opening handshake completion and before that endpoint has sent a Close frame.

```
      0                   1                   2                   3
      0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
     +-+-+-+-+-------+-+-------------+-------------------------------+
     |F|R|R|R| opcode|M| Payload len |    Extended payload length    |
     |I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
     |N|V|V|V|       |S|             |   (if payload len==126/127)   |
     | |1|2|3|       |K|             |                               |
     +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
     |     Extended payload length continued, if payload len == 127  |
     + - - - - - - - - - - - - - - - +-------------------------------+
     |                               |Masking-key, if MASK set to 1  |
     +-------------------------------+-------------------------------+
     | Masking-key (continued)       |          Payload Data         |
     +-------------------------------- - - - - - - - - - - - - - - - +
     :                     Payload Data continued ...                :
     + - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
     |                     Payload Data continued ...                |
     +---------------------------------------------------------------+
```

### Fragmentation

The primary purpose of fragmentation is to allow sending a message that is of unknown size when the message is started without having to buffer that message.
If messages couldn't be fragmented, then an endpoint would have to buffer the entire message so its length could be counted before the first byte is sent.
With fragmentation, a server or intermediary may choose a reasonable size buffer and, when the buffer is full, write a fragment to the network.

A secondary use-case for fragmentation is for multiplexing, where it is not desirable for a large message on one logical channel to monopolize the output channel, so the multiplexing needs to be free to split the message into smaller fragments to better share the output channel.
(Note that the multiplexing extension is not described in this document.)

Unless specified otherwise by an extension, frames have no semantic meaning.
An intermediary might coalesce and/or split frames, if no extensions were negotiated by the client and the server or if some extensions were negotiated, but the intermediary understood all the extensions negotiated and knows how to coalesce and/or split frames in the presence of these extensions.
One implication of this is that in absence of extensions, senders and receivers must not depend on the presence of specific frame boundaries.

The following rules apply to fragmentation:

- An unfragmented message consists of a single frame with the FIN bit set (Section 5.2) and an opcode other than 0.
- A fragmented message consists of a single frame with the FIN bit clear and an opcode other than 0, followed by zero or more frames with the FIN bit clear and the opcode set to 0, and terminated by a single frame with the FIN bit set and an opcode of 0.
  A fragmented message is conceptually equivalent to a single larger message whose payload is equal to the concatenation of the payloads of the fragments in order; however, in the presence of extensions, this may not hold true as the extension defines the interpretation of the "Extension data" present.
  For instance,"Extension data" may only be present at the beginning of the first fragment and apply to subsequent fragments, or there may be"Extension data" present in each of the fragments that applies only to that particular fragment.
  In the absence of "Extension data", the following example demonstrates how fragmentation works.<br>
  EXAMPLE: For a text message sent as three fragments, the first fragment would have an opcode of 0x1 and a FIN bit clear, the second fragment would have an opcode of 0x0 and a FIN bit clear, and the third fragment would have an opcode of 0x0 and a FIN bit that is set.
- Control frames MAY be injected in the middle of a fragmented message.  Control frames themselves MUST NOT be fragmented.
- Message fragments MUST be delivered to the recipient in the order sent by the sender.
- The fragments of one message MUST NOT be interleaved between the fragments of another message unless an extension has been negotiated that can interpret the interleaving.
- An endpoint MUST be capable of handling control frames in the middle of a fragmented message.
- A sender MAY create fragments of any size for non-control messages.
- Clients and servers MUST support receiving both fragmented and unfragmented messages.
- As control frames cannot be fragmented, an intermediary MUST NOT attempt to change the fragmentation of a control frame.
- An intermediary MUST NOT change the fragmentation of a message if any reserved bit values are used and the meaning of these values is not known to the intermediary.
- An intermediary MUST NOT change the fragmentation of any message in the context of a connection where extensions have been negotiated and the intermediary is not aware of the semantics of the negotiated extensions.
  Similarly, an intermediary that didn't see the WebSocket handshake (and wasn't notified about its content) that resulted in a WebSocket connection MUST NOT change the fragmentation of any message of such connection.
- As a consequence of these rules, all fragments of a message are of the same type, as set by the first fragment's opcode.
  Since control frames cannot be fragmented, the type for all fragments in a message MUST be either text, binary, or one of the reserved opcodes.

NOTE: If control frames could not be interjected, the latency of a ping, for example, would be very long if behind a large message.
Hence, the requirement of handling control frames in the middle of a fragmented message.

IMPLEMENTATION NOTE: In the absence of any extension, a receiver doesn't have to buffer the whole frame in order to process it.
For example, if a streaming API is used, a part of a frame can be delivered to the application.
However, note that this assumption might not hold true for all future WebSocket extensions.

Control frames are identified by opcodes where the most significant bit of the opcode is 1.
Currently defined opcodes for control frames include 0x8 (Close), 0x9 (Ping), and 0xA (Pong).
Opcodes 0xB-0xF are reserved for further control frames yet to be defined.

Control frames are used to communicate state about the WebSocket.
Control frames can be interjected in the middle of a fragmented message.

All control frames MUST have a payload length of 125 bytes or less and MUST NOT be fragmented.

## Sending and Receiving Data

### Sending Data

### Receiving Data

## Security Considerations

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [TCP](/docs/CS/CN/TCP/TCP.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## References

1. [RFC 6455 - The WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)
