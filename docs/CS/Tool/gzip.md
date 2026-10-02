## Introduction

gzip 是基于 **DEFLATE**（LZ77 字典压缩 + Huffman 熵编码）的通用文件压缩格式与工具，规范见 [RFC 1952](https://datatracker.ietf.org/doc/html/rfc1952)。它与 zlib（RFC 1950，带 zlib 头+ Adler-32）同源但封装不同：gzip 带 `gzip` 魔术头与 `CRC-32` + `ISIZE` 校验，适合单文件压缩；而 `.zip`、PNG 内部也用到 DEFLATE，但容器格式各异。

## 文件格式（成员结构）

一个 gzip 成员（member）头部为 10 字节固定头，后接可变头部字段与压缩数据，结尾是 8 字节 trailer：

```
 +---+---+---+---+---+---+---+---+---+---+
 |ID1|ID2|CM |FLG|     MTIME     |XFL|OS |  (更多头部字段 -->)
 +---+---+---+---+---+---+---+---+---+---+
```

- `ID1 ID2` = `0x1f 0x8b`（gzip 魔术字）。
- `CM` = 压缩方法，固定 `8`（DEFLATE）。
- `FLG` = 标志位（如 `FNAME` 含原文件名、`FCOMMENT` 含注释）。
- `MTIME` = 4 字节小端，原文件修改时间；`gzip -n` 可置 0 以**去除时间戳**，使相同输入的压缩产物字节一致（便于内容寻址/校验去重）。
- trailer：`CRC-32`（4B）+ `ISIZE`（4B，原始大小 mod 2³²）。

## 常用命令与陷阱

```shell
# -n 去掉 MTIME/文件名，输出可复现
gzip -n -c swagger.yaml | xxd -p -c 4 | sed -n '2p'

# 解压 / 保留原文件(-k) / 最快(-1) ~ 最慢(-9)
gzip -d file.gz ; gzip -k file ; gzip -9 file
```

- **可复现性**：默认 gzip 会把当前时间写进 `MTIME`、把文件名写进头部，导致同一文件每次压缩出的字节不同；CI/缓存场景务必用 `gzip -n` 去掉这些非确定性字段。
- **HTTP 传输**：服务端常对文本（js/css/json）做 `Content-Encoding: gzip`，浏览器透明解压；注意压缩是 CPU 换带宽，已压缩的格式（图片/视频）再 gzip 收益甚微。

## 与其他压缩对比

| 格式 | 算法 | 特点 |
|---|---|---|
| gzip | DEFLATE | 通用、速度快、生态广 |
| bzip2 | BWT | 压缩率更高、更慢 |
| xz/lzma | LZMA | 极高压缩率、最慢 |
| zstd | 字典+FSE | 可调速度/压缩率、现代首选 |

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [JPEG](/docs/CS/Algorithms/JPEG.md)

## References

- [RFC 1952 - GZIP file format specification](https://datatracker.ietf.org/doc/html/rfc1952)
- [RFC 1951 - DEFLATE Compressed Data Format](https://datatracker.ietf.org/doc/html/rfc1951)
