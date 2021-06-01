# OAuth



[RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)


The OAuth 2.0 authorization framework enables a third-party application to obtain limited access to an HTTP service, either on behalf of a resource owner by orchestrating an approval interaction between the resource owner and the HTTP service, or by allowing the third-party application to obtain access on its own behalf.  This specification replaces and obsoletes the OAuth 1.0 protocol described in [RFC 5849](https://datatracker.ietf.org/doc/html/rfc5849).






  OAuth defines four roles:

   resource owner
      An entity capable of granting access to a protected resource.
      When the resource owner is a person, it is referred to as an
      end-user.

   resource server
      The server hosting the protected resources, capable of accepting
      and responding to protected resource requests using access tokens.

   client
      An application making protected resource requests on behalf of the
      resource owner and with its authorization.  The term "client" does
      not imply any particular implementation characteristics (e.g.,
      whether the application executes on a server, a desktop, or other
      devices).

   authorization server
      The server issuing access tokens to the client after successfully
      authenticating the resource owner and obtaining authorization.




Authorization Grant

1. Authorization Code
2. Implicit
3. Resource Owner Password Credentials
4. Client Credentials

