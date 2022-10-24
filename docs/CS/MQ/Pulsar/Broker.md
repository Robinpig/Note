## Introduction

```java
public class PulsarBrokerStarter {
    public static void main(String[] args) throws Exception {
        DateFormat dateFormat = new SimpleDateFormat(
                FixedDateFormat.FixedFormat.ISO8601_OFFSET_DATE_TIME_HHMM.getPattern());
        Thread.setDefaultUncaughtExceptionHandler((thread, exception) -> {
            System.out.println(String.format("%s [%s] error Uncaught exception in thread %s: %s",
                    dateFormat.format(new Date()), thread.getContextClassLoader(),
                    thread.getName(), exception.getMessage()));
            exception.printStackTrace(System.out);
        });

        BrokerStarter starter = new BrokerStarter(args);
        Runtime.getRuntime().addShutdownHook(
                new Thread(() -> {
                    try {
                        starter.shutdown();
                    } catch (Throwable t) {
                        log.error("Error while shutting down Pulsar service", t);
                    }
                }, "pulsar-service-shutdown")
        );

        PulsarByteBufAllocator.registerOOMListener(oomException -> {
            if (starter.brokerConfig.isSkipBrokerShutdownOnOOM()) {
                log.error("-- Received OOM exception: {}", oomException.getMessage(), oomException);
            } else {
                log.error("-- Shutting down - Received OOM exception: {}", oomException.getMessage(), oomException);
                starter.pulsarService.shutdownNow();
            }
        });

        try {
            starter.start();
        } catch (Throwable t) {
            log.error("Failed to start pulsar service.", t);
            LogManager.shutdown();
            Runtime.getRuntime().halt(1);
        } finally {
            starter.join();
        }
    }
}
```

start

```java
    private static class BrokerStarter {
    public void start() throws Exception {
        if (bookieStatsProvider != null) {
            bookieStatsProvider.start(bookieConfig);
        }
        if (bookieServer != null) {
            bookieServer.start();
        }
        if (autoRecoveryMain != null) {
            autoRecoveryMain.start();
        }

        pulsarService.start();
    }
}
```

PulsarService

