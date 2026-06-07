## 简介

## CORS

**跨域资源共享（CORS）**是一种基于 HTTP 头的机制，允许服务器指示除自身以外的任何来源（域名、协议或端口），浏览器应允许从中加载资源。
CORS 还依赖于一种机制，浏览器向托管跨域资源的服务器发出"预检"请求，以检查服务器是否允许实际请求。
在该预检中，浏览器发送指示实际请求中将使用的 HTTP 方法和头部。

出于安全原因，浏览器限制从脚本发起的跨域 HTTP 请求。
这意味着使用这些 API 的 Web 应用只能从加载应用的同一来源请求资源，除非来自其他来源的响应包含正确的 CORS 头。

CORS 机制支持浏览器和服务器之间的安全跨域请求和数据传输。
现代浏览器在 XMLHttpRequest 或 Fetch 等 API 中使用 CORS，以减轻跨域 HTTP 请求的风险。

CORS 不是针对跨域攻击（如[跨站请求伪造（CSRF）](/docs/CS/CN/HTTP/Security.md?id=CSRF)）的防护。

### 访问控制场景

#### 简单请求

某些请求不会触发 CORS 预检。
这些称为简单请求，尽管 Fetch 规范（定义了 CORS）不使用该术语。

此操作在客户端和服务器之间执行简单交换，使用 CORS 头处理权限：

请求

```http
GET /resources/public-data/ HTTP/1.1
Origin: https://normal-website.com
```

响应

```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://normal-website.com
```

这种 Origin 和 Access-Control-Allow-Origin 头的模式是访问控制协议最简单的用法。

#### 预检请求

与简单请求不同，对于"预检"请求，浏览器首先使用 OPTIONS 方法向其他来源的资源发送 HTTP 请求，以确定实际请求是否安全发送。
此类跨域请求需要预检，因为它们可能对用户数据有影响。

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

预检请求完成后，发送实际请求。

#### 带凭证的请求

### CSRF

**跨站请求伪造（CSRF）**是一种 Web 安全漏洞，允许攻击者诱导用户执行他们不打算执行的操作。
它允许攻击者部分绕过同源策略，该策略旨在防止不同网站相互干扰。

CSRF 攻击可能发生需要三个关键条件：

* **相关操作。** 应用中存在攻击者有理由诱发的操作。
  这可能是特权操作（如修改其他用户的权限）或任何涉及用户特定数据的操作（如更改用户自己的密码）。
* **基于 Cookie 的会话处理。** 执行该操作涉及发出一个或多个 HTTP 请求，应用仅依赖会话 Cookie 来标识发出请求的用户。
  没有其他机制来跟踪会话或验证用户请求。
* **无不可预测的请求参数。** 执行操作的请求不包含攻击者无法确定或猜测其值的参数。
  例如，当导致用户更改密码时，如果攻击者需要知道现有密码的值，则该功能不易受攻击。

#### 防止 CSRF 攻击

防御 CSRF 攻击最稳健的方法是在相关请求中包含 [CSRF 令牌](https://portswigger.net/web-security/csrf/tokens)。
该令牌应具有：

* 与一般会话令牌一样，具有高熵且不可预测。
* 绑定到用户的会话。
* 在执行相关操作之前，始终严格验证。

## 链接

- [计算机网络](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## 参考文献

1. [MDN Web Docs HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP)
