# MyBatis



## Introduction



- [MyBatis](https://mybatis.org/mybatis-3/) is a first class persistence framework with support for custom SQL, stored procedures and advanced mappings. 
- MyBatis eliminates almost all of the JDBC code and manual setting of parameters and retrieval of results. 
- MyBatis can use simple XML or Annotations for configuration and map primitives, Map interfaces and Java POJOs (Plain Old Java Objects) to database records.


Compare with Hibernate

- Mybatis
    - programmers need to write SQL 
    - SQL may not work if DataBase changed
- Hibernate
    - programmers not need to write SQL
    - absolutely a ORM framework



## Architecture



### Infrastructure

#### [Reflector](/docs/CS/Java/MyBatis/Reflector.md)

`Reflector class represents a cached set of class definition information that allows for easy mapping between property names and getter/setter methods.`

#### Type Transfer



#### [Log](/docs/CS/Java/MyBatis/Log.md) 

`Log provide log4j log4j2 slf4j jdklog and so on`



#### load Resources



#### Interceptor




#### [Init](/docs/CS/Java/MyBatis/Init.md) 

`Load Mybatis-config.xml, create Configuration and SqlsessionFactory`



#### Build

#### 

#### Execute

##### [Executor](/docs/CS/Java/MyBatis/Executor.md) 

##### [StatementHandler](/docs/CS/Java/MyBatis/StatementHandler.md)

##### ParameterHandler

##### [ResultSetHandler](/docs/CS/Java/MyBatis/ResultSetHandler.md) 


#### Plugins



### 接口层


##### [Logging](/docs/CS/Java/MyBatis/Logging.md) 


