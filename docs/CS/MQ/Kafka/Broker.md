## Introduction




```scala
object Kafka extends Logging {
  def main(args: Array[String]): Unit = {
    try {
      val serverProps = getPropsFromArgs(args)
      val server = buildServer(serverProps)

      try {
        if (!OperatingSystem.IS_WINDOWS && !Java.isIbmJdk)
          new LoggingSignalHandler().register()
      } catch {
        case e: ReflectiveOperationException =>
          warn("Failed to register optional signal handler that logs a message when the process is terminated " +
            s"by a signal. Reason for registration failure is: $e", e)
      }

      // attach shutdown handler to catch terminating signals as well as normal termination
      Exit.addShutdownHook("kafka-shutdown-hook", {
        try server.shutdown()
        catch {
          case _: Throwable =>
            fatal("Halting Kafka.")
            // Calling exit() can lead to deadlock as exit() can be called multiple times. Force exit.
            Exit.halt(1)
        }
      })

      try server.startup()
      catch {
        case e: Throwable =>
          // KafkaServer.startup() calls shutdown() in case of exceptions, so we invoke `exit` to set the status code
          fatal("Exiting Kafka due to fatal exception during startup.", e)
          Exit.exit(1)
      }

      server.awaitShutdown()
    }
    catch {
      case e: Throwable =>
        fatal("Exiting Kafka due to fatal exception", e)
        Exit.exit(1)
    }
    Exit.exit(0)
  }

  private def buildServer(props: Properties): Server = {
    val config = KafkaConfig.fromProps(props, false)
    if (config.requiresZookeeper) {
      new KafkaServer(
        config,
        Time.SYSTEM,
        threadNamePrefix = None,
        enableForwarding = false
      )
    } else {
      new KafkaRaftServer(
        config,
        Time.SYSTEM,
        threadNamePrefix = None
      )
    }
  }
}
```
Raft
```scala
class KafkaRaftServer(
                       config: KafkaConfig,
                       time: Time,
                       threadNamePrefix: Option[String]
                     ) extends Server with Logging {
  override def startup(): Unit = {
    Mx4jLoader.maybeLoad()
    // Note that we startup `RaftManager` first so that the controller and broker
    // can register listeners during initialization.
    raftManager.startup()
    controller.foreach(_.startup())
    broker.foreach(_.startup())
    AppInfoParser.registerAppInfo(Server.MetricsPrefix, config.brokerId.toString, metrics, time.milliseconds())
    info(KafkaBroker.STARTED_MESSAGE)
  }
}
```
Server
```scala
class KafkaServer(
                   val config: KafkaConfig,
                   time: Time = Time.SYSTEM,
                   threadNamePrefix: Option[String] = None,
                   enableForwarding: Boolean = false
                 ) extends KafkaBroker with Server {
  override def startup(): Unit = {
    try {
      info("starting")

      if (isShuttingDown.get)
        throw new IllegalStateException("Kafka server is still shutting down, cannot re-start!")

      if (startupComplete.get)
        return

      val canStartup = isStartingUp.compareAndSet(false, true)
      if (canStartup) {
        _brokerState = BrokerState.STARTING

        /* setup zookeeper */
        initZkClient(time)
        configRepository = new ZkConfigRepository(new AdminZkClient(zkClient))

        /* Get or create cluster_id */
        _clusterId = getOrGenerateClusterId(zkClient)
        info(s"Cluster ID = $clusterId")

        /* load metadata */
        val (preloadedBrokerMetadataCheckpoint, initialOfflineDirs) =
          BrokerMetadataCheckpoint.getBrokerMetadataAndOfflineDirs(config.logDirs, ignoreMissing = true)

        if (preloadedBrokerMetadataCheckpoint.version != 0) {
          throw new RuntimeException(s"Found unexpected version in loaded `meta.properties`: " +
            s"$preloadedBrokerMetadataCheckpoint. Zk-based brokers only support version 0 " +
            "(which is implicit when the `version` field is missing).")
        }

        /* check cluster id */
        if (preloadedBrokerMetadataCheckpoint.clusterId.isDefined && preloadedBrokerMetadataCheckpoint.clusterId.get != clusterId)
          throw new InconsistentClusterIdException(
            s"The Cluster ID $clusterId doesn't match stored clusterId ${preloadedBrokerMetadataCheckpoint.clusterId} in meta.properties. " +
              s"The broker is trying to join the wrong cluster. Configured zookeeper.connect may be wrong.")

        /* generate brokerId */
        config.brokerId = getOrGenerateBrokerId(preloadedBrokerMetadataCheckpoint)
        logContext = new LogContext(s"[KafkaServer id=${config.brokerId}] ")
        this.logIdent = logContext.logPrefix

        // initialize dynamic broker configs from ZooKeeper. Any updates made after this will be
        // applied after ZkConfigManager starts.
        config.dynamicConfig.initialize(Some(zkClient))

        /* start scheduler */
        kafkaScheduler = new KafkaScheduler(config.backgroundThreads)
        kafkaScheduler.startup()

        /* create and configure metrics */
        kafkaYammerMetrics = KafkaYammerMetrics.INSTANCE
        kafkaYammerMetrics.configure(config.originals)
        metrics = Server.initializeMetrics(config, time, clusterId)

        /* register broker metrics */
        _brokerTopicStats = new BrokerTopicStats

        quotaManagers = QuotaFactory.instantiate(config, metrics, time, threadNamePrefix.getOrElse(""))
        KafkaBroker.notifyClusterListeners(clusterId, kafkaMetricsReporters ++ metrics.reporters.asScala)

        logDirFailureChannel = new LogDirFailureChannel(config.logDirs.size)

        /* start log manager */
        _logManager = LogManager(
          config,
          initialOfflineDirs,
          configRepository,
          kafkaScheduler,
          time,
          brokerTopicStats,
          logDirFailureChannel,
          config.usesTopicId)
        _brokerState = BrokerState.RECOVERY
        logManager.startup(zkClient.getAllTopicsInCluster())

        metadataCache = MetadataCache.zkMetadataCache(config.brokerId, config.interBrokerProtocolVersion, brokerFeatures)
        val controllerNodeProvider = MetadataCacheControllerNodeProvider(config, metadataCache)

        /* initialize feature change listener */
        _featureChangeListener = new FinalizedFeatureChangeListener(metadataCache, _zkClient)
        if (config.isFeatureVersioningSupported) {
          _featureChangeListener.initOrThrow(config.zkConnectionTimeoutMs)
        }

        // Enable delegation token cache for all SCRAM mechanisms to simplify dynamic update.
        // This keeps the cache up-to-date if new SCRAM mechanisms are enabled dynamically.
        tokenCache = new DelegationTokenCache(ScramMechanism.mechanismNames)
        credentialProvider = new CredentialProvider(ScramMechanism.mechanismNames, tokenCache)

        clientToControllerChannelManager = BrokerToControllerChannelManager(
          controllerNodeProvider = controllerNodeProvider,
          time = time,
          metrics = metrics,
          config = config,
          channelName = "forwarding",
          threadNamePrefix = threadNamePrefix,
          retryTimeoutMs = config.requestTimeoutMs.longValue
        )
        clientToControllerChannelManager.start()

        /* start forwarding manager */
        var autoTopicCreationChannel = Option.empty[BrokerToControllerChannelManager]
        if (enableForwarding) {
          this.forwardingManager = Some(ForwardingManager(clientToControllerChannelManager))
          autoTopicCreationChannel = Some(clientToControllerChannelManager)
        }

        val apiVersionManager = ApiVersionManager(
          ListenerType.ZK_BROKER,
          config,
          forwardingManager,
          brokerFeatures,
          metadataCache
        )
```
Create and start the socket server acceptor threads so that the bound port is known.
Delay starting processors until the end of the initialization sequence to ensure that credentials have been loaded before processing authentications.

