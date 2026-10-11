## Introduction

All the Redis commands are defined in the following way:

```
void foobarCommand(client *c) {
    printf("%s",c->argv[1]->ptr); /* Do something with the argument. */
    addReply(c,shared.ok); /* Reply something to the client. */
}

```

After the command operates in some way, it returns a reply to the client, usually using `addReply()` or a similar function defined inside `networking.c`.

## Command Definition

> [!NOTE]
> 版本基线 Redis 8.10.2：命令定义文件共 **459 个**（`src/commands/*.json`）。

Redis 命令不是手写进C 代码的，而是**声明式定义 + 自动生成命令表**：

1. 每个命令一个 JSON 文件放在 `src/commands/`，含命令名、参数规格、实现函数名、复杂度、`since` 版本、`command_flags`、`acl_categories` 等。
2. `utils/generate-command-code.py` 在构建时把全部 JSON 编译成 `commands.c` 里的命令表。
3. `src/server.h:3058` 的 `struct redisCommand` 承载生成结果，其中多数字段直接来自 JSON 声明（`summary`、`complexity`、`since`、`doc_flags`、`replaced_by`、`deprecated_since`、`tips` 等）。

**这个机制的实际价值**：官方文档站与命令元数据同源于这些 JSON，所以「某命令自哪个版本引入」「是否已废弃」「替代命令是什么」都可以直接在 JSON 里查到，而不依赖可能滞后的文档页面。查版本兼容性时优先看 `src/commands/<cmd>.json` 的 `since` 字段，而不是猜。

参数类型由脚本翻译为 `ARG_TYPE_*`（`string` / `integer` / `double` / `key` / `pattern` / `unix-time` / `pure-token` / `oneof` / `block`），其中 `key` 类型的声明同时被 Cluster 用来判断命令要访问哪些 slot —— 这也是脚本类命令必须正确声明 key 范围的原因。

命令分组（`utils/generate-command-code.py` 的 `GROUPS`）映射到 `COMMAND_GROUP_*`，脚本里列出 19 个：`generic`、`string`、`list`、`set`、`sorted_set`、`hash`、`pubsub`、`transactions`、`connection`、`server`、`scripting`、`hyperloglog`、`cluster`、`sentinel`、`geo`、`stream`、`bitmap`、`array`、`rate_limit`。`COMMAND INFO` / `COMMAND DOCS` 返回的分组信息即源于此。

> [!TIP]
> 分组枚举里有两个需要留意：`array` 在 8.10.2 下确有 **18 个命令**（`ARCOUNT`/`ARDEL`/`ARDELRANGE`/`ARGET`/`ARGETRANGE`/`ARGREP`/`ARINFO`/`ARINSERT`/`ARLASTITEMS`/`ARLEN`/`ARMGET`/`ARMSET`/`ARNEXT`/`AROP`/`ARRING`/`ARSCAN`/`ARSEEK`/`ARSET`，全部 `since 8.8.0`）；而 `rate_limit` 在 8.10.2 的 `src/commands/*.json` 里**没有任何命令使用它**，属预留的空分组 —— 不要据此以为当前版本有速率限制命令。

查「某命令属于哪组 / 有哪些命令」用 `COMMAND INFO <cmd>`、`COMMAND DOCS <cmd>` 或 `COMMAND LIST`，比翻源码快；只有需要确认「某能力是否存在」以及「从哪个版本起」时，才去读 `src/commands/*.json` 的 `since` 字段。

新增命令时，除了实现 `xxxCommand` 函数与写 JSON，还要注意 `command_flags` 里的 `NOSCRIPT`、`NOSCRIPT` 类标记会禁止在Lua /FUNCTION 中调用；模块命令则通过 `RedisModule_CreateCommand` 注册，由[module.md](/docs/CS/DB/Redis/module.md) 覆盖。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [server.md](/docs/CS/DB/Redis/server.md)
- [module.md](/docs/CS/DB/Redis/module.md)