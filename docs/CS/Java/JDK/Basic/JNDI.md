## Introduction

The [Java Naming and Directory InterfaceTM (JNDI)](https://docs.oracle.com/javase/jndi/tutorial/getStarted/overview/index.html) is an application programming interface (API) that provides naming and directory functionality to applications written using the JavaTM programming language. It is defined to be independent of any specific directory service implementation. Thus a variety of directories--new, emerging, and already deployed--can be accessed in a common way.

The JNDI architecture consists of an API and a [service provider interface (SPI)](/docs//CS/Java/JDK/Basic/SPI.md). Java applications use the JNDI API to access a variety of naming and directory services. The SPI enables a variety of naming and directory services to be plugged in transparently, thereby allowing the Java application using the JNDI API to access their services. See the following figure.

To use the JNDI, you must have the JNDI classes and one or more service providers. The Java 2 SDK, v1.3 includes three service providers for the following naming/directory services:

- Lightweight Directory Access Protocol (LDAP)
- Common Object Request Broker Architecture (CORBA) Common Object Services (COS) name service
- Java Remote Method Invocation (RMI) Registry


Other service providers can be downloaded from the JNDI Web site or obtained from other vendors. 



## Links

- [JDK basics](/docs/CS/Java/JDK/Basic/Basic.md)