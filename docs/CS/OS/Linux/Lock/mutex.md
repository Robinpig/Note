## Introduction







Simple, straightforward mutexes with strict semantics:

- only one task can hold the mutex at a time
- only the owner can unlock the mutex
- multiple unlocks are not permitted
- recursive locking is not permitted
- a mutex object must be initialized via the API
- a mutex object must not be initialized via memset or copying
- task may not exit with mutex held
- memory areas where held locks reside must not be freed
- held mutexes must not be reinitialized
- mutexes may not be used in hardware or software interrupt contexts such as tasklets and timers

These semantics are fully enforced when DEBUG_MUTEXES is enabled. 
Furthermore, besides enforcing the above rules, the mutex debugging code also implements a number of additional features that make lock debugging easier and faster:

- uses symbolic names of mutexes, whenever they are printed in debug output
- point-of-acquire tracking, symbolic lookup of function names
- list of all locks held in the system, printout of them
- owner tracking
- detects self-recursing locks and prints out all relevant info
- detects multi-task circular deadlocks and prints out all affected locks and tasks (and only those tasks)

 ```c
struct mutex {
	atomic_long_t		owner;
	raw_spinlock_t		wait_lock;
#ifdef CONFIG_MUTEX_SPIN_ON_OWNER
	struct optimistic_spin_queue osq; /* Spinner MCS lock */
#endif
	struct list_head	wait_list;
#ifdef CONFIG_DEBUG_MUTEXES
	void			*magic;
#endif
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map	dep_map;
#endif
};
```


初始化