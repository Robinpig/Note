## Introduction


The network server for kafka. Now application specific code here, just general network server stuff.
<br>
The classes Receive and Send encapsulate the incoming and outgoing transmission of bytes. 
A Handler is a mapping between a Receive and a Send, and represents the users hook to add logic for mapping requests to actual processing code.
Any uncaught exceptions in the reading or writing of the transmissions will result in the server logging an error and closing the offending socket. 
As a result it is the duty of the Handler implementation to catch and serialize any application-level errors that should be sent to the client.
<br>
This slightly lower-level interface that models sending and receiving rather than requests and responses is necessary in order to allow the send or receive to be overridden with a non-user-space writing of bytes using FileChannel.transferTo.

The sendfile implementation is done by giving the MessageSet interface a writeTo method. 
This allows the file-backed message set to use the more efficient transferTo implementation instead of an in-process buffered write.
The threading model is a single acceptor thread and N processor threads which handle a fixed number of connections each.
```java
/**
 *                                           Sender
 *                                             |
 *                                            \|/
 *  ClientRequest/ClientResponse        NetworkClient
 *      
 *  Send/Receive   kafka.Selector          KafkaChannel    
 *
 *  Buffer          Selector                Channel
 *
 *
 */


```

## NetworkClient

A network client for asynchronous request/response network i/o. This is an internal class used to implement the user-facing producer and consumer clients.
This class is not thread-safe!

### Connect

```java
public class NetworkClient implements KafkaClient {
    public boolean ready(@NotEmpty Node node, long now) {

        if (isReady(node, now))
            return true;

        if (connectionStates.canConnect(node.idString(), now))
            // if we are interested in sending to a node and we don't have a connection to it, initiate one
            initiateConnect(node, now);

        return false;
    }

    private void initiateConnect(Node node, long now) {
        String nodeConnectionId = node.idString();
        try {
            connectionStates.connecting(nodeConnectionId, now, node.host());
            InetAddress address = connectionStates.currentAddress(nodeConnectionId);
            selector.connect(nodeConnectionId,
                    new InetSocketAddress(address, node.port()),
                    this.socketSendBuffer,
                    this.socketReceiveBuffer);
        } catch (IOException e) {
            // Attempt failed, we'll try again after the backoff
            connectionStates.disconnected(nodeConnectionId, now);
            // Notify metadata updater of the connection failure
            metadataUpdater.handleServerDisconnect(now, nodeConnectionId, Optional.empty());
        }
    }
}
```
Begin connecting to the given address and add the connection to this nioSelector associated with the given id number.
Note that this call only initiates the connection, which will be completed on a future poll(long) call. Check connected() to see which (if any) connections have completed after a given poll call.

immediatelyConnectedKeys see [JDK NIO](/docs/CS/Java/JDK/IO/IO.md?id=Connect) and will finishConnect
```java
public void connect(String id, InetSocketAddress address, int sendBufferSize, int receiveBufferSize) throws IOException {
        ensureNotRegistered(id);
        SocketChannel socketChannel = SocketChannel.open();
        SelectionKey key = null;
        try {
            configureSocketChannel(socketChannel, sendBufferSize, receiveBufferSize);
            boolean connected = doConnect(socketChannel, address);
            key = registerChannel(id, socketChannel, SelectionKey.OP_CONNECT);

            if (connected) {
                // OP_CONNECT won't trigger for immediately connected channels
                immediatelyConnectedKeys.add(key);
                key.interestOps(0);
            }
        } catch (IOException | RuntimeException e) {
            if (key != null)
                immediatelyConnectedKeys.remove(key);
            channels.remove(id);
            socketChannel.close();
            throw e;
        }
    }
```

#### finishConnect

