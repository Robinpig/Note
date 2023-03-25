## Introduction


## Structure

- coordinationService
- leaderElectionService
- schemaStorage
- brokerService
  - start netty
- loadManager
- webService
- webSocketService
- 

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

## start

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


## elect

startLeaderElectionService -> LeaderElectionImpl#start -> elect

if create a temp znode `/loadbalance/leader` successfully, then tryToBecomeLeader

```java
class LeaderElectionImpl<T> implements LeaderElection<T> {
  private synchronized CompletableFuture<LeaderElectionState> elect() {
    // First check if there's already a leader elected
    internalState = InternalState.ElectionInProgress;
    return store.get(path).thenCompose(optLock -> {
      if (optLock.isPresent()) {
        return handleExistingLeaderValue(optLock.get());
      } else {
        return tryToBecomeLeader();
      }
    }).thenCompose(leaderElectionState ->
            // make sure that the cache contains the current leader so that getLeaderValueIfPresent works on all brokers
            cache.get(path).thenApply(__ -> leaderElectionState));
  }
}
```
#### tryToBecomeLeader

```java
class LeaderElectionImpl<T> implements LeaderElection<T> {
  private synchronized CompletableFuture<LeaderElectionState> tryToBecomeLeader() {
    byte[] payload;
    try {
      payload = serde.serialize(path, proposedValue.get());
    } catch (Throwable t) {
      return FutureUtils.exception(t);
    }

    CompletableFuture<LeaderElectionState> result = new CompletableFuture<>();
    store.put(path, payload, Optional.of(-1L), EnumSet.of(CreateOption.Ephemeral))
            .thenAccept(stat -> {
              synchronized (LeaderElectionImpl.this) {
                if (internalState == InternalState.ElectionInProgress) {
                  // Do a get() in order to force a notification later, if the z-node disappears
                  cache.get(path)
                          .thenRun(() -> {
                            synchronized (LeaderElectionImpl.this) {
                              log.info("Acquired leadership on {}", path);
                              internalState = InternalState.LeaderIsPresent;
                              if (leaderElectionState != LeaderElectionState.Leading) {
                                leaderElectionState = LeaderElectionState.Leading;
                                try {
                                  stateChangesListener.accept(leaderElectionState);
                                } catch (Throwable t) {
                                  log.warn("Exception in state change listener", t);
                                }
                              }
                              result.complete(leaderElectionState);
                            }
                          }).exceptionally(ex -> {
                            // We fail to do the get(), so clean up the leader election fail the whole
                            // operation
                            store.delete(path, Optional.of(stat.getVersion()))
                                    .thenRun(() -> result.completeExceptionally(ex))
                                    .exceptionally(ex2 -> {
                                      result.completeExceptionally(ex2);
                                      return null;
                                    });
                            return null;
                          });
                } else {
                  // LeaderElection was closed in between. Release the lock asynchronously
                  store.delete(path, Optional.of(stat.getVersion()))
                          .thenRun(() -> result.completeExceptionally(
                                  new AlreadyClosedException("The leader election was already closed")))
                          .exceptionally(ex -> {
                            result.completeExceptionally(ex);
                            return null;
                          });
                }
              }
            }).exceptionally(ex -> {
              if (ex.getCause() instanceof BadVersionException) {
                // There was a conflict between 2 participants trying to become leaders at same time. Retry
                // to fetch info on new leader.

                // We force the invalidation of the cache entry. Since we received a BadVersion error, we
                // already know that the entry is out of date. If we don't invalidate, we'd be retrying the
                // leader election many times until we finally receive the notification that invalidates the
                // cache.
                cache.invalidate(path);
                elect()
                        .thenAccept(lse -> result.complete(lse))
                        .exceptionally(ex2 -> {
                          result.completeExceptionally(ex2);
                          return null;
                        });
              } else {
                result.completeExceptionally(ex.getCause());
              }
              return null;
            });

    return result;
  }
}
```


## Topic


### createPersistentTopic


```java
public class BrokerService implements Closeable {
  private void createPersistentTopic(final String topic, boolean createIfMissing,
                                     CompletableFuture<Optional<Topic>> topicFuture) {
    final long topicCreateTimeMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime());
    TopicName topicName = TopicName.get(topic);

    if (isTransactionSystemTopic(topicName)) {
      String msg = String.format("Can not create transaction system topic %s", topic);
      log.warn(msg);
      pulsar.getExecutor().execute(() -> topics.remove(topic, topicFuture));
      topicFuture.completeExceptionally(new NotAllowedException(msg));
      return;
    }

    CompletableFuture<Void> maxTopicsCheck = createIfMissing
            ? checkMaxTopicsPerNamespace(topicName, 1)
            : CompletableFuture.completedFuture(null);

    maxTopicsCheck.thenCompose(__ -> getManagedLedgerConfig(topicName)).thenAccept(managedLedgerConfig -> {
      if (isBrokerEntryMetadataEnabled()) {
        // init managedLedger interceptor
        Set<BrokerEntryMetadataInterceptor> interceptors = new HashSet<>();
        for (BrokerEntryMetadataInterceptor interceptor : brokerEntryMetadataInterceptors) {
          // add individual AppendOffsetMetadataInterceptor for each topic
          if (interceptor instanceof AppendIndexMetadataInterceptor) {
            interceptors.add(new AppendIndexMetadataInterceptor());
          } else {
            interceptors.add(interceptor);
          }
        }
        managedLedgerConfig.setManagedLedgerInterceptor(new ManagedLedgerInterceptorImpl(interceptors));
      }

      managedLedgerConfig.setCreateIfMissing(createIfMissing);

      // Once we have the configuration, we can proceed with the async open operation
      managedLedgerFactory.asyncOpen(topicName.getPersistenceNamingEncoding(), managedLedgerConfig,
              new OpenLedgerCallback() {
                @Override
                public void openLedgerComplete(ManagedLedger ledger, Object ctx) {
                  try {
                    PersistentTopic persistentTopic = isSystemTopic(topic)
                            ? new SystemTopic(topic, ledger, BrokerService.this)
                            : new PersistentTopic(topic, ledger, BrokerService.this);
                    CompletableFuture<Void> preCreateSubForCompaction =
                            persistentTopic.preCreateSubscriptionForCompactionIfNeeded();
                    CompletableFuture<Void> replicationFuture = persistentTopic
                            .initialize()
                            .thenCompose(__ -> persistentTopic.checkReplication());


                    CompletableFuture.allOf(preCreateSubForCompaction, replicationFuture)
                            .thenCompose(v -> {
                              // Also check dedup status
                              return persistentTopic.checkDeduplicationStatus();
                            }).thenRun(() -> {
                              log.info("Created topic {} - dedup is {}", topic,
                                      persistentTopic.isDeduplicationEnabled() ? "enabled" : "disabled");
                              long topicLoadLatencyMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime())
                                      - topicCreateTimeMs;
                              pulsarStats.recordTopicLoadTimeValue(topic, topicLoadLatencyMs);
                              if (topicFuture.isCompletedExceptionally()) {
                                log.warn("{} future is already completed with failure {}, closing the topic",
                                        topic, FutureUtil.getException(topicFuture));
                                persistentTopic.stopReplProducers().whenCompleteAsync((v, exception) -> {
                                  topics.remove(topic, topicFuture);
                                }, executor());
                              } else {
                                addTopicToStatsMaps(topicName, persistentTopic);
                                topicFuture.complete(Optional.of(persistentTopic));
                              }
                            }).exceptionally((ex) -> {
                              log.warn(
                                      "Replication or dedup check failed."
                                              + " Removing topic from topics list {}, {}",
                                      topic, ex);
                              persistentTopic.stopReplProducers().whenCompleteAsync((v, exception) -> {
                                topics.remove(topic, topicFuture);
                                topicFuture.completeExceptionally(ex);
                              }, executor());

                              return null;
                            });
                  } catch (PulsarServerException e) {
                    log.warn("Failed to create topic {}-{}", topic, e.getMessage());
                    pulsar.getExecutor().execute(() -> topics.remove(topic, topicFuture));
                    topicFuture.completeExceptionally(e);
                  }
                }

                @Override
                public void openLedgerFailed(ManagedLedgerException exception, Object ctx) {
                  if (!createIfMissing && exception instanceof ManagedLedgerNotFoundException) {
                    // We were just trying to load a topic and the topic doesn't exist
                    topicFuture.complete(Optional.empty());
                  } else {
                    log.warn("Failed to create topic {}", topic, exception);
                    pulsar.getExecutor().execute(() -> topics.remove(topic, topicFuture));
                    topicFuture.completeExceptionally(new PersistenceException(exception));
                  }
                }
              }, () -> isTopicNsOwnedByBroker(topicName), null);

    }).exceptionally((exception) -> {
      log.warn("[{}] Failed to get topic configuration: {}", topic, exception.getMessage(), exception);
      // remove topic from topics-map in different thread to avoid possible deadlock if
      // createPersistentTopic-thread only tries to handle this future-result
      pulsar.getExecutor().execute(() -> topics.remove(topic, topicFuture));
      topicFuture.completeExceptionally(exception);
      return null;
    });
  }
}
```


