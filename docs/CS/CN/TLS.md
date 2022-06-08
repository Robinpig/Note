## Introduction

> HTTPS = [HTTP](/docs/CS/CN/HTTP/HTTP.md) + TLS/SSL

TLS is a client/server protocol, designed to support security for a connection between two applications. 
The Record protocol provides fragmentation, compression, integrity protection, and encryption for data objects exchanged between clients and servers, 
and the handshake protocols establish identities, perform authentication, indicate alerts, and provide unique key material for the Record protocol to use on each connection. 
The handshaking protocols comprise four specific protocols: the Handshake protocol, the Alert protocol, the Change Cipher Spec protocol, and the application data protocol. 

The Change Cipher Spec protocol is used to change the current operating parameters. 
This is accomplished by first using the Handshake protocol to set up a “pending” state, followed by an indication to switch from the current state to the pending state (which then becomes the current state). 
Such switching is allowed only after the pending state has been readied. 
TLS depends on five cryptographic operations: digital signing, stream cipher encryption, block cipher encryption, AEAD, and public key encryption. For integrity protection, the TLS record layer uses HMAC. 
For key generation, TLS 1.2 uses a PRF based on HMAC with SHA-256. TLS also integrates an optional compression algorithm that is negotiated when a connection is first established.


### Record Protocol

The Record protocol uses an extensible set of record content type values to identify which message type (i.e., which of the higher-layer protocols) is being multiplexed. 
At any given point in time, the Record protocol has an active current connection state and another set of state parameters called the pending connection state. 
Each connection state is further divided into a read state and a write state. 
Each of these states specifies a compression algorithm, encryption algorithm, and MAC algorithm to be used for communication, along with any necessary keys and parameters. 
When a key is changed, the pending state is first set up using the Handshake protocol, and then a synchronization operation (usually accomplished using the Cipher Change protocol) sets the current state equal to the pending state. 
When first initialized, all states are set up with NULL encryption, no compression, and no MAC processing.


### Handshaking Protocols

There are three subprotocols to TLS, which perform tasks roughly equivalent to those performed by IKE in IPsec. 
More specifically, these other protocols are identified by numbers used for multiplexing and demultiplexing by the record layer and are called the Handshake protocol (22), 
Alert protocol (21), and Cipher Change protocol (20). 
The Cipher Change protocol is very simple. It consists of one message containing a single byte that has the value 
1. The purpose of the message is to indicate to the peer a desire to change from the current to the pending state. Receiving such a message moves the read pending state to the current state and causes an indication to the record layer to transition to the pending write state as soon as possible. 
   This message is used by both client and server.


The Alert protocol is used to deliver status information from one end of a TLS connection to another. 
This can include terminating conditions (either fatal errors or controlled shutdowns) or nonfatal error conditions. 
As of the publication of [RFC5246], 24 alert messages were defined in standards. More than half of them are always fatal (e.g., bad MACs, missing or unknown messages, algorithm failures).

The Handshake protocol sets up the relevant connection operating parameters. 
It allows the TLS endpoints to achieve six major objectives: agree on algorithms and exchange random values used in forming symmetric encryption keys, 
establish algorithm operating parameters, exchange certificates and perform mutual authentication, generate a session-specific secret, 
provide security parameters to the record layer, and verify that all of these operations have executed properly. 



### Renegotiation

TLS supports the ability to renegotiate cryptographic connection parameters while maintaining the same connection. This can be initiated by either the server or the client. 
If the server wishes to renegotiate the connection parameters, it generates a HelloRequest message, and the client responds with a new ClientHell message, which begins the renegotiation procedure. 
The client is also able to generate such a ClientHello message spontaneously, without prompting from the server.




The primary goal of TLS is to provide a secure channel between two communicating peers; the only requirement from the underlying transport is a reliable, in-order data stream.  
Specifically, the secure channel should provide the following properties:

