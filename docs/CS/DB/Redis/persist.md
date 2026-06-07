## 介绍

Redis 提供了不同范围的持久化选项：

- **RDB**（Redis Database）：RDB 持久化在指定时间间隔对数据集执行时间点快照。
- **AOF**（Append Only File）：AOF 持久化记录服务器接收到的每个写操作，这些操作将在服务器启动时重新执行，重建原始数据集。
  命令以 Redis 协议本身的相同格式记录，采用追加写入方式。当 AOF 文件过大时，Redis 能够在后台[重写日志](/docs/CS/DB/Redis/persist.md?id=rewriting)。
- **无持久化**：如果需要，可以完全禁用持久化，使数据只在服务器运行时存在。
- **RDB + AOF**：可以在同一实例中同时使用 AOF 和 RDB。
  注意，在这种情况下，当 Redis 重启时，将使用 AOF 文件重建原始数据集，因为它被保证是最完整的。

最重要的是理解 RDB 和 AOF 持久化之间的不同权衡。

## RDB

RDB 优势：

- RDB 是 Redis 数据的一个非常紧凑的单文件时间点表示。RDB 文件非常适合备份。
  例如，你可能希望每小时的 RDB 文件归档最近 24 小时，并每天保存一个 RDB 快照保留 30 天。
  这允许你在灾难发生时轻松恢复不同版本的数据集。
- RDB 非常适合灾难恢复，它是一个紧凑的单文件，可以传输到远程数据中心或 Amazon S3（可能加密）。
- RDB 最大化 Redis 性能，因为 Redis 父进程为了持久化唯一需要做的是 fork 一个子进程，子进程将完成其余所有工作。
  父进程永远不会执行磁盘 I/O 或类似操作。
- 与 AOF 相比，RDB 允许大数据集更快地重启。
- 在副本上，RDB 支持重启和故障转移后的部分重新同步。

RDB 缺点：

- 如果需要最小化 Redis 停止工作时（例如断电后）的数据丢失可能性，RDB 并不好。
  你可以配置不同的*save 点*来生成 RDB（例如至少五分钟且有 100 次写入时，但你可以有多个保存点）。
  然而，你通常每五分钟或更长时间创建一个 RDB 快照，因此如果 Redis 因任何原因未正确关闭而停止工作，你应该做好丢失最近几分钟数据的准备。
- RDB 需要经常 fork() 以便使用子进程持久化到磁盘。
  如果数据集很大，fork() 可能会很耗时，并可能导致 Redis 停止服务客户端几毫秒，甚至如果数据集非常大且 CPU 性能不佳，可能达到一秒。
  AOF 也需要 fork()，但你可以调整重写日志的频率，而不会影响持久性。

默认情况下，Redis 将数据集快照保存到磁盘上的二进制文件中，名为 `dump.rdb`。

RDB 文件分为两个阶段，RDB 文件生成阶段和加载阶段。

**1. RDB 文件生成**

从内存状态持久化成 RDB（文件）的时候，会对 key 进行过期检查，过期的键不会被保存到新的 RDB 文件中，因此 Redis 中的过期键不会对生成新 RDB 文件产生任何影响。

**2. RDB 文件加载**

RDB 加载分为以下两种情况：

- 如果 Redis 是主服务器运行模式的话，在载入 RDB 文件时，程序会对文件中保存的键进行检查，过期键不会被载入到数据库中。所以过期键不会对载入 RDB 文件的主服务器造成影响；
- 如果 Redis 是从服务器运行模式的话，在载入 RDB 文件时，不论键是否过期都会被载入到数据库中。但由于主从服务器在进行数据同步时，从服务器的数据会被清空。所以一般来说，过期键对载入 RDB 文件的从服务器也不会造成影响。

当 Redis 运行在主从模式下时，从库不会进行过期扫描，从库对过期的处理是被动的。也就是即使从库中的 key 过期了，如果有客户端访问从库时，依然可以得到 key 对应的值，像未过期的键值对一样返回。

从库的过期键处理依靠主服务器控制，主库在 key 到期时，会在 AOF 文件里增加一条 del 指令，同步到所有的从库，从库通过执行这条 del 指令来删除过期的 key。

**RDB 触发方式**

你可以配置 Redis，使其在数据集每 N 秒至少有 M 次更改时保存数据集，或者你可以手动调用 `SAVE` 或 `BGSAVE` 命令。

例如，以下配置将使 Redis 每 60 秒自动将数据集转储到磁盘，如果至少有 1000 个键发生更改：

```conf
save 60 1000
```

过于频繁的执行全量数据快照，有两个严重性能开销：

1. 频繁生成 RDB 文件写入磁盘，磁盘压力过大。会出现上一个 RDB 还未执行完，下一个又开始生成，陷入死循环。
2. fork 出 bgsave 子进程会阻塞主线程，主线程的内存越大，阻塞时间越长。

`flushall` 命令用于清空 Redis 数据库，在生产环境下一定慎用，当 Redis 执行了 `flushall` 命令之后，则会触发自动持久化，把 RDB 文件清空。

在 Redis 主从复制中，当从节点执行全量复制操作时，主节点会执行 `bgsave` 命令，并将 RDB 文件发送给从节点。

### save

每当 Redis 需要将数据集转储到磁盘时，会发生以下情况：

- Redis [fork](/docs/CS/OS/Linux/proc/process.md?id=fork) 一个子进程。现在我们有了一个子进程和一个父进程。
- 子进程开始将数据集写入临时 RDB 文件。
- 当子进程完成写入新的 RDB 文件后，它会替换旧文件。

这种方法允许 Redis 受益于**写时复制**语义。

BGSAVE 命令实现

```c
/* BGSAVE [SCHEDULE] */
void bgsaveCommand(client *c) {
    int schedule = 0;

    /* The SCHEDULE option changes the behavior of BGSAVE when an AOF rewrite
     * is in progress. Instead of returning an error a BGSAVE gets scheduled. */
    if (c->argc > 1) {
        if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"schedule")) {
            schedule = 1;
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    }

    rdbSaveInfo rsi, *rsiptr;
    rsiptr = rdbPopulateSaveInfo(&rsi);

    if (server.child_type == CHILD_TYPE_RDB) {
        addReplyError(c,"Background save already in progress");
    } else if (hasActiveChildProcess() || server.in_exec) {
        if (schedule || server.in_exec) {
            server.rdb_bgsave_scheduled = 1;
            addReplyStatus(c,"Background saving scheduled");
        } else {
            addReplyError(c,
            "Another child process is active (AOF?): can't BGSAVE right now. "
            "Use BGSAVE SCHEDULE in order to schedule a BGSAVE whenever "
            "possible.");
        }
    } else if (rdbSaveBackground(SLAVE_REQ_NONE,server.rdb_filename,rsiptr,RDBFLAGS_NONE) == C_OK) {
        addReplyStatus(c,"Background saving started");
    } else {
        addReplyErrorObject(c,shared.err);
    }
}
```