ManagedLedgerImpl#initialize
```java
public class ManagedLedgerImpl implements ManagedLedger, CreateCallback {
  synchronized void initialize(final ManagedLedgerInitializeLedgerCallback callback, final Object ctx) {
    log.info("Opening managed ledger {}", name);

    // Fetch the list of existing ledgers in the managed ledger
    store.getManagedLedgerInfo(name, config.isCreateIfMissing(), new MetaStoreCallback<ManagedLedgerInfo>() {
      @Override
      public void operationComplete(ManagedLedgerInfo mlInfo, Stat stat) {
        ledgersStat = stat;
        if (mlInfo.hasTerminatedPosition()) {
          state = State.Terminated;
          lastConfirmedEntry = new PositionImpl(mlInfo.getTerminatedPosition());
          log.info("[{}] Recovering managed ledger terminated at {}", name, lastConfirmedEntry);
        }

        for (LedgerInfo ls : mlInfo.getLedgerInfoList()) {
          ledgers.put(ls.getLedgerId(), ls);
        }

        if (mlInfo.getPropertiesCount() > 0) {
          propertiesMap = Maps.newHashMap();
          for (int i = 0; i < mlInfo.getPropertiesCount(); i++) {
            MLDataFormats.KeyValue property = mlInfo.getProperties(i);
            propertiesMap.put(property.getKey(), property.getValue());
          }
        }
        if (managedLedgerInterceptor != null) {
          managedLedgerInterceptor.onManagedLedgerPropertiesInitialize(propertiesMap);
        }

        // Last ledger stat may be zeroed, we must update it
        if (ledgers.size() > 0) {
          final long id = ledgers.lastKey();
          OpenCallback opencb = (rc, lh, ctx1) -> {
            executor.executeOrdered(name, safeRun(() -> {
              mbean.endDataLedgerOpenOp();
              if (rc == BKException.Code.OK) {
                LedgerInfo info = LedgerInfo.newBuilder().setLedgerId(id)
                        .setEntries(lh.getLastAddConfirmed() + 1).setSize(lh.getLength())
                        .setTimestamp(clock.millis()).build();
                ledgers.put(id, info);
                if (managedLedgerInterceptor != null) {
                  managedLedgerInterceptor.onManagedLedgerLastLedgerInitialize(name, lh)
                          .thenRun(() -> initializeBookKeeper(callback))
                          .exceptionally(ex -> {
                            callback.initializeFailed(
                                    new ManagedLedgerInterceptException(ex.getCause()));
                            return null;
                          });
                } else {
                  initializeBookKeeper(callback);
                }
              } else if (isNoSuchLedgerExistsException(rc)) {
                log.warn("[{}] Ledger not found: {}", name, ledgers.lastKey());
                ledgers.remove(ledgers.lastKey());
                initializeBookKeeper(callback);
              } else {
                log.error("[{}] Failed to open ledger {}: {}", name, id, BKException.getMessage(rc));
                callback.initializeFailed(createManagedLedgerException(rc));
                return;
              }
            }));
          };

          mbean.startDataLedgerOpenOp();
          bookKeeper.asyncOpenLedger(id, digestType, config.getPassword(), opencb, null);
        } else {
          initializeBookKeeper(callback);
        }
      }

      @Override
      public void operationFailed(MetaStoreException e) {
        if (e instanceof MetadataNotFoundException) {
          callback.initializeFailed(new ManagedLedgerNotFoundException(e));
        } else {
          callback.initializeFailed(new ManagedLedgerException(e));
        }
      }
    });

    scheduleTimeoutTask();
  }
}
```
initializeBookKeeper