Note that we allow the use of KRaft mode controller APIs when forwarding is enabled so that the Envelope request is exposed. This is only used in testing currently.
```scala
        socketServer = new SocketServer(config, metrics, time, credentialProvider, apiVersionManager)

        // Start alter partition manager based on the IBP version
        alterPartitionManager = if (config.interBrokerProtocolVersion.isAlterPartitionSupported) {
          AlterPartitionManager(
            config = config,
            metadataCache = metadataCache,
            scheduler = kafkaScheduler,
            controllerNodeProvider,
            time = time,
            metrics = metrics,
            threadNamePrefix = threadNamePrefix,
            brokerEpochSupplier = () => kafkaController.brokerEpoch
          )
        } else {
          AlterPartitionManager(kafkaScheduler, time, zkClient)
        }
        alterPartitionManager.start()

        // Start replica manager
        _replicaManager = createReplicaManager(isShuttingDown)
        replicaManager.startup()

        val brokerInfo = createBrokerInfo
        val brokerEpoch = zkClient.registerBroker(brokerInfo)

        // Now that the broker is successfully registered, checkpoint its metadata
        checkpointBrokerMetadata(ZkMetaProperties(clusterId, config.brokerId))

        /* start token manager */
        tokenManager = new DelegationTokenManager(config, tokenCache, time, zkClient)
        tokenManager.startup()

        /* start kafka controller */
        _kafkaController = new KafkaController(config, zkClient, time, metrics, brokerInfo, brokerEpoch, tokenManager, brokerFeatures, metadataCache, threadNamePrefix)
        kafkaController.startup()

        adminManager = new ZkAdminManager(config, metrics, metadataCache, zkClient)

        /* start group coordinator */
        // Hardcode Time.SYSTEM for now as some Streams tests fail otherwise, it would be good to fix the underlying issue
        groupCoordinator = GroupCoordinator(config, replicaManager, Time.SYSTEM, metrics)
        groupCoordinator.startup(() => zkClient.getTopicPartitionCount(Topic.GROUP_METADATA_TOPIC_NAME).getOrElse(config.offsetsTopicPartitions))

        /* create producer ids manager */
        val producerIdManager = if (config.interBrokerProtocolVersion.isAllocateProducerIdsSupported) {
          ProducerIdManager.rpc(
            config.brokerId,
            brokerEpochSupplier = () => kafkaController.brokerEpoch,
            clientToControllerChannelManager,
            config.requestTimeoutMs
          )
        } else {
          ProducerIdManager.zk(config.brokerId, zkClient)
        }
        /* start transaction coordinator, with a separate background thread scheduler for transaction expiration and log loading */
        // Hardcode Time.SYSTEM for now as some Streams tests fail otherwise, it would be good to fix the underlying issue
        transactionCoordinator = TransactionCoordinator(config, replicaManager, new KafkaScheduler(threads = 1, threadNamePrefix = "transaction-log-manager-"),
          () => producerIdManager, metrics, metadataCache, Time.SYSTEM)
        transactionCoordinator.startup(
          () => zkClient.getTopicPartitionCount(Topic.TRANSACTION_STATE_TOPIC_NAME).getOrElse(config.transactionTopicPartitions))

        /* start auto topic creation manager */
        this.autoTopicCreationManager = AutoTopicCreationManager(
          config,
          metadataCache,
          threadNamePrefix,
          autoTopicCreationChannel,
          Some(adminManager),
          Some(kafkaController),
          groupCoordinator,
          transactionCoordinator
        )

        /* Get the authorizer and initialize it if one is specified.*/
        authorizer = config.createNewAuthorizer()
        authorizer.foreach(_.configure(config.originals))
        val authorizerFutures: Map[Endpoint, CompletableFuture[Void]] = authorizer match {
          case Some(authZ) =>
            authZ.start(brokerInfo.broker.toServerInfo(clusterId, config)).asScala.map { case (ep, cs) =>
              ep -> cs.toCompletableFuture
            }
          case None =>
            brokerInfo.broker.endPoints.map { ep =>
              ep.toJava -> CompletableFuture.completedFuture[Void](null)
            }.toMap
        }

        val fetchManager = new FetchManager(Time.SYSTEM,
          new FetchSessionCache(config.maxIncrementalFetchSessionCacheSlots,
            KafkaServer.MIN_INCREMENTAL_FETCH_SESSION_EVICTION_MS))

        /* start processing requests */
        val zkSupport = ZkSupport(adminManager, kafkaController, zkClient, forwardingManager, metadataCache)

        def createKafkaApis(requestChannel: RequestChannel): KafkaApis = new KafkaApis(
          requestChannel = requestChannel,
          metadataSupport = zkSupport,
          replicaManager = replicaManager,
          groupCoordinator = groupCoordinator,
          txnCoordinator = transactionCoordinator,
          autoTopicCreationManager = autoTopicCreationManager,
          brokerId = config.brokerId,
          config = config,
          configRepository = configRepository,
          metadataCache = metadataCache,
          metrics = metrics,
          authorizer = authorizer,
          quotas = quotaManagers,
          fetchManager = fetchManager,
          brokerTopicStats = brokerTopicStats,
          clusterId = clusterId,
          time = time,
          tokenManager = tokenManager,
          apiVersionManager = apiVersionManager)

        dataPlaneRequestProcessor = createKafkaApis(socketServer.dataPlaneRequestChannel)

        dataPlaneRequestHandlerPool = new KafkaRequestHandlerPool(config.brokerId, socketServer.dataPlaneRequestChannel, dataPlaneRequestProcessor, time,
          config.numIoThreads, s"${DataPlaneAcceptor.MetricPrefix}RequestHandlerAvgIdlePercent", DataPlaneAcceptor.ThreadPrefix)

        socketServer.controlPlaneRequestChannelOpt.foreach { controlPlaneRequestChannel =>
          controlPlaneRequestProcessor = createKafkaApis(controlPlaneRequestChannel)
          controlPlaneRequestHandlerPool = new KafkaRequestHandlerPool(config.brokerId, socketServer.controlPlaneRequestChannelOpt.get, controlPlaneRequestProcessor, time,
            1, s"${ControlPlaneAcceptor.MetricPrefix}RequestHandlerAvgIdlePercent", ControlPlaneAcceptor.ThreadPrefix)
        }

        Mx4jLoader.maybeLoad()

        /* Add all reconfigurables for config change notification before starting config handlers */
        config.dynamicConfig.addReconfigurables(this)
        Option(logManager.cleaner).foreach(config.dynamicConfig.addBrokerReconfigurable)

        /* start dynamic config manager */
        dynamicConfigHandlers = Map[String, ConfigHandler](ConfigType.Topic -> new TopicConfigHandler(logManager, config, quotaManagers, Some(kafkaController)),
          ConfigType.Client -> new ClientIdConfigHandler(quotaManagers),
          ConfigType.User -> new UserConfigHandler(quotaManagers, credentialProvider),
          ConfigType.Broker -> new BrokerConfigHandler(config, quotaManagers),
          ConfigType.Ip -> new IpConfigHandler(socketServer.connectionQuotas))

        // Create the config manager. start listening to notifications
        dynamicConfigManager = new ZkConfigManager(zkClient, dynamicConfigHandlers)
        dynamicConfigManager.startup()

        socketServer.enableRequestProcessing(authorizerFutures)

        _brokerState = BrokerState.RUNNING
        shutdownLatch = new CountDownLatch(1)
        startupComplete.set(true)
        isStartingUp.set(false)
        AppInfoParser.registerAppInfo(Server.MetricsPrefix, config.brokerId.toString, metrics, time.milliseconds())
        info("started")
      }
    }
    catch {
      case e: Throwable =>
        fatal("Fatal error during KafkaServer startup. Prepare to shutdown", e)
        isStartingUp.set(false)
        shutdown()
        throw e
    }
  }
}
```