可以看到 fork() 函数的执行，在子进程中执行了 rdbSave() 函数，父进程则执行了一些设置状态的操作。

#### rdbSaveBackground

`BGSAVE` 命令或 serverCron 调用

```c
// rdb.c
int rdbSaveBackground(char *filename, rdbSaveInfo *rsi) {
    pid_t childpid;

    if (hasActiveChildProcess()) return C_ERR;

    server.dirty_before_bgsave = server.dirty;
    server.lastbgsave_try = time(NULL);

    if ((childpid = redisFork(CHILD_TYPE_RDB)) == 0) {
        int retval;

        /* Child */
        redisSetProcTitle("redis-rdb-bgsave");
        redisSetCpuAffinity(server.bgsave_cpulist);
        retval = rdbSave(filename,rsi);
        if (retval == C_OK) {
            sendChildCowInfo(CHILD_INFO_TYPE_RDB_COW_SIZE, "RDB");
        }
        exitFromChild((retval == C_OK) ? 0 : 1);
    } else {
        /* Parent */
        if (childpid == -1) {
            server.lastbgsave_status = C_ERR;
            serverLog(LL_WARNING,"Can't save in background: fork: %s",
                strerror(errno));
            return C_ERR;
        }
        serverLog(LL_NOTICE,"Background saving started by pid %ld",(long) childpid);
        server.rdb_save_time_start = time(NULL);
        server.rdb_child_type = RDB_CHILD_TYPE_DISK;
        return C_OK;
    }
    return C_OK; /* unreached */
}
```

#### saveDoneHandler

当后台 RDB 保存/传输终止时，调用相应的处理程序。

```c
// rdb.c
void backgroundSaveDoneHandler(int exitcode, int bysignal) {
    int type = server.rdb_child_type;
    switch(server.rdb_child_type) {
    case RDB_CHILD_TYPE_DISK:
        backgroundSaveDoneHandlerDisk(exitcode,bysignal);
        break;
    case RDB_CHILD_TYPE_SOCKET:
        backgroundSaveDoneHandlerSocket(exitcode,bysignal);
        break;
    default:
        serverPanic("Unknown RDB child type.");
        break;
    }

    server.rdb_child_type = RDB_CHILD_TYPE_NONE;
    server.rdb_save_time_last = time(NULL)-server.rdb_save_time_start;
    server.rdb_save_time_start = -1;
    /* Possibly there are slaves waiting for a BGSAVE in order to be served
     * (the first stage of SYNC is a bulk transfer of dump.rdb) */
    updateSlavesWaitingBgsave((!bysignal && exitcode == 0) ? C_OK : C_ERR, type);
}
```

#### rdbSave

刚开始生成一个临时的 RDB 文件，只有在执行成功后，才会进行 rename 操作，然后以写权限打开文件，然后调用了 rdbSaveRio() 函数将数据库的内容写到临时的 RDB 文件，
之后进行刷新缓冲区和同步操作，就关闭文件进行 rename 操作和更新服务器状态。

```c
int rdbSave(int req, char *filename, rdbSaveInfo *rsi, int rdbflags) {
    char tmpfile[256];
    char cwd[MAXPATHLEN]; /* Current working dir path for error messages. */

    startSaving(rdbflags);
    snprintf(tmpfile,256,"temp-%d.rdb", (int) getpid());

    if (rdbSaveInternal(req,tmpfile,rsi,rdbflags) != C_OK) {
        stopSaving(0);
        return C_ERR;
    }
    
    /* Use RENAME to make sure the DB file is changed atomically only
     * if the generate DB file is ok. */
    if (rename(tmpfile,filename) == -1) {
        char *str_err = strerror(errno);
        char *cwdp = getcwd(cwd,MAXPATHLEN);
        serverLog(LL_WARNING,
            "Error moving temp DB file %s on the final "
            "destination %s (in server root dir %s): %s",
            tmpfile,
            filename,
            cwdp ? cwdp : "unknown",
            str_err);
        unlink(tmpfile);
        stopSaving(0);
        return C_ERR;
    }
    if (fsyncFileDir(filename) != 0) {
        serverLog(LL_WARNING,
            "Failed to fsync directory while saving DB: %s", strerror(errno));
        stopSaving(0);
        return C_ERR;
    }

    serverLog(LL_NOTICE,"DB saved on disk");
    server.dirty = 0;
    server.lastsave = time(NULL);
    server.lastbgsave_status = C_OK;
    stopSaving(1);
    return C_OK;
}
```

rio 是 Redis 抽象的 IO 层，它可以面向三种对象，分别是缓冲区，文件 IO 和 socket IO。

#### saveRio

```c
int rdbSaveRio(int req, rio *rdb, int *error, int rdbflags, rdbSaveInfo *rsi) {
    char magic[10];
    uint64_t cksum;
    long key_counter = 0;
    int j;

    if (server.rdb_checksum)
        rdb->update_cksum = rioGenericUpdateChecksum;
    snprintf(magic,sizeof(magic),"REDIS%04d",RDB_VERSION);
    if (rdbWriteRaw(rdb,magic,9) == -1) goto werr;
    if (rdbSaveInfoAuxFields(rdb,rdbflags,rsi) == -1) goto werr;
    if (!(req & SLAVE_REQ_RDB_EXCLUDE_DATA) && rdbSaveModulesAux(rdb, REDISMODULE_AUX_BEFORE_RDB) == -1) goto werr;

    /* save functions */
    if (!(req & SLAVE_REQ_RDB_EXCLUDE_FUNCTIONS) && rdbSaveFunctions(rdb) == -1) goto werr;

    /* save all databases, skip this if we're in functions-only mode */
    if (!(req & SLAVE_REQ_RDB_EXCLUDE_DATA)) {
        for (j = 0; j < server.dbnum; j++) {
            if (rdbSaveDb(rdb, j, rdbflags, &key_counter) == -1) goto werr;
        }
    }

    if (!(req & SLAVE_REQ_RDB_EXCLUDE_DATA) && rdbSaveModulesAux(rdb, REDISMODULE_AUX_AFTER_RDB) == -1) goto werr;

    /* EOF opcode */
    if (rdbSaveType(rdb,RDB_OPCODE_EOF) == -1) goto werr;

    /* CRC64 checksum. It will be zero if checksum computation is disabled, the
     * loading code skips the check in this case. */
    cksum = rdb->cksum;
    memrev64ifbe(&cksum);
    if (rioWrite(rdb,&cksum,8) == 0) goto werr;
    return C_OK;

werr:
    if (error) *error = errno;
    return C_ERR;
}
```

