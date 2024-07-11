## Introduction

Nacos `/nɑ:kəʊs/` 是 Dynamic Naming and Configuration Service的首字母简称，一个更易于构建云原生应用的动态服务发现、配置管理和服务管理平台

服务（Service）是 Nacos 世界的一等公民。Nacos 支持几乎所有主流类型的“服务”的发现、配置和管理

Nacos 的关键特性包括:

- **Service Discovery And Service Health Check**
  Nacos supports both DNS-based and RPC-based (Dubbo/gRPC) [service discovery](/docs/CS/Java/Spring_Cloud/nacos/registry.md). 
  After a service provider registers a service with native, OpenAPI, or a dedicated agent, a consumer can discover the service with either DNS or HTTP.
  Nacos provides real-time health check to prevent services from sending requests to unhealthy hosts or service instances. 
  Nacos supports both transport layer (PING or TCP) health check and application layer (such as HTTP, Redis, MySQL, and user-defined protocol) health check. 
  For the health check of complex clouds and network topologies(such as VPC, Edge Service etc), Nacos provides both agent mode and server mode health check. 
  Nacos also provide a unity service health dashboard to help you manage the availability and traffic of services.
- **Dynamic configuration management**
  [Dynamic configuration](/docs/CS/Java/Spring_Cloud/nacos/config.md) service allows you to manage the configuration of all applications and services in a centralized, externalized and dynamic manner across all environments.
  Dynamic configuration eliminates the need to redeploy applications and services when configurations are updated.
  Centralized management of configuration makes it more convenient for you to achieve stateless services and elastic expansion of service instances on-demand.
  Nacos provides an easy-to-use UI (DEMO) to help you manage all of your application or services's configurations. 
  It provides some out-of-box features including configuration version tracking, canary/beta release, configuration rollback, and client configuration update status tracking to ensure the safety and control the risk of configuration change.

- **Dynamic DNS service**
  Dynamic DNS service which supports weighted routing makes it easier for you to implement mid-tier load balancing, flexible routing policies, traffic control, and simple DNS resolution services in your production environment within your data center. 
  Dynamic DNS service makes it easier for you to implement DNS-based Service discovery.
  Nacos provides some simple DNS APIs TODO for you to manage your DNS domain names and IPs.
- **Service governance and metadata management**
  Nacos allows you to manage all of your services and metadata from the perspective of a microservices platform builder. 
  This includes managing service description, life cycle, service static dependencies analysis, service health status, service traffic management，routing and security rules, service SLA, and first line metrics.



## Architecture

![](./img/Architecture.png)

采⽤了阿⾥巴巴内部⾃研的 Distro 协议来实现数据弱⼀致性同步。其中
所有节点都将存储集群内所有服务元数据，因此都可以提供数据读取服务，但每个节点只负责
⼀部分客户端的数据写服务



## Service Registry

```java
public interface NamingClientProxy extends Closeable {
  void registerService(String serviceName, String groupName, Instance instance) throws NacosException;
    
}

public class NamingClientProxyDelegate implements NamingClientProxy {
    private NamingClientProxy getExecuteClientProxy(Instance instance) {
        if (instance.isEphemeral() || grpcClientProxy.isAbilitySupportedByServer(AbilityKey.SERVER_SUPPORT_PERSISTENT_INSTANCE_BY_GRPC)) {
            return grpcClientProxy;
        }
        return httpClientProxy;
    }
}
```



grpc