```java
    /**
     * Marks the beginning of a finishConnect operation that might block.
     */
    private void beginFinishConnect(boolean blocking) throws ClosedChannelException {
        if (blocking) {
            // set hook for Thread.interrupt
            begin();
        }
        synchronized (stateLock) {
            ensureOpen();
            if (state != ST_CONNECTIONPENDING)
                throw new NoConnectionPendingException();
            if (blocking) {
                // record thread so it can be signalled if needed
                readerThread = NativeThread.current();
            }
        }
    }

    /**
     * Marks the end of a finishConnect operation that may have blocked.
     */
    private void endFinishConnect(boolean blocking, boolean completed)
        throws IOException
    {
        endRead(blocking, completed);

        if (completed) {
            synchronized (stateLock) {
                if (state == ST_CONNECTIONPENDING) {
                    localAddress = Net.localAddress(fd);
                    state = ST_CONNECTED;
                }
            }
        }
    }

    @Override
    public boolean finishConnect() throws IOException {
        try {
            readLock.lock();
            try {
                writeLock.lock();
                try {
                    // no-op if already connected
                    if (isConnected())
                        return true;

                    boolean blocking = isBlocking();
                    boolean connected = false;
                    try {
                        beginFinishConnect(blocking);
                        boolean polled = Net.pollConnectNow(fd);
                        if (blocking) {
                            while (!polled && isOpen()) {
                                park(Net.POLLOUT);
                                polled = Net.pollConnectNow(fd);
                            }
                        }
                        connected = polled && isOpen();
                    } finally {
                        endFinishConnect(blocking, connected);
                    }
                    assert (blocking && connected) ^ !blocking;
                    return connected;
                } finally {
                    writeLock.unlock();
                }
            } finally {
                readLock.unlock();
            }
        } catch (IOException ioe) {
            // connect failed, close the channel
            close();
            throw SocketExceptions.of(ioe, remoteAddress);
        }
    }
```



### send

```java
public class NetworkClient implements KafkaClient {
    public void send(ClientRequest request, long now) {
        doSend(request, false, now);
    }

    private void doSend(ClientRequest clientRequest, boolean isInternalRequest, long now) {
        ensureActive();
        String nodeId = clientRequest.destination();
        if (!isInternalRequest) {
            // If this request came from outside the NetworkClient, validate
            // that we can send data.  If the request is internal, we trust
            // that internal code has done this validation.  Validation
            // will be slightly different for some internal requests (for
            // example, ApiVersionsRequests can be sent prior to being in
            // READY state.)
            if (!canSendRequest(nodeId, now))
                throw new IllegalStateException("Attempt to send a request to node " + nodeId + " which is not ready.");
        }
        AbstractRequest.Builder<?> builder = clientRequest.requestBuilder();
        try {
            NodeApiVersions versionInfo = apiVersions.get(nodeId);
            short version;
            // Note: if versionInfo is null, we have no server version information. This would be
            // the case when sending the initial ApiVersionRequest which fetches the version
            // information itself.  It is also the case when discoverBrokerVersions is set to false.
            if (versionInfo == null) {
                version = builder.latestAllowedVersion();
            } else {
                version = versionInfo.latestUsableVersion(clientRequest.apiKey(), builder.oldestAllowedVersion(),
                        builder.latestAllowedVersion());
            }
            // The call to build may also throw UnsupportedVersionException, if there are essential
            // fields that cannot be represented in the chosen version.
            doSend(clientRequest, isInternalRequest, now, builder.build(version));
        } catch (UnsupportedVersionException unsupportedVersionException) {
            // If the version is not supported, skip sending the request over the wire.
            // Instead, simply add it to the local queue of aborted requests.
            ClientResponse clientResponse = new ClientResponse(clientRequest.makeHeader(builder.latestAllowedVersion()),
                    clientRequest.callback(), clientRequest.destination(), now, now,
                    false, unsupportedVersionException, null, null);

            if (!isInternalRequest)
                abortedSends.add(clientResponse);
            else if (clientRequest.apiKey() == ApiKeys.METADATA)
                metadataUpdater.handleFailedRequest(now, Optional.of(unsupportedVersionException));
        }
    }

    private void doSend(ClientRequest clientRequest, boolean isInternalRequest, long now, AbstractRequest request) {
        String destination = clientRequest.destination();
        RequestHeader header = clientRequest.makeHeader(request.version());
        Send send = request.toSend(header);
        InFlightRequest inFlightRequest = new InFlightRequest(
                clientRequest,
                header,
                isInternalRequest,
                request,
                send,
                now);
        this.inFlightRequests.add(inFlightRequest);
        selector.send(new NetworkSend(clientRequest.destination(), send));
    }
}
```

