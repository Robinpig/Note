## Introduction

HTTP 升级过程与新协议之间的接口。

```java
public interface HttpUpgradeHandler {

    /**
     * This method is called once the request/response pair where
     * HttpServletRequest#upgrade(Class) is called has completed
     * processing and is the point where control of the connection passes from
     * the container to the HttpUpgradeHandler.
     */
    void init(WebConnection connection);

    /** This method is called after the upgraded connection has been closed. */
    void destroy();
}
```

WebConnection 供 HttpUpgradeHandler 使用，用于与升级后的 HTTP 连接进行交互。

```java
public abstract class UpgradeProcessorBase extends AbstractProcessorLight implements WebConnection
```

注册对任何标注了 ServerEndpoint 的类的兴趣，以便 Endpoint 可以通过 WebSocket 服务器发布。

```java
@HandlesTypes({ServerEndpoint.class, ServerApplicationConfig.class, Endpoint.class})
public class WsSci implements ServletContainerInitializer {

  @Override
  public void onStartup(Set<Class<?>> clazzes, ServletContext ctx)
          throws ServletException {
    // ...
  }
}
```

WsFilter

```java
public class UpgradeProcessorInternal extends UpgradeProcessorBase {
  
  private final InternalHttpUpgradeHandler internalHttpUpgradeHandler;

  public UpgradeProcessorInternal(SocketWrapperBase<?> wrapper, UpgradeToken upgradeToken,
                                  UpgradeGroupInfo upgradeGroupInfo) {
    super(upgradeToken);
    this.internalHttpUpgradeHandler = (InternalHttpUpgradeHandler) upgradeToken.getHttpUpgradeHandler();
    /*
     * Leave timeouts in the hands of the upgraded protocol.
     */
    wrapper.setReadTimeout(INFINITE_TIMEOUT);
    wrapper.setWriteTimeout(INFINITE_TIMEOUT);

    internalHttpUpgradeHandler.setSocketWrapper(wrapper);

    // HTTP/2 uses RequestInfo objects so does not provide upgradeInfo
    UpgradeInfo upgradeInfo = internalHttpUpgradeHandler.getUpgradeInfo();
    if (upgradeInfo != null && upgradeGroupInfo != null) {
      upgradeInfo.setGroupInfo(upgradeGroupInfo);
    }
  }
}
```

## Links

- [Tomcat](/docs/CS/Framework/Tomcat/Tomcat.md)
