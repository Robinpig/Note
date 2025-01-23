## Introduction




协议位于jute module下

```java
@InterfaceAudience.Public
public interface Record {
    void serialize(OutputArchive archive, String tag) throws IOException;
    void deserialize(InputArchive archive, String tag) throws IOException;
}
```


## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)