## Introduction

## CORS

**Cross-Origin Resource Sharing (CORS)** is an HTTP-header based mechanism that allows a server to indicate any origins (domain, scheme, or port) other than its own from which a browser should permit loading resources.
CORS also relies on a mechanism by which browsers make a "preflight" request to the server hosting the cross-origin resource, in order to check that the server will permit the actual request.
In that preflight, the browser sends headers that indicate the HTTP method and headers that will be used in the actual request.

For security reasons, browsers restrict cross-origin HTTP requests initiated from scripts.
This means that a web application using those APIs can only request resources from the same origin the application was loaded from unless the response from other origins includes the right CORS headers.

The CORS mechanism supports secure cross-origin requests and data transfers between browsers and servers.
Modern browsers use CORS in APIs such as XMLHttpRequest or Fetch to mitigate the risks of cross-origin HTTP requests.

CORS is not a protection against cross-origin attacks such as [cross-site request forgery (CSRF)](/docs/CS/CN/HTTP/Security.md?id=CSRF).

### Access Control Scenarios

#### Simple requests

Some requests don't trigger a CORS preflight.
Those are called simple requests, though the Fetch spec (which defines CORS) doesn't use that term.

This operation performs a simple exchange between the client and the server, using CORS headers to handle the privileges:

Req

```http
GET /resources/public-data/ HTTP/1.1
Origin: https://normal-website.com
```

Resp

```http
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://normal-website.com
```

This pattern of the Origin and Access-Control-Allow-Origin headers is the simplest use of the access control protocol.

#### Preflighted requests

Unlike simple requests, for "preflighted" requests the browser first sends an HTTP request using the OPTIONS method to the resource on the other origin, in order to determine if the actual request is safe to send.
Such cross-origin requests are preflighted since they may have implications for user data.

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

Once the preflight request is complete, the real request is sent.

#### Requests with credentials

### CSRF

**Cross-site request forgery (CSRF)** is a web security vulnerability that allows an attacker to induce users to perform actions that they do not intend to perform.
It allows an attacker to partly circumvent the same origin policy, which is designed to prevent different websites from interfering with each other.

For a CSRF attack to be possible, three key conditions must be in place:

* **A relevant action.** There is an action within the application that the attacker has a reason to induce.
  This might be a privileged action (such as modifying permissions for other users) or any action on user-specific data (such as changing the user's own password).
* **Cookie-based session handling.** Performing the action involves issuing one or more HTTP requests, and the application relies solely on session cookies to identify the user who has made the requests.
  There is no other mechanism in place for tracking sessions or validating user requests.
* **No unpredictable request parameters.** The requests that perform the action do not contain any parameters whose values the attacker cannot determine or guess.
  For example, when causing a user to change their password, the function is not vulnerable if an attacker needs to know the value of the existing password.

#### Preventing CSRF attacks

The most robust way to defend against CSRF attacks is to include a [CSRF token](https://portswigger.net/web-security/csrf/tokens) within relevant requests. 
The token should be:

* Unpredictable with high entropy, as for session tokens in general.
* Tied to the user's session.
* Strictly validated in every case before the relevant action is executed.

## Links

- [Computer Network](/docs/CS/CN/CN.md)
- [HTTP](/docs/CS/CN/HTTP/HTTP.md)

## References

1. [MDN Web Docs HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP)
