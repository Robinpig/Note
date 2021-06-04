# HTTP

`HyperText Transfer Protocol`

简单 灵活 易扩展

Stateless

明文 不安全

HTTPS

TLS



性能不算高

1. 明文传输，不检查内容是否被窃听
2. 不校验通信方是否是伪装
3. 不确定报文是否正常，未被篡改





报文

- Header
  - start line
  - header
- entity

 

Method

- GET
- POST
- PUT
- DELETE
- HEAD
- OPTIONS
- TRACE
- CONNECT


## Version

### HTTP 1.1

connection keep-alive

pipeline, 不必等上一个请求返回可发送第二个请求

队头阻塞 串行化顺序等待

### HTTP 2.0



头部压缩 HPACK algorithm

二进制格式

强化安全

服务器推送

多路复用 并发请求 无队头阻塞问题

标头

- Cache-Control
- Connection
- Pragma
- Trailer
- Transfer-Encoding
- Upgrade
- Via
- Warning



Cache

no-cache

public



Connection

```http
Connection: keep-Alive
```



```http
Connection: close
```

issues:

多路复用同一个TCP连接，TCP连接不了解上层多少HTTP请求， 当存在丢包时， 其他HTTP请求必须阻塞等待

### HTTP 3.0

使用UDP代替TCP ，防止出现队头阻塞或者重传阻塞

升级到TLS1.3 头部压缩算法QPack

基于TCP+TLS1.2需要6次握手，QUIC压缩到3次



## Authority

HTTP协议的无状态性 无法认证请求来源 需要使用机制来记录用户信息与状态



### Cookie

优点

会话管理

行为追踪 个性定制

cookie类型

会话 - 客户端可选择 是否删除 删除后无法识别

永久 - 设置了过期条件 客户端进行持久化



```http
Set-Cookie: xxx
```

Cookie跨域

不同域名未使用相同Cookie



Session

session依赖于容器 

解决方案

1. 集群复制 影响性能
2. 路由 固定用户固定容器 容错性不高
3. 使用中间件统一存储

多系统时可以考虑独立于其它业务系统

### 区别

- Cookie存储在客户端
    - 不安全
    - 数量限制
- Session存储在服务端
    - 不能跨域
- Token
    - 无状态、可扩展
    - 支持移动设备
    - 跨程序调用
    - 安全
### 基于Token的验证原理


基于Token的身份验证是无状态的，我们不将用户信息存在服务器或Session中。

这种概念解决了在服务端存储信息时的许多问题。NoSession意味着你的程序可以根据需要去增减机器，而不用去担心用户是否登录。

基于Token的身份验证的过程如下:
    

   - 用户通过用户名和密码发送请求。
   - 程序验证。
   - 程序返回一个签名的token 给客户端。
   - 客户端储存token,并且每次用于每次发送请求。
   - 服务端验证token并返回数据。

   每一次请求都需要 token。token 应该在HTTP的头部发送从而保证了Http请求无状态。我们同样通过设置服务器属性Access-Control-Allow-Origin:* ，让服务器能接受到来自所有域的请求。需要主要的是，在ACAO头部标明(designating)*时，不得带有像HTTP认证，客户端SSL证书和cookies的证书。

### 基于Token验证的优势

- 无状态、可扩展

在客户端存储的 Token 是无状态的，并且能够被扩展。基于这种无状态和不存储Session信息，负载负载均衡器能够将用户信息从一个服务传到其他服务器上。

如果我们将已验证的用户的信息保存在Session中，则每次请求都需要用户向已验证的服务器发送验证信息(称为Session亲和性)。用户量大时，可能会造成 一些拥堵。

但是不要着急。使用Token之后这些问题都迎刃而解，因为Token自己hold住了用户的验证信息。

- 安全性

请求中发送token而不再是发送cookie能够防止CSRF(跨站请求伪造)。即使在客户端使用cookie存储token，cookie也仅仅是一个存储机制而不是用于认证。不将信息存储在Session中，让我们少了对session操作。

Token是有时效的，一段时间之后用户需要重新验证。我们也不一定需要等到Token自动失效，Token有撤回的操作，通过token revocataion可以使一个特定的Token或是一组有相同认证的token无效。

- 可扩展性

Token能够创建与其它程序共享权限的程序。例如，能将一个随便的社交帐号和自己的大号(Fackbook或是Twitter)联系起来。当通过服务登录Twitter(我们将这个过程Buffer)时，我们可以将这些Buffer附到Twitter的数据流上(we are allowing Buffer to post to our Twitter stream)。

使用Token时，可以提供可选的权限给第三方应用程序。当用户想让另一个应用程序访问它们的数据，我们可以通过建立自己的API，得出特殊权限的tokens。

- 多平台跨域

我们提前先来谈论一下CORS(跨域资源共享)，对应用程序和服务进行扩展的时候，需要介入各种各种的设备和应用程序。

