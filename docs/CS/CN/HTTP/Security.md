## Introduction

## CORS

**跨域资源共享（Cross-Origin Resource Sharing，CORS）**是一种基于 HTTP 头的机制：服务器通过它告知浏览器，除了自身源（域、协议或端口）之外，还允许从哪些源加载资源。
CORS 还依赖一种「预检」（preflight）机制：浏览器先向托管跨域资源的服务器发一个预检请求，确认服务器会允许实际请求。
在预检请求中，浏览器会发出头部，指明实际请求将使用的 HTTP 方法和头部。

出于安全原因，浏览器会限制由脚本发起的跨域 HTTP 请求。
这意味着，使用这些 API 的 Web 应用只能从加载该应用的同一个源请求资源，除非其他源的响应带有正确的 CORS 头部。

CORS 机制支持浏览器与服务器之间安全的跨域请求和数据传输。
现代浏览器在 XMLHttpRequest、Fetch 等 API 中使用 CORS，以降低跨域 HTTP 请求的风险。

CORS 并不能防御[跨站请求伪造（CSRF）](/docs/CS/CN/HTTP/Security.md?id=csrf)这类跨站攻击。

### Access Control Scenarios

#### Simple requests

有些请求不会触发 CORS 预检。
这类请求称为「简单请求」（simple requests），不过定义 CORS 的 Fetch 规范并不使用这个术语。

下面这次交互就是客户端与服务器之间一次最简单的交换，通过 CORS 头部处理权限：

请求（Req）

```http
GET /resources/public-data/ HTTP/1.1
Origin: https://normal-website.com
```

响应（Resp）

```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://normal-website.com
```

Origin 与 Access-Control-Allow-Origin 头部相呼应的这种模式，是访问控制协议最简单的用法。

#### Preflighted requests

与简单请求不同，「预检」请求会先用 OPTIONS 方法向另一个源的资源发一个 HTTP 请求，以确定实际请求是否可以安全发送。
这类跨域请求之所以要预检，是因为它们可能影响用户数据。

```http
OPTIONS /doc HTTP/1.1
Origin: https://foo.example
Access-Control-Request-Method: POST
Access-Control-Request-Headers: X-PINGOTHER, Content-Type

HTTP/1.1 204 No Content
Access-Control-Allow-Origin: https://foo.example
Access-Control-Allow-Methods: POST, GET, OPTIONS
Access-Control-Allow-Headers: X-PINGOTHER, Content-Type
Access-Control-Max-Age: 86400
```

预检请求完成后，才会发送真正的请求。

#### Requests with credentials

### CSRF

**跨站请求伪造（Cross-site request forgery，CSRF）**是一种 Web 安全漏洞：攻击者可以诱导用户执行其本无意执行的操作。
它让攻击者得以部分绕过同源策略（same origin policy）——该策略的本意是防止不同网站相互干扰。

一次 CSRF 攻击要成立，需要同时满足三个关键条件：

* **存在可用的操作。** 应用中有一个攻击者有理由诱导用户执行的操作。它可能是特权操作（比如修改其他用户的权限），也可能是针对用户个人数据的操作（比如修改用户自己的密码）。
* **基于 Cookie 的会话处理。** 执行该操作需要发起一个或多个 HTTP 请求，而应用仅依靠会话 Cookie 来识别发出请求的用户，没有其他跟踪会话或校验用户请求的机制。
* **没有不可预测的请求参数。** 执行该操作的请求不包含攻击者无法确定或猜测的参数值。例如，诱导用户修改密码时，如果攻击者需要知道原密码的值，该功能就不存在此漏洞。

#### Preventing CSRF attacks

防御 CSRF 攻击最稳妥的方式，是在相关请求中加入 [CSRF 令牌](https://portswigger.net/web-security/csrf/tokens)。
该令牌应当：

* 具有高熵、不可预测，与会话令牌同理。
* 与用户的会话绑定。
* 在执行相关操作前逐一严格校验。

> [!NOTE]
>
> 本页聚焦 HTTP 层的安全机制（CORS、CSRF）；密码学基础、TLS 协议与攻击面总览见 [Security](/docs/CS/CN/Security.md)。

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [CyberSecurity](/docs/CS/CN/CyberSecurity/CyberSecurity.md)
- [Authentication](/docs/CS/CN/CyberSecurity/Authentication.md)

## References

1. [MDN Web Docs HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP)
