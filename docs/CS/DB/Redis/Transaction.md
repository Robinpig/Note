## Introduction

> [!NOTE]
> 版本基线：Redis 8.10.2（commit 498ecd0d）。本页机制若与其他版本口径冲突，以 [Redis 版本基线](/docs/CS/DB/Redis/Redis.md?id=version-baseline) 为准。

Redis Transactions allow the execution of a group of commands in a single step, they are centered around the commands `MULTI`, `EXEC`, `DISCARD` and `WATCH`.
Redis Transactions make two important guarantees:

* All the commands in a transaction are serialized and executed sequentially.
  A request sent by another client will never be served **in the middle** of the execution of a Redis Transaction.
  This guarantees that the commands are executed as a single isolated operation.
* The `EXEC` command triggers the execution of all the commands in the transaction, so if a client loses the connection to the server in the context of a transaction before calling the `EXEC` command none of the operations are performed,
  instead if the `EXEC` command is called, all the operations are performed.
  When using the [append-only file](/docs/CS/DB/Redis/persist.md?id=aof) Redis makes sure to use a single write(2) syscall to write the transaction on disk.
  However if the Redis server crashes or is killed by the system administrator in some hard way it is possible that only a partial number of operations are registered.
  Redis will detect this condition at restart, and will exit with an error. Using the `redis-check-aof` tool it is possible to fix the append only file that will remove the partial transaction so that the server can start again.

Starting with version 2.2, Redis allows for an extra guarantee to the above two, in the form of optimistic locking in a way very similar to a check-and-set (CAS) operation.

## Errors and rollbacks

During a transaction it is possible to encounter two kind of command errors:

- A command may fail to be queued, so there may be an error before EXEC is called.
  For instance the command may be syntactically wrong (wrong number of arguments, wrong command name, ...), or there may be some critical condition like an out of memory condition (if the server is configured to have a memory limit using the maxmemory directive).
- A command may fail after EXEC is called, for instance since we performed an operation against a key with the wrong value (like calling a list operation against a string value).

Starting with Redis 2.6.5, the server will detect an error during the accumulation of commands.
It will then refuse to execute the transaction returning an error during EXEC, discarding the transaction.
Errors happening after EXEC instead are not handled in a special way: all the other commands will be executed even if some command fails during the transaction.

**Redis does not support rollbacks of transactions** since supporting rollbacks would have a significant impact on the simplicity and performance of Redis.





#### **Why Transaction Rollback Is Not Supported?**

Redis 官方文档的解释如下：

> If you have a relational databases background, the fact that Redis commands can fail during a transaction, but still Redis will execute the rest of the transaction instead of rolling back, may look odd to you.
>
> However there are good opinions for this behavior:
>
>- Redis commands can fail only if called with a wrong syntax (and the problem is not detectable during the command queueing), or against keys holding the wrong data type: this means that in practical terms a failing command is the result of a programming errors, and a kind of error that is very likely to be detected during development, and not in production.
>- Redis is internally simplified and faster because it does not need the ability to roll back.

An argument against Redis point of view is that bugs happen, however it should be noted that in general the roll back does not save you from programming errors. For instance if a query increments a key by 2 instead of 1, or increments the wrong key, there is no way for a rollback mechanism to help. Given that no one can save the programmer from his or her errors, and that the kind of errors required for a Redis command to fail are unlikely to enter in production, we selected the simpler and faster approach of not supporting roll backs on errors.





这里不支持事务回滚，指的是不支持运行时错误的事务回滚

## process

表示事务状态。注意 8.10.2 里 `multiCmd` 已被 `pendingCommand` 取代，`commands` 是指针数组，`server.h` 还多了 `executing_cmd` 字段——这是 8.x 为事务内逐 key 通知（module keyed jobs）加的：
```c
// server.h
typedef struct pendingCommand pendingCommand;
typedef struct multiState {
    pendingCommand **commands;     /* Array of pointers to MULTI commands */
    int executing_cmd;      /* The index of the currently executed transaction 
                               command (index in commands field) */
    int count;              /* Total number of MULTI commands */
    int cmd_flags;          /* The accumulated command flags OR-ed together.
                               So if at least a command has a given flag, it
                               will be set in this field. */
    int cmd_inv_flags;      /* Same as cmd_flags, OR-ing the ~flags. so that it
                               is possible to know if all the commands have a
                               certain flag. */
    size_t argv_len_sums;    /* mem used by all commands arguments */
    int alloc_count;         /* total number of pendingCommand struct memory reserved. */
} multiState;
```
进入事务状态后 把命令暂存到队列

