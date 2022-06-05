## Introduction

Feign is a Java to HTTP client binder inspired by Retrofit, JAXRS-2.0, and WebSocket. 
Feign's first goal was reducing the complexity of binding Denominator uniformly to HTTP APIs regardless of ReSTfulness.


Features:

- client
  - [Ribbon](/docs/CS/Java/Spring_Cloud/Ribbon.md)
  - OK Http
  - java 11 Http2
- Circuit Breaker
- [Hystrix](/docs/CS/Java/Spring_Cloud/Hystrix.md)


![](https://camo.githubusercontent.com/f1bd8b9bfe3c049484b0776b42668bb76a57872fe0f01402e5ef73d29b811e50/687474703a2f2f7777772e706c616e74756d6c2e636f6d2f706c616e74756d6c2f70726f78793f63616368653d6e6f267372633d68747470733a2f2f7261772e67697468756275736572636f6e74656e742e636f6d2f4f70656e466569676e2f666569676e2f6d61737465722f7372632f646f63732f6f766572766965772d6d696e646d61702e69756d6c)



```java
@Configuration(proxyBeanMethods = false)
public class FeignClientsConfiguration {
    @Bean
    @ConditionalOnMissingBean
    @ConditionalOnMissingClass("org.springframework.data.domain.Pageable")
    public Encoder feignEncoder(ObjectProvider<AbstractFormWriter> formWriterProvider) {
        return springEncoder(formWriterProvider);
    }

    @Bean
    @ConditionalOnMissingBean
    public Retryer feignRetryer() {
        return Retryer.NEVER_RETRY;
    }
}
```

## Prepare

### registerFeignClients

Only allows interface.
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
                    Assert.isTrue(annotationMetadata.isInterface(),
                            "@FeignClient can only be specified on an interface");

                    Map<String, Object> attributes = annotationMetadata.getAnnotationAttributes(FeignClient.class.getCanonicalName());

                    String name = getClientName(attributes);
                    registerClientConfiguration(registry, name,
                            attributes.get("configuration"));

                    registerFeignClient(registry, annotationMetadata, attributes);
                }
            }
        }
    }
}
```
registerBeanDefinition into [Spring](/docs/CS/Java/Spring/IoC.md).

> [!TIP]
> 
> BeanDefinition is FeignClientFactoryBean.class.

```java
private void registerFeignClient(BeanDefinitionRegistry registry,
			AnnotationMetadata annotationMetadata, Map<String, Object> attributes) {
		String className = annotationMetadata.getClassName();
		BeanDefinitionBuilder definition = BeanDefinitionBuilder
				.genericBeanDefinition(FeignClientFactoryBean.class);
		//...
		// has a default, won't be null
		boolean primary = (Boolean) attributes.get("primary");
		beanDefinition.setPrimary(primary);

		String qualifier = getQualifier(attributes);
		if (StringUtils.hasText(qualifier)) {
			alias = qualifier;
		}

		BeanDefinitionHolder holder = new BeanDefinitionHolder(beanDefinition, className,
				new String[] { alias });
		BeanDefinitionReaderUtils.registerBeanDefinition(holder, registry);
	}
```

## Execute

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
        FeignContext context = applicationContext.getBean(FeignContext.class);
        Feign.Builder builder = feign(context);

        if (!StringUtils.hasText(url)) {
            if (!name.startsWith("http")) {
                url = "http://" + name;
            } else {
                url = name;
            }
            url += cleanPath();
            return (T) loadBalance(builder, context,
                    new HardCodedTarget<>(type, name, url));
        }
        if (StringUtils.hasText(url) && !url.startsWith("http")) {
            url = "http://" + url;
        }
        String url = this.url + cleanPath();
        Client client = getOptional(context, Client.class);
        if (client != null) {
            if (client instanceof LoadBalancerFeignClient) {
                // not load balancing because we have a url,
                // but ribbon is on the classpath, so unwrap
                client = ((LoadBalancerFeignClient) client).getDelegate();
            }
            if (client instanceof FeignBlockingLoadBalancerClient) {
                // not load balancing because we have a url,
                // but Spring Cloud LoadBalancer is on the classpath, so unwrap
                client = ((FeignBlockingLoadBalancerClient) client).getDelegate();
            }
            builder.client(client);
        }
        Targeter targeter = get(context, Targeter.class);
        return (T) targeter.target(this, builder, context,
                new HardCodedTarget<>(type, name, url));
    }
}
```

### Trageter


```java
class DefaultTargeter implements Targeter {
    public <T> T target(Target<T> target) {
        return build().newInstance(target);
    }
}
```
#### HystrixTargeter

Also you can wrapper it using [Hystrix](/docs/CS/Java/Spring_Cloud/Hystrix.md).

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

creates an api binding to the target. As this invokes reflection, care should be taken to cache the result.

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
}
```



#### parse

```java
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
```
parseAndValidateMetadata like @RequestMapping in [Spring MVC](/docs/CS/Java/Spring/MVC.md)

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

#### InvocationHandler

dispatch method in cacheMap

```java
  static class FeignInvocationHandler implements InvocationHandler {

    private final Target target;
    private final Map<Method, MethodHandler> dispatch;
}
```

#### invoke

Using RequestTemplate.

```java
@Override
  public Object invoke(Object[] argv) throws Throwable {
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
          Throwable cause = th.getCause();
          if (propagationPolicy == UNWRAP && cause != null) {
            throw cause;
          } else {
            throw th;
          }
        }
        if (logLevel != Logger.Level.NONE) {
          logger.logRetry(metadata.configKey(), logLevel);
        }
        continue;
      }
    }
  }
```

## Interceptor

## Retry

Feign, by default, will automatically retry IOExceptions, regardless of HTTP method, treating them as transient network related exceptions, and any RetryableException thrown from an ErrorDecoder. 
To customize this behavior, register a custom Retryer instance via the builder.

If the retry is determined to be unsuccessful, the last RetryException will be thrown. 
To throw the original cause that led to the unsuccessful retry, build your Feign client with the exceptionPropagationPolicy() option.

## Metrics

By default, feign won't collect any metrics.
But, it's possible to add metric collection capabilities to any feign client.


## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md?id=RPC)

## References

1. [OpenFeign](https://github.com/OpenFeign/feign)