## Introduction

In the fields of information technology and systems management,
**application performance management** (**APM**) is the monitoring and management of performance and availability of software applications.
APM strives to detect and diagnose complex application performance problems to maintain an expected level of service.
APM is the translation of IT metrics into business meaning ([i.e.] value).



常见的APM系统
- cat: 大众点评开源，实现方式为代码埋点，自带报表系统，集成时需要入侵代码，地址
- pinpoint: 韩国团队开发，通过JavaAgent实现，功能丰富，但收集数据过多，性能较差，地址
- zipkin :推特开源，与spring cloud集成较好，但也需修改代码地址
- skywalking : 华为吴晟开源，通过JavaAgent实现


分布式链路追踪最早由2010年提出的，当时谷歌发布了一篇 Dapper 论文，介绍了谷歌自研的分布式链路追踪的实现原理
[OpenTracing](/docs/CS/Distributed/Tracing/Tracing.md) 通过提供平台无关、厂商无关的API，使得开发人员能够方便的添加（或更换）追踪系统的实现
OpenTracing提供了用于运营支撑系统的和针对特定平台的辅助程序库


traceId

在gateway生成 向后传递 日志记录

日志收集 ELK







Logs

ELK

Collect

Send to

- Logstach
- Kafka

Traces






Not obey OpenTracing

- Zipkin
- Pinpoint

Metrics

Cat
