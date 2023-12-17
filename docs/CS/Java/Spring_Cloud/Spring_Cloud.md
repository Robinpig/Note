## Introduction

Spring Cloud provides tools for developers to quickly build some of the common patterns in distributed systems 
(e.g. configuration management, service discovery, circuit breakers, intelligent routing, micro-proxy, control bus, one-time tokens, global locks, leadership election, distributed sessions, cluster state).

## Service Registry


- Registry
- HeartBeat
- UpdateTask


Represents an instance of a service in a discovery system.
```java
public interface ServiceInstance {

	/**
	 * @return The unique instance ID as registered.
	 */
	default String getInstanceId() {
		return null;
	}

	String getServiceId();

	String getHost();

	int getPort();

	boolean isSecure();

	URI getUri();

	Map<String, String> getMetadata();

	default String getScheme() {
		return null;
	}
}
```



### ServiceRegistry

A marker interface used by a ServiceRegistry.

```java
public interface Registration extends ServiceInstance {

}
```
Contract to register and deregister instances with a Service Registry.
```java
public interface ServiceRegistry<R extends Registration> {

	/**
	 * Registers the registration. A registration typically has information about an instance, such as its hostname and port.
	 */
	void register(R registration);

	/**
	 * Deregisters the registration.
	 */
	void deregister(R registration);

	/**
	 * Closes the ServiceRegistry. This is a lifecycle method.
	 */
	void close();

	/**
	 * Sets the status of the registration. The status values are determined by the individual implementations.
	 */
	void setStatus(R registration, String status);

	/**
	 * Gets the status of a particular registration.
	 */
	<T> T getStatus(R registration);

}
```

### AbstractAutoServiceRegistration

Implementations:
- [Nacos](/docs/CS/Java/Spring_Cloud/nacos/registry.md)
- [Eureka](/docs/CS/Java/Spring_Cloud/Eureka.md)

```java
public abstract class AbstractAutoServiceRegistration<R extends Registration>
        implements AutoServiceRegistration, ApplicationContextAware,
        ApplicationListener<WebServerInitializedEvent> {
    
    private final ServiceRegistry<R> serviceRegistry;

    private boolean autoStartup = true;

    private AtomicBoolean running = new AtomicBoolean(false);
    
    @Override
    @SuppressWarnings("deprecation")
    public void onApplicationEvent(WebServerInitializedEvent event) {
        bind(event);
    }

    @Deprecated
    public void bind(WebServerInitializedEvent event) {
        ApplicationContext context = event.getApplicationContext();
        if (context instanceof ConfigurableWebServerApplicationContext) {
            if ("management".equals(((ConfigurableWebServerApplicationContext) context)
                    .getServerNamespace())) {
                return;
            }
        }
        this.port.compareAndSet(0, event.getWebServer().getPort());
        this.start();
    }

    public void start() {
        // only initialize if nonSecurePort is greater than 0 and it isn't already running
        // because of containerPortInitializer below
        if (!this.running.get()) {
            this.context.publishEvent(
                    new InstancePreRegisteredEvent(this, getRegistration()));
            register();
            if (shouldRegisterManagement()) {
                registerManagement();
            }
            this.context.publishEvent(
                    new InstanceRegisteredEvent<>(this, getConfiguration()));
            this.running.compareAndSet(false, true);
        }

    }
}
```

## Config Refresh

use [Spring RefreshEventListener](/docs/CS/Java/Spring/IoC.md?id=EventListener).

## Load Balance

[Ribbon](/docs/CS/Java/Spring_Cloud/Ribbon.md)

Load Balancer

## Circuit Breaker

[Spring Cloud Circuit breaker](https://spring.io/projects/spring-cloud-circuitbreaker) provides an abstraction across different circuit breaker implementations.
It provides a consistent API to use in your applications allowing you the developer to choose the circuit breaker implementation that best fits your needs for your app.

Implementations:

- [Hystrix](/docs/CS/Java/Spring_Cloud/Hystrix.md)
- [Resilience4J]()
- [Sentinel](/docs/CS/Java/Spring_Cloud/Sentinel/Sentinel.md)
- [Spring Retry]()

> [!NOTE]
> 
> Load Balancer retries timeout must less than circuit breaker timeout.

The CircuitBreakerFactory.create API will create an instance of a class called CircuitBreaker. The run method takes a Supplier and a Function. 
The Supplier is the code that you are going to wrap in a circuit breaker. 
The Function is the fallback that will be executed if the circuit breaker is tripped. 
The function will be passed the Throwable that caused the fallback to be triggered.


```java
public interface CircuitBreaker {

	default <T> T run(Supplier<T> toRun) {
		return run(toRun, throwable -> {
			throw new NoFallbackAvailableException("No fallback available.", throwable);
		});
	};

	<T> T run(Supplier<T> toRun, Function<Throwable, T> fallback);

}
```
The ReactiveCircuitBreakerFactory.create API will create an instance of a class called ReactiveCircuitBreaker. 
The run method takes with a Mono or Flux and wraps it in a circuit breaker. 

## Gateway

Zuul



- [Gateway](/docs/CS/Java/Spring_Cloud/gateway.md)

## Stream

## Sleuth

[Spring Cloud Sleuth](https://spring.io/projects/spring-cloud-sleuth) provides Spring Boot auto-configuration for distributed tracing.

Sleuth configures everything you need to get started. This includes where trace data (spans) are reported to, how many traces to keep (sampling), if remote fields (baggage) are sent, and which libraries are traced.

Specifically, Spring Cloud Sleuth

- Adds trace and span ids to the Slf4J MDC, so you can extract all the logs from a given trace or span in a log aggregator.
- Instruments common ingress and egress points from Spring applications (servlet filter, rest template, scheduled actions, message channels, feign client).
- If `spring-cloud-sleuth-zipkin` is available then the app will generate and report Zipkin-compatible traces via HTTP. By default it sends them to a Zipkin collector service on localhost (port 9411). 
  Configure the location of the service using `spring.zipkin.baseUrl`.

- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)

## RPC

- [Feign](/docs/CS/Java/Spring_Cloud/Feign.md)




## Links

- [Spring Framework](/docs/CS/Java/Spring/Spring.md)
- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)