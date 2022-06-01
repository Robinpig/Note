## Introduction

The [Hypertext Transfer Protocol](https://www.w3.org/Protocols/) (HTTP) is an application-level protocol with the lightness and speed necessary for distributed, collaborative, hypermedia information systems.

It is a generic, stateless, protocol which can be used for many tasks beyond its use for hypertext,
such as name servers and distributed object management systems, through extension of its request methods, error codes and headers. A feature of HTTP is the typing and negotiation of data representation, allowing systems to be built independently of the data being transferred.

半双工 请求-响应 容易队头阻塞

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

内容编码

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

首部字段允许重复, 由接受者自行处理

RFC 2616 -

RFC 4229 -

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

Multiple connections are typically used to avoid the ["head-of-line blocking"](/docs/CS/CN/HOL.md?id=HTTP) problem, wherein a request that takes significant server-side processing and/or has a large payload blocks subsequent requests on the same connection.
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

服务器返回的 **响应报文** 中第一行为状态行，包含了状态码以及原因短语，用来告知客户端请求的结果。

[HTTP Code](https://zh.wikipedia.org/wiki/HTTP%E7%8A%B6%E6%80%81%E7%A0%81)


| 状态码 | 类别                             | 原因短语                   |
| -------- | ---------------------------------- | ---------------------------- |
| 1XX    | Informational（信息性状态码）    | 接收的请求正在处理         |
| 2XX    | Success（成功状态码）            | 请求正常处理完毕           |
| 3XX    | Redirection（重定向状态码）      | 需要进行附加操作以完成请求 |
| 4XX    | Client Error（客户端错误状态码） | 服务器无法处理请求         |
| 5XX    | Server Error（服务器错误状态码） | 服务器处理请求出错         |

##### 1XX

- **100 Continue** ：表明到目前为止都很正常，客户端可以继续发送请求或者忽略这个响应。

##### 2XX

- **200 OK**
- **204 No Content** ：请求已经成功处理，但是返回的响应报文不包含实体的主体部分。一般在只需要从客户端往服务器发送信息，而不需要返回数据时使用。
- **206 Partial Content** ：表示客户端进行了范围请求。响应报文包含由 Content-Range 指定范围的实体内容。

##### 3XX

- **301 Moved Permanently** ：永久性重定向
- **302 Found** ：临时性重定向
- **303 See Other** ：和 302 有着相同的功能，但是 303 明确要求客户端应该采用 GET 方法获取资源。
- 注：虽然 HTTP 协议规定 301、302 状态下重定向时不允许把 POST 方法改成 GET 方法，但是大多数浏览器都会在 301、302 和 303 状态下的重定向把 POST 方法改成 GET 方法。
- **304 Not Modified** ：如果请求报文首部包含一些条件，例如：If-Match，If-ModifiedSince，If-None-Match，If-Range，If-Unmodified-Since，如果不满足条件，则服务器会返回 304 状态码。
- **307 Temporary Redirect** ：临时重定向，与 302 的含义类似，但是 307 要求浏览器不会把重定向请求的 POST 方法改成 GET 方法。

##### 4XX

- **400 Bad Request** ：请求报文中存在语法错误。
- **401 Unauthorized** ：该状态码表示发送的请求需要有认证信息（BASIC 认证、DIGEST 认证）。如果之前已进行过一次请求，则表示用户认证失败。
- **403 Forbidden** ：请求被拒绝，服务器端没有必要给出拒绝的详细理由。
- **404 Not Found**

##### 5XX

- **500 Internal Server Error** ：服务器正在执行请求时发生错误。
- **503 Service Unavilable** ：服务器暂时处于超负载或正在进行停机维护，现在无法处理请求。

## Version

### 1.0

todo PUT DELETE not security

### 1.1

#### Connection Keepalive

```http
Connection: keep-Alive
```

[Pipelining](/docs/CS/CN/HTTP.md?id=pipelining)

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

[QUIC](/docs/CS/CN/QUIC.md)

HTTP over UDP

升级到TLS1.3 头部压缩算法QPack

基于TCP+TLS1.2需要6次握手，QUIC压缩到3次

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
For these purposes, HTTP uses cookies. Cookies, defined in [RFC 6265], allow sites to keep track of users.
Most major commercial Web sites use cookies today.

Cookie technology has four components:

1. a cookie header line in the HTTP response message
2. a cookie header line in the HTTP request message
3. a cookie file kept on theuser’s end system and managed by the user’s browser
4. a back-end database at the Web site

### Session

In the session based authentication, the server will create a session for the user after the user logs in. The session id is then stored on a cookie on the user’s browser. While the user stays logged in, the cookie would be sent along with every subsequent request. The server can then compare the session id stored on the cookie against the session information stored in the memory to verify user’s identity and sends response with the corresponding state!
session依赖于容器

解决方案

1. 集群复制 影响性能
2. 路由 固定用户固定容器 容错性不高
3. 使用中间件统一存储

多系统时可以考虑独立于其它业务系统

Cookie 优点

会话管理

行为追踪 个性定制

cookie类型

会话 - 客户端可选择 是否删除 删除后无法识别

永久 - 设置了过期条件 客户端进行持久化

```http
Set-Cookie: xxx
```

```http
Cookie: xxx
```

Cookie跨域

不同域名未使用相同Cookie

### Token

Many web applications use JSON Web Token (JWT) instead of sessions for authentication. In the token based application, the server creates JWT with a secret and sends the JWT to the client. **The client stores the JWT (usually in local storage) and includes JWT in the header with every request.** The server would then validate the JWT with every request from the client and sends response.

基于Token的身份验证是无状态的，我们不将用户信息存在服务器或Session中。

这种概念解决了在服务端存储信息时的许多问题。NoSession意味着你的程序可以根据需要去增减机器，而不用去担心用户是否登录。

基于Token的身份验证的过程如下:

- 用户通过用户名和密码发送请求。
- 程序验证。
- 程序返回一个签名的token 给客户端。
- 客户端储存token,并且每次用于每次发送请求。
- 服务端验证token并返回数据。

每一次请求都需要 token。token 应该在HTTP的头部发送从而保证了Http请求无状态。我们同样通过设置服务器属性Access-Control-Allow-Origin:* ，让服务器能接受到来自所有域的请求。需要主要的是，在ACAO头部标明(designating)*时，不得带有像HTTP认证，客户端SSL证书和cookies的证书。

#### Token验证的优势

- Scalability
- Multiple Device
- 基于标准

创建Token的时候，你可以设定一些选项。我们在后续的文章中会进行更加详尽的描述，但是标准的用法会在JSON Web Token体现。

最近的程序和文档是供给JSON Web Token的。它支持众多的语言。这意味在未来的使用中你可以真正的转换你的认证机制。

#### JWT

*[`JSON Web Token(JWT)`](https://datatracker.ietf.org/doc/rfc7519/)  is a compact, URL-safe means of representing claims to be transferred between two parties.  The claims in a JWT are encoded as a JSON object that is used as the payload of a JSON Web Signature (JWS) structure or as the plaintext of a JSON Web Encryption (JWE) structure, enabling the claims to be digitally signed or integrity protected with a Message Authentication Code (MAC) and/or encrypted.*

可以在服务端验证

可以跨域认证

ensure only the necessary information is included in JWT and sensitive information should be omitted to prevent XSS security attacks.

用途：

- 授权：这是使用JWT的最常见方案。一旦用户登录，每个后续请求将包括JWT，从而允许用户访问该令牌允许的路由，服务和资源。单一登录是当今广泛使用JWT的一项功能，因为它的开销很小并且可以在不同的域中轻松使用。
- 信息交换：JSON Web令牌是在各方之间安全地传输信息的好方法。因为可以对JWT进行签名（例如，使用公钥/私钥对），所以您可以确定发件人是他们所说的人。另外，由于签名是使用标头和有效负载计算的，因此您还可以验证内容是否未被篡改。

结构：
JSON Web令牌以紧凑的形式由三部分组成，这些部分由点（.）分隔，分别是：

- Header 标头
  - 通常由两部分组成：令牌的类型（即JWT）和所使用的签名算法
- Payload
- Signature
  - 通过payload和secret使用Header指定算法生成

### Session vs Token

- Session存储在服务端
  - 不能跨域
- Token
  - 可让客户端存储
  - 无状态、可扩展
  - 支持移动设备
  - 跨程序调用
  - 安全
  - much bigger comparing with the session id stored in cookie

## Security

(Cross-Origin Resource Sharing)CORS跨域

## Performance

[WebPageTest](https://www.webpagetest.org)

[H2O](https://h2o.examp1e.net/)

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [DNS](/docs/CS/CN/DNS.md)
- [WebSocket](/docs/CS/CN/WebSocket.md)

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
