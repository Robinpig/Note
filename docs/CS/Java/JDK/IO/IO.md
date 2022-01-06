

## Introduction

操作一块数据要好过一系列单个字节

ByteArrayInputStream和ByteArrayOutputStream类时，微妙的问题更多。首先，这些类基本上就是大的内存缓冲区。在很多情况下，用缓冲管理器流包装它们，意味着数据会被复制两次：一次是缓冲在过滤器流中，一次是缓冲在ByteArrayInputStream中（输出流的情况相反）

对于压缩和编解码时应予以缓冲流

- 字符流的速度比字节流快
- 本身是有缓存(ByteArrayOutputStream)的加上Buffer多复制一次会降低性能
- 慎用压缩功能 可能更慢

Byte read 8 bit for once

Char read 1 char depends on encoding

| from/to | byte         | char   |
| ------- | ------------ | ------ |
| Input   | InuputStream | Reader |
| Output  | OutputStream | Writer |



TelnetInputStream

only ByteArray or Buffered support mark



```java
void flush()
```





## write

### BIO

BIO的文件写`FileOutputStream#write`最终会调用到native层的`io_util.c#writeBytes`方法

```cpp
void
writeBytes(JNIEnv *env, jobject this, jbyteArray bytes,
           jint off, jint len, jboolean append, jfieldID fid)
{
    jint n;
    char stackBuf[BUF_SIZE];
    char *buf = NULL;
    FD fd;

 	...

    // 如果写入长度为0，直接返回0
    if (len == 0) {
        return;
    } else if (len > BUF_SIZE) {
        // 如果写入长度大于BUF_SIZE（8192），无法使用栈空间buffer
        // 需要调用malloc在堆空间申请buffer
        buf = malloc(len);
        if (buf == NULL) {
            JNU_ThrowOutOfMemoryError(env, NULL);
            return;
        }
    } else {
        buf = stackBuf;
    }

    // 复制Java传入的byte数组数据到C空间的buffer中
    (*env)->GetByteArrayRegion(env, bytes, off, len, (jbyte *)buf);
 	
     if (!(*env)->ExceptionOccurred(env)) {
        off = 0;
        while (len > 0) {
            fd = GET_FD(this, fid);
            if (fd == -1) {
                JNU_ThrowIOException(env, "Stream Closed");
                break;
            }
            //写入到文件，这里传递的数组是我们新创建的buf
            if (append == JNI_TRUE) {
                n = (jint)IO_Append(fd, buf+off, len);
            } else {
                n = (jint)IO_Write(fd, buf+off, len);
            }
            if (n == JVM_IO_ERR) {
                JNU_ThrowIOExceptionWithLastError(env, "Write error");
                break;
            } else if (n == JVM_IO_INTR) {
                JNU_ThrowByName(env, "java/io/InterruptedIOException", NULL);
                break;
            }
            off += n;
            len -= n;
        }
    }
}
```

`GetByteArrayRegion`其实就是对数组进行了一份拷贝，该函数的实现在jni.cpp宏定义中，找了很久才找到

```cpp
//jni.cpp
JNI_ENTRY(void, \
jni_Get##Result##ArrayRegion(JNIEnv *env, ElementType##Array array, jsize start, \
             jsize len, ElementType *buf)) \
 ...
      int sc = TypeArrayKlass::cast(src->klass())->log2_element_size(); \
      //内存拷贝
      memcpy((u_char*) buf, \
             (u_char*) src->Tag##_at_addr(start), \
             len << sc);                          \
...
  } \
JNI_END
```

可以看到，传统的BIO，在native层真正写文件前，会在堆外内存（c分配的内存）中对字节数组拷贝一份，之后真正IO时，使用的是堆外的数组。





### NIO

In `IOUtil.write()`

1. `if (src instanceof DirectBuffer)`, `writeFromNativeBuffer`
2. Else  copy to directBuffer from `getTemporaryDirectBuffer`

```java
static int write(FileDescriptor fd, ByteBuffer src, long position,
                 NativeDispatcher nd)
    throws IOException
{
    if (src instanceof DirectBuffer)
        return writeFromNativeBuffer(fd, src, position, nd);

    // Substitute a native buffer
    int pos = src.position();
    int lim = src.limit();
    assert (pos <= lim);
    int rem = (pos <= lim ? lim - pos : 0);
  //not DirectBuffer will 
    ByteBuffer bb = Util.getTemporaryDirectBuffer(rem);
    try {
        bb.put(src);
        bb.flip();
        // Do not update src until we see how many bytes were written
        src.position(pos);

        int n = writeFromNativeBuffer(fd, bb, position, nd);
        if (n > 0) {
            // now update src
            src.position(pos + n);
        }
        return n;
    } finally {
        Util.offerFirstTemporaryDirectBuffer(bb);
    }
}

public static ByteBuffer getTemporaryDirectBuffer(int size) {
    if (isBufferTooLarge(size)) {
        return ByteBuffer.allocateDirect(size);
    }

    BufferCache cache = bufferCache.get();
    ByteBuffer buf = cache.get(size);
    if (buf != null) {
        return buf;
    } else {
        // No suitable buffer in the cache so we need to allocate a new
        // one. To avoid the cache growing then we remove the first
        // buffer from the cache and free it.
        if (!cache.isEmpty()) {
            buf = cache.removeFirst();
            free(buf);
        }
      //Releases a temporary buffer by returning to the cache or freeing it.
        return ByteBuffer.allocateDirect(size);
    }
}
```



## NIO

### Buffer

### Channel

A socket will have a channel if, and only if, the channel itself was created via the `SocketChannel.open` or `ServerSocketChannel.accept` methods.

### Selector

 

## AIO