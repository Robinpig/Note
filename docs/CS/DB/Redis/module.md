## Introduction

Redis 从 4.0 版本开始，就提供了扩展模块（Module）的功能。这些扩展模块以动态链接库（so 文件）的形式加载到 Redis 中，我们可以基于 Redis 来新增功能模块

在 Redis 的入口 main 函数的执行流程中，会**调用 moduleInitModulesSystem 函数**（在 module.c 文件中）初始化扩展模块框架

```c

void moduleInitModulesSystem(void) {
    moduleUnblockedClients = listCreate();
    server.loadmodule_queue = listCreate();
    server.module_configs_queue = dictCreate(&sdsKeyValueHashDictType);
    server.module_gil_acquring = 0;
    modules = dictCreate(&modulesDictType);
    moduleAuthCallbacks = listCreate();

    /* Set up the keyspace notification subscriber list and static client */
    moduleKeyspaceSubscribers = listCreate();

    modulePostExecUnitJobs = listCreate();

    /* Set up filter list */
    moduleCommandFilters = listCreate();

    moduleRegisterCoreAPI();

    /* Create a pipe for module threads to be able to wake up the redis main thread.
     * Make the pipe non blocking. This is just a best effort aware mechanism
     * and we do not want to block not in the read nor in the write half.
     * Enable close-on-exec flag on pipes in case of the fork-exec system calls in
     * sentinels or redis servers. */
    if (anetPipe(server.module_pipe, O_CLOEXEC|O_NONBLOCK, O_CLOEXEC|O_NONBLOCK) == -1) {
        serverLog(LL_WARNING,
            "Can't create the pipe for module threads: %s", strerror(errno));
        exit(1);
    }

    /* Create the timers radix tree. */
    Timers = raxNew();

    /* Setup the event listeners data structures. */
    RedisModule_EventListeners = listCreate();

    /* Making sure moduleEventVersions is synced with the number of events. */
    serverAssert(sizeof(moduleEventVersions)/sizeof(moduleEventVersions[0]) == _REDISMODULE_EVENT_NEXT);

    /* Our thread-safe contexts GIL must start with already locked:
     * it is just unlocked when it's safe. */
    pthread_mutex_lock(&moduleGIL);
}
```



在 Redis 的入口 main 函数的执行流程中，在调用完 moduleInitModulesSystem 函数，完成扩展模块框架初始化后，实际上，main 函数还会调用 moduleLoadFromQueue 函数，来加载扩展模块

moduleLoadFromQueue 函数会进一步调用 moduleLoad 函数，而 moduleLoad 函数会根据模块文件所在的路径、模块所需的参数来完成扩展模块的加载

在 moduleLoad 函数中，它会在我们自行开发的模块文件中查找“RedisModule_” 开头函数，并执行这个函数。然后，它会调用 dictAdd 函数，把成功加载的模块添加到全局哈希表 modules 









## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=struct)