```java
public class PulsarService implements AutoCloseable, ShutdownService {
    public void start() throws PulsarServerException {
        LOG.info("Starting Pulsar Broker service; version: '{}'",
                (brokerVersion != null ? brokerVersion : "unknown"));
        LOG.info("Git Revision {}", PulsarVersion.getGitSha());
        LOG.info("Git Branch {}", PulsarVersion.getGitBranch());
        LOG.info("Built by {} on {} at {}",
                PulsarVersion.getBuildUser(),
                PulsarVersion.getBuildHost(),
                PulsarVersion.getBuildTime());

        long startTimestamp = System.currentTimeMillis();  // start time mills

        mutex.lock();
        try {
            if (state != State.Init) {
                throw new PulsarServerException("Cannot start the service once it was stopped");
            }

            if (!config.getWebServicePort().isPresent() && !config.getWebServicePortTls().isPresent()) {
                throw new IllegalArgumentException("webServicePort/webServicePortTls must be present");
            }

            if (config.isAuthorizationEnabled() && !config.isAuthenticationEnabled()) {
                throw new IllegalStateException("Invalid broker configuration. Authentication must be enabled with "
                        + "authenticationEnabled=true when authorization is enabled with authorizationEnabled=true.");
            }

            localMetadataStore = createLocalMetadataStore();
            localMetadataStore.registerSessionListener(this::handleMetadataSessionEvent);

            coordinationService = new CoordinationServiceImpl(localMetadataStore);

            if (!StringUtils.equals(config.getConfigurationStoreServers(), config.getZookeeperServers())) {
                configurationMetadataStore = createConfigurationMetadataStore();
                shouldShutdownConfigurationMetadataStore = true;
            } else {
                configurationMetadataStore = localMetadataStore;
                shouldShutdownConfigurationMetadataStore = false;
            }
            pulsarResources = new PulsarResources(localMetadataStore, configurationMetadataStore,
                    config.getZooKeeperOperationTimeoutSeconds());

            pulsarResources.getClusterResources().getStore().registerListener(this::handleDeleteCluster);

            orderedExecutor = OrderedExecutor.newBuilder()
                    .numThreads(config.getNumOrderedExecutorThreads())
                    .name("pulsar-ordered")
                    .build();

            // Initialize the message protocol handlers
            protocolHandlers = ProtocolHandlers.load(config);
            protocolHandlers.initialize(config);

            // Now we are ready to start services
            this.bkClientFactory = newBookKeeperClientFactory();

            managedLedgerClientFactory = ManagedLedgerStorage.create(
                    config, localMetadataStore, getZkClient(),
                    bkClientFactory, ioEventLoopGroup
            );

            this.brokerService = newBrokerService(this);

            // Start load management service (even if load balancing is disabled)
            this.loadManager.set(LoadManager.create(this));

            // needs load management service and before start broker service,
            this.startNamespaceService();

            schemaStorage = createAndStartSchemaStorage();
            schemaRegistryService = SchemaRegistryService.create(
                    schemaStorage, config.getSchemaRegistryCompatibilityCheckers());

            this.defaultOffloader = createManagedLedgerOffloader(
                    OffloadPoliciesImpl.create(this.getConfiguration().getProperties()));
            this.brokerInterceptor = BrokerInterceptors.load(config);
            brokerService.setInterceptor(getBrokerInterceptor());
            this.brokerInterceptor.initialize(this);
            brokerService.start();

            // Load additional servlets
            this.brokerAdditionalServlets = AdditionalServlets.load(config);

            this.webService = new WebService(this);
            this.metricsServlet = new PrometheusMetricsServlet(
                    this, config.isExposeTopicLevelMetricsInPrometheus(),
                    config.isExposeConsumerLevelMetricsInPrometheus(),
                    config.isExposeProducerLevelMetricsInPrometheus(),
                    config.isSplitTopicAndPartitionLabelInPrometheus());
            if (pendingMetricsProviders != null) {
                pendingMetricsProviders.forEach(provider -> metricsServlet.addRawMetricsProvider(provider));
                this.pendingMetricsProviders = null;
            }

            this.addWebServerHandlers(webService, metricsServlet, this.config);
            this.webService.start();
            heartbeatNamespaceV1 = NamespaceService.getHeartbeatNamespace(this.advertisedAddress, this.config);
            heartbeatNamespaceV2 = NamespaceService.getHeartbeatNamespaceV2(this.advertisedAddress, this.config);

            // Refresh addresses and update configuration, since the port might have been dynamically assigned
            if (config.getBrokerServicePort().equals(Optional.of(0))) {
                config.setBrokerServicePort(brokerService.getListenPort());
            }
            if (config.getBrokerServicePortTls().equals(Optional.of(0))) {
                config.setBrokerServicePortTls(brokerService.getListenPortTls());
            }
            this.webServiceAddress = webAddress(config);
            this.webServiceAddressTls = webAddressTls(config);
            this.brokerServiceUrl = brokerUrl(config);
            this.brokerServiceUrlTls = brokerUrlTls(config);


            if (null != this.webSocketService) {
                ClusterDataImpl clusterData = ClusterDataImpl.builder()
                        .serviceUrl(webServiceAddress)
                        .serviceUrlTls(webServiceAddressTls)
                        .brokerServiceUrl(brokerServiceUrl)
                        .brokerServiceUrlTls(brokerServiceUrlTls)
                        .build();
                this.webSocketService.setLocalCluster(clusterData);
            }

            // Initialize namespace service, after service url assigned. Should init zk and refresh self owner info.
            this.nsService.initialize();

            // Start topic level policies service
            if (config.isTopicLevelPoliciesEnabled() && config.isSystemTopicEnabled()) {
                this.topicPoliciesService = new SystemTopicBasedTopicPoliciesService(this);
            }

            this.topicPoliciesService.start();

            // Start the leader election service
            startLeaderElectionService();

            // Register heartbeat and bootstrap namespaces.
            this.nsService.registerBootstrapNamespaces();

            // Register pulsar system namespaces and start transaction meta store service
            if (config.isTransactionCoordinatorEnabled()) {
                this.transactionBufferSnapshotService = new SystemTopicBaseTxnBufferSnapshotService(getClient());
                this.transactionTimer =
                        new HashedWheelTimer(new DefaultThreadFactory("pulsar-transaction-timer"));
                transactionBufferClient = TransactionBufferClientImpl.create(this, transactionTimer,
                        config.getTransactionBufferClientMaxConcurrentRequests(),
                        config.getTransactionBufferClientOperationTimeoutInMills());

                transactionMetadataStoreService = new TransactionMetadataStoreService(TransactionMetadataStoreProvider
                        .newProvider(config.getTransactionMetadataStoreProviderClassName()), this,
                        transactionBufferClient, transactionTimer);

                transactionBufferProvider = TransactionBufferProvider
                        .newProvider(config.getTransactionBufferProviderClassName());
                transactionPendingAckStoreProvider = TransactionPendingAckStoreProvider
                        .newProvider(config.getTransactionPendingAckStoreProviderClassName());
            }

            this.metricsGenerator = new MetricsGenerator(this);

            // By starting the Load manager service, the broker will also become visible
            // to the rest of the broker by creating the registration z-node. This needs
            // to be done only when the broker is fully operative.
            this.startLoadManagementService();

            // Initialize the message protocol handlers.
            // start the protocol handlers only after the broker is ready,
            // so that the protocol handlers can access broker service properly.
            this.protocolHandlers.start(brokerService);
            Map<String, Map<InetSocketAddress, ChannelInitializer<SocketChannel>>> protocolHandlerChannelInitializers =
                    this.protocolHandlers.newChannelInitializers();
            this.brokerService.startProtocolHandlers(protocolHandlerChannelInitializers);

            acquireSLANamespace();

            // start function worker service if necessary
            this.startWorkerService(brokerService.getAuthenticationService(), brokerService.getAuthorizationService());

            // start packages management service if necessary
            if (config.isEnablePackagesManagement()) {
                this.startPackagesManagementService();
            }

            // Start the task to publish resource usage, if necessary
            this.resourceUsageTransportManager = DISABLE_RESOURCE_USAGE_TRANSPORT_MANAGER;
            if (isNotBlank(config.getResourceUsageTransportClassName())) {
                Class<?> clazz = Class.forName(config.getResourceUsageTransportClassName());
                Constructor<?> ctor = clazz.getConstructor(PulsarService.class);
                Object object = ctor.newInstance(new Object[]{this});
                this.resourceUsageTransportManager = (ResourceUsageTopicTransportManager) object;
            }
            this.resourceGroupServiceManager = new ResourceGroupService(this);

            long currentTimestamp = System.currentTimeMillis();
            final long bootstrapTimeSeconds = TimeUnit.MILLISECONDS.toSeconds(currentTimestamp - startTimestamp);

            final String bootstrapMessage = "bootstrap service "
                    + (config.getWebServicePort().isPresent() ? "port = " + config.getWebServicePort().get() : "")
                    + (config.getWebServicePortTls().isPresent() ? ", tls-port = " + config.getWebServicePortTls() : "")
                    + (StringUtils.isNotEmpty(brokerServiceUrl) ? ", broker url= " + brokerServiceUrl : "")
                    + (StringUtils.isNotEmpty(brokerServiceUrlTls) ? ", broker tls url= " + brokerServiceUrlTls : "");
            LOG.info("messaging service is ready, bootstrap_seconds={}", bootstrapTimeSeconds);
            LOG.info("messaging service is ready, {}, cluster={}, configs={}", bootstrapMessage,
                    config.getClusterName(), ReflectionToStringBuilder.toString(config));

            state = State.Started;
        } catch (Exception e) {
            LOG.error("Failed to start Pulsar service: {}", e.getMessage(), e);
            throw new PulsarServerException(e);
        } finally {
            mutex.unlock();
        }
    }
}
```

## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
