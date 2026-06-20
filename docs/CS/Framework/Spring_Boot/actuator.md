
## Introduction


The spring-boot-actuator module provides all of Spring Boot’s production-ready features. 
The recommended way to enable the features is to add a dependency on the `spring-boot-starter-actuator`‘Starter’.

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
```




Actuator endpoints let you monitor and interact with your application. 
Each individual endpoint can be enabled or disabled and exposed (made remotely accessible) over HTTP or JMX. 
An endpoint is considered to be available when it is both enabled and exposed. The built-in endpoints will only be auto-configured when they are available. 

To change which endpoints are exposed, use the following technology-specific include and exclude properties.
The include property lists the IDs of the endpoints that are exposed. 
* can be used to select all endpoints. 
```properties
management.endpoints.web.exposure.include=*
```





inject `HttpTraceRepository`, get cookie from `/actuator/httptrace`

```java
@Bean
@ConditionalOnMissingBean(HttpTraceRepository.class)
public HttpTraceRepository traceRepository(){
    return new InMemoryHttpTraceRepository();

}
```



get datasource url from `/actuactor/env`

Get all things from `/actuator/heapdump`

```
jhat heapdump
```

datasource in instance of `org.springframework.boot.autoconfigure.jdbc.DataSourceProperties`