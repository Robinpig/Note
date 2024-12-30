## Introduction

Redis Transactions allow the execution of a group of commands in a single step, they are centered around the commands `MULTI`, `EXEC`, `DISCARD` and `WATCH`.
Redis Transactions make two important guarantees:

* All the commands in a transaction are serialized and executed sequentially.
  A request sent by another client will never be served **in the middle** of the execution of a Redis Transaction.
  This guarantees that the commands are executed as a single isolated operation.
* The `EXEC` command triggers the execution of all the commands in the transaction, so if a client loses the connection to the server in the context of a transaction before calling the `EXEC` command none of the operations are performed,
  instead if the `EXEC` command is called, all the operations are performed.
  When using the [append-only file](/docs/CS/DB/Redis/persist.md?id=AOF) Redis makes sure to use a single write(2) syscall to write the transaction on disk.
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

## process

表示事务状态
```c
typedef struct multiState {
    multiCmd *commands;     /* Array of MULTI commands */
    int count;              /* Total number of MULTI commands */
    int cmd_flags;          /* The accumulated command flags OR-ed together.
                               So if at least a command has a given flag, it
                               will be set in this field. */
    int cmd_inv_flags;      /* Same as cmd_flags, OR-ing the ~flags. so that it
                               is possible to know if all the commands have a
                               certain flag. */
    size_t argv_len_sums;    /* mem used by all commands arguments */
    int alloc_count;         /* total number of multiCmd struct memory reserved. */
} multiState;
```
进入事务状态后 把命令暂存到队列

Redis执行事务时可能会遇到三种错误
- 语法错误
- 命令报错 正确的命令依旧会被执行 不能保证原子性
- Redis忽然宕机


Redis事务没有事务隔离级别的概念 


Redis是基于内存存储的 无论是RDB还是AOF都无法完全保证数据不丢失

### multi

queueMultiCommand in [processCommand](/docs/CS/DB/Redis/server.md?id=processCommand)

### Exec

```c

void execCommand(client *c) {
    int j;
    robj **orig_argv;
    int orig_argc;
    struct redisCommand *orig_cmd;
    int was_master = server.masterhost == NULL;

    if (!(c->flags & CLIENT_MULTI)) {
        addReplyError(c,"EXEC without MULTI");
        return;
    }

    /* EXEC with expired watched key is disallowed*/
    if (isWatchedKeyExpired(c)) {
        c->flags |= (CLIENT_DIRTY_CAS);
    }
```

Check if we need to abort the EXEC because:

1. Some WATCHed key was touched.
2. There was a previous error while queueing commands.

A failed EXEC in the first case returns a multi bulk nil object (technically it is not an error but a special behavior), while in the second an EXECABORT error is returned.

```c
    if (c->flags & (CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC)) {
        addReply(c, c->flags & CLIENT_DIRTY_EXEC ? shared.execaborterr :
                                                   shared.nullarray[c->resp]);
        discardTransaction(c);
        return;
    }

    uint64_t old_flags = c->flags;

    /* we do not want to allow blocking commands inside multi */
    c->flags |= CLIENT_DENY_BLOCKING;
```

Exec all the queued commands.
Unwatch ASAP otherwise we'll waste CPU cycles

```c
    unwatchAllKeys(c);

    server.in_exec = 1;

    orig_argv = c->argv;
    orig_argc = c->argc;
    orig_cmd = c->cmd;
    addReplyArrayLen(c,c->mstate.count);
    for (j = 0; j < c->mstate.count; j++) {
        c->argc = c->mstate.commands[j].argc;
        c->argv = c->mstate.commands[j].argv;
        c->cmd = c->mstate.commands[j].cmd;

        /* ACL permissions are also checked at the time of execution in case
         * they were changed after the commands were queued. */
        int acl_errpos;
        int acl_retval = ACLCheckAllPerm(c,&acl_errpos);
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
            addACLLogEntry(c,acl_retval,acl_errpos,NULL);
            addReplyErrorFormat(c,
                "-NOPERM ACLs rules changed between the moment the "
                "transaction was accumulated and the EXEC call. "
                "This command is no longer allowed for the "
                "following reason: %s", reason);
        } else {
            call(c,server.loading ? CMD_CALL_NONE : CMD_CALL_FULL);
            serverAssert((c->flags & CLIENT_BLOCKED) == 0);
        }

        /* Commands may alter argc/argv, restore mstate. */
        c->mstate.commands[j].argc = c->argc;
        c->mstate.commands[j].argv = c->argv;
        c->mstate.commands[j].cmd = c->cmd;
    }

    // restore old DENY_BLOCKING value
    if (!(old_flags & CLIENT_DENY_BLOCKING))
        c->flags &= ~CLIENT_DENY_BLOCKING;

    c->argv = orig_argv;
    c->argc = orig_argc;
    c->cmd = orig_cmd;
    discardTransaction(c);
```

Make sure the EXEC command will be propagated as well if MULTI was already propagated.

If inside the MULTI/EXEC block this instance was suddenly switched from master to slave (using the SLAVEOF command), the initial MULTI was propagated into the replication backlog, but the rest was not.
We need to make sure to at least terminate the backlog with the final EXEC.

```c
    if (server.propagate_in_transaction) {
        int is_master = server.masterhost == NULL;
        server.dirty++;
        if (server.repl_backlog && was_master && !is_master) {
            char *execcmd = "*1\r\n$4\r\nEXEC\r\n";
            feedReplicationBacklog(execcmd,strlen(execcmd));
        }
        afterPropagateExec();
    }

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

```c
// multi.c
typedef struct watchedKey {
    robj *key;
    redisDb *db;
} watchedKey;

void watchForKey(client *c, robj *key) {
    list *clients = NULL;
    listIter li;
    listNode *ln;
    watchedKey *wk;

    /* Check if we are already watching for this key */
    listRewind(c->watched_keys,&li);
    while((ln = listNext(&li))) {
        wk = listNodeValue(ln);
        if (wk->db == c->db && equalStringObjects(key,wk->key))
            return; /* Key already watched */
    }
```

This key is not already watched in this DB. Let's add it

```c
    clients = dictFetchValue(c->db->watched_keys,key);
    if (!clients) {
        clients = listCreate();
        dictAdd(c->db->watched_keys,key,clients);
        incrRefCount(key);
    }
    listAddNodeTail(clients,c);
    /* Add the new key to the list of keys watched by this client */
    wk = zmalloc(sizeof(*wk));
    wk->key = key;
    wk->db = c->db;
    incrRefCount(key);
    listAddNodeTail(c->watched_keys,wk);
}
```

### signalModifiedKey

Every time a key in the database is modified the function `signalModifiedKey()` is called.

```c
// db.c
void signalModifiedKey(client *c, redisDb *db, robj *key) {
    touchWatchedKey(db,key);
    trackingInvalidateKey(c,key);
}
```

"Touch" a key, so that if this key is being WATCHed by some client the next EXEC will fail.

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
        client *c = listNodeValue(ln);

        c->flags |= CLIENT_DIRTY_CAS;
    }
}
```

## RedisCommand

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md?id=persistence)

## References

1. [Redis Transactions](https://redis.io/docs/manual/transactions/)