调用 `rdbSaveKeyValuePair`

一个空数据库持久化生成的 dump.rdb 文件，使用 od -cx dump.rdb 命令查看一下。

### load RDB

#### loadDataFromDisk

Redis 启动时调用 loadDataFromDisk 函数从磁盘 rdb 文件加载数据到内存。

```c
int main(int argc, char **argv) {
    ...
    if (!server.sentinel_mode) {
        loadDataFromDisk();
    }
}
```

优先 AOF 文件，没有 AOF 才加载 RDB 文件。

- loadAppendOnlyFile

```c
void loadDataFromDisk(void) {
    long long start = ustime();
    if (server.aof_state == AOF_ON) {
        if (loadAppendOnlyFile(server.aof_filename) == C_OK)
            serverLog(LL_NOTICE,"DB loaded from append only file: %.3f seconds",(float)(ustime()-start)/1000000);
    } else {
        rdbSaveInfo rsi = RDB_SAVE_INFO_INIT;
        errno = 0; /* Prevent a stale value from affecting error checking */
        if (rdbLoad(server.rdb_filename,&rsi,RDBFLAGS_NONE) == C_OK) {
            /* Restore the replication ID / offset from the RDB file. */
        } else if (errno != ENOENT) {
            serverLog(LL_WARNING,"Fatal error loading the DB: %s. Exiting.",strerror(errno));
            exit(1);
        }
    }
}
```

从 rio 流 'rdb' 加载 RDB 文件。成功返回 C_OK，否则返回 C_ERR 并相应设置 'errno'。

```c
int rdbLoadRio(rio *rdb, int rdbflags, rdbSaveInfo *rsi) {
```

## AOF

说到日志，我们比较熟悉的是数据库的写前日志（Write Ahead Log, WAL），也就是说，在实际写数据前，先把修改的数据记到日志文件中，以便故障时进行恢复。不过，AOF 日志正好相反，它是写后日志，"写后"的意思是 Redis 是先执行命令，把数据写入内存，然后才记录日志。

AOF 优势：

- 使用 AOF，Redis 更持久：你可以使用不同的 fsync 策略：从不 fsync、每秒 fsync、每次查询 fsync。
  使用默认的每秒 fsync 策略，写入性能仍然很好（fsync 由后台线程执行，主线程会尽力在没有 fsync 进行时执行写入），但你最多可能丢失一秒钟的写入。
- AOF 日志是仅追加日志，因此没有寻道问题，也不会因断电而损坏。
  即使日志以某些原因（磁盘满或其他原因）的半写命令结尾，redis-check-aof 工具也能轻松修复。
- 当 AOF 文件过大时，Redis 能够在后台自动重写。
  重写是完全安全的，因为当 Redis 继续追加到旧文件时，会生成一个全新的文件，其中包含创建当前数据集所需的最少操作集，一旦第二个文件准备好，Redis 切换两者并开始追加到新文件。
- AOF 包含所有操作的日志，以易于理解和解析的格式一个接一个地排列。
  你甚至可以轻松导出 AOF 文件。
  例如，即使你不小心使用 `FLUSHALL` 命令清除了所有内容，只要在此期间没有执行日志重写，你仍然可以通过停止服务器、删除最新命令并重新启动 Redis 来保存数据集。

AOF 缺点：

- 对于相同的数据集，AOF 文件通常比等效的 RDB 文件大。
- 根据具体的 fsync 策略，AOF 可能比 RDB 慢。通常，将 fsync 设置为*每秒一次*时性能仍然非常高，禁用 fsync 时即使在高负载下也应与 RDB 一样快。
  尽管如此，即使在大量写入负载的情况下，RDB 也能在最大延迟方面提供更多保证。
- 过去，我们在特定命令中遇到过罕见的错误（例如有一个涉及阻塞命令如 `BRPOPLPUSH` 的错误），导致生成的 AOF 在重新加载时无法完全重现相同的数据集。
  这些错误很少见，我们在测试套件中有测试，自动创建随机复杂数据集并重新加载以检查一切正常。
  然而，这类错误在 RDB 持久化中几乎不可能发生。
  更明确地说：Redis AOF 通过增量更新现有状态工作，就像 MySQL 或 MongoDB 所做的那样，而 RDB 快照则一次又一次地从零开始创建所有内容，这在概念上更健壮。

然而：

1. 需要注意的是，每次 Redis 重写 AOF 时，都会基于数据集中包含的实际数据从头开始重新创建，这使得对错误的抵抗力比始终追加的 AOF 文件（或通过读取旧 AOF 而不是读取内存中数据来重写的 AOF）更强。
2. 我们从未收到过用户关于在现实世界中检测到 AOF 损坏的报告。

**Redis < 7.0**

- 如果重写期间有对数据库的写入，AOF 可能会使用大量内存（这些写入缓冲在内存中，最后写入新 AOF）。
- 重写期间到达的所有写入命令都会写入磁盘两次。
- 在重写结束时，Redis 可能会冻结写入和 fsync 这些写入命令到新 AOF 文件。

你可以在配置文件中开启 AOF：

```
appendonly yes
```

从现在开始，每当 Redis 收到更改数据集的命令（例如 `SET`）时，它都会将其追加到 AOF。
当你重启 Redis 时，它将重放 AOF 以重建状态，就像 MySQL 中的 [binlog](/docs/CS/DB/MySQL/binlog.md) 一样。

检查是否启动：

```
config get appendonly
```

写后日志避免了额外的检查开销，不需要对执行的命令进行语法检查。如果使用写前日志的话，就需要先检查语法是否有误，否则日志记录了错误的命令，在使用日志恢复的时候就会出错。

AOF 日志是主线程执行，将日志写入磁盘过程中，如果磁盘压力大就会导致写磁盘很慢，导致后续的「写」指令阻塞。

从 Redis 7.0.0 开始，Redis 使用多部分 AOF 机制。
也就是说，原始的单 AOF 文件被拆分为基础文件（最多一个）和增量文件（可能有多个）。
基础文件表示 AOF 重写时数据的初始（RDB 或 AOF 格式）快照。
增量文件包含自上一个基础 AOF 文件创建以来的增量更改。所有这些文件都放在一个单独的目录中，并由一个清单文件跟踪。

你可以配置 Redis 将数据 `fsync` 到磁盘的频率。
有三个选项：

- `appendfsync always`：每次将新命令追加到 AOF 时 `fsync`。非常非常慢，非常安全。
  注意，命令是在来自多个客户端或管道的命令批次执行后追加到 AOF，因此这意味着在发送回复之前进行一次写入和一次 fsync。
