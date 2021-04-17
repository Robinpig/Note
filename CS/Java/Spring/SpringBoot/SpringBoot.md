# SpringBoot



## [How to start Spring Boot Application?](https://github.com/Robinpig/Note/blob/master/CS/Java/Spring/SpringBoot/Start.md)

## Annotations

### @SpringBootApplication

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Inherited
@SpringBootConfiguration
@EnableAutoConfiguration
@ComponentScan(excludeFilters = { @Filter(type = FilterType.CUSTOM, classes = TypeExcludeFilter.class),
      @Filter(type = FilterType.CUSTOM, classes = AutoConfigurationExcludeFilter.class) })
public @interface SpringBootApplication {
```

#### @SpringBootConfiguration

```java
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Configuration
public @interface SpringBootConfiguration {
```

##### @Configuration



#### @EnableAutoConfiguration

```
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Inherited
@AutoConfigurationPackage
@Import(AutoConfigurationImportSelector.class)
public @interface EnableAutoConfiguration {
```

In class AutoConfigurationImportSelector, **getAutoConfigurationEntry** load configurations.

```java
/**
 * Return the {@link AutoConfigurationEntry} based on the {@link AnnotationMetadata}
 * of the importing {@link Configuration @Configuration} class.
 * @param annotationMetadata the annotation metadata of the configuration class
 * @return the auto-configurations that should be imported
 */
protected AutoConfigurationEntry getAutoConfigurationEntry(AnnotationMetadata annotationMetadata) {
   if (!isEnabled(annotationMetadata)) {
      return EMPTY_ENTRY;
   }
   AnnotationAttributes attributes = getAttributes(annotationMetadata);
   List<String> configurations = getCandidateConfigurations(annotationMetadata, attributes);
   configurations = removeDuplicates(configurations);
   Set<String> exclusions = getExclusions(annotationMetadata, attributes);
   checkExcludedClasses(configurations, exclusions);
   configurations.removeAll(exclusions);
   configurations = getConfigurationClassFilter().filter(configurations);
   fireAutoConfigurationImportEvents(configurations, exclusions);
   return new AutoConfigurationEntry(configurations, exclusions);
}
```

##### @AutoConfigurationPackage

```java
/**
 * Indicates that the package containing the annotated class should be registered with
 * {@link AutoConfigurationPackages}.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Inherited
@Import(AutoConfigurationPackages.Registrar.class)
public @interface AutoConfigurationPackage {
```

```java
/**
 * {@link ImportBeanDefinitionRegistrar} to store the base package from the importing
 * configuration.
 */
static class Registrar implements ImportBeanDefinitionRegistrar, DeterminableImports {

   @Override
   public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
      register(registry, new PackageImport(metadata).getPackageName());
   }

   @Override
   public Set<Object> determineImports(AnnotationMetadata metadata) {
      return Collections.singleton(new PackageImport(metadata));
   }

}
```



~~~java
/**
 * Interface that can be implemented by {@link ImportSelector} and
 * {@link ImportBeanDefinitionRegistrar} implementations when they can determine imports
 * early. The {@link ImportSelector} and {@link ImportBeanDefinitionRegistrar} interfaces
 * are quite flexible which can make it hard to tell exactly what bean definitions they
 * will add. This interface should be used when an implementation consistently results in
 * the same imports, given the same source.
 * <p>
 * Using {@link DeterminableImports} is particularly useful when working with Spring's
 * testing support. It allows for better generation of {@link ApplicationContext} cache
 * keys.
 */
@FunctionalInterface
public interface DeterminableImports {

   /**
    * Return a set of objects that represent the imports. Objects within the returned
    * {@code Set} must implement a valid {@link Object#hashCode() hashCode} and
    * {@link Object#equals(Object) equals}.
    * <p>
    * Imports from multiple {@link DeterminableImports} instances may be combined by the
    * caller to create a complete set.
    * <p>
    * Unlike {@link ImportSelector} and {@link ImportBeanDefinitionRegistrar} any
    * {@link Aware} callbacks will not be invoked before this method is called.
    * @param metadata the source meta-data
    * @return a key representing the annotations that actually drive the import
    */
   Set<Object> determineImports(AnnotationMetadata metadata);

}
~~~

##### register

```java
/**
 * Programmatically registers the auto-configuration package names. Subsequent
 * invocations will add the given package names to those that have already been
 * registered. You can use this method to manually define the base packages that will
 * be used for a given {@link BeanDefinitionRegistry}. Generally it's recommended that
 * you don't call this method directly, but instead rely on the default convention
 * where the package name is set from your {@code @EnableAutoConfiguration}
 * configuration class or classes.
 * @param registry the bean definition registry
 * @param packageNames the package names to set
 */
public static void register(BeanDefinitionRegistry registry, String... packageNames) {
   if (registry.containsBeanDefinition(BEAN)) {
      BeanDefinition beanDefinition = registry.getBeanDefinition(BEAN);
      ConstructorArgumentValues constructorArguments = beanDefinition.getConstructorArgumentValues();
      constructorArguments.addIndexedArgumentValue(0, addBasePackages(constructorArguments, packageNames));
   }
   else {
      GenericBeanDefinition beanDefinition = new GenericBeanDefinition();
      beanDefinition.setBeanClass(BasePackages.class);
      beanDefinition.getConstructorArgumentValues().addIndexedArgumentValue(0, packageNames);
      beanDefinition.setRole(BeanDefinition.ROLE_INFRASTRUCTURE);
      registry.registerBeanDefinition(BEAN, beanDefinition);
   }
}
```



###### @Import



## Web

![SpringBoot Web Annotation](https://github.com/Robinpig/Note/raw/master/images/Spring/springboot-web-annotation.png)

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