Queue the given request for sending in the subsequent poll(long) calls

`Channel.setSend()`
```java
    public void send(NetworkSend send) {
        String connectionId = send.destinationId();
        KafkaChannel channel = openOrClosingChannelOrFail(connectionId);
        if (closingChannels.containsKey(connectionId)) {
            // ensure notification via `disconnected`, leave channel in the state in which closing was triggered
            this.failedSends.add(connectionId);
        } else {
            try {
                channel.setSend(send);
            } catch (Exception e) {
                // update the state for consistency, the channel will be discarded after `close`
                channel.state(ChannelState.FAILED_SEND);
                // ensure notification via `disconnected` when `failedSends` are processed in the next poll
                this.failedSends.add(connectionId);
                close(channel, CloseMode.DISCARD_NO_NOTIFY);
                if (!(e instanceof CancelledKeyException)) {
                    throw e;
                }
            }
        }
    }
```


### poll

Do actual reads and writes to sockets.

call [Selector.poll()](/docs/CS/MQ/Kafka/Network.md?id=Selector)
```java
public class NetworkClient implements KafkaClient {
    @Override
    public List<ClientResponse> poll(long timeout, long now) {
        ensureActive();

        if (!abortedSends.isEmpty()) {
            // If there are aborted sends because of unsupported version exceptions or disconnects,
            // handle them immediately without waiting for Selector#poll.
            List<ClientResponse> responses = new ArrayList<>();
            handleAbortedSends(responses);
            completeResponses(responses);
            return responses;
        }

        long metadataTimeout = metadataUpdater.maybeUpdate(now);
        try {
            this.selector.poll(Utils.min(timeout, metadataTimeout, defaultRequestTimeoutMs));
        } catch (IOException e) {
            log.error("Unexpected error during I/O", e);
        }

        // process completed actions
        long updatedNow = this.time.milliseconds();
        List<ClientResponse> responses = new ArrayList<>();
        handleCompletedSends(responses, updatedNow);
        handleCompletedReceives(responses, updatedNow);
        handleDisconnections(responses, updatedNow);
        handleConnections();
        handleInitiateApiVersionRequests(updatedNow);
        handleTimedOutConnections(responses, updatedNow);
        handleTimedOutRequests(responses, updatedNow);
        completeResponses(responses);

        return responses;
    }
}
```
Handle any completed request send. In particular if no response is expected consider the request complete.

```java
public class NetworkClient implements KafkaClient {
    private void handleCompletedSends(List<ClientResponse> responses, long now) {
        // if no response is expected then when the send is completed, return it
        for (NetworkSend send : this.selector.completedSends()) {
            InFlightRequest request = this.inFlightRequests.lastSent(send.destinationId());
            if (!request.expectResponse) {
                this.inFlightRequests.completeLastSent(send.destinationId());
                responses.add(request.completed(null, now));
            }
        }
    }
}
```


```java
public class NetworkClient implements KafkaClient {
    private void handleCompletedReceives(List<ClientResponse> responses, long now) {
        for (NetworkReceive receive : this.selector.completedReceives()) {
            String source = receive.source();
            InFlightRequest req = inFlightRequests.completeNext(source);

            AbstractResponse response = parseResponse(receive.payload(), req.header);
            if (throttleTimeSensor != null)
                throttleTimeSensor.record(response.throttleTimeMs(), now);

            // If the received response includes a throttle delay, throttle the connection.
            maybeThrottle(response, req.header.apiVersion(), req.destination, now);
            if (req.isInternalRequest && response instanceof MetadataResponse)
                metadataUpdater.handleSuccessfulResponse(req.header, now, (MetadataResponse) response);
            else if (req.isInternalRequest && response instanceof ApiVersionsResponse)
                handleApiVersionsResponse(responses, req, now, (ApiVersionsResponse) response);
            else
                responses.add(req.completed(response, now));
        }
    }
}
```


### KafkaChannel


