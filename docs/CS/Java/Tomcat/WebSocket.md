## Introduction



Interface between the HTTP upgrade process and the new protocol.
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

WebConnection used by an HttpUpgradeHandler to interact with an upgraded HTTP connection.



public abstract class UpgradeProcessorBase extends AbstractProcessorLight implements WebConnection