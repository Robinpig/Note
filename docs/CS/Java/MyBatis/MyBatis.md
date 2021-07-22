## Introduction



- [MyBatis](https://mybatis.org/mybatis-3/) is a first class persistence framework with support for custom SQL, stored procedures and advanced mappings. 
- MyBatis eliminates almost all of the JDBC code and manual setting of parameters and retrieval of results. 
- MyBatis can use simple XML or Annotations for configuration and map primitives, Map interfaces and Java POJOs (Plain Old Java Objects) to database records.

Compare with Hibernate



|      | MyBatis            | Hibernate      |
| ---- | ------------------ | -------------- |
| DB   | Depend on DB       | Undependent DB |
| SQL  | write SQL manually | Less SQL       |
|      |                    |                |





### Architecture

| 类名                     | 说明                                                         |
| ------------------------ | ------------------------------------------------------------ |
| MapperProxy              | 用于实现动态代理，是InvocationHandler接口的实现类。          |
| MapperMethod             | 主要作用是将我们定义的接口方法转换成MappedStatement对象。    |
| DefaultSqlSession        | 默认会话                                                     |
| CachingExecutor          | 二级缓存执行器（这里没有用到）                               |
| BaseExecutor             | 抽像类，基础执行器，包括一级缓存逻辑在此实现                 |
| SimpleExecutor           | 可以理解成默认执行器                                         |
| JdbcTransaction          | 事物管理器，会话当中的连接由它负责                           |
| PooledDataSource         | myBatis自带的默认连接池数据源                                |
| UnpooledDataSource       | 用于一次性获取连接的数据源                                   |
| StatementHandler         | SQL执行处理器                                                |
| RoutingStatementHandler  | 用于根据 MappedStatement 的执行类型确定使用哪种处理器：如STATEMENT（单次执行）、PREPARED(预处理)、CALLABLE（存储过程） |
| BaseStatementHandler     | StatementHandler基础类                                       |
| PreparedStatementHandler | Sql预处理执行器                                              |
| ConnectionLogger         | 用于记录Connection对像的方法调用日志。                       |
| DefaultParameterHandler  | 默认预处理器实现                                             |
| BaseTypeHandler          | java类型与JDBC类型映射处理基础类                             |
| IntegerTypeHandler       | Integer与JDBC类型映射处理                                    |
| PreparedStatementLogger  | 用于记录PreparedStatement对像方法调用日志。                  |

## Infrastructure

#### [Reflector](/docs/CS/Java/MyBatis/Reflector.md)

`Reflector class represents a cached set of class definition information that allows for easy mapping between property names and getter/setter methods.`





## Execute

### [Executor](/docs/CS/Java/MyBatis/Executor.md) 

##### [StatementHandler](/docs/CS/Java/MyBatis/StatementHandler.md)

##### ParameterHandler

##### [ResultSetHandler](/docs/CS/Java/MyBatis/ResultSetHandler.md) 





#### Type Transfer



#### [Log](/docs/CS/Java/MyBatis/Log.md) 

`Log provide log4j log4j2 slf4j jdklog and so on`



#### load Resources



#### Interceptor




#### [Init](/docs/CS/Java/MyBatis/Init.md) 

`Load Mybatis-config.xml, create Configuration and SqlsessionFactory`



#### Build




#### Plugins



### 接口层


##### [Logging](/docs/CS/Java/MyBatis/Logging.md) 

