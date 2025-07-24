## Introduction



spring-ai-openai-starter

配置application.properties
```properties
spring.application.name=hello
spring.ai.openai.api-key=换成个人的DeepSeek API key
spring.ai.openai.base-url=https://api.deepseek.com
spring.ai.openai.chat.options.model=deepseek-chat
```



```java
@RestController
public class HelloController {

    private ChatClient chatClient;

    public HelloController(ChatClient.Builder builder) {
        this.chatClient = builder.build();
    }
    @GetMapping("/hello")
    public String hello(@RequestParam(value = "input", defaultValue = "讲一个笑话") String input) {

        return chatClient.prompt(input).call().content();

    }
}
```

通常大模型的响应耗时较长，为了优化用户体验，ChatGPT等厂商纷纷采用流式输出；我们可以通过Reactor框架来实现

```java
private ExecutorService executor = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MICROSECONDS, new LinkedBlockingQueue<>(10));

@GetMapping(value = "/hello/stream", produces = "text/html;charset=UTF-8")
public Flux<String> helloStream(@RequestParam(value = "input", defaultValue = "讲一个笑话") String input) {

    return chatClient.prompt(input).stream().content();

}

```

https://bailian.console.aliyun.com/?tab=model#/api-key&userCode=okjhlpr5 也支持这套 OpenAI规范


## 监控


```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<dependency>
<groupId>io.micrometer</groupId>
<artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

management.endpoints.web.exposure.include=health,metrics,prometheus
spring.ai.observability.enabled=true

Spring Boot通过AutoConfiguration.imports申明自动装配的全限定类名， 在Spring AI工程中，会引入spring-ai-spring-boot-autoconfigure模块，该模块完成Spring AI自动装配

观察ChatClientAutoConfiguration类，只要ChatClient对应的Class存在即生效
类中申明ChatClient.BuilderBean，该Bean的构造依赖ChatClientBuilderConfigurer、ChatModel、ObservationRegistry、ObservationConvention四个对象

在chatClientBuilder方法中调用ChatClient.builder最终构造DefaultChatClientBuilder实例，也就是说ChatClient.builder的本质是DefaultChatClientBuilder

[Spring AI Alibaba OpenManus 框架bug](https://github.com/spring-projects/spring-ai/issues/2497?spm=ata.28742492.0.0.40ac3fed6bplVT)

当我们基于框架进行二次开发时，必须使用该补丁实现覆盖掉原框架中的实现，否则会出现上述反序列化异常



## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