```java

    private synchronized void initializeBookKeeper(final ManagedLedgerInitializeLedgerCallback callback) {
        // Calculate total entries and size
        Iterator<LedgerInfo> iterator = ledgers.values().iterator();
        while (iterator.hasNext()) {
            LedgerInfo li = iterator.next();
            if (li.getEntries() > 0) {
                NUMBER_OF_ENTRIES_UPDATER.addAndGet(this, li.getEntries());
                TOTAL_SIZE_UPDATER.addAndGet(this, li.getSize());
            } else {
                iterator.remove();
                bookKeeper.asyncDeleteLedger(li.getLedgerId(), (rc, ctx) -> {
                }, null);
            }
        }

        if (state == State.Terminated) {
            // When recovering a terminated managed ledger, we don't need to create
            // a new ledger for writing, since no more writes are allowed.
            // We just move on to the next stage
            initializeCursors(callback);
            return;
        }

        final MetaStoreCallback<Void> storeLedgersCb = new MetaStoreCallback<Void>() {
            @Override
            public void operationComplete(Void v, Stat stat) {
                ledgersStat = stat;
                initializeCursors(callback);
            }

            @Override
            public void operationFailed(MetaStoreException e) {
                callback.initializeFailed(new ManagedLedgerException(e));
            }
        };

        // Create a new ledger to start writing
        this.lastLedgerCreationInitiationTimestamp = System.currentTimeMillis();
        mbean.startDataLedgerCreateOp();

        asyncCreateLedger(bookKeeper, config, digestType, (rc, lh, ctx) -> {

            if (checkAndCompleteLedgerOpTask(rc, lh, ctx)) {
                return;
            }

            executor.executeOrdered(name, safeRun(() -> {
                mbean.endDataLedgerCreateOp();
                if (rc != BKException.Code.OK) {
                    callback.initializeFailed(createManagedLedgerException(rc));
                    return;
                }

                log.info("[{}] Created ledger {}", name, lh.getId());
                STATE_UPDATER.set(this, State.LedgerOpened);
                updateLastLedgerCreatedTimeAndScheduleRolloverTask();
                currentLedger = lh;

                lastConfirmedEntry = new PositionImpl(lh.getId(), -1);
                // bypass empty ledgers, find last ledger with Message if possible.
                while (lastConfirmedEntry.getEntryId() == -1) {
                    Map.Entry<Long, LedgerInfo> formerLedger = ledgers.lowerEntry(lastConfirmedEntry.getLedgerId());
                    if (formerLedger != null) {
                        LedgerInfo ledgerInfo = formerLedger.getValue();
                        lastConfirmedEntry = PositionImpl.get(ledgerInfo.getLedgerId(), ledgerInfo.getEntries() - 1);
                    } else {
                        break;
                    }
                }

                LedgerInfo info = LedgerInfo.newBuilder().setLedgerId(lh.getId()).setTimestamp(0).build();
                ledgers.put(lh.getId(), info);

                // Save it back to ensure all nodes exist
                store.asyncUpdateLedgerIds(name, getManagedLedgerInfo(), ledgersStat, storeLedgersCb);
            }));
        }, ledgerMetadata);
    }

```
### lookup

findBrokerServiceUrl -> searchForCandidateBroker

```java

    private void searchForCandidateBroker(NamespaceBundle bundle,
                                          CompletableFuture<Optional<LookupResult>> lookupFuture,
                                          LookupOptions options) {
        if (null == pulsar.getLeaderElectionService()) {
            LOG.warn("The leader election has not yet been completed! NamespaceBundle[{}]", bundle);
            lookupFuture.completeExceptionally(
                    new IllegalStateException("The leader election has not yet been completed!"));
            return;
        }
        String candidateBroker = null;
        String candidateBrokerAdvertisedAddr = null;

        LeaderElectionService les = pulsar.getLeaderElectionService();
        if (les == null) {
            // The leader election service was not initialized yet. This can happen because the broker service is
            // initialized first and it might start receiving lookup requests before the leader election service is
            // fully initialized.
            LOG.warn("Leader election service isn't initialized yet. "
                            + "Returning empty result to lookup. NamespaceBundle[{}]",
                    bundle);
            lookupFuture.complete(Optional.empty());
            return;
        }

        boolean authoritativeRedirect = les.isLeader();

        try {
            // check if this is Heartbeat or SLAMonitor namespace
            candidateBroker = checkHeartbeatNamespace(bundle);
            if (candidateBroker == null) {
                candidateBroker = checkHeartbeatNamespaceV2(bundle);
            }
            if (candidateBroker == null) {
                String broker = getSLAMonitorBrokerName(bundle);
                // checking if the broker is up and running
                if (broker != null && isBrokerActive(broker)) {
                    candidateBroker = broker;
                }
            }

            if (candidateBroker == null) {
                Optional<LeaderBroker> currentLeader = pulsar.getLeaderElectionService().getCurrentLeader();

                if (options.isAuthoritative()) {
                    // leader broker already assigned the current broker as owner
                    candidateBroker = pulsar.getSafeWebServiceAddress();
                } else {
                    LoadManager loadManager = this.loadManager.get();
                    boolean makeLoadManagerDecisionOnThisBroker = !loadManager.isCentralized() || les.isLeader();
                    if (!makeLoadManagerDecisionOnThisBroker) {
                        // If leader is not active, fallback to pick the least loaded from current broker loadmanager
                        boolean leaderBrokerActive = currentLeader.isPresent()
                                && isBrokerActive(currentLeader.get().getServiceUrl());
                        if (!leaderBrokerActive) {
                            makeLoadManagerDecisionOnThisBroker = true;
                            if (!currentLeader.isPresent()) {
                                LOG.warn(
                                        "The information about the current leader broker wasn't available. "
                                                + "Handling load manager decisions in a decentralized way. "
                                                + "NamespaceBundle[{}]",
                                        bundle);
                            } else {
                                LOG.warn(
                                        "The current leader broker {} isn't active. "
                                                + "Handling load manager decisions in a decentralized way. "
                                                + "NamespaceBundle[{}]",
                                        currentLeader.get(), bundle);
                            }
                        }
                    }
                    if (makeLoadManagerDecisionOnThisBroker) {
                        Optional<Pair<String, String>> availableBroker = getLeastLoadedFromLoadManager(bundle);
                        if (!availableBroker.isPresent()) {
                            LOG.warn("Load manager didn't return any available broker. "
                                            + "Returning empty result to lookup. NamespaceBundle[{}]",
                                    bundle);
                            lookupFuture.complete(Optional.empty());
                            return;
                        }
                        candidateBroker = availableBroker.get().getLeft();
                        candidateBrokerAdvertisedAddr = availableBroker.get().getRight();
                        authoritativeRedirect = true;
                    } else {
                        // forward to leader broker to make assignment
                        candidateBroker = currentLeader.get().getServiceUrl();
                    }
                }
            }
        } catch (Exception e) {
            LOG.warn("Error when searching for candidate broker to acquire {}: {}", bundle, e.getMessage(), e);
            lookupFuture.completeExceptionally(e);
            return;
        }

        try {
            checkNotNull(candidateBroker);

            if (candidateBroker.equals(pulsar.getSafeWebServiceAddress())) {
                // Load manager decided that the local broker should try to become the owner
                ownershipCache.tryAcquiringOwnership(bundle).thenAccept(ownerInfo -> {
                    if (ownerInfo.isDisabled()) {
                        lookupFuture.completeExceptionally(new IllegalStateException(
                                String.format("Namespace bundle %s is currently being unloaded", bundle)));
                    } else {
                        // Found owner for the namespace bundle

                        if (options.isLoadTopicsInBundle()) {
                            // Schedule the task to pre-load topics
                            pulsar.loadNamespaceTopics(bundle);
                        }
                        // find the target
                        if (options.hasAdvertisedListenerName()) {
                            AdvertisedListener listener =
                                    ownerInfo.getAdvertisedListeners().get(options.getAdvertisedListenerName());
                            if (listener == null) {
                                lookupFuture.completeExceptionally(
                                        new PulsarServerException("the broker do not have "
                                                + options.getAdvertisedListenerName() + " listener"));
                                return;
                            } else {
                                URI url = listener.getBrokerServiceUrl();
                                URI urlTls = listener.getBrokerServiceUrlTls();
                                lookupFuture.complete(Optional.of(
                                        new LookupResult(ownerInfo,
                                                url == null ? null : url.toString(),
                                                urlTls == null ? null : urlTls.toString())));
                                return;
                            }
                        } else {
                            lookupFuture.complete(Optional.of(new LookupResult(ownerInfo)));
                            return;
                        }
                    }
                }).exceptionally(exception -> {
                    LOG.warn("Failed to acquire ownership for namespace bundle {}: {}", bundle, exception);
                    lookupFuture.completeExceptionally(new PulsarServerException(
                            "Failed to acquire ownership for namespace bundle " + bundle, exception));
                    return null;
                });

            } else {
                // Load managed decider some other broker should try to acquire ownership

                // Now setting the redirect url
                createLookupResult(candidateBrokerAdvertisedAddr == null ? candidateBroker
                        : candidateBrokerAdvertisedAddr, authoritativeRedirect, options.getAdvertisedListenerName())
                        .thenAccept(lookupResult -> lookupFuture.complete(Optional.of(lookupResult)))
                        .exceptionally(ex -> {
                            lookupFuture.completeExceptionally(ex);
                            return null;
                        });

            }
        } catch (Exception e) {
            LOG.warn("Error in trying to acquire namespace bundle ownership for {}: {}", bundle, e.getMessage(), e);
            lookupFuture.completeExceptionally(e);
        }
    }

```

