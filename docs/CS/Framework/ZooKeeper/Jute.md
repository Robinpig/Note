## Introduction



协议位于jute module下



ZooKeeper 在实现序列化的时候要实现 Record 接口，而在 Record 接口的内部，真正起作用的是两个工具类，分别是 OutPutArchive 和 InputArchive

```java
@InterfaceAudience.Public
public interface Record {
    void serialize(OutputArchive archive, String tag) throws IOException;
    void deserialize(InputArchive archive, String tag) throws IOException;
}
```



OutPutArchive 是一个接口，规定了一系列序列化相关的操作。而要实现具体的相关操作



在 Jute 中实现 Binary 序列化方式的类是 BinaryOutputArchive。该 BinaryOutputArchive  类通过实现 OutPutArchive 接口，在 Jute 框架采用二进制的方式实现序列化的时候，采用其作为具体的实现类



```java
    public void writeString(String s, String tag) throws IOException {
        if (s == null) {
            writeInt(-1, "len");
            return;
        }
        ByteBuffer bb = stringToByteBuffer(s);
        int strLen = bb.remaining();
        writeInt(strLen, "len");
        out.write(bb.array(), bb.position(), bb.limit());
        dataSize += strLen;
    }
```

在调用 BinaryOutputArchive 类的 stringToByteBuffer  方法时，在将字符串转化成二进制字节流的过程中，首选将字符串转化成字符数组 CharSequence 对象，并根据 ascii  编码判断字符类型，如果是字母等则使用1个 byte 进行存储。如果是诸如 “¥” 等符号则采用两个 byte 进程存储。如果是汉字则采用3个  byte 进行存储

```java
public class BinaryOutputArchive implements OutputArchive {
    private ByteBuffer bb = ByteBuffer.allocate(1024);

	private ByteBuffer stringToByteBuffer(CharSequence s) {
        bb.clear();
        final int len = s.length();
        for (int i = 0; i < len; i++) {
            if (bb.remaining() < 3) {
                ByteBuffer n = ByteBuffer.allocate(bb.capacity() << 1);
                bb.flip();
                n.put(bb);
                bb = n;
            }
            char c = s.charAt(i);
            if (c < 0x80) {
                bb.put((byte) c);
            } else if (c < 0x800) {
                bb.put((byte) (0xc0 | (c >> 6)));
                bb.put((byte) (0x80 | (c & 0x3f)));
            } else {
                bb.put((byte) (0xe0 | (c >> 12)));
                bb.put((byte) (0x80 | ((c >> 6) & 0x3f)));
                bb.put((byte) (0x80 | (c & 0x3f)));
            }
        }
        bb.flip();
        return bb;
    }
}
```







## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)