```java
 public KafkaChannel(String id, TransportLayer transportLayer, Supplier<Authenticator> authenticatorCreator,
                        int maxReceiveSize, MemoryPool memoryPool, ChannelMetadataRegistry metadataRegistry) {
        this.id = id;
        this.transportLayer = transportLayer;
        this.authenticatorCreator = authenticatorCreator;
        this.authenticator = authenticatorCreator.get();
        this.networkThreadTimeNanos = 0L;
        this.maxReceiveSize = maxReceiveSize;
        this.memoryPool = memoryPool;
        this.metadataRegistry = metadataRegistry;
        this.disconnected = false;
        this.muteState = ChannelMuteState.NOT_MUTED;
        this.state = ChannelState.NOT_CONNECTED;
    }
```


```java
protected SelectionKey registerChannel(String id, SocketChannel socketChannel, int interestedOps) throws IOException {
        SelectionKey key = socketChannel.register(nioSelector, interestedOps);
        KafkaChannel channel = buildAndAttachKafkaChannel(socketChannel, id, key);
        this.channels.put(id, channel);
        if (idleExpiryManager != null)
        idleExpiryManager.update(channel.id(), time.nanoseconds());
        return key;
        }

private KafkaChannel buildAndAttachKafkaChannel(SocketChannel socketChannel, String id, SelectionKey key) throws IOException {
        try {
            KafkaChannel channel = channelBuilder.buildChannel(id, key, maxReceiveSize, memoryPool,
                new SelectorChannelMetadataRegistry());
            key.attach(channel);
            return channel;
        } catch (Exception e) {
            try {
                socketChannel.close();
            } finally {
                key.cancel();
            }
            throw new IOException("Channel could not be created for socket " + socketChannel, e);
        }
    }

public KafkaChannel buildChannel(String id, SelectionKey key, int maxReceiveSize,
                                     MemoryPool memoryPool, ChannelMetadataRegistry metadataRegistry) throws KafkaException {
        try {
            PlaintextTransportLayer transportLayer = buildTransportLayer(key);
            Supplier<Authenticator> authenticatorCreator = () -> new PlaintextAuthenticator(configs, transportLayer, listenerName);
            return buildChannel(id, transportLayer, authenticatorCreator, maxReceiveSize,
                    memoryPool != null ? memoryPool : MemoryPool.NONE, metadataRegistry);
        } catch (Exception e) {
            throw new KafkaException(e);
        }
    }
```

### Selector

Do whatever I/O can be done on each connection without blocking.
This includes completing connections, completing disconnections, initiating new sends, or making progress on in-progress sends or receives.

When this call is completed the user can check for completed sends, receives, connections or disconnects using completedSends(), completedReceives(), connected(), disconnected().
These lists will be cleared at the beginning of each `poll` call and repopulated by the call if there is any completed I/O.

In the "Plaintext" setting, we are using socketChannel to read & write to the network.
But for the "SSL" setting, we encrypt the data before we use socketChannel to write data to the network, and decrypt before we return the responses.
This requires additional buffers to be maintained as we are reading from network, since the data on the wire is encrypted we won't be able to read exact no.of bytes as kafka protocol requires.
We read as many bytes as we can, up to SSLEngine's application buffer size. This means we might be reading additional bytes than the requested size.
If there is no further data to read from socketChannel selector won't invoke that channel and we have additional bytes in the buffer.
To overcome this issue we added "keysWithBufferedRead" map which tracks channels which have data in the SSL buffers.
If there are channels with buffered data that can by processed, we set "timeout" to 0 and process the data even if there is no more data to read from the socket.

Atmost one entry is added to "completedReceives" for a channel in each poll.
This is necessary to guarantee that requests from a channel are processed on the broker in the order they are sent.
Since outstanding requests added by SocketServer to the request queue may be processed by different request handler threads, requests on each channel must be processed one-at-a-time to guarantee ordering.

