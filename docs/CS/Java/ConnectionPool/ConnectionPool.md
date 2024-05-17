## Introduction



Connection pooling is a well-known data access pattern. 
Its main purpose is to reduce the overhead involved in performing database connections and read/write database operations.
**At the most basic level,** **a connection pool is a database connection cache implementation** that can be configured to suit specific requirements.

## Connection Management

maximum/minimum connection

MinIdle

fixed pool: minIdle == maxPoolSize

IdleTimeout

MaxLifetime

#### pool-locking

The prospect of "pool-locking" has been raised with respect to single actors that acquire many connections. This is largely an application-level issue.
Increasing the pool size can alleviate lockups in these scenarios, but we would urge you to examine first what can be done at the application level.

### connect timeout

leak connections

### keepalive

statement execute timeout

Test connections with isValid() before returning them from the pool

socket timeout

link [TCP keepalive](/docs/CS/CN/TCP/TCP.md?id=keepalive)

### maxLifetime

## Advanced

log: tracing

### Cache Management

cache: statement

### Connection Issues

> [Connect Java to a MySQL database Stack Overflow](https://stackoverflow.com/questions/2839321/connect-java-to-a-mysql-database/2840358#2840358)
>
> If you get a SQLException: Connection refused or Connection timed out or a MySQL specific CommunicationsException:
> Communications link failure, then it means that the DB isn't reachable at all.
>
> This can have one or more of the following causes:
>
> 1. IP address or hostname in JDBC URL is wrong.
> 2. Hostname in JDBC URL is not recognized by local DNS server.
> 3. Port number is missing or wrong in JDBC URL.
> 4. DB server is down.
> 5. DB server doesn't accept TCP/IP connections.
> 6. DB server has run out of connections.
> 7. Something in between Java and DB is blocking connections, e.g. a firewall or proxy.
>
> To solve the one or the other, follow the following advices:
>
> 1. Verify and test them with ping.
> 2. Refresh DNS or use IP address in JDBC URL instead.
> 3. Verify it based on my.cnf of MySQL DB.
> 4. Start the DB.
> 5. Verify if mysqld is started without the --skip-networking option.
> 6. Restart the DB and fix your code accordingly that it closes connections in finally.
> 7. Disable firewall and/or configure firewall/proxy to allow/forward the port.

### Dynamic Configuration

## JDBC Connection Pooling Frameworks

[Apache Commons DBCP](/docs/CS/Java/ConnectionPool/DBCP.md)

[HikariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)

[Druid](/docs/CS/Java/ConnectionPool/Druid.md)

## Links

　