- `appendfsync everysec`：每秒 `fsync`。足够快（在 2.4 中可能与快照一样快），如果发生灾难，你可能丢失 1 秒的数据。
- `appendfsync no`：从不 `fsync`，将数据完全交给操作系统。最快但最不安全的方法。
  通常，Linux 使用此配置每 30 秒刷新一次数据，但这取决于内核的确切调优。

建议（和默认）策略是每秒 `fsync`。它既非常快又相当安全。
`always` 策略在实践中非常慢，但它支持组提交，因此如果有多个并行写入，Redis 将尝试执行单个 `fsync` 操作。

AOF 缓冲区是一个简单动态字符串（sds）。
```c
// server.h
struct redisServer {
    sds aof_buf;      /* AOF buffer, written before entering the event loop */
}
```

### append

将指定命令（在指定数据库 ID 的上下文中）传播到 AOF 和从节点。
```c
void propagate(struct redisCommand *cmd, int dbid, robj **argv, int argc,
               int flags)
{
   // ...
    if (server.aof_state != AOF_OFF && flags & PROPAGATE_AOF)
        feedAppendOnlyFile(cmd,dbid,argv,argc);
}
```

#### feedAppendOnlyFile

feedAppendOnlyFile 创建一个空的简单动态字符串（sds），将当前所有追加命令操作都追加到这个 sds 中，最终将这个 sds 追加到 `server.aof_buf`。

```c
void feedAppendOnlyFile(struct redisCommand *cmd, int dictid, robj **argv, int argc) {
    sds buf = sdsempty();
    /* The DB this command was targeting is not the same as the last command
     * we appended. To issue a SELECT command is needed. */
    if (dictid != server.aof_selected_db) {
        char seldb[64];

        snprintf(seldb,sizeof(seldb),"%d",dictid);
        buf = sdscatprintf(buf,"*2\r\n$6\r\nSELECT\r\n$%lu\r\n%s\r\n",
            (unsigned long)strlen(seldb),seldb);
        server.aof_selected_db = dictid;
    }

    if (cmd->proc == expireCommand || cmd->proc == pexpireCommand ||
        cmd->proc == expireatCommand) {
```

将 EXPIRE/PEXPIRE/EXPIREAT 转换为 PEXPIREAT。
```c
        buf = catAppendOnlyExpireAtCommand(buf,cmd,argv[1],argv[2]);
    } else if (cmd->proc == setCommand && argc > 3) {
        robj *pxarg = NULL;
        /* When SET is used with EX/PX argument setGenericCommand propagates them with PX millisecond argument.
         * So since the command arguments are re-written there, we can rely here on the index of PX being 3. */
        if (!strcasecmp(argv[3]->ptr, "px")) {
            pxarg = argv[4];
        }
        /* For AOF we convert SET key value relative time in milliseconds to SET key value absolute time in
         * millisecond. Whenever the condition is true it implies that original SET has been transformed
         * to SET PX with millisecond time argument so we do not need to worry about unit here.*/
        if (pxarg) {
            robj *millisecond = getDecodedObject(pxarg);
            long long when = strtoll(millisecond->ptr,NULL,10);
            when += mstime();

            decrRefCount(millisecond);

            robj *newargs[5];
            newargs[0] = argv[0];
            newargs[1] = argv[1];
            newargs[2] = argv[2];
            newargs[3] = shared.pxat;
            newargs[4] = createStringObjectFromLongLong(when);
            buf = catAppendOnlyGenericCommand(buf,5,newargs);
            decrRefCount(newargs[4]);
        } else {
            buf = catAppendOnlyGenericCommand(buf,argc,argv);
        }
    } else {
        /* All the other commands don't need translation or need the
         * same translation already operated in the command vector
         * for the replication itself. */
        buf = catAppendOnlyGenericCommand(buf,argc,argv);
    }
```

追加到 AOF 缓冲区。这将在重新进入事件循环之前刷新到磁盘，因此在客户端获得关于操作的肯定回复之前。
```c
    if (server.aof_state == AOF_ON)
        server.aof_buf = sdscatlen(server.aof_buf,buf,sdslen(buf));
```

如果后台追加文件重写正在进行中，我们希望将子进程 DB 和当前 DB 之间的差异累积到缓冲区中，以便当子进程完成其工作时，我们可以将差异追加到新的追加文件。
```c
    if (server.child_type == CHILD_TYPE_AOF)
        aofRewriteBufferAppend((unsigned char*)buf,sdslen(buf));

    sdsfree(buf);
}
```

catAppendOnlyGenericCommand() 函数实现了追加命令到缓冲区中。

```c
sds catAppendOnlyGenericCommand(sds dst, int argc, robj **argv) {
    char buf[32];
    int len, j;
    robj *o;

    buf[0] = '*';
    len = 1+ll2string(buf+1,sizeof(buf)-1,argc);
    buf[len++] = '\r';
    buf[len++] = '\n';
    dst = sdscatlen(dst,buf,len);

    for (j = 0; j < argc; j++) {
        o = getDecodedObject(argv[j]);
        buf[0] = '$';
        len = 1+ll2string(buf+1,sizeof(buf)-1,sdslen(o->ptr));
        buf[len++] = '\r';
        buf[len++] = '\n';
        dst = sdscatlen(dst,buf,len);
        dst = sdscatlen(dst,o->ptr,sdslen(o->ptr));
        dst = sdscatlen(dst,"\r\n",2);
        decrRefCount(o);
    }
    return dst;
}
```

### flush

#### flushAppendOnlyFile

如果 sync_in_progress，最多等待 2 秒。

将追加文件缓冲区写入磁盘。

由于我们需要在回复客户端之前写入 AOF，而客户端 socket 只有在进入事件循环时才能写入，因此我们将所有 AOF 写入累积到内存缓冲区中，并在再次进入事件循环之前使用此函数将其写入磁盘。

关于 'force' 参数：

当 fsync 策略设置为 'everysec' 时，如果后台线程中仍有 fsync() 正在进行，我们可能会延迟刷新，因为在 Linux 上 write(2) 无论如何都会被后台 fsync 阻塞。
当发生这种情况时，我们会记住有一些 AOF 缓冲区需要尽快刷新，并将在 serverCron() 函数中尝试这样做。

然而，如果 force 设置为 1，我们将忽略后台 fsync 直接写入。

由 `serverCron` 或 `beforeSleep` 或 `prepareForShutdown` 调用。

```c
// aof
#define AOF_WRITE_LOG_ERROR_RATE 30 /* Seconds between errors logging. */
void flushAppendOnlyFile(int force) {
    ssize_t nwritten;
    int sync_in_progress = 0;
    mstime_t latency;

    if (sdslen(server.aof_buf) == 0) {
```

