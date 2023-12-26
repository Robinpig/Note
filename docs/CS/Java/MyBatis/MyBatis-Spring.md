## Introduction

## Transaction

<div style="text-align: center;">

![Fig.1. Transaction Organization](img/transaction.png)

</div>

<p style="text-align: center;">
Fig.1. Transaction Organization.
</p>

```java
public class SpringManagedTransactionFactory implements TransactionFactory {

    @Override
    public Transaction newTransaction(DataSource dataSource, TransactionIsolationLevel level, boolean autoCommit) {
        return new SpringManagedTransaction(dataSource);
    }
  
    @Override
    public Transaction newTransaction(Connection conn) {
        throw new UnsupportedOperationException("New Spring transactions require a DataSource");
    }
  
    @Override
    public void setProperties(Properties props) {
        // not needed in this version
    }
}
```

SpringManagedTransaction handles the lifecycle of a JDBC connection. It retrieves a connection from Spring's transaction manager and returns it back to it when it is no longer needed.
If Spring's transaction handling is active it will no-op all commit/rollback/close calls assuming that the Spring transaction manager will do the job.
If it is not it will behave like JdbcTransaction.

```java
public class SpringManagedTransaction implements Transaction {

  private final DataSource dataSource;

  private Connection connection;

  private boolean isConnectionTransactional;

  private boolean autoCommit;
...
}
```

Helper class that provides static methods for obtaining JDBC Connections from a DataSource.
Includes special support for Spring-managed transactional Connections, e.g. managed by DataSourceTransactionManager or org.springframework.transaction.jta.JtaTransactionManager.
Used internally by Spring's org.springframework.jdbc.core.JdbcTemplate, Spring's JDBC operation objects and the JDBC DataSourceTransactionManager.
Can also be used directly in application code.

```java
// org.springframework.jdbc.datasource.DataSourceUtils
public static Connection doGetConnection(DataSource dataSource) throws SQLException {
   ConnectionHolder conHolder = (ConnectionHolder) TransactionSynchronizationManager.getResource(dataSource);
   if (conHolder != null && (conHolder.hasConnection() || conHolder.isSynchronizedWithTransaction())) {
      conHolder.requested();
      if (!conHolder.hasConnection()) {
         logger.debug("Fetching resumed JDBC Connection from DataSource");
         conHolder.setConnection(fetchConnection(dataSource));
      }
      return conHolder.getConnection();
   }
   // Else we either got no holder or an empty thread-bound holder here.

   Connection con = fetchConnection(dataSource);

   if (TransactionSynchronizationManager.isSynchronizationActive()) {
      try {
         // Use same Connection for further JDBC actions within the transaction.
         // Thread-bound object will get removed by synchronization at transaction completion.
         ConnectionHolder holderToUse = conHolder;
         if (holderToUse == null) {
            holderToUse = new ConnectionHolder(con);
         }
         else {
            holderToUse.setConnection(con);
         }
         holderToUse.requested();
         TransactionSynchronizationManager.registerSynchronization(
               new ConnectionSynchronization(holderToUse, dataSource));
         holderToUse.setSynchronizedWithTransaction(true);
         if (holderToUse != conHolder) {
            TransactionSynchronizationManager.bindResource(dataSource, holderToUse);
         }
      }
      catch (RuntimeException ex) {
         // Unexpected exception from external delegation call -> close Connection and rethrow.
         releaseConnection(con, dataSource);
         throw ex;
      }
   }

   return con;
}
```

```java
// TransactionSynchronizationManager

private static final ThreadLocal<Map<Object, Object>> resources =
			new NamedThreadLocal<>("Transactional resources");


@Nullable
private static Object doGetResource(Object actualKey) {
   Map<Object, Object> map = resources.get();
   if (map == null) {
      return null;
   }
   Object value = map.get(actualKey);
   // Transparently remove ResourceHolder that was marked as void...
   if (value instanceof ResourceHolder && ((ResourceHolder) value).isVoid()) {
      map.remove(actualKey);
      // Remove entire ThreadLocal if empty...
      if (map.isEmpty()) {
         resources.remove();
      }
      value = null;
   }
   return value;
}
```

### ConnectionHolder

Resource holder wrapping a JDBC Connection. DataSourceTransactionManager binds instances of this class to the thread, for a specific javax.sql.DataSource.
Inherits rollback-only support for nested JDBC transactions and reference count functionality from the base class.

```java
public class ConnectionHolder extends ResourceHolderSupport {

   /**
    * Prefix for savepoint names.
    */
   public static final String SAVEPOINT_NAME_PREFIX = "SAVEPOINT_";


   @Nullable
   private ConnectionHandle connectionHandle;

   @Nullable
   private Connection currentConnection;

   private boolean transactionActive = false;

   @Nullable
   private Boolean savepointsSupported;

   private int savepointCounter = 0;
  
}
```

