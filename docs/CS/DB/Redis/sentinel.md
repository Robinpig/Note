## 简介

默认情况下，哨兵运行在 **TCP 端口 26379 上监听连接**，因此哨兵要正常工作，服务器的 26379 端口**必须开放**以接收其他哨兵实例 IP 地址的连接。
否则哨兵无法相互通信，无法就后续操作达成一致，因此永远不会执行故障转移。

实际上这意味着在故障期间，**如果大多数哨兵进程无法通信，哨兵永远不会启动故障转移**（即在少数分区中不进行故障转移）。

```
down-after-milliseconds
```

1. 如果副本优先级设置为 0，则该副本永远不会被提升为主库。
2. Sentinel 优先选择优先级数字*较低*的副本。

```
slave-priority
```

max

```
slave_repl_offset
```

min id

`__sentinel__:hello`

## 测试故障转移

此时我们的测试哨兵部署已准备好进行测试。
我们可以直接杀死主库并检查配置是否更改。
可以这样做：

```
redis-cli -p 6379 DEBUG sleep 30
```

此命令将使主库不再可达，休眠 30 秒。它模拟了主库因某种原因挂起。

如果检查哨兵日志，应该可以看到很多操作：

1. 每个哨兵通过 `+sdown` 事件检测到主库下线。
2. 此事件随后升级为 `+odown`，表示多个哨兵一致认为主库不可达。
3. 哨兵选举出一个哨兵来启动第一次故障转移尝试。
4. 故障转移发生。

如果再次询问 `mymaster` 的当前主库地址，最终应得到不同的回复：

```
127.0.0.1:5000> SENTINEL get-master-addr-by-name mymaster
1) "127.0.0.1"
2) "6380"
```

到此为止一切顺利...此时你可以去创建哨兵部署，或者继续阅读以了解所有哨兵命令和内部机制。

#### sentinelState

```c
struct sentinelState {
    char myid[CONFIG_RUN_ID_SIZE+1]; /* 此哨兵 ID */
    uint64_t current_epoch;         /* 当前纪元 */
    dict *masters;      /* 主库 sentinelRedisInstance 字典。
                           键是实例名称，值是 sentinelRedisInstance 结构指针。 */
    int tilt;           /* 是否处于 TILT 模式？ */
    int running_scripts;    /* 当前正在执行的脚本数 */
    mstime_t tilt_start_time;       /* TILT 开始时间 */
    mstime_t previous_time;         /* 上次运行时间处理程序的时间 */
    list *scripts_queue;            /* 要执行的用户脚本队列 */
    char *announce_ip;  /* 如果不为 NULL，向其他哨兵传播的 IP 地址 */
    int announce_port;  /* 如果不为零，向其他哨兵传播的端口 */
    unsigned long simfailure_flags; /* 故障模拟 */
    int deny_scripts_reconfig; /* 是否允许在运行时通过 SENTINEL SET ... 更改脚本路径？ */
    char *sentinel_auth_pass;    /* 用于对其他哨兵进行 AUTH 的密码 */
    char *sentinel_auth_user;    /* 用于对其他哨兵进行 ACLs AUTH 的用户名 */
    int resolve_hostnames;       /* 支持使用主机名，假设 DNS 配置良好 */
    int announce_hostnames;      /* 在有时宣布主机名而非 IP */
} sentinel;
```

#### sentinelRedisInstance