检查是否需要在 AOF 缓冲区为空时执行 fsync，因为之前在 AOF_FSYNC_EVERYSEC 模式下，仅在 AOF 缓冲区不为空时调用 fsync，因此如果用户在一秒钟内 fsync 被调用之前停止了写入命令，页面缓存中的数据无法及时刷新。
```c
        if (server.aof_fsync == AOF_FSYNC_EVERYSEC &&
            server.aof_fsync_offset != server.aof_current_size &&
            server.unixtime > server.aof_last_fsync &&
            !(sync_in_progress = aofFsyncInProgress())) {
            goto try_fsync;
        } else {
            return;
        }
    }

    if (server.aof_fsync == AOF_FSYNC_EVERYSEC)
        sync_in_progress = aofFsyncInProgress();

    if (server.aof_fsync == AOF_FSYNC_EVERYSEC && !force) {
        /* With this append fsync policy we do background fsyncing.
         * If the fsync is still in progress we can try to delay
         * the write for a couple of seconds. */
        if (sync_in_progress) {
            if (server.aof_flush_postponed_start == 0) {
                /* No previous write postponing, remember that we are
                 * postponing the flush and return. */
                server.aof_flush_postponed_start = server.unixtime;
                return;
            } else if (server.unixtime - server.aof_flush_postponed_start < 2) {
                /* We were already waiting for fsync to finish, but for less
                 * than two seconds this is still ok. Postpone again. */
                return;
            }
            /* Otherwise fall trough, and go write since we can't wait
             * over two seconds. */
            server.aof_delayed_fsync++;
            serverLog(LL_NOTICE,"Asynchronous AOF fsync is taking too long (disk is busy?). Writing the AOF buffer without waiting for fsync to complete, this may slow down Redis.");
        }
    }
    /* We want to perform a single write. This should be guaranteed atomic
     * at least if the filesystem we are writing is a real physical one.
     * While this will save us against the server being killed I don't think
     * there is much to do about the whole server stopping for power problems
     * or alike */

    if (server.aof_flush_sleep && sdslen(server.aof_buf)) {
        usleep(server.aof_flush_sleep);
    }
```

write

```c
    latencyStartMonitor(latency);
    nwritten = aofWrite(server.aof_fd,server.aof_buf,sdslen(server.aof_buf));
    latencyEndMonitor(latency);
    /* We want to capture different events for delayed writes:
     * when the delay happens with a pending fsync, or with a saving child
     * active, and when the above two conditions are missing.
     * We also use an additional event name to save all samples which is
     * useful for graphing / monitoring purposes. */
    if (sync_in_progress) {
        latencyAddSampleIfNeeded("aof-write-pending-fsync",latency);
    } else if (hasActiveChildProcess()) {
        latencyAddSampleIfNeeded("aof-write-active-child",latency);
    } else {
        latencyAddSampleIfNeeded("aof-write-alone",latency);
    }
    latencyAddSampleIfNeeded("aof-write",latency);

    /* We performed the write so reset the postponed flush sentinel to zero. */
    server.aof_flush_postponed_start = 0;

    if (nwritten != (ssize_t)sdslen(server.aof_buf)) {
        static time_t last_write_error_log = 0;
        int can_log = 0;

        /* Limit logging rate to 1 line per AOF_WRITE_LOG_ERROR_RATE seconds. */
        if ((server.unixtime - last_write_error_log) > AOF_WRITE_LOG_ERROR_RATE) {
            can_log = 1;
            last_write_error_log = server.unixtime;
        }

        /* Log the AOF write error and record the error code. */
        if (nwritten == -1) {
            if (can_log) {
                serverLog(LL_WARNING,"Error writing to the AOF file: %s",
                    strerror(errno));
                server.aof_last_write_errno = errno;
            }
        } else {
            if (can_log) {
                serverLog(LL_WARNING,"Short write while writing to "
                                       "the AOF file: (nwritten=%lld, "
                                       "expected=%lld)",
                                       (long long)nwritten,
                                       (long long)sdslen(server.aof_buf));
            }

            if (ftruncate(server.aof_fd, server.aof_current_size) == -1) {
                if (can_log) {
                    serverLog(LL_WARNING, "Could not remove short write "
                             "from the append-only file.  Redis may refuse "
                             "to load the AOF the next time it starts.  "
                             "ftruncate: %s", strerror(errno));
                }
            } else {
                /* If the ftruncate() succeeded we can set nwritten to
                 * -1 since there is no longer partial data into the AOF. */
                nwritten = -1;
            }
            server.aof_last_write_errno = ENOSPC;
        }

        /* Handle the AOF write error. */
        if (server.aof_fsync == AOF_FSYNC_ALWAYS) {
            /* We can't recover when the fsync policy is ALWAYS since the reply
             * for the client is already in the output buffers (both writes and
             * reads), and the changes to the db can't be rolled back. Since we
             * have a contract with the user that on acknowledged or observed
             * writes are is synced on disk, we must exit. */
            serverLog(LL_WARNING,"Can't recover from AOF write error when the AOF fsync policy is 'always'. Exiting...");
            exit(1);
        } else {
            /* Recover from failed write leaving data into the buffer. However
             * set an error to stop accepting writes as long as the error
             * condition is not cleared. */
            server.aof_last_write_status = C_ERR;

            /* Trim the sds buffer if there was a partial write, and there
             * was no way to undo it with ftruncate(2). */
            if (nwritten > 0) {
                server.aof_current_size += nwritten;
                sdsrange(server.aof_buf,nwritten,-1);
            }
            return; /* We'll try again on the next call... */
        }
    } else {
        /* Successful write(2). If AOF was in error state, restore the
         * OK state and log the event. */
        if (server.aof_last_write_status == C_ERR) {
            serverLog(LL_WARNING,
                "AOF write error looks solved, Redis can write again.");
            server.aof_last_write_status = C_OK;
        }
    }
    server.aof_current_size += nwritten;
```

当 AOF 缓冲区足够小时重用。最大值来自 4k 的 arena 大小减去一些开销（但其他方面是任意的）。

