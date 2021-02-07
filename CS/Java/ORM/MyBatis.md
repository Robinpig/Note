# MyBatis

## 简述



SqlSessionFactory

SqlSession

Mapper

## SqlSessionFactory

## SqlSession

## Mapper

Mapper接口

MapperProxy.newInstance()生成JDK动态代理对象

## 工作流程

详细流程如下：

- 加载mybatis全局配置文件（数据源、mapper映射文件等），解析配置文件，MyBatis基于XML配置文件生成Configuration，和一个个MappedStatement（包括了参数映射配置、动态SQL语句、结果映射配置），其对应着<select | update | delete | insert>标签项。

- SqlSessionFactoryBuilder通过Configuration对象生成SqlSessionFactory，用来开启SqlSession。
- SqlSession对象完成和数据库的交互：
  - 用户程序调用mybatis接口层api（即Mapper接口中的方法）
  - SqlSession通过调用api的Statement ID找到对应的MappedStatement对象
  - 通过Executor（负责动态SQL的生成和查询缓存的维护）将MappedStatement对象进行解析，sql参数转化、动态sql拼接，生成jdbc Statement对象
  - JDBC执行sql.
  - 借助MappedStatement中的结果映射关系，将返回结果转化成HashMap、JavaBean等存储结构并返回。

## 源码分析

### openSessionFromDataSource方法

 

```java
private SqlSession openSessionFromDataSource(ExecutorType execType, TransactionIsolationLevel level, boolean autoCommit) {  
    Connection connection = null;    
    try {       
        final Environment environment = configuration.getEnvironment();     
        final DataSource dataSource = getDataSourceFromEnvironment(environment);        
        TransactionFactory transactionFactory = getTransactionFactoryFromEnvironment(environment);       
        connection = dataSource.getConnection();                                         
        if (level != null) { 
        connection.setTransactionIsolation(level.getLevel());       
    }      
        connection = wrapConnection(connection);       
        Transaction tx = transactionFactory.newTransaction(connection, autoCommit);       
        Executor executor = configuration.newExecutor(tx, execType);        
        return new DefaultSqlSession(configuration, executor, autoCommit);    
    } catch (Exception e) {       
        closeConnection(connection);       
        throw ExceptionFactory.wrapException("Error opening session.  Cause: " + e, e);   
    } finally {       
        ErrorContext.instance().reset();     
    }    
}  
```



 

这里我们分析一下这里所涉及的步骤：

（1）获取前面我们加载配置文件的环境信息，并且获取环境信息中配置的数据源。

（2）通过数据源获取一个连接，对连接进行包装代理（通过JDK的代理来实现日志功能）。

（3）设置连接的事务信息（是否自动提交、事务级别），从配置环境中获取事务工厂，事务工厂获取一个新的事务。

（4）传入事务对象获取一个新的执行器，并传入执行器、配置信息等获取一个执行会话对象。

 

从上面的代码我们可以得出，一次配置加载只能有且对应一个数据源。对于上述步骤，我们不难理解，我们重点看看新建执行器和DefaultSqlSession。

### newExecutor方法

 

Java代码  

```java
public Executor newExecutor(Transaction transaction, ExecutorType executorType) { 
    executorType = executorType == null ? defaultExecutorType : executorType;     
    executorType = executorType == null ? ExecutorType.SIMPLE : executorType;     
    Executor executor;    
    if (ExecutorType.BATCH == executorType) {     
        executor = new BatchExecutor(this, transaction);  
    } else if (ExecutorType.REUSE == executorType) {       
        executor = new ReuseExecutor(this, transaction);    
    } else {      
        executor = new SimpleExecutor(this, transaction);    
    }    
    if (cacheEnabled) {      
        executor = new CachingExecutor(executor);    
    }    
    executor = (Executor) interceptorChain.pluginAll(executor);    
    return executor;  
}  
```



上面代码的执行步骤如下：

（1）判断执行器类型，如果配置文件中没有配置执行器类型，则采用默认执行类型ExecutorType.SIMPLE。

（2）根据执行器类型返回不同类型的执行器（执行器有三种，分别是 BatchExecutor、SimpleExecutor和CachingExecutor，后面我们再详细看看）。

（3）跟执行器绑定拦截器插件（这里也是使用代理来实现）。

 

### DefaultSqlSession

DefaultSqlSession实现了SqlSession接口，里面有各种各样的SQL执行方法，主要用于SQL操作的对外接口，它会的调用执行器来执行实际的SQL语句。

 