#### selectBrokerForAssignment
searchForCandidateBroker -> getLeastLoadedFromLoadManager -> getLeastLoaded -> selectBrokerForAssignment

As the leader broker, find a suitable broker for the assignment of the given bundle.

```java
  @Override
    public Optional<String> selectBrokerForAssignment(final ServiceUnitId serviceUnit) {
        // Use brokerCandidateCache as a lock to reduce synchronization.
        long startTime = System.nanoTime();

        try {
            synchronized (brokerCandidateCache) {
                final String bundle = serviceUnit.toString();
                if (preallocatedBundleToBroker.containsKey(bundle)) {
                    // If the given bundle is already in preallocated, return the selected broker.
                    return Optional.of(preallocatedBundleToBroker.get(bundle));
                }
                final BundleData data = loadData.getBundleData().computeIfAbsent(bundle,
                        key -> getBundleDataOrDefault(bundle));
                brokerCandidateCache.clear();
                LoadManagerShared.applyNamespacePolicies(serviceUnit, policies, brokerCandidateCache,
                        getAvailableBrokers(),
                        brokerTopicLoadingPredicate);

                // filter brokers which owns topic higher than threshold
                LoadManagerShared.filterBrokersWithLargeTopicCount(brokerCandidateCache, loadData,
                        conf.getLoadBalancerBrokerMaxTopics());

                // distribute namespaces to domain and brokers according to anti-affinity-group
                LoadManagerShared.filterAntiAffinityGroupOwnedBrokers(pulsar, serviceUnit.toString(),
                        brokerCandidateCache,
                        brokerToNamespaceToBundleRange, brokerToFailureDomainMap);
                // distribute bundles evenly to candidate-brokers

                LoadManagerShared.removeMostServicingBrokersForNamespace(serviceUnit.toString(), brokerCandidateCache,
                        brokerToNamespaceToBundleRange);
                log.info("{} brokers being considered for assignment of {}", brokerCandidateCache.size(), bundle);

                // Use the filter pipeline to finalize broker candidates.
                try {
                    for (BrokerFilter filter : filterPipeline) {
                        filter.filter(brokerCandidateCache, data, loadData, conf);
                    }
                } catch (BrokerFilterException x) {
                    // restore the list of brokers to the full set
                    LoadManagerShared.applyNamespacePolicies(serviceUnit, policies, brokerCandidateCache,
                            getAvailableBrokers(),
                            brokerTopicLoadingPredicate);
                }

                if (brokerCandidateCache.isEmpty()) {
                    // restore the list of brokers to the full set
                    LoadManagerShared.applyNamespacePolicies(serviceUnit, policies, brokerCandidateCache,
                            getAvailableBrokers(),
                            brokerTopicLoadingPredicate);
                }

                // Choose a broker among the potentially smaller filtered list, when possible
                Optional<String> broker = placementStrategy.selectBroker(brokerCandidateCache, data, loadData, conf);

                if (!broker.isPresent()) {
                    // No brokers available
                    return broker;
                }

                final double overloadThreshold = conf.getLoadBalancerBrokerOverloadedThresholdPercentage() / 100.0;
                final double maxUsage = loadData.getBrokerData().get(broker.get()).getLocalData().getMaxResourceUsage();
                if (maxUsage > overloadThreshold) {
                    // All brokers that were in the filtered list were overloaded, so check if there is a better broker
                    LoadManagerShared.applyNamespacePolicies(serviceUnit, policies, brokerCandidateCache,
                            getAvailableBrokers(),
                            brokerTopicLoadingPredicate);
                    Optional<String> brokerTmp =
                            placementStrategy.selectBroker(brokerCandidateCache, data, loadData, conf);
                    if (brokerTmp.isPresent()) {
                        broker = brokerTmp;
                    }
                }

                // Add new bundle to preallocated.
                loadData.getBrokerData().get(broker.get()).getPreallocatedBundleData().put(bundle, data);
                preallocatedBundleToBroker.put(bundle, broker.get());

                final String namespaceName = LoadManagerShared.getNamespaceNameFromBundleName(bundle);
                final String bundleRange = LoadManagerShared.getBundleRangeFromBundleName(bundle);
                final ConcurrentOpenHashMap<String, ConcurrentOpenHashSet<String>> namespaceToBundleRange =
                        brokerToNamespaceToBundleRange
                                .computeIfAbsent(broker.get(),
                                        k -> ConcurrentOpenHashMap.<String,
                                                ConcurrentOpenHashSet<String>>newBuilder()
                                                .build());
                synchronized (namespaceToBundleRange) {
                    namespaceToBundleRange.computeIfAbsent(namespaceName,
                            k -> ConcurrentOpenHashSet.<String>newBuilder().build())
                            .add(bundleRange);
                }
                return broker;
            }
        } finally {
            selectBrokerForAssignment.observe(System.nanoTime() - startTime, TimeUnit.NANOSECONDS);
        }
    }

```