```java
public class Selector implements Selectable, AutoCloseable {
    public void poll(long timeout) throws IOException {
        if (timeout < 0)
            throw new IllegalArgumentException("timeout should be >= 0");

        boolean madeReadProgressLastCall = madeReadProgressLastPoll;
        clear();

        boolean dataInBuffers = !keysWithBufferedRead.isEmpty();

        if (!immediatelyConnectedKeys.isEmpty() || (madeReadProgressLastCall && dataInBuffers))
            timeout = 0;

        if (!memoryPool.isOutOfMemory() && outOfMemory) {
            //we have recovered from memory pressure. unmute any channel not explicitly muted for other reasons
            for (KafkaChannel channel : channels.values()) {
                if (channel.isInMutableState() && !explicitlyMutedChannels.contains(channel)) {
                    channel.maybeUnmute();
                }
            }
            outOfMemory = false;
        }

        /* check ready keys */
        long startSelect = time.nanoseconds();
        int numReadyKeys = select(timeout);
        long endSelect = time.nanoseconds();
        this.sensors.selectTime.record(endSelect - startSelect, time.milliseconds());

        if (numReadyKeys > 0 || !immediatelyConnectedKeys.isEmpty() || dataInBuffers) {
            Set<SelectionKey> readyKeys = this.nioSelector.selectedKeys();

            // Poll from channels that have buffered data (but nothing more from the underlying socket)
            if (dataInBuffers) {
                keysWithBufferedRead.removeAll(readyKeys); //so no channel gets polled twice
                Set<SelectionKey> toPoll = keysWithBufferedRead;
                keysWithBufferedRead = new HashSet<>(); //poll() calls will repopulate if needed
                pollSelectionKeys(toPoll, false, endSelect);
            }

            // Poll from channels where the underlying socket has more data
            pollSelectionKeys(readyKeys, false, endSelect);
            // Clear all selected keys so that they are included in the ready count for the next select
            readyKeys.clear();

            pollSelectionKeys(immediatelyConnectedKeys, true, endSelect);
            immediatelyConnectedKeys.clear();
        } else {
            madeReadProgressLastPoll = true; //no work is also "progress"
        }

        long endIo = time.nanoseconds();
        this.sensors.ioTime.record(endIo - endSelect, time.milliseconds());

        // Close channels that were delayed and are now ready to be closed
        completeDelayedChannelClose(endIo);

        // we use the time at the end of select to ensure that we don't close any connections that
        // have just been processed in pollSelectionKeys
        maybeCloseOldestConnection(endSelect);
    }
}
```


#### pollSelectionKeys

