## Introduction
[Spring Boot](https://spring.io/projects/spring-boot) makes it easy to create stand-alone, production-grade Spring based Applications that you can "just run".

![packages.png](./images/packages.png)

Convention Over Configuration

spring-boot
spring-boot-autoconfigure

spring-boot-starters

spring-boot-test





## AutoConfiguration

- Cache
- Log - LoggingApplicationListener

- JdbcTemplateAutoConfiguration
- DataSourceAutoConfiguration
- DispatcherServletAutoConfiguration
- WebMvcAutoConfiguration



## [How to start Spring Boot Application?](/docs/CS/Java/Spring_Boot/Start.md)



## YAML



How to bind the properties 

```groovy
annotationProcessor 'org.springframework.boot:spring-boot-configuration-processor'
```



## Tools

### DevTool

### SpringInitializer



### Lombok



## Web

resolve request order:

-  dynamic controller
- static resources

## Test



### Junit5

It's need JDK15 to build Junit5,.

#### Condition

#### Extension

#### Annotations

@DisplayName



##### @Timeout

##### @Isolated

##### @SpringBootTest

@AutoConfigureMockMvc

| Junit5                                      | Junit4                                  |
| ------------------------------------------- | --------------------------------------- |
| @Disabled                                   | @Ignore                                 |
| @ExtendWith                                 | @RunWith                                |
| @Tag                                        | @Category                               |
| @BeforeEach @AfterEach @BeforeAll @AfterAll | @Before @After @BeforeClass @AfterClass |



#### Assertions

static methods

Nest Test 

Inner test invoke Outer test.

##### Paramterized Test

Use different parameters to run test.

- @ParamterizedTest
- @ValueSource
- @CsvValueSource
- @MethodSource
- @EnumSource
- @NullSource





#### Actuator

Admin



Starter





