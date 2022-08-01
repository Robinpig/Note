## Introduction

The [Hypertext Transfer Protocol](https://www.w3.org/Protocols/) (HTTP) is an application-level protocol with the lightness and speed necessary for distributed, collaborative, hypermedia information systems.

It is a generic, stateless, protocol which can be used for many tasks beyond its use for hypertext,
such as name servers and distributed object management systems, through extension of its request methods, error codes and headers. A feature of HTTP is the typing and negotiation of data representation, allowing systems to be built independently of the data being transferred.


> [!NOTE]
>
> See [HTTPS](/docs/CS/CN/TLS.md)

1. 明文传输，不检查内容是否被窃听
2. Stateless
3. 不确定报文是否正常，未被篡改
4. 性能不算高

## HTTP Message

- Header

  - start line
  - header
- CR+LF
- Content


大容量数据使用 Chunked Transfer Coding

多种数据多部分对象集合

**MIME(Multipurpose Internet Mail Extensions)**

multipart/form-data

传输恢复 Range Request

内容协商机制

Content Negotiation

request

request row

method URI HTTP version

```http
GET / HTTP/1.1
```

### Request

A request message from a client to a server includes, within the
first line of that message, the method to be applied to the resource,
the identifier of the resource, and the protocol version in use.

```
        Request       = Request-Line  
                        *(( general-header  
                         | request-header   
                         | entity-header ) CRLF)  
                        CRLF
                        [ message-body ]  
```

#### Request-Line

> [!NOTE]
>
> Request-Line   = Method SP Request-URI SP HTTP-Version CRLF

### Response

After receiving and interpreting a request message, a server responds
with an HTTP response message.

```
       Response      = Status-Line   
                       *(( general-header  
                        | response-header  
                        | entity-header ) CRLF)  
                       CRLF
                       [ message-body ]  
```

#### Status-Line

> [!NOTE]
>
> Status-Line = HTTP-Version SP Status-Code SP Reason-Phrase CRLF

```http
HTTP/1.1 304 Not Modified
```

### HTTP Header

Zip

- gzip (See Nginx `gzip on`)
- br for html

“Transfer-Encoding: chunked”和“Content-Length”这两个字段是互斥的

Accept-Ranges: bytes
ange: bytes=0-31

Content-Range

multipart/byteranges

常用的下载工具里的多段下载、断点续传也是基于它实现的，要点是：

先发个 HEAD，看服务器是否支持范围请求，同时获取文件的大小；
开 N 个线程，每个线程使用 Range 字段划分出各自负责下载的片段，发请求传输数据；
下载意外中断也不怕，不必重头再来一遍，只要根据上次的下载记录，用 Range 请求剩下的那一部分就可以了。

### Connection Management

#### Pipelining

A client that supports persistent connections MAY "pipeline" its requests (i.e., send multiple requests without waiting for each response).
A server may process a sequence of pipelined requests in parallel if they all have safe methods, **but it MUST send the corresponding responses in the same order that the requests were received**.

> [!TIP]
>
> Pipelining solves HOL blocking for requests, but not for responses.

A client that pipelines requests SHOULD retry unanswered requests if the connection closes before it receives all of the corresponding responses.
When retrying pipelined requests after a failed connection (a connection not explicitly closed by the server in its last complete response), a client MUST NOT pipeline immediately after connection establishment,
since the first remaining request in the prior pipeline might have caused an error response that can be lost again if multiple requests are sent on a prematurely closed connection (see the *TCP reset problem*).

> [!NOTE]
>
> **TCP Reset Problem**
>
> If a server performs an immediate close of a TCP connection, there is a significant risk that the client will not be able to read the last HTTP response.
> If the server receives additional data from the client on a fully closed connection, such as another request that was sent by the client before receiving the server's response,
> the server's TCP stack will send a reset packet to the client; unfortunately, the reset packet might erase the client's unacknowledged input buffers before they can be read and interpreted by the client's HTTP parser.
>
> To avoid the TCP reset problem, servers typically close a connection in stages.
>
> - First, the server performs a half-close by closing only the write side of the read/write connection.
>   The server then continues to read from the connection until it receives a corresponding close by the client, or until the server is reasonably certain that its own TCP stack has received the client's acknowledgement of the packet(s) containing the server's last response.
> - Finally, the server fully closes the connection.

Idempotent methods are significant to pipelining because they can be automatically retried after a connection failure.
A user agent SHOULD NOT pipeline requests after a non-idempotent method, until the final response status code for that method has been received, unless the user agent has a means to detect and recover from partial failure conditions involving the pipelined sequence.

An intermediary that receives pipelined requests MAY pipeline those requests when forwarding them inbound, since it can rely on the outbound user agent(s) to determine what requests can be safely pipelined.
If the inbound connection fails before receiving a response, the pipelining intermediary MAY attempt to retry a sequence of requests that have yet to receive a response if the requests all have idempotent methods;
otherwise, the pipelining intermediary SHOULD forward any received responses and then close the corresponding outbound connection(s) so that the outbound user agent(s) can recover accordingly.

- Firstly, some files that can be processed/rendered incrementally do profit from multiplexing. This is for example the case for progressive images.
- Secondly, as also discussed above, it can be useful if one of the files is much smaller than the others, as it will be downloaded earlier while not delaying the others by too much.
- Thirdly, **multiplexing allows changing the order of responses and interrupting a low priority response for a higher priority one.**

[Chromium Remove HTTP pipelining support.](https://codereview.chromium.org/275953002)

#### Concurrency

A client ought to limit the number of simultaneous open connections that it maintains to a given server.

Previous revisions of HTTP gave a specific number of connections as a ceiling, but this was found to be impractical for many applications.
As a result, this specification does not mandate a particular maximum number of connections but, instead, encourages clients to be conservative when opening multiple connections.

Multiple connections are typically used to avoid the ["head-of-line blocking"](/docs/CS/CN/HTTP/HOL.md?id=HTTP) problem, wherein a request that takes significant server-side processing and/or has a large payload blocks subsequent requests on the same connection.
However, each connection consumes server resources.  Furthermore, using multiple connections can cause undesirable side effects in congested networks.

Note that a server might reject traffic that it deems abusive or characteristic of a denial-of-service attack, such as an excessive number of open connections from a single client.

## Request Methods

### Method Definitions

- GET
- POST
- PUT
- DELETE
- HEAD
- OPTIONS
- TRACE
- CONNECT

在HTTP/1.1规范中幂等性的定义是：

> Methods can also have the property of "idempotence" in that (aside from error or expiration issues) the side-effects of N > 0 identical requests is the same as for a single request.

从定义上看，HTTP 方法的幂等性是指一次和多次请求某一个资源应该具有同样的副作用。幂等性属于语义范畴，正如编译器只能帮助检查语法错误一样，HTTP 规范也没有办法通过消息格式等语法手段来定义它，这可能是它不太受到重视的原因之一。但实际上，幂等性是分布式系统设计中十分重要的概念，而 HTTP 的分布式本质也决定了它在 HTTP 中具有重要地位。

HTTP 方法的安全性指的是不会改变服务器状态，也就是说它只是可读的。所以只有 OPTIONS、GET、HEAD 是安全的，其他都是不安全的。


| HTTP 方法 | 幂等性 | 安全性 |
| ----------- | -------- | -------- |
| OPTIONS   | yes    | yes    |
| GET       | yes    | yes    |
| HEAD      | yes    | yes    |
| PUT       | yes    | no     |
| DELETE    | yes    | no     |
| POST      | no     | no     |
| PATCH     | no     | no     |

**POST 和 PATCH 这两个不是幂等性的**。
两次相同的POST请求会在服务器端创建两份资源，它们具有不同的URI。
对同一URI进行多次PUT的副作用和一次PUT是相同的。

### HTTP Status Code



[HTTP Code](https://zh.wikipedia.org/wiki/HTTP%E7%8A%B6%E6%80%81%E7%A0%81)



## Version

### 1.0

todo PUT DELETE not security

### 1.1

#### Connection Keepalive

```http
Connection: keep-Alive
```

[Pipelining](/docs/CS/CN/HTTP/HTTP.mdTP.md?id=pipelining)

### 2

HTTP/2 standard was based on SPDY with some improvements.

#### HTTP Frames

HTTP/2 solved the head-of-the-line blocking problem by multiplexing the HTTP requests over a single open TCP connection.
HTTP/2 solves this quite elegantly by prepending small control messages, called **frames**, before the resource chunks.
By “framing” individual messages HTTP/2 is thus much more flexible than HTTP/1.1.
It allows for many resources to be sent multiplexed on a single TCP connection by interleaving their chunks.

An important consequence of HTTP/2’s approach is that we suddenly also need a way for the browser to communicate to the server how it would like the single connection’s bandwidth to be distributed across resources.
Put differently: how resource chunks should be “scheduled” or interleaved.
If we again visualize this with 1’s and 2’s, we see that for HTTP/1.1, the only option was 11112222 (let’s call that sequential).
HTTP/2 however has a lot more freedom:

- Fair multiplexing (for example two progressive JPEGs): 12121212
- Weighted multiplexing (2 is twice as important as 1): 221221221
- Reversed sequential scheduling (for example 2 is a key Server Pushed resource): 22221111
- Partial scheduling (stream 1 is aborted and not sent in full): 112222

Which of these is used is driven by the so-called “prioritization” system in HTTP/2 and the chosen approach can have a big impact on Web performance.

HTTP/2 also allows compressing request headers in addition to the request body, which further reduces the amount of data transferred over the wire.

#### HTTP2 over TLS

Next Protocol Negotiation (NPN) is the protocol used to negotiate SPDY with TLS servers. 
As it wasn't a proper standard, it was taken through the IETF and the result was ALPN: Application Layer Protocol Negotiation. 
ALPN is being promoted for use by http2, while SPDY clients and servers still use NPN.

The fact that NPN existed first and ALPN has taken a while to go through standardization has led to many early http2 clients and http2 servers implementing and using both these extensions when negotiating http2. 
Also, NPN is what's used for SPDY and many servers offer both SPDY and http2, so supporting both NPN and ALPN on those servers makes perfect sense.

ALPN differs from NPN primarily in who decides what protocol to speak. 
With ALPN, the client gives the server a list of protocols in its order of preference and the server picks the one it wants, while with NPN the client makes the final choice.

#### Binary Message

HTTP/2 also enables more efficient processing of messages through use of binary message framing.

#### HPACK

[HPACK](https://www.rfc-editor.org/rfc/rfc7541.txt) was designed to make it difficult for a conforming implementation to leak information, to make encoding and decoding very fast/cheap, 
to provide for receiver control over compression context size, to allow for proxy re-indexing (i.e., shared state between frontend and backend within a proxy), and for quick comparisons of Huffman-encoded strings.


#### Reset

One of the drawbacks with HTTP 1.1 is that when an HTTP message has been sent off with a Content-Length of a certain size, you can't easily just stop it. Sure, you can often (but not always) disconnect the TCP connection, but that comes at the cost of having to negotiate a new TCP handshake again.
A better solution would be to just stop the message and start anew. This can be done with http2's RST_STREAM frame which will help prevent wasted bandwidth and the need to tear down connections.

#### Server push

This is the feature also known as “cache push”. The idea is that if the client asks for resource X, the server may know that the client will probably want resource Z as well, and sends it to the client without being asked. It helps the client by putting Z into its cache so that it will be there when it wants it.
Server push is something a client must explicitly allow the server to do. Even then, the client can swiftly terminate a pushed stream at any time with RST_STREAM should it not want a particular resource.

#### Flow Control

Each individual http2 stream has its own advertised flow window that the other end is allowed to send data for. If you happen to know how SSH works, this is very similar in style and spirit.
For every stream, both ends have to tell the peer that it has enough room to handle incoming data, and the other end is only allowed to send that much data until the window is extended. Only DATA frames are flow controlled.


### 3

HTTP over [QUIC](/docs/CS/CN/HTTP/QUIC.md)

## URI

URI(Uniform Resource Identifier)

URL(Uniform Resource Locator)

Proxy

Cache

## State Management Mechanism

HTTP is stateless.

To overcome the stateless nature of HTTP requests, we could use either a session or a token.


### Cookies

It is often desirable for a Web site to identify users, either because the server wishes to restrict user access or because it wants to serve content as a function of the user identity.
For these purposes, HTTP uses cookies.
[RFC 6265](https://datatracker.ietf.org/doc/rfc6265/) defines the HTTP Cookie and Set-Cookie header fields.
These header fields can be used by HTTP servers to store state(called cookies) at HTTP user agents, letting the servers maintain a stateful session over the mostly stateless HTTP protocol.  
Although cookies have many historical infelicities that degrade their security and privacy, the Cookie and Set-Cookie header fields are widely used on the Internet.


To store state, the origin server includes a Set-Cookie header in an HTTP response.  
In subsequent requests, the user agent returns a Cookie request header to the origin server.  
The Cookie header contains cookies the user agent received in previous Set-Cookie headers.  
The origin server is free to ignore the Cookie header or use its contents for an application-defined purpose.

Origin servers MAY send a Set-Cookie response header with any response.  
User agents MAY ignore Set-Cookie headers contained in responses with 100-level status codes but MUST process Set-Cookie headers contained in other responses (including responses with 400- and 500-level status codes).  
An origin server can include multiple Set-Cookie header fields in a single response.  
The presence of a Cookie or a Set-Cookie header field does not preclude HTTP caches from storing and reusing a response.

Origin servers SHOULD NOT fold multiple Set-Cookie header fields into a single header field.  
The usual mechanism for folding HTTP headers fields might change the semantics of the Set-Cookie header field because the %x2C (",") character is used by Set-Cookie in a way that conflicts with such folding.

Cookie technology has four components:

1. a cookie header line in the HTTP response message
2. a cookie header line in the HTTP request message
3. a cookie file kept on theuser’s end system and managed by the user’s browser
4. a back-end database at the Web site

#### Security

Cookies have a number of security pitfalls.  This section overviews a few of the more salient issues.

In particular, cookies encourage developers to rely on ambient authority for authentication, often becoming vulnerable to attacks such as cross-site request forgery [CSRF].  
Also, when storing session identifiers in cookies, developers often create session fixation vulnerabilities.

Transport-layer encryption, such as that employed in HTTPS, is insufficient to prevent a network attacker from obtaining or altering a victim's cookies because the cookie protocol itself has various vulnerabilities (see "Weak Confidentiality" and "Weak Integrity", below).  
In addition, by default, cookies do not provide confidentiality or integrity from network attackers, even when used in conjunction with HTTPS.

Unless sent over a secure channel (such as TLS), the information in the Cookie and Set-Cookie headers is transmitted in the clear.

1.  All sensitive information conveyed in these headers is exposed to an eavesdropper.
2.  A malicious intermediary could alter the headers as they travel in either direction, with unpredictable results.
3.  A malicious client could alter the Cookie header before transmission, with unpredictable results.


Instead of storing session information directly in a cookie (where it might be exposed to or replayed by an attacker), servers commonly store a nonce (or "session identifier") in a cookie.  
When the server receives an HTTP request with a nonce, the server can look up state information associated with the cookie using the nonce as a key.

##### Weak Confidentiality and Weak Integrity

- Cookies do not provide isolation by port.
- Cookies do not provide isolation by scheme.
- Cookies do not always provide isolation by path.
- Cookies do not provide integrity guarantees for sibling domains (and their subdomains).


### Json Web Token

JSON Web Token (JWT) is a compact claims representation format intended for space constrained environments such as HTTP Authorization headers and URI query parameters.  
JWTs encode claims to be transmitted as a JSON object that is used as the payload of a JSON Web Signature (JWS) structure or as the plaintext of a JSON Web Encryption (JWE) structure, 
enabling the claims to be digitally signed or integrity protected with a Message Authentication Code (MAC) and/or encrypted.  
JWTs are always represented using the JWS Compact Serialization or the JWE Compact Serialization.

Here are some scenarios where JSON Web Tokens are useful:

- **Authorization**: This is the most common scenario for using JWT. 
  Once the user is logged in, each subsequent request will include the JWT, allowing the user to access routes, services, and resources that are permitted with that token. 
  Single Sign On is a feature that widely uses JWT nowadays, because of its small overhead and its ability to be easily used across different domains.
- **Information Exchange**: JSON Web Tokens are a good way of securely transmitting information between parties. 
  Because JWTs can be signed—for example, using public/private key pairs—you can be sure the senders are who they say they are. 
  Additionally, as the signature is calculated using the header and the payload, you can also verify that the content hasn't been tampered with.





> [RFC 7519 - JSON Web Token (JWT)](https://datatracker.ietf.org/doc/rfc7519/)
> [RFC 7797 - JSON Web Signature (JWS) Unencoded Payload Option](https://datatracker.ietf.org/doc/rfc7797/)
> [RFC 8725 - JSON Web Token Best Current Practices](https://datatracker.ietf.org/doc/rfc8725/)




#### Structure

Header

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

Payload

```json
{
  "sub": "1234567890",
  "name": "John Doe",
  "iat": 1516239022
}
```
Signature

See [JWT.IO](https://jwt.io/).



In authentication, when the user successfully logs in using their credentials, a JSON Web Token will be returned. 
Since tokens are credentials, great care must be taken to prevent security issues. In general, you should not keep tokens longer than required.

You also should not store sensitive session data in browser storage due to lack of security.

Whenever the user wants to access a protected route or resource, the user agent should send the JWT, typically in the Authorization header using the Bearer schema. 
The content of the header should look like the following:

```http
Authorization: Bearer <token>
```

This can be, in certain cases, a stateless authorization mechanism. 
The server's protected routes will check for a valid JWT in the Authorization header, and if it's present, the user will be allowed to access protected resources. 
If the JWT contains the necessary data, the need to query the database for certain operations may be reduced, though this may not always be the case.

If the token is sent in the Authorization header, Cross-Origin Resource Sharing (CORS) won't be an issue as it doesn't use cookies.

Do note that with signed tokens, all the information contained within the token is exposed to users or other parties, even though they are unable to change it. 
This means you should not put secret information within the token.

## Security

[HTTP Security](/docs/CS/CN/HTTP/Security.md)

## Performance

[WebPageTest](https://www.webpagetest.org)

[H2O](https://h2o.examp1e.net/)

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [DNS](/docs/CS/CN/DNS.md)
- [WebSocket](/docs/CS/CN/WebSocket.md)
- [OAuth](/docs/CS/CN/HTTP/OAuth.md)

## References

1. [RFC 1945 - Hypertext Transfer Protocol -- HTTP/1.0](https://www.rfc-editor.org/info/rfc1945)
2. [RFC 2045 - Multipurpose Internet Mail Extensions(MIME) Part One:Format of Internet Message Bodies](https://www.rfc-editor.org/info/rfc2045)
3. [RFC 2324 - Hyper Text Coffee Pot Control Protocol (HTCPCP/1.0)](https://www.rfc-editor.org/info/rfc2324)
4. [RFC 2616 - Hypertext Transfer Protocol -- HTTP/1.1](https://www.rfc-editor.org/info/rfc2616)
5. [RFC 2616 - Hypertext Transfer Protocol -- HTTP/1.1](https://www.rfc-editor.org/info/rfc7230)
6. [RFC 4122 - A Universally Unique IDentifier (UUID) URN Namespace](https://www.rfc-editor.org/info/rfc4122)
7. [RFC 4648 - The Base16, Base32, and Base64 Data Encodings](https://www.rfc-editor.org/info/rfc4648)
8. [RFC 7230 - Hypertext Transfer Protocol (HTTP/1.1): Message Syntax and Routing](https://www.rfc-editor.org/info/rfc7230)
9. [RFC 7540 - Hypertext Transfer Protocol Version 2 (HTTP/2)](https://www.rfc-editor.org/info/rfc7540)
10. [RFC 7168 - The Hyper Text Coffee Pot Control Protocol for Tea Efflux Appliances (HTCPCP-TEA)](https://datatracker.ietf.org/doc/html/rfc7168)
11. [RFC 6265 - HTTP State Management Mechanism](https://datatracker.ietf.org/doc/rfc6265/)
12. [RFC 2396 - Uniform Resource Identifiers (URI): Generic Syntax](https://datatracker.ietf.org/doc/rfc2396/)
13. [RFC 3986 - Uniform Resource Identifier (URI): Generic Syntax](https://datatracker.ietf.org/doc/rfc3986/)
14. [Hypertext Transfer Protocol Version 3 (HTTP/3)](https://quicwg.org/base-drafts/draft-ietf-quic-http.html)
