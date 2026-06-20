## Introduction

[Apache Log4j](https://logging.apache.org/log4j/2.x/) is a versatile, industrial-grade Java logging framework composed of an API, its implementation, and components to assist the deployment for various use cases. 

### Log4j features

- Log4j bundles a rich set of components to assist various use cases.
  - Appenders targeting files, network sockets, databases, SMTP servers, etc.
  - Layouts that can render CSV, HTML, JSON, Syslog, etc. formatted outputs
  - Filters that can be configured using log event rates, regular expressions, scripts, time, etc.
  - Lookups for accessing system properties, environment variables, log event fields, etc.
- The API for Log4j (i.e., ) is separate from the implementation (i.e., ) making it clear for application developers which classes and methods they can use while ensuring forward compatibility.
- Even though the Log4j API is implemented by the Log4j at its fullest, users can choose to use another logging backend. This can be achieved by either using another backend implementing the Log4j API, or forwarding Log4j API calls to another logging facade (e.g., SLF4J) and using a backend for that particular facade.
- When configured correctly, Log4j can deliver excelling performance without almost any burden on the Java garbage collector. This is made possible via an asynchronous logger founded on the LMAX Disruptor technology (having its roots in the demanding industry of financial trading) and the garbage-free features baked at hot paths. 
- Log4j contains a fully-fledged plugin support that users can leverage to extend its functionality. 


## Lookups

Lookups provide a way to add values to the Log4j configuration at arbitrary places. They are a particular type of Plugin that implements the StrLookup interface. 

### Jndi lookup

As of Log4j 2.17.0 [JNDI](/docs/CS/Java/JDK/Basic/JNDI.md) operations require that `log4j2.enableJndiLookup=true` be set as a system property or the corresponding environment variable for this lookup to function. See [CVE-2021-44228](https://www.cve.org/CVERecord?id=CVE-2021-44228), [CVE-2021-45046](https://www.cve.org/CVERecord?id=CVE-2021-45105), [CVE-2021-45046](https://www.cve.org/CVERecord?id=CVE-2021-45105) and [CVE-2021-44832](https://www.cve.org/CVERecord?id=CVE-2021-44832).

The JNDI Lookup only supports the java protocol or no protocol.


**Java's JNDI module is not available on Android.**


## Async



get stack trace(not suggest to enable in PROD)

- 1.8 new throwable
- 9+ stackwalker

```c++
// javaclasses.cpp
void java_lang_Throwable::get_stack_trace_elements(int depth, Handle backtrace,
                                                   objArrayHandle stack_trace_array_h, TRAPS) {

    // ...
    InstanceKlass* holder = InstanceKlass::cast(java_lang_Class::as_Klass(bte._mirror()));
    methodHandle method (THREAD, holder->method_with_orig_idnum(bte._method_id, bte._version));

    java_lang_StackTraceElement::fill_in(stack_trace_element, holder,
                                         method,
                                         bte._version,
                                         bte._bci,
                                         bte._name,
                                         CHECK);
  }
}
```


```cpp
// stackwalk.cpp
oop StackWalk::walk(Handle stackStream, jlong mode, int skip_frames, Handle cont_scope, Handle cont,
                    int frame_count, int start_index, objArrayHandle frames_array,
                    TRAPS) {
  // ...
  // Setup traversal onto my stack.
  if (live_frame_info(mode)) {
    RegisterMap regMap = cont.is_null() ? RegisterMap(jt,
                                                      RegisterMap::UpdateMap::include,
                                                      RegisterMap::ProcessFrames::include,
                                                      RegisterMap::WalkContinuation::include)
                                        : RegisterMap(cont(), RegisterMap::UpdateMap::include);
    LiveFrameStream stream(jt, &regMap, cont_scope, cont);
    return fetchFirstBatch(stream, stackStream, mode, skip_frames, frame_count,
                           start_index, frames_array, THREAD);
  } else {
    JavaFrameStream stream(jt, mode, cont_scope, cont);
    return fetchFirstBatch(stream, stackStream, mode, skip_frames, frame_count,
                           start_index, frames_array, THREAD);
  }
}
```


### RingBuffer




### Metrics



### Batch flush


### Wait strategy


AsyncLoggerConfig.WaitStrategy=Sleep







## Links

- [logback](/docs/CS/log/logback.md)


## References

1. [LMAX Disruptor](https://lmax-exchange.github.io/disruptor/)