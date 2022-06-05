## Introduction

The OAuth 2.0 authorization framework enables a third-party application to obtain limited access to an HTTP service, either on behalf of a resource owner by orchestrating an approval interaction between the resource owner and the HTTP service,
or by allowing the third-party application to obtain access on its own behalf.

This OAuth is designed for use with [HTTP](/docs/CS/CN/HTTP.md).  The use of OAuth over any protocol other than HTTP is out of scope.

### Roles

OAuth defines four roles:

- **resource owner**
  An entity capable of granting access to a protected resource.
  When the resource owner is a person, it is referred to as an end-user.
- **resource server**
  The server hosting the protected resources, capable of accepting and responding to protected resource requests using access tokens.
- **client**
  An application making protected resource requests on behalf of the resource owner and with its authorization.  
  The term "client" does not imply any particular implementation characteristics (e.g., whether the application executes on a server, a desktop, or other devices).
- **authorization server**
  The server issuing access tokens to the client after successfully authenticating the resource owner and obtaining authorization.

The authorization server may be the same server as the resource server or a separate entity.
A single authorization server may issue access tokens accepted by multiple resource servers.

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


Authorization Grant

1. Authorization Code
2. Implicit
3. Resource Owner Password Credentials
4. Client Credentials

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [Spring Security](/docs/CS/Java/Spring/Security.md?id=OAuth)

## References

1. [RFC 5849 - The OAuth 1.0 Protocol](https://datatracker.ietf.org/doc/html/rfc5849).
2. [RFC 6749 - The OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/rfc6749)