```java
@Override
    public void registerService(String serviceName, String groupName, Instance instance) throws NacosException {
        NAMING_LOGGER.info("[REGISTER-SERVICE] {} registering service {} with instance {}", namespaceId, serviceName,
                instance);
        if (instance.isEphemeral()) {
            registerServiceForEphemeral(serviceName, groupName, instance);
        } else {
            doRegisterServiceForPersistent(serviceName, groupName, instance);
        }
    }

```
Ephemeral
```java
private void registerServiceForEphemeral(String serviceName, String groupName, Instance instance)
            throws NacosException {
        redoService.cacheInstanceForRedo(serviceName, groupName, instance);
        doRegisterService(serviceName, groupName, instance);
    }
    
public void doRegisterService(String serviceName, String groupName, Instance instance) throws NacosException {
        InstanceRequest request = new InstanceRequest(namespaceId, serviceName, groupName,
                NamingRemoteConstants.REGISTER_INSTANCE, instance);
        requestToServer(request, Response.class);
  			// Instance register successfully, mark registered status as true.
        redoService.instanceRegistered(serviceName, groupName);
    }
```
Persistent

```java
public void doRegisterServiceForPersistent(String serviceName, String groupName, Instance instance)
            throws NacosException {
        PersistentInstanceRequest request = new PersistentInstanceRequest(namespaceId, serviceName, groupName,
                NamingRemoteConstants.REGISTER_INSTANCE, instance);
        requestToServer(request, Response.class);
    }


 private <T extends Response> T requestToServer(AbstractNamingRequest request, Class<T> responseClass)
            throws NacosException {
        Response response = null;
        try {
            request.putAllHeader(
                    getSecurityHeaders(request.getNamespace(), request.getGroupName(), request.getServiceName()));
            response = requestTimeout < 0 ? rpcClient.request(request) : rpcClient.request(request, requestTimeout);
            if (ResponseCode.SUCCESS.getCode() != response.getResultCode()) {
                throw new NacosException(response.getErrorCode(), response.getMessage());
            }
            if (responseClass.isAssignableFrom(response.getClass())) {
                return (T) response;
            }
            NAMING_LOGGER.error("Server return unexpected response '{}', expected response should be '{}'",
                    response.getClass().getName(), responseClass.getName());
            throw new NacosException(NacosException.SERVER_ERROR, "Server return invalid response");
        } catch (NacosException e) {
            recordRequestFailedMetrics(request, e, response);
            throw e;
        } catch (Exception e) {
            recordRequestFailedMetrics(request, e, response);
            throw new NacosException(NacosException.SERVER_ERROR, "Request nacos server failed: ", e);
        }
    }
```



RPC client