### unload
tasks
```java
public class PulsarService implements AutoCloseable, ShutdownService {
  protected void startLeaderElectionService() {
    this.leaderElectionService = new LeaderElectionService(coordinationService, getSafeWebServiceAddress(),
            state -> {
              if (state == LeaderElectionState.Leading) {
                LOG.info("This broker was elected leader");
                if (getConfiguration().isLoadBalancerEnabled()) {
                  long loadSheddingInterval = TimeUnit.MINUTES
                          .toMillis(getConfiguration().getLoadBalancerSheddingIntervalMinutes());
                  long resourceQuotaUpdateInterval = TimeUnit.MINUTES
                          .toMillis(getConfiguration().getLoadBalancerResourceQuotaUpdateIntervalMinutes());
                  // cancel exist tasks
                  
                  loadSheddingTask = loadManagerExecutor.scheduleAtFixedRate(
                          new LoadSheddingTask(loadManager),
                          loadSheddingInterval, loadSheddingInterval, TimeUnit.MILLISECONDS);
                  loadResourceQuotaTask = loadManagerExecutor.scheduleAtFixedRate(
                          new LoadResourceQuotaUpdaterTask(loadManager), resourceQuotaUpdateInterval,
                          resourceQuotaUpdateInterval, TimeUnit.MILLISECONDS);
                }
              }
            });

    leaderElectionService.start();
  }
}
```
LoadSheddingTask
```java
public class LoadSheddingTask implements Runnable {
    private static final Logger LOG = LoggerFactory.getLogger(LoadSheddingTask.class);
    private final AtomicReference<LoadManager> loadManager;

    public LoadSheddingTask(AtomicReference<LoadManager> loadManager) {
        this.loadManager = loadManager;
    }

    @Override
    public void run() {
        try {
            loadManager.get().doLoadShedding();
        } catch (Exception e) {
            LOG.warn("Error during the load shedding", e);
        }
    }
}
```
#### doLoadShedding
```java
 @Override
    public synchronized void doLoadShedding() {
        if (!LoadManagerShared.isLoadSheddingEnabled(pulsar)) {
            return;
        }
        if (getAvailableBrokers().size() <= 1) {
            log.info("Only 1 broker available: no load shedding will be performed");
            return;
        }
        // Remove bundles who have been unloaded for longer than the grace period from the recently unloaded map.
        final long timeout = System.currentTimeMillis()
                - TimeUnit.MINUTES.toMillis(conf.getLoadBalancerSheddingGracePeriodMinutes());
        final Map<String, Long> recentlyUnloadedBundles = loadData.getRecentlyUnloadedBundles();
        recentlyUnloadedBundles.keySet().removeIf(e -> recentlyUnloadedBundles.get(e) < timeout);

        for (LoadSheddingStrategy strategy : loadSheddingPipeline) {
            final Multimap<String, String> bundlesToUnload = strategy.findBundlesForUnloading(loadData, conf);

            bundlesToUnload.asMap().forEach((broker, bundles) -> {
                bundles.forEach(bundle -> {
                    final String namespaceName = LoadManagerShared.getNamespaceNameFromBundleName(bundle);
                    final String bundleRange = LoadManagerShared.getBundleRangeFromBundleName(bundle);
                    if (!shouldAntiAffinityNamespaceUnload(namespaceName, bundleRange, broker)) {
                        return;
                    }

                    log.info("[{}] Unloading bundle: {} from broker {}",
                            strategy.getClass().getSimpleName(), bundle, broker);
                    try {
                        pulsar.getAdminClient().namespaces().unloadNamespaceBundle(namespaceName, bundleRange);
                        loadData.getRecentlyUnloadedBundles().put(bundle, System.currentTimeMillis());
                    } catch (PulsarServerException | PulsarAdminException e) {
                        log.warn("Error when trying to perform load shedding on {} for broker {}", bundle, broker, e);
                    }
                });
            });

            updateBundleUnloadingMetrics(bundlesToUnload);
        }
    }

```





## handleSend

```java
package org.apache.pulsar.broker.service;

public class ServerCnx extends PulsarHandler implements TransportCnx {
    @Override
    protected void handleSend(CommandSend send, ByteBuf headersAndPayload) {
        checkArgument(state == State.Connected);

        CompletableFuture<Producer> producerFuture = producers.get(send.getProducerId());

        if (producerFuture == null || !producerFuture.isDone() || producerFuture.isCompletedExceptionally()) {
            log.warn("[{}] Received message, but the producer is not ready : {}. Closing the connection.",
                    remoteAddress, send.getProducerId());
            close();
            return;
        }

        Producer producer = producerFuture.getNow(null);

        if (producer.isNonPersistentTopic()) {
            // avoid processing non-persist message if reached max concurrent-message limit
            if (nonPersistentPendingMessages > maxNonPersistentPendingMessages) {
                final long producerId = send.getProducerId();
                final long sequenceId = send.getSequenceId();
                final long highestSequenceId = send.getHighestSequenceId();
                service.getTopicOrderedExecutor().executeOrdered(producer.getTopic().getName(), SafeRun.safeRun(() -> {
                    commandSender.sendSendReceiptResponse(producerId, sequenceId, highestSequenceId, -1, -1);
                }));
                producer.recordMessageDrop(send.getNumMessages());
                return;
            } else {
                nonPersistentPendingMessages++;
            }
        }

        startSendOperation(producer, headersAndPayload.readableBytes(), send.getNumMessages());

        if (send.hasTxnidMostBits() && send.hasTxnidLeastBits()) {
            TxnID txnID = new TxnID(send.getTxnidMostBits(), send.getTxnidLeastBits());
            producer.publishTxnMessage(txnID, producer.getProducerId(), send.getSequenceId(),
                    send.getHighestSequenceId(), headersAndPayload, send.getNumMessages(), send.isIsChunk(),
                    send.isMarker());
            return;
        }

        // Persist the message
        if (send.hasHighestSequenceId() && send.getSequenceId() <= send.getHighestSequenceId()) {
            producer.publishMessage(send.getProducerId(), send.getSequenceId(), send.getHighestSequenceId(),
                    headersAndPayload, send.getNumMessages(), send.isIsChunk(), send.isMarker());
        } else {
            producer.publishMessage(send.getProducerId(), send.getSequenceId(), headersAndPayload,
                    send.getNumMessages(), send.isIsChunk(), send.isMarker());
        }
    }
}
```
### publishMessage

```java
public class Producer {
  public void publishMessage(long producerId, long lowestSequenceId, long highestSequenceId,
                             ByteBuf headersAndPayload, long batchSize, boolean isChunked, boolean isMarker) {
    if (lowestSequenceId > highestSequenceId) {
      cnx.execute(() -> {
        cnx.getCommandSender().sendSendError(producerId, highestSequenceId, ServerError.MetadataError,
                "Invalid lowest or highest sequence id");
        cnx.completedSendOperation(isNonPersistentTopic, headersAndPayload.readableBytes());
      });
      return;
    }
    if (checkAndStartPublish(producerId, highestSequenceId, headersAndPayload, batchSize)) {
      publishMessageToTopic(headersAndPayload, lowestSequenceId, highestSequenceId, batchSize, isChunked,
              isMarker);
    }
  }
}

public class PersistentTopic extends AbstractTopic
        implements Topic, AddEntryCallback, TopicPolicyListener<TopicPolicies> {
  @Override
  public void publishMessage(ByteBuf headersAndPayload, PublishContext publishContext) {
    pendingWriteOps.incrementAndGet();
    if (isFenced) {
      publishContext.completed(new TopicFencedException("fenced"), -1, -1);
      decrementPendingWriteOpsAndCheck();
      return;
    }
    if (isExceedMaximumMessageSize(headersAndPayload.readableBytes())) {
      publishContext.completed(new NotAllowedException("Exceed maximum message size")
              , -1, -1);
      decrementPendingWriteOpsAndCheck();
      return;
    }

    MessageDeduplication.MessageDupStatus status =
            messageDeduplication.isDuplicate(publishContext, headersAndPayload);
    switch (status) {
      case NotDup:
        asyncAddEntry(headersAndPayload, publishContext);
        break;
      case Dup:
        // Immediately acknowledge duplicated message
        publishContext.completed(null, -1, -1);
        decrementPendingWriteOpsAndCheck();
        break;
      default:
        publishContext.completed(new MessageDeduplication.MessageDupUnknownException(), -1, -1);
        decrementPendingWriteOpsAndCheck();

    }
  }

  private void asyncAddEntry(ByteBuf headersAndPayload, PublishContext publishContext) {
    if (brokerService.isBrokerEntryMetadataEnabled()) {
      ledger.asyncAddEntry(headersAndPayload,
              (int) publishContext.getNumberOfMessages(), this, publishContext);
    } else {
      ledger.asyncAddEntry(headersAndPayload, this, publishContext);
    }
  }
}
```

