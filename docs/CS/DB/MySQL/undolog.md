

purge


/** Start purge threads. During upgrade we start
purge threads early to apply purge. */
void srv_start_purge_threads() -> srv_purge_coordinator_thread() -> srv_do_purge() -> trx_purge()


```c

/* the number of pages to purge in one batch */
ulong srv_purge_batch_size = 20

ulint trx_purge(){
    // ...
    trx_sys->mvcc->clone_oldest_view(&purge_sys->view);
    
    /* Fetch the UNDO recs that need to be purged. */
    n_pages_handled = trx_purge_attach_undo_recs(n_purge_threads, batch_size);
 
    /* Submit the tasks to the work queue if n_pages_handled > 1. */
    
 }

```