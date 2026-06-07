## Introduction

[Feign](https://github.com/OpenFeign/feign) 是一个 Java 到 HTTP 的客户端绑定器，灵感来自 Retrofit、JAXRS-2.0 和 WebSocket。
Feign 的首要目标是降低将 Denominator 统一绑定到 HTTP API 的复杂性，无论其 [RESTfulness](/docs/CS/Distributed/RPC/RESTful.md) 如何。

Feign 使用 Jersey 和 CXF 等工具为 ReST 或 SOAP 服务编写 Java 客户端。
此外，Feign 允许你在 Apache HC 等 http 库之上编写自己的代码。
Feign 通过可自定义的解码器和错误处理，以最小的开销和代码量将你的代码连接到 http API，可以编写为任何基于文本的 http API。

Feign 通过将注解处理为模板化请求来工作。
参数在输出前以直接的方式应用于这些模板。
尽管 Feign 仅限于支持基于文本的 API，但它极大地简化了重放请求等系统方面的处理。
此外，Feign 使得对你的转换进行单元测试变得很容易。

client
- [Ribbon](/docs/CS/Framework/Spring_Cloud/Ribbon.md)(In maintenance)
- OK Http
- java 11 Http2




Feign 通过将注解处理为模板化请求来工作。
参数在输出前以直接的方式应用于这些模板。
尽管 Feign 仅限于支持基于文本的 API，但它极大地简化了重放请求等系统方面的处理。
此外，Feign 使得对你的转换进行单元测试变得很容易。



## Spring Cloud OpenFeign

Spring Cloud 增加了对 Spring MVC 注解以及使用 Spring Web 中默认使用的相同 HttpMessageConverters 的支持。
Spring Cloud 集成了 Eureka、Spring Cloud CircuitBreaker 以及 Spring Cloud LoadBalancer，以便在使用 Feign 时提供负载均衡的 http 客户端。

要在你的项目中使用 Feign，请使用 group 为 `org.springframework.cloud`、artifact id 为 `spring-cloud-starter-openfeign` 的 starter。

> [!NOTE]
>
> `spring-cloud-starter-openfeign` supports `spring-cloud-starter-loadbalancer`.
> However, as is an optional dependency.



Spring Cloud 的 Feign 支持中的一个核心概念是 named client。
每个 feign client 是一个组件集合的一部分，这些组件协同工作以按需联系远程服务器，并且该集合有一个你作为应用程序开发者使用 `@FeignClient` 注解赋予的名称。
Spring Cloud 使用 FeignClientsConfiguration 按需为每个 named client 创建一个 ApplicationContext 作为新的集合。
这包含（其中包括）一个 feign.Decoder、一个 feign.Encoder 和一个 feign.Contract。可以通过使用 @FeignClient 注解的 contextId 属性来覆盖该集合的名称。

如果我们想创建多个具有相同名称或 url 的 feign client，使它们指向同一台服务器，但每个具有不同的自定义配置，那么我们必须使用 @FeignClient 注解的 contextId 属性，以避免这些配置 bean 的名称冲突。

上述的负载均衡 client 将想要发现 "stores" 服务的物理地址。
如果你的应用程序是 Eureka client，那么它将在 Eureka 服务注册中心中解析该服务。
如果你不想使用 Eureka，可以在外部配置中使用 SimpleDiscoveryClient 配置服务器列表。

在创建 Feign client bean 时，我们解析通过 @FeignClient 注解传入的值。
从 4.x 版本开始，这些值会被立即解析。这对于大多数用例来说是一个好的解决方案，并且它还支持 AOT。

如果你需要延迟解析属性，请将 `spring.cloud.openfeign.lazy-attributes-resolution` 属性值设置为 true。


> A bean of `Retryer.NEVER_RETRY` with the type Retryer is created by default, which will disable retrying.


如果 Spring Cloud CircuitBreaker 在 classpath 上并且 `spring.cloud.openfeign.circuitbreaker.enabled=true`，Feign 将把所有方法包装在断路器中。
要启用 Spring Cloud CircuitBreaker 分组，请将 `spring.cloud.openfeign.circuitbreaker.group.enabled` 属性设置为 true（默认 false）。


Feign 通过单继承接口支持样板 API。这允许将公共操作分组到方便的基础接口中。

我们不建议在应用程序生命周期的早期阶段（处理配置和初始化 bean 时）使用 Feign client。
在 bean 初始化期间使用这些 client 是不支持的。
同样，取决于你如何使用 Feign client，在启动应用程序时可能会遇到初始化错误。
为了解决这个问题，可以在自动注入你的 client 时使用 ObjectProvider。

通过 `@EnableFeignClients` 启用

Spring Cloud OpenFeign 默认不为 feign 提供以下 bean，但仍然会从应用程序上下文中查找这些类型的 bean 来创建 feign client：

- Logger.Level
- Retryer
- ErrorDecoder
- Request.Options
- Collection<RequestInterceptor>
- SetterFactory
- QueryMapEncoder
- Capability (MicrometerObservationCapability and CachingCapability are provided by default)


默认情况下会创建一个 Retryer.NEVER_RETRY 类型的 Retryer bean，它将禁用重试。请注意，此重试行为与 Feign 的默认行为不同，Feign 默认会自动重试 IOException，将其视为瞬态网络相关异常，以及 ErrorDecoder 抛出的任何 RetryableException。

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

创建其中一种类型的 bean 并将其放入 @FeignClient 配置中（例如上面的 FooConfiguration），可以让你覆盖上述描述的每个 bean。
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



@FeignClient 也可以使用配置属性进行配置。

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


如果服务器未运行或不可用，数据包会导致连接被拒绝。
通信将以错误消息或回退结束。
如果 connectTimeout 设置得非常低，这可能在超时之前发生。
执行查找和接收此类数据包所花费的时间是此延迟的重要组成部分。
它可能会根据涉及 DNS 查找的远程主机而变化。


### registerFeignClients

BeanDefinitionReaderUtils.registerBeanDefinition into [Spring Context](/docs/CS/Framework/Spring/IoC.md).

> [!TIP]
>
> BeanDefinition is FeignClientFactoryBean.class.



@FeignClient 只能指定在接口上。


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
一个创建 feign 类实例的工厂。
它为每个 client name 创建一个 Spring ApplicationContext，并从中提取所需的 bean。

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

你也可以使用 [Hystrix](/docs/CS/Framework/Spring_Cloud/Hystrix.md) 来包装它。

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

基于 `ReflectiveFeign`，解析 `@FeignClient` + `@RequestMapping`，通过 `Contract` 生成方法到 HTTP 请求的映射模板

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

parseAndValidateMetadata 类似于 [Spring MVC](/docs/CS/Framework/Spring/MVC.md) 中的 @RequestMapping

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

创建一个 restTemplate
在 cacheMap 中 dispatch 方法

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
通过 client 执行

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
可以配置零个或多个 RequestInterceptor，用于向所有请求添加 header 等目的。
**不保证拦截器的执行顺序。**
一旦拦截器应用完毕，将调用 `Target.apply(RequestTemplate)` 来创建通过 `Client.execute(Request, Request.Options)` 发送的不可变 http 请求。
```java
public interface RequestInterceptor {
  void apply(RequestTemplate template);
}
```
RequestInterceptors 通过 `Feign.Builder.requestInterceptors` 进行配置。

## Retry

Feign 默认会自动重试 IOException（无论 HTTP 方法是什么），将其视为瞬态网络相关异常，以及 ErrorDecoder 抛出的任何 RetryableException。
要自定义此行为，请通过 builder 注册一个自定义的 Retryer 实例。

如果确定重试不成功，将抛出最后一个 RetryException。
要抛出导致重试失败的原始原因，请使用 exceptionPropagationPolicy() 选项构建 Feign client。

## Fallback

Feign 的 fallback 机制要生效，需要三部分配合
- Fallback/FallbackFactory 实现
- FeignClientsConfiguration 配置
- 限流熔断框架的引入（Hystrix(已经不支持 不推荐) / Spring Cloud Circuit Breaker / Sentinel）

Feign + SpringCloudCircuitBreaker 的用法从 2020.0.0 版本开始支持，目前经历一次大变化
- 2022.0.0 开始开关从 feign.circuitbreaker.enabled 调整为 spring.cloud.openfeign.circuitbreaker.enabled



## Log

OpenFeign 组件默认将日志信息以 debug 模式输出，而默认情况下 Spring Boot 的日志
级别是 Info，因此我们必须将应用日志的打印级别改为 debug 后才能看到 OpenFeign 的日志

```
logging:
  level:
    com.xx.TemplateService: debug
    com.xx.CalculationService: debug
```

## Metrics

默认情况下，feign 不收集任何指标。
但是，可以为任何 feign client 添加指标收集功能。



## Summary

### 生态集成与适用场景



| 场景     | Dubbo 更合适                                                | OpenFeign 更合适                                           |
| -------- | ----------------------------------------------------------- | ---------------------------------------------------------- |
| 技术栈   | Java 为主，Spring Boot/Cloud Alibaba                        | Spring Cloud 全家桶，多语言混合                            |
| 调用类型 | 内部微服务高频 RPC、大数据/实时计算节点通信                 | 面向外部的 REST API、跨语言服务对接、BFF 层聚合            |
| 治理需求 | 需要完整的服务路由、权重、灰度、全链路追踪、精细化降级      | 依赖 Spring Cloud Gateway + Sentinel/Resilience4j 拼装治理 |
| 部署环境 | 传统 VM / K8s 均可，Dubbo3 原生支持云原生（Mesh/Proxyless） | 云原生友好，天然契合 HTTP Ingress / API Gateway            |

两者在协议层开始交汇（Dubbo 支持 HTTP/REST，Feign 可接二进制序列化），但**底层设计哲学未变**：Dubbo 是"协议栈驱动的全链路框架"，OpenFeign 是"声明式模板+生态拼装"





## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=RPC)

## References

1. [OpenFeign](https://github.com/OpenFeign/feign)
