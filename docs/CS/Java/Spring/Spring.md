## Introduction

The [Spring Framework](https://spring.io/projects/spring-framework) provides a comprehensive programming and configuration model for modern Java-based enterprise applications - on any kind of deployment platform. makes programming Java quicker, easier, and safer for everybody.
Spring’s focus on speed, simplicity, and productivity has made it the world's most popular Java framework.

## Architecture

At its core, Spring offers a *container*, often referred to as the *Spring application context*, that creates and manages application components.
These components, or beans, are wired together inside the Spring application context to make a complete application.

The act of wiring beans together is based on a pattern known as *dependency injection*(DI).
Rather than have components create and maintain the life cycle of other beans that they depend on, a dependency-injected application relies on a separate entity(the container) to create and maintain all components and inject those into the beans that need them.
This is done typically through constructor arguments or property accessor methods.

Historically, the way you would guide Spring’s application context to wire beans together was with one or more XML files that described the components and their relationship to other components.
In recent versions of Spring, however, a Java-based configuration is more common.

Java-based configuration offers several benefits over XML-based configuration, including greater type safety and improved refactorability.
Even so, explicit configuration with either Java or XML is necessary only if Spring is unable to automatically configure the components.

Automatic configuration has its roots in the Spring techniques known as autowiring and component scanning.
With component scanning, Spring can automatically discover components from an application’s classpath and create them as beans in the Spring application context.
With autowiring, Spring automatically injects the components with the other beans that they depend on.

More recently, with the introduction of [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md), automatic configuration has gone well beyond component scanning and autowiring.
Spring Boot is an extension of the Spring Framework that offers several productivity enhancements.
The most well known of these enhancements is autoconfiguration, where Spring Boot can make reasonable guesses at what components need to be configured and wired together, based on entries in the classpath, environment variables, and other factors.

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
- [AOT](/docs/CS/Java/Spring/AOT.md)

### Web

Spring comes with a powerful web framework known as [Spring MVC](/docs/CS/Java/Spring/MVC.md).
At the center of Spring MVC is the concept of a *controller*, a class that handles requests and responds with information of some sort.
In the case of a browser-facing application, a controller responds by optionally populating model data and passing the request on to a view to produce HTML that’s returned to the browser.

[Spring WebFlux](/docs/CS/Java/Spring/webflux.md) web frameworks.

### Data Access

Spring Data’s mission is to provide a familiar and consistent,  Spring-based programming model for data access while still retaining the special traits of the underlying data store.

It makes it easy to use data access technologies, relational and  non-relational databases, map-reduce frameworks, and cloud-based data  services. This is an umbrella project which contains many subprojects  that are specific to a given database.

- [Spring Data Commons](https://github.com/spring-projects/spring-data-commons) - Core Spring concepts underpinning every Spring Data module.
- [Spring Data JDBC](https://spring.io/projects/spring-data-jdbc) - Spring Data repository support for JDBC.
- [Spring Data R2DBC](https://spring.io/projects/spring-data-r2dbc) - Spring Data repository support for R2DBC.
- [Spring Data JPA](https://spring.io/projects/spring-data-jpa) - Spring Data repository support for JPA.
- [Spring Data KeyValue](https://github.com/spring-projects/spring-data-keyvalue) - `Map` based repositories and SPIs to easily build a Spring Data module for key-value stores.
- [Spring Data LDAP](https://spring.io/projects/spring-data-ldap) - Spring Data repository support for [Spring LDAP](https://github.com/spring-projects/spring-ldap).
- [Spring Data MongoDB](https://spring.io/projects/spring-data-mongodb) - Spring based, object-document support and repositories for MongoDB.
- [Spring Data Redis](https://spring.io/projects/spring-data-redis) - Easy configuration and access to Redis from Spring applications.
- [Spring Data REST](https://spring.io/projects/spring-data-rest) - Exports Spring Data repositories as hypermedia-driven RESTful resources.
- [Spring Data for Apache Cassandra](https://spring.io/projects/spring-data-cassandra) - Easy configuration and access to Apache Cassandra or large scale, highly available, data oriented Spring applications.
- [Spring Data for Apache Geode](https://spring.io/projects/spring-data-geode) - Easy configuration and access to Apache Geode for highly consistent, low latency, data oriented Spring applications.



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

## Deploy

### Dockerfile

```dockerfile
FROM openjdk:11.0.12-jre
ARG JAR_FILE=target/*.jar
COPY ${JAR_FILE} app.jar
ENTRYPOINT ["java","-jar","/app.jar"]
```

### K8s

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: taco-cloud-deploy
  labels:
    app: taco-cloud
spec:
  replicas: 3
  selector:
    matchLabels:
      app: taco-cloud
  template:
    metadata:
      labels:
        app: taco-cloud
  spec:
    containers:
    - name: taco-cloud-container
      image: tacocloud/tacocloud:latest
```

server:
shutdown: graceful

### war

## Links

- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)
- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)
