# HTTP

## Cookie？Session？Token？
###为什么需要？
HTTP协议的无状态性无法认证请求来源
###区别
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
###基于Token的验证原理
    
基于Token的身份验证是无状态的，我们不将用户信息存在服务器或Session中。
    
这种概念解决了在服务端存储信息时的许多问题。NoSession意味着你的程序可以根据需要去增减机器，而不用去担心用户是否登录。
    
基于Token的身份验证的过程如下:
    
   - 用户通过用户名和密码发送请求。
   - 程序验证。
   - 程序返回一个签名的token 给客户端。
   - 客户端储存token,并且每次用于每次发送请求。
   - 服务端验证token并返回数据。
    
   每一次请求都需要 token。token 应该在HTTP的头部发送从而保证了Http请求无状态。我们同样通过设置服务器属性Access-Control-Allow-Origin:* ，让服务器能接受到来自所有域的请求。需要主要的是，在ACAO头部标明(designating)*时，不得带有像HTTP认证，客户端SSL证书和cookies的证书。
   
###基于Token验证的优势

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
###JWT
JSON Web Token 是一个开放标准

用途：
- 授权：这是使用JWT的最常见方案。一旦用户登录，每个后续请求将包括JWT，从而允许用户访问该令牌允许的路由，服务和资源。单一登录是当今广泛使用JWT的一项功能，因为它的开销很小并且可以在不同的域中轻松使用。
- 信息交换：JSON Web令牌是在各方之间安全地传输信息的好方法。因为可以对JWT进行签名（例如，使用公钥/私钥对），所以您可以确定发件人是他们所说的人。另外，由于签名是使用标头和有效负载计算的，因此您还可以验证内容是否未被篡改。

结构：
JSON Web令牌以紧凑的形式由三部分组成，这些部分由点（.）分隔，分别是：
- Header 标头
    - 通常由两部分组成：令牌的类型（即JWT）和所使用的签名算法
- Payload 有效载荷
- Signature 签名
    - 通过payload和secret使用Header指定算法生成