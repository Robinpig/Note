## Introduction

[Hypertext Transfer Protocol](https://www.w3.org/Protocols/)（HTTP）是一种应用层协议，轻量、快速，专为分布式协作的超媒体信息系统而设计。
它最初面向浏览器与 Web 服务器之间的通信，但也可用于其他场景。
HTTP 遵循经典的客户端-服务器模型：客户端建立连接、发出请求，然后等待接收响应。

HTTP 是一种通用的、无状态的协议；除超文本传输外，还可通过扩展请求方法、错误码和头部，胜任名称服务器、分布式对象管理系统等许多任务。
HTTP 的一大特性是数据表示的定型与协商（typing and negotiation），使系统构建与所传输的具体数据相互独立。

> [!NOTE]
>
> 参见 [TLS](/docs/CS/CN/TLS.md)

1. 明文传输
2. HTTP 是无状态协议，即服务器不会在两次请求之间保留任何数据（状态）。
   不过 HTTP 核心虽是无状态的，HTTP Cookie 借助头部扩展机制实现了有状态会话：每个 HTTP 请求都带上 Cookie，使一系列请求共享同一上下文（即同一状态）。
3. 不确定报文是否正常，未被篡改
4. 性能不算高

## HTTP Message

报文结构：

- 首部
  - 起始行
  - 首部字段
- CR+LF
- 消息正文

大容量数据使用 Chunked Transfer Coding

多种数据多部分对象集合

**MIME(Multipurpose Internet Mail Extensions)**

multipart/form-data

传输恢复 Range Request

内容协商机制

Content Negotiation

请求行的格式为：

```
method URI HTTP version
```

```http
GET / HTTP/1.1
```

### Request

客户端发给服务器的请求报文，其首行包含三项内容：要应用于资源的方法（method）、资源的标识符（URI）以及所使用的协议版本。

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

RFC 原文：请求行由「方法 SP 请求 URI SP HTTP 版本 CRLF」组成，SP 为单个空格。

### Response

服务器接收并解析请求报文后，会回以 HTTP 响应报文。

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

RFC 原文：状态行由「HTTP 版本 SP 状态码 SP 原因短语 CRLF」组成。

例如：

```http
HTTP/1.1 304 Not Modified
```


HTTP 状态码由三个十进制数字组成，第一个十进制数字定义了状态码的类型。
响应分为五类：信息响应(100–199)，成功响应(200–299)，重定向(300–399)，客户端错误(400–499)和服务器错误 (500–599)

HTTP状态码列表:

| 状态码 	 | 状态码英文名称 | 	中文描述                                                     |
|-------| --- |-----------------------------------------------------------|
| 500   |	Internal Server Error | 	服务器内部错误，无法完成请求                                           |
| 501   |	Not Implemented  | 	服务器不支持请求的功能，无法完成请求                                       |
| 502   |	Bad Gateway  | 	作为网关或者代理工作的服务器尝试执行请求时，从远程服务器接收到了一个无效的响应 例如服务器执行超时TCP异常导致 |
| 503   |	Service Unavailable | 	由于超载或系统维护，服务器暂时的无法处理客户端的请求。延时的长度可包含在服务器的Retry-After头信息中  |
| 504   |	Gateway Time-out | 	充当网关或代理的服务器，未及时从远端服务器获取请求                                |
| 505   |	HTTP Version not supported | 	服务器不支持请求的HTTP协议的版本，无法完成处理                                |



### HTTP Header

内容压缩编码：

- gzip
- br（用于 html）

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

支持持久连接的客户端可以「流水线化」（pipeline）其请求，即不等每个响应回来就连发多个请求。
如果一组流水线请求使用的都是安全方法，服务器可以并行处理它们，**但 MUST 按照收到请求的相同顺序发出相应的响应**。

> [!TIP]
>
> 流水线化解决了请求侧的队头阻塞，但没有解决响应侧的。

如果连接在收到全部响应之前关闭，流水线发送请求的客户端 SHOULD 重试那些未得到响应的请求。
在连接失败后重试流水线请求时（失败指服务器未在最后一个完整响应中显式关闭连接），客户端 MUST NOT 在连接刚建立后就立即再次流水线发送：
因为前一条流水线中剩余的第一个请求可能已经引发了一个错误响应，若在过早关闭的连接上批量重发，该错误响应可能再次丢失（参见 *TCP reset problem*）。

> [!NOTE]
>
> **TCP 重置问题（TCP Reset Problem）**
>
> 如果服务器立即关闭 TCP 连接，客户端很可能来不及读取最后一个 HTTP 响应。
> 如果服务器在一个已完全关闭的连接上又收到客户端发来的数据——比如客户端在收到服务器响应前发出的另一个请求——服务器的 TCP 栈会向客户端发送重置（reset）报文；
> 不幸的是，这个重置报文可能在客户端的 HTTP 解析器读取并解释那些未确认的输入缓冲区之前，就把它们清掉了。
>
> 为避免 TCP 重置问题，服务器通常分阶段关闭连接。
>
> - 首先，服务器执行半关闭（half-close），只关闭读写连接中的写方向。
>   然后继续从连接读取数据，直到收到客户端相应的关闭，或者直到服务器有充分把握：自己的 TCP 栈已收到客户端对包含最后一个响应的报文的确认。
> - 最后，服务器完全关闭连接。

幂等方法对流水线化意义重大，因为连接失败后它们可以被自动重试。
除非用户代理有办法检测并从涉及流水线序列的部分失败中恢复，否则在非幂等方法之后、收到该方法的最终响应状态码之前，用户代理 SHOULD NOT 流水线发送请求。

收到流水线请求的中介在向内转发时 MAY 继续流水线发送，因为它可以依赖外侧的用户代理来判断哪些请求可以安全地流水线化。
如果入站连接在收到响应前失败，且这批尚未得到响应的请求全部使用幂等方法，流水线中介 MAY 尝试重试；
否则，流水线中介 SHOULD 先转发已收到的响应，再关闭相应的出站连接，让外侧的用户代理自行恢复。

多路复用（multiplexing）的收益主要体现在三方面：

- 其一，可以增量处理或渲染的文件确实受益于多路复用，渐进式图片（progressive images）就是典型例子。
- 其二，当其中一个文件远小于其他文件时也很有用：小文件可以先下载完，同时不会把其他文件拖慢太多。
- 其三，**多路复用允许改变响应顺序，并中断低优先级的响应，优先发送高优先级响应。**

[Chromium 移除 HTTP 流水线支持](https://codereview.chromium.org/275953002)

#### Concurrency

客户端应当限制自己对同一服务器同时保持打开的连接数。

HTTP 的早期修订版曾把连接数上限写成一个具体数字，但实践证明这对许多应用并不现实。
因此，现行规范不再规定最大连接数，而是建议客户端在开设多条连接时保持克制。

多连接通常用来规避[「队头阻塞」](/docs/CS/CN/HTTP/HOL.md?id=http)问题：同一连接上，一个需要大量服务端处理或载荷很大的请求会阻塞后续请求。
但每条连接都会消耗服务器资源；此外，在拥塞网络中使用多条连接还可能带来负面副作用。

注意，服务器可能拒绝它认定为滥用或类似拒绝服务攻击（DoS）的流量，例如来自单个客户端的过多并发连接。

## Request Methods

### Method Definitions

如果一个请求对服务器的预期效果，与发送多个相同请求的效果相同，则该 HTTP 方法是**幂等（idempotent）**的。

这并不意味着请求没有任何独特副作用：例如，服务器可以记录每个请求的接收时间。幂等性只适用于客户端意图产生的效果——例如 POST 意在把数据发送给服务器，DELETE 意在删除服务器上的某个资源。

判断幂等时只考虑服务器的状态，每次请求返回的响应可以不同：例如第一次调用 [`DELETE`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/DELETE) 多半返回 [`200`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/200)，后续调用则多半返回 [`404`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404)。由 [`DELETE`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/DELETE) 的幂等性还可以推出：开发者不应该用 `DELETE` 方法去实现 RESTful API 的「删除最后一条记录」功能。

如果一个 HTTP 方法不改变服务器状态，它就是**安全（safe）**的；换句话说，安全的方法对应只读操作。
所有安全方法都是[幂等](https://developer.mozilla.org/en-US/docs/Glossary/Idempotent)的，但并非所有幂等方法都安全。

即使安全方法语义上是只读的，服务器仍然可以改变自身状态，比如记录日志或做统计。关键在于：调用安全方法时，客户端本身没有请求服务器做任何改变，因此不会给服务器带来不必要的负载。浏览器可以放心调用安全方法而不必担心伤害服务器，因此能无风险地执行预取（pre-fetching）之类的操作；网络爬虫也依赖调用安全方法。

安全方法也不一定只能提供静态文件：服务器完全可以动态生成安全方法的响应，只要生成逻辑自身保证安全——不应触发外部副作用，比如在电商网站上真的提交一个订单。

正确实现安全语义是服务器端应用的责任，Web 服务器本身（无论是 Apache、Nginx 还是 IIS）都无法代为强制执行。特别地，应用不应该允许 [`GET`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/GET) 请求改变自己的状态。

| 方法 | 幂等性 | 安全性（只读） |
| --------- | ------ | ------ |
| OPTIONS   | 是    | 是    |
| GET       | 是    | 是    |
| HEAD      | 是    | 是    |
| PUT       | 是    | 否     |
| DELETE    | 是    | 否     |
| POST      | 否     | 否     |
| PATCH     | 否     | 否     |


### HTTP Status Code

[HTTP 状态码](https://zh.wikipedia.org/wiki/HTTP%E7%8A%B6%E6%80%81%E7%A0%81)

## Version

### 1.0

todo：PUT、DELETE 非安全方法

### 1.1

#### Connection Keepalive

```http
Connection: keep-Alive
```

[流水线化（Pipelining）](/docs/CS/CN/HTTP/HTTP.md?id=pipelining)

### HTTP/2

HTTP/2 标准以 SPDY 为基础并做了若干改进。
HTTP/2 通过**二进制分帧（binary message framing）**实现更高效的报文处理。

#### HTTP Frames

HTTP/2 通过在单条 TCP 连接上多路复用 HTTP 请求，消除了 HTTP 层的队头阻塞（注意：TCP 层的队头阻塞依然存在，详见 [HOL](/docs/CS/CN/HTTP/HOL.md)）。

HTTP/2 的解法相当优雅：在资源分片之前加上小的控制消息，称为**帧（frame）**。
通过给每条消息「分帧」，HTTP/2 比 HTTP/1.1 灵活得多：
它允许多个资源的分片在单条 TCP 连接上交错发送，实现多路复用。

这一做法带来一个重要后果：我们还需要一种机制，让浏览器告诉服务器，它希望单条连接的带宽如何在各资源之间分配。
换句话说，就是资源分片应当如何「调度」或交错发送。
继续用 1 和 2 来可视化：HTTP/1.1 下唯一的选择是 11112222（顺序发送），而 HTTP/2 的自由度大得多：

- 公平多路复用（例如两张渐进式 JPEG）：12121212
- 加权多路复用（2 的重要性是 1 的两倍）：221221221
- 逆序调度（例如 2 是关键的服务端推送资源）：22221111
- 部分调度（流 1 被中止，未完整发送）：112222

具体采用哪种由 HTTP/2 的「优先级（prioritization）」系统决定，不同选择对 Web 性能影响很大。

HTTP/2 还支持在压缩请求体之外压缩请求头，进一步减少线上传输的数据量。

#### HTTP2 over TLS

NPN（Next Protocol Negotiation）是早期用于与 TLS 服务器协商 SPDY 的协议。
由于它并非正式标准，IETF 将其接管并标准化，成果就是 ALPN（Application Layer Protocol Negotiation，应用层协议协商）。
ALPN 被推广用于 http2，而 SPDY 的客户端和服务器仍在使用 NPN。

NPN 先出现、ALPN 又花了较长时间走完标准化流程，导致许多早期 http2 客户端和服务器在协商 http2 时同时实现并启用了这两个扩展。
另外，SPDY 用的就是 NPN，而很多服务器同时提供 SPDY 和 http2，所以这些服务器同时支持 NPN 与 ALPN 是完全合理的。

ALPN 与 NPN 的主要区别在于由谁决定最终使用哪个协议：
ALPN 中，客户端按偏好顺序给出协议列表，由服务器挑选；NPN 中，则由客户端做最终选择。


#### HPACK

[HPACK](https://www.rfc-editor.org/rfc/rfc7541.txt) 的设计目标包括：让合规实现难以泄漏信息、让编解码非常快且开销低、让接收端能控制压缩上下文大小、支持代理重新索引（即代理内部前端与后端之间的共享状态），以及便于对哈夫曼编码字符串做快速比较。

HPACK 是 HTTP/2.0 为了降低 HTTP payload 大小从而提高传输效率的杀招，应用了静态表、动态表和哈夫曼编码三种技术，把冗余的 HTTP 头信息大大压缩


#### Reset

HTTP/1.1 的一个缺点是：一个声明了 Content-Length 的 HTTP 报文一旦发出去，就不容易叫停。当然，你通常可以（但不总是可以）直接断开 TCP 连接，但代价是得重新走一遍 TCP 握手。
更好的做法是直接中止这条消息、重新开始——http2 的 RST_STREAM 帧就能做到，既避免浪费带宽，也不必拆除连接。

#### Server push

这个特性也叫「缓存推送（cache push）」：客户端请求资源 X 时，服务器可能判断客户端多半还会需要资源 Z，于是不等客户端开口就先把 Z 发过去，并放进客户端缓存，等客户端真正需要时即可直接命中。
服务端推送必须得到客户端显式允许。即便如此，客户端只要不想要某个被推送的资源，随时可以用 RST_STREAM 迅速终止对应的推送流。

#### Flow Control

每个 http2 流都有自己通告的流量窗口（flow window），对端只允许发送窗口以内的数据。如果你了解 SSH 的工作方式，会发现二者在风格和精神上非常相似。
对每个流，两端都必须告知对端自己还有多少空间接收数据；在窗口扩大之前，对端只能发送相应数量的数据。只有 DATA 帧受流量控制。

### HTTP/3

HTTP/3 即 HTTP over [QUIC](/docs/CS/CN/HTTP/QUIC.md)：把 HTTP 语义搬到 QUIC 之上，从根本上消除传输层的队头阻塞。

## URI

URI（Uniform Resource Identifier，统一资源标识符）

URL（Uniform Resource Locator，统一资源定位符）

代理（Proxy）

缓存（Cache）

## State Management Mechanism

HTTP 是无状态的。

为了克服 HTTP 请求的无状态性，可以使用会话（session）或令牌（token）两种机制。

### Cookies

网站经常需要识别用户身份——要么是为了限制访问，要么是想根据用户身份提供不同内容。为此，HTTP 使用了 Cookie。
[RFC 6265](https://datatracker.ietf.org/doc/rfc6265/) 定义了 Cookie 和 Set-Cookie 两个头部字段。
服务器可以用它们在用户代理上保存状态（即 Cookie），从而在基本无状态的 HTTP 协议之上维持有状态会话。
尽管 Cookie 有不少削弱安全与隐私的历史遗留缺陷，这两个字段在互联网上仍被广泛使用。

存储状态的具体流程是：源服务器在 HTTP 响应中带上 Set-Cookie 头；后续请求中，用户代理再把 Cookie 请求头回传给源服务器，其中包含它此前从 Set-Cookie 头收到的所有 Cookie。源服务器可以忽略 Cookie 头，也可以按应用自定义的用途使用其内容。

源服务器 MAY 在任意响应中发送 Set-Cookie 响应头。
用户代理 MAY 忽略 100 级状态码响应中的 Set-Cookie 头，但 MUST 处理其他响应（包括 400、500 级）中的 Set-Cookie 头。
一个响应中可以包含多个 Set-Cookie 头字段。
响应中是否存在 Cookie 或 Set-Cookie 字段，并不妨碍 HTTP 缓存存储并复用该响应。

源服务器 SHOULD NOT 把多个 Set-Cookie 字段折叠合并成单个字段。
常规的头部字段折叠机制可能改变 Set-Cookie 的语义，因为 %x2C（","）字符在 Set-Cookie 中的用法与折叠语义冲突。

Cookie 技术由四个部分组成：

1. HTTP 响应报文中的 Cookie 头行（Set-Cookie）
2. HTTP 请求报文中的 Cookie 头行
3. 保存在用户端系统上、由浏览器管理的 Cookie 文件
4. Web 站点的后端数据库

#### Security

Cookie 有不少安全陷阱，本节概述其中较突出的几个。

特别是，Cookie 容易诱导开发者依赖「环境权威」（ambient authority）做身份认证，从而经常受到跨站请求伪造（CSRF）等攻击。
此外，把会话标识符存放在 Cookie 中时，开发者常常引入会话固定（session fixation）漏洞。

传输层加密（如 HTTPS 所用的 TLS）并不足以防止网络攻击者获取或篡改受害者的 Cookie，因为 Cookie 协议自身存在多种漏洞（参见下文的「弱机密性」与「弱完整性」）。
此外，默认情况下，即使配合 HTTPS 使用，Cookie 也不对网络攻击者提供机密性或完整性保障。

除非通过安全信道（如 TLS）发送，Cookie 和 Set-Cookie 头中的信息都是明文传输的，后果有三：

1. 这些头中传递的所有敏感信息都会暴露给窃听者。
2. 恶意中间人可以篡改双向传输途中的头部，后果难以预料。
3. 恶意客户端也可以在发送前篡改 Cookie 头，后果同样难以预料。

服务器通常不在 Cookie 里直接存放会话信息（否则可能被攻击者窃取或重放），而是存放一个 nonce（即「会话标识符」）。
收到带 nonce 的请求时，服务器以该 nonce 为键查找关联的状态信息。

##### Weak Confidentiality and Weak Integrity

- Cookie 不提供基于端口的隔离。
- Cookie 不提供基于协议 scheme 的隔离。
- Cookie 并非总是提供基于路径的隔离。
- Cookie 对兄弟域名（及其子域）不提供完整性保证。

### Json Web Token

JSON Web Token（JWT）是一种紧凑的 claims（声明）表示格式，面向空间受限的环境，例如 HTTP Authorization 头和 URI 查询参数。
JWT 把待传输的 claims 编码为一个 JSON 对象：该对象可作为 JSON Web Signature（JWS）结构的载荷，或作为 JSON Web Encryption（JWE）结构的明文，
从而可以对 claims 做数字签名，或用消息认证码（MAC）做完整性保护，也可以加密。
JWT 总是以 JWS 紧凑序列化或 JWE 紧凑序列化的形式表示。

JWT 的典型应用场景：

- **授权（Authorization）**：这是 JWT 最常见的场景。用户登录后，后续每个请求都带上 JWT，即可访问该令牌许可的路由、服务和资源。单点登录（Single Sign On）如今广泛使用 JWT，因为它开销小，且易于跨域使用。
- **信息交换（Information Exchange）**：JWT 是在各方之间安全传输信息的好办法。由于 JWT 可以签名（例如使用公私钥对），你可以确认发送方确实如其所言；此外，签名基于头部和载荷计算，因此还能验证内容未被篡改。

> [RFC 7519 - JSON Web Token (JWT)](https://datatracker.ietf.org/doc/rfc7519/)
> [RFC 7797 - JSON Web Signature (JWS) Unencoded Payload Option](https://datatracker.ietf.org/doc/rfc7797/)
> [RFC 8725 - JSON Web Token Best Current Practices](https://datatracker.ietf.org/doc/rfc8725/)

#### Structure

头部（Header）

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

载荷（Payload）

```json
{
  "sub": "1234567890",
  "name": "John Doe",
  "iat": 1516239022
}
```

签名（Signature）

参见 [JWT.IO](https://jwt.io/)。

身份认证流程中，用户凭据登录成功后，服务端会返回一个 JWT。
令牌本身就是凭证，必须格外小心以防安全问题；一般来说，令牌不应保存得比需要的时间更久。
也不要把敏感的会话数据存放在浏览器存储里，因为那里并不安全。
每当用户要访问受保护的路由或资源时，用户代理都应发送 JWT，通常放在 Authorization 头中、使用 Bearer 模式，格式如下：

```http
Authorization: Bearer <token>
```

在某些情况下，这是一种无状态的授权机制：服务器的受保护路由会检查 Authorization 头中是否有有效 JWT，有就放行。如果 JWT 内含必要数据，某些操作可以免查数据库——但也并非总是如此。
如果令牌通过 Authorization 头发送，就不会涉及跨域资源共享（CORS）问题，因为它不使用 Cookie。
要注意：签名令牌虽然无法被篡改，但其中包含的所有信息对用户或其他方都是可见的，所以不要在令牌里放秘密信息。

## Security

[HTTP Security](/docs/CS/CN/HTTP/Security.md)

## Performance

[WebPageTest](https://www.webpagetest.org)

[H2O](https://h2o.examp1e.net/)

## Notes Navigation

本页是 HTTP 协议的主干：消息格式、方法、状态码、连接管理与版本演进均以本页为准，五个专题页各回答一个延伸问题——[HTTPS](/docs/CS/CN/HTTP/HTTPS.md) 把 TLS 插入 HTTP 与 TCP 之间，拆解完整请求的五个阶段并算出约 5 个 RTT 的成本；[QUIC](/docs/CS/CN/HTTP/QUIC.md) 是 HTTP/3 的传输底座，解决 TCP 层面的队头阻塞并带来连接迁移；[HOL](/docs/CS/CN/HTTP/HOL.md) 从交换机输入缓冲、乱序交付与 HTTP 管线三个尺度解释队头阻塞，是理解 HTTP/2 多路复用与 HTTP/3 改造动机的约束条件；[OAuth](/docs/CS/CN/HTTP/OAuth.md) 覆盖授权框架与各 flow 的适用场景；[Security](/docs/CS/CN/HTTP/Security.md) 汇总 CORS 预检与浏览器侧防护头。

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
