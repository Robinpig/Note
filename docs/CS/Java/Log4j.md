## Introduction

[Apache Log4j](https://logging.apache.org/log4j/2.x/) 是一个多功能的工业级 Java 日志框架，由 API、其实现以及辅助各种用例部署的组件组成。

### Log4j features

- Log4j 捆绑了丰富的组件以支持各种用例。
  - Appenders 目标为文件、网络套接字、数据库、SMTP 服务器等。
  - Layouts 可以渲染 CSV、HTML、JSON、Syslog 等格式的输出。
  - Filters 可以根据日志事件速率、正则表达式、脚本、时间等进行配置。
  - Lookups 用于访问系统属性、环境变量、日志事件字段等。
- Log4j 的 API 与其实现分离，使应用开发者清楚哪些类和方法可以使用，同时确保前向兼容性。
- 尽管 Log4j API 由 Log4j 最充分地实现，用户可以选择使用其他日志后端。这可以通过使用实现 Log4j API 的其他后端，或者将 Log4j API 调用转发给其他日志门面（例如 SLF4J）并为该门面使用特定的后端来实现。
- 正确配置后，Log4j 可以在几乎不给 Java 垃圾收集器带来负担的情况下提供卓越的性能。这得益于基于 LMAX Disruptor 技术的异步日志记录器（其根源在于金融交易的苛刻行业）以及在热路径上内建的无垃圾特性。
- Log4j 包含完整的插件支持，用户可以利用它来扩展其功能。

## Lookups

Lookups 提供了一种在任意位置向 Log4j 配置添加值的方式。它们是实现 StrLookup 接口的一种特定类型的 Plugin。

### Jndi lookup

从 Log4j 2.17.0 开始，[JNDI](/docs/CS/Java/JDK/Basic/JNDI.md) 操作需要设置系统属性或相应的环境变量 `log4j2.enableJndiLookup=true` 才能使用此 lookup。参见 [CVE-2021-44228](https://www.cve.org/CVERecord?id=CVE-2021-44228)、[CVE-2021-45046](https://www.cve.org/CVERecord?id=CVE-2021-45105)、[CVE-2021-45046](https://www.cve.org/CVERecord?id=CVE-2021-45105) 和 [CVE-2021-44832](https://www.cve.org/CVERecord?id=CVE-2021-44832)。

JNDI Lookup 仅支持 java 协议或不使用协议。

**Java 的 JNDI 模块在 Android 上不可用。**

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