-  Authentication: 
   The server side of the channel is always authenticated; the client side is optionally authenticated.
   Authentication can happen via asymmetric cryptography (e.g., RSA, the Elliptic Curve Digital Signature Algorithm (ECDSA), or the Edwards-Curve Digital Signature Algorithm ([EdDSA](https://www.rfc-editor.org/rfc/rfc8032)) or a symmetric pre-shared key (PSK).

-  Confidentiality: 
   Data sent over the channel after establishment is only visible to the endpoints.  
   TLS does not hide the length of the data it transmits, though endpoints are able to pad TLS records in order to obscure lengths and improve protection against traffic analysis techniques.

-  Integrity: 
   Data sent over the channel after establishment cannot be modified by attackers without detection.

These properties should be true even in the face of an attacker who has complete control of the network, as described in [RFC3552](https://www.rfc-editor.org/rfc/rfc3552).  
See Appendix E for a more complete statement of the relevant security properties.

TLS consists of two primary components:
-  A handshake protocol that authenticates the communicating parties, negotiates cryptographic modes and parameters, and establishes shared keying material.  
   The handshake protocol is designed to resist tampering; an active attacker should not be able to force the peers to negotiate different parameters than they would if the connection were not under attack.
-  A record protocol that uses the parameters established by the handshake protocol to protect traffic between the communicating peers.  
   The record protocol divides traffic up into a series of records, each of which is independently protected using the traffic keys.





TLS is application protocol independent; higher-level protocols can layer on top of TLS transparently.  
The TLS standard, however, does not specify how protocols add security with TLS; 
how to initiate TLS handshaking and how to interpret the authentication certificates exchanged are left to the judgment of the designers and implementors of protocols that run on top of TLS.




TLS supports three basic key exchange modes:

-  (EC)DHE (Diffie-Hellman over either finite fields or elliptic curves)
-  PSK-only
-  PSK with (EC)DHE


### security

verified certifcation

client验证CA证书正确后本地生成随机数用于对称算法 通过公钥传输给服务端私钥解析后对称加密传输

中间人攻击 若中间存在伪造的服务器 则可获得随机数对称解密数据 拿用户请求的数据去请求目标服务器

非对称加密传输对称加密的密钥

对称加密解析比非对称加密快

摘要算法

客户端在发送明文之前会通过摘要算法算出明文的「指纹」，发送的时候把「指纹 + 明文」一同加密成
密文后，发送给服务器，服务器解密后，用相同的摘要算法算出发送过来的明文，通过比较客户端携带
的「指纹」和当前算出的「指纹」做比较，若「指纹」相同，说明数据是完整的。

CA

客户端在发送明文之前会通过摘要算法算出明文的「指纹」，发送的时候把「指纹 + 明文」一同加密成
密文后，发送给服务器，服务器解密后，用相同的摘要算法算出发送过来的明文，通过比较客户端携带
的「指纹」和当前算出的「指纹」做比较，若「指纹」相同，说明数据是完整的。

Encryption

Data integrity

Authentication

SSL

`Secure Socket Layer`

TLS

`Transport Layer Security`

key pairs

- private key in Server
- public key

密钥交换算法 - signature algorithms - 对称加密算法 - (分组模式) - 摘要算法

CA

`Certificate Authority`

可信度依次增加

1. DV
2. OV
3. EV

SSL/TLS 协议建立流程:

1. ClientHello

   client->server, send Client Random, support protocol version, algorithm list
2. ServerHello

   check protocol version and algorithm list, return with Server Random CA
3. client response

   check CA, get public key from CA ,

   create pre-master key and send
4. server response

   get pre-master key, calc private key

## Version

### 1.2

2 RTT

### 1.3

1 RTT

ECDHE rather than RSA

0 RTT

Digest Algorithm

## Handshaking

The TLS Handshake Protocol involves the following steps:

-  Exchange hello messages to agree on algorithms, exchange *random values*, and check for session resumption.
-  Exchange the *necessary cryptographic parameters* to allow the client and server to agree on a *premaster secret*.
-  Exchange certificates and cryptographic information to allow the client and server to authenticate themselves.
-  Generate a master secret from the premaster secret and exchanged random values.
-  Provide security parameters to the record layer.
-  Allow the client and server to verify that their peer has calculated the same security parameters and that the handshake occurred without tampering by an attacker.

1.2

```
Client                                               Server

   ClientHello                  -------->
                                                   ServerHello
                                                  Certificate*
                                            ServerKeyExchange*
                                           CertificateRequest*
                                <--------      ServerHelloDone
   Certificate*
   ClientKeyExchange
   CertificateVerify*
   [ChangeCipherSpec]
   Finished                     -------->
                                            [ChangeCipherSpec]
                                <--------             Finished
   Application Data             <------->     Application Data

          Message flow for a full handshake
```


## 0-RTT and Anti-Replay




DES

unsafe 

AES





## References

1. [RFC 2246 - The TLS Protocol Version 1.0](https://www.rfc-editor.org/rfc/rfc2246.html)
2. [RFC 4346 - The Transport Layer Security (TLS) Protocol Version 1.1](https://www.rfc-editor.org/rfc/rfc4346.html)
3. [RFC 5246 - The Transport Layer Security (TLS) Protocol Version 1.2](https://www.rfc-editor.org/rfc/rfc5246.html)
4. [RFC 8446 - The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446.html)
