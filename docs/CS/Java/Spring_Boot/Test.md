## Introduction


## Context Management

### Cache Context

A nice feature of the Spring Test support is that the application context is cached between tests.
That way, if you have multiple methods in a test case or multiple test cases with the same configuration, they incur the cost of starting the application only once.
You can control the cache by using the @DirtiesContext annotation.



Once the TestContext framework loads an (or ) for a test, that context is cached and reused for all subsequent tests that declare the same unique context configuration within the same test suite. To understand how caching works, it is important to understand what is meant by “unique” and “test suite.”`ApplicationContext``WebApplicationContext`

An can be uniquely identified by the combination of configuration parameters that is used to load it. Consequently, the unique combination of configuration parameters is used to generate a key under which the context is cached. The TestContext framework uses the following configuration parameters to build the context cache key:`ApplicationContext`

* `locations` (from `@ContextConfiguration`)
* `classes` (from `@ContextConfiguration`)
* `contextInitializerClasses` (from `@ContextConfiguration`)
* `contextCustomizers` (from ) – this includes methods as well as various features from Spring Boot’s testing support such as and .`ContextCustomizerFactory``@DynamicPropertySource``@MockBean``@SpyBean`
* `contextLoader` (from `@ContextConfiguration`)
* `parent` (from `@ContextHierarchy`)
* `activeProfiles` (from `@ActiveProfiles`)
* `propertySourceLocations` (from `@TestPropertySource`)
* `propertySourceProperties` (from `@TestPropertySource`)
* `resourceBasePath` (from `@WebAppConfiguration`)



n general, you should avoid modifying any global state inside your application context that prevents reusing it.

Make sure to always clean up resources and leave the Spring Context clean after each test execution.

Try to stick as much as possible to the same context configuration for your integration tests. To achieve this, you can either introduce an abstract parent class that includes your common configuration

```java
@AutoConfigureMockMvc
@ContextConfiguration(initializers = CustomInitializer.class)
@SpringBootTest(webEnvironment = RANDOM_PORT)
public abstract class AbstractIntegrationTest {
 
  @BeforeAll
  public static void commonSetup() {
    // e.g. provide WireMock stubs
  }
}
```

## Transaction Management

Roll Back Changes Using @Transactional

Earlier, when testing the persistence layer we saw how @DataJpaTest makes tests @Transactional by default.
However, @SpringBootTest does not do this, so if we would like to roll back any changes after tests, we have to add the @Transcational annotation ourselves:

## Links

- [Spring Boot](/docs/CS/Java/Spring_Boot/Spring_Boot.md)