ZkAdminManager#createTopics



Create topics and wait until the topics have been completely created.
The callback function will be triggered either when timeout, error or the topics are created.

```scala
  def createTopics(timeout: Int,
                   validateOnly: Boolean,
                   toCreate: Map[String, CreatableTopic],
                   includeConfigsAndMetadata: Map[String, CreatableTopicResult],
                   controllerMutationQuota: ControllerMutationQuota,
                   responseCallback: Map[String, ApiError] => Unit): Unit = {

    // 1. map over topics creating assignment and calling zookeeper
    val brokers = metadataCache.getAliveBrokers()
    val metadata = toCreate.values.map(topic =>
      try {
        if (metadataCache.contains(topic.name))
          throw new TopicExistsException(s"Topic '${topic.name}' already exists.")

        val nullConfigs = topic.configs.asScala.filter(_.value == null).map(_.name)
        if (nullConfigs.nonEmpty)
          throw new InvalidConfigurationException(s"Null value not supported for topic configs: ${nullConfigs.mkString(",")}")

        if ((topic.numPartitions != NO_NUM_PARTITIONS || topic.replicationFactor != NO_REPLICATION_FACTOR)
            && !topic.assignments().isEmpty) {
          throw new InvalidRequestException("Both numPartitions or replicationFactor and replicasAssignments were set. " +
            "Both cannot be used at the same time.")
        }

        val resolvedNumPartitions = if (topic.numPartitions == NO_NUM_PARTITIONS)
          defaultNumPartitions else topic.numPartitions
        val resolvedReplicationFactor = if (topic.replicationFactor == NO_REPLICATION_FACTOR)
          defaultReplicationFactor else topic.replicationFactor

        val assignments = if (topic.assignments.isEmpty) {
          AdminUtils.assignReplicasToBrokers(
            brokers, resolvedNumPartitions, resolvedReplicationFactor)
        } else {
          val assignments = new mutable.HashMap[Int, Seq[Int]]
          // Note: we don't check that replicaAssignment contains unknown brokers - unlike in add-partitions case,
          // this follows the existing logic in TopicCommand
          topic.assignments.forEach { assignment =>
            assignments(assignment.partitionIndex) = assignment.brokerIds.asScala.map(a => a: Int)
          }
          assignments
        }
        trace(s"Assignments for topic $topic are $assignments ")

        val configs = new Properties()
        topic.configs.forEach(entry => configs.setProperty(entry.name, entry.value))
        adminZkClient.validateTopicCreate(topic.name, assignments, configs)
        validateTopicCreatePolicy(topic, resolvedNumPartitions, resolvedReplicationFactor, assignments)

        // For responses with DescribeConfigs permission, populate metadata and configs. It is
        // safe to populate it before creating the topic because the values are unset if the
        // creation fails.
        maybePopulateMetadataAndConfigs(includeConfigsAndMetadata, topic.name, configs, assignments)

        if (validateOnly) {
          CreatePartitionsMetadata(topic.name, assignments.keySet)
        } else {
          controllerMutationQuota.record(assignments.size)
          adminZkClient.createTopicWithAssignment(topic.name, configs, assignments, validate = false, config.usesTopicId)
          populateIds(includeConfigsAndMetadata, topic.name)
          CreatePartitionsMetadata(topic.name, assignments.keySet)
        }
      } catch {
        // Log client errors at a lower level than unexpected exceptions
        case e: TopicExistsException =>
          debug(s"Topic creation failed since topic '${topic.name}' already exists.", e)
          CreatePartitionsMetadata(topic.name, e)
        case e: ThrottlingQuotaExceededException =>
          debug(s"Topic creation not allowed because quota is violated. Delay time: ${e.throttleTimeMs}")
          CreatePartitionsMetadata(topic.name, e)
        case e: ApiException =>
          info(s"Error processing create topic request $topic", e)
          CreatePartitionsMetadata(topic.name, e)
        case e: ConfigException =>
          info(s"Error processing create topic request $topic", e)
          CreatePartitionsMetadata(topic.name, new InvalidConfigurationException(e.getMessage, e.getCause))
        case e: Throwable =>
          error(s"Error processing create topic request $topic", e)
          CreatePartitionsMetadata(topic.name, e)
      }).toBuffer

    // 2. if timeout <= 0, validateOnly or no topics can proceed return immediately
    if (timeout <= 0 || validateOnly || !metadata.exists(_.error.is(Errors.NONE))) {
      val results = metadata.map { createTopicMetadata =>
        // ignore topics that already have errors
        if (createTopicMetadata.error.isSuccess && !validateOnly) {
          (createTopicMetadata.topic, new ApiError(Errors.REQUEST_TIMED_OUT, null))
        } else {
          (createTopicMetadata.topic, createTopicMetadata.error)
        }
      }.toMap
      responseCallback(results)
    } else {
      // 3. else pass the assignments and errors to the delayed operation and set the keys
      val delayedCreate = new DelayedCreatePartitions(timeout, metadata, this,
        responseCallback)
      val delayedCreateKeys = toCreate.values.map(topic => TopicKey(topic.name)).toBuffer
      // try to complete the request immediately, otherwise put it into the purgatory
      topicPurgatory.tryCompleteElseWatch(delayedCreate, delayedCreateKeys)
    }
  }
```
AdminUtils#assignReplicasToBrokersRackAware

