## Introduction

Redis provides a different range of persistence options:

- **RDB** (Redis Database): The RDB persistence performs point-in-time snapshots of your dataset at specified intervals.
- **AOF** (Append Only File): The AOF persistence logs every write operation received by the server, that will be played again at server startup, reconstructing the original dataset.
  Commands are logged using the same format as the Redis protocol itself, in an append-only fashion. Redis is able to [rewrite the log](/docs/CS/DB/Redis/persist.md?id=rewriting) in the background when it gets too big.
- **No persistence**: If you wish, you can disable persistence completely, if you want your data to just exist as long as the server is running.
- **RDB + AOF**: It is possible to combine both AOF and RDB in the same instance.
  Notice that, in this case, when Redis restarts the AOF file will be used to reconstruct the original dataset since it is guaranteed to be the most complete.

The most important thing to understand is the different trade-offs between the RDB and AOF persistence.

## RDB

RDB advantages:

- RDB is a very compact single-file point-in-time representation of your Redis data. RDB files are perfect for backups.
  For instance you may want to archive your RDB files every hour for the latest 24 hours, and to save an RDB snapshot every day for 30 days.
  This allows you to easily restore different versions of the data set in case of disasters.
- RDB is very good for disaster recovery, being a single compact file that can be transferred to far data centers, or onto Amazon S3 (possibly encrypted).
- RDB maximizes Redis performances since the only work the Redis parent process needs to do in order to persist is forking a child that will do all the rest.
  The parent instance will never perform disk I/O or alike.
- RDB allows faster restarts with big datasets compared to AOF.
- On replicas, RDB supports partial resynchronizations after restarts and failovers.

RDB disadvantages:

- RDB is NOT good if you need to minimize the chance of data loss in case Redis stops working (for example after a power outage).
  You can configure different *save points* where an RDB is produced (for instance after at least five minutes and 100 writes against the data set, but you can have multiple save points).
  However you'll usually create an RDB snapshot every five minutes or more, so in case of Redis stopping working without a correct shutdown for any reason you should be prepared to lose the latest minutes of data.
- RDB needs to fork() often in order to persist on disk using a child process.
  Fork() can be time consuming if the dataset is big, and may result in Redis to stop serving clients for some millisecond or even for one second if the dataset is very big and the CPU performance not great.
  AOF also needs to fork() but you can tune how often you want to rewrite your logs without any trade-off on durability.

By default Redis saves snapshots of the dataset on disk, in a binary file called `dump.rdb`.

You can configure Redis to have it save the dataset every N seconds if there are at least M changes in the dataset, or you can manually call the `SAVE` or `BGSAVE` commands.

For example, this configuration will make Redis automatically dump the dataset to disk every 60 seconds if at least 1000 keys changed:

```conf
save 60 1000
```

过于频繁的执行全量数据快照，有两个严重性能开销：

1. 频繁生成 RDB 文件写入磁盘，磁盘压力过大。会出现上一个 RDB 还未执行完，下一个又开始生成，陷入死循环。
2. fork 出 bgsave 子进程会阻塞主线程，主线程的内存越大，阻塞时间越长。

### save

Whenever Redis needs to dump the dataset to disk, this is what happens:

- Redis [forks](/docs/CS/OS/Linux/process.md?id=fork). We now have a child and a parent process.
- The child starts to write the dataset to a temporary RDB file.
- When the child is done writing the new RDB file, it replaces the old one.

This method allows Redis to benefit from **copy-on-write** semantics.



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


可以看见fork()函数的执行，在子进程中执行了rdbSave()函数，父进程则执行了一些设置状态的操作


#### rdbSaveBackground

`BGSAVE` command or serverCron

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

When a background RDB saving/transfer terminates, call the right handler.

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
刚开始生成一个临时的RDB文件，只有在执行成功后，才会进行rename操作，然后以写权限打开文件，然后调用了rdbSaveRio()函数将数据库的内容写到临时的RDB文件，
之后进行刷新缓冲区和同步操作，就关闭文件进行rename操作和更新服务器状态

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
rio是Redis抽象的IO层，它可以面向三种对象，分别是缓冲区，文件IO和socket IO

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

