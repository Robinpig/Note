## Introduction

Redis 的 Lua 能力让客户端可以用脚本在**服务端原子地**执行多步逻辑，避免「读出来→客户端算→写回去」的竞态，也是实现分布式锁（[Lock.md](/docs/CS/DB/Redis/Lock.md)）与原子计数增减的基础。

> [!NOTE]
> 版本基线 Redis 8.10.2。脚本能力自 2.6 引入；3.2 起内置调试器；7.0 引入 `FUNCTION` 命令族（与 Lua 并行、但语义不同的一套服务端函数机制，7.2 未新增任何 `FUNCTION` 命令）。

## Script

用 `EVAL` 执行一段脚本：

```shell
EVAL "return 1+1" 0
```

第二个参数 `numkeys` 声明后续参数中有多少个是 key—— Redis Cluster 依据它决定路由到哪个 slot，**Lua 脚本里访问的 key 若不在声明范围内，集群模式下会报错**。其余参数是 `ARGV`。

三个实用要点：

- **超时是硬约束**。执行超过阈值后 Redis 会在 `busy-reply-threshold` 处让出—— 8.10.2 `src/config.c:3573` 里该配置项的**正式名是 `busy-reply-threshold`，默认 5000 毫秒**；`lua-time-limit` 只是保留的 deprecated 别名（同一行createLongLongConfig 的第二个参数）。网上大量资料仍在教旧名。
- **禁止阻塞与不确定操作**。脚本里不能 `sleep`、不能做外部 IO、不能依赖时间或随机数，否则主线程被占住且副本重放结果不一致。
- **默认不复制写操作**。7.0 起脚本的写命令走 `redis.replicate_commands()`，实际行为受 `lua-replicate-commands` 控制（8.10.2 `src/config.c:501` 标为 deprecated，取值 2）。

## Redis Lua scripts debugger

Starting with version 3.2 Redis includes a complete Lua debugger, that can be used in order to make the task of writing complex Redis scripts much simpler.

By default every new debugging session is a **forked session**. This also means that changes are **rolled back** after the script debugging session finished.

An alternative synchronous (non forked) debugging model is available on demand, so that changes to the dataset can be retained. In this mode the server blocks for the time the debugging session is active

> [!WARNING]
> **旧资料里的 `ldb` 命令在当前版本已不存在。** 8.10.2 源码中 `ldb` / `lldb` 在 `src/commands/*.json` 与 `debug.c` 里**零命中**，官方文档站 `redis.io/topics/ldb` 对应的交互式调试器已被移除。
>
> 现行的两个入口是分工的：
> - `SCRIPT DEBUG YES | SYNC | NO` —— 控制服务端脚本调试模式（`src/commands/script-debug.json`，`since 3.2.0`，实现函数 `scriptCommand`）。默认每个调试会话是 **forked session**，会话结束后改动**回滚**；`SYNC` 模式改为同步非forked，改动可保留，但**调试期间服务端阻塞**。
> - `DEBUG <subcommand>` —— 仍是 ADMIN 类调试命令容器（`src/commands/debug.json`），其 `command_flags` 含 **`PROTECTED`**，因此受 `enable-debug-command` 约束。
>
> `enable-debug-command` 的默认值是 `no`（`src/config.c:3497`；取值三态见 `config.c:150-155`：`no` / `yes` / `local`，即 `PROTECTED_ACTION_ALLOWED_NO` / `_YES` / `_LOCAL`，其中 `local` 表示仅允许本机连接），且该项带 `IMMUTABLE_CONFIG` —— **只能启动时指定，运行期改不了**。默认值即禁止，所以线上实例直接调`DEBUG` 会被拒。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Transaction](/docs/CS/DB/Redis/Transaction.md)
- [command.md](/docs/CS/DB/Redis/command.md)
- [Lock.md](/docs/CS/DB/Redis/Lock.md)

## References
1. [Redis Lua scripts debugger](https://redis.io/topics/ldb)