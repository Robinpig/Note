## Introduction

Based on Apache Commons-pool2
```
GenericObjectPoolConfig jedisPoolConfig = new GenericObjectPoolConfig();
jedisPoolConfig.setMaxTotal(...);
jedisPoolConfig.setMaxIdle(...);
jedisPoolConfig.setMinIdle(...);
jedisPoolConfig.setMaxWaitMillis(...);
```

```java
public class JedisPoolConfig extends GenericObjectPoolConfig {
  public JedisPoolConfig() {
    setTestWhileIdle(true);
    setMinEvictableIdleTimeMillis(60000);
    setTimeBetweenEvictionRunsMillis(30000);
    setNumTestsPerEvictionRun(-1);
    }
}
```

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

## Tuning

JedisConnectionException: Could not get a resource from the pool

此类异常的原因不一定是资源池不够大 建议从网络、资源池参数设置、资源池监控（如果对JMX监控）、代码（例如没执行jedis.close()）、慢查询、DNS等方面进行排查。


JedisPool定义最大资源数、最小空闲资源数时，不会在连接池中创建Jedis连接。初次使用时，池中没有资源使用则会先新建一个new Jedis，使用后再放入资源池，该过程会有一定的时间开销，所以建议在定义JedisPool后，以最小空闲数量为基准对JedisPool进行预热



## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References