```c
    if ((sdslen(server.aof_buf)+sdsavail(server.aof_buf)) < 4000) {
        sdsclear(server.aof_buf);
    } else {
        sdsfree(server.aof_buf);
        server.aof_buf = sdsempty();
    }

try_fsync:
    /* Don't fsync if no-appendfsync-on-rewrite is set to yes and there are
     * children doing I/O in the background. */
    if (server.aof_no_fsync_on_rewrite && hasActiveChildProcess())
        return;

    /* Perform the fsync if needed. */
    if (server.aof_fsync == AOF_FSYNC_ALWAYS) {
        /* redis_fsync is defined as fdatasync() for Linux in order to avoid
         * flushing metadata. */
        latencyStartMonitor(latency);
        /* Let's try to get this data on the disk. To guarantee data safe when
         * the AOF fsync policy is 'always', we should exit if failed to fsync
         * AOF (see comment next to the exit(1) after write error above). */
        if (redis_fsync(server.aof_fd) == -1) {
            serverLog(LL_WARNING,"Can't persist AOF for fsync error when the "
              "AOF fsync policy is 'always': %s. Exiting...", strerror(errno));
            exit(1);
        }
        latencyEndMonitor(latency);
        latencyAddSampleIfNeeded("aof-fsync-always",latency);
        server.aof_fsync_offset = server.aof_current_size;
        server.aof_last_fsync = server.unixtime;
    } else if ((server.aof_fsync == AOF_FSYNC_EVERYSEC &&
                server.unixtime > server.aof_last_fsync)) {
        if (!sync_in_progress) {
            aof_background_fsync(server.aof_fd);
            server.aof_fsync_offset = server.aof_current_size;
        }
        server.aof_last_fsync = server.unixtime;
    }
}

void aof_background_fsync(int fd) {
    bioCreateFsyncJob(fd);
}
```

### rewriting

AOF 文件重写是生成一个全新的文件，并把当前数据的最少操作命令保存到新文件上，当把所有的数据都保存至新文件之后，Redis 会交换两个文件，并把最新的持久化操作命令追加到新文件上。

日志重写使用与快照相同的写时复制技术。工作原理如下：

**Redis >= 7.0**

* Redis [fork](/docs/CS/OS/Linux/proc/process.md?id=fork) 一个子进程，现在我们有了一个子进程和一个父进程。
* 子进程开始将新的基础 AOF 写入临时文件。
* 父进程打开一个新的增量 AOF 文件以继续写入更新。如果重写失败，旧的基础文件和增量文件（如果有的话）加上这个新打开的增量文件代表完整的更新数据集，因此我们是安全的。
* 当子进程完成基础文件的重写后，父进程收到信号，并使用新打开的增量文件和子进程生成的基础文件构建临时清单，并持久化它。
* 完成！现在 Redis 原子地交换清单文件，使此次 AOF 重写的结果生效。Redis 还会清理旧的基础文件和任何未使用的增量文件。

**Redis < 7.0**

* Redis [fork](/docs/CS/OS/Linux/proc/process.md?id=fork) 一个子进程，现在我们有了一个子进程和一个父进程。
* 子进程开始将新的 AOF 写入临时文件。
* 父进程将所有新更改累积在内存缓冲区中（但同时将新更改写入旧的追加文件，因此如果重写失败，我们是安全的）。
* 当子进程完成文件重写后，父进程收到信号，并将内存缓冲区追加到子进程生成的文件末尾。
* 现在 Redis 原子地将新文件重命名为旧文件，并开始将新数据追加到新文件中。

每当你发出 `BGREWRITEAOF` 命令时，Redis 将写入重建当前内存中数据集所需的最短命令序列。

bgrewriteaof

#### rewriteAppendOnlyFileBackground

由以下调用：

1. startAppendOnly
2. bgrewriteaofCommand
3. serverCron

这是后台重写追加文件的方式：

1. 用户调用 `BGREWRITEAOF`
2. Redis 调用此函数，该函数 fork()：
   a. 子进程将追加文件重写到临时文件。
   b. 父进程将差异累积在 server.aof_rewrite_buf 中。
3. 当子进程完成 '2a' 后退出。
4. 父进程将捕获退出代码，如果成功，将累积在 server.aof_rewrite_buf 中的数据追加到临时文件，最后将临时文件 rename(2) 为实际文件名。
   然后新文件重新打开作为新的追加文件。完成！

```c
int rewriteAppendOnlyFileBackground(void) {
    pid_t childpid;

    if (hasActiveChildProcess()) return C_ERR;
    if (aofCreatePipes() != C_OK) return C_ERR;
    if ((childpid = redisFork(CHILD_TYPE_AOF)) == 0) {
        char tmpfile[256];

        /* Child */
        redisSetProcTitle("redis-aof-rewrite");
        redisSetCpuAffinity(server.aof_rewrite_cpulist);
        snprintf(tmpfile,256,"temp-rewriteaof-bg-%d.aof", (int) getpid());
        if (rewriteAppendOnlyFile(tmpfile) == C_OK) {
            sendChildCowInfo(CHILD_INFO_TYPE_AOF_COW_SIZE, "AOF rewrite");
            exitFromChild(0);
        } else {
            exitFromChild(1);
        }
    } else {
        /* Parent */
        if (childpid == -1) {
            serverLog(LL_WARNING,
                "Can't rewrite append only file in background: fork: %s",
                strerror(errno));
            aofClosePipes();
            return C_ERR;
        }
        serverLog(LL_NOTICE,
            "Background append only file rewriting started by pid %ld",(long) childpid);
        server.aof_rewrite_scheduled = 0;
        server.aof_rewrite_time_start = time(NULL);

        /* We set appendseldb to -1 in order to force the next call to the
         * feedAppendOnlyFile() to issue a SELECT command, so the differences
         * accumulated by the parent into server.aof_rewrite_buf will start
         * with a SELECT statement and it will be safe to merge. */
        server.aof_selected_db = -1;
        replicationScriptCacheFlush();
        return C_OK;
    }
    return C_OK; /* unreached */
}
```

```c
int rewriteAppendOnlyFile(char *filename) {
    rio aof;
    FILE *fp = NULL;
    char tmpfile[256];

    /* Note that we have to use a different temp name here compared to the
     * one used by rewriteAppendOnlyFileBackground() function. */
    snprintf(tmpfile,256,"temp-rewriteaof-%d.aof", (int) getpid());
    fp = fopen(tmpfile,"w");
    if (!fp) {
        serverLog(LL_WARNING, "Opening the temp file for AOF rewrite in rewriteAppendOnlyFile(): %s", strerror(errno));
        return C_ERR;
    }

    rioInitWithFile(&aof,fp);

    if (server.aof_rewrite_incremental_fsync) {
        rioSetAutoSync(&aof,REDIS_AUTOSYNC_BYTES);
        rioSetReclaimCache(&aof,1);
    }

    startSaving(RDBFLAGS_AOF_PREAMBLE);

    if (server.aof_use_rdb_preamble) {
        int error;
        if (rdbSaveRio(SLAVE_REQ_NONE,&aof,&error,RDBFLAGS_AOF_PREAMBLE,NULL) == C_ERR) {
            errno = error;
            goto werr;
        }
    } else {
        if (rewriteAppendOnlyFileRio(&aof) == C_ERR) goto werr;
    }

    /* Make sure data will not remain on the OS's output buffers */
    if (fflush(fp)) goto werr;
    if (fsync(fileno(fp))) goto werr;
    if (reclaimFilePageCache(fileno(fp), 0, 0) == -1) {
        /* A minor error. Just log to know what happens */
        serverLog(LL_NOTICE,"Unable to reclaim page cache: %s", strerror(errno));
    }
    if (fclose(fp)) { fp = NULL; goto werr; }
    fp = NULL;

    /* Use RENAME to make sure the DB file is changed atomically only
     * if the generate DB file is ok. */
    if (rename(tmpfile,filename) == -1) {
        serverLog(LL_WARNING,"Error moving temp append only file on the final destination: %s", strerror(errno));
        unlink(tmpfile);
        stopSaving(0);
        return C_ERR;
    }
    stopSaving(1);

    return C_OK;

werr:
    serverLog(LL_WARNING,"Write error writing append only file on disk: %s", strerror(errno));
    if (fp) fclose(fp);
    unlink(tmpfile);
    stopSaving(0);
    return C_ERR;
}
```