```c
typedef struct sentinelRedisInstance {
    int flags;      /* 参见 SRI_... 定义 */
    char *name;     /* 从此哨兵角度看的主库名称 */
    char *runid;    /* 此实例的运行 ID，如果是哨兵则为唯一 ID */
    uint64_t config_epoch;  /* 配置纪元 */
    sentinelAddr *addr; /* 主库主机 */
    instanceLink *link; /* 指向实例的链接，哨兵之间可能共享 */
    mstime_t last_pub_time;   /* 上次通过 Pub/Sub 发送 hello 的时间 */
    mstime_t last_hello_time; /* 仅当设置了 SRI_SENTINEL 时使用。上次通过 Pub/Sub
                                 从此哨兵接收 hello 的时间 */
    mstime_t last_master_down_reply_time; /* 上次回复 SENTINEL is-master-down 命令的时间 */
    mstime_t s_down_since_time; /* 主观下线开始时间 */
    mstime_t o_down_since_time; /* 客观下线开始时间 */
    mstime_t down_after_period; /* 经过此时间段后视为下线 */
    mstime_t info_refresh;  /* 上次从中接收 INFO 输出的时间 */
    dict *renamed_commands;     /* 此实例中重命名的命令：Sentinel 将使用此表上映射的替代命令
                                   发送 SLAVEOF、CONFIG、INFO 等 */

    /* 角色及首次观察到的时间。
     * 这用于延迟用我们自己的配置替换实例报告的内容。
     * 我们总是需要等待一段时间，给领导者报告新配置的机会，
     * 然后我们才做蠢事。 */
    int role_reported;
    mstime_t role_reported_time;
    mstime_t slave_conf_change_time; /* 上次从库主库地址更改时间 */

    /* 主库特定 */
    dict *sentinels;    /* 监控同一主库的其他哨兵 */
    dict *slaves;       /* 此主库实例的从库 */
    unsigned int quorum;/* 需要就故障达成一致的哨兵数 */
    int parallel_syncs; /* 同时重新配置的从库数 */
    char *auth_pass;    /* 用于对主库和副本进行 AUTH 的密码 */
    char *auth_user;    /* 用于对主库和副本进行 ACLs AUTH 的用户名 */

    /* 从库特定 */
    mstime_t master_link_down_time; /* 从库复制链接断开时间 */
    int slave_priority; /* 根据其 INFO 输出的从库优先级 */
    int replica_announced; /* 根据其 INFO 输出的副本宣告 */
    mstime_t slave_reconf_sent_time; /* 发送 SLAVE OF <new> 的时间 */
    struct sentinelRedisInstance *master; /* 如果是从库，则为对应主库实例 */
    char *slave_master_host;    /* INFO 报告的主库主机 */
    int slave_master_port;      /* INFO 报告的主库端口 */
    int slave_master_link_status; /* INFO 报告的主库链接状态 */
    unsigned long long slave_repl_offset; /* 从库复制偏移量 */
    /* 故障转移 */
    char *leader;       /* 如果这是主库实例，这是应执行故障转移的哨兵的 runid。
                           如果这是哨兵，这是此哨兵投票支持为领导者的哨兵的 runid。 */
    uint64_t leader_epoch; /* 'leader' 字段的纪元 */
    uint64_t failover_epoch; /* 当前启动的故障转移的纪元 */
    int failover_state; /* 参见 SENTINEL_FAILOVER_STATE_* 定义 */
    mstime_t failover_state_change_time;
    mstime_t failover_start_time;   /* 上次故障转移尝试开始时间 */
    mstime_t failover_timeout;      /* 刷新故障转移状态的最长时间 */
    mstime_t failover_delay_logged; /* 针对哪个 failover_start_time 值
                                       记录了故障转移延迟 */
    struct sentinelRedisInstance *promoted_slave; /* 被提升的从库实例 */
    /* 执行以通知管理员或重新配置客户端的脚本：当设置为 NULL 时不执行脚本 */
    char *notification_script;
    char *client_reconfig_script;
    sds info; /* 缓存的 INFO 输出 */
} sentinelRedisInstance;
```

## 定时器

由 serverCron 调用。

```c
void sentinelTimer(void) {
    sentinelCheckTiltCondition();
    sentinelHandleDictOfRedisInstances(sentinel.masters);
    sentinelRunPendingScripts();
    sentinelCollectTerminatedScripts();
    sentinelKillTimedoutScripts();

    /* 我们连续改变 Redis "定时器中断" 的频率
     * 以使每个 Sentinel 与其他去同步。
     * 这种非确定性避免了同时启动的 Sentinel
     * 完全相同步，在同一时间反复请求被投票
     * （导致因脑裂投票无人获胜）。 */
    server.hz = CONFIG_DEFAULT_HZ + rand() % CONFIG_DEFAULT_HZ;
}
```

