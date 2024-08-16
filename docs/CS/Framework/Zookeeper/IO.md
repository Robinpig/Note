


在QuorumPeerMain::runFromConfig的启动中初始化了Communication layer并设置到QuorumPeer



ServerCnxnFactory cnxnFactory = null;
ServerCnxnFactory secureCnxnFactory = null;

if (config.getClientPortAddress() != null) {
    cnxnFactory = ServerCnxnFactory.createFactory();
    cnxnFactory.configure(config.getClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), false);
}

if (config.getSecureClientPortAddress() != null) {
    secureCnxnFactory = ServerCnxnFactory.createFactory();
    secureCnxnFactory.configure(config.getSecureClientPortAddress(), config.getMaxClientCnxns(), config.getClientPortListenBacklog(), true);
}


quorumPeer.setCnxnFactory(cnxnFactory);
quorumPeer.setSecureCnxnFactory(secureCnxnFactory);


public static ServerCnxnFactory createFactory() throws IOException {
    String serverCnxnFactoryName = System.getProperty(ZOOKEEPER_SERVER_CNXN_FACTORY);
    if (serverCnxnFactoryName == null) {
        serverCnxnFactoryName = NIOServerCnxnFactory.class.getName();
    }
    try {
        ServerCnxnFactory serverCnxnFactory = (ServerCnxnFactory) Class.forName(serverCnxnFactoryName)
                                                                       .getDeclaredConstructor()
                                                                       .newInstance();
        LOG.info(”Using {} as server connection factory“, serverCnxnFactoryName);
        return serverCnxnFactory;
    } catch (Exception e) {
        IOException ioe = new IOException(”Couldn‘t instantiate “ + serverCnxnFactoryName, e);
        throw ioe;
    }
}


Zookeeper作为一个服务器,自然要与客户端进行网络通信,如何高效的与客户端进行通信,让网络IO不成为ZooKeeper的瓶颈是ZooKeeper急需解决的问题,ZooKeeper中使用ServerCnxnFactory管理与客户端的连接,从系统属性zookeeper.serverCnxnFactory中获取配置 其有两个实现, 
- 一个是NIOServerCnxnFactory,使用 Java原生NIO实现 默认实现 不支持ssl
- 一个是NettyServerCnxnFactory,使用 Netty实现 ;

 
> In versions 3.5+, a ZooKeeper server can use Netty instead of NIO (default option) by setting the environment variable zookeeper.serverCnxnFactory to org.apache.zookeeper.server.NettyServerCnxnFactory; for the client, set zookeeper.clientCnxnSocket to org.apache.zookeeper.ClientCnxnSocketNetty.


使用ServerCnxn代表一个客户端与服务端的连接


public class NettyServerCnxnFactory extends ServerCnxnFactory {
    @Override
    public void start() {
        if (listenBacklog != -1) {
            bootstrap.option(ChannelOption.SO_BACKLOG, listenBacklog);
        }
        LOG.info(“binding to port {}”, localAddress);
        parentChannel = bootstrap.bind(localAddress).syncUninterruptibly().channel();
        // Port changes after bind() if the original port was 0, update
        // localAddress to get the real port.
        localAddress = (InetSocketAddress) parentChannel.localAddress();
        LOG.info(“bound to port {}”, getLocalPort());
    }
}



## NIO

NIOServerCnxnFactory implements a multi-threaded ServerCnxnFactory using NIO non-blocking socket calls. Communication between threads is handled via queues. 
- 1 accept thread, which accepts new connections and assigns to a selector thread 
- 1-N selector threads, each of which selects on 1/ N of the connections. The reason the factory supports more than one selector thread is that with large numbers of connections, select() itself can become a performance bottleneck. 
- 0-M socket I/ O worker threads, which perform basic socket reads and writes. If configured with 0 worker threads, the selector threads do the socket I/ O directly. 
- 1 connection expiration thread, which closes idle connections; this is necessary to expire connections on which no session is established. 
Typical (default) thread counts are: on a 32 core machine, 1 accept thread, 1 connection expiration thread, 4 selector threads, and 64 worker threads.



public class NIOServerCnxnFactory extends ServerCnxnFactory {
    @Override
    public void start() {
        stopped = false;
        if (workerPool == null) {
            workerPool = new WorkerService(“NIOWorker”, numWorkerThreads, false);
        }
        for (SelectorThread thread : selectorThreads) {
            if (thread.getState() == Thread.State.NEW) {
                thread.start();
            }
        }
        // ensure thread is started once and only once
        if (acceptThread.getState() == Thread.State.NEW) {
            acceptThread.start();
        }
        if (expirerThread.getState() == Thread.State.NEW) {
            expirerThread.start();
        }
    }
}


SelectorThread.acceptedQueue¶
acceptedQueue是LinkedBlockingQueue类型的, 在selector thread中.其中包含了accept thread接收的客户端连接,由selector thread负责将客户端连接注册到selector上,监听OP_READ和OP_WRITE.

SelectorThread.updateQueue¶
updateQueue和acceptedQueue一样,也是LinkedBlockingQueue类型的,在selector thread中.但是要说明白该队列的作用,就要对Java NIO的实现非常了解了. _Java NIO使用epoll（Linux中）系统调用,且是水平触发,也即若selector.select()发现socketChannel中有事件发生,比如有数据可读, 只要没有将这些数据从socketChannel读取完毕,下一次selector.select()还是会检测到有事件发生,直至数据被读取完毕. ZooKeeper一直认为selector.select()是性能的瓶颈,为了提高selector.select()的性能,避免上述水平触发模式的缺陷,ZooKeeper在处理IO的过程中, 会让socketChannel不再监听OP_READ和OP_WRITE事件,这样就可以减轻selector.select()的负担. 


此时便出现一个问题,IO处理完毕后,如何让socketChannel再监听OP_READ和OP_WRITE事件? 有的小伙伴可能认为这件事情非常容易,worker thread处理IO结束后,直接调用key.interestOps(OP_READ & OP_WRITE)不就可以了吗? 事情并没有这简单,是因为selector.select()是在selector thread中执行的, 若在 selector.select()的过程中 ,worker thread调用了 key.interestOps(OP_READ & OP_WRITE) , 可能会阻塞selector.select() .
ZooKeeper为了追求性能的极致,设计为由selector thread调用key.interestOps(OP_READ & OP_WRITE), 因此worker thread就需在IO处理完毕后告诉selector thread该socketChannel可以去监听OP_READ和OP_WRITE事件了, updateQueue就是存放那些需要监听OP_READ和OP_WRITE事件



socketChannel.NIOServerCnxn.outgoingBuffers¶
outgoingBuffers存放待发送给客户端的响应数据. 注:既然key.interestOps(OP_READ & OP_WRITE)会阻塞selector.select(),那么accepted.register(selector, SelectionKey.OP_READ) 也会阻塞selector.select(), 因此接收到的客户端连接注册到selector上也要在selector thread上执行,这也是acceptedQueue存在的理由

## Netty



## Comparsion

简单比较














