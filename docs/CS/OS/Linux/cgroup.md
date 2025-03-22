## Introduction


"cgroup" stands for "control group" and is never capitalized.
The singular form is used to designate the whole feature and also as a qualifier as in "cgroup controllers".
When explicitly referring to multiple individual control groups, the plural form "cgroups" is used.

cgroup is a mechanism to organize processes hierarchically and distribute system resources along the hierarchy in a controlled and configurable manner.

cgroup is largely composed of two parts - the core and controllers.
cgroup core is primarily responsible for hierarchically organizing processes.
A cgroup controller is usually responsible for distributing a specific type of system resource along the hierarchy although there are utility controllers which serve purposes other than resource distribution.

cgroups form a tree structure and every process in the system belongs to one and only one cgroup.
All threads of a process belong to the same cgroup.
On creation, all processes are put in the cgroup that the parent process belongs to at the time.
A process can be migrated to another cgroup. Migration of a process doesn't affect already existing descendant processes.

Following certain structural constraints, controllers may be enabled or disabled selectively on a cgroup.
All controller behaviors are hierarchical - if a controller is enabled on a cgroup, it affects all processes which belong to the cgroups consisting the inclusive sub-hierarchy of the cgroup.
When a controller is enabled on a nested cgroup, it always restricts the resource distribution further.
The restrictions set closer to the root in the hierarchy can not be overridden from further away.

cgroups are, therefore, a facility built into the kernel that allow the administrator to set resource utilization limits on any process on the system.
In general, cgroups control:

- The number of CPU shares per process.
- The limits on memory per process.
- Block Device I/O per process.
- Which network packets are identified as the same type so that another application can enforce network traffic rules.

```shell
cd /sys/fs/cgroup/cpu,cpuacct
mkdir test
cd test
echo 100000 > cpu.cfs_period_us // 100ms 
echo 100000 > cpu.cfs_quota_us //200ms 
echo {$pid} > cgroup.procs
```

All cgroup_subsys_state(such as cpu, cpuset and memory) are inherited from different ancestors.

| cgroup_subsys_state type | ancestor |
| --- | --- |
| cpu |  task_group |
| memory | mem_cgroup |
| dev | dev_cgroup |


```c
struct cgroup {
	/* Private pointers for each registered subsystem */
	struct cgroup_subsys_state __rcu *subsys[CGROUP_SUBSYS_COUNT];
};  
```


Let's see the task_struct.

```c
struct task_struct {
  #ifdef CONFIG_CGROUPS
	/* Control Group info protected by css_set_lock: */
	struct css_set __rcu		*cgroups;
	/* cg_list protected by css_set_lock and tsk->alloc_lock: */
	struct list_head		cg_list;
#endif
}
```

A css_set is a structure holding pointers to a set of cgroup_subsys_state objects.
This saves space in the task struct object and speeds up `fork()`/`exit()`, since a single inc/dec and a list_add()/del() can bump the reference count on the entire cgroup set for a task.

```c
struct css_set {
	/*
	 * Set of subsystem states, one for each subsystem. This array is
	 * immutable after creation apart from the init_css_set during
	 * subsystem registration (at boot time).
	 */
	struct cgroup_subsys_state *subsys[CGROUP_SUBSYS_COUNT];
}    
```



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Container](/docs/CS/Container/Container.md)