```java
void pollSelectionKeys(Set<SelectionKey> selectionKeys,
                           boolean isImmediatelyConnected,
                           long currentTimeNanos) {
        for (SelectionKey key : determineHandlingOrder(selectionKeys)) {
            KafkaChannel channel = channel(key);
            long channelStartTimeNanos = recordTimePerConnection ? time.nanoseconds() : 0;
            boolean sendFailed = false;
            String nodeId = channel.id();

            // register all per-connection metrics at once
            sensors.maybeRegisterConnectionMetrics(nodeId);
            if (idleExpiryManager != null)
                idleExpiryManager.update(nodeId, currentTimeNanos);

            try {
                /* complete any connections that have finished their handshake (either normally or immediately) */
                if (isImmediatelyConnected || key.isConnectable()) {
                    if (channel.finishConnect()) {
                        this.connected.add(nodeId);
                        this.sensors.connectionCreated.record();

                        SocketChannel socketChannel = (SocketChannel) key.channel();
                        log.debug("Created socket with SO_RCVBUF = {}, SO_SNDBUF = {}, SO_TIMEOUT = {} to node {}",
                                socketChannel.socket().getReceiveBufferSize(),
                                socketChannel.socket().getSendBufferSize(),
                                socketChannel.socket().getSoTimeout(),
                                nodeId);
                    } else {
                        continue;
                    }
                }

                /* if channel is not ready finish prepare */
                if (channel.isConnected() && !channel.ready()) {
                    channel.prepare();
                    if (channel.ready()) {
                        long readyTimeMs = time.milliseconds();
                        boolean isReauthentication = channel.successfulAuthentications() > 1;
                        if (isReauthentication) {
                            sensors.successfulReauthentication.record(1.0, readyTimeMs);
                            if (channel.reauthenticationLatencyMs() == null)
                                log.warn(
                                    "Should never happen: re-authentication latency for a re-authenticated channel was null; continuing...");
                            else
                                sensors.reauthenticationLatency
                                    .record(channel.reauthenticationLatencyMs().doubleValue(), readyTimeMs);
                        } else {
                            sensors.successfulAuthentication.record(1.0, readyTimeMs);
                            if (!channel.connectedClientSupportsReauthentication())
                                sensors.successfulAuthenticationNoReauth.record(1.0, readyTimeMs);
                        }
                        log.debug("Successfully {}authenticated with {}", isReauthentication ?
                            "re-" : "", channel.socketDescription());
                    }
                }
                if (channel.ready() && channel.state() == ChannelState.NOT_CONNECTED)
                    channel.state(ChannelState.READY);
                Optional<NetworkReceive> responseReceivedDuringReauthentication = channel.pollResponseReceivedDuringReauthentication();
                responseReceivedDuringReauthentication.ifPresent(receive -> {
                    long currentTimeMs = time.milliseconds();
                    addToCompletedReceives(channel, receive, currentTimeMs);
                });

                //if channel is ready and has bytes to read from socket or buffer, and has no
                //previous completed receive then read from it
                if (channel.ready() && (key.isReadable() || channel.hasBytesBuffered()) && !hasCompletedReceive(channel)
                        && !explicitlyMutedChannels.contains(channel)) {
                    attemptRead(channel);
                }

                if (channel.hasBytesBuffered() && !explicitlyMutedChannels.contains(channel)) {
                    //this channel has bytes enqueued in intermediary buffers that we could not read
                    //(possibly because no memory). it may be the case that the underlying socket will
                    //not come up in the next poll() and so we need to remember this channel for the
                    //next poll call otherwise data may be stuck in said buffers forever. If we attempt
                    //to process buffered data and no progress is made, the channel buffered status is
                    //cleared to avoid the overhead of checking every time.
                    keysWithBufferedRead.add(key);
                }

                /* if channel is ready write to any sockets that have space in their buffer and for which we have data */

                long nowNanos = channelStartTimeNanos != 0 ? channelStartTimeNanos : currentTimeNanos;
                try {
                    attemptWrite(key, channel, nowNanos);
                } catch (Exception e) {
                    sendFailed = true;
                    throw e;
                }

                /* cancel any defunct sockets */
                if (!key.isValid())
                    close(channel, CloseMode.GRACEFUL);

            } catch (Exception e) {
                String desc = String.format("%s (channelId=%s)", channel.socketDescription(), channel.id());
                if (e instanceof IOException) {
                    log.debug("Connection with {} disconnected", desc, e);
                } else if (e instanceof AuthenticationException) {
                    boolean isReauthentication = channel.successfulAuthentications() > 0;
                    if (isReauthentication)
                        sensors.failedReauthentication.record();
                    else
                        sensors.failedAuthentication.record();
                    String exceptionMessage = e.getMessage();
                    if (e instanceof DelayedResponseAuthenticationException)
                        exceptionMessage = e.getCause().getMessage();
                    log.info("Failed {}authentication with {} ({})", isReauthentication ? "re-" : "",
                        desc, exceptionMessage);
                } else {
                    log.warn("Unexpected error from {}; closing connection", desc, e);
                }

                if (e instanceof DelayedResponseAuthenticationException)
                    maybeDelayCloseOnAuthenticationFailure(channel);
                else
                    close(channel, sendFailed ? CloseMode.NOTIFY_ONLY : CloseMode.GRACEFUL);
            } finally {
                maybeRecordTimePerConnection(channel, channelStartTimeNanos);
            }
        }
    }
```
#### attemptWrite

```java
private void attemptWrite(SelectionKey key, KafkaChannel channel, long nowNanos) throws IOException {
        if (channel.hasSend()
                && channel.ready()
                && key.isWritable()
                && !channel.maybeBeginClientReauthentication(() -> nowNanos)) {
            write(channel);
        }
    }

    // package-private for testing
    void write(KafkaChannel channel) throws IOException {
        String nodeId = channel.id();
        long bytesSent = channel.write();
        NetworkSend send = channel.maybeCompleteSend();
        // We may complete the send with bytesSent < 1 if `TransportLayer.hasPendingWrites` was true and `channel.write()`
        // caused the pending writes to be written to the socket channel buffer
        if (bytesSent > 0 || send != null) {
            long currentTimeMs = time.milliseconds();
            if (bytesSent > 0)
                this.sensors.recordBytesSent(nodeId, bytesSent, currentTimeMs);
            if (send != null) {
                this.completedSends.add(send);
                this.sensors.recordCompletedSend(nodeId, send.size(), currentTimeMs);
            }
        }
    }

```