Redis执行事务时可能会遇到三种错误
- 语法错误
- 命令报错 正确的命令依旧会被执行 不能保证原子性
- Redis忽然宕机


Redis事务没有事务隔离级别的概念 


Redis 是基于内存存储的 无论是 RDB 还是 AOF 都无法完全保证数据不丢失

### multi

queueMultiCommand in [processCommand](/docs/CS/DB/Redis/server.md?id=processcommand)

### Exec

先看入口与 abort 条件。8.10.2 把 abort 的条件判断合并进 `isWatchedKeyExpired` 与 `CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC` 分支，且 `was_master` / `propagate_in_transaction` 那段复制传播逻辑已移出 `execCommand`（见下方 `multi.c` 现状）：

```c
// multi.c
void execCommand(client *c) {
    int j;
    robj **orig_argv;
    int orig_argc, orig_argv_len;
    size_t orig_all_argv_len_sum;
    struct redisCommand *orig_cmd;

    if (!(c->flags & CLIENT_MULTI)) {
        addReplyError(c,"EXEC without MULTI");
        return;
    }

    /* EXEC with expired watched key is disallowed*/
    if (isWatchedKeyExpired(c)) {
        c->flags |= (CLIENT_DIRTY_CAS);
    }

    /* Check if we need to abort the EXEC because:
     * 1) Some WATCHed key was touched.
     * 2) There was a previous error while queueing commands.
     * A failed EXEC in the first case returns a multi bulk nil object
     * (technically it is not an error but a special behavior), while
     * in the second an EXECABORT error is returned. */
    if (c->flags & (CLIENT_DIRTY_CAS | CLIENT_DIRTY_EXEC)) {
        if (c->flags & CLIENT_DIRTY_EXEC) {
            addReplyErrorObject(c, shared.execaborterr);
        } else {
            addReply(c, shared.nullarray[c->resp]);
        }

        discardTransaction(c);
        return;
    }

    uint64_t old_flags = c->flags;

    /* we do not want to allow blocking commands inside multi */
    c->flags |= CLIENT_DENY_BLOCKING;
```

随后 unwatch 并逐条 `call()`。注意 ACL 检查传的是**入队命令本身**（不是 EXEC），且 AOF 加载期的跳过判断、per-key jobs 的排空都是 8.x 新增：

