## Introduction

perf在采样的过程大概分为两步，一是调用 perf_event_open 来打开一个 event 文件，而是调用 read、mmap等系统调用读取内核采样回来的数据


perf_event_open 完成了非常重要的几项工作

- 创建各种event内核对象
- 创建各种event文件句柄
- 指定采样处理回调

在 perf_event_open 调用的 perf_event_alloc 指定了采样处理回调函数为，比如perf_event_output_backward、perf_event_output_forward等

```c
/*
 * Allocate and initialize an event structure
 */
static struct perf_event *
perf_event_alloc(struct perf_event_attr *attr, int cpu,
         struct task_struct *task,
         struct perf_event *group_leader,
         struct perf_event *parent_event,
         perf_overflow_handler_t overflow_handler,
         void *context, int cgroup_fd)
{
    struct pmu *pmu;
    struct perf_event *event;
    struct hw_perf_event *hwc;
    long err = -EINVAL;

    if ((unsigned)cpu >= nr_cpu_ids) {
        if (!task || cpu != -1)
            return ERR_PTR(-EINVAL);
    }

    event = kzalloc(sizeof(*event), GFP_KERNEL);
    if (!event)
        return ERR_PTR(-ENOMEM);

    /*
     * Single events are their own group leaders, with an
     * empty sibling list:
     */
    if (!group_leader)
        group_leader = event;

    mutex_init(&event->child_mutex);
    INIT_LIST_HEAD(&event->child_list);

    INIT_LIST_HEAD(&event->event_entry);
    INIT_LIST_HEAD(&event->sibling_list);
    INIT_LIST_HEAD(&event->active_list);
    init_event_group(event);
    INIT_LIST_HEAD(&event->rb_entry);
    INIT_LIST_HEAD(&event->active_entry);
    INIT_LIST_HEAD(&event->addr_filters.list);
    INIT_HLIST_NODE(&event->hlist_entry);


    init_waitqueue_head(&event->waitq);
    event->pending_disable = -1;
    init_irq_work(&event->pending, perf_pending_event);

    mutex_init(&event->mmap_mutex);
    raw_spin_lock_init(&event->addr_filters.lock);

    atomic_long_set(&event->refcount, 1);
    event->cpu      = cpu;
    event->attr     = *attr;
    event->group_leader = group_leader;
    event->pmu      = NULL;
    event->oncpu        = -1;

    event->parent       = parent_event;

    event->ns       = get_pid_ns(task_active_pid_ns(current));
    event->id       = atomic64_inc_return(&perf_event_id);

    event->state        = PERF_EVENT_STATE_INACTIVE;

    if (task) {
        event->attach_state = PERF_ATTACH_TASK;
        /*
         * XXX pmu::event_init needs to know what task to account to
         * and we cannot use the ctx information because we need the
         * pmu before we get a ctx.
         */
        event->hw.target = get_task_struct(task);
    }

    event->clock = &local_clock;
    if (parent_event)
        event->clock = parent_event->clock;

    if (!overflow_handler && parent_event) {
        overflow_handler = parent_event->overflow_handler;
        context = parent_event->overflow_handler_context;
#if defined(CONFIG_BPF_SYSCALL) && defined(CONFIG_EVENT_TRACING)
        if (overflow_handler == bpf_overflow_handler) {
            struct bpf_prog *prog = parent_event->prog;

            bpf_prog_inc(prog);
            event->prog = prog;
            event->orig_overflow_handler =
                parent_event->orig_overflow_handler;
        }
#endif
    }

    if (overflow_handler) {
        event->overflow_handler = overflow_handler;
        event->overflow_handler_context = context;
    } else if (is_write_backward(event)){
        event->overflow_handler = perf_event_output_backward;
        event->overflow_handler_context = NULL;
    } else {
        event->overflow_handler = perf_event_output_forward;
        event->overflow_handler_context = NULL;
    }

    perf_event__state_init(event);

    pmu = NULL;

    hwc = &event->hw;
    hwc->sample_period = attr->sample_period;
    if (attr->freq && attr->sample_freq)
        hwc->sample_period = 1;
    hwc->last_period = hwc->sample_period;

    local64_set(&hwc->period_left, hwc->sample_period);

    /*
     * We currently do not support PERF_SAMPLE_READ on inherited events.
     * See perf_output_read().
     */
    if (attr->inherit && (attr->sample_type & PERF_SAMPLE_READ))
        goto err_ns;

    if (!has_branch_stack(event))
        event->attr.branch_sample_type = 0;

    pmu = perf_init_event(event);
    if (IS_ERR(pmu)) {
        err = PTR_ERR(pmu);
        goto err_ns;
    }

    /*
     * Disallow uncore-cgroup events, they don't make sense as the cgroup will
     * be different on other CPUs in the uncore mask.
     */
    if (pmu->task_ctx_nr == perf_invalid_context && cgroup_fd != -1) {
        err = -EINVAL;
        goto err_pmu;
    }

    if (event->attr.aux_output &&
        !(pmu->capabilities & PERF_PMU_CAP_AUX_OUTPUT)) {
        err = -EOPNOTSUPP;
        goto err_pmu;
    }

    if (cgroup_fd != -1) {
        err = perf_cgroup_connect(cgroup_fd, event, attr, group_leader);
        if (err)
            goto err_pmu;
    }

    err = exclusive_event_init(event);
    if (err)
        goto err_pmu;

    if (has_addr_filter(event)) {
        event->addr_filter_ranges = kcalloc(pmu->nr_addr_filters,
                            sizeof(struct perf_addr_filter_range),
                            GFP_KERNEL);
        if (!event->addr_filter_ranges) {
            err = -ENOMEM;
            goto err_per_task;
        }

        /*
         * Clone the parent's vma offsets: they are valid until exec()
         * even if the mm is not shared with the parent.
         */
        if (event->parent) {
            struct perf_addr_filters_head *ifh = perf_event_addr_filters(event);

            raw_spin_lock_irq(&ifh->lock);
            memcpy(event->addr_filter_ranges,
                   event->parent->addr_filter_ranges,
                   pmu->nr_addr_filters * sizeof(struct perf_addr_filter_range));
            raw_spin_unlock_irq(&ifh->lock);
        }

        /* force hw sync on the address filters */
        event->addr_filters_gen = 1;
    }

    if (!event->parent) {
        if (event->attr.sample_type & PERF_SAMPLE_CALLCHAIN) {
            err = get_callchain_buffers(attr->sample_max_stack);
            if (err)
                goto err_addr_filters;
        }
    }

    err = security_perf_event_alloc(event);
    if (err)
        goto err_callchain_buffer;

    /* symmetric to unaccount_event() in _free_event() */
    account_event(event);

    return event;

err_callchain_buffer:
    if (!event->parent) {
        if (event->attr.sample_type & PERF_SAMPLE_CALLCHAIN)
            put_callchain_buffers();
    }
err_addr_filters:
    kfree(event->addr_filter_ranges);

err_per_task:
    exclusive_event_destroy(event);

err_pmu:
    if (is_cgroup_event(event))
        perf_detach_cgroup(event);
    if (event->destroy)
        event->destroy(event);
    module_put(pmu->module);
err_ns:
    if (event->ns)
        put_pid_ns(event->ns);
    if (event->hw.target)
        put_task_struct(event->hw.target);
    kfree(event);

    return ERR_PTR(err);
}
```





## Links

- [Tools](/docs/CS/OS/Linux/Tools/Tools.md)