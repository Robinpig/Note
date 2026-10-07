## Introduction

[Spring AI](https://spring.io/projects/spring-ai) is an application framework for AI engineering. Its goal is to apply to the AI domain Spring ecosystem design principles such as portability and modular design and promote using POJOs as the building blocks of an application to the AI domain.

Spring AI 解决了 AI 集成的根本难题：将企业数据和 API 与 AI 模型连接起来。

> [!NOTE]
> 版本基线：Spring AI **1.0** 于 2025-05 GA，对应 Spring Boot 3.4+；Jackson 3 支持在其 2.0 一线引入（Spring AI 是 Spring 家族中最晚切换到 Jackson 3 的项目）。其自动配置完全沿用 Boot 的 starter + `AutoConfiguration.imports` 机制。

![spring-ai-integration-diagram-3](https://images.ctfassets.net/mnrwi97vnhts/4mda205vy509Dx3vGkMwFr/af520e66dc79fb80cd1bc129a11d6d23/spring-ai-integration-diagram-3.svg)

设计思路与 Spring 一贯的抽象哲学一致：`ChatModel` 之于大模型，如同 `JdbcTemplate` 之于数据库——统一接口屏蔽厂商差异（OpenAI、Anthropic、Ollama、DeepSeek 等各有 starter），可移植的 prompt 与 options 配置不绑定具体供应商。

## Core Concepts

| 概念 | 职责 |
| :-- | :-- |
| `ChatClient` | 面向应用的流式 fluent API 入口（prompt 编排、advisors、结构化输出） |
| `ChatModel` | 可移植的模型调用抽象，各厂商一个实现（`OpenAiChatModel`、`OllamaChatModel` …） |
| `Prompt` | 消息列表 + 运行时选项的封装，一次调用的全部输入 |
| `Message` | `SystemMessage` / `UserMessage` / `AssistantMessage` / `ToolResponseMessage` 四类角色消息 |
| `ChatOptions` | 模型参数（model、temperature、maxTokens…），运行时选项覆盖默认值 |
| `EmbeddingModel` | 向量嵌入抽象，供 RAG / 相似度检索使用 |

## Getting Started Example

spring-ai-openai-starter 配置 `application.properties`（OpenAI 兼容协议，换 base-url 即可接入 DeepSeek、阿里云百炼等）：

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

通常大模型的响应耗时较长，为了优化用户体验，ChatGPT等厂商纷纷采用流式输出；我们可以通过 [Reactor](/docs/CS/Framework/Spring/Reactive.md) 框架来实现：

```java
@GetMapping(value = "/hello/stream", produces = "text/html;charset=UTF-8")
public Flux<String> helloStream(@RequestParam(value = "input", defaultValue = "讲一个笑话") String input) {

    return chatClient.prompt(input).stream().content();

}
```

https://bailian.console.aliyun.com/?tab=model#/api-key&userCode=okjhlpr5 也支持这套 OpenAI规范

## Advisors

Advisor 是环绕 `ChatModel` 调用的拦截器（类比 MVC 的 HandlerInterceptor、WebFlux 的 WebFilter），在请求发送前后增强 Prompt 与响应：

- `SimpleLoggerAdvisor`：打印请求 / 响应日志，调试必备。
- `MessageChatMemoryAdvisor`：把[会话记忆](?id=chatmemory)注入消息列表。
- `QuestionAnswerAdvisor`：RAG 检索增强，见下文。
- `SafeGuardAdvisor`：命中敏感词时直接短路返回。

```java
String content = chatClient.prompt()
        .user(input)
        .advisors(a -> a.advisors(
                new SimpleLoggerAdvisor(),
                MessageChatMemoryAdvisor.builder(chatMemory).conversationId(sessionId).build()))
        .call()
        .content();
```

### ChatMemory

Spring AI 1.x 提供 `ChatMemory` 抽象，默认实现 `MessageWindowChatMemory`（滑动窗口截断历史，防止上下文超限），可替换为 JDBC / Redis 等持久化实现。

## Tool Calling

让模型把自然语言请求转成函数调用，由框架负责执行并把结果回传模型继续推理（agentic loop 的基础）。Spring AI 1.x 使用 `@Tool` 注解声明工具：

```java
class WeatherTools {

    @Tool(description = "按城市查询当前天气")
    String currentWeather(@ToolParam(description = "城市名") String city) {
        return weatherApi.query(city);
    }
}
```

```java
String answer = chatClient.prompt()
        .user("上海今天适合跑步吗")
        .tools(new WeatherTools())
        .call()
        .content();
```

`ToolCallingManager` 内部维护执行循环：模型返回 tool call 请求 → 框架反射执行 → 结果包装为 `ToolResponseMessage` 再送回模型，直到模型给出最终回答。工具也可通过 MCP 协议远程暴露，见下文。

## Structured Output

`.call().entity(Class)` 一行把模型输出转成 Java 对象，底层由 `BeanOutputConverter`（Jackson 反序列化 + 自动生成 JSON Schema 提示）、`MapOutputConverter` / `ListOutputConverter` 承担：

```java
record Movie(String title, int year, List<String> actors) {}

Movie movie = chatClient.prompt()
        .user("推荐一部诺兰的电影")
        .call()
        .entity(Movie.class);
```

## RAG

ETL 三段式管道负责知识入库，检索增强由 Advisor 在对话时注入：

```
DocumentReader（PDF/HTML/Tika） → DocumentTransformer（TokenTextSplitter 切块） → DocumentWriter（VectorStore.write()）
```

- `VectorStore` 是向量库统一抽象，官方适配 PGvector、Redis、Milvus、Elasticsearch、Chroma、Qdrant 等，检索入口为 `similaritySearch(SearchRequest)`（可带 metadata 过滤表达式）。
- 应用侧通常不需要手写检索逻辑，挂上 `QuestionAnswerAdvisor` 即可：内部完成查询改写 → 向量检索 → 上下文拼装进 system prompt。
- RAG 的整体架构（离线入库 / 在线检索、与重排的组合）见 [RAG](/docs/CS/AI/RAG.md)。

## MCP

Spring AI 提供 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 客户端与服务端两套 starter（`spring-ai-starter-mcp-client` / `spring-ai-starter-mcp-server`，传输层分 stdio 与 SSE/WebFlux 变体）：

- 作为 **MCP Client**：应用接入任意 MCP Server，把外部工具自动注册进 `ToolCallback` 列表，与 `@Tool` 本地工具无差别使用。
- 作为 **MCP Server**：把自有业务工具按 MCP 规范暴露，供 Claude Desktop 等任意 MCP 宿主调用，实现"一次开发、处处接入"。

## Agentic Patterns

Spring AI 官方参考 [Anthropic 的 Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)，把应用形态分为 **Workflow（预编排流程）** 与 **Agent（自主循环）** 两类。前者可控性高、成本低，后者灵活但代价大，应按需降级：

| Pattern | 形态 | Spring AI 实现要点 |
| :-- | :-- | :-- |
| Chain（链式） | Workflow | 前一步输出作为后一步输入，串接多个 ChatClient 调用 |
| Parallelization（并行） | Workflow | 同一输入 fan-out 给多个模型/视角，fan-in 汇总（配合 `CompletableFuture` / Reactor） |
| Router（路由） | Workflow | 先分类再分发，结构化输出返回路由决策 |
| Orchestrator-workers | Workflow | 中心模型拆解任务分派给 worker，再聚合结果 |
| Evaluator-optimizer | Workflow | 生成器 + 评估器循环打分迭代，直到达标 |
| Agent（自主循环） | Agent | Tool Calling 执行循环 + ChatMemory 维持状态，模型自主决定下一步 |

Agent 模式 = ChatClient + `tools()` + ChatMemory 的自然组合；更复杂的编排建议外置到工作流引擎或 [Agent 平台](/docs/CS/AI/LLM/Agent/Theory/Agent.md)。

## Monitoring

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

观察 ChatClientAutoConfiguration 类，只要 ChatClient 对应的 Class 存在即生效
类中申明 ChatClient.BuilderBean，该 Bean 的构造依赖 ChatClientBuilderConfigurer、ChatModel、ObservationRegistry、ObservationConvention 四个对象

在chatClientBuilder方法中调用ChatClient.builder最终构造DefaultChatClientBuilder实例，也就是说ChatClient.builder的本质是DefaultChatClientBuilder

Micrometer Observation 侧自动产出 `spring.ai.chat.client` / `spring.ai.chat.model` 两组 metrics 与 spans（token 用量、耗时等），可接入 Prometheus / Zipkin。

[Spring AI Alibaba OpenManus 框架bug](https://github.com/spring-projects/spring-ai/issues/2497?spm=ata.28742492.0.0.40ac3fed6bplVT)

当我们基于框架进行二次开发时，必须使用该补丁实现覆盖掉原框架中的实现，否则会出现上述反序列化异常

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [RAG](/docs/CS/AI/RAG.md)
- [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md)

## References

1. [Spring AI Reference](https://docs.spring.io/spring-ai/reference/)
2. [Spring AI (GitHub)](https://github.com/spring-projects/spring-ai)
3. [Building Effective Agents — Anthropic](https://www.anthropic.com/engineering/building-effective-agents)