#### asyncAddEntry

```java
public class ManagedLedgerImpl implements ManagedLedger, CreateCallback {
  @Override
  public void asyncAddEntry(ByteBuf buffer, AddEntryCallback callback, Object ctx) {
    // retain buffer in this thread
    buffer.retain();

    // Jump to specific thread to avoid contention from writers writing from different threads
    executor.executeOrdered(name, safeRun(() -> {
      OpAddEntry addOperation = OpAddEntry.createNoRetainBuffer(this, buffer, callback, ctx);
      internalAsyncAddEntry(addOperation);
    }));
  }


  private synchronized void internalAsyncAddEntry(OpAddEntry addOperation) {
    if (!beforeAddEntry(addOperation)) {
      return;
    }
    final State state = STATE_UPDATER.get(this);
    if (state == State.Fenced) {
      addOperation.failed(new ManagedLedgerFencedException());
      return;
    } else if (state == State.Terminated) {
      addOperation.failed(new ManagedLedgerTerminatedException("Managed ledger was already terminated"));
      return;
    } else if (state == State.Closed) {
      addOperation.failed(new ManagedLedgerAlreadyClosedException("Managed ledger was already closed"));
      return;
    } else if (state == State.WriteFailed) {
      addOperation.failed(new ManagedLedgerAlreadyClosedException("Waiting to recover from failure"));
      return;
    }
    pendingAddEntries.add(addOperation);

    if (state == State.ClosingLedger || state == State.CreatingLedger) {
      // We don't have a ready ledger to write into
      // We are waiting for a new ledger to be created
      if (State.CreatingLedger == state) {
        long elapsedMs = System.currentTimeMillis() - this.lastLedgerCreationInitiationTimestamp;
        if (elapsedMs > TimeUnit.SECONDS.toMillis(2 * config.getMetadataOperationsTimeoutSeconds())) {
          log.info("[{}] Ledger creation was initiated {} ms ago but it never completed" +
                          " and creation timeout task didn't kick in as well. Force to fail the create ledger operation.",
                  name, elapsedMs);
          this.createComplete(Code.TimeoutException, null, null);
        }
      }
    } else if (state == State.ClosedLedger) {
      // No ledger and no pending operations. Create a new ledger
      if (STATE_UPDATER.compareAndSet(this, State.ClosedLedger, State.CreatingLedger)) {
        log.info("[{}] Creating a new ledger", name);
        this.lastLedgerCreationInitiationTimestamp = System.currentTimeMillis();
        mbean.startDataLedgerCreateOp();
        asyncCreateLedger(bookKeeper, config, digestType, this, Collections.emptyMap());
      }
    } else {
      checkArgument(state == State.LedgerOpened, "ledger=%s is not opened", state);

      // Write into lastLedger
      addOperation.setLedger(currentLedger);

      ++currentLedgerEntries;
      currentLedgerSize += addOperation.data.readableBytes();


      if (currentLedgerIsFull()) {
        // This entry will be the last added to current ledger
        addOperation.setCloseWhenDone(true);
        STATE_UPDATER.set(this, State.ClosingLedger);
      }
      addOperation.initiate();
    }
  }
}
```

### Rollover Ledger
initializeBookKeeper -> asyncCreateLedger -> updateLastLedgerCreatedTimeAndScheduleRolloverTask

```java
 private void updateLastLedgerCreatedTimeAndScheduleRolloverTask() {
        this.lastLedgerCreatedTimestamp = clock.millis();
        if (config.getMaximumRolloverTimeMs() > 0) {
            if (checkLedgerRollTask != null && !checkLedgerRollTask.isDone()) {
                // new ledger has been created successfully
                // and the previous checkLedgerRollTask is not done, we could cancel it
                checkLedgerRollTask.cancel(true);
            }
            this.checkLedgerRollTask = this.scheduledExecutor.schedule(
                    safeRun(this::rollCurrentLedgerIfFull), this.maximumRolloverTimeMs, TimeUnit.MILLISECONDS);
        }
    }
```

rollCurrentLedgerIfFull

```java

 @VisibleForTesting
    @Override
    public void rollCurrentLedgerIfFull() {
        log.info("[{}] Start checking if current ledger is full", name);
        if (currentLedgerEntries > 0 && currentLedgerIsFull()
                && STATE_UPDATER.compareAndSet(this, State.LedgerOpened, State.ClosingLedger)) {
            currentLedger.asyncClose(new AsyncCallback.CloseCallback() {
                @Override
                public void closeComplete(int rc, LedgerHandle lh, Object o) {
                    checkArgument(currentLedger.getId() == lh.getId(), "ledgerId %s doesn't match with acked ledgerId %s",
                            currentLedger.getId(),
                            lh.getId());

                    if (rc == BKException.Code.OK) {
                        log.debug("Successfully closed ledger {}", lh.getId());
                    } else {
                        log.warn("Error when closing ledger {}. Status={}", lh.getId(), BKException.getMessage(rc));
                    }

                    ledgerClosed(lh);
                    createLedgerAfterClosed();
                }
            }, System.nanoTime());
        }
    }
```
#### asyncCreateLedger
```java
synchronized void createLedgerAfterClosed() {
        if (isNeededCreateNewLedgerAfterCloseLedger()) {
            log.info("[{}] Creating a new ledger after closed", name);
            STATE_UPDATER.set(this, State.CreatingLedger);
            this.lastLedgerCreationInitiationTimestamp = System.currentTimeMillis();
            mbean.startDataLedgerCreateOp();
            // Use the executor here is to avoid use the Zookeeper thread to create the ledger which will lead
            // to deadlock at the zookeeper client, details to see https://github.com/apache/pulsar/issues/13736
            this.executor.execute(() ->
                    asyncCreateLedger(bookKeeper, config, digestType, this, Collections.emptyMap()));
        }
    }
```

Create ledger async and schedule a timeout task to check ledger-creation is complete else it fails the callback with TimeoutException.