Having our API just serve data, we can also make the design choice to serve assets from a CDN. This eliminates the issues that CORS brings up after we set a quick header configuration for our application.

只要用户有一个通过了验证的token，数据和资源就能够在任何域上被请求到。

    Access-Control-Allow-Origin: *

- 基于标准

创建Token的时候，你可以设定一些选项。我们在后续的文章中会进行更加详尽的描述，但是标准的用法会在JSON Web Token体现。

最近的程序和文档是供给JSON Web Token的。它支持众多的语言。这意味在未来的使用中你可以真正的转换你的认证机制。   
### JWT

*[`JSON Web Token(JWT)`](https://datatracker.ietf.org/doc/rfc7519/)  is a compact, URL-safe means of representing claims to be transferred between two parties.  The claims in a JWT are encoded as a JSON object that is used as the payload of a JSON Web Signature (JWS) structure or as the plaintext of a JSON Web Encryption (JWE) structure, enabling the claims to be digitally signed or integrity protected with a Message Authentication Code (MAC) and/or encrypted.*



可以在服务端验证

可以跨域认证




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





在HTTP/1.1规范中幂等性的定义是：

> Methods can also have the property of "idempotence" in that (aside from error or expiration issues) the side-effects of N > 0 identical requests is the same as for a single request.

从定义上看，HTTP 方法的幂等性是指一次和多次请求某一个资源应该具有同样的副作用。幂等性属于语义范畴，正如编译器只能帮助检查语法错误一样，HTTP 规范也没有办法通过消息格式等语法手段来定义它，这可能是它不太受到重视的原因之一。但实际上，幂等性是分布式系统设计中十分重要的概念，而 HTTP 的分布式本质也决定了它在 HTTP 中具有重要地位。

HTTP 方法的安全性指的是不会改变服务器状态，也就是说它只是可读的。所以只有 OPTIONS、GET、HEAD 是安全的，其他都是不安全的。

| HTTP 方法 | 幂等性 | 安全性 |
| --------- | ------ | ------ |
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

## HTTP 状态码

服务器返回的 **响应报文** 中第一行为状态行，包含了状态码以及原因短语，用来告知客户端请求的结果。

| 状态码 | 类别                             | 原因短语                   |
| ------ | -------------------------------- | -------------------------- |
| 1XX    | Informational（信息性状态码）    | 接收的请求正在处理         |
| 2XX    | Success（成功状态码）            | 请求正常处理完毕           |
| 3XX    | Redirection（重定向状态码）      | 需要进行附加操作以完成请求 |
| 4XX    | Client Error（客户端错误状态码） | 服务器无法处理请求         |
| 5XX    | Server Error（服务器错误状态码） | 服务器处理请求出错         |

### 1XX 信息

- **100 Continue** ：表明到目前为止都很正常，客户端可以继续发送请求或者忽略这个响应。

### 2XX 成功

- **200 OK**
- **204 No Content** ：请求已经成功处理，但是返回的响应报文不包含实体的主体部分。一般在只需要从客户端往服务器发送信息，而不需要返回数据时使用。
- **206 Partial Content** ：表示客户端进行了范围请求。响应报文包含由 Content-Range 指定范围的实体内容。

### 3XX 重定向

- **301 Moved Permanently** ：永久性重定向
- **302 Found** ：临时性重定向
- **303 See Other** ：和 302 有着相同的功能，但是 303 明确要求客户端应该采用 GET 方法获取资源。
- 注：虽然 HTTP 协议规定 301、302 状态下重定向时不允许把 POST 方法改成 GET 方法，但是大多数浏览器都会在 301、302 和 303 状态下的重定向把 POST 方法改成 GET 方法。
- **304 Not Modified** ：如果请求报文首部包含一些条件，例如：If-Match，If-ModifiedSince，If-None-Match，If-Range，If-Unmodified-Since，如果不满足条件，则服务器会返回 304 状态码。
- **307 Temporary Redirect** ：临时重定向，与 302 的含义类似，但是 307 要求浏览器不会把重定向请求的 POST 方法改成 GET 方法。

### 4XX 客户端错误

- **400 Bad Request** ：请求报文中存在语法错误。
- **401 Unauthorized** ：该状态码表示发送的请求需要有认证信息（BASIC 认证、DIGEST 认证）。如果之前已进行过一次请求，则表示用户认证失败。
- **403 Forbidden** ：请求被拒绝，服务器端没有必要给出拒绝的详细理由。
- **404 Not Found**

### 5XX 服务器错误

- **500 Internal Server Error** ：服务器正在执行请求时发生错误。
- **503 Service Unavilable** ：服务器暂时处于超负载或正在进行停机维护，现在无法处理请求。



[HTTP Code](https://zh.wikipedia.org/wiki/HTTP%E7%8A%B6%E6%80%81%E7%A0%81)



并行连接

持久连接

pipeline



(Cross-Origin Resource Sharing)CORS跨域