```scala
  
  private def assignReplicasToBrokersRackAware(nPartitions: Int,
                                               replicationFactor: Int,
                                               brokerMetadatas: Iterable[BrokerMetadata],
                                               fixedStartIndex: Int,
                                               startPartitionId: Int): Map[Int, Seq[Int]] = {
    val brokerRackMap = brokerMetadatas.collect { case BrokerMetadata(id, Some(rack)) =>
      id -> rack
    }.toMap
    val numRacks = brokerRackMap.values.toSet.size
    val arrangedBrokerList = getRackAlternatedBrokerList(brokerRackMap)
    val numBrokers = arrangedBrokerList.size
    val ret = mutable.Map[Int, Seq[Int]]()
    val startIndex = if (fixedStartIndex >= 0) fixedStartIndex else rand.nextInt(arrangedBrokerList.size)
    var currentPartitionId = math.max(0, startPartitionId)
    var nextReplicaShift = if (fixedStartIndex >= 0) fixedStartIndex else rand.nextInt(arrangedBrokerList.size)
    for (_ <- 0 until nPartitions) {
      if (currentPartitionId > 0 && (currentPartitionId % arrangedBrokerList.size == 0))
        nextReplicaShift += 1
      val firstReplicaIndex = (currentPartitionId + startIndex) % arrangedBrokerList.size
      val leader = arrangedBrokerList(firstReplicaIndex)
      val replicaBuffer = mutable.ArrayBuffer(leader)
      val racksWithReplicas = mutable.Set(brokerRackMap(leader))
      val brokersWithReplicas = mutable.Set(leader)
      var k = 0
      for (_ <- 0 until replicationFactor - 1) {
        var done = false
        while (!done) {
          val broker = arrangedBrokerList(replicaIndex(firstReplicaIndex, nextReplicaShift * numRacks, k, arrangedBrokerList.size))
          val rack = brokerRackMap(broker)
          // Skip this broker if
          // 1. there is already a broker in the same rack that has assigned a replica AND there is one or more racks
          //    that do not have any replica, or
          // 2. the broker has already assigned a replica AND there is one or more brokers that do not have replica assigned
          if ((!racksWithReplicas.contains(rack) || racksWithReplicas.size == numRacks)
              && (!brokersWithReplicas.contains(broker) || brokersWithReplicas.size == numBrokers)) {
            replicaBuffer += broker
            racksWithReplicas += rack
            brokersWithReplicas += broker
            done = true
          }
          k += 1
        }
      }
      ret.put(currentPartitionId, replicaBuffer)
      currentPartitionId += 1
    }
    ret
  }

```
replicaIndex

