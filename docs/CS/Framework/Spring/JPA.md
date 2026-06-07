## Introduction

Spring Data JPA 是更大 Spring Data 家族的一部分，使得基于 JPA（Java Persistence API）的仓库实现变得简单。

Spring Data 仓库抽象中的核心接口是 Repository。
它接受要管理的领域类以及领域类的标识符类型作为类型参数。
此接口主要作为标记接口，用于捕获要处理的类型，并帮助你发现扩展此接口的接口。
CrudRepository 和 ListCrudRepository 接口为正在管理的实体类提供了复杂的 CRUD 功能。

常用 JPA 注解

@Entiry
@MappedSuperClass

@Id
@GeneratedValue
@SequenceGenerator

基于注解的 base packages 配置
```java
@Configuration
@EnableJpaRepositories
@EnableTransactionManagement
class ApplicationConfig {

  @Bean
  public DataSource dataSource() {

    EmbeddedDatabaseBuilder builder = new EmbeddedDatabaseBuilder();
    return builder.setType(EmbeddedDatabaseType.HSQL).build();
  }

  @Bean
  public LocalContainerEntityManagerFactoryBean entityManagerFactory() {

    HibernateJpaVendorAdapter vendorAdapter = new HibernateJpaVendorAdapter();
    vendorAdapter.setGenerateDdl(true);

    LocalContainerEntityManagerFactoryBean factory = new LocalContainerEntityManagerFactoryBean();
    factory.setJpaVendorAdapter(vendorAdapter);
    factory.setPackagesToScan("com.acme.domain");
    factory.setDataSource(dataSource());
    return factory;
  }

  @Bean
  public PlatformTransactionManager transactionManager(EntityManagerFactory entityManagerFactory) {

    JpaTransactionManager txManager = new JpaTransactionManager();
    txManager.setEntityManagerFactory(entityManagerFactory);
    return txManager;
  }
}
```

```java
class JpaRepositoriesRegistrar extends RepositoryBeanDefinitionRegistrarSupport {

	@Override
	protected Class<? extends Annotation> getAnnotation() {
		return EnableJpaRepositories.class;
	}

	@Override
	protected RepositoryConfigurationExtension getExtension() {
		return new JpaRepositoryConfigExtension();
	}
}

public abstract class RepositoryBeanDefinitionRegistrarSupport
		implements ImportBeanDefinitionRegistrar, ResourceLoaderAware, EnvironmentAware {

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry,
                                        BeanNameGenerator generator) {
        
        AnnotationRepositoryConfigurationSource configurationSource = new AnnotationRepositoryConfigurationSource(metadata,
                getAnnotation(), resourceLoader, environment, registry, generator);

        RepositoryConfigurationExtension extension = getExtension();
        RepositoryConfigurationUtils.exposeRegistration(extension, registry, configurationSource);

        RepositoryConfigurationDelegate delegate = new RepositoryConfigurationDelegate(configurationSource, resourceLoader,
                environment);

        delegate.registerRepositoriesIn(registry, extension);
    }
}

public class JpaRepositoryConfigExtension extends RepositoryConfigurationExtensionSupport {

    @Override
    public String getRepositoryFactoryBeanClassName() {
        return JpaRepositoryFactoryBean.class.getName();
    }
}
```
lazy get Repository
```java
public class JpaRepositoryFactoryBean<T extends Repository<S, ID>, S, ID>
		extends TransactionalRepositoryFactoryBeanSupport<T, S, ID> {

    public void afterPropertiesSet() {
        this.factory = createRepositoryFactory();
        // ...

        this.repository = Lazy.of(() -> this.factory.getRepository(repositoryInterface, repositoryFragmentsToUse));
        // ...
        if (!lazyInit) {
            this.repository.get();
        }
    }
}
```

创建 repository 的代理对象，添加 processors 的拦截