```c
/* 每种实例 */
sentinelCheckSubjectivelyDown(ri);

 sentinelCheckObjectivelyDown(ri);
```

```c
/* 为具有 'req_runid' 的哨兵投票，如果已为指定的 'req_epoch' 或更大纪元投票过，
 * 则返回旧投票。
 *
 * 如果没有可用投票则返回 NULL，否则返回哨兵 runid 并填充 leader_epoch 为投票的纪元。 */
char *sentinelVoteLeader(sentinelRedisInstance *master, uint64_t req_epoch, char *req_runid, uint64_t *leader_epoch) {
    if (req_epoch > sentinel.current_epoch) {
        sentinel.current_epoch = req_epoch;
        sentinelFlushConfig();
        sentinelEvent(LL_WARNING,"+new-epoch",master,"%llu",
            (unsigned long long) sentinel.current_epoch);
    }

    if (master->leader_epoch < req_epoch && sentinel.current_epoch <= req_epoch)
    {
        sdsfree(master->leader);
        master->leader = sdsnew(req_runid);
        master->leader_epoch = sentinel.current_epoch;
        sentinelFlushConfig();
        sentinelEvent(LL_WARNING,"+vote-for-leader",master,"%s %llu",
            master->leader, (unsigned long long) master->leader_epoch);
        /* 如果没有投票给自己，则将主库故障转移开始时间设为现在，
         * 以强制延迟后再为同一主库启动故障转移。 */
        if (strcasecmp(master->leader,sentinel.myid))
            master->failover_start_time = mstime()+rand()%SENTINEL_MAX_DESYNC;
    }

    *leader_epoch = master->leader_epoch;
    return master->leader ? sdsnew(master->leader) : NULL;
}
```

### handleDict

对字典中的所有实例执行计划操作。
递归地针对从库字典调用函数。

```c
void sentinelHandleDictOfRedisInstances(dict *instances) {
    dictIterator *di;
    dictEntry *de;
    sentinelRedisInstance *switch_to_promoted = NULL;

    /* 需要对每个主库执行许多操作。 */
    di = dictGetIterator(instances);
    while((de = dictNext(di)) != NULL) {
        sentinelRedisInstance *ri = dictGetVal(de);

        sentinelHandleRedisInstance(ri);
        if (ri->flags & SRI_MASTER) {
            sentinelHandleDictOfRedisInstances(ri->slaves);
            sentinelHandleDictOfRedisInstances(ri->sentinels);
            if (ri->failover_state == SENTINEL_FAILOVER_STATE_UPDATE_CONFIG) {
                switch_to_promoted = ri;
            }
        }
    }
    if (switch_to_promoted)
        sentinelFailoverSwitchToPromotedSlave(switch_to_promoted);
    dictReleaseIterator(di);
}
```

## 处理

这是哨兵的"主"函数，哨兵设计为完全非阻塞。该函数每秒调用一次。

为指定的 Redis 实例执行计划操作。

```c
void sentinelHandleRedisInstance(sentinelRedisInstance *ri) {
    /* ========== 监控部分 ============ */
    /* 每种实例 */
    sentinelReconnectInstance(ri);
    sentinelSendPeriodicCommands(ri);

    /* ============== 动作部分 ============= */
    /* 如果在 TILT 模式，不执行动作部分。
     * TILT 发生在发现时间异常时，如时钟突变。 */
    if (sentinel.tilt) {
        if (mstime()-sentinel.tilt_start_time < SENTINEL_TILT_PERIOD) return;
        sentinel.tilt = 0;
        sentinelEvent(LL_WARNING,"-tilt",NULL,"#tilt mode exited");
    }

    sentinelCheckSubjectivelyDown(ri);

    /* 主库和从库 */
    if (ri->flags & (SRI_MASTER|SRI_SLAVE)) {
        /* 目前没有操作。 */
    }

    /* 仅主库 */
    if (ri->flags & SRI_MASTER) {
        sentinelCheckObjectivelyDown(ri);

        if (sentinelStartFailoverIfNeeded(ri))
            sentinelAskMasterStateToOtherSentinels(ri,SENTINEL_ASK_FORCED);
        sentinelFailoverStateMachine(ri);
        sentinelAskMasterStateToOtherSentinels(ri,SENTINEL_NO_FLAGS);
    }
}
```

