## Introduction

基于 Apache Commons-pool2
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

对于许多应用程序，最好使用连接池。

使用 `JedisPool` 实例，可以通过 try-with-resources 块获取连接并运行 Redis 命令。

```
JedisPool pool = new JedisPool("localhost", 6379);
try (Jedis jedis = pool.getResource()) {
  jedis.set("clientName", "Jedis");
}
```

BinaryJedis

对于许多应用程序，最好使用连接池。

Sentinel

JedisCluster

## Tuning

JedisConnectionException: Could not get a resource from the pool

此类异常的原因不一定是资源池不够大 建议从网络、资源池参数设置、资源池监控（如果对JMX监控）、代码（例如没执行jedis.close()）、慢查询、DNS等方面进行排查。

JedisPool定义最大资源数、最小空闲资源数时，不会在连接池中创建Jedis连接。初次使用时，池中没有资源使用则会先新建一个new Jedis，使用后再放入资源池，该过程会有一定的时间开销，所以建议在定义JedisPool后，以最小空闲数量为基准对JedisPool进行预热

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)

## References