```c
    /* Exec all the queued commands */
    unwatchAllKeys(c); /* Unwatch ASAP otherwise we'll waste CPU cycles */

    server.in_exec = 1;

    orig_argv = c->argv;
    orig_argv_len = c->argv_len;
    orig_argc = c->argc;
    orig_cmd = c->cmd;

    /* Multi-state commands aren't tracked through all_argv_len_sum, so we don't want anything done while executing them to affect that field.
     * Otherwise, we get inconsistencies and all_argv_len_sum doesn't go back to exactly 0 when the client is finished */
    orig_all_argv_len_sum = c->all_argv_len_sum;

    c->all_argv_len_sum = c->mstate.argv_len_sums;

    /* Skip ACL check for the AOF client while server loading. */
    int skip_acl_check = server.loading && c->id == CLIENT_ID_AOF;

    addReplyArrayLen(c,c->mstate.count);
    for (j = 0; j < c->mstate.count; j++) {
        c->argc = c->mstate.commands[j]->argc;
        c->argv = c->mstate.commands[j]->argv;
        c->argv_len = c->mstate.commands[j]->argv_len;
        c->cmd = c->realcmd = c->mstate.commands[j]->cmd;

        /* ACL permissions are also checked at the time of execution in case
         * they were changed after the commands were queued. Note we pass the
         * queued command itself, so that the key permissions are checked against
         * its keys and not against the EXEC command we are currently running. */
        int acl_errpos;
        int acl_retval = ACL_OK;
        if (!skip_acl_check) {
            acl_retval = ACLCheckAllPerm(c,c->mstate.commands[j],&acl_errpos);
        }
        if (acl_retval != ACL_OK) {
            char *reason;
            switch (acl_retval) {
            case ACL_DENIED_CMD:
                reason = "no permission to execute the command or subcommand";
                break;
            case ACL_DENIED_KEY:
                reason = "no permission to touch the specified keys";
                break;
            case ACL_DENIED_CHANNEL:
                reason = "no permission to access one of the channels used "
                         "as arguments";
                break;
            default:
                reason = "no permission";
                break;
            }
            addACLLogEntry(c,acl_retval,ACL_LOG_CTX_MULTI,acl_errpos,NULL,NULL);
            addReplyErrorFormat(c,
                "-NOPERM ACLs rules changed between the moment the "
                "transaction was accumulated and the EXEC call. "
                "This command is no longer allowed for the "
                "following reason: %s", reason);
        } else {
            c->mstate.executing_cmd = j;
            if (c->id == CLIENT_ID_AOF)
                call(c,CMD_CALL_NONE);
            else
                call(c,CMD_CALL_FULL);

            serverAssert((c->flags & CLIENT_BLOCKED) == 0);

            /* Drain per-key jobs queued by this sub-command so modules observe
             * per-key effects between MULTI/EXEC sub-commands. Done here rather
             * than on afterCommand() so standalone commands pay nothing. Regular
             * jobs drain at the end of the EXEC's execution unit. */
            if (server.fire_keyed_jobs_between_subcommands)
                firePerKeyJobsBetweenSubcommands();
        }

        /* Commands may alter argc/argv, restore mstate. */
        c->mstate.commands[j]->argc = c->argc;
        c->mstate.commands[j]->argv = c->argv;
        c->mstate.commands[j]->argv_len = c->argv_len;
        c->mstate.commands[j]->cmd = c->cmd;
    }

    // restore old DENY_BLOCKING value
    if (!(old_flags & CLIENT_DENY_BLOCKING))
        c->flags &= ~CLIENT_DENY_BLOCKING;

    c->argv = orig_argv;
    c->argv_len = orig_argv_len;
    c->argc = orig_argc;
    c->cmd = c->realcmd = orig_cmd;
    c->all_argv_len_sum = orig_all_argv_len_sum;
    discardTransaction(c);

    server.in_exec = 0;
}
```

## Watch

`WATCH` is used to provide a check-and-set (CAS) behavior to Redis transactions.
It is a command that will make the EXEC conditional: we are asking Redis to perform the transaction only if none of the WATCHed keys were modified.
This includes modifications made by the client, like write commands, and by Redis itself, like expiration or eviction.
If keys were modified between when they were WATCHed and when the EXEC was received, the entire transaction will be aborted instead, and EXEC returns a Null reply to notify that the transaction failed.

### watchForKey

The implementation uses a per-DB hash table mapping keys to list of clients
WATCHing those keys, so that given a key that is going to be modified we can mark all the associated clients as dirty.

Also every client contains a list of WATCHed keys so that's possible to un-watch such keys when the client is freed or when UNWATCH is called.
In the client->watched_keys list we need to use watchedKey structures as in order to identify a key in Redis we need both the key name and the DB.

`watchedKey` 现在把 `listNode` 内嵌进结构（同时挂在 `client->watched_keys` 与 `db->watched_keys` 两条链上），靠结构体偏移从 node 反查 `watchedKey`，省掉 `listSearchKey`；`expired` 位记录「WATCH 时该 key 已逻辑过期」：

```c
// multi.c
typedef struct watchedKey {
    listNode node;
    robj *key;
    redisDb *db;
    client *client;
    unsigned expired:1; /* Flag that we're watching an already expired key. */
} watchedKey;

/* Watch for the specified key */
void watchForKey(client *c, robj *key) {
    list *clients = NULL;
    listIter li;
    listNode *ln;
    watchedKey *wk;

    if (listLength(c->watched_keys) == 0) server.watching_clients++;

    /* Check if we are already watching for this key */
    listRewind(c->watched_keys,&li);
    while((ln = listNext(&li))) {
        wk = listNodeValue(ln);
        if (wk->db == c->db && equalStringObjects(key,wk->key))
            return; /* Key already watched */
    }
    /* This key is not already watched in this DB. Let's add it */
    clients = dictFetchValue(c->db->watched_keys,key);
    if (!clients) {
        clients = listCreate();
        dictAdd(c->db->watched_keys,key,clients);
        incrRefCount(key);
    }
    /* Add the new key to the list of keys watched by this client */
    wk = zmalloc(sizeof(*wk));
    wk->key = key;
    wk->client = c;
    wk->db = c->db;
    wk->expired = keyIsExpired(c->db, key->ptr, NULL);
    incrRefCount(key);
    listAddNodeTail(c->watched_keys, wk);
    watchedKeyLinkToClients(clients, wk);
}
```

