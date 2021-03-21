# IO

操作一块数据要好过一系列单个字节

ByteArrayInputStream和ByteArrayOutputStream类时，微妙的问题更多。首先，这些类基本上就是大的内存缓冲区。在很多情况下，用缓冲管理器流包装它们，意味着数据会被复制两次：一次是缓冲在过滤器流中，一次是缓冲在ByteArrayInputStream中（输出流的情况相反）

对于压缩和编解码时应予以缓冲流

- 字符流的速度比字节流快
- 本身是有缓存(ByteArrayOutputStream)的加上Buffer多复制一次会降低性能
- 慎用压缩功能 可能更慢