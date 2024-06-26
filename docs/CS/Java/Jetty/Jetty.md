## Introduction



Connectors, handlers and a global thread pool.


SelectorManager
ManagedSelector


ByteBufPool re-usable objects , ConcurrentLinkedDeque

## Architecture



<div style="text-align: center;">

![](./img/Architecture.png)

</div>

<p style="text-align: center;">
Fig.1. Tomcat architecture
</p>

Jetty Server 可以有多个 Connector 在不同的端口上监听客户请求，而对于请求处理的
Handler 组件，也可以根据具体场景使用不同的 Handler。这样的设计提高了 Jetty 的灵
活性，需要支持 Servlet，则可以使用 ServletHandler；需要支持 Session，则再增加一个
SessionHandler。也就是说我们可以不使用 Servlet 或者 Session，只要不配置这个
Handler 就行了。

为了启动和协调上面的核心组件工作，Jetty 提供了一个 Server 类来做这个事情，它负责
创建并初始化 Connector、Handler、ThreadPool 组件，然后调用 start 方法启动它们


## Connector

### Acceptor

The connector will execute a number of acceptor tasks to the Exception service passed to the constructor. 
The acceptor tasks run in a loop while the connector is running and repeatedly call the abstract accept(int) method. 
The implementation of the accept method must:
- block waiting for new connections
- accept the connection (eg socket accept)
- perform any configuration of the connection (eg. socket configuration)
- call the getDefaultConnectionFactory() ConnectionFactory.newConnection(Connector, EndPoint) method to create a new Connection instance.

The default number of acceptor tasks is the minimum of 1 and the number of available CPUs divided by 8. 
Having more acceptors may reduce the latency for servers that see a high rate of new connections (eg HTTP/1.0 without keep-alive). 
Typically the default is sufficient for modern persistent protocols (HTTP/1.1, HTTP/2 etc.)

```java
public abstract class AbstractConnector extends ContainerLifeCycle implements Connector, Dumpable
{
  private final Thread[] _acceptors;

    @Override
    protected void doStart() throws Exception
    { 
        // ...
        super.doStart();

        for (int i = 0; i < _acceptors.length; i++)
        {
            Acceptor a = new Acceptor(i);
            addBean(a);
            getExecutor().execute(a);
        }
 
    }
}
 ```   

处理请求流程

1.Acceptor 监听连接请求，当有连接请求到达时就接受连接，一个连接对应一个
Channel，Acceptor 将 Channel 交给 ManagedSelector 来处理。
2.ManagedSelector 把 Channel 注册到 Selector 上，并创建一个 EndPoint 和
Connection 跟这个 Channel 绑定，接着就不断地检测 I/O 事件。
3.I/O 事件到了就调用 EndPoint 的方法拿到一个 Runnable，并扔给线程池执行。
4. 线程池中调度某个线程执行 Runnable。
5.Runnable 执行时，调用回调函数，这个回调函数是 Connection 注册到 EndPoint 中
的。
6. 回调函数内部实现，其实就是调用 EndPoint 的接口方法来读数据。
7.Connection 解析读到的数据，生成请求对象并交给 Handler 组件去处理

## Handler

A Jetty component that handles HTTP requests, of any version (HTTP/1.1, HTTP/2 or HTTP/3). A Handler is a Request.Handler with the addition of LifeCycle behaviours, plus variants that allow organizing Handlers as a tree structure.

Handlers may wrap the Request, Response and/or Callback and then forward the wrapped instances to their children, so that they see a modified request; and/or to intercept the read of the request content; and/or intercept the generation of the response; and/or to intercept the completion of the callback.

A Handler is an Invocable and implementations must respect the Invocable.InvocationType they declare within calls to handle(Request, Response, Callback).

Handler实现了 Servlet 规范中的 Servlet、Filter 和 Listener 功能中的一个或者多个




## Lifecycle

```java

WebAppContext webapp = new WebAppContext();
webapp.setContextPath("/mywebapp");
webapp.setWar("mywebapp.war");

server.setHandler(webapp);

server.start();
server.join()

```

## Comparison with Tomcat


相同点:

设计组件化 支持配置 模板模式

生命周期管理 实现一键式启停 状态流转与监听器模式

组件间调用

流程处理 责任链模式








Jetty没有Service的概念


Tomcat可以对Connector配置不同的线程池

Jetty的Connector都是公用全局线程池

Jetty Connector 设计中的一大特点是，使用了回调函数来模拟异步 I/O，比如
Connection 向 EndPoint 注册了一堆回调函数。它的本质将函数当作一个参数来传递


Jetty的Selector和processor默认是同一个线程处理 类似Netty

Tomcat是分离的 使用Poller单独做Selector

## Links

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)