call `rdbSaveKeyValuePair`

一个空数据库持久化生成的dump.rdb文件，使用od -cx dump.rdb命令查看一下





### load RDB

#### loadDataFromDisk


在startup时被调用

优先AOF文件 没有AOF才加载RDB文件

load RDB or AOF file in memory.

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
            serverLog(LL_NOTICE,"DB loaded from disk: %.3f seconds",
                (float)(ustime()-start)/1000000);

            /* Restore the replication ID / offset from the RDB file. */
            if ((server.masterhost ||
                (server.cluster_enabled &&
                nodeIsSlave(server.cluster->myself))) &&
                rsi.repl_id_is_set &&
                rsi.repl_offset != -1 &&
                /* Note that older implementations may save a repl_stream_db
                 * of -1 inside the RDB file in a wrong way, see more
                 * information in function rdbPopulateSaveInfo. */
                rsi.repl_stream_db != -1)
            {
                memcpy(server.replid,rsi.repl_id,sizeof(server.replid));
                server.master_repl_offset = rsi.repl_offset;
                /* If we are a slave, create a cached master from this
                 * information, in order to allow partial resynchronizations
                 * with masters. */
                replicationCacheMasterUsingMyself();
                selectDb(server.cached_master,rsi.repl_stream_db);
            }
        } else if (errno != ENOENT) {
            serverLog(LL_WARNING,"Fatal error loading the DB: %s. Exiting.",strerror(errno));
            exit(1);
        }
    }
}
```

Load an RDB file from the rio stream 'rdb'. On success C_OK is returned, otherwise C_ERR is returned and 'errno' is set accordingly.

```c
int rdbLoadRio(rio *rdb, int rdbflags, rdbSaveInfo *rsi) {
```

## AOF

AOF advantages:

- Using AOF Redis is much more durable: you can have different fsync policies: no fsync at all, fsync every second, fsync at every query.
  With the default policy of fsync every second write performances are still great (fsync is performed using a background thread and the main thread will try hard to perform writes when no fsync is in progress.) but you can only lose one second worth of writes.
- The AOF log is an append only log, so there are no seeks, nor corruption problems if there is a power outage. 
  Even if the log ends with an half-written command for some reason (disk full or other reasons) the redis-check-aof tool is able to fix it easily.
- Redis is able to automatically rewrite the AOF in background when it gets too big.
  The rewrite is completely safe as while Redis continue
  s appending to the old file, a completely new one is produced with the minimal set of operations needed to create the current data set, and once this second file is ready Redis switches the two and starts appending to the new one.
- AOF contains a log of all the operations one after the other in an easy to understand and parse format.
  You can even easily export an AOF file.
  For instance even if you've accidentally flushed everything using the `FLUSHALL` command, as long as no rewrite of the log was performed in the meantime, you can still save your data set just by stopping the server, removing the latest command, and restarting Redis again.

AOF disadvantages:

- AOF files are usually bigger than the equivalent RDB files for the same dataset.
- AOF can be slower than RDB depending on the exact fsync policy. In general with fsync set to *every second* performance is still very high, and with fsync disabled it should be exactly as fast as RDB even under high load.
  Still RDB is able to provide more guarantees about the maximum latency even in the case of an huge write load.
- In the past we experienced rare bugs in specific commands (for instance there was one involving blocking commands like `BRPOPLPUSH`) causing the AOF produced to not reproduce exactly the same dataset on reloading.
  These bugs are rare and we have tests in the test suite creating random complex datasets automatically and reloading them to check everything is fine.
  However, these kind of bugs are almost impossible with RDB persistence.
  To make this point more clear: the Redis AOF works by incrementally updating an existing state, like MySQL or MongoDB does, while the RDB snapshotting creates everything from scratch again and again, that is conceptually more robust.

However

1. It should be noted that every time the AOF is rewritten by Redis it is recreated from scratch starting from the actual data contained in the data set, making resistance to bugs stronger compared to an always appending AOF file (or one rewritten reading the old AOF instead of reading the data in memory).
2. We have never had a single report from users about an AOF corruption that was detected in the real world.

**Redis < 7.0**

- AOF can use a lot of memory if there are writes to the database during a rewrite (these are buffered in memory and written to the new AOF at the end).
- All write commands that arrive during rewrite are written to disk twice.
- Redis could freeze writing and fsyncing these write commands to the new AOF file at the end of the rewrite.

You can turn on the AOF in your configuration file:

```
appendonly yes
```

From now on, every time Redis receives a command that changes the dataset (e.g. `SET`) it will append it to the AOF.
When you restart Redis it will re-play the AOF to rebuild the state like [binlog](/docs/CS/DB/MySQL/binlog.md) in MySQL



写后日志避免了额外的检查开销，不需要对执行的命令进行语法检查。如果使用写前日志的话，就需要先检查语法是否有误，否则日志记录了错误的命令，在使用日志恢复的时候就会出错。

AOF 日志是主线程执行，将日志写入磁盘过程中，如果磁盘压力大就会导致写磁盘很慢，导致后续的「写」指令阻塞。

Since Redis 7.0.0, Redis uses a multi part AOF mechanism.
That is, the original single AOF file is split into base file (at most one) and incremental files (there may be more than one).
The base file represents an initial (RDB or AOF format) snapshot of the data present when the AOF is rewritten.
The incremental files contains incremental changes since the last base AOF file was created. All these files are put in a separate directory and are tracked by a manifest file.

You can configure how many times Redis will `fsync` data on disk.
There are three options:

- `appendfsync always`: `fsync` every time new commands are appended to the AOF. Very very slow, very safe.
  Note that the commands are apended to the AOF after a batch of commands from multiple clients or a pipeline are executed, so it means a single write and a single fsync (before sending the replies).
- `appendfsync everysec`: `fsync` every second. Fast enough (in 2.4 likely to be as fast as snapshotting), and you can lose 1 second of data if there is a disaster.
- `appendfsync no`: Never `fsync`, just put your data in the hands of the Operating System. The faster and less safe method.
  Normally Linux will flush data every 30 seconds with this configuration, but it's up to the kernel exact tuning.

The suggested (and default) policy is to `fsync` every second. It is both very fast and pretty safe.
The `always` policy is very slow in practice, but it supports group commit, so if there are multiple parallel writes Redis will try to perform a single `fsync` operation.





AOF缓冲区是一个简单动态字符串（sds）
```c
// server.h
struct redisServer {
    sds aof_buf;      /* AOF buffer, written before entering the event loop */
}
```

### append

Propagate the specified command (in the context of the specified database id) to AOF and Slaves.
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

feedAppendOnlyFile创建一个空的简单动态字符串（sds），将当前所有追加命令操作都追加到这个sds中，最终将这个sds追加到`server.aof_buf`

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
Translate EXPIRE/PEXPIRE/EXPIREAT into PEXPIREAT
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
Append to the AOF buffer. This will be flushed on disk just before of re-entering the event loop, so before the client will get a positive reply about the operation performed.
```c
    if (server.aof_state == AOF_ON)
        server.aof_buf = sdscatlen(server.aof_buf,buf,sdslen(buf));
```
If a background append only file rewriting is in progress we want to accumulate the differences between the child DB and the current one in a buffer, so that when the child process will do its work we can append the differences to the new append only file.
```c
    if (server.child_type == CHILD_TYPE_AOF)
        aofRewriteBufferAppend((unsigned char*)buf,sdslen(buf));

    sdsfree(buf);
}
```

catAppendOnlyGenericCommand()函数实现了追加命令到缓冲区中

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

Max wait 2 seconds if sync_in_progress

Write the append only file buffer on disk.

Since we are required to write the AOF before replying to the client, and the only way the client socket can get a write is entering when the the event loop, we accumulate all the AOF writes in a memory buffer and write it on disk using this function just before entering the event loop again.

About the 'force' argument:

When the fsync policy is set to 'everysec' we may delay the flush if there is still an fsync() going on in the background thread, since for instance on Linux write(2) will be blocked by the background fsync anyway.
When this happens we remember that there is some aof buffer to be flushed ASAP, and will try to do that in the serverCron() function.

However if force is set to 1 we'll write regardless of the background fsync.

called by `serverCron` or `beforeSleep` or `prepareForShutdown`

```c
// aof
#define AOF_WRITE_LOG_ERROR_RATE 30 /* Seconds between errors logging. */
void flushAppendOnlyFile(int force) {
    ssize_t nwritten;
    int sync_in_progress = 0;
    mstime_t latency;

    if (sdslen(server.aof_buf) == 0) {
```
Check if we need to do fsync even the aof buffer is empty, because previously in AOF_FSYNC_EVERYSEC mode, fsync is called only when aof buffer is not empty, so if users stop write commands before fsync called in one second, the data in page cache cannot be flushed in time.
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

Re-use AOF buffer when it is small enough. The maximum comes from the arena size of 4k minus some overhead (but is otherwise arbitrary).

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




Log rewriting uses the same copy-on-write trick already in use for snapshotting. This is how it works:

**Redis >= 7.0**

* Redis [forks](/docs/CS/OS/Linux/process.md?id=fork), so now we have a child and a parent process.
* The child starts writing the new base AOF in a temporary file.
* The parent opens a new increments AOF file to continue writing updates. If the rewriting fails, the old base and increment files (if there are any) plus this newly opened increment file represent the complete updated dataset, so we are safe.
* When the child is done rewriting the base file, the parent gets a signal, and uses the newly opened increment file and child generated base file to build a temp manifest, and persist it.
* Profit! Now Redis does an atomic exchange of the manifest files so that the result of this AOF rewrite takes effect. Redis also cleans up the old base file and any unused increment files.

**Redis < 7.0**

* Redis [forks](/docs/CS/OS/Linux/process.md?id=fork), so now we have a child and a parent process.
* The child starts writing the new AOF in a temporary file.
* The parent accumulates all the new changes in an in-memory buffer (but at the same time it writes the new changes in the old append-only file, so if the rewriting fails, we are safe).
* When the child is done rewriting the file, the parent gets a signal, and appends the in-memory buffer at the end of the file generated by the child.
* Now Redis atomically renames the new file into the old one, and starts appending new data into the new file.

Whenever you issue a `BGREWRITEAOF` Redis will write the shortest sequence of commands needed to rebuild the current dataset in memory.



bgrewriteaof 

#### rewriteAppendOnlyFileBackground



call by:

1. startAppendOnly
2. bgrewriteaofCommand
3. serverCron

This is how rewriting of the append only file in background works:

1. The user calls `BGREWRITEAOF`
2. Redis calls this function, that forks():
   a. the child rewrite the append only file in a temp file.
   b. the parent accumulates differences in server.aof_rewrite_buf.
3. When the child finished '2a' exists.
4. The parent will trap the exit code, if it's OK, will append the data accumulated into server.aof_rewrite_buf into the temp file, and finally will rename(2) the temp file in the actual file name.
   The the new file is reopened as the new append only file. Profit!

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


Replay the append log file. On success C_OK is returned. On non fatal error (the append only file is zero-length) C_ERR is returned. On fatal error an error message is logged and the program exists.

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



## Interactions

Redis >= 2.4 makes sure to avoid triggering an AOF rewrite when an RDB snapshotting operation is already in progress, or allowing a BGSAVE while the AOF rewrite is in progress. 
This prevents two Redis background processes from doing heavy disk I/O at the same time.

When snapshotting is in progress and the user explicitly requests a log rewrite operation using `BGREWRITEAOF` the server will reply with an OK status code telling the user the operation is scheduled, and the rewrite will start once the snapshotting is completed.

In the case both AOF and RDB persistence are enabled and Redis restarts the AOF file will be used to reconstruct the original dataset since it is guaranteed to be the most complete.

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)

## References

1. [Redis Persistence](https://redis.io/topics/persistence)