接下来我们看看SQL查询是怎么进行的

```java
UserInfo user = (UserInfo) session.selectOne("User.selectUser", "1");  
```





 实际调用的是DefaultSqlSession类的**selectOne**方法，该方法代码如下：

```java
public Object selectOne(String statement, Object parameter) { 
    // Popular vote was to return null on 0 results and throw exception on too many.     
    List list = selectList(statement, parameter);      
    if (list.size() == 1) {       
        return list.get(0);     
    } else if (list.size() > 1) { 
        throw new TooManyResultsException("Expected one result (or null) to be returned by selectOne(), but found: " + list.size());     
    } else {       
        return null;      
    }   
}  
```

 



```java
public List selectList(String statement, Object parameter) {
    return selectList(statement, parameter, RowBounds.DEFAULT);   
}     
public List selectList(String statement, Object parameter, RowBounds rowBounds) { 
    try {        
        MappedStatement ms = configuration.getMappedStatement(statement);        
        return executor.query(ms, wrapCollection(parameter), rowBounds, Executor.NO_RESULT_HANDLER);      
    } catch (Exception e) {        
        throw ExceptionFactory.wrapException("Error querying database.  Cause: " + e, e);      } finally {       
        ErrorContext.instance().reset();      
    }    
}  
```



 

第二个selectList的执行步骤如下：

（1）根据SQL的ID到配置信息中找对应的MappedStatement，在之前配置被加载初始化的时候我们看到了系统会把配置文件中的SQL块解析并放到一个MappedStatement里面，并将MappedStatement对象放到一个Map里面进行存放，Map的key值是该SQL块的ID。

（2）调用执行器的query方法，传入MappedStatement对象、SQL参数对象、范围对象（此处为空）和结果处理方式。

 

好了，目前只剩下一个疑问，那就是执行器到底怎么执行SQL的呢？

 

上面我们知道了，默认情况下是采用SimpleExecutor执行的，我们看看这个类的doQuery方法：

```java
public List doQuery(MappedStatement ms, Object parameter, RowBounds rowBounds, ResultHandler resultHandler) throws SQLException {  

   Statement stmt = null;  

   try {  

     Configuration configuration = ms.getConfiguration();  

    StatementHandler handler = configuration.newStatementHandler(this, ms, parameter, rowBounds, resultHandler);  
      stmt = prepareStatement(handler);  
     return handler.query(stmt, resultHandler);  
    } finally {  

     closeStatement(stmt);  
	   }  

  } 
```


doQuery方法的内部执行步骤：

（1） 获取配置信息对象。

（2）通过配置对象获取一个新的StatementHandler，该类主要用来处理一次SQL操作。

（3）预处理StatementHandler对象，得到Statement对象。

（4）传入Statement和结果处理对象，通过StatementHandler的query方法来执行SQL，并对执行结果进行处理。



### newStatementHandler方法

 



上面代码的执行步骤：

（1）根据相关的参数获取对应的StatementHandler对象。

（2）为StatementHandler对象绑定拦截器插件。

 

RoutingStatementHandler类的构造方法RoutingStatementHandler如下：

```java
public RoutingStatementHandler(Executor executor, MappedStatement ms, Object parameter, RowBounds rowBounds, ResultHandler resultHandler) {
    switch (ms.getStatementType()) {
        case STATEMENT:         
            delegate = new SimpleStatementHandler(executor, ms, parameter, rowBounds, resultHandler);         
            break;       
        case PREPARED:         
            delegate = new PreparedStatementHandler(executor, ms, parameter, rowBounds, resultHandler);         
            break;       
        case CALLABLE:         
            delegate = new CallableStatementHandler(executor, ms, parameter, rowBounds, resultHandler);        
            break;      
        default:        
            throw new ExecutorException("Unknown statement type: " + ms.getStatementType());     
    }     
}  
```



根据 MappedStatement对象的StatementType来创建不同的StatementHandler，这个跟前面执行器的方式类似。StatementType有STATEMENT、PREPARED和CALLABLE三种类型，跟JDBC里面的Statement类型一一对应。

 

我们看一下prepareStatement方法具体内容：



Java代码  

```java
private Statement prepareStatement(StatementHandler handler) throws SQLException {     
    Statement stmt;     
    Connection connection = transaction.getConnection();     //从连接中获取Statement对象     stmt = handler.prepare(connection);     //处理预编译的传入参数     handler.parameterize(stmt);     return stmt;   }  
```