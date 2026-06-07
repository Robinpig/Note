## 简介

[OAuth 2.0](https://oauth.net/2/) 是业界标准的授权协议。OAuth 2.0 专注于客户端开发者的简易性，同时为 Web 应用、桌面应用、移动设备和客厅设备提供特定的授权流程。

OAuth 2.0 授权框架使第三方应用能够获得对 HTTP 服务的有限访问，既可以代表资源所有者通过协调资源所有者和 HTTP 服务之间的批准交互来实现，
也可以允许第三方应用代表自身获得访问权限。

此 OAuth 设计用于 [HTTP](/docs/CS/CN/HTTP/HTTP.md)。在任何非 HTTP 协议上使用 OAuth 不在范围内。

### 角色

OAuth 定义了四个角色：

- **资源所有者（resource owner）**
  能够授予对受保护资源访问权限的实体。
  当资源所有者是人时，称为最终用户。
- **资源服务器（resource server）**
  托管受保护资源的服务器，能够接受并使用访问令牌响应受保护资源请求。
- **客户端（client）**
  代表资源所有者并凭借其授权发出受保护资源请求的应用。
  "客户端"一词不暗示任何特定的实现特征（例如，应用是在服务器、桌面还是其他设备上执行）。
- **授权服务器（authorization server）**
  在成功验证资源所有者并获取授权后，向客户端颁发访问令牌的服务器。

授权服务器可以与资源服务器是同一台服务器，也可以是独立的实体。
单个授权服务器可以颁发被多个资源服务器接受的访问令牌。

### 协议流程

```
     +--------+                               +---------------+
     |        |--(A)- 授权请求 --------------->|   资源所有者    |
     |        |                               |               |
     |        |<-(B)-- 授权许可 ---------------|               |
     |        |                               +---------------+
     |        |
     |        |                               +---------------+
     |        |--(C)-- 授权许可 -------------->|   授权服务器   |
     | 客户端  |                               |               |
     |        |<-(D)----- 访问令牌 ------------|               |
     |        |                               +---------------+
     |        |
     |        |                               +---------------+
     |        |--(E)----- 访问令牌 ----------->|   资源服务器   |
     |        |                               |               |
     |        |<-(F)--- 受保护资源 ------------|               |
     +--------+                               +---------------+

                    协议流程
```

授权许可（Authorization Grant）

1. 授权码（Authorization Code）
2. 隐式（Implicit）
3. 资源所有者密码凭证（Resource Owner Password Credentials）
4. 客户端凭证（Client Credentials）

## 链接

- [计算机网络](/docs/CS/CN/CN.md) 
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md?id=OAuth)

## 参考文献

1. [RFC 5849 - The OAuth 1.0 Protocol](https://datatracker.ietf.org/doc/html/rfc5849)
2. [RFC 6749 - The OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/rfc6749)