#### sentinelStartFailoverIfNeeded

此函数检查是否存在启动故障转移的条件，即：

1. 主库必须处于 ODOWN 状态。
2. 没有已在进行的故障转移。
3. 最近没有已尝试过的故障转移。

我们仍不知道是否会赢得选举，因此可能启动故障转移但无法执行。

如果启动了故障转移则返回非零。

```c
int sentinelStartFailoverIfNeeded(sentinelRedisInstance *master) {
    /* 主库不在 O_DOWN 状态不能故障转移 */
    if (!(master->flags & SRI_O_DOWN)) return 0;
    /* 已在进行的故障转移？ */
    if (master->flags & SRI_FAILOVER_IN_PROGRESS) return 0;
    /* 上次故障转移尝试开始时间太近？ */
    if (mstime() - master->failover_start_time < master->failover_timeout*2)
    {
        if (master->failover_delay_logged != master->failover_start_time) {
            time_t clock = (master->failover_start_time + master->failover_timeout*2) / 1000;
            char ctimebuf[26];
            ctime_r(&clock,ctimebuf);
            ctimebuf[24] = '\0';
            master->failover_delay_logged = master->failover_start_time;
            serverLog(LL_WARNING,
                "Next failover delay: I will not start a failover before %s", ctimebuf);
        }
        return 0;
    }
    sentinelStartFailover(master);
    return 1;
}
```

如果我们认为主库已下线，开始向其他哨兵发送 SENTINEL IS-MASTER-DOWN-BY-ADDR 请求，以获取回复，达到标记主库为 ODOWN 状态并触发故障转移所需的法定人数。

```c
#define SENTINEL_ASK_FORCED (1<<0)
void sentinelAskMasterStateToOtherSentinels(sentinelRedisInstance *master, int flags) {
    // ...
}
```

#### 选举领导者

为具有 'req_runid' 的哨兵投票，如果已为指定的 'req_epoch' 或更大纪元投票过，则返回旧投票。
如果没有可用投票则返回 NULL，否则返回哨兵 runid 并填充 leader_epoch 为投票的纪元。

```c
char *sentinelVoteLeader(sentinelRedisInstance *master, uint64_t req_epoch, char *req_runid, uint64_t *leader_epoch) {
    // ...
}
```

## 故障转移

1. 在 Redis 集群中，当 sentinel 检测到 master 出现故障，那么 sentinel 需要对集群进行故障转移。
2. 当一个 sentinel 发现 master 下线，它会将下线的 master 确认为**主观下线**。
3. 当"法定个数"（quorum）sentinel 已经发现该 master 节点下线，那么 sentinel 会将其确认为**客观下线**。
4. 多个 sentinel 根据一定的逻辑，选举出一个 sentinel 作为 leader，由它去进行故障转移，将原来连接已客观下线 master 最优的一个 slave 提升为新 master 角色。旧 master 如果重新激活，它将被降级为 slave。

### 状态机

```c
void sentinelFailoverStateMachine(sentinelRedisInstance *ri) {
    serverAssert(ri->flags & SRI_MASTER);
    if (!(ri->flags & SRI_FAILOVER_IN_PROGRESS)) return;

    switch(ri->failover_state) {
        case SENTINEL_FAILOVER_STATE_WAIT_START:
            sentinelFailoverWaitStart(ri);
            break;
        case SENTINEL_FAILOVER_STATE_SELECT_SLAVE:
            sentinelFailoverSelectSlave(ri);
            break;
        case SENTINEL_FAILOVER_STATE_SEND_SLAVEOF_NOONE:
            sentinelFailoverSendSlaveOfNoOne(ri);
            break;
        case SENTINEL_FAILOVER_STATE_WAIT_PROMOTION:
            sentinelFailoverWaitPromotion(ri);
            break;
        case SENTINEL_FAILOVER_STATE_RECONF_SLAVES:
            sentinelFailoverReconfNextSlave(ri);
            break;
    }
}
```