```scala
  private def replicaIndex(firstReplicaIndex: Int, secondReplicaShift: Int, replicaIndex: Int, nBrokers: Int): Int = {
    val shift = 1 + (secondReplicaShift + replicaIndex) % (nBrokers - 1)
    (firstReplicaIndex + shift) % nBrokers
  }
```

AdminZkClient
```scala
  def createTopic(topic: String,
                  partitions: Int,
                  replicationFactor: Int,
                  topicConfig: Properties = new Properties,
                  rackAwareMode: RackAwareMode = RackAwareMode.Enforced,
                  usesTopicId: Boolean = false): Unit = {
    val brokerMetadatas = getBrokerMetadatas(rackAwareMode)
    val replicaAssignment = AdminUtils.assignReplicasToBrokers(brokerMetadatas, partitions, replicationFactor)
    createTopicWithAssignment(topic, topicConfig, replicaAssignment, usesTopicId = usesTopicId)
  }
```

### ISR



## Controller

It is also important to optimize the leadership election process as that is the critical window of unavailability.
A naive implementation of leader election would end up running an election per partition for all partitions a node hosted when that node failed.
As discussed above in the section on replication, Kafka clusters have a special role known as the "controller" which is responsible for managing the registration of brokers.
If the controller detects the failure of a broker, it is responsible for electing one of the remaining members of the ISR to serve as the new leader.
The result is that we are able to batch together many of the required leadership change notifications which makes the election process far cheaper and faster for a large number of partitions.
If the controller itself fails, then another controller will be elected.