### Buffer


#### Send

```java
public class ByteBufferSend implements Send {

    private final long size;
    protected final ByteBuffer[] buffers;
    private long remaining;
    private boolean pending = false;
}
```

```java
public class KafkaChannel implements AutoCloseable {
    public long write() throws IOException {
        if (send == null)
            return 0;

        midWrite = true;
        return send.writeTo(transportLayer);
    }
}
```

#### NetworkReceive

A size delimited Receive that consists of a 4 byte network-ordered size N followed by N bytes of content
```java
public class NetworkReceive implements Receive {

    private static final ByteBuffer EMPTY_BUFFER = ByteBuffer.allocate(0);

    private final String source;
    private final ByteBuffer size;
    private final int maxSize;
    private final MemoryPool memoryPool;
    private int requestedBufferSize = -1;
    private ByteBuffer buffer;
}
```


```java
public class KafkaChannel implements AutoCloseable {
    private long receive(NetworkReceive receive) throws IOException {
        try {
            return receive.readFrom(transportLayer);
        } catch (SslAuthenticationException e) {
            // With TLSv1.3, post-handshake messages may throw SSLExceptions, which are
            // handled as authentication failures
            String remoteDesc = remoteAddress != null ? remoteAddress.toString() : null;
            state = new ChannelState(ChannelState.State.AUTHENTICATION_FAILED, e, remoteDesc);
            throw e;
        }
    }
}


```

### Partition

```java
public interface Partitioner extends Configurable, Closeable {

    int partition(String topic, Object key, byte[] keyBytes, Object value, byte[] valueBytes, Cluster cluster);
}
```

RoundRobin


The default partitioning strategy:
- If a partition is specified in the record, use it
- If no partition is specified but a key is present choose a partition based on a hash of the key
- If no partition or key is present choose the sticky partition(`ThreadLocalRandom.current().nextInt()`) that changes when the batch is full. See KIP-480 for details about sticky partitioning.

### Topic


See https://kafka.apache.org/documentation/#configuration

```properties
auto.create.topics.enable: false
unclean.leader.election.enable：false
auto.leader.rebalance.enable：false
```


```properties
log.retention.{hour|minutes|ms}: 168
log.retention.bytes：-1
message.max.bytes:
```

JVM 6GB Heap


### KafkaTemplate

```java
public ListenableFuture<SendResult<K, V>> send(String topic, @Nullable V data) {
		ProducerRecord<K, V> producerRecord = new ProducerRecord<>(topic, data);
		return doSend(producerRecord);
	}
```

### Record

Producer compress、Broker storage(also decompress to verify records)、Consumer decompress.

> [!WARNING]
>
> Broker keep the same compression type and same message version(v1 <-> v1, v2 <-> v2) as producers to avoid performance risk.



## NetworkServer

### Reactor

