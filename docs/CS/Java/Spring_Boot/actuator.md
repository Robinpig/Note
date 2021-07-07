
## Introduction



### Sample



add dependency 

```groovy
// https://mvnrepository.com/artifact/org.springframework.boot/spring-boot-starter-actuator
    compile group: 'org.springframework.boot', name: 'spring-boot-starter-actuator'
```





Exposure all endpoints

```yaml
management:
  endpoints:
    web:
      exposure:
        include: '*'
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