rewriteAppendOnlyFileRio

```c
int rewriteAppendOnlyFileRio(rio *aof) {
    dictEntry *de;
    int j;
    long key_count = 0;
    long long updated_time = 0;
    kvstoreIterator *kvs_it = NULL;

    /* Record timestamp at the beginning of rewriting AOF. */
    if (server.aof_timestamp_enabled) {
        sds ts = genAofTimestampAnnotationIfNeeded(1);
        if (rioWrite(aof,ts,sdslen(ts)) == 0) { sdsfree(ts); goto werr; }
        sdsfree(ts);
    }

    if (rewriteFunctions(aof) == 0) goto werr;

    for (j = 0; j < server.dbnum; j++) {
        char selectcmd[] = "*2\r\n$6\r\nSELECT\r\n";
        redisDb *db = server.db + j;
        if (kvstoreSize(db->keys) == 0) continue;

        /* SELECT the new DB */
        if (rioWrite(aof,selectcmd,sizeof(selectcmd)-1) == 0) goto werr;
        if (rioWriteBulkLongLong(aof,j) == 0) goto werr;

        kvs_it = kvstoreIteratorInit(db->keys);
        /* Iterate this DB writing every entry */
        while((de = kvstoreIteratorNext(kvs_it)) != NULL) {
            sds keystr;
            robj key, *o;
            long long expiretime;
            size_t aof_bytes_before_key = aof->processed_bytes;

            keystr = dictGetKey(de);
            o = dictGetVal(de);
            initStaticStringObject(key,keystr);

            expiretime = getExpire(db,&key);

            /* Save the key and associated value */
            if (o->type == OBJ_STRING) {
                /* Emit a SET command */
                char cmd[]="*3\r\n$3\r\nSET\r\n";
                if (rioWrite(aof,cmd,sizeof(cmd)-1) == 0) goto werr;
                /* Key and value */
                if (rioWriteBulkObject(aof,&key) == 0) goto werr;
                if (rioWriteBulkObject(aof,o) == 0) goto werr;
            } else if (o->type == OBJ_LIST) {
                if (rewriteListObject(aof,&key,o) == 0) goto werr;
            } else if (o->type == OBJ_SET) {
                if (rewriteSetObject(aof,&key,o) == 0) goto werr;
            } else if (o->type == OBJ_ZSET) {
                if (rewriteSortedSetObject(aof,&key,o) == 0) goto werr;
            } else if (o->type == OBJ_HASH) {
                if (rewriteHashObject(aof,&key,o) == 0) goto werr;
            } else if (o->type == OBJ_STREAM) {
                if (rewriteStreamObject(aof,&key,o) == 0) goto werr;
            } else if (o->type == OBJ_MODULE) {
                if (rewriteModuleObject(aof,&key,o,j) == 0) goto werr;
            } else {
                serverPanic("Unknown object type");
            }

            /* In fork child process, we can try to release memory back to the
             * OS and possibly avoid or decrease COW. We give the dismiss
             * mechanism a hint about an estimated size of the object we stored. */
            size_t dump_size = aof->processed_bytes - aof_bytes_before_key;
            if (server.in_fork_child) dismissObject(o, dump_size);

            /* Save the expire time */
            if (expiretime != -1) {
                char cmd[]="*3\r\n$9\r\nPEXPIREAT\r\n";
                if (rioWrite(aof,cmd,sizeof(cmd)-1) == 0) goto werr;
                if (rioWriteBulkObject(aof,&key) == 0) goto werr;
                if (rioWriteBulkLongLong(aof,expiretime) == 0) goto werr;
            }

            /* Update info every 1 second (approximately).
             * in order to avoid calling mstime() on each iteration, we will
             * check the diff every 1024 keys */
            if ((key_count++ & 1023) == 0) {
                long long now = mstime();
                if (now - updated_time >= 1000) {
                    sendChildInfo(CHILD_INFO_TYPE_CURRENT_INFO, key_count, "AOF rewrite");
                    updated_time = now;
                }
            }

            /* Delay before next key if required (for testing) */
            if (server.rdb_key_save_delay)
                debugDelay(server.rdb_key_save_delay);
        }
        kvstoreIteratorRelease(kvs_it);
    }
    return C_OK;

werr:
    if (kvs_it) kvstoreIteratorRelease(kvs_it);
    return C_ERR;
}
```

### load AOF

只要开启了 AOF 持久化，并且提供了正常的 appendonly.aof 文件，在 Redis 启动时就会自动加载 AOF 文件并启动。

在 AOF 开启的情况下，即使 AOF 文件不存在，只有 RDB 文件，也不会加载 RDB 文件。

重放追加日志文件。成功返回 C_OK。非致命错误（追加文件长度为零）返回 C_ERR。致命错误时记录错误信息并退出程序。

Redis 判断 AOF 文件的开头是否是 RDB 格式的，是通过关键字 `REDIS` 判断的，RDB 文件的开头一定是 `REDIS` 关键字开头的。