```java
public class NioEchoServer extends Thread {
    private final ServerSocketChannel serverSocketChannel;
    private final List<SocketChannel> newChannels;
    private final List<SocketChannel> socketChannels;
    private final AcceptorThread acceptorThread;
    private final Selector selector;
    private volatile TransferableChannel outputChannel;
    private final CredentialCache credentialCache;
    private final Metrics metrics;
    private volatile int numSent = 0;
    private volatile boolean closeKafkaChannels;
    private final DelegationTokenCache tokenCache;
    private final Time time;

    public NioEchoServer(ListenerName listenerName, SecurityProtocol securityProtocol, AbstractConfig config,
                         String serverHost, ChannelBuilder channelBuilder, CredentialCache credentialCache,
                         int failedAuthenticationDelayMs, Time time, DelegationTokenCache tokenCache) throws Exception {
        super("echoserver");
        setDaemon(true);
        serverSocketChannel = ServerSocketChannel.open();
        serverSocketChannel.configureBlocking(false);
        serverSocketChannel.socket().bind(new InetSocketAddress(serverHost, 0));
        this.port = serverSocketChannel.socket().getLocalPort();
        this.socketChannels = Collections.synchronizedList(new ArrayList<SocketChannel>());
        this.newChannels = Collections.synchronizedList(new ArrayList<SocketChannel>());
        this.credentialCache = credentialCache;
        this.tokenCache = tokenCache;
        if (securityProtocol == SecurityProtocol.SASL_PLAINTEXT || securityProtocol == SecurityProtocol.SASL_SSL) {
            for (String mechanism : ScramMechanism.mechanismNames()) {
                if (credentialCache.cache(mechanism, ScramCredential.class) == null)
                    credentialCache.createCache(mechanism, ScramCredential.class);
            }
        }
        LogContext logContext = new LogContext();
        if (channelBuilder == null)
            channelBuilder = ChannelBuilders.serverChannelBuilder(listenerName, false,
                    securityProtocol, config, credentialCache, tokenCache, time, logContext,
                    () -> ApiVersionsResponse.defaultApiVersionsResponse(ApiMessageType.ListenerType.ZK_BROKER));
        this.metrics = new Metrics();
        this.selector = new Selector(10000, failedAuthenticationDelayMs, metrics, time,
                "MetricGroup", channelBuilder, logContext);
        acceptorThread = new AcceptorThread();
        this.time = time;
    }
}
```

#### Acceptor

```java
private class AcceptorThread extends Thread {
    public AcceptorThread() {
        setName("acceptor");
    }

    @Override
    public void run() {
        java.nio.channels.Selector acceptSelector = null;

        try {
            acceptSelector = java.nio.channels.Selector.open();
            serverSocketChannel.register(acceptSelector, SelectionKey.OP_ACCEPT);
            while (serverSocketChannel.isOpen()) {
                if (acceptSelector.select(1000) > 0) {
                    Iterator<SelectionKey> it = acceptSelector.selectedKeys().iterator();
                    while (it.hasNext()) {
                        SelectionKey key = it.next();
                        if (key.isAcceptable()) {
                            SocketChannel socketChannel = ((ServerSocketChannel) key.channel()).accept();
                            socketChannel.configureBlocking(false);
                            newChannels.add(socketChannel);
                            selector.wakeup();
                        }
                        it.remove();
                    }
                }
            }
        } catch (IOException e) {
            LOG.warn(e.getMessage(), e);
        } finally {
            Utils.closeQuietly(acceptSelector, "acceptSelector");
        }
    }
}
```



```java
public class NioEchoServer extends Thread {
    @Override
    public void run() {
        try {
            acceptorThread.start();
            while (serverSocketChannel.isOpen()) {
                selector.poll(100);
                synchronized (newChannels) {
                    for (SocketChannel socketChannel : newChannels) {
                        String id = id(socketChannel);
                        selector.register(id, socketChannel);
                        socketChannels.add(socketChannel);
                    }
                    newChannels.clear();
                }
                if (closeKafkaChannels) {
                    for (KafkaChannel channel : selector.channels())
                        selector.close(channel.id());
                }

                Collection<NetworkReceive> completedReceives = selector.completedReceives();
                for (NetworkReceive rcv : completedReceives) {
                    KafkaChannel channel = channel(rcv.source());
                    if (!maybeBeginServerReauthentication(channel, rcv, time)) {
                        String channelId = channel.id();
                        selector.mute(channelId);
                        NetworkSend send = new NetworkSend(rcv.source(), ByteBufferSend.sizePrefixed(rcv.payload()));
                        if (outputChannel == null)
                            selector.send(send);
                        else {
                            send.writeTo(outputChannel);
                            selector.unmute(channelId);
                        }
                    }
                }
                for (NetworkSend send : selector.completedSends()) {
                    selector.unmute(send.destinationId());
                    numSent += 1;
                }
            }
        } catch (IOException e) {
            LOG.warn(e.getMessage(), e);
        }
    }
}
```

## Links

- [Apache Kafka](/docs/CS/MQ/Kafka/Kafka.md)