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


Registers an interest in any class that is annotated with ServerEndpoint so that Endpoint can be published via the WebSocket server.

```java
@HandlesTypes({ServerEndpoint.class, ServerApplicationConfig.class, Endpoint.class})
public class WsSci implements ServletContainerInitializer {

  @Override
  public void onStartup(Set<Class<?>> clazzes, ServletContext ctx)
          throws ServletException {

    WsServerContainer sc = init(ctx, true);

    // Group the discovered classes by type
    Set<ServerApplicationConfig> serverApplicationConfigs = new HashSet<>();
    Set<Class<? extends Endpoint>> scannedEndpointClazzes = new HashSet<>();
    Set<Class<?>> scannedPojoEndpoints = new HashSet<>();

    try {
      // wsPackage is "jakarta.websocket."
      String wsPackage = ContainerProvider.class.getName();
      wsPackage = wsPackage.substring(0, wsPackage.lastIndexOf('.') + 1);
      for (Class<?> clazz : clazzes) {
        int modifiers = clazz.getModifiers();
        if (!Modifier.isPublic(modifiers) ||
                Modifier.isAbstract(modifiers) ||
                Modifier.isInterface(modifiers) ||
                !isExported(clazz)) {
          // Non-public, abstract, interface or not in an exported
          // package - skip it.
          continue;
        }
        // Protect against scanning the WebSocket API JARs
        if (clazz.getName().startsWith(wsPackage)) {
          continue;
        }
        if (ServerApplicationConfig.class.isAssignableFrom(clazz)) {
          serverApplicationConfigs.add(
                  (ServerApplicationConfig) clazz.getConstructor().newInstance());
        }
        if (Endpoint.class.isAssignableFrom(clazz)) {
          @SuppressWarnings("unchecked")
          Class<? extends Endpoint> endpoint =
                  (Class<? extends Endpoint>) clazz;
          scannedEndpointClazzes.add(endpoint);
        }
        if (clazz.isAnnotationPresent(ServerEndpoint.class)) {
          scannedPojoEndpoints.add(clazz);
        }
      }
    } catch (ReflectiveOperationException e) {
      throw new ServletException(e);
    }

    // Filter the results
    Set<ServerEndpointConfig> filteredEndpointConfigs = new HashSet<>();
    Set<Class<?>> filteredPojoEndpoints = new HashSet<>();

    if (serverApplicationConfigs.isEmpty()) {
      filteredPojoEndpoints.addAll(scannedPojoEndpoints);
    } else {
      for (ServerApplicationConfig config : serverApplicationConfigs) {
        Set<ServerEndpointConfig> configFilteredEndpoints =
                config.getEndpointConfigs(scannedEndpointClazzes);
        if (configFilteredEndpoints != null) {
          filteredEndpointConfigs.addAll(configFilteredEndpoints);
        }
        Set<Class<?>> configFilteredPojos =
                config.getAnnotatedEndpointClasses(
                        scannedPojoEndpoints);
        if (configFilteredPojos != null) {
          filteredPojoEndpoints.addAll(configFilteredPojos);
        }
      }
    }

    try {
      // Deploy endpoints
      for (ServerEndpointConfig config : filteredEndpointConfigs) {
        sc.addEndpoint(config);
      }
      // Deploy POJOs
      for (Class<?> clazz : filteredPojoEndpoints) {
        sc.addEndpoint(clazz, true);
      }
    } catch (DeploymentException e) {
      throw new ServletException(e);
    }
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

- [Tomcat](/docs/CS/Java/Tomcat/Tomcat.md)