### 故障转移-开始

```c
void sentinelFailoverWaitStart(sentinelRedisInstance *ri) {
    char *leader;
    int isleader;

    /* 检查我们是否是故障转移纪元的领导者 */
    leader = sentinelGetLeader(ri, ri->failover_epoch);
    isleader = leader && strcasecmp(leader,sentinel.myid) == 0;
    sdsfree(leader);

    /* 如果我不是领导者，且不是通过 SENTINEL FAILOVER 强制故障转移，
     * 则无法继续故障转移。 */
    if (!isleader && !(ri->flags & SRI_FORCE_FAILOVER)) {
        int election_timeout = SENTINEL_ELECTION_TIMEOUT;
        if (election_timeout > ri->failover_timeout)
            election_timeout = ri->failover_timeout;
        /* 如果经过一段时间后仍不是领导者，则中止故障转移 */
        if (mstime() - ri->failover_start_time > election_timeout) {
            sentinelEvent(LL_WARNING,"-failover-abort-not-elected",ri,"%@");
            sentinelAbortFailover(ri);
        }
        return;
    }
    // ... 继续故障转移
}
```

### 重新配置下一个从库

向所有仍显示未配置更新的其余从库发送 SLAVE OF <新主库地址>。

```c
void sentinelFailoverReconfNextSlave(sentinelRedisInstance *master) {
    // ...
}
```

## 集群

哨兵实例之间可以相互发现，要归功于 Redis 提供的 pub/sub 机制。

哨兵只要和主库建立起了连接，就可以在主库上发布消息了，比如说发布它自己的连接信息（IP 和端口）。
同时，它也可以从主库上订阅消息，获得其他哨兵发布的连接信息。当多个哨兵实例都在主库上做了发布和订阅操作后，它们之间就能知道彼此的 IP 地址和端口。
在主从集群中，主库上有一个名为"sentinel:hello"的频道，不同哨兵就是通过它来相互发现，实现互相通信的。

哨兵除了彼此之间建立起连接形成集群外，还需要和从库建立连接。这是因为，在哨兵的监控任务中，它需要对主从库都进行心跳判断，而且在主从库切换完成后，它还需要通知从库，让它们和新主库进行同步。
哨兵向主库发送 INFO 命令来获取从库信息。

我们可以依赖 pub/sub 机制，来帮助我们完成哨兵和客户端间的信息同步。
客户端读取哨兵的配置文件后，可以获得哨兵的地址和端口，和哨兵建立网络连接。我们可以在客户端执行订阅命令，来获取不同的事件消息。

要保证所有哨兵实例的配置是一致的，尤其是主观下线的判断值 down-after-milliseconds。

> 在我们的项目中，因为这个值在不同的哨兵实例上配置不一致，导致哨兵集群一直没有对有故障的主库形成共识，也就没有及时切换主库，最终的结果就是集群服务不稳定。

## 调优

- Redis 脑裂主要表现为：同一个 Redis 集群，原来的 master，经过故障转移后，出现多个 master。
- 解决方案主要通过 sentinel 哨兵的配置和 redis 的配置去解决问题。
- 上述方案也是有不足的地方，例如 Redis 配置限制可能会受到副本个数的影响，所以具体设置，要看具体的业务场景。主要是怎么通过比较小的代价去解决问题，或者降低出现问题的概率。
- Redis 虽然已经发布了 gossip 协议的无中心集群，sentinel 哨兵模式还是比较常用的，我们不建议直接使用 sentinel，可以考虑使用 codis。

## 链接

- [Redis](/docs/CS/DB/Redis/Redis.md)
