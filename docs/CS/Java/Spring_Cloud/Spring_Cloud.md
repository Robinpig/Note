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

```java
public interface AutoServiceRegistration {

}
```

### AbstractAutoServiceRegistration

Implementations:
- [Nacos](/docs/CS/Java/Spring_Cloud/nacos/registry.md)

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


## Spring Cloud Netflix

### Eureka

- [Eureka](/docs/CS/Java/Spring_Cloud/Eureka.md)
  
### Load Balance

- [Ribbon](/docs/CS/Java/Spring_Cloud/Ribbon.md)
- [Feign](/docs/CS/Java/Spring_Cloud/Feign.md)
- [Hystrix](/docs/CS/Java/Spring_Cloud/Hystrix.md)
- [Zipkin](/docs/CS/Java/Spring_Cloud/zipkin.md)
- [Gateway](/docs/CS/Java/Spring_Cloud/gateway.md)


## Spring Cloud Alibaba

Spring Cloud Alibaba provides a one-stop solution for distributed application development.
It contains all the components required to develop distributed applications, making it easy for you to develop your applications using Spring Cloud.

### Nacos

[Nacos](/docs/CS/Java/Spring_Cloud/nacos/Nacos.md) is an easy-to-use dynamic service discovery, configuration and service management platform for building cloud native applications.

**Nacos: Dynamic *Na*ming and *Co*nfiguration *S*ervice**


### Sentinel

[Sentinel](/docs/CS/Java/Spring_Cloud/Sentinel/Sentinel.md) is a powerful flow control component that takes "flow" as the breakthrough point and covers multiple fields including flow control, concurrency limiting, circuit breaking, and adaptive system protection to guarantee the reliability of microservices


### RocketMQ



### Seata




Alibaba Cloud OSS

Alibaba Cloud SchedulerX

Alibaba Cloud SMS


## Links

- [Spring Framework](/docs/CS/Java/Spring/Spring.md)
- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)