## Introduction

The holy grail of observability is having a system that allows you to discover any previously unknown state without deploying additional code to diagnose it.
Monitoring and observability are separate, but dependent. Namely, if a system is observable, it can be monitored.

The three pillars of observability are **Metrics**, **Tracing**, and **Logging**.
Each pillar has a distinct role to play in infrastructure and application monitoring and is essential in gaining visibility into containerized or serverless applications.

Working with these pillars individually, or using different tools for each one, does not guarantee observability. But by combining your metrics, traces, and logs into a single solution, you can create a successful observability approach.

### Metrics

Metrics are numeric values that represent and describe the overall behavior of a service or component measured over time. They include features like timestamp, name, and value. Metrics, unlike logs, are structured by default, making them easy to query and optimize for storage, so you can keep them for extended periods of time.


With monitoring tools, you can visualize metrics you care about and configure alerts (especially with tools like [Prometheus](https://prometheus.io/)). Most metrics-based monitoring solutions allow you to combine data from a small number of labels, which can help you see which service is having an issue or on which machines it's happening. Metrics allow you to define what is normal and what is not.

Let’s say you get a [PagerDuty](https://www.pagerduty.com/) alert that your database connections have exceeded the maximum threshold in one of your services (we’ll call it “Order service”). New connections could be timing out or requests could be queued, driving up latency—you don’t know yet. The metric that triggered the alert doesn’t tell you what customers are experiencing or why the system got to its current state. You need other pillars of observability to know more.


### Tracing

Tracing is used to understand how an application’s different services connect and how resources flow through them. Traces helps engineers analyze request flow and understand the entire lifecycle of a request in a distributed application. Every operation done on a request, also called a "span," is encoded with critical data related to the microservice conducting that operation as it passes through the host system. Tracking the path of a trace through a distributed system may help you find the reason for a bottleneck or breakdown.

Using tracing tools, such as [Jaeger](https://www.jaegertracing.io/) and [Zipkin](https://zipkin.io/), you can look into individual system calls and figure out what's going on with your underlying components (which took the most or least time, whether or not specific underlying processes generated errors, etc.). Traces are also an excellent way to go deep into a metrics system alert.


Distributed tracing, also called distributed request tracing, is a method used to profile and monitor applications, especially those built using a microservices architecture. 
Distributed tracing helps pinpoint where failures occur and what causes poor performance.




### Logging

With metrics and tracing, it’s hard to understand how the system got to its current state. This is where logging comes into play. Logs are immutable records of discrete events that happened over some time within an application. They help uncover emergent and unpredictable behaviors exhibited by each component in a microservices architecture. Logs can also be seen as a text record of an event with a timestamp that indicates when it happened and a payload that offers context.

There are three types of logs: plain text, structured, and binary. While logs in plain-text format are common, it’s better when they’re structured, include contextual data, and are quicker to access. As a rule of thumb, logs should be readable by humans and parsable by machines. When something goes wrong in a system, logs are the first place to look.

Because every component of a cloud-native application emits logs, logs should be centralized so you can get the most out of them. [Elasticsearch](https://www.elastic.co/), [Fluentd](https://www.fluentd.org/), and [Kibana](https://www.elastic.co/kibana) (part of the EFK Stack that allows full-text and structured searches) are commonly used to centralize logs.

## OpenTracing

It is probably easier to start with what OpenTracing is NOT.

- OpenTracing is not a download or a program. Distributed tracing requires that software developers add instrumentation to the code of an application, or to the frameworks used in the application.
- OpenTracing is not a standard. The Cloud Native Computing Foundation (CNCF) is not an official standards body. 
  The OpenTracing API project is working towards creating more standardized APIs and instrumentation for distributed tracing.

OpenTracing is comprised of an API specification, frameworks and libraries that have implemented the specification, and documentation for the project. 
OpenTracing allows developers to add instrumentation to their application code using APIs that do not lock them into any one particular product or vendor.


## The OpenTracing Data Model

Traces in OpenTracing are defined implicitly by their Spans. 
In particular, a Trace can be thought of as a directed acyclic graph (DAG) of Spans, where the edges between Spans are called References.

For example, the following is an example Trace made up of 8 Spans:

```
Causal relationships between Spans in a single Trace

        [Span A]  ←←←(the root span)
            |
     +------+------+
     |             |
 [Span B]      [Span C] ←←←(Span C is a `ChildOf` Span A)
     |             |
 [Span D]      +---+-------+
               |           |
           [Span E]    [Span F] >>> [Span G] >>> [Span H]
                                       ↑
                                       ↑
                                       ↑
                         (Span G `FollowsFrom` Span F)
```

Each Span encapsulates the following state:

- An operation name
- A start timestamp
- A finish timestamp
- A set of zero or more key:value Span Tags. The keys must be strings. The values may be strings, bools, or numeric types.
- A set of zero or more Span Logs, each of which is itself a key:value map paired with a timestamp. 
  The keys must be strings, though the values may be of any type. Not all OpenTracing implementations must support every value type.
- A SpanContext (see below)
- References to zero or more causally-related Spans (via the SpanContext of those related Spans)

Each SpanContext encapsulates the following state:

- Any OpenTracing-implementation-dependent state (for example, trace and span ids) needed to refer to a distinct Span across a process boundary
- Baggage Items, which are just key:value pairs that cross process boundaries


## OpenTelemetry

OpenTelemetry is an `Observability` framework and toolkit designed to create and manage _telemetry data_ such as `traces`, `metrics`, and `logs`. 
Crucially, OpenTelemetry is vendor- and tool-agnostic, meaning that it can be used with a broad variety of Observability backends, 
including open source tools like [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) and [Prometheus](/docs/CS/Distributed/Tracing/Prometheus.md), as well as commercial offerings. 
OpenTelemetry is a Cloud Native Computing Foundation (CNCF) project.

OpenTelemetry is not an observability back-end like Jaeger, Prometheus, or commercial vendors.
OpenTelemetry is focused on the generation, collection, management, and export of telemetry data.
The storage and visualization of that data is intentionally left to other tools.





## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed_Systems.md)


## References

1. [OpenTelemetry](https://opentelemetry.io/)
2. [OpenTracing specification](https://opentracing.io/specification/)
