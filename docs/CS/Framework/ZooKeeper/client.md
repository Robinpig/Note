## Introduction




```java
class SendThread extends ZooKeeperThread {
    private void startConnect(InetSocketAddress addr) throws IOException {
        // initializing it for new connection
        saslLoginFailed = false;
        if (!isFirstConnect) {
            try {
                Thread.sleep(ThreadLocalRandom.current().nextLong(1000));
            } catch (InterruptedException e) {
                LOG.warn("Unexpected exception", e);
            }
        }
        changeZkState(States.CONNECTING);

        String hostPort = addr.getHostString() + ":" + addr.getPort();
        MDC.put("myid", hostPort);
        setName(getName().replaceAll("\\(.*\\)", "(" + hostPort + ")"));
        if (clientConfig.isSaslClientEnabled()) {
            try {
                zooKeeperSaslClient = new ZooKeeperSaslClient(
                        SaslServerPrincipal.getServerPrincipal(addr, clientConfig), clientConfig, loginRef);
            } catch (LoginException e) {
                // An authentication error occurred when the SASL client tried to initialize:
                // for Kerberos this means that the client failed to authenticate with the KDC.
                // This is different from an authentication error that occurs during communication
                // with the Zookeeper server, which is handled below.
                LOG.warn(
                        "SASL configuration failed. "
                                + "Will continue connection to Zookeeper server without "
                                + "SASL authentication, if Zookeeper server allows it.", e);
                eventThread.queueEvent(new WatchedEvent(Watcher.Event.EventType.None, Watcher.Event.KeeperState.AuthFailed, null));
                saslLoginFailed = true;
            }
        }
        logStartConnect(addr);

        clientCnxnSocket.connect(addr);
    }
}
```
ClientCnxnSocketNIO

```java
@Override
void connect(InetSocketAddress addr) throws IOException {
    SocketChannel sock = createSock();
    try {
        registerAndConnect(sock, addr);
    } catch (UnresolvedAddressException | UnsupportedAddressTypeException | SecurityException | IOException e) {
        LOG.error("Unable to open socket to {}", addr);
        sock.close();
        throw e;
    }
    initialized = false;

    /*
     * Reset incomingBuffer
     */
    lenBuffer.clear();
    incomingBuffer = lenBuffer;
}


    SocketChannel createSock() throws IOException {
        SocketChannel sock;
        sock = SocketChannel.open();
        sock.configureBlocking(false);
        sock.socket().setSoLinger(false, -1);
        sock.socket().setTcpNoDelay(true);
        return sock;
    }
```


## Links

- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