```java
public abstract class RepositoryFactorySupport implements BeanClassLoaderAware, BeanFactoryAware {
    public <T> T getRepository(Class<T> repositoryInterface, RepositoryFragments fragments) {
        ApplicationStartup applicationStartup = getStartup();
        StartupStep repositoryInit = onEvent(applicationStartup, "spring.data.repository.init", repositoryInterface);
        StartupStep repositoryMetadataStep = onEvent(applicationStartup, "spring.data.repository.metadata",
                repositoryInterface);
        StartupStep repositoryCompositionStep = onEvent(applicationStartup, "spring.data.repository.composition",
                repositoryInterface);

        StartupStep repositoryTargetStep = onEvent(applicationStartup, "spring.data.repository.target",
                repositoryInterface);
        // ...
        
        Object target = getTargetRepository(information);
        // Create proxy
        StartupStep repositoryProxyStep = onEvent(applicationStartup, "spring.data.repository.proxy", repositoryInterface);
        ProxyFactory result = new ProxyFactory();
        result.setTarget(target);
        result.setInterfaces(repositoryInterface, Repository.class, TransactionalProxy.class);

        if (MethodInvocationValidator.supports(repositoryInterface)) {
            result.addAdvice(new MethodInvocationValidator());
        }

        result.addAdvisor(ExposeInvocationInterceptor.ADVISOR);

        if (!postProcessors.isEmpty()) {
            StartupStep repositoryPostprocessorsStep = onEvent(applicationStartup, "spring.data.repository.postprocessors",
                    repositoryInterface);
            postProcessors.forEach(processor -> {

                StartupStep singlePostProcessor = onEvent(applicationStartup, "spring.data.repository.postprocessor",
                        repositoryInterface);
                singlePostProcessor.tag("type", processor.getClass().getName());
                processor.postProcess(result, information);
                singlePostProcessor.end();
            });
            repositoryPostprocessorsStep.end();
        }

        if (DefaultMethodInvokingMethodInterceptor.hasDefaultMethods(repositoryInterface)) {
            result.addAdvice(new DefaultMethodInvokingMethodInterceptor());
        }

        Optional<QueryLookupStrategy> queryLookupStrategy = getQueryLookupStrategy(queryLookupStrategyKey,
                evaluationContextProvider);
        result.addAdvice(new QueryExecutorMethodInterceptor(information, getProjectionFactory(), queryLookupStrategy,
                namedQueries, queryPostProcessors, methodInvocationListeners));

        result.addAdvice(
                new ImplementationMethodExecutionInterceptor(information, compositionToUse, methodInvocationListeners));

        T repository = (T) result.getProxy(classLoader);
        repositoryProxyStep.end();
        repositoryInit.end();

        return repository;
    }
}
```

执行查询和 interceptor

```java
class QueryExecutorMethodInterceptor implements MethodInterceptor {
    public QueryExecutorMethodInterceptor(RepositoryInformation repositoryInformation,
                                          ProjectionFactory projectionFactory, Optional<QueryLookupStrategy> queryLookupStrategy, NamedQueries namedQueries,
                                          List<QueryCreationListener<?>> queryPostProcessors,
                                          List<RepositoryMethodInvocationListener> methodInvocationListeners) {
        // ...
        this.resultHandler = new QueryExecutionResultHandler(RepositoryFactorySupport.CONVERSION_SERVICE);
        this.queries = queryLookupStrategy //
                .map(it -> mapMethodsToQuery(repositoryInformation, it, projectionFactory)) //
                .orElse(Collections.emptyMap());
    }

    @Override
    @Nullable
    public Object invoke(@SuppressWarnings("null") MethodInvocation invocation) throws Throwable {
        Method method = invocation.getMethod();
        QueryExecutionConverters.ExecutionAdapter executionAdapter = QueryExecutionConverters //
                .getExecutionAdapter(method.getReturnType());

        if (executionAdapter == null) {
            return resultHandler.postProcessInvocationResult(doInvoke(invocation), method);
        }
        return executionAdapter //
                .apply(() -> resultHandler.postProcessInvocationResult(doInvoke(invocation), method));
    }

    @Nullable
    private Object doInvoke(MethodInvocation invocation) throws Throwable {
        Method method = invocation.getMethod();
        if (hasQueryFor(method)) {
            // ...
            return invocationMetadata.invoke(repositoryInformation.getRepositoryInterface(), invocationMulticaster,
                    invocation.getArguments());
        }
        return invocation.proceed();
    }
}
```

SQL 解析实现在 commons 包里

## Log

```properties
logging.level.org.springframework.orm.jpa=DEBUG
```

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
