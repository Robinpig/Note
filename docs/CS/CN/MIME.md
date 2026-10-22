## Introduction

MIME（Multipurpose Internet Mail Extensions，多用途互联网邮件扩展）最初为电子邮件定义，如今其最广泛的应用是 **媒体类型（Media Type / Content-Type）**——用 `type/subtype` 的形式描述数据的格式，让接收方知道该如何解析载荷。HTTP 的 `Content-Type` 头、邮件 `Content-Type`、以及 `multipart/form-data` 上传都建立在 MIME 之上。

## Media Type Structure

一个媒体类型由**顶级类型 + 子类型**组成，可选参数：

```
type "/" subtype *( ";" parameter )
# 例：text/html; charset=utf-8
#     application/json
#     image/png
#     multipart/form-data; boundary=----abcd
```

**初始七个标准顶级类型**（RFC 2046）：5 个离散型（text/image/audio/video/application）+ 2 个组合型（multipart/message）——

| 顶级类型 | 分类 | 含义 | 典型子类型 |
|---|---|---|---|
| `text` | 离散 | 可读文本 | `text/plain`、`text/html`、`text/css` |
| `image` | 离散 | 静态图像 | `image/png`、`image/jpeg`、`image/svg+xml` |
| `audio` | 离散 | 音频 | `audio/mpeg`、`audio/aac` |
| `video` | 离散 | 视频 | `video/mp4`、`video/webm` |
| `application` | 离散 | 二进制/应用数据 | `application/json`、`application/octet-stream`、`application/pdf` |
| `multipart` | 组合 | 多部分聚合 | `multipart/form-data`、`multipart/byteranges` |
| `message` | 组合 | 封装的消息 | `message/rfc822`、`message/http` |

七个之后，IANA 又按 RFC 6838 §4.2.7（新增顶级类型必须走 IETF Standards Track RFC）陆续登记了三个：**model**（RFC 2077）、**example**（RFC 4735，专供文档示例）、**font**（RFC 8081）——目前 IANA 已注册的顶级类型共 **10 个**。

> [!WARNING]
> 「MIME 有八大顶级类型」是常见误传：RFC 2046 原文只有初始七个，现存的十大是「7 + 后登记 3」的结果，中间从来没有过「八大」这种官方定义。

常见参数：`charset`（字符集，如 `utf-8`）、`boundary`（`multipart` 各部分的边界分隔符，必须唯一且不会出现在正文里）。

## Content-Transfer-Encoding

MIME 实体除了「是什么类型」，还要声明「怎么编码传输」。RFC 2045 定义的两种主力编码：

| 编码 | 适用场景 | 特点 |
|---|---|---|
| base64（RFC 2045 §6.8） | 任意二进制数据 | 每 3 字节编成 4 个 ASCII 字符，体积约膨胀 33%，人不可读 |
| quoted-printable（RFC 2045 §6.7） | 以 ASCII 为主的文本 | 仅非 ASCII 字节与少数控制字符转义为 `=XX`，保持人眼可读 |

另有 7bit / 8bit / binary 三个取值，声明「未经编码」的载荷形态：7bit（默认）要求纯 ASCII 短行，8bit 允许高位字节，binary 则不限行长——它们决定邮件能否直接走 7bit 传输通道。HTTP 报文不使用 `Content-Transfer-Encoding`（压缩协商走 `Transfer-Encoding` 与 `Content-Encoding`），该头主要服务于邮件世界。

## Structured Syntax Suffix

RFC 6838 §4.2.8 规定：子类型名里**最后一个 `+` 之后的部分是结构化语法后缀**，标明实体的底层语法而非业务语义：

- `image/svg+xml` 的 `+xml`、`application/problem+json` 的 `+json`、`application/atom+xml`
- `+xml` 由 RFC 3023 首开先例（XML 媒体类型注册时确立），此后成为通用约定
- 后缀本身有 IANA 注册表（RFC 6838 §6），遇到陌生后缀可据此判断载荷该如何解析

## Role in HTTP and File Upload

- **响应类型协商**：服务器通过 `Content-Type: text/html; charset=utf-8` 告诉浏览器如何渲染；缺失或错误常导致「下载而非显示」或乱码。
- **表单上传**：`<form enctype="multipart/form-data">` 把文件与字段切成多段，每段带自己的 `Content-Disposition` 与 `Content-Type`，靠 `boundary` 分隔，是文件上传的标准机制。
- **MIME 嗅探**：浏览器有时会「嗅探」实际字节而非信任 `Content-Type`，带来安全风险（如把 `text/plain` 当 HTML 执行），可用 `X-Content-Type-Options: nosniff` 关闭。

## Difference from File Extensions

MIME 类型描述的是**内容语义**，扩展名只是**文件名约定**。同一扩展名（`.json`）对应唯一类型 `application/json`，但同一类型可有多种扩展名；可靠的系统应以 `Content-Type` 为准，而不是靠后缀猜测。

## Links

- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [HTTPS](/docs/CS/CN/HTTP/HTTPS.md)
- [FTP](/docs/CS/CN/FTP.md)
- [Computer Network](/docs/CS/CN/CN.md)

## References

- [RFC 2045 - MIME Part One: Format of Internet Message Bodies](https://datatracker.ietf.org/doc/rfc2045/)
- [RFC 2046 - MIME Part Two: Media Types](https://datatracker.ietf.org/doc/rfc2046/)
- [RFC 6838 - Media Type Specifications and Registration Procedures](https://datatracker.ietf.org/doc/rfc6838/)
- [MDN - MIME types (IANA media types)](https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP/MIME_types)
