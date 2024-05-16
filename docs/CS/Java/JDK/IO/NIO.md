## Introduction

*Java* *NIO* (New IO) is an alternative IO API for Java. Note: Sometimes NIO is claimed to mean *Non-blocking IO* . However, this is not what NIO meant originally. Also, parts of the NIO APIs are actually blocking - e.g. the file APIs - so the label "Non-blocking" would be slightly misleading.

The table below summarizes the main differences between Java NIO and IO.

| IO              | NIO             |
| --------------- | --------------- |
| Stream oriented | Buffer oriented |
| Blocking IO     | Non blocking IO |
|                 | Selectors       |

## Non-blocking IO

Java NIO enables you to do non-blocking IO. For instance, a thread can ask a channel to read data into a buffer. While the channel reads data into the buffer, the thread can do something else. Once data is read into the buffer, the thread can then continue processing it. The same is true for writing data to channels.

## Channels and Buffers

In NIO you work with channels and buffers. Data is always read from a channel into a buffer, or written from a buffer to a channel.

### Channels

Java NIO Channels are similar to streams with a few differences:

* You can both read and write to a Channels. Streams are typically one-way (read or write).
* Channels can be read and written asynchronously.
* Channels always read to, or write from, a Buffer.

Here are the most important Channel implementations in Java NIO:

* FileChannel
* DatagramChannel
* SocketChannel
* ServerSocketChannel

### Buffers

A buffer is essentially a block of memory into which you can write data, which you can then later read again. This memory block is wrapped in a NIO Buffer object, which provides a set of methods that makes it easier to work with the memory block.




directBuffer

mapped memory

#### Capacity, Position and Limit

position<=limit<=capacity

Using a** **`Buffer` to read and write data typically follows this little 4-step process:

1. Write data into the Buffer
2. Call** **`buffer.flip()`
3. Read data out of the Buffer
4. Call** **`buffer.clear()` or** **`buffer.compact()`

## Selectors

A selector is an object that can monitor multiple channels for events (like: connection opened, data arrived etc.). Thus, a single thread can monitor multiple channels for data.

轮询注册的channel状态
SelectorProvider sychronized 单例
依据不同JDK生成不同的Selector实现类
调用OS的接口创建FD

### SelectorProvider

```java
//java.nio.channels.spi.SelectorProvider#provider()
public static SelectorProvider provider() {
        synchronized (lock) {
            if (provider != null)
                return provider;
            return AccessController.doPrivileged(
                new PrivilegedAction<SelectorProvider>() {
                    public SelectorProvider run() {
                            if (loadProviderFromProperty())
                                return provider;
                            if (loadProviderAsService())
                                return provider;
                            provider = sun.nio.ch.DefaultSelectorProvider.create();
                            return provider;
                        }
                    });
        }
    }

//sun.nio.ch.DefaultSelectorProvider.create()
public static SelectorProvider create() {
        String osname = AccessController
            .doPrivileged(new GetPropertyAction("os.name"));
        if (osname.equals("SunOS"))
            return createProvider("sun.nio.ch.DevPollSelectorProvider");
        if (osname.equals("Linux"))
            return createProvider("sun.nio.ch.EPollSelectorProvider");
        return new sun.nio.ch.PollSelectorProvider();
    }
```

See [Netty EventLoop - Selector](/docs/CS/Java/Netty/EventLoop.md?id=Selector).

## Links

## Reference

1. [Java NIO Tutorial](http://tutorials.jenkov.com/java-nio/index.html)