```c
/* Load the AOF files according the aofManifest pointed by am. */
int loadAppendOnlyFiles(aofManifest *am) {
    serverAssert(am != NULL);
    int status, ret = AOF_OK;
    long long start;
    off_t total_size = 0, base_size = 0;
    sds aof_name;
    int total_num, aof_num = 0, last_file;

    /* If the 'server.aof_filename' file exists in dir, we may be starting
     * from an old redis version. We will use enter upgrade mode in three situations.
     *
     * 1. If the 'server.aof_dirname' directory not exist
     * 2. If the 'server.aof_dirname' directory exists but the manifest file is missing
     * 3. If the 'server.aof_dirname' directory exists and the manifest file it contains
     *    has only one base AOF record, and the file name of this base AOF is 'server.aof_filename',
     *    and the 'server.aof_filename' file not exist in 'server.aof_dirname' directory
     * */
    if (fileExist(server.aof_filename)) {
        if (!dirExists(server.aof_dirname) ||
            (am->base_aof_info == NULL && listLength(am->incr_aof_list) == 0) ||
            (am->base_aof_info != NULL && listLength(am->incr_aof_list) == 0 &&
             !strcmp(am->base_aof_info->file_name, server.aof_filename) && !aofFileExist(server.aof_filename)))
        {
            aofUpgradePrepare(am);
        }
    }

    if (am->base_aof_info == NULL && listLength(am->incr_aof_list) == 0) {
        return AOF_NOT_EXIST;
    }

    total_num = getBaseAndIncrAppendOnlyFilesNum(am);
    serverAssert(total_num > 0);

    /* Here we calculate the total size of all BASE and INCR files in
     * advance, it will be set to `server.loading_total_bytes`. */
    total_size = getBaseAndIncrAppendOnlyFilesSize(am, &status);
    if (status != AOF_OK) {
        /* If an AOF exists in the manifest but not on the disk, we consider this to be a fatal error. */
        if (status == AOF_NOT_EXIST) status = AOF_FAILED;

        return status;
    } else if (total_size == 0) {
        return AOF_EMPTY;
    }

    startLoading(total_size, RDBFLAGS_AOF_PREAMBLE, 0);

    /* Load BASE AOF if needed. */
    if (am->base_aof_info) {
        serverAssert(am->base_aof_info->file_type == AOF_FILE_TYPE_BASE);
        aof_name = (char*)am->base_aof_info->file_name;
        updateLoadingFileName(aof_name);
        base_size = getAppendOnlyFileSize(aof_name, NULL);
        last_file = ++aof_num == total_num;
        start = ustime();
        ret = loadSingleAppendOnlyFile(aof_name);
        if (ret == AOF_OK || (ret == AOF_TRUNCATED && last_file)) {
            serverLog(LL_NOTICE, "DB loaded from base file %s: %.3f seconds",
                aof_name, (float)(ustime()-start)/1000000);
        }

        /* If the truncated file is not the last file, we consider this to be a fatal error. */
        if (ret == AOF_TRUNCATED && !last_file) {
            ret = AOF_FAILED;
            serverLog(LL_WARNING, "Fatal error: the truncated file is not the last file");
        }

        if (ret == AOF_OPEN_ERR || ret == AOF_FAILED) {
            goto cleanup;
        }
    }

    /* Load INCR AOFs if needed. */
    if (listLength(am->incr_aof_list)) {
        listNode *ln;
        listIter li;

        listRewind(am->incr_aof_list, &li);
        while ((ln = listNext(&li)) != NULL) {
            aofInfo *ai = (aofInfo*)ln->value;
            serverAssert(ai->file_type == AOF_FILE_TYPE_INCR);
            aof_name = (char*)ai->file_name;
            updateLoadingFileName(aof_name);
            last_file = ++aof_num == total_num;
            start = ustime();
            ret = loadSingleAppendOnlyFile(aof_name);
            if (ret == AOF_OK || (ret == AOF_TRUNCATED && last_file)) {
                serverLog(LL_NOTICE, "DB loaded from incr file %s: %.3f seconds",
                    aof_name, (float)(ustime()-start)/1000000);
            }

            /* We know that (at least) one of the AOF files has data (total_size > 0),
             * so empty incr AOF file doesn't count as a AOF_EMPTY result */
            if (ret == AOF_EMPTY) ret = AOF_OK;

            /* If the truncated file is not the last file, we consider this to be a fatal error. */
            if (ret == AOF_TRUNCATED && !last_file) {
                ret = AOF_FAILED;
                serverLog(LL_WARNING, "Fatal error: the truncated file is not the last file");
            }

            if (ret == AOF_OPEN_ERR || ret == AOF_FAILED) {
                goto cleanup;
            }
        }
    }

    server.aof_current_size = total_size;
    /* Ideally, the aof_rewrite_base_size variable should hold the size of the
     * AOF when the last rewrite ended, this should include the size of the
     * incremental file that was created during the rewrite since otherwise we
     * risk the next automatic rewrite to happen too soon (or immediately if
     * auto-aof-rewrite-percentage is low). However, since we do not persist
     * aof_rewrite_base_size information anywhere, we initialize it on restart
     * to the size of BASE AOF file. This might cause the first AOFRW to be
     * executed early, but that shouldn't be a problem since everything will be
     * fine after the first AOFRW. */
    server.aof_rewrite_base_size = base_size;

cleanup:
    stopLoading(ret == AOF_OK || ret == AOF_TRUNCATED);
    return ret;
}
```

## mix

**混合持久化优点：**

- 混合持久化结合了 RDB 和 AOF 持久化的优点，开头为 RDB 的格式，使得 Redis 可以更快的启动，同时结合 AOF 的优点，又减低了大量数据丢失的风险。

**混合持久化缺点：**

- AOF 文件中添加了 RDB 格式的内容，使得 AOF 文件的可读性变得很差；
- 兼容性差，如果开启混合持久化，那么此混合持久化 AOF 文件，就不能用在 Redis 4.0 之前版本了。

查询是否开启混合持久化可以使用 `config get aof-use-rdb-preamble` 命令。

Redis 5.0 默认是开启的。

在开启混合持久化的情况下，AOF 重写时会把 Redis 的持久化数据，以 RDB 的格式写入到 AOF 文件的开头，之后的数据再以 AOF 的格式化追加的文件的末尾。

## Interactions

Redis >= 2.4 确保在 RDB 快照操作已在进行中时避免触发 AOF 重写，或者在 AOF 重写进行中时避免允许 BGSAVE。
这防止了两个 Redis 后台进程同时执行繁重的磁盘 I/O。

当快照正在进行且用户使用 `BGREWRITEAOF` 明确请求日志重写操作时，服务器将回复 OK 状态码，告诉用户操作已安排，重写将在快照完成后开始。

如果同时启用 AOF 和 RDB 持久化，Redis 重启时将使用 AOF 文件重建原始数据集，因为它被保证是最完整的。

## Summary

关于 AOF 和 RDB 的选择：

- 数据不能丢失时，内存快照和 AOF 的混合使用是一个很好的选择；
- 如果允许分钟级别的数据丢失，可以只使用 RDB；
- 如果只用 AOF，优先使用 everysec 的配置选项，因为它在可靠性和性能之间取了一个平衡。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)

## References

1. [Redis Persistence](https://redis.io/topics/persistence)
