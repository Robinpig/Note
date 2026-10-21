## Introduction

[OAuth 2.0](https://oauth.net/2/) 是行业标准的授权（authorization）协议。OAuth 2.0 以简化客户端开发为目标，同时为 Web 应用、桌面应用、手机和客厅设备提供专门的授权流程。

OAuth 2.0 授权框架让第三方应用可以获得对 HTTP 服务的有限访问权限——要么代表资源所有者（通过在资源所有者与 HTTP 服务之间编排一次批准交互），要么允许第三方应用以自身名义获取访问权限。

OAuth 的设计用途是配合 [HTTP](/docs/CS/CN/HTTP/HTTP.md) 使用；在 HTTP 之外的协议上使用 OAuth 不在其范围内。

### Roles

OAuth 定义四种角色：

- **资源所有者（resource owner）**
  能够授予受保护资源访问权限的实体。当资源所有者是人时，称为终端用户（end-user）。
- **资源服务器（resource server）**
  托管受保护资源的服务器，能够接受并使用访问令牌（access token）响应受保护资源的请求。
- **客户端（client）**
  经资源所有者授权、代表其发起受保护资源请求的应用。
  「client」一词不蕴含任何特定实现特征（例如应用是跑在服务器、桌面还是其他设备上）。
- **授权服务器（authorization server）**
  在成功认证资源所有者并获得授权后，向客户端签发访问令牌的服务器。

授权服务器可以与资源服务器是同一台服务器，也可以是独立的实体。
一个授权服务器签发的访问令牌，可以被多个资源服务器接受。

### Protocol Flow

```
     +--------+                               +---------------+
     |        |--(A)- Authorization Request ->|   Resource    |
     |        |                               |     Owner     |
     |        |<-(B)-- Authorization Grant ---|               |
     |        |                               +---------------+
     |        |
     |        |                               +---------------+
     |        |--(C)-- Authorization Grant -->| Authorization |
     | Client |                               |     Server    |
     |        |<-(D)----- Access Token -------|               |
     |        |                               +---------------+
     |        |
     |        |                               +---------------+
     |        |--(E)----- Access Token ------>|    Resource   |
     |        |                               |     Server    |
     |        |<-(F)--- Protected Resource ---|               |
     +--------+                               +---------------+

                        Protocol Flow
```

上图中：(A) 客户端向资源所有者请求授权；(B) 资源所有者返回授权许可（Authorization Grant）；(C) 客户端携带授权许可请求授权服务器；(D) 授权服务器签发访问令牌（Access Token）；(E) 客户端携带访问令牌请求资源服务器；(F) 资源服务器返回受保护资源。

授权许可（Authorization Grant）分四种类型：

1. 授权码（Authorization Code）
2. 隐式（Implicit）
3. 资源所有者密码凭据（Resource Owner Password Credentials）
4. 客户端凭据（Client Credentials）

## Links

- [Computer Network](/docs/CS/CN/CN.md) 
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [Spring Security](/docs/CS/Framework/Spring/Security.md?id=oauth)

## References

1. [RFC 5849 - The OAuth 1.0 Protocol](https://datatracker.ietf.org/doc/html/rfc5849)
2. [RFC 6749 - The OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/rfc6749)
