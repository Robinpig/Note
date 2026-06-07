## 简介

[超文本传输协议](https://www.w3.org/Protocols/)（HTTP）是一种应用级协议，具有分布式、协作式超媒体信息系统所需的轻量和速度。
它设计用于 Web 浏览器和 Web 服务器之间的通信，但也可用于其他目的。
HTTP 遵循经典的客户端-服务器模型，客户端打开连接发出请求，然后等待直到收到响应。

它是一种通用的、无状态的协议，通过扩展其请求方法、错误码和头部，可用于超文本之外的许多任务，
例如名称服务器和分布式对象管理系统。
HTTP 的一个特性是数据表示的 typing 和协商，允许系统独立于被传输的数据构建。

> [!NOTE]
>
> 参见 [HTTPS](/docs/CS/CN/TLS.md)

1. 明文
2. HTTP 是无状态协议，意味着服务器在两个请求之间不保留任何数据（状态）。
    但虽然 HTTP 本身是无状态的，HTTP Cookie 允许使用有状态会话。利用头部可扩展性，HTTP Cookie 被添加到工作流中，允许在每个 HTTP 请求上创建会话以共享相同上下文或相同状态。
3. 不确定报文是否正常，未被篡改
4. 性能不算高

## HTTP 消息

消息结构：
- 头部（Header）
  - 起始行（start line）
  - 头部（header）
- CR+LF
- 内容（Content）

大容量数据使用 Chunked Transfer Coding

多种数据多部分对象集合

**MIME（多用途互联网邮件扩展）**

multipart/form-data

传输恢复 Range Request

内容协商机制

Content Negotiation

请求（request）

请求行（request row）

方法 URI HTTP 版本

```http
GET / HTTP/1.1
```

### 请求

从客户端到服务器的请求消息，在该消息的第一行中包括要应用于资源的
方法、资源标识符和使用的协议版本。

```
        Request       = Request-Line  
                        *(( general-header  
                         | request-header   
                         | entity-header ) CRLF)  
                        CRLF
                        [ message-body ]  
```

#### 请求行

> [!NOTE]
>
> Request-Line   = Method SP Request-URI SP HTTP-Version CRLF

### 响应

接收并解释请求消息后，服务器响应
HTTP 响应消息。

```
       Response      = Status-Line   
                       *(( general-header  
                        | response-header  
                        | entity-header ) CRLF)  
                       CRLF
                       [ message-body ]  
```

#### 状态行

> [!NOTE]
>
> Status-Line = HTTP-Version SP Status-Code SP Reason-Phrase CRLF

例如：

```http
HTTP/1.1 304 Not Modified
```

HTTP 状态码由三个十进制数字组成，第一个十进制数字定义了状态码的类型。
响应分为五类：信息响应(100–199)，成功响应(200–299)，重定向(300–399)，客户端错误(400–499)和服务器错误 (500–599)

HTTP状态码列表:

| 状态码 | 状态码英文名称 | 中文描述 |
|-------| --- |-----------------------------------------------------------|
| 500 | Internal Server Error | 服务器内部错误，无法完成请求 |
| 501 | Not Implemented | 服务器不支持请求的功能，无法完成请求 |
| 502 | Bad Gateway | 作为网关或者代理工作的服务器尝试执行请求时，从远程服务器接收到了一个无效的响应 例如服务器执行超时TCP异常导致 |
| 503 | Service Unavailable | 由于超载或系统维护，服务器暂时的无法处理客户端的请求。延时的长度可包含在服务器的Retry-After头信息中 |
| 504 | Gateway Time-out | 充当网关或代理的服务器，未及时从远端服务器获取请求 |
| 505 | HTTP Version not supported | 服务器不支持请求的HTTP协议的版本，无法完成处理 |

### HTTP 头部

Zip

- gzip
- br for html

"Transfer-Encoding: chunked"和"Content-Length"这两个字段是互斥的

Accept-Ranges: bytes
Range: bytes=0-31

Content-Range

multipart/byteranges

常用的下载工具里的多段下载、断点续传也是基于它实现的，要点是：

先发个 HEAD，看服务器是否支持范围请求，同时获取文件的大小；
开 N 个线程，每个线程使用 Range 字段划分出各自负责下载的片段，发请求传输数据；
下载意外中断也不怕，不必重头再来一遍，只要根据上次的下载记录，用 Range 请求剩下的那一部分就可以了。

### 连接管理

#### 管道化

支持持久连接的客户端可以"管道化"其请求（即发送多个请求而不等待每个响应）。
如果所有请求方法都是安全的，服务器可以并行处理一系列管道化请求，**但必须以请求接收的相同顺序发送相应的响应**。

> [!TIP]
>
> 管道化解决了请求的 HOL 阻塞，但不解决响应的。

管道化请求的客户端应在连接关闭之前未收到所有相应响应时重试未应答的请求。
在失败的连接后重试管道化请求时（服务器在其最后一个完整响应中未显式关闭的连接），客户端不得在连接建立后立即管道化，
因为先前管道中的第一个剩余请求可能已导致错误响应，如果在过早关闭的连接上发送多个请求，该错误响应可能再次丢失（参见 *TCP 重置问题*）。

> [!NOTE]
>
> **TCP 重置问题（TCP Reset Problem）**
>
> 如果服务器立即关闭 TCP 连接，客户端很可能无法读取最后一个 HTTP 响应。
> 如果服务器在完全关闭的连接上从客户端接收到额外数据，例如客户端在收到服务器响应之前发送的另一个请求，
> 服务器的 TCP 栈将向客户端发送重置数据包；不幸的是，重置数据包可能会在客户端的 HTTP 解析器读取和解释之前擦除其未确认的输入缓冲区。
>
> 为避免 TCP 重置问题，服务器通常分阶段关闭连接。
>
> - 首先，服务器通过仅关闭读/写连接的写半部执行半关闭。
>   然后服务器继续从连接读取，直到收到客户端的相应关闭，或者直到服务器合理确信其自己的 TCP 栈已收到客户端对包含服务器最后一个响应的数据包的确认。
> - 最后，服务器完全关闭连接。

幂等方法（Idempotent methods）对管道化很重要，因为它们在连接失败后可以自动重试。
在非幂等方法之后，用户代理不应管道化请求，直到收到该方法的最终响应状态码，除非用户代理有办法检测和恢复涉及管道化序列的部分失败条件。

接收管道化请求的中介在转发这些请求时可能会管道化它们，因为它可以依赖出站用户代理来确定哪些请求可以安全地管道化。
如果在收到响应之前入站连接失败，管道化中介可以尝试重试尚未收到响应的请求序列，如果这些请求都具有幂等方法；
否则，管道化中介应转发任何已收到的响应，然后关闭相应的出站连接，以便出站用户代理能够相应恢复。

- 首先，某些可以增量处理/渲染的文件确实受益于多路复用。例如渐进式图像就是这种情况。
- 其次，如上所述，如果某个文件比其他文件小得多，它会更早被下载，同时不会过多延迟其他文件。
- 第三，**多路复用允许更改响应的顺序，并为更高优先级的响应中断低优先级的响应。**

[Chromium Remove HTTP pipelining support.](https://codereview.chromium.org/275953002)

#### 并发

客户端应限制其维护到给定服务器的同时打开连接数量。

HTTP 的先前版本给出了一个特定连接数作为上限，但这被发现对许多应用不实用。
因此，本规范不强制定最大连接数，而是鼓励客户端在打开多个连接时保持保守。

多个连接通常用于避免["队头阻塞"](/docs/CS/CN/HTTP/HOL.md?id=HTTP)问题，其中需要大量服务器端处理和/或具有大有效载荷的请求会阻塞同一连接上的后续请求。
然而，每个连接都消耗服务器资源。此外，在拥塞的网络中使用多个连接可能导致不良的副作用。

注意，服务器可能会拒绝其认为滥用或具有拒绝服务攻击特征的流量，例如来自单个客户端的过多打开连接。

## 请求方法

### 方法定义

如果对服务器发出单个请求的预期效果与发出多个相同请求的效果相同，则 HTTP 方法是**幂等的**。

这不一定意味着请求没有*任何*独特的副作用：例如，服务器可能记录每个请求及其接收时间。幂等性仅适用于客户端预期的效果：例如，POST 请求意图向服务器发送数据，或 DELETE 请求意图删除服务器上的资源。

要成为幂等的，只考虑服务器的状态。每个请求返回的响应可能不同：例如，第一次调用 [`DELETE`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/DELETE) 可能返回 [`200`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/200)，而后续调用可能返回 [`404`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404)。[`DELETE`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/DELETE) 是幂等的另一个含义是，开发者不应使用 `DELETE` 方法实现*删除最后一项*功能的 RESTful API。

如果不改变服务器的状态，则 HTTP 方法是**安全的**。换句话说，如果方法导致只读操作，则该方法是安全的。
所有安全方法也是[幂等的](https://developer.mozilla.org/en-US/docs/Glossary/Idempotent)，但并非所有幂等方法都是安全的。

即使安全方法具有只读语义，服务器也可以改变其状态：例如，它们可以记录或保持统计信息。这里重要的是，通过调用安全方法，客户端本身不请求任何服务器更改，因此不会对服务器造成不必要的负载或负担。浏览器可以调用安全方法而不必担心对服务器造成任何损害；这使得它们能够执行预取等活动而无需承担风险。Web 爬虫也依赖调用安全方法。

安全方法不需要仅服务于静态文件；服务器可以动态生成对安全方法的回答，只要生成脚本保证安全性：它不应触发外部效果，如触发电子商务网站上的订单。

正确实现安全语义是服务器上应用的责任，Web 服务器本身（Apache、Nginx 或 IIS）无法自行强制执行。特别是，应用不应允许 [`GET`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/GET) 请求更改其状态。

| 方法 | 幂等性 | 安全性（只读） |
| --------- | ------ | ------ |
| OPTIONS   | 是    | 是    |
| GET       | 是    | 是    |
| HEAD      | 是    | 是    |
| PUT       | 是    | 否     |
| DELETE    | 是    | 否     |
| POST      | 否     | 否     |
| PATCH     | 否     | 否     |

### HTTP 状态码

[HTTP Code](https://zh.wikipedia.org/wiki/HTTP%E7%8A%B6%E6%80%81%E7%A0%81)

## 版本

### 1.0

todo PUT DELETE not security

### 1.1

#### 连接保活

```http
Connection: keep-Alive
```

[管道化](/docs/CS/CN/HTTP/HTTP.md?id=pipelining)

### HTTP/2

HTTP/2 标准基于 SPDY，进行了一些改进。
HTTP/2 通过使用**二进制消息帧**实现了更高效的消息处理。

#### HTTP 帧

HTTP/2 通过在单个打开的 TCP 连接上多路复用 HTTP 请求，解决了队头阻塞问题。

HTTP/2 通过在资源块前添加称为**帧**的小型控制消息来优雅地解决这个问题。
通过对单个消息进行"帧化"，HTTP/2 比 HTTP/1.1 灵活得多。
它允许通过交错块，在单个 TCP 连接上多路复用多个资源。

HTTP/2 方法的一个重要后果是，我们突然也需要一种方式让浏览器向服务器传达它希望如何在资源之间分配单个连接的带宽。
换句话说：资源块应如何被"调度"或交错。
如果我们再次用 1 和 2 来可视化，我们看到对于 HTTP/1.1，唯一的选择是 11112222（我们称之为顺序）。
然而 HTTP/2 有更多自由：

- 公平多路复用（例如两个渐进式 JPEG）：12121212
- 加权多路复用（2 的重要性是 1 的两倍）：221221221
- 反向顺序调度（例如 2 是关键的服务器推送资源）：22221111
- 部分调度（流 1 被中止，未完全发送）：112222

使用哪种调度由 HTTP/2 中所谓的"优先级"系统驱动，选择的方法可能对 Web 性能产生重大影响。

HTTP/2 还允许压缩请求头部以及请求体，这进一步减少了在线路上传输的数据量。

#### HTTP2 over TLS

下一代协议协商（NPN）是用于与 TLS 服务器协商 SPDY 的协议。
由于它不是适当的标准，它被提交给 IETF，结果产生了 ALPN：应用层协议协商（Application Layer Protocol Negotiation）。
ALPN 被推广用于 http2，而 SPDY 客户端和服务器仍然使用 NPN。

NPN 首先存在，而 ALPN 经过一段时间才完成标准化，这导致许多早期的 http2 客户端和 http2 服务器在协商 http2 时实现并使用这两种扩展。
此外，NPN 用于 SPDY，许多服务器同时提供 SPDY 和 http2，因此在这些服务器上支持 NPN 和 ALPN 非常合理。

ALPN 与 NPN 的主要区别在于谁决定使用哪种协议。
使用 ALPN，客户端按偏好顺序向服务器提供协议列表，服务器选择它想要的一个，而使用 NPN，客户端做出最终选择。

#### HPACK

[HPACK](https://www.rfc-editor.org/rfc/rfc7541.txt) 设计为使符合规范的实现难以泄露信息，使编码和解码非常快速/廉价，
为接收方提供对压缩上下文大小的控制，允许代理重新索引（即代理内前端和后端之间的共享状态），以及快速比较 Huffman 编码的字符串。

HPACK 是 HTTP/2.0 为了降低 HTTP payload 大小从而提高传输效率的杀招，应用了静态表、动态表和哈夫曼编码三种技术，把冗余的 HTTP 头信息大大压缩

#### 重置

HTTP 1.1 的缺点之一是，当具有特定 Content-Length 大小的 HTTP 消息已发送后，你无法轻易停止它。当然，你通常可以（但并非总是）断开 TCP 连接，但这需要重新进行 TCP 握手的代价。
更好的解决方案是直接停止消息并重新开始。这可以通过 http2 的 RST_STREAM 帧实现，这有助于防止带宽浪费并避免需要断开连接。

#### 服务器推送

此功能也称为"缓存推送"。其思想是，如果客户端请求资源 X，服务器可能知道客户端可能还需要资源 Z，并在未被请求的情况下将其发送给客户端。它通过将 Z 放入客户端缓存来帮助客户端，以便客户端需要时它已在那里。
服务器推送是客户端必须显式允许服务器执行的操作。即便如此，客户端可以在任何时候使用 RST_STREAM 快速终止推送的流，如果它不想要特定资源。

#### 流控制

每个 http2 流都有自己通告的流窗口，允许对端发送数据。如果你碰巧知道 SSH 的工作原理，这在风格和精神上非常相似。
对于每个流，两端都必须告诉对端它有足够的空间处理传入数据，并且对端只能发送那么多数据，直到窗口被扩展。只有 DATA 帧受流控制。

### HTTP/3

HTTP over [QUIC](/docs/CS/CN/HTTP/QUIC.md)

## URI

URI（统一资源标识符）

URL（统一资源定位符）

代理（Proxy）

缓存（Cache）

## 状态管理机制

HTTP 是无状态的。

为了克服 HTTP 请求的无状态特性，我们可以使用会话（session）或令牌（token）。

### Cookies

Web 站点通常希望标识用户，要么是因为服务器希望限制用户访问，要么是因为它想根据用户身份提供内容。
出于这些目的，HTTP 使用 Cookie。
[RFC 6265](https://datatracker.ietf.org/doc/rfc6265/) 定义了 HTTP Cookie 和 Set-Cookie 头字段。
这些头字段可以被 HTTP 服务器用来在 HTTP 用户代理上存储状态（称为 cookie），让服务器在基本上无状态的 HTTP 协议上维护有状态会话。
尽管 Cookie 有许多历史缺陷降低了其安全性和隐私性，但 Cookie 和 Set-Cookie 头字段在互联网上被广泛使用。

为了存储状态，源服务器在 HTTP 响应中包含 Set-Cookie 头。
在后续请求中，用户代理向源服务器返回 Cookie 请求头。
Cookie 头包含用户代理在之前的 Set-Cookie 头中接收到的 cookie。
源服务器可以自由忽略 Cookie 头或将其内容用于应用定义的目的。

源服务器可以在任何响应中发送 Set-Cookie 响应头。
用户代理可以忽略包含在 100 级状态码的响应中的 Set-Cookie 头，但必须处理其他响应（包括包含 400 和 500 级状态码的响应）中的 Set-Cookie 头。
源服务器可以在单个响应中包含多个 Set-Cookie 头字段。
Cookie 或 Set-Cookie 头字段的存在不阻止 HTTP 缓存存储和重用响应。

源服务器不应将多个 Set-Cookie 头字段折叠到单个头字段中。
折叠 HTTP 头字段的通常机制可能改变 Set-Cookie 头字段的语义，因为 %x2C（","）字符在 Set-Cookie 中的使用与此类折叠冲突。

Cookie 技术有四个组件：

1. HTTP 响应消息中的 cookie 头行
2. HTTP 请求消息中的 cookie 头行
3. 用户终端系统上维护并由用户浏览器管理的 cookie 文件
4. Web 站点的后端数据库

#### 安全

Cookie 有许多安全缺陷。本节概述了一些更突出的问题。

特别是，Cookie 鼓励开发者依赖 ambient authority 进行认证，通常容易受到跨站请求伪造 [CSRF] 等攻击。
此外，当在 Cookie 中存储会话标识符时，开发者常常创建会话固定漏洞。

传输层加密（如 HTTPS 中使用的）不足以防止网络攻击者获取或更改受害者的 Cookie，因为 Cookie 协议本身存在各种漏洞（参见下文"弱机密性"和"弱完整性"）。
此外，默认情况下，即使与 HTTPS 结合使用，Cookie 也不提供针对网络攻击者的机密性或完整性。

除非通过安全通道（如 TLS）发送，否则 Cookie 和 Set-Cookie 头中的信息以明文传输。

1. 这些头中传输的所有敏感信息都暴露给窃听者。
2. 恶意中介可以在任一侧更改这些头，产生不可预测的结果。
3. 恶意客户端可以在传输前更改 Cookie 头，产生不可预测的结果。

服务器不是将会话信息直接存储在 Cookie 中（可能被攻击者暴露或重放），而是常在 Cookie 中存储随机数（或"会话标识符"）。
当服务器接收到带有随机数的 HTTP 请求时，服务器可以使用该随机数作为键查找与 Cookie 关联的状态信息。

##### 弱机密性和弱完整性

- Cookie 不提供按端口的隔离。
- Cookie 不提供按协议的隔离。
- Cookie 不总是提供按路径的隔离。
- Cookie 不为兄弟域（及其子域）提供完整性保证。

### Json Web Token

JSON Web Token（JWT）是一种紧凑的声明表示格式，适用于空间受限的环境，如 HTTP Authorization 头和 URI 查询参数。
JWT 将要传输的声明编码为 JSON 对象，作为 JSON Web Signature（JWS）结构的有效载荷或 JSON Web Encryption（JWE）结构的明文，
使声明能够通过消息认证码（MAC）进行数字签名或完整性保护，以及/或加密。
JWT 始终使用 JWS 紧凑序列化或 JWE 紧凑序列化表示。

以下是 JSON Web Token 有用的一些场景：

- **授权（Authorization）**：这是使用 JWT 最常见的场景。
  一旦用户登录，每个后续请求将包含 JWT，允许用户访问该令牌允许的路由、服务和资源。
  单点登录（Single Sign On）是如今广泛使用 JWT 的一个特性，因为其开销小且易于在不同域间使用。
- **信息交换（Information Exchange）**：JSON Web Tokens 是在各方之间安全传输信息的好方式。
  由于 JWT 可以被签名（例如使用公/私钥对），你可以确保发送方是他们声称的人。
  此外，由于签名是使用头部和有效载荷计算的，你还可以验证内容未被篡改。

> [RFC 7519 - JSON Web Token (JWT)](https://datatracker.ietf.org/doc/rfc7519/)
> [RFC 7797 - JSON Web Signature (JWS) Unencoded Payload Option](https://datatracker.ietf.org/doc/rfc7797/)
> [RFC 8725 - JSON Web Token Best Current Practices](https://datatracker.ietf.org/doc/rfc8725/)

#### 结构

头部

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

有效载荷

```json
{
  "sub": "1234567890",
  "name": "John Doe",
  "iat": 1516239022
}
```

签名

参见 [JWT.IO](https://jwt.io/)。

在认证中，当用户使用其凭据成功登录时，将返回 JSON Web Token。
由于令牌是凭据，必须非常小心以防止安全问题。一般来说，你不应保留令牌超过所需时间。

由于缺乏安全性，你也不应将敏感会话数据存储在浏览器存储中。

每当用户想要访问受保护的路由或资源时，用户代理应发送 JWT，通常在 Authorization 头中使用 Bearer 方案。
头的内容应如下所示：

```http
Authorization: Bearer <token>
```

在某些情况下，这可以是一种无状态授权机制。
服务器的受保护路由将检查 Authorization 头中的有效 JWT，如果存在，用户将被允许访问受保护的资源。
如果 JWT 包含必要的数据，可以减少对数据库进行某些操作的查询需求，尽管并非总是如此。

如果令牌在 Authorization 头中发送，跨域资源共享（CORS）不会成为问题，因为它不使用 Cookie。

请注意，对于签名的令牌，令牌中包含的所有信息都暴露给用户或其他方，即使他们无法更改它。
这意味着你不应将秘密信息放在令牌中。

## 安全

[HTTP Security](/docs/CS/CN/HTTP/Security.md)

## 性能

[WebPageTest](https://www.webpagetest.org)

[H2O](https://h2o.examp1e.net/)

## 链接

- [计算机网络](/docs/CS/CN/CN.md)
- [DNS](/docs/CS/CN/DNS.md)
- [WebSocket](/docs/CS/CN/WebSocket.md)
- [OAuth](/docs/CS/CN/HTTP/OAuth.md)

## 参考文献

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
