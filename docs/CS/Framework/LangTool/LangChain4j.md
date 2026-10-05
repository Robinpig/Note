## Introduction

LangChain4j 是 LangChain 思想的 **Java 实现**：用统一抽象屏蔽各家大模型 API 差异，把 Prompt、记忆、工具调用、RAG、Agent 编排组装成可工程化的应用框架。它的目标用户是已经身处 Spring/Quarkus 生态、希望把 LLM 能力引入后端服务（而非另起一个 Python 服务）的 Java 团队。

与 Python 版 [LangChain](/docs/CS/Framework/LangTool/LangChain.md) 的关系：**理念同源、API 各自地道**。LangChain4j 不是逐行移植，而是按 Java 习惯重新设计（Builder、接口、声明式 AiServices），并深度集成 Spring Boot / Quarkus。需要长流程有状态编排（检查点、分叉、人机协同）时，Java 侧通常直接用 Spring AI 或自研状态机，对应 Python 生态的 [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md)。

## 核心抽象

| 抽象 | 作用 |
| --- | --- |
| `ChatLanguageModel` / `StreamingChatLanguageModel` | 对话模型统一接口：同步返回或流式回调（`onPartialResponse`） |
| `ChatMemory` | 对话历史窗口：`MessageWindowChatMemory`（按条数）等，底层可接持久化 |
| `AiServices` | **声明式 Agent 接口**：只写接口 + 注解，框架用动态代理生成实现 |
| `@Tool` | 把一个普通 Java 方法暴露给模型，自动从方法签名与 Javadoc 生成工具 schema |
| `EmbeddingModel` / `EmbeddingStore` | 向量化模型与向量库（In-memory、PgVector、Milvus、Elasticsearch、Redis 等） |
| `ContentRetriever` / `RetrievalAugmentor` | RAG 检索与增强：文档切分、检索、重排、注入 Prompt |
| `Document` / `DocumentSplitter` | 文档加载与切分（按段落/Token/递归） |

## AiServices：声明式接口

最能体现 LangChain4j 风格的设计——接口即应用，机制上与 [Retrofit](/docs/CS/Java/Retrofit.md) 的动态代理、[Spring AOP](/docs/CS/Java/AspectJ.md) 的代理生成本质相同：

```java
interface CustomerSupportAgent {
    String chat(String userMessage);
}

CustomerSupportAgent agent = AiServices.builder(CustomerSupportAgent.class)
        .chatLanguageModel(model)
        .chatMemory(MessageWindowChatMemory.withMaxMessages(20))
        .tools(orderQueryTool, refundTool)   // @Tool 标注的方法
        .contentRetriever(retriever)         // RAG
        .build();

String answer = agent.chat("我上周的订单到哪了？");
```

代理在运行时完成：组装历史记忆 → 检索知识 → 序列化工具描述 → 调用模型 → 模型请求工具时反射执行 Java 方法 → 把结果回填模型 → 返回最终答案。

## Agentic 工作流编排模式

LangChain4j Agentic 框架提供了多种工作流编排模式，按自主程度从低到高：

| 模式 | 控制流 | 适用 |
| --- | --- | --- |
| 单次 RAG | 检索一次 → 生成 | 知识问答 |
| Tools（Function Calling） | 模型在一轮内自主决定调用哪个 `@Tool` | 查询订单、调内部 API |
| Agent 循环 | 模型多轮「思考→调工具→观察」直到给出答案 | 多步任务 |
| 编排（workflow） | 开发者显式定义步骤与分支，模型只填空 | 合规要求高、流程固定的业务 |

经验法则与 Harness 三层划分一致：**流程越确定越该写死成编排，流程越开放越交给 Agent 循环**，参见 [Harness](/docs/CS/AI/LLM/Harness.md) 的 Runtime/Framework/Harness 分层。

## 与 Python 生态的取舍

| 维度 | LangChain4j | LangChain (Python) |
| --- | --- | --- |
| 团队 | 已有 Java 后端，单体/同进程集成 | 算法/数据团队，Python 技术栈 |
| 集成 | Spring Boot starter、Quarkus extension | 生态最广、新特性最快 |
| 编排 | 基础 Agent + 自研/Workflow 类 | LangGraph 成熟的图运行时 |
| 部署 | 打进现有 jar/war，无需跨语言运维 | 独立 Python 服务 |

如果团队主力是 Java 且需求是「给现有系统加一个会用工具、能查知识库的智能助手」，LangChain4j 是成本最低的选择；如果要做深度定制的多 Agent 研究型系统，Python 生态仍然领先。

## Links

- [LangChain](/docs/CS/Framework/LangTool/LangChain.md) / [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md) — Python 同源框架与图编排运行时
- [Agent](/docs/CS/AI/LLM/Agent.md) — Agent 四构成（Loop/Tools/Memory/Harness）
- [Harness](/docs/CS/AI/LLM/Harness.md) — Runtime / Framework / Harness 三层
- [RAG](/docs/CS/AI/RAG.md) — 检索增强生成
- [MCP](/docs/CS/AI/LLM/MCP.md) — 工具接入的标准化协议（对散落 @Tool 的协议化替代）
- [Retrofit](/docs/CS/Java/Retrofit.md) — 同为动态代理声明式接口的设计先例
- [AI](/docs/CS/Framework/Spring/AI.md)

## References

- [LangChain4j 官方文档](https://docs.langchain4j.dev/)
