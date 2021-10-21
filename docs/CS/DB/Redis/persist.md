## Introduction


## RDB
save
bgsave
snapshot，
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


like binlog in MySQL

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
