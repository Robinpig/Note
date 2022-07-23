## Introduction




Redis uses a persistence model based on the `fork()` system call in order to create a process with the same (shared) memory content of the main Redis process. 
This secondary process dumps the content of the memory on disk. 
This is used by `rdb.c` to create the snapshots on disk and by `aof.c` in order to perform the AOF rewrite when the append only file gets too big.

The implementation inside `aof.c` has additional functions in order to implement an API that allows commands to append new commands into the AOF file as clients execute them.

The `call()` function defined inside `server.c` is responsible for calling the functions that in turn will write the commands into the AOF.


Redis provides a different range of persistence options:

- **RDB** (Redis Database): The RDB persistence performs point-in-time snapshots of your dataset at specified intervals.
- **AOF** (Append Only File): The AOF persistence logs every write operation received by the server, that will be played again at server startup, reconstructing the original dataset. Commands are logged using the same format as the Redis protocol itself, in an append-only fashion. Redis is able to rewrite the log in the background when it gets too big.
- **No persistence**: If you wish, you can disable persistence completely, if you want your data to just exist as long as the server is running.
- **RDB + AOF**: It is possible to combine both AOF and RDB in the same instance. Notice that, in this case, when Redis restarts the AOF file will be used to reconstruct the original dataset since it is guaranteed to be the most complete.

The most important thing to understand is the different trade-offs between the RDB and AOF persistence. Let's start with RDB:

Redis uses a persistence model based on the `fork()`system call in order to create a thread with the same (shared) memory content of the main Redis thread. This secondary thread dumps the content of the memory on disk. This is used by `rdb.c` to create the snapshots on disk and by `aof.c` in order to perform the AOF rewrite when the append only file gets too big.

## RDB advantages

