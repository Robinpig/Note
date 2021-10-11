

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