```java
public class ManagedLedgerImpl implements ManagedLedger, CreateCallback {
  protected void asyncCreateLedger(BookKeeper bookKeeper, ManagedLedgerConfig config, DigestType digestType,
                                   CreateCallback cb, Map<String, byte[]> metadata) {
    AtomicBoolean ledgerCreated = new AtomicBoolean(false);
    Map<String, byte[]> finalMetadata = new HashMap<>();
    finalMetadata.putAll(ledgerMetadata);
    finalMetadata.putAll(metadata);
    if (config.getBookKeeperEnsemblePlacementPolicyClassName() != null
            && config.getBookKeeperEnsemblePlacementPolicyProperties() != null) {
      try {
        finalMetadata.putAll(LedgerMetadataUtils.buildMetadataForPlacementPolicyConfig(
                config.getBookKeeperEnsemblePlacementPolicyClassName(),
                config.getBookKeeperEnsemblePlacementPolicyProperties()
        ));
      } catch (EnsemblePlacementPolicyConfig.ParseEnsemblePlacementPolicyConfigException e) {
        log.error("[{}] Serialize the placement configuration failed", name, e);
        cb.createComplete(Code.UnexpectedConditionException, null, ledgerCreated);
        return;
      }
    }
    createdLedgerCustomMetadata = finalMetadata;
    log.info("[{}] Creating ledger, metadata: {} - metadata ops timeout : {} seconds",
            name, finalMetadata, config.getMetadataOperationsTimeoutSeconds());
    try {
      bookKeeper.asyncCreateLedger(config.getEnsembleSize(), config.getWriteQuorumSize(), config.getAckQuorumSize(),
              digestType, config.getPassword(), cb, ledgerCreated, finalMetadata);
    } catch (Throwable cause) {
      log.error("[{}] Encountered unexpected error when creating ledger",
              name, cause);
      cb.createComplete(Code.UnexpectedConditionException, null, ledgerCreated);
      return;
    }
    scheduledExecutor.schedule(() -> {
      if (!ledgerCreated.get()) {
      } else {
      }
      cb.createComplete(BKException.Code.TimeoutException, null, ledgerCreated);
    }, config.getMetadataOperationsTimeoutSeconds(), TimeUnit.SECONDS);
  }
}
```

## handleFlow

```java
public class ServerCnx extends PulsarHandler implements TransportCnx {
  protected void handleFlow(CommandFlow flow) {
    checkArgument(state == State.Connected);

    CompletableFuture<Consumer> consumerFuture = consumers.get(flow.getConsumerId());

    if (consumerFuture != null && consumerFuture.isDone() && !consumerFuture.isCompletedExceptionally()) {
      Consumer consumer = consumerFuture.getNow(null);
      if (consumer != null) {
        consumer.flowPermits(flow.getMessagePermits());
      } else {
        log.info("[{}] Couldn't find consumer {}", remoteAddress, flow.getConsumerId());
      }
    }
  }
}
public class Consumer {
  public void flowPermits(int additionalNumberOfMessages) {
    checkArgument(additionalNumberOfMessages > 0);

    // block shared consumer when unacked-messages reaches limit
    if (shouldBlockConsumerOnUnackMsgs() && unackedMessages >= maxUnackedMessages) {
      blockedConsumerOnUnackedMsgs = true;
    }
    int oldPermits;
    if (!blockedConsumerOnUnackedMsgs) {
      oldPermits = MESSAGE_PERMITS_UPDATER.getAndAdd(this, additionalNumberOfMessages);
      subscription.consumerFlow(this, additionalNumberOfMessages);
    } else {
      oldPermits = PERMITS_RECEIVED_WHILE_CONSUMER_BLOCKED_UPDATER.getAndAdd(this, additionalNumberOfMessages);
    }
  }
}
```


readMoreEntries
```java
public class PersistentDispatcherMultipleConsumers extends AbstractDispatcherMultipleConsumers
        implements Dispatcher, ReadEntriesCallback {
  public synchronized void readMoreEntries() {
    if (shouldPauseDeliveryForDelayTracker()) {
      return;
    }

    // totalAvailablePermits may be updated by other threads
    int firstAvailableConsumerPermits = getFirstAvailableConsumerPermits();
    int currentTotalAvailablePermits = Math.max(totalAvailablePermits, firstAvailableConsumerPermits);
    if (currentTotalAvailablePermits > 0 && firstAvailableConsumerPermits > 0) {
      Pair<Integer, Long> calculateResult = calculateToRead(currentTotalAvailablePermits);
      int messagesToRead = calculateResult.getLeft();
      long bytesToRead = calculateResult.getRight();

      if (messagesToRead == -1 || bytesToRead == -1) {
        // Skip read as topic/dispatcher has exceed the dispatch rate or previous pending read hasn't complete.
        return;
      }

      Set<PositionImpl> messagesToReplayNow = getMessagesToReplayNow(messagesToRead);

      if (!messagesToReplayNow.isEmpty()) {
        havePendingReplayRead = true;
        minReplayedPosition = messagesToReplayNow.stream().min(PositionImpl::compareTo).orElse(null);
        Set<? extends Position> deletedMessages = topic.isDelayedDeliveryEnabled()
                ? asyncReplayEntriesInOrder(messagesToReplayNow) : asyncReplayEntries(messagesToReplayNow);
        // clear already acked positions from replay bucket

        deletedMessages.forEach(position -> redeliveryMessages.remove(((PositionImpl) position).getLedgerId(),
                ((PositionImpl) position).getEntryId()));
        // if all the entries are acked-entries and cleared up from redeliveryMessages, try to read
        // next entries as readCompletedEntries-callback was never called
        if ((messagesToReplayNow.size() - deletedMessages.size()) == 0) {
          havePendingReplayRead = false;
          // We should not call readMoreEntries() recursively in the same thread
          // as there is a risk of StackOverflowError
          topic.getBrokerService().executor().execute(() -> readMoreEntries());
        }
      } else if (BLOCKED_DISPATCHER_ON_UNACKMSG_UPDATER.get(this) == TRUE) {
        log.warn("[{}] Dispatcher read is blocked due to unackMessages {} reached to max {}", name,
                totalUnackedMessages, topic.getMaxUnackedMessagesOnSubscription());
      } else if (!havePendingRead) {
        havePendingRead = true;
        Set<PositionImpl> toReplay = getMessagesToReplayNow(1);
        minReplayedPosition = toReplay.stream().findFirst().orElse(null);
        if (minReplayedPosition != null) {
          redeliveryMessages.add(minReplayedPosition.getLedgerId(), minReplayedPosition.getEntryId());
        }
        cursor.asyncReadEntriesOrWait(messagesToRead, bytesToRead, this,
                ReadType.Normal, topic.getMaxReadPosition());
      } else {
        log.debug("[{}] Cannot schedule next read until previous one is done", name);
      }
    }
  }
}
```

#### asyncReadEntry
asyncReadEntriesOrWait -> asyncReadEntries -> internalReadFromLedger -> asyncReadEntry
```java
 protected void asyncReadEntry(ReadHandle ledger, long firstEntry, long lastEntry, boolean isSlowestReader,
            OpReadEntry opReadEntry, Object ctx) {
        if (config.getReadEntryTimeoutSeconds() > 0) {
            // set readOpCount to uniquely validate if ReadEntryCallbackWrapper is already recycled
            long readOpCount = READ_OP_COUNT_UPDATER.incrementAndGet(this);
            long createdTime = System.nanoTime();
            ReadEntryCallbackWrapper readCallback = ReadEntryCallbackWrapper.create(name, ledger.getId(), firstEntry,
                    opReadEntry, readOpCount, createdTime, ctx);
            lastReadCallback = readCallback;
            entryCache.asyncReadEntry(ledger, firstEntry, lastEntry, isSlowestReader, readCallback, readOpCount);
        } else {
            entryCache.asyncReadEntry(ledger, firstEntry, lastEntry, isSlowestReader, opReadEntry, ctx);
        }
    }
```

