## Introduction

MIME（Multipurpose Internet Mail Extensions，多用途互联网邮件扩展）最初为电子邮件定义，如今其最广泛的应用是 **媒体类型（Media Type / Content-Type）**——用 `type/subtype` 的形式描述数据的格式，让接收方知道该如何解析载荷。HTTP 的 `Content-Type` 头、邮件 `Content-Type`、以及 `multipart/form-data` 上传都建立在 MIME 之上。

## 媒体类型结构

一个媒体类型由**顶级类型 + 子类型**组成，可选参数：

```
type "/" subtype *( ";" parameter )
# 例：text/html; charset=utf-8
#     application/json
#     image/png
#     multipart/form-data; boundary=----abcd
```

**八大顶级类型**：

| 顶级类型 | 含义 | 典型子类型 |
|---|---|---|
| `text` | 可读文本 | `text/plain`、`text/html`、`text/css` |
| `image` | 静态图像 | `image/png`、`image/jpeg`、`image/svg+xml` |
| `audio` | 音频 | `audio/mpeg`、`audio/aac` |
| `video` | 视频 | `video/mp4`、`video/webm` |
| `application` | 二进制/应用数据 | `application/json`、`application/octet-stream`、`application/pdf` |
| `multipart` | 多部分聚合 | `multipart/form-data`、`multipart/byteranges` |
| `message` | 封装的消息 | `message/rfc822`、`message/http` |

常见参数：`charset`（字符集，如 `utf-8`）、`boundary`（`multipart` 各部分的边界分隔符）、`boundary` 必须唯一且不会出现在正文里。

## 在 HTTP 与文件上传中的角色

- **响应类型协商**：服务器通过 `Content-Type: text/html; charset=utf-8` 告诉浏览器如何渲染；缺失或错误常导致「下载而非显示」或乱码。
- **表单上传**：`<form enctype="multipart/form-data">` 把文件与字段切成多段，每段带自己的 `Content-Disposition` 与 `Content-Type`，靠 `boundary` 分隔，是文件上传的标准机制。
- **MIME 嗅探**：浏览器有时会「嗅探」实际字节而非信任 `Content-Type`，带来安全风险（如把 `text/plain` 当 HTML 执行），可用 `X-Content-Type-Options: nosniff` 关闭。

## 与文件扩展名的区别

MIME 类型描述的是**内容语义**，扩展名只是**文件名约定**。同一扩展名（`.json`）对应唯一类型 `application/json`，但同一类型可有多种扩展名；可靠的系统应以 `Content-Type` 为准，而不是靠后缀猜测。

## Links

- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [HTTPS](/docs/CS/CN/HTTP/HTTPS.md)
- [FTP](/docs/CS/CN/FTP.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

- [RFC 6838 - Media Type Specifications and Registration Procedures](https://datatracker.ietf.org/doc/rfc6838/)
- [MDN - MIME types (IANA media types)](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types)
