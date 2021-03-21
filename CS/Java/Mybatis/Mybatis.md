# Mybatis



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



#### 资源加载

Mybatis 对类加载器进行了封装, 用来确定类加载器的使用顺序, 用来记载类文件以及其它资源文件, 感兴趣可以参考 **ClassLoaderWrapper**

#### 解析器模块

解析器模块主要提供了两个功能, 一个是封装了 XPath 类, 在 Mybatis 初始化时解析 Mybatis-config.xml 配置文件以及映射配置文件提供功能, 另一点就是处理动态 SQL 语句的占位符提供帮助



#### [Init](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Init.md) 

`Load Mybatis-config.xml, create Configuration and SqlsessionFactory`



#### Build

#### 

#### Execute

##### [Executor](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/Executor.md) 



##### [StatementHandler](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/StatementHandler.md) 



##### ParameterHandler

##### [ResultSetHandler](https://github.com/Robinpig/Note/blob/master/CS/Java/Mybatis/ResultSetHandler.md) 

Executor 负责维护 **一级、二级缓存以及事务提交回滚操作**, 举个查询的例子, 查询请求会由 Executor 交给 StatementHandler 完成

StatementHandler 通过 ParameterHandler 完成 **SQL 语句的实参绑定**, 通过 java.sql.Statement 执行 SQL 语句并拿到对应的 **结果集映射**

最后交由 ResultSetHandler 对结果集进行解析, 将 JDBC 类型转换为程序自定义的对象

#### 插件

插件模块是 Mybatis 提供的一层扩展, 可以针对 SQL 执行的四大对象进行 **拦截并执行自定义插件**

插件编写需要很熟悉 Mybatis 运行机制, 这样才能控制编写的插件安全、高效

### 接口层





