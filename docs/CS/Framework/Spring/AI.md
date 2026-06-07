## Introduction

Spring AI 是一个用于 AI 工程的应用框架。其目标是将 Spring 生态系统设计原则（如可移植性和模块化设计）应用于 AI 领域，并推广使用 POJO 作为应用的构建块。

Spring AI 解决了 AI 集成的根本难题：将企业数据和 API 与 AI 模型连接起来

![spring-ai-integration-diagram-3](https://images.ctfassets.net/mnrwi97vnhts/4mda205vy509Dx3vGkMwFr/af520e66dc79fb80cd1bc129a11d6d23/spring-ai-integration-diagram-3.svg)

spring-ai-openai-starter

配置 application.properties
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

通常大模型的响应耗时较长，为了优化用户体验，ChatGPT 等厂商纷纷采用流式输出；我们可以通过 Reactor 框架来实现

```java
private ExecutorService executor = new ThreadPoolExecutor(1, 1, 0L, TimeUnit.MICROSECONDS, new LinkedBlockingQueue<>(10));

@GetMapping(value = "/hello/stream", produces = "text/html;charset=UTF-8")
public Flux<String> helloStream(@RequestParam(value = "input", defaultValue = "讲一个笑话") String input) {

    return chatClient.prompt(input).stream().content();

}
```

https://bailian.console.aliyun.com/?tab=model#/api-key&userCode=okjhlpr5 也支持这套 OpenAI 规范

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

Spring Boot 通过 AutoConfiguration.imports 申明自动装配的全限定类名，在 Spring AI 工程中，会引入 spring-ai-spring-boot-autoconfigure 模块，该模块完成 Spring AI 自动装配

观察 ChatClientAutoConfiguration 类，只要 ChatClient 对应的 Class 存在即生效
类中申明 ChatClient.BuilderBean，该 Bean 的构造依赖 ChatClientBuilderConfigurer、ChatModel、ObservationRegistry、ObservationConvention 四个对象

在 chatClientBuilder 方法中调用 ChatClient.builder 最终构造 DefaultChatClientBuilder 实例，也就是说 ChatClient.builder 的本质是 DefaultChatClientBuilder

[Spring AI Alibaba OpenManus 框架 bug](https://github.com/spring-projects/spring-ai/issues/2497?spm=ata.28742492.0.0.40ac3fed6bplVT)

当我们基于框架进行二次开发时，必须使用该补丁实现覆盖掉原框架中的实现，否则会出现上述反序列化异常

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