```java
public final void start() throws NacosException {
        
        boolean success = rpcClientStatus.compareAndSet(RpcClientStatus.INITIALIZED, RpcClientStatus.STARTING);
        if (!success) {
            return;
        }
        
        clientEventExecutor = new ScheduledThreadPoolExecutor(2,
                new NameThreadFactory("com.alibaba.nacos.client.remote.worker"));
        
        // connection event consumer.
        clientEventExecutor.submit(() -> {
            while (!clientEventExecutor.isTerminated() && !clientEventExecutor.isShutdown()) {
                ConnectionEvent take;
                try {
                    take = eventLinkedBlockingQueue.take();
                    if (take.isConnected()) {
                        notifyConnected(take.connection);
                    } else if (take.isDisConnected()) {
                        notifyDisConnected(take.connection);
                    }
                } catch (Throwable e) {
                    // Do nothing
                }
            }
        });
        
        clientEventExecutor.submit(() -> {
            while (true) {
                try {
                    if (isShutdown()) {
                        break;
                    }
                    ReconnectContext reconnectContext = reconnectionSignal
                            .poll(rpcClientConfig.connectionKeepAlive(), TimeUnit.MILLISECONDS);
                    if (reconnectContext == null) {
                        // check alive time.
                        if (System.currentTimeMillis() - lastActiveTimeStamp >= rpcClientConfig.connectionKeepAlive()) {
                            boolean isHealthy = healthCheck();
                            if (!isHealthy) {
                                if (currentConnection == null) {
                                    continue;
                                }
                                LoggerUtils.printIfInfoEnabled(LOGGER,
                                        "[{}] Server healthy check fail, currentConnection = {}",
                                        rpcClientConfig.name(), currentConnection.getConnectionId());
                                
                                RpcClientStatus rpcClientStatus = RpcClient.this.rpcClientStatus.get();
                                if (RpcClientStatus.SHUTDOWN.equals(rpcClientStatus)) {
                                    break;
                                }
                                
                                boolean statusFLowSuccess = RpcClient.this.rpcClientStatus
                                        .compareAndSet(rpcClientStatus, RpcClientStatus.UNHEALTHY);
                                if (statusFLowSuccess) {
                                    reconnectContext = new ReconnectContext(null, false);
                                } else {
                                    continue;
                                }
                                
                            } else {
                                lastActiveTimeStamp = System.currentTimeMillis();
                                continue;
                            }
                        } else {
                            continue;
                        }
                        
                    }
                    
                    if (reconnectContext.serverInfo != null) {
                        // clear recommend server if server is not in server list.
                        boolean serverExist = false;
                        for (String server : getServerListFactory().getServerList()) {
                            ServerInfo serverInfo = resolveServerInfo(server);
                            if (serverInfo.getServerIp().equals(reconnectContext.serverInfo.getServerIp())) {
                                serverExist = true;
                                reconnectContext.serverInfo.serverPort = serverInfo.serverPort;
                                break;
                            }
                        }
                        if (!serverExist) {
                            LoggerUtils.printIfInfoEnabled(LOGGER,
                                    "[{}] Recommend server is not in server list, ignore recommend server {}",
                                    rpcClientConfig.name(), reconnectContext.serverInfo.getAddress());
                            
                            reconnectContext.serverInfo = null;
                            
                        }
                    }
                    reconnect(reconnectContext.serverInfo, reconnectContext.onRequestFail);
                } catch (Throwable throwable) {
                    // Do nothing
                }
            }
        });
        
        // connect to server, try to connect to server sync retryTimes times, async starting if failed.
        Connection connectToServer = null;
        rpcClientStatus.set(RpcClientStatus.STARTING);
        
        int startUpRetryTimes = rpcClientConfig.retryTimes();
        while (startUpRetryTimes >= 0 && connectToServer == null) {
            try {
                startUpRetryTimes--;
                ServerInfo serverInfo = nextRpcServer();
                
                LoggerUtils.printIfInfoEnabled(LOGGER, "[{}] Try to connect to server on start up, server: {}",
                        rpcClientConfig.name(), serverInfo);
                
                connectToServer = connectToServer(serverInfo);
            } catch (Throwable e) {
                LoggerUtils.printIfWarnEnabled(LOGGER,
                        "[{}] Fail to connect to server on start up, error message = {}, start up retry times left: {}",
                        rpcClientConfig.name(), e.getMessage(), startUpRetryTimes, e);
            }
            
        }
        
        if (connectToServer != null) {
            LoggerUtils
                    .printIfInfoEnabled(LOGGER, "[{}] Success to connect to server [{}] on start up, connectionId = {}",
                            rpcClientConfig.name(), connectToServer.serverInfo.getAddress(),
                            connectToServer.getConnectionId());
            this.currentConnection = connectToServer;
            rpcClientStatus.set(RpcClientStatus.RUNNING);
            eventLinkedBlockingQueue.offer(new ConnectionEvent(ConnectionEvent.CONNECTED, currentConnection));
        } else {
            switchServerAsync();
        }
        
        registerServerRequestHandler(new ConnectResetRequestHandler());
        
        // register client detection request.
        registerServerRequestHandler((request, connection) -> {
            if (request instanceof ClientDetectionRequest) {
                return new ClientDetectionResponse();
            }
            
            return null;
        });
        
    }
    
```





Abstract Connection

```java
public abstract class Connection implements Requester {
}
```



HTTP





## Config






## Links

- [Spring Cloud](/docs/CS/Java/Spring_Cloud/Spring_Cloud.md)

## References
1. [Quick Start for Nacos Spring Boot Projects](https://nacos.io/en-us/docs/quick-start-spring-boot.html)