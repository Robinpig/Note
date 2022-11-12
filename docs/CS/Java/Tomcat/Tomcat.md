## Introduction

[The Apache Tomcat® software](https://tomcat.apache.org/) is an open source implementation of the Jakarta [Servlet](/docs/CS/Java/Tomcat/Servlet.md), Jakarta Server Pages, Jakarta Expression Language, Jakarta WebSocket, Jakarta Annotations and Jakarta Authentication specifications. These specifications are part of the Jakarta EE platform.

> [Apache Tomcat Versions](https://tomcat.apache.org/whichversion.html)

Different versions of Apache Tomcat are available for different versions of the specifications. The mapping between the specifications and the respective Apache Tomcat versions is:


| **Servlet Spec** | **JSP Spec** | **EL Spec** | **WebSocket Spec** | **Authentication (JASPIC) Spec** | **Apache Tomcat Version** | **Latest Released Version** | **Supported Java Versions**                 |
| ------------------ | -------------- | ------------- | -------------------- | ---------------------------------- | --------------------------- | ----------------------------- | --------------------------------------------- |
| 6.0              | 3.1          | 5.0         | 2.1                | 3.0                              | 10.1.x                    | 10.1.1                      | 11 and later                                |
| 5.0              | 3.0          | 4.0         | 2.0                | 2.0                              | 10.0.x (superseded)       | 10.0.27 (superseded)        | 8 and later                                 |
| 4.0              | 2.3          | 3.0         | 1.1                | 1.1                              | 9.0.x                     | 9.0.68                      | 8 and later                                 |
| 3.1              | 2.3          | 3.0         | 1.1                | 1.1                              | 8.5.x                     | 8.5.83                      | 7 and later                                 |
| 3.1              | 2.3          | 3.0         | 1.1                | N/A                              | 8.0.x (superseded)        | 8.0.53 (superseded)         | 7 and later                                 |
| 3.0              | 2.2          | 2.2         | 1.1                | N/A                              | 7.0.x (archived)          | 7.0.109 (archived)          | 6 and later<br/>(7 and later for WebSocket) |
| 2.5              | 2.1          | 2.1         | N/A                | N/A                              | 6.0.x (archived)          | 6.0.53 (archived)           | 5 and later                                 |
| 2.4              | 2.0          | N/A         | N/A                | N/A                              | 5.5.x (archived)          | 5.5.36 (archived)           | 1.4 and later                               |
| 2.3              | 1.2          | N/A         | N/A                | N/A                              | 4.1.x (archived)          | 4.1.40 (archived)           | 1.3 and later                               |
| 2.2              | 1.1          | N/A         | N/A                | N/A                              | 3.3.x (archived)          | 3.3.2 (archived)            | 1.1 and later                               |

### Debug Tomcat

1. git clone git@github.com:apache/tomcat.git
2. add pom.xml

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">

  <modelVersion>4.0.0</modelVersion>

  <groupId>org.apache.tomcat</groupId>
  <artifactId>tomcat</artifactId>
  <name>tomcat</name>
  <version>10.1.1</version>

  <dependencies>
    <!-- https://mvnrepository.com/artifact/biz.aQute.bnd/biz.aQute.bndlib -->
    <dependency>
      <groupId>biz.aQute.bnd</groupId>
      <artifactId>biz.aQute.bndlib</artifactId>
      <version>6.3.1</version>
    </dependency>

    <!-- https://mvnrepository.com/artifact/org.apache.tomcat/jakartaee-migration -->
    <dependency>
      <groupId>org.apache.tomcat</groupId>
      <artifactId>jakartaee-migration</artifactId>
      <version>1.0.5</version>
    </dependency>


    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>4.13.2</version>
      <scope>test</scope>
    </dependency>

    <dependency>
      <groupId>org.apache.ant</groupId>
      <artifactId>ant</artifactId>
      <version>1.10.11</version>
    </dependency>
    <dependency>
      <groupId>wsdl4j</groupId>
      <artifactId>wsdl4j</artifactId>
      <version>1.6.3</version>
    </dependency>

    <dependency>
      <groupId>org.apache.geronimo.specs</groupId>
      <artifactId>geronimo-jaxrpc_1.1_spec</artifactId>
      <version>2.1</version>
    </dependency>

    <dependency>
      <groupId>org.eclipse.jdt</groupId>
      <artifactId>ecj</artifactId>
      <version>3.31.0</version>
    </dependency>


    <dependency>
      <groupId>org.easymock</groupId>
      <artifactId>easymock</artifactId>
      <version>5.0.1</version>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration>
          <source>11</source>
          <target>11</target>
          <encoding>UTF-8</encoding>
        </configuration>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-resources-plugin</artifactId>
        <configuration>
          <encoding>UTF-8</encoding>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
```

3. set Project Structure
4. add JasperInitializer in ContextConfig#configureStart

```java
context.addServletContainerInitializer(new JasperInitializer(), null);
```

5. change password in conf/tomcat-users.xml

## Architecture

![Lifecycle](./images/Lifecycle.png)

Catalina is a very sophisticated piece of software, which was elegantly designed and developed. It is also modular too.
Catalina is consisting of two main modules: the [connector](/docs/CS/Java/Tomcat/Connector.md) and the container.。

```plantuml
@startuml

!theme plain
top to bottom direction
skinparam linetype ortho

class Connector
interface Container << interface >>

@enduml

```

- [start](/docs/CS/Java/Tomcat/Start.md)
- [ClassLoader](/docs/CS/Java/Tomcat/ClassLoader.md)

```dot

strict digraph  {
rankdir=LR;
autosize=false;
 size="30.0, 38.3";

  User -> SocketWrapper;
 
  Acceptor -> Poller 
  Poller -> Executor 
  Processor;
  Executor -> Processor 
  
  Engine_Valve -> Host_Valve;
  Host_Valve -> Context_Valve;
  Context_Valve -> Wrapper_Valve_1;
  Context_Valve -> Wrapper_Valve_2;
  Context_Valve -> Wrapper_Valve_3;
  
   SocketWrapper -> Acceptor;
   SocketWrapper -> User;
  
    subgraph cluster_Server {
        label="Server"
 
  
    subgraph cluster_Service {
        label="Serice"
        subgraph cluster_Connector {
            label="Connector"
            subgraph cluster_ProtocolHandler {
                label="ProtocolHandler"
  
                    subgraph cluster_Endpoint {
                        label="Endpoint"
                        forcelabels= true
  
                        SocketWrapper;
                        Poller;
                        Acceptor;
                        Executor [label=<Executor<BR/> <FONT POINT-SIZE="12">A Thread Pool</FONT>>] ;
                        {rank="same"; SocketWrapper;Acceptor;Poller;Executor;}
                        LimitLatch;
                    }
                Processor;
  
                }
            Adapter;
            Processor -> Adapter;
            Adapter -> Mapper;
            Adapter -> Processor;
            
            Processor -> SocketWrapper;
    
        }

        subgraph cluster_Engine {
            label="Engine"
            Engine_Valve [label="Valve"];
             Adapter -> Engine_Valve;
             Adapter -> cc;
             subgraph cluster_Host {
                label="Host"
                Host_Valve [label="Valve"];
                subgraph cluster_Context {
                    label="Context"
                    autosize=false;
                    size="10.0, 18.3";
 
                    Context_Valve [label="Valve"];
    
                    subgraph cluster_Wrapper_1 {
                        label="Wrapper"
                        Wrapper_Valve_1 [label="Valve"];
                        Servlet_1[label="JspServlet"];
                
                        Wrapper_Valve_1 -> Servlet_1 [headlabel="FilterChain" constraint=false];
                    }
                    subgraph cluster_Wrapper_2 {
                        label="Wrapper"
                        Wrapper_Valve_2 [label="Valve"];
                        Servlet_2[label="DefaultServlet"];
                
                        Wrapper_Valve_2 -> Servlet_2 [headlabel="FilterChain" constraint=false];
                    }
                    subgraph cluster_Wrapper_3 {
                        label="Wrapper"
                        Wrapper_Valve_3 [label="Valve"];
                        Servlet_3[label="HttpServlet"];
  
                        Wrapper_Valve_3 -> Servlet_3 [headlabel="FilterChain" constraint=false];
                    }
                }
    
            }
        }
    }
}
}

```

### Container

A container must implement `org.apache.catalina.Container`.

The first thing to note about containers in Catalina is that there are four types of containers at different conceptual levels:

- Engine. Represents the entire Catalina servlet engine.
- Host. Represents a virtual host with a number of contexts.
- Context. Represents a web application. A context contains one or more wrappers.
- Wrapper. Represents an individual servlet.

Each conceptual level above is represented by an interface in the org.apache.catalina package.
These interfaces are Engine, Host, Context, and Wrapper. All the four extends the Container interface.
Standard implementations of the four containers are StandardEngine, StandardHost, StandardContext, and StandardWrapper, respectively, all of which are part of the org.apache.catalina.core package.

```plantuml
@startuml

!theme plain
top to bottom direction
skinparam linetype ortho

interface Container << interface >>
class ContainerBase
interface Context << interface >>
interface Engine << interface >>
interface Host << interface >>
interface Lifecycle << interface >>
class StandardContext
class StandardEngine
class StandardHost
class StandardWrapper
interface Wrapper << interface >>

Container        -[#008200,plain]-^  Lifecycle   
ContainerBase    -[#008200,dashed]-^  Container   
ContainerBase    -[#008200,dashed]-^  Lifecycle   
Context          -[#008200,plain]-^  Container   
Engine           -[#008200,plain]-^  Container   
Host             -[#008200,plain]-^  Container   
StandardContext  -[#000082,plain]-^  ContainerBase   
StandardContext  -[#008200,dashed]-^  Context   
StandardEngine   -[#000082,plain]-^  ContainerBase   
StandardEngine   -[#008200,dashed]-^  Engine    
StandardHost     -[#000082,plain]-^  ContainerBase   
StandardHost     -[#008200,dashed]-^  Host      
StandardWrapper  -[#000082,plain]-^  ContainerBase   
StandardWrapper  -[#008200,dashed]-^  Wrapper   
Wrapper          -[#008200,plain]-^  Container   
@enduml

```

Note All implementation classes derive from the abstract class ContainerBase.

A container can have zero or more child containers of the lower level.
For instance, a context normally has one or more wrappers and a host can have zero or more contexts.
However, a wrapper, being the lowest in the 'hierarchy', cannot contain a child container.
To add a child container to a container, you use the Container interface's addChild method whose signature is as follows.

```java
public interface Container extends Lifecycle {
    void addChild(Container child);

    void removeChild(Container child);

    Container findChild(String name);

    Container[] findChildren();
}
```

A container can also contain a number of support components such as Loader, Logger, Manager, Realm, and Resources.
One thing worth noting here is that the Container interface provides the get and set methods for associating itself with those components.
These methods include getLoader and setLoader, getLogger and setLogger, getManager and
setManager, getRealm and setRealm, and getResources and setResources.
More interestingly, the Container interface has been designed in such a way that at the time of deployment a Tomcat administrator can determine what a container performs by editing the configuration file (server.xml).
This is achieved by introducing a pipeline and a set of valves in a container.


#### Engine

An Engine is a Container that represents the entire Catalina servlet engine. It is useful in the following types of scenarios:

- You wish to use Interceptors that see every single request processed by the entire engine.
- You wish to run Catalina in with a standalone HTTP connector, but still want support for multiple virtual hosts.

In general, you would not use an Engine when deploying Catalina connected to a web server (such as Apache), because the Connector will have utilized the web server's facilities to determine which Context (or perhaps even which Wrapper) should be utilized to process this request.
The child containers attached to an Engine are generally implementations of Host (representing a virtual host) or Context (representing individual an individual servlet context), depending upon the Engine implementation.
If used, an Engine is always the top level Container in a Catalina hierarchy. Therefore, the implementation's setParent() method should throw IllegalArgumentException.

#### Context

A Context is a Container that represents a servlet context, and therefore an individual web application, in the Catalina servlet engine.
It is therefore useful in almost every deployment of Catalina (even if a Connector attached to a web server (such as Apache) uses the web server's facilities to identify the appropriate Wrapper to handle this request.
It also provides a convenient mechanism to use Interceptors that see every request processed by this particular web application.
**The parent Container attached to a Context is generally a Host, but may be some other implementation, or may be omitted if it is not necessary.**
The child containers attached to a Context are generally implementations of Wrapper (representing individual servlet definitions).

### Server and Service

A Server element represents the entire Catalina servlet container. Its attributes represent the characteristics of the servlet container as a whole. 
A Server may contain one or more Services, and the top level set of naming resources.
Normally, an implementation of this interface will also implement Lifecycle, such that when the start() and stop() methods are called, all of the defined Services are also started or stopped.
In between, the implementation must open a server socket on the port number specified by the port property. When a connection is accepted, the first line is read and compared with the specified shutdown command. 
If the command matches, shutdown of the server is initiated.

- JreMemoryLeakPreventionListener Provide a workaround for known places where the Java Runtime environment can cause a memory leak or lock files.
  Memory leaks occur when JRE code uses the context class loader to load a singleton as this will cause a memory leak if a web application class loader happens to be the context class loader at the time. The work-around is to initialise these singletons when Tomcat's common class loader is the context class loader.
  Locked files usually occur when a resource inside a JAR is accessed without first disabling Jar URL connection caching. The workaround is to disable this caching by default.
- ThreadLocalLeakPreventionListener A LifecycleListener that triggers the renewal of threads in Executor pools when a Context is being stopped to avoid thread-local related memory leaks.
  Note : active threads will be renewed one by one when they come back to the pool after executing their task, see ThreadPoolExecutor.afterExecute().



A service component encapsulates a container and one or many connectors.

The org.apache.catalina.core.StandardService class is the standard implementation of Service.
The StandardService class's initialize method initializes all the connectors added to the service.
StandardService implements Service as well as the org.apache.catalina.Lifecycle interface.
Its start method starts the container and all the connectors.

A StandardService instance contains two types of components: a container and one or more connectors.
Being able to have multiple connectors enable Tomcat to service multiple protocols.
One connector can be used to service HTTP requests, and another for servicing HTTPS requests.

Standard implementation of the Service interface. The associated Container is generally an instance of Engine, but this is not required.

```java
public class StandardService extends LifecycleMBeanBase implements Service {

    protected Connector connectors[] = new Connector[0];

    private Engine engine = null;
}
```
### Pipeline

A pipeline contains tasks that the container will invoke.
A valve represents a specific task.
There is one basic valve in a container's pipeline, but you can add as many valves as you want.
The number of valves is defined to be the number of additional valves, i.e. not including the basic valve.
Interestingly, valves can be added dynamically by editing Tomcat's configuration file (server.xml).

If you understand servlet filters, it is not hard to imagine how a pipeline and its valve work.
A pipeline is like a filter chain and each valve is a filter. Like a filter, a valve can manipulate the request and response objects passed to it.
After a valve finishes processing, it calls the next valve in the pipeline. The basic valve is always called the last.

A container can have one pipeline.
When a container's invoke method is called, the container passes processing to its pipeline and the pipeline invokes the first valve in it, which will then invoke the next valve, and so on, until there is no more valve in the pipeline.

A container does not hard code what it is supposed to do when its invoke method is called by the connector.
Instead, the container calls its pipeline's invoke method.

```java
public interface Valve {
    void invoke(Request request, Response response) throws IOException, ServletException;
}
```

A Valve is a request processing component associated with a particular Container.
A series of Valves are generally associated with each other into a Pipeline.
The detailed contract for a Valve is included in the description of the invoke() method below.
HISTORICAL NOTE: The "Valve" name was assigned to this concept because a valve is what you use in a real world pipeline to control and/or modify flows through it.

```java
public class CoyoteAdapter implements Adapter {
    @Override
    public boolean asyncDispatch(org.apache.coyote.Request req, org.apache.coyote.Response res, SocketEvent status) throws Exception {
        // ...
        connector.getService().getContainer().getPipeline().getFirst().invoke(request, response);
        // ...
    }
}
```

#### Wrapper

A Wrapper is a Container that represents an individual servlet definition from the deployment descriptor of the web application.
It provides a convenient mechanism to use Interceptors that see every single request to the servlet represented by this definition.
Implementations of Wrapper are responsible for managing the servlet life cycle for their underlying servlet class, including calling init() and destroy() at appropriate times.
The parent Container attached to a Wrapper will generally be an implementation of Context, representing the servlet context (and therefore the web application) within which this servlet executes.
Since a wrapper is the lowest level of container, you must not add a child to it.
Child Containers are not allowed on Wrapper implementations, so the addChild() method should throw an IllegalArgumentException.

## reload

Private runnable class to invoke the backgroundProcess method of this container and its children after a fixed delay.

```java
protected class ContainerBackgroundProcessor implements Runnable {

    @Override
    public void run() {
        processChildren(ContainerBase.this);
    }

    protected void processChildren(Container container) {
        ClassLoader originalClassLoader = null;

        try {
            if (container instanceof Context) {
                Loader loader = ((Context) container).getLoader();
                // Loader will be null for FailedContext instances
                if (loader == null) {
                    return;
                }

                // Ensure background processing for Contexts and Wrappers is performed under the web app's class loader
                originalClassLoader = ((Context) container).bind(false, null);
            }
            container.backgroundProcess();
            Container[] children = container.findChildren();
            for (int i = 0; i < children.length; i++) {
                if (children[i].getBackgroundProcessorDelay() <= 0) {
                    processChildren(children[i]);
                }
            }
        } catch (Throwable t) {
            ExceptionUtils.handleThrowable(t);
            log.error(sm.getString("containerBase.backgroundProcess.error"), t);
        } finally {
            if (container instanceof Context) {
                ((Context) container).unbind(false, originalClassLoader);
            }
        }
    }
}
```

backgroundProcess

```java
public class StandardContext extends ContainerBase implements Context, NotificationEmitter {
    @Override
    public void backgroundProcess() {
        Loader loader = getLoader();
        if (loader != null) {
            loader.backgroundProcess();
        }
        // ...
    }
}
```
Execute a periodic task, such as reloading, etc. This method will be invoked inside the classloading context of this container. Unexpected throwables will be caught and logged.

```java
public class WebappLoader extends LifecycleMBeanBase implements Loader {
    @Override
    public void backgroundProcess() {
        Context context = getContext();
        if (context != null) {
            if (context.getReloadable() && modified()) {
                ClassLoader originalTccl = Thread.currentThread().getContextClassLoader();
                try {
                    Thread.currentThread().setContextClassLoader(WebappLoader.class.getClassLoader());
                    context.reload();
                } finally {
                    Thread.currentThread().setContextClassLoader(originalTccl);
                }
            }
        }
    }
}
```
### StandardContext#reload
Reload this web application, if reloading is supported.
**This method is designed to deal with reloads required by changes to classes in the underlying repositories of our class loader and changes to the web.xml file.** 
It does not handle changes to any context.xml file. 
If the context.xml has changed, you should stop this Context and create (and start) a new Context instance instead. 
Note that there is additional code in CoyoteAdapter#postParseRequest() to handle mapping requests to paused Contexts.

```java
public class StandardContext extends ContainerBase implements Context, NotificationEmitter {
  @Override
    public synchronized void reload() {

    // Validate our current component state

    // Stop accepting requests temporarily.
    setPaused(true);

    stop();

    start();

    setPaused(false);
  }
}
```

## Upgrade

Comet

Websocket