- RDB is a very compact single-file point-in-time representation of your Redis data. RDB files are perfect for backups. For instance you may want to archive your RDB files every hour for the latest 24 hours, and to save an RDB snapshot every day for 30 days. This allows you to easily restore different versions of the data set in case of disasters.
- RDB is very good for disaster recovery, being a single compact file that can be transferred to far data centers, or onto Amazon S3 (possibly encrypted).
- RDB maximizes Redis performances since the only work the Redis parent process needs to do in order to persist is forking a child that will do all the rest. The parent instance will never perform disk I/O or alike.
- RDB allows faster restarts with big datasets compared to AOF.
- On replicas, RDB supports [partial resynchronizations after restarts and failovers](https://redis.io/topics/replication#partial-resynchronizations-after-restarts-and-failovers).

## RDB disadvantages

- RDB is NOT good if you need to minimize the chance of data loss in case Redis stops working (for example after a power outage). You can configure different *save points* where an RDB is produced (for instance after at least five minutes and 100 writes against the data set, but you can have multiple save points). However you'll usually create an RDB snapshot every five minutes or more, so in case of Redis stopping working without a correct shutdown for any reason you should be prepared to lose the latest minutes of data.
- RDB needs to fork() often in order to persist on disk using a child process. Fork() can be time consuming if the dataset is big, and may result in Redis to stop serving clients for some millisecond or even for one second if the dataset is very big and the CPU performance not great. AOF also needs to fork() but you can tune how often you want to rewrite your logs without any trade-off on durability.

## AOF advantages

- Using AOF Redis is much more durable: you can have different fsync policies: no fsync at all, fsync every second, fsync at every query. With the default policy of fsync every second write performances are still great (fsync is performed using a background thread and the main thread will try hard to perform writes when no fsync is in progress.) but you can only lose one second worth of writes.
- The AOF log is an append only log, so there are no seeks, nor corruption problems if there is a power outage. Even if the log ends with an half-written command for some reason (disk full or other reasons) the redis-check-aof tool is able to fix it easily.
- Redis is able to automatically rewrite the AOF in background when it gets too big. The rewrite is completely safe as while Redis continues appending to the old file, a completely new one is produced with the minimal set of operations needed to create the current data set, and once this second file is ready Redis switches the two and starts appending to the new one.
- AOF contains a log of all the operations one after the other in an easy to understand and parse format. You can even easily export an AOF file. For instance even if you've accidentally flushed everything using the [FLUSHALL](https://redis.io/commands/flushall) command, as long as no rewrite of the log was performed in the meantime, you can still save your data set just by stopping the server, removing the latest command, and restarting Redis again.

## AOF disadvantages

- AOF files are usually bigger than the equivalent RDB files for the same dataset.
- AOF can be slower than RDB depending on the exact fsync policy. In general with fsync set to *every second* performance is still very high, and with fsync disabled it should be exactly as fast as RDB even under high load. Still RDB is able to provide more guarantees about the maximum latency even in the case of an huge write load.
- In the past we experienced rare bugs in specific commands (for instance there was one involving blocking commands like [BRPOPLPUSH](https://redis.io/commands/brpoplpush)) causing the AOF produced to not reproduce exactly the same dataset on reloading. These bugs are rare and we have tests in the test suite creating random complex datasets automatically and reloading them to check everything is fine. However, these kind of bugs are almost impossible with RDB persistence. To make this point more clear: the Redis AOF works by incrementally updating an existing state, like MySQL or MongoDB does, while the RDB snapshotting creates everything from scratch again and again, that is conceptually more robust. However - 1) It should be noted that every time the AOF is rewritten by Redis it is recreated from scratch starting from the actual data contained in the data set, making resistance to bugs stronger compared to an always appending AOF file (or one rewritten reading the old AOF instead of reading the data in memory). 2) We have never had a single report from users about an AOF corruption that was detected in the real world.
-

## RDB

By default Redis saves snapshots of the dataset on disk, in a binary file called `dump.rdb`. You can configure Redis to have it save the dataset every N seconds if there are at least M changes in the dataset, or you can manually call the [SAVE](https://redis.io/commands/save) or [BGSAVE](https://redis.io/commands/bgsave) commands.

For example, this configuration will make Redis automatically dump the dataset to disk every 60 seconds if at least 1000 keys changed:

```
save 60 1000
```

### How it works

Whenever Redis needs to dump the dataset to disk, this is what happens:

- Redis [forks](http://linux.die.net/man/2/fork). We now have a child and a parent process.
- The child starts to write the dataset to a temporary RDB file.
- When the child is done writing the new RDB file, it replaces the old one.

This method allows Redis to benefit from copy-on-write semantics.

SAVE use sync，BGSAVE create child process by calling fork() of glib.
file Name: dump.rdb

```c
int rdbSaveRio(rio *rdb, int *error, int rdbflags, rdbSaveInfo *rsi) {

}
```

call `rdbSaveKeyValuePair`

load RDB

Function called at startup to load RDB or AOF file in memory.

```c
void loadDataFromDisk(void) {
}
```

Load an RDB file from the rio stream 'rdb'. On success C_OK is returned, otherwise C_ERR is returned and 'errno' is set accordingly.

```c
int rdbLoadRio(rio *rdb, int rdbflags, rdbSaveInfo *rsi) {
```

## AOF

You can turn on the AOF in your configuration file:

```
appendonly yes
```

From now on, every time Redis receives a command that changes the dataset (e.g. [SET](https://redis.io/commands/set)) it will append it to the AOF. When you restart Redis it will re-play the AOF to rebuild the state like binlog in MySQL

### How durable is the append only file?

You can configure how many times Redis will [`fsync`](http://linux.die.net/man/2/fsync) data on disk. There are three options:

- `appendfsync always`: `fsync` every time new commands are appended to the AOF. Very very slow, very safe. Note that the commands are apended to the AOF after a batch of commands from multiple clients or a pipeline are executed, so it means a single write and a single fsync (before sending the replies).
- `appendfsync everysec`: `fsync` every second. Fast enough (in 2.4 likely to be as fast as snapshotting), and you can lose 1 second of data if there is a disaster.
- `appendfsync no`: Never `fsync`, just put your data in the hands of the Operating System. The faster and less safe method. Normally Linux will flush data every 30 seconds with this configuration, but it's up to the kernel exact tuning.

The suggested (and default) policy is to `fsync` every second. It is both very fast and pretty safe. The `always` policy is very slow in practice, but it supports group commit, so if there are multiple parallel writes Redis will try to perform a single `fsync` operation.

bgrewriteaof

```c
// server.h
struct redisServer {

    size_t stat_rdb_cow_bytes;      /* Copy on write bytes during RDB saving. */
    size_t stat_aof_cow_bytes;      /* Copy on write bytes during AOF rewrite. */
  
    /* AOF persistence */
    int aof_enabled;                /* AOF configuration */
    int aof_state;                  /* AOF_(ON|OFF|WAIT_REWRITE) */
    int aof_fsync;                  /* Kind of fsync() policy */
    char *aof_filename;             /* Name of the AOF file */
    int aof_no_fsync_on_rewrite;    /* Don't fsync if a rewrite is in prog. */
    int aof_rewrite_perc;           /* Rewrite AOF if % growth is > M and... */
    off_t aof_rewrite_min_size;     /* the AOF file is at least N bytes. */
    off_t aof_rewrite_base_size;    /* AOF size on latest startup or rewrite. */
    off_t aof_current_size;         /* AOF current size. */
    off_t aof_fsync_offset;         /* AOF offset which is already synced to disk. */
    int aof_flush_sleep;            /* Micros to sleep before flush. (used by tests) */
    int aof_rewrite_scheduled;      /* Rewrite once BGSAVE terminates. */
    list *aof_rewrite_buf_blocks;   /* Hold changes during an AOF rewrite. */
    sds aof_buf;      /* AOF buffer, written before entering the event loop */
    int aof_fd;       /* File descriptor of currently selected AOF file */
    int aof_selected_db; /* Currently selected DB in AOF */
    time_t aof_flush_postponed_start; /* UNIX time of postponed AOF flush */
    time_t aof_last_fsync;            /* UNIX time of last fsync() */
    time_t aof_rewrite_time_last;   /* Time used by last AOF rewrite run. */
    time_t aof_rewrite_time_start;  /* Current AOF rewrite start time. */
    int aof_lastbgrewrite_status;   /* C_OK or C_ERR */
    unsigned long aof_delayed_fsync;  /* delayed AOF fsync() counter */
    int aof_rewrite_incremental_fsync;/* fsync incrementally while aof rewriting? */
    int rdb_save_incremental_fsync;   /* fsync incrementally while rdb saving? */
    int aof_last_write_status;      /* C_OK or C_ERR */
    int aof_last_write_errno;       /* Valid if aof write/fsync status is ERR */
    int aof_load_truncated;         /* Don't stop on unexpected AOF EOF. */
    int aof_use_rdb_preamble;       /* Use RDB preamble on AOF rewrites. */
    redisAtomic int aof_bio_fsync_status; /* Status of AOF fsync in bio job. */
    redisAtomic int aof_bio_fsync_errno;  /* Errno of AOF fsync in bio job. */
    /* AOF pipes used to communicate between parent and child during rewrite. */
    int aof_pipe_write_data_to_child;
    int aof_pipe_read_data_from_parent;
    int aof_pipe_write_ack_to_parent;
    int aof_pipe_read_ack_from_child;
    int aof_pipe_write_ack_to_child;
    int aof_pipe_read_ack_from_parent;
    int aof_stop_sending_diff;     /* If true stop sending accumulated diffs
                                      to child process. */
    sds aof_child_diff;             /* AOF diff accumulator child side. */
    /* RDB persistence */
    long long dirty;                /* Changes to DB from the last save */
    long long dirty_before_bgsave;  /* Used to restore dirty on failed BGSAVE */
    struct saveparam *saveparams;   /* Save points array for RDB */
    int saveparamslen;              /* Number of saving points */
    char *rdb_filename;             /* Name of RDB file */
    int rdb_compression;            /* Use compression in RDB? */
    int rdb_checksum;               /* Use RDB checksum? */
    int rdb_del_sync_files;         /* Remove RDB files used only for SYNC if
                                       the instance does not use persistence. */
    time_t lastsave;                /* Unix time of last successful save */
    time_t lastbgsave_try;          /* Unix time of last attempted bgsave */
    time_t rdb_save_time_last;      /* Time used by last RDB save run. */
    time_t rdb_save_time_start;     /* Current RDB save start time. */
    int rdb_bgsave_scheduled;       /* BGSAVE when possible if true. */
    int rdb_child_type;             /* Type of save by active child. */
    int lastbgsave_status;          /* C_OK or C_ERR */
    int stop_writes_on_bgsave_err;  /* Don't allow writes if can't BGSAVE */
    int rdb_pipe_read;              /* RDB pipe used to transfer the rdb data */
                                    /* to the parent process in diskless repl. */
    int rdb_child_exit_pipe;        /* Used by the diskless parent allow child exit. */
    connection **rdb_pipe_conns;    /* Connections which are currently the */
    int rdb_pipe_numconns;          /* target of diskless rdb fork child. */
    int rdb_pipe_numconns_writing;  /* Number of rdb conns with pending writes. */
    char *rdb_pipe_buff;            /* In diskless replication, this buffer holds data */
    int rdb_pipe_bufflen;           /* that was read from the the rdb pipe. */
    int rdb_key_save_delay;         /* Delay in microseconds between keys while
                                     * writing the RDB. (for testings). negative
                                     * value means fractions of microsecons (on average). */
    int key_load_delay;             /* Delay in microseconds between keys while
                                     * loading aof or rdb. (for testings). negative
                                     * value means fractions of microsecons (on average). */
}                               
```

Replay the append log file. On success C_OK is returned. On non fatal error (the append only file is zero-length) C_ERR is returned. On fatal error an error message is logged and the program exists.

```c
int loadAppendOnlyFile(char *filename) {
```

write AOF

Write the append only file buffer on disk.

Since we are required to write the AOF before replying to the client, and the only way the client socket can get a write is entering when the the event loop, we accumulate all the AOF writes in a memory buffer and write it on disk using this function just before entering the event loop again.

About the 'force' argument:

When the fsync policy is set to 'everysec' we may delay the flush if there is still an fsync() going on in the background thread, since for instance on Linux write(2) will be blocked by the background fsync anyway.

When this happens we remember that there is some aof buffer to be flushed ASAP, and will try to do that in the serverCron() function.

However if force is set to 1 we'll write regardless of the background fsync.

called by `serverCron` or `beforeSleep` or `prepareForShutdown`

```c
#define AOF_WRITE_LOG_ERROR_RATE 30 /* Seconds between errors logging. */
void flushAppendOnlyFile(int force)

```

Max wait 2 seconds

```c
// aof.flushAppendOnlyFile
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
```

### Log rewriting

Whenever you issue a [BGREWRITEAOF](https://redis.io/commands/bgrewriteaof) Redis will write the shortest sequence of commands needed to rebuild the current dataset in memory.

call by:

1. startAppendOnly
2. bgrewriteaofCommand
3. serverCron

```c
rewriteAppendOnlyFileBackground
```

#### How it works

Log rewriting uses the same copy-on-write trick already in use for snapshotting. This is how it works:

- Redis [forks](http://linux.die.net/man/2/fork), so now we have a child and a parent process.
- The child starts writing the new AOF in a temporary file.
- The parent accumulates all the new changes in an in-memory buffer (but at the same time it writes the new changes in the old append-only file, so if the rewriting fails, we are safe).
- When the child is done rewriting the file, the parent gets a signal, and appends the in-memory buffer at the end of the file generated by the child.
- Profit! Now Redis atomically renames the old file into the new one, and starts appending new data into the new file.

### How to optimize

- avoid bigkey
- disable huge page

## References

1. [Redis Persistence](https://redis.io/topics/persistence)
