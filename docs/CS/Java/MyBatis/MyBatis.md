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

#### [Reflector](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Reflector.md)

`Reflector class represents a cached set of class definition information that allows for easy mapping between property names and getter/setter methods.`

#### Type Transfer



#### [Log](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Log.md) 

`Log provide log4j log4j2 slf4j jdklog and so on`



#### load Resources



#### Interceptor




#### [Init](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Init.md) 

`Load Mybatis-config.xml, create Configuration and SqlsessionFactory`



#### Build

#### 

#### Execute

##### [Executor](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Executor.md) 

##### [StatementHandler](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/StatementHandler.md)

##### ParameterHandler

##### [ResultSetHandler](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/ResultSetHandler.md) 


#### Plugins



### 接口层


##### [Logging](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Logging.md) 


