# Bootstrap

![Bootstrap](https://github.com/Robinpig/Note/raw/master/images/Netty/Bootstrap.png)

group

```java
/**
 * The {@link EventLoopGroup} which is used to handle all the events for the to-be-created
 * {@link Channel}
 */
public B group(EventLoopGroup group) {
    ObjectUtil.checkNotNull(group, "group");
    if (this.group != null) {
        throw new IllegalStateException("group set already");
    }
    this.group = group;
    return self();
}

/**
 * Set the {@link EventLoopGroup} for the parent (acceptor) and the child (client). These
 * {@link EventLoopGroup}'s are used to handle all the events and IO for {@link ServerChannel} and
 * {@link Channel}'s.
 */
public ServerBootstrap group(EventLoopGroup parentGroup, EventLoopGroup childGroup) {
    super.group(parentGroup);
    ObjectUtil.checkNotNull(childGroup, "childGroup");
    if (this.childGroup != null) {
        throw new IllegalStateException("childGroup set already");
    }
    this.childGroup = childGroup;
    return this;
}
```
channel

```java
/**
 * The {@link Class} which is used to create {@link Channel} instances from.
 * You either use this or {@link #channelFactory(io.netty.channel.ChannelFactory)} if your
 * {@link Channel} implementation has no no-args constructor.
 */
public B channel(Class<? extends C> channelClass) {
    return channelFactory(new ReflectiveChannelFactory<C>(
            ObjectUtil.checkNotNull(channelClass, "channelClass")
    ));
}

/**
 * Creates a new channel.
*/
@Override
public T newChannel() {
    try {
        return constructor.newInstance();
    } catch (Throwable t) {
        throw new ChannelException("Unable to create Channel from class " + constructor.getDeclaringClass(), t);
    }
}

/**
 * Creates a new instance.In AbstractChannel Constructor
 *
 * @param parent
 *        the parent of this channel. {@code null} if there's no parent.
 */
protected AbstractChannel(Channel parent) {
    this.parent = parent;
    id = newId();
    unsafe = newUnsafe();
    pipeline = newChannelPipeline();
}
```

[Channel](https://github.com/Robinpig/Note/CS/Java/Netty/Channel.md)

Where  to new channel? 

connect( )->doResolveAndConnect( )->initAndRegister( )

```java
final ChannelFuture initAndRegister() {
    Channel channel = null;
    try {
        channel = channelFactory.newChannel();
        init(channel);
    } catch (Throwable t) {
        if (channel != null) {
            // channel can be null if newChannel crashed (eg SocketException("too many open files"))
            channel.unsafe().closeForcibly();
            // as the Channel is not registered yet we need to force the usage of the GlobalEventExecutor
            return new DefaultChannelPromise(channel, GlobalEventExecutor.INSTANCE).setFailure(t);
        }
        // as the Channel is not registered yet we need to force the usage of the GlobalEventExecutor
        return new DefaultChannelPromise(new FailedChannel(), GlobalEventExecutor.INSTANCE).setFailure(t);
    }

    ChannelFuture regFuture = config().group().register(channel);
    if (regFuture.cause() != null) {
        if (channel.isRegistered()) {
            channel.close();
        } else {
            channel.unsafe().closeForcibly();
        }
    }

    // If we are here and the promise is not failed, it's one of the following cases:
    // 1) If we attempted registration from the event loop, the registration has been completed at this point.
    //    i.e. It's safe to attempt bind() or connect() now because the channel has been registered.
    // 2) If we attempted registration from the other thread, the registration request has been successfully
    //    added to the event loop's task queue for later execution.
    //    i.e. It's safe to attempt bind() or connect() now:
    //         because bind() or connect() will be executed *after* the scheduled registration task is executed
    //         because register(), bind(), and connect() are all bound to the same thread.

    return regFuture;
}
```