## Introduction




For many applications, it's best to use a connection pool.

With a `JedisPool` instance, you can use a [try-with-resources](https://docs.oracle.com/javase/tutorial/essential/exceptions/tryResourceClose.html) block to get a connection and run Redis commands.

```
JedisPool pool = new JedisPool("localhost", 6379);
try (Jedis jedis = pool.getResource()) {
  jedis.set("clientName", "Jedis");
}
```


BinaryJedis





For many applications, it's best to use a connection pool.

Sentinel

JedisCluster

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References
