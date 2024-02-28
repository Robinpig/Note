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

## Links