QuorumController implements the main logic of the KRaft (Kafka Raft Metadata) mode controller.
The node which is the leader of the metadata log becomes the active controller.
All other nodes remain in standby mode. Standby controllers cannot create new metadata log entries.
They just replay the metadata log entries that the current active controller has created.
The QuorumController is **single-threaded**. A single event handler thread performs most operations.
This avoids the need for complex locking.
The controller exposes an *asynchronous, futures-based API* to the world.
This reflects the fact that the controller may have several operations in progress at any given point.
The future associated with each operation will not be completed until the results of the operation have been made durable to the metadata log.

1. Register Brokers
2. Register Topics
3. load Balance

### quorum replace zookeeper

why

1. 强依赖 维护困难
2. Zookeeper CP 影响性能

[KIP-500: Replace ZooKeeper with a Self-Managed Metadata Quorum](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum)

We would like to remove this dependency on ZooKeeper.
This will enable us to manage metadata in a more scalable and robust way, enabling support for more partitions.
It will also simplify the deployment and configuration of Kafka.

#### Metadata as an Event Log

We often talk about the benefits of managing state as a stream of events.
A single number, the offset, describes a consumer's position in the stream.
Multiple consumers can quickly catch up to the latest state simply by replaying all the events newer than their current offset.
The log establishes a clear ordering between events, and ensures that the consumers always move along a single timeline.

