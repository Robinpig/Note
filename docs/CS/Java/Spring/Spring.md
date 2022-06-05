## Introduction

The [Spring Framework](https://spring.io/projects/spring-framework) provides a comprehensive programming and configuration model for modern Java-based enterprise applications - on any kind of deployment platform. makes programming Java quicker, easier, and safer for everybody. 
Spring’s focus on speed, simplicity, and productivity has made it the world's most popular Java framework.

## Architecture
Packages
- IoC
    - core
    - beans
    - context
    - expression
- AOP
    - aop
    - aspects
    - instrument
- data
    - jdbc
    - tx
    - orm
    - oxm
    - jms
- web
    - web
    - webmvc
    - websocket
    - webflux

### Core

- [The IoC Container](/docs/CS/Java/Spring/IoC.md)
- [Resources]
- [Validation, Data Binding, and Type Conversion]
- [Spring Expression Language]
- [Aspect Oriented Programming with Spring](/docs/CS/Java/Spring/AOP.md)
- [Data Buffers and Codecs]
- [Event](/docs/CS/Java/Spring/Event.md)

### Web

- [MVC](/docs/CS/Java/Spring/MVC.md)
- [webflux](/docs/CS/Java/Spring/webflux.md)

### Data Access

### Integration

 REST Endpoints

The Spring Framework provides two choices for making calls to REST endpoints:
- RestTemplate: The original Spring REST client with a synchronous, template method API.
- WebClient: a non-blocking, reactive alternative that supports both synchronous and asynchronous as well as streaming scenarios.



 [Task Execution and Scheduling](/docs/CS/Java/Spring/Task.md)

 [Cache Abstraction](/docs/CS/Java/Spring/Cache.md)

[Spring Security](/docs/CS/Java/Spring/Security.md)

### Testing


SpringProperties

`SpringProperties.setProperty(String key, String value)`

## Links

- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)
- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)