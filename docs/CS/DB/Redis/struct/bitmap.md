## 简介

位图（Bitmaps）并非实际的数据类型，而是一组基于 [String 类型](/docs/CS/DB/Redis/struct/SDS.md) 定义的面向位的操作。
由于字符串是二进制安全的 blob，最大长度为 512 MB，因此它们适合设置最多 2^32 个不同的位。

位图的最大优势之一是它们在存储信息时通常提供极大的空间节省。
例如，在一个由递增用户 ID 表示不同用户的系统中，只需 512 MB 内存就可以记住 40 亿用户的单比特信息（例如，知道用户是否愿意接收新闻通讯）。

位图可以轻松地拆分为多个键，例如为了分片数据集，通常最好避免使用巨大的键。
要将位图分散到不同键上，而不是将所有位设置到一个键中，一个简单的策略就是每个键存储 M 位，用 `bit-number/M` 获取键名，用 `bit-number MOD M` 获取键内的第 N 位。

## 命令

查看帮助：

```shell
help @string
```

```shell
SETBIT key offset value
```

## 链接

- [Redis 数据结构](/docs/CS/DB/Redis/struct/struct.md?id=hashes)