## wrap SqlSession

### SqlSessionTemplate

```java
public class SqlSessionTemplate implements SqlSession, DisposableBean {

  private final SqlSessionFactory sqlSessionFactory;

  private final ExecutorType executorType;

  private final SqlSession sqlSessionProxy;

  private final PersistenceExceptionTranslator exceptionTranslator;
 ...
   
   public SqlSessionTemplate(SqlSessionFactory sqlSessionFactory, ExecutorType executorType,
                             PersistenceExceptionTranslator exceptionTranslator) {
   this.sqlSessionFactory = sqlSessionFactory;
   this.executorType = executorType;
   this.exceptionTranslator = exceptionTranslator;
   this.sqlSessionProxy = (SqlSession) newProxyInstance(
     SqlSessionFactory.class.getClassLoader(),
     new Class[] { SqlSession.class },
     new SqlSessionInterceptor());
 }
}
```

#### SqlSessionInterceptor

Proxy needed to route MyBatis method calls to the proper SqlSession got from Spring's Transaction Manager It also unwraps exceptions thrown by Method#invoke(Object, Object...) to pass a PersistenceException to the PersistenceExceptionTranslator.

```java
private class SqlSessionInterceptor implements InvocationHandler {
  @Override
  public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
    SqlSession sqlSession = getSqlSession(
        SqlSessionTemplate.this.sqlSessionFactory,
        SqlSessionTemplate.this.executorType,
        SqlSessionTemplate.this.exceptionTranslator);
    try {
      Object result = method.invoke(sqlSession, args);
      if (!isSqlSessionTransactional(sqlSession, SqlSessionTemplate.this.sqlSessionFactory)) {
        // force commit even on non-dirty sessions because some databases require
        // a commit/rollback before calling close()
        sqlSession.commit(true);
      }
      return result;
    } catch (Throwable t) {
      Throwable unwrapped = unwrapThrowable(t);
      if (SqlSessionTemplate.this.exceptionTranslator != null && unwrapped instanceof PersistenceException) {
        // release the connection to avoid a deadlock if the translator is no loaded. See issue #22
        closeSqlSession(sqlSession, SqlSessionTemplate.this.sqlSessionFactory);
        sqlSession = null;
        Throwable translated = SqlSessionTemplate.this.exceptionTranslator.translateExceptionIfPossible((PersistenceException) unwrapped);
        if (translated != null) {
          unwrapped = translated;
        }
      }
      throw unwrapped;
    } finally {
      if (sqlSession != null) {
        closeSqlSession(sqlSession, SqlSessionTemplate.this.sqlSessionFactory);
      }
    }
  }
}
```

```java
// DaoSupport implements InitializingBean
@Override
public final void afterPropertiesSet() throws IllegalArgumentException, BeanInitializationException {
   // Let abstract subclasses check their configuration.
   checkDaoConfig();

   // Let concrete implementations initialize themselves.
   try {
      initDao();
   }
   catch (Exception ex) {
      throw new BeanInitializationException("Initialization of DAO failed", ex);
   }
}
```

SqlSessionDaoSupport

```java
public abstract class SqlSessionDaoSupport extends DaoSupport {

  private SqlSessionTemplate sqlSessionTemplate;
...
}
```

BeanFactory that enables injection of MyBatis mapper interfaces. It can be set up with a SqlSessionFactory or a pre-configured SqlSessionTemplate.

```java
public class MapperFactoryBean<T> extends SqlSessionDaoSupport implements FactoryBean<T> {

  private Class<T> mapperInterface;

  private boolean addToConfig = true;
  
  ...
}
```

```java
@Override
protected void checkDaoConfig() {
  super.checkDaoConfig(); // check sqlSessionTemplate not null

  notNull(this.mapperInterface, "Property 'mapperInterface' is required");

  Configuration configuration = getSqlSession().getConfiguration();
  if (this.addToConfig && !configuration.hasMapper(this.mapperInterface)) {
    try {
      configuration.addMapper(this.mapperInterface);
    } catch (Exception e) {
      throw new IllegalArgumentException(e);
    } finally {
      ErrorContext.instance().reset();
    }
  }
}
```

### 1st cache invalid

Because every call will new SqlSession, please use transaction.

## start

![](img/MapperScan.png)


### MapperScan

Use this annotation to register MyBatis mapper interfaces when using Java Config.
It performs when same work as MapperScannerConfigurer via MapperScannerRegistrar.

**Configuration example**:

```java
@Configuration
@MapperScan("org.mybatis.spring.sample.mapper")
public class AppConfig {

    @Bean
    public DataSource dataSource() {
        return new EmbeddedDatabaseBuilder()
                .addScript("schema.sql")
                .addScript("data.sql")
                .build();
    }

    @Bean
    public DataSourceTransactionManager transactionManager() {
        return new DataSourceTransactionManager(dataSource());
    }

    @Bean
    public SqlSessionFactory sqlSessionFactory() throws Exception {
        SqlSessionFactoryBean sessionFactory = new SqlSessionFactoryBean();
        sessionFactory.setDataSource(dataSource());
        return sessionFactory.getObject();
    }
}
```

MapperScannerRegistrar register MapperScannerConfigurer into BeanDefinitionRegistry

```java
public class MapperScannerRegistrar implements ImportBeanDefinitionRegistrar, ResourceLoaderAware {
    void registerBeanDefinitions(AnnotationMetadata annoMeta, AnnotationAttributes annoAttrs,
                                 BeanDefinitionRegistry registry, String beanName) {

        BeanDefinitionBuilder builder = BeanDefinitionBuilder.genericBeanDefinition(MapperScannerConfigurer.class);
        // ...
        registry.registerBeanDefinition(beanName, builder.getBeanDefinition());

    }
}
```

#### processBeanDefinitions

BeanDefinitionRegistryPostProcessor that searches recursively starting from a base package for **interfaces** and registers them as **MapperFactoryBean**.

```java
public class MapperScannerConfigurer
        implements BeanDefinitionRegistryPostProcessor, InitializingBean, ApplicationContextAware, BeanNameAware {
    @Override
    public void postProcessBeanDefinitionRegistry(BeanDefinitionRegistry registry) {
        // ...
        scanner.scan(
                StringUtils.tokenizeToStringArray(this.basePackage, ConfigurableApplicationContext.CONFIG_LOCATION_DELIMITERS));
    }
}
```

This class was a BeanFactoryPostProcessor until 1.0.1 version. It changed to BeanDefinitionRegistryPostProcessor in 1.0.2.
See https://jira.springsource.org/browse/SPR-8269 for the details.



### SpringBoot

Auto-Configuration for Mybatis.
Contributes a **SqlSessionFactory** and a **SqlSessionTemplate**.
If `org.mybatis.spring.annotation.MapperScan` is used, or a configuration file is specified as a property, those will be considered,
otherwise this auto-configuration will attempt to register mappers based on the interface definitions in or under the root auto-configuration package.

```java
@org.springframework.context.annotation.Configuration
@ConditionalOnClass({ SqlSessionFactory.class, SqlSessionFactoryBean.class })
@ConditionalOnSingleCandidate(DataSource.class)
@EnableConfigurationProperties(MybatisProperties.class)
@AutoConfigureAfter(DataSourceAutoConfiguration.class)
public class MybatisAutoConfiguration implements InitializingBean {}
```

```java
// MybatisAutoConfiguration
@Bean
@ConditionalOnMissingBean
public SqlSessionFactory sqlSessionFactory(DataSource dataSource) throws Exception {
  SqlSessionFactoryBean factory = new SqlSessionFactoryBean();
  factory.setDataSource(dataSource);
  factory.setVfs(SpringBootVFS.class);
  if (StringUtils.hasText(this.properties.getConfigLocation())) {
    factory.setConfigLocation(this.resourceLoader.getResource(this.properties.getConfigLocation()));
  }
  applyConfiguration(factory);
  if (this.properties.getConfigurationProperties() != null) {
    factory.setConfigurationProperties(this.properties.getConfigurationProperties());
  }
  if (!ObjectUtils.isEmpty(this.interceptors)) { // set plugins
    factory.setPlugins(this.interceptors);
  }
  if (this.databaseIdProvider != null) {
    factory.setDatabaseIdProvider(this.databaseIdProvider);
  }
  if (StringUtils.hasLength(this.properties.getTypeAliasesPackage())) {
    factory.setTypeAliasesPackage(this.properties.getTypeAliasesPackage());
  }
  if (this.properties.getTypeAliasesSuperType() != null) {
    factory.setTypeAliasesSuperType(this.properties.getTypeAliasesSuperType());
  }
  if (StringUtils.hasLength(this.properties.getTypeHandlersPackage())) {
    factory.setTypeHandlersPackage(this.properties.getTypeHandlersPackage());
  }
  if (!ObjectUtils.isEmpty(this.properties.resolveMapperLocations())) {
    factory.setMapperLocations(this.properties.resolveMapperLocations());
  }

  return factory.getObject();
}
```

## Links

- [MyBatis](/docs/CS/Java/MyBatis/MyBatis.md)
