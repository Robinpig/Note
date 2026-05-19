## Introduction



leuth 提供了一种无感知的集成方案，只需要添加一个依赖项，再做一些本地启动参数配
置就可以开启打标功能了，整个过程不需要做任何的代码改动

Sleuth 为了将 Trace ID 和 Customer 服务的 Span ID 传递给 Template 微服务，它在
OpenFeign 的环节动了一个手脚。Sleuth 通过 TracingFeignClient 类，将一系列 Tag
标记塞进了 OpenFeign 构造的服务请求的 Header 结构中



## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=sleuth)