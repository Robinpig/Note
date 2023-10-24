## Introduction

Distributed tracing, also called distributed request tracing, is a method used to profile and monitor applications, especially those built using a microservices architecture. 
Distributed tracing helps pinpoint where failures occur and what causes poor performance.




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