However, although our users enjoy these benefits, Kafka itself has been left out.  We treat changes to metadata as isolated changes with no relationship to each other.
When the controller pushes out state change notifications (such as LeaderAndIsrRequest) to other brokers in the cluster, it is possible for brokers to get some of the changes, but not all.
Although the controller retries several times, it eventually give up.  This can leave brokers in a divergent state.

Worse still, although ZooKeeper is the store of record, the state in ZooKeeper often doesn't match the state that is held in memory in the controller.
For example, when a partition leader changes its ISR in ZK, the controller will typically not learn about these changes for many seconds.
There is no generic way for the controller to follow the ZooKeeper event log.
Although the controller can set one-shot watches, the number of watches is limited for performance reasons.
When a watch triggers, it doesn't tell the controller the current state-- only that the state has changed.
By the time the controller re-reads the znode and sets up a new watch, the state may have changed from what it was when the watch originally fired.
If there is no watch set, the controller may not learn about the change at all.  In some cases, restarting the controller is the only way to resolve the discrepancy.

Rather than being stored in a separate system, metadata should be stored in Kafka itself.  This will avoid all the problems associated with discrepancies between the controller state and the Zookeeper state.
Rather than pushing out notifications to brokers, brokers should simply consume metadata events from the event log.  This ensures that metadata changes will always arrive in the same order.
Brokers will be able to store metadata locally in a file.  When they start up, they will only need to read what has changed from the controller, not the full state.
This will let us support more partitions with less CPU consumption.

#### The Controller Quorum

The controller nodes comprise a Raft quorum which manages the metadata log.  This log contains information about each change to the cluster metadata.  Everything that is currently stored in ZooKeeper, such as topics, partitions, ISRs, configurations, and so on, will be stored in this log.

Using the Raft algorithm, the controller nodes will elect a leader from amongst themselves, without relying on any external system.  The leader of the metadata log is called the active controller.  The active controller handles all RPCs made from the brokers.  The follower controllers replicate the data which is written to the active controller, and serve as hot standbys if the active controller should fail.  Because the controllers will now all track the latest state, controller failover will not require a lengthy reloading period where we transfer all the state to the new controller.

Just like ZooKeeper, Raft requires a majority of nodes to be running in order to continue running.  Therefore, a three-node controller cluster can survive one failure.  A five-node controller cluster can survive two failures, and so on.

Periodically, the controllers will write out a snapshot of the metadata to disk.  While this is conceptually similar to compaction, the code path will be a bit different because we can simply read the state from memory rather than re-reading the log from disk.

#### Broker Metadata Management

Instead of the controller pushing out updates to the other brokers, those brokers will fetch updates from the active controller via the new MetadataFetch API.

A MetadataFetch is similar to a fetch request.  Just like with a fetch request, the broker will track the offset of the last updates it fetched, and only request newer updates from the active controller.

The broker will persist the metadata it fetched to disk.  
This will allow the broker to start up very quickly, even if there are hundreds of thousands or even millions of partitions.
(Note that since this persistence is an optimization, we can leave it out of the first version, if it makes development easier.)

Most of the time, the broker should only need to fetch the deltas, not the full state.  
However, if the broker is too far behind the active controller, or if the broker has no cached metadata at all, the controller will send a full metadata image rather than a series of deltas.



## Membership



### ZooKeeper





### KRaft



## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)