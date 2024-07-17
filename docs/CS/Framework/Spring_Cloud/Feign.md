## Introduction

[Feign](https://github.com/OpenFeign/feign) is a Java to HTTP client binder inspired by Retrofit, JAXRS-2.0, and WebSocket. 
Feign's first goal was reducing the complexity of binding Denominator uniformly to HTTP APIs regardless of [RESTfulness](/docs/CS/Distributed/RPC/RESTful.md).

Feign uses tools like Jersey and CXF to write Java clients for ReST or SOAP services.
Furthermore, Feign allows you to write your own code on top of http libraries such as Apache HC. 
Feign connects your code to http APIs with minimal overhead and code via customizable decoders and error handling, which can be written to any text-based http API.

Feign works by processing annotations into a templatized request. 
Arguments are applied to these templates in a straightforward fashion before output. 
Although Feign is limited to supporting text-based APIs, it dramatically simplifies system aspects such as replaying requests.
Furthermore, Feign makes it easy to unit test your conversions knowing this.

client
- [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md)(In maintenance)
- OK Http
- java 11 Http2




Feign works by processing annotations into a templatized request. 
Arguments are applied to these templates in a straightforward fashion before output. 
Although Feign is limited to supporting text-based APIs, it dramatically simplifies system aspects such as replaying requests. 
Furthermore, Feign makes it easy to unit test your conversions knowing this.



## Spring Cloud OpenFeign

Spring Cloud adds support for Spring MVC annotations and for using the same HttpMessageConverters used by default in Spring Web. 
Spring Cloud integrates Eureka, Spring Cloud CircuitBreaker, as well as Spring Cloud LoadBalancer to provide a load-balanced http client when using Feign.

To include Feign in your project use the starter with group `org.springframework.cloud` and artifact id `spring-cloud-starter-openfeign`.

> [!NOTE]
> 
> `spring-cloud-starter-openfeign` supports `spring-cloud-starter-loadbalancer`. 
> However, as is an optional dependency.



A central concept in Spring Cloud’s Feign support is that of the named client. 
Each feign client is part of an ensemble of components that work together to contact a remote server on demand, and the ensemble has a name that you give it as an application developer using the `@FeignClient` annotation.
Spring Cloud creates a new ensemble as an ApplicationContext on demand for each named client using FeignClientsConfiguration.
This contains (amongst other things) an feign.Decoder, a feign.Encoder, and a feign.Contract. It is possible to override the name of that ensemble by using the contextId attribute of the @FeignClient annotation.

If we want to create multiple feign clients with the same name or url so that they would point to the same server but each with a different custom configuration then we have to use contextId attribute of the @FeignClient in order to avoid name collision of these configuration beans.

The load-balancer client above will want to discover the physical addresses for the "stores" service. 
If your application is a Eureka client then it will resolve the service in the Eureka service registry.
If you don’t want to use Eureka, you can configure a list of servers in your external configuration using SimpleDiscoveryClient.


While creating Feign client beans, we resolve the values passed via the @FeignClient annotation. 
As of 4.x, the values are being resolved eagerly. This is a good solution for most use-cases, and it also allows for AOT support.

If you need the attributes to be resolved lazily, set the spring.cloud.openfeign.lazy-attributes-resolution property value to true.


> A bean of `Retryer.NEVER_RETRY` with the type Retryer is created by default, which will disable retrying.


If Spring Cloud CircuitBreaker is on the classpath and `spring.cloud.openfeign.circuitbreaker.enabled=true`, Feign will wrap all methods with a circuit breaker.
To enable Spring Cloud CircuitBreaker group set the spring.cloud.openfeign.circuitbreaker.group.enabled property to true (by default false).


Feign supports boilerplate apis via single-inheritance interfaces. This allows grouping common operations into convenient base interfaces.


We discourage using Feign clients in the early stages of application lifecycle, while processing configurations and initialising beans.
Using the clients during bean initialisation is not supported.
Similarly, depending on how you are using your Feign clients, you may see initialization errors when starting your application. 
To work around this problem you can use an ObjectProvider when autowiring your client.

Enable with `@EnableFeignClients`

Spring Cloud OpenFeign does not provide the following beans by default for feign, but still looks up beans of these types from the application context to create the feign client:

- Logger.Level
- Retryer
- ErrorDecoder
- Request.Options
- Collection<RequestInterceptor>
- SetterFactory
- QueryMapEncoder
- Capability (MicrometerObservationCapability and CachingCapability are provided by default)


A bean of Retryer.NEVER_RETRY with the type Retryer is created by default, which will disable retrying. Notice this retrying behavior is different from the Feign default one, where it will automatically retry IOExceptions, treating them as transient network related exceptions, and any RetryableException thrown from an ErrorDecoder.

```java
@Configuration(proxyBeanMethods = false)
public class FeignClientsConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public Retryer feignRetryer() {
        return Retryer.NEVER_RETRY;
    }
}
```

Creating a bean of one of those type and placing it in a @FeignClient configuration (such as FooConfiguration above) allows you to override each one of the beans described. 
Example:
```java
@Configuration
public class FooConfiguration {
	 @Bean
    public Retryer feignRetryer() {
        return new Retryer.Default();
    }
}
```



@FeignClient also can be configured using configuration properties.

```yaml
spring:
    cloud:
        openfeign:
            client:
                config:
                    feignName:
                        url: http://remote-service.com
                        connectTimeout: 5000 #default 10s
                        readTimeout: 5000    #default 60s 
                        loggerLevel: full
                        errorDecoder: com.example.SimpleErrorDecoder
                        retryer: com.example.SimpleRetryer
```
> [!TIP]
> 
> If we create both @Configuration bean and configuration properties, configuration properties will win. It will override @Configuration values. 
> But if you want to change the priority to @Configuration, you can change spring.cloud.openfeign.client.default-to-properties to false.


In case the server is not running or available a packet results in connection refused. 
The communication ends either with an error message or in a fallback.
This can happen before the connectTimeout if it is set very low. The time taken to perform a lookup and to receive such a packet causes a significant part of this delay.
It is subject to change based on the remote host that involves a DNS lookup.


### registerFeignClients

BeanDefinitionReaderUtils.registerBeanDefinition into [Spring Context](/docs/CS/Framework/Spring/IoC.md).

> [!TIP]
> 
> BeanDefinition is FeignClientFactoryBean.class.




@FeignClient can only be specified on an interface.


```java
class FeignClientsRegistrar implements ImportBeanDefinitionRegistrar, ResourceLoaderAware, EnvironmentAware {
    public void registerFeignClients(AnnotationMetadata metadata,
                                     BeanDefinitionRegistry registry) {
        ClassPathScanningCandidateComponentProvider scanner = getScanner();
        scanner.setResourceLoader(this.resourceLoader);

        Set<String> basePackages;
        // get basePackage from getAnnotationAttributes(EnableFeignClients.class)
        for (String basePackage : basePackages) {
            Set<BeanDefinition> candidateComponents = scanner.findCandidateComponents(basePackage);
            for (BeanDefinition candidateComponent : candidateComponents) {
                if (candidateComponent instanceof AnnotatedBeanDefinition) {
                    // verify annotated class is an interface
                    AnnotatedBeanDefinition beanDefinition = (AnnotatedBeanDefinition) candidateComponent;
                    AnnotationMetadata annotationMetadata = beanDefinition.getMetadata();

                    Map<String, Object> attributes = annotationMetadata.getAnnotationAttributes(FeignClient.class.getCanonicalName());
                    String name = getClientName(attributes);
                    registerClientConfiguration(registry, name, attributes.get("configuration"));

                    registerFeignClient(registry, annotationMetadata, attributes);
                }
            }
        }
    }

    private void registerFeignClient(BeanDefinitionRegistry registry, AnnotationMetadata annotationMetadata,
        Map<String, Object> attributes) {
        String className = annotationMetadata.getClassName();
        if (String.valueOf(false).equals(
                environment.getProperty("spring.cloud.openfeign.lazy-attributes-resolution", String.valueOf(false)))) {
            eagerlyRegisterFeignClientBeanDefinition(className, attributes, registry);
        }
        else {
            lazilyRegisterFeignClientBeanDefinition(className, attributes, registry);
        }
	}
}
```


```java

	private void lazilyRegisterFeignClientBeanDefinition(String className, Map<String, Object> attributes,
			BeanDefinitionRegistry registry) {
		ConfigurableBeanFactory beanFactory = registry instanceof ConfigurableBeanFactory
				? (ConfigurableBeanFactory) registry : null;
		Class clazz = ClassUtils.resolveClassName(className, null);
		String contextId = getContextId(beanFactory, attributes);
		String name = getName(attributes);
		FeignClientFactoryBean factoryBean = new FeignClientFactoryBean();
		factoryBean.setBeanFactory(beanFactory);
		factoryBean.setName(name);
		factoryBean.setContextId(contextId);
		factoryBean.setType(clazz);
		factoryBean.setRefreshableClient(isClientRefreshEnabled());
		BeanDefinitionBuilder definition = BeanDefinitionBuilder.genericBeanDefinition(clazz, () -> {
			factoryBean.setUrl(getUrl(beanFactory, attributes));
			factoryBean.setPath(getPath(beanFactory, attributes));
			factoryBean.setDismiss404(Boolean.parseBoolean(String.valueOf(attributes.get("dismiss404"))));
			Object fallback = attributes.get("fallback");
			if (fallback != null) {
				factoryBean.setFallback(fallback instanceof Class ? (Class<?>) fallback
						: ClassUtils.resolveClassName(fallback.toString(), null));
			}
			Object fallbackFactory = attributes.get("fallbackFactory");
			if (fallbackFactory != null) {
				factoryBean.setFallbackFactory(fallbackFactory instanceof Class ? (Class<?>) fallbackFactory
						: ClassUtils.resolveClassName(fallbackFactory.toString(), null));
			}
			return factoryBean.getObject();
		});
		definition.setAutowireMode(AbstractBeanDefinition.AUTOWIRE_BY_TYPE);
		definition.setLazyInit(true);
		validate(attributes);

		AbstractBeanDefinition beanDefinition = definition.getBeanDefinition();
		beanDefinition.setAttribute("feignClientsRegistrarFactoryBean", factoryBean);

		// has a default, won't be null
		boolean primary = (Boolean) attributes.get("primary");

		beanDefinition.setPrimary(primary);

		String[] qualifiers = getQualifiers(attributes);
		if (ObjectUtils.isEmpty(qualifiers)) {
			qualifiers = new String[] { contextId + "FeignClient" };
		}

		BeanDefinitionHolder holder = new BeanDefinitionHolder(beanDefinition, className, qualifiers);
		BeanDefinitionReaderUtils.registerBeanDefinition(holder, registry);

		registerRefreshableBeanDefinition(registry, contextId, Request.Options.class, OptionsFactoryBean.class);
		registerRefreshableBeanDefinition(registry, contextId, RefreshableUrl.class, RefreshableUrlFactoryBean.class);
	}
```


### builder

```java
public static final class Builder<T> {

    private FeignClientFactoryBean feignClientFactoryBean;

    public T build() {
        return this.feignClientFactoryBean.getTarget();
    }
}

class FeignClientFactoryBean implements FactoryBean<Object>, InitializingBean, ApplicationContextAware {
    <T> T getTarget() {
        FeignClientFactory feignClientFactory = beanFactory != null ? beanFactory.getBean(FeignClientFactory.class)
                : applicationContext.getBean(FeignClientFactory.class);
        Feign.Builder builder = feign(feignClientFactory);
        if (!StringUtils.hasText(url) && !isUrlAvailableInConfig(contextId)) {

            if (LOG.isInfoEnabled()) {
                LOG.info("For '" + name + "' URL not provided. Will try picking an instance via load-balancing.");
            }
            if (!name.startsWith("http://") && !name.startsWith("https://")) {
                url = "http://" + name;
            }
            else {
                url = name;
            }
            url += cleanPath();
            return (T) loadBalance(builder, feignClientFactory, new HardCodedTarget<>(type, name, url));
        }
        if (StringUtils.hasText(url) && !url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        Client client = getOptional(feignClientFactory, Client.class);
        if (client != null) {
            if (client instanceof FeignBlockingLoadBalancerClient) {
                // not load balancing because we have a url,
                // but Spring Cloud LoadBalancer is on the classpath, so unwrap
                client = ((FeignBlockingLoadBalancerClient) client).getDelegate();
            }
            if (client instanceof RetryableFeignBlockingLoadBalancerClient) {
                // not load balancing because we have a url,
                // but Spring Cloud LoadBalancer is on the classpath, so unwrap
                client = ((RetryableFeignBlockingLoadBalancerClient) client).getDelegate();
            }
            builder.client(client);
        }

        applyBuildCustomizers(feignClientFactory, builder);

        Targeter targeter = get(feignClientFactory, Targeter.class);
        return targeter.target(this, builder, feignClientFactory, resolveTarget(feignClientFactory, contextId, url));
    }
}
```


```java
public class FeignAutoConfiguration {

	@Autowired(required = false)
	private List<FeignClientSpecification> configurations = new ArrayList<>();

    @Bean
	public FeignClientFactory feignContext() {
		FeignClientFactory context = new FeignClientFactory();
		context.setConfigurations(this.configurations);
		return context;
	}
}
```
A factory that creates instances of feign classes. 
It creates a Spring ApplicationContext per client name, and extracts the beans that it needs from there.

```java
public class FeignClientFactory extends NamedContextFactory<FeignClientSpecification> {

	public FeignClientFactory() {
		this(new HashMap<>());
	}

	public FeignClientFactory(
			Map<String, ApplicationContextInitializer<GenericApplicationContext>> applicationContextInitializers) {
		super(FeignClientsConfiguration.class, "spring.cloud.openfeign", "spring.cloud.openfeign.client.name",
				applicationContextInitializers);
	}
}
```



### Targeter


```java
class DefaultTargeter implements Targeter {
    public <T> T target(Target<T> target) {
        return build().newInstance(target);
    }
}
```
#### HystrixTargeter

Also you can wrapper it using [Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md).

```java
class HystrixTargeter implements Targeter {

    @Override
    public <T> T target(FeignClientFactoryBean factory, Feign.Builder feign,
                        FeignContext context, Target.HardCodedTarget<T> target) {
        if (!(feign instanceof feign.hystrix.HystrixFeign.Builder)) {
            return feign.target(target);
        }
        feign.hystrix.HystrixFeign.Builder builder = (feign.hystrix.HystrixFeign.Builder) feign;
        String name = StringUtils.isEmpty(factory.getContextId()) ? factory.getName()
                : factory.getContextId();
        SetterFactory setterFactory = getOptional(name, context, SetterFactory.class);
        if (setterFactory != null) {
            builder.setterFactory(setterFactory);
        }
        Class<?> fallback = factory.getFallback();
        if (fallback != void.class) {
            return targetWithFallback(name, context, target, builder, fallback);
        }
        Class<?> fallbackFactory = factory.getFallbackFactory();
        if (fallbackFactory != void.class) {
            return targetWithFallbackFactory(name, context, target, builder,
                    fallbackFactory);
        }

        return feign.target(target);
    }
}
```

### newInstance

creates an api binding to the target. 
As this invokes reflection, care should be taken to cache the result.



```java
public class ReflectiveFeign extends Feign {
    @Override
    public <T> T newInstance(Target<T> target) {
        Map<String, MethodHandler> nameToHandler = targetToHandlersByName.apply(target);
        Map<Method, MethodHandler> methodToHandler = new LinkedHashMap<Method, MethodHandler>();
        List<DefaultMethodHandler> defaultMethodHandlers = new LinkedList<DefaultMethodHandler>();

        for (Method method : target.type().getMethods()) {
            if (method.getDeclaringClass() == Object.class) {
                continue;
            } else if (Util.isDefault(method)) {
                DefaultMethodHandler handler = new DefaultMethodHandler(method);
                defaultMethodHandlers.add(handler);
                methodToHandler.put(method, handler);
            } else {
                methodToHandler.put(method, nameToHandler.get(Feign.configKey(target.type(), method)));
            }
        }
        InvocationHandler handler = factory.create(target, methodToHandler);
        T proxy = (T) Proxy.newProxyInstance(target.type().getClassLoader(),
                new Class<?>[]{target.type()}, handler);

        for (DefaultMethodHandler defaultMethodHandler : defaultMethodHandlers) {
            defaultMethodHandler.bindTo(proxy);
        }
        return proxy;
    }

    public Map<String, MethodHandler> apply(Target target) {
        List<MethodMetadata> metadata = contract.parseAndValidateMetadata(target.type());
        Map<String, MethodHandler> result = new LinkedHashMap<String, MethodHandler>();
        for (MethodMetadata md : metadata) {
            BuildTemplateByResolvingArgs buildTemplate;
            if (!md.formParams().isEmpty() && md.template().bodyTemplate() == null) {
                buildTemplate =
                        new BuildFormEncodedTemplateFromArgs(md, encoder, queryMapEncoder, target);
            } else if (md.bodyIndex() != null) {
                buildTemplate = new BuildEncodedTemplateFromArgs(md, encoder, queryMapEncoder, target);
            } else {
                buildTemplate = new BuildTemplateByResolvingArgs(md, queryMapEncoder, target);
            }
            if (md.isIgnored()) {
                result.put(md.configKey(), args -> {
                    throw new IllegalStateException(md.configKey() + " is not a method handled by feign");
                });
            } else {
                result.put(md.configKey(),
                        factory.create(target, md, buildTemplate, options, decoder, errorDecoder));
            }
        }
        return result;
    }
}
```



#### parse

parseAndValidateMetadata like @RequestMapping in [Spring MVC](/docs/CS/Framework/Spring/MVC.md)

```java
abstract class BaseContract implements Contract {
    protected MethodMetadata parseAndValidateMetadata(Class<?> targetType, Method method) {
        final MethodMetadata data = new MethodMetadata();
        data.targetType(targetType);
        data.method(method);
        data.returnType(Types.resolve(targetType, targetType, method.getGenericReturnType()));
        data.configKey(Feign.configKey(targetType, method));

        if (targetType.getInterfaces().length == 1) {
            processAnnotationOnClass(data, targetType.getInterfaces()[0]);
        }
        processAnnotationOnClass(data, targetType);


        for (final Annotation methodAnnotation : method.getAnnotations()) {
            processAnnotationOnMethod(data, methodAnnotation, method);
        }
        if (data.isIgnored()) {
            return data;
        }
        checkState(data.template().method() != null,
                "Method %s not annotated with HTTP method type (ex. GET, POST)%s",
                data.configKey(), data.warnings());
        final Class<?>[] parameterTypes = method.getParameterTypes();
        final Type[] genericParameterTypes = method.getGenericParameterTypes();

        final Annotation[][] parameterAnnotations = method.getParameterAnnotations();
        final int count = parameterAnnotations.length;
        for (int i = 0; i < count; i++) {
            boolean isHttpAnnotation = false;
            if (parameterAnnotations[i] != null) {
                isHttpAnnotation = processAnnotationsOnParameter(data, parameterAnnotations[i], i);
            }

            if (isHttpAnnotation) {
                data.ignoreParamater(i);
            }

            if (parameterTypes[i] == URI.class) {
                data.urlIndex(i);
            } else if (!isHttpAnnotation && parameterTypes[i] != Request.Options.class) {
                if (data.isAlreadyProcessed(i)) {
                    checkState(data.formParams().isEmpty() || data.bodyIndex() == null,
                            "Body parameters cannot be used with form parameters.%s", data.warnings());
                } else {
                    checkState(data.formParams().isEmpty(),
                            "Body parameters cannot be used with form parameters.%s", data.warnings());
                    checkState(data.bodyIndex() == null,
                            "Method has too many Body parameters: %s%s", method, data.warnings());
                    data.bodyIndex(i);
                    data.bodyType(Types.resolve(targetType, targetType, genericParameterTypes[i]));
                }
            }
        }

        if (data.headerMapIndex() != null) {
            checkMapString("HeaderMap", parameterTypes[data.headerMapIndex()],
                    genericParameterTypes[data.headerMapIndex()]);
        }

        if (data.queryMapIndex() != null) {
            if (Map.class.isAssignableFrom(parameterTypes[data.queryMapIndex()])) {
                checkMapKeys("QueryMap", genericParameterTypes[data.queryMapIndex()]);
            }
        }

        return data;
    }
}
```

### InvocationHandler

create a restTemplate
dispatch method in cacheMap

retryer

```java
static class FeignInvocationHandler implements InvocationHandler {

    private final Target target;
    private final Map<Method, MethodHandler> dispatch;

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        // equals/hashCode/toString no need remote call
        if (!dispatch.containsKey(method)) {
            throw new UnsupportedOperationException(String.format("Method \"%s\" should not be called", method.getName()));
        }

        return dispatch.get(method).invoke(args);
    }
}
```
InvocationHandlerFactory

#### SynchronousMethodHandler
```java
final class SynchronousMethodHandler implements MethodHandler {
    @Override
    public Object invoke(Object[] argv) throws Throwable {
        // Create a Request Template from an existing Request Template.
        RequestTemplate template = buildTemplateFromArgs.create(argv);
        Options options = findOptions(argv);
        Retryer retryer = this.retryer.clone();
        while (true) {
            try {
                return executeAndDecode(template, options);
            } catch (RetryableException e) {
                try {
                    retryer.continueOrPropagate(e);
                } catch (RetryableException th) {
                   // ...
                }
                continue;
            }
        }
    }

    Object executeAndDecode(RequestTemplate template, Options options) throws Throwable {
        Request request = targetRequest(template);
        Response response;
        long start = System.nanoTime();
        try {
            response = client.execute(request, options);
            // ensure the request is set. TODO: remove in Feign 12
            response = response.toBuilder()
                    .request(request)
                    .requestTemplate(template)
                    .build();
        } catch (IOException e) {
            throw errorExecuting(request, e);
        }

        long elapsedTime = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);
        return responseHandler.handleResponse(
                metadata.configKey(), response, metadata.returnType(), elapsedTime);
    }

    Request targetRequest(RequestTemplate template) {
        for (RequestInterceptor interceptor : requestInterceptors) {
            interceptor.apply(template);
        }
        return target.apply(template);
    }
}
```
execute by client

```java
package feign;
/**
 * Submits HTTP requests. Implementations are expected to be thread-safe.
 */
public interface Client {
    Response execute(Request request, Options options) throws IOException;
}
```

## Interceptor
Zero or more RequestInterceptors may be configured for purposes such as adding headers to all requests. 
**No guarantees are given with regards to the order that interceptors are applied.** 
Once interceptors are applied, `Target.apply(RequestTemplate)` is called to create the immutable http request sent via `Client.execute(Request, Request.Options)`.
```java
public interface RequestInterceptor {
  void apply(RequestTemplate template);
}
```
RequestInterceptors are configured via `Feign.Builder.requestInterceptors`.

## Retry

Feign, by default, will automatically retry IOExceptions, regardless of HTTP method, treating them as transient network related exceptions, and any RetryableException thrown from an ErrorDecoder. 
To customize this behavior, register a custom Retryer instance via the builder.

If the retry is determined to be unsuccessful, the last RetryException will be thrown. 
To throw the original cause that led to the unsuccessful retry, build your Feign client with the exceptionPropagationPolicy() option.

## Metrics

By default, feign won't collect any metrics.
But, it's possible to add metric collection capabilities to any feign client.


## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=RPC)

## References

1. [OpenFeign](https://github.com/OpenFeign/feign)