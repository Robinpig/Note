## Introduction

Retrofit 是 Square 开源的**类型安全 HTTP 客户端**（Android 与 Java），核心思想是**声明式接口 + 动态代理**：只定义一个 Java 接口并用注解描述 HTTP 方法、路径、参数，Retrofit 在运行时通过 `Proxy.newProxyInstance` 生成实现类，把方法调用翻译成 HTTP 请求，再用底层 HTTP 客户端（默认 OkHttp）发出并把响应反序列化为声明的返回类型。它不直接做网络 IO——真正的连接池、拦截器、HTTP/2 都在 OkHttp 层。

## 声明与调用

```java
interface GitHubService {
    @GET("users/{user}/repos")
    Call<List<Repo>> listRepos(@Path("user") String user);

    @POST("repos/{owner}/{repo}/issues")
    Call<Issue> createIssue(@Path("owner") String owner, @Path("repo") String repo,
                            @Body IssueReq body);
}

Retrofit retrofit = new Retrofit.Builder()
        .baseUrl("https://api.github.com/")
        .addConverterFactory(JacksonConverterFactory.create())  // 响应反序列化
        .build();
GitHubService svc = retrofit.create(GitHubService.class);      // 动态代理
List<Repo> repos = svc.listRepos("octocat").execute().body();  // 同步；enqueue() 异步
```

注解与参数映射：

| 注解 | 含义 |
|------|------|
| `@GET/@POST/@PUT/@DELETE` + 相对路径 | HTTP 方法与资源路径 |
| `@Path` | 替换 URL 模板 `{id}` |
| `@Query/@QueryMap` | URL 查询参数（自动 URL encode） |
| `@Body` | 请求体（经 Converter 序列化为 JSON） |
| `@FormUrlEncoded + @Field` | 表单提交 |
| `@Header/@Headers` | 静态/动态请求头（鉴权 token） |
| `@Multipart + @Part` | 文件上传 |
| `@Url` | 动态完整 URL |

## 适配层：Call 之外的返回类型

默认返回 `Call<T>`；注册 adapter 后接口方法可直接返回：

- RxJava 的 `Observable/Flowable/Single`（RxJava2/3 CallAdapter）；
- Kotlin 协程 `suspend fun ... : T`（Retrofit 2.6+ 原生支持，内部转 `Call.enqueue`）；
- Guava `ListenableFuture`。

这种"接口 + 适配"分层让业务代码完全看不到 HTTP 细节，也便于单测时把接口 mock 成普通对象。

## Converter 与 OkHttp 拦截器

- ConverterFactory 决定序列化：Gson（最常用）、Jackson、Moshi、Protobuf、Wire；必须与 `Content-Type` 匹配。
- 横切逻辑放在 OkHttp Interceptor 而不是 Retrofit 接口里：鉴权头注入、统一加签、日志（HttpLoggingInterceptor）、重试与超时、解压。应用拦截器与网络拦截器（跟随重定向后、看到真实连接）的层级不同。
- 错误处理：`response.isSuccessful()`（2xx）与业务错误码要分开；异常分 IOException（网络层）与解析异常两类。

## 与 Feign 的定位差异

- **Retrofit**：端上（Android）出身，也广泛用于服务端，轻量、强依赖 OkHttp、注解描述偏 RESTful 资源；
- **[Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)**：微服务间调用出身，与 Spring Cloud/服务发现/负载均衡/熔断深度集成，接口上直接贴 Spring MVC 注解，服务端 Java 生态更主流；
- 二者架构同源（声明式接口 + 动态代理 + 可插拔编解码），可对照学习，理解一个就理解另一个。Go 侧的同类思路见 [go-resty](/docs/CS/Go/Framework/go-resty.md)（但 go-resty 是链式客户端而非动态代理）。

## Links

- [Feign](/docs/CS/Framework/Spring_Cloud/Feign.md)
- [go-resty](/docs/CS/Go/Framework/go-resty.md)
- [Jackson](/docs/CS/Java/Jackson.md)
- [RxJava](/docs/CS/Framework/RxJava/RxJava.md)
- [gRPC](/docs/CS/Framework/gRPC/gRPC.md)

## References

1. [Retrofit 官方文档](https://square.github.io/retrofit/)
2. [Retrofit GitHub](https://github.com/square/retrofit)
