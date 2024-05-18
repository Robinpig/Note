## Introduction

Spring Data JPA, part of the larger Spring Data family, makes it easy to easily implement JPA-based (Java Persistence API) repositories.


The central interface in the Spring Data repository abstraction is Repository. 
It takes the domain class to manage as well as the identifier type of the domain class as type arguments. 
This interface acts primarily as a marker interface to capture the types to work with and to help you to discover interfaces that extend this one. 
The CrudRepository and ListCrudRepository interfaces provide sophisticated CRUD functionality for the entity class that is being managed.


Annotation-driven configuration of base packages
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

create proxy for repository
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

## Log

```properties
logging.level.org.springframework.orm.jpa=DEBUG
```


## Links

- [Spring](/docs/CS/Java/Spring/Spring.md)
