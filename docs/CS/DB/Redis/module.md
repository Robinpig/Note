## Introduction

> 版本基线：Redis 8.10.2（commit 498ecd0d）。以下片段均取自该 tag 的 `src/module.c`。

Redis 从 4.0 起提供扩展模块（Module）：模块编译成动态链接库（`.so`），在运行时加载进 Redis 进程，通过 `RedisModule_*` API 注册新命令、数据类型、配置与事件监听。8.0 起 Redis 把 Query Engine、JSON、Time Series、Bloom 等能力以内建模块形态随主仓库一起发布（见枢纽 [Version Baseline](/docs/CS/DB/Redis/Redis.md) 的 8.0 条目），但动态加载机制本身仍是 Redis 的核心扩展点——[RediSearch](/docs/CS/DB/Redis/RediSearch.md) 等也可以独立 `.so` 形态存在。

入口 `main()` 初始化运行时与配置后，先调 `moduleInitModulesSystem()` 搭起模块框架，再调 `moduleLoadFromQueue()` 加载配置里 `loadmodule` 指令排队的模块。

## Framework Initialization: moduleInitModulesSystem

框架初始化一次性建好模块运行所需的全部容器与基础设施：

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

    /* Create the timers radix tree. Key is a uint64_t timer ID (BE). */
    Timers = raxNewEx(0, NULL, sizeof(uint64_t));

    /* Setup the event listeners data structures. */
    RedisModule_EventListeners = listCreate();

    /* Making sure moduleEventVersions is synced with the number of events. */
    serverAssert(sizeof(moduleEventVersions)/sizeof(moduleEventVersions[0]) == _REDISMODULE_EVENT_NEXT);

    /* Our thread-safe contexts GIL must start with already locked:
     * it is just unlocked when it's safe. */
    pthread_mutex_lock(&moduleGIL);
}
```

要点：`modules` 是全局模块表（模块名 → `RedisModule`），`loadmodule_queue` 暂存待加载项，`moduleRegisterCoreAPI()` 把所有 `RedisModule_*` API 填进函数表供模块调用；一条非阻塞 pipe 让模块线程能唤醒主线程；`moduleGIL` 是线程安全上下文的全局锁，初始化时先锁住，只在确认安全的时机放开。

## Loading from Queue: moduleLoadFromQueue

配置解析阶段遇到的 `loadmodule` 指令**不会当场加载**，而是先塞进 `server.loadmodule_queue`——此时 server 尚未完全初始化。等初始化完成后 `moduleLoadFromQueue()` 遍历队列，逐项调用 `moduleLoad()`。它是 fail-fast 的：任一模块加载失败就 abort 整个 server，而不是带病启动——客户端可能依赖模块提供的命令，AOF 加载可能需要模块存在，从节点也必须理解主节点发来的模块命令。

## The OnLoad Contract: moduleLoad

函数签名为 `int moduleLoad(const char *path, void **module_argv, int module_argc, int is_loadex)`，核心是按路径打开 `.so` 并查找约定符号：

```c
    handle = dlopen(path,RTLD_NOW|RTLD_LOCAL);
    if (handle == NULL) {
        serverLog(LL_WARNING, "Module %s failed to load: %s", path, dlerror());
        return C_ERR;
    }
    onload = (int (*)(void *, void **, int))(unsigned long) dlsym(handle,"RedisModule_OnLoad");
    if (onload == NULL) {
        dlclose(handle);
        serverLog(LL_WARNING,
            "Module %s does not export RedisModule_OnLoad() "
            "symbol. Module not loaded.",path);
        return C_ERR;
    }

    return moduleOnLoad(onload, path, handle, module_argv, module_argc, is_loadex);
```

约定很直接：每个模块**必须导出名为 `RedisModule_OnLoad` 的符号**，签名为 `int RedisModule_OnLoad(RedisModuleCtx *ctx, RedisModuleString **argv, int argc)`；`dlsym` 就按这个字符串查找，找不到即报 "does not export RedisModule_OnLoad()" 并拒绝加载。库以 `RTLD_NOW|RTLD_LOCAL` 打开，加载前还会检查文件的可执行权限。

## Registration: moduleOnLoad

`moduleOnLoad()` 造一个临时 `RedisModuleCtx` 回调 `OnLoad`，再根据返回值决定登记还是回滚：

```c
int moduleOnLoad(int (*onload)(void *, void **, int), const char *path, void *handle, void **module_argv, int module_argc, int is_loadex) {
    RedisModuleCtx ctx;
    moduleCreateContext(&ctx, NULL, REDISMODULE_CTX_TEMP_CLIENT); /* We pass NULL since we don't have a module yet. */
    if (onload((void*)&ctx,module_argv,module_argc) == REDISMODULE_ERR) {
        serverLog(LL_WARNING,
            "Module %s initialization failed. Module not loaded", path ? path : "(null)");
        if (ctx.module) {
            moduleUnregisterCleanup(ctx.module);
            moduleRemoveCateogires(ctx.module);
            moduleFreeModuleStructure(ctx.module);
        }
        moduleFreeContext(&ctx);
        if (handle) dlclose(handle);
        return C_ERR;
    }

    /* Redis module loaded! Register it. */
    dictAdd(modules,ctx.module->name,ctx.module);
    ctx.module->blocked_clients = 0;
    ctx.module->handle = handle;
```

模块在 `RedisModule_OnLoad` 里通过 `RedisModule_CreateCommand` / `RedisModule_CreateDataType` 等 API 注册的东西都挂在 `ctx.module` 上；`dictAdd(modules, ctx.module->name, ctx.module)` 一旦把模块写进全局 `modules` 表，这些命令与类型就一并生效。返回 `REDISMODULE_ERR` 则清理已注册的 cleanup / ACL 分类 / 模块结构、`dlclose` 并拒绝加载。8.10.2 还在这里处理模块配置的 `LoadConfigs` 校验、ACL 分类位重算，并触发 `REDISMODULE_EVENT_MODULE_CHANGE` 事件。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)


## References

1. [Redis Modules API](https://redis.io/docs/latest/develop/reference/modules/)