```java
public class EntryCacheImpl implements EntryCache {
 @Override
    public void asyncReadEntry(ReadHandle lh, long firstEntry, long lastEntry, boolean isSlowestReader,
            final ReadEntriesCallback callback, Object ctx) {
        try {
            asyncReadEntry0(lh, firstEntry, lastEntry, isSlowestReader, callback, ctx);
        } catch (Throwable t) {
            log.warn("failed to read entries for {}--{}-{}", lh.getId(), firstEntry, lastEntry, t);
            // invalidate all entries related to ledger from the cache (it might happen if entry gets corrupt
            // (entry.data is already deallocate due to any race-condition) so, invalidate cache and next time read from
            // the bookie)
            invalidateAllEntries(lh.getId());
            callback.readEntriesFailed(createManagedLedgerException(t), ctx);
        }
    }
}
```

```java
public class EntryCacheImpl implements EntryCache {
  @SuppressWarnings({"unchecked", "rawtypes"})
  private void asyncReadEntry0(ReadHandle lh, long firstEntry, long lastEntry, boolean isSlowestReader,
                               final ReadEntriesCallback callback, Object ctx) {
    final long ledgerId = lh.getId();
    final int entriesToRead = (int) (lastEntry - firstEntry) + 1;
    final PositionImpl firstPosition = PositionImpl.get(lh.getId(), firstEntry);
    final PositionImpl lastPosition = PositionImpl.get(lh.getId(), lastEntry);

    Collection<EntryImpl> cachedEntries = entries.getRange(firstPosition, lastPosition);

    if (cachedEntries.size() == entriesToRead) {
      long totalCachedSize = 0;
      final List<EntryImpl> entriesToReturn = Lists.newArrayListWithExpectedSize(entriesToRead);

      // All entries found in cache
      for (EntryImpl entry : cachedEntries) {
        entriesToReturn.add(EntryImpl.create(entry));
        totalCachedSize += entry.getLength();
        entry.release();
      }

      manager.mlFactoryMBean.recordCacheHits(entriesToReturn.size(), totalCachedSize);

      callback.readEntriesComplete((List) entriesToReturn, ctx);

    } else {
      if (!cachedEntries.isEmpty()) {
        cachedEntries.forEach(entry -> entry.release());
      }

      // Read all the entries from bookkeeper
      lh.readAsync(firstEntry, lastEntry).thenAcceptAsync(
              ledgerEntries -> {
                checkNotNull(ml.getName());
                checkNotNull(ml.getExecutor());

                try {
                  // We got the entries, we need to transform them to a List<> type
                  long totalSize = 0;
                  final List<EntryImpl> entriesToReturn
                          = Lists.newArrayListWithExpectedSize(entriesToRead);
                  for (LedgerEntry e : ledgerEntries) {
                    EntryImpl entry = EntryImpl.create(e);

                    entriesToReturn.add(entry);
                    totalSize += entry.getLength();
                  }

                  manager.mlFactoryMBean.recordCacheMiss(entriesToReturn.size(), totalSize);
                  ml.getMBean().addReadEntriesSample(entriesToReturn.size(), totalSize);

                  callback.readEntriesComplete((List) entriesToReturn, ctx);
                } finally {
                  ledgerEntries.close();
                }
              }, ml.getExecutor().chooseThread(ml.getName())).exceptionally(exception -> {
        if (exception instanceof BKException
                && ((BKException) exception).getCode() == BKException.Code.TooManyRequestsException) {
          callback.readEntriesFailed(createManagedLedgerException(exception), ctx);
        } else {
          ml.invalidateLedgerHandle(lh);
          ManagedLedgerException mlException = createManagedLedgerException(exception);
          callback.readEntriesFailed(mlException, ctx);
        }
        return null;
      });
    }
  }
}
```
### sendMessages
Dispatch a list of entries to the consumer. It is also responsible to release entries data and recycle entries object.
```java
public class Consumer {
  public Future<Void> sendMessages(final List<Entry> entries, EntryBatchSizes batchSizes,
                                   EntryBatchIndexesAcks batchIndexesAcks,
                                   int totalMessages, long totalBytes, long totalChunkedMessages,
                                   RedeliveryTracker redeliveryTracker) {
    this.lastConsumedTimestamp = System.currentTimeMillis();

    if (entries.isEmpty() || totalMessages == 0) {
      batchSizes.recyle();
      if (batchIndexesAcks != null) {
        batchIndexesAcks.recycle();
      }
      final Promise<Void> writePromise = cnx.newPromise();
      writePromise.setSuccess(null);
      return writePromise;
    }
    int unackedMessages = totalMessages;
    int totalEntries = 0;

    for (int i = 0; i < entries.size(); i++) {
      Entry entry = entries.get(i);
      if (entry != null) {
        totalEntries++;
        // Note
        // Must ensure that the message is written to the pendingAcks before sent is first,
        // because this consumer is possible to disconnect at this time.
        if (pendingAcks != null) {
          int batchSize = batchSizes.getBatchSize(i);
          int stickyKeyHash = getStickyKeyHash(entry);
          long[] ackSet = getCursorAckSet(PositionImpl.get(entry.getLedgerId(), entry.getEntryId()));
          if (ackSet != null) {
            unackedMessages -= (batchSize - BitSet.valueOf(ackSet).cardinality());
          }
          pendingAcks.put(entry.getLedgerId(), entry.getEntryId(), batchSize, stickyKeyHash);
        }
      }
    }

    // calculate avg message per entry
    if (avgMessagesPerEntry.get() < 1) { //valid avgMessagesPerEntry should always >= 1
      // set init value.
      avgMessagesPerEntry.set(1.0 * totalMessages / totalEntries);
    } else {
      avgMessagesPerEntry.set(avgMessagesPerEntry.get() * avgPercent
              + (1 - avgPercent) * totalMessages / totalEntries);
    }

    // reduce permit and increment unackedMsg count with total number of messages in batch-msgs
    int ackedCount = batchIndexesAcks == null ? 0 : batchIndexesAcks.getTotalAckedIndexCount();
    MESSAGE_PERMITS_UPDATER.addAndGet(this, ackedCount - totalMessages);
    incrementUnackedMessages(unackedMessages);
    msgOut.recordMultipleEvents(totalMessages, totalBytes);
    msgOutCounter.add(totalMessages);
    bytesOutCounter.add(totalBytes);
    chunkedMessageRate.recordMultipleEvents(totalChunkedMessages, 0);


    return cnx.getCommandSender().sendMessagesToConsumer(consumerId, topicName, subscription, partitionIdx,
            entries, batchSizes, batchIndexesAcks, redeliveryTracker);
  }
}
```

## Metadata

Caffeine



## Authentication





## Links

- [Pulsar](/docs/CS/MQ/Pulsar/Pulsar.md)