### keyModified

8.x 里 `signalModifiedKey()` 已被 `keyModified()` 取代（同时承担 LRM 时间戳更新与 WATCH / 客户端缓存失效通知）；`trackingInvalidateKey` 也多了第三个参数 `bcast`：

```c
// db.c
void keyModified(client *c, redisDb *db, robj *key, robj *val, int signal) {
    if (val) updateLRM(val);
    if (signal) {
        touchWatchedKey(db,key);
        trackingInvalidateKey(c,key,1);
    }
}
```

"Touch" a key, so that if this key is being WATCHed by some client the next EXEC will fail.

`touchWatchedKey` 现在从内嵌 node 反查 `watchedKey` 进而拿到 client，并处理「WATCH 时已过期」的 key——若该 key 已真正被删除则视为逻辑无变化、清掉 expired 标记而非置脏；置脏后会立即 `unwatchAllKeys(c)` 以免后续重复打扰：

```c
// multi.c
void touchWatchedKey(redisDb *db, robj *key) {
    list *clients;
    listIter li;
    listNode *ln;

    if (dictSize(db->watched_keys) == 0) return;
    clients = dictFetchValue(db->watched_keys, key);
    if (!clients) return;

    /* Mark all the clients watching this key as CLIENT_DIRTY_CAS */
    /* Check if we are already watching for this key */
    listRewind(clients,&li);
    while((ln = listNext(&li))) {
        watchedKey *wk = redis_member2struct(watchedKey, node, ln);
        client *c = wk->client;

        if (wk->expired) {
            /* The key was already expired when WATCH was called. */
            if (db == wk->db &&
                equalStringObjects(key, wk->key) &&
                dbFind(db, key->ptr) == NULL)
            {
                /* Already expired key is deleted, so logically no change. Clear
                 * the flag. Deleted keys are not flagged as expired. */
                wk->expired = 0;
                goto skip_client;
            }
            break;
        }

        c->flags |= CLIENT_DIRTY_CAS;
        /* As the client is marked as dirty, there is no point in getting here
         * again in case that key (or others) are modified again (or keep the
         * memory overhead till EXEC). */
        unwatchAllKeys(c);

    skip_client:
        continue;
    }
}
```

## RedisCommand

事务队列里的每个元素都是 `pendingCommand`（8.10.2 里它取代了旧的 `multiCmd`），除了 `argv/argc/cmd`，还预存了 `keys_result`（命令的 key 规格解析结果）、`reploff`、`slot` 等，供 EXEC 逐条执行时直接复用——这也是 cluster 模式下事务要求所有 key 同槽的前提（key 声明见 [command.md](/docs/CS/DB/Redis/command.md)）：

```c
// server.h
struct pendingCommand {
    int argc;                 /* Num of arguments of current command. */
    int argv_len;             /* Size of argv array (may be more than argc) */
    robj **argv;              /* Arguments of current command. */
    size_t argv_len_sum;      /* Sum of lengths of objects in argv list. */
    unsigned long long input_bytes;
    struct redisCommand *cmd;
    getKeysResult keys_result;
    long long reploff;        /* c->reploff should be set to this value when the command is processed */
    int flags;
    int slot;         /* The slot the command is executing against. Set to INVALID_CLUSTER_SLOT
                       * if no slot is being used or if the command has a cross slot error */
    uint8_t read_error;

    struct pendingCommand *next;
    struct pendingCommand *prev;
};
```

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=command)
- [Lock](/docs/CS/DB/Redis/Lock.md)
- [Lua](/docs/CS/DB/Redis/Lua.md)

## References

1. [Redis Transactions](https://redis.io/docs/manual/transactions/)
