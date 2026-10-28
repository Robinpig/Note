## Introduction

XXL-JOB 没有注册中心：执行器靠**周期性 HTTP 注册**向调度中心报活，调度中心靠**周期性扫表**剔除死机器。这个"心跳 + 扫表"的组合等价于 ZooKeeper 的临时节点，代价是有一致的延迟窗口，收益是不依赖任何外部组件。

两个时间常量决定全部行为（`com.xxl.job.core.constant.Const`）：

```java
public static final int BEAT_TIMEOUT = 30;                  // registry beat interval, default 30s
public static final int DEAD_TIMEOUT = BEAT_TIMEOUT * 3;    // registry dead timeout, default 90s
```

即：**30s 一次心跳，90s 没心跳判定死亡**。

源码基线 tag `3.5.0`。执行器侧的启动链路见 [Executor](/docs/CS/Framework/Job/xxl-job/Executor.md)，地址选出来之后怎么用见 [Route Strategy](/docs/CS/Framework/Job/xxl-job/Route_Strategy.md)。

## Two Tables

注册发现涉及两张表，职责完全不同：

| 表 | 谁写 | 语义 |
| :--- | :--- | :--- |
| `xxl_job_registry` | 执行器（经 `/api/registry`） | **自动注册**的在线机器表：`registry_group` = `EXECUTOR`、`registry_key` = appName、`registry_value` = 地址。唯一索引 `(g,k,v)` |
| `xxl_job_group` | 人工（管理后台）+ 监控线程 | 执行器清单：`address_type`（0 自动 / 1 手动）+ `address_list`（逗号分隔地址簿） |

路由时读的是 `XxlJobGroup.getRegistryList()`，而它其实是从 `address_list` 拆出来的：

```java
private List<String> registryList;
public List<String> getRegistryList() {
    if (StringTool.isNotBlank(addressList)) {
        registryList = StringTool.split(addressList, ",");
    }
    return registryList;
}
```

**关键点：`address_list` 是唯一的地址来源**，无论自动注册还是手动录入。自动注册模式下，监控线程把 `xxl_job_registry` 里聚合出来的在线地址**回写**进 `xxl_job_group.address_list`。所以：

- 手动录入（`address_type = 1`）：人工填 `address_list`，监控线程不碰它；
- 自动注册（`address_type = 0`）：`address_list` 由监控线程每 30s 覆盖刷新。

这给了"固定机器清单"与"弹性扩缩"两种接入方式，切换只需改 `address_type`。

## Executor Side

```java
registryThread = new CyclicThread("ExecutorRegistryThread#registryThread", true, new Runnable() {
    public void run() {
        RegistryRequest registryParam = new RegistryRequest(
                RegistTypeEnum.EXECUTOR.name(), xxlJobExecutor.getAppname(), xxlJobExecutor.getAddress());
        for (AdminBiz adminBiz: xxlJobExecutor.getAdminBizList()) {
            try {
                Response<String> registryResult = adminBiz.registry(registryParam);
                if (registryResult!=null && registryResult.isSuccess()) {
                    break;      // 任一调度中心成功即止
                }
            } catch (Throwable e) { ... }
        }
    }
}, Const.BEAT_TIMEOUT * 1000L, true);
```

注册线程每 30s 向**所有**调度中心地址发一次注册（保活），任一返回成功即 `break`。停机时 `stop()` 先停线程再发 `registryRemove` 摘除自己——这是优雅下线的关键动作，让调度中心不必等 90s 才发现机器没了。

注册内容是三元组：`(EXECUTOR, appName, address)`。`RegistTypeEnum` 里还有 `ADMIN` 类型（调度中心自注册，供管理后台展示），但当前只有 `EXECUTOR` 在跑。

> [!NOTE]
>
> `address` 默认形式是 `http://ip:port/`，由 `IPTool.getIp()` 探测本机网卡得出。多网卡 / 容器环境下探测可能选错网卡，此时必须显式配置 `xxl.job.executor.address`，否则调度中心拿到的地址连不上。

## Admin Side

### Write Path

```java
public Response<String> registry(RegistryRequest registryParam) {
    if (blank(group) || blank(key) || blank(value)) { return Response.ofFail("Illegal Argument."); }

    registryOrRemoveThreadPool.execute(new Runnable() {
        public void run() {
            // 0-fail; 1-save suc; 2-update suc;
            int ret = ...getXxlJobRegistryMapper().registrySaveOrUpdate(
                    registryParam.getRegistryGroup(), registryParam.getRegistryKey(),
                    registryParam.getRegistryValue(), new Date());
            if (ret == 1) {
                freshGroupRegistryInfo(registryParam);
            }
        }
    });

    return Response.ofSuccess();
}
```

注册/摘除走独立线程池（核心 2、最大 10、队列 2000），**入口立即返回成功**，落库异步。这里的拒绝策略是 `r.run()`（调用方线程直接执行），与执行器侧抛异常、调度中心侧丢弃都不同——注册是低频且必须完成的动作，宁可降级为同步也不丢。

`registrySaveOrUpdate` 返回码语义：`0` 失败、`1` 新增成功、`2` 更新成功。只有新增（`ret == 1`）才触发 `freshGroupRegistryInfo`，而该方法体是空的：

```java
private void freshGroupRegistryInfo(RegistryRequest registryParam){
    // Under consideration, prevent affecting core tables
}
```

注释写明是刻意留空——避免在高频注册路径上写核心表。新机器的可见性交给下面 30s 一轮的监控线程。

### Monitor Thread

```java
registryMonitorThread = new CyclicThread("JobRegistryHelper#registryMonitorThread", true, new Runnable() {
    public void run() {
        // 2.1、refresh auto-registry group
        List<XxlJobGroup> groupList = ...getXxlJobGroupMapper().findByAddressType(0);
        if (groupList!=null && !groupList.isEmpty()) {

            // a、remove dead address (admin/executor)
            List<Integer> ids = ...getXxlJobRegistryMapper().findDead(Const.DEAD_TIMEOUT, new Date());
            if (ids!=null && !ids.isEmpty()) {
                ...getXxlJobRegistryMapper().removeDead(ids);
            }

            // b、fresh online address (appname ： List<address>)
            List<XxlJobRegistry> list = ...getXxlJobRegistryMapper().findAll(Const.DEAD_TIMEOUT, new Date());
            HashMap<String, List<String>> appnameAddressMap = new HashMap<>();
            for (XxlJobRegistry item: list) {
                if (RegistTypeEnum.EXECUTOR.name().equals(item.getRegistryGroup())) {
                    ...appnameAddressMap.put(item.getRegistryKey(), registryList);
                }
            }

            // c、write group address
            for (XxlJobGroup group: groupList) {
                List<String> registryList = appnameAddressMap.get(group.getAppname());
                String addressListStr = null;
                if (CollectionTool.isNotEmpty(registryList)) {
                    Collections.sort(registryList);
                    addressListStr = StringTool.join(registryList, ",");
                }
                group.setAddressList(addressListStr);
                group.setUpdateTime(new Date());
                ...getXxlJobGroupMapper().update(group);
            }
        }

        // 2.2、refresh localcache
        ...
    }
}, Const.BEAT_TIMEOUT * 1000L, true);
```

一轮做三件事：剔除死亡记录 → 聚合在线地址 → 回写 `address_list`。三点值得注意：

- **`findDead` / `findAll` 都带 `DEAD_TIMEOUT` 参数**，即"只认 90s 内有心跳的记录"。所以即使剔除动作没跑，聚合出的地址列表本身也已是过滤过的。
- **`Collections.sort(registryList)`**：地址按字典序排序后再回写。这让 `FIRST` / `LAST` 路由的"第一个/最后一个"在集群内稳定一致，也让地址簿可读。
- **只对 `address_type = 0` 的组回写**（`findByAddressType(0)`），手动录入的组不受影响。

### Local Cache

3.5.0 新增了执行器清单的本地缓存，这是相对 2.x 的一处实质改动：

```java
private volatile Map<String, XxlJobGroup> appname2GroupCache = new ConcurrentHashMap<>();
private volatile Map<Integer, XxlJobGroup> id2GroupCache = new ConcurrentHashMap<>();

// 2.2、refresh localcache
List<XxlJobGroup> jobGroupList = ...getXxlJobGroupMapper().findAll();
Map<String, XxlJobGroup> appname2GroupCacheNew = new ConcurrentHashMap<>();
Map<Integer, XxlJobGroup> id2GroupCacheNew = new ConcurrentHashMap<>();
for (XxlJobGroup group: jobGroupList) {
    group.setUpdateTime(null);          // 排除 updateTime 干扰
    appname2GroupCacheNew.put(group.getAppname(), group);
    id2GroupCacheNew.put(group.getId(), group);
}
if (!GsonTool.toJson(appname2GroupCacheNew).equals(GsonTool.toJson(appname2GroupCache))) {
    appname2GroupCache = appname2GroupCacheNew;
    id2GroupCache = id2GroupCacheNew;
    logger.info("... detect changes and refresh JobGroupCache success ...");
}
```

两个缓存分别供 OpenAPI 鉴权（`loadByAppName`）与触发时加载（`load(id)`）使用。**每次触发不再查库**，直接读缓存。

变更检测用 `GsonTool.toJson` 全量序列化后比字符串——简单粗暴但对"执行器清单"这种小表足够，且避免了逐字段比较。注意 `group.setUpdateTime(null)` 是必需的：否则每轮监控线程写 `update_time` 都会让缓存看起来"变了"，导致每 30s 全量刷新一次。

缓存刷新周期是 30s，所以**修改执行器配置（如 accessToken、地址）最多 30s 后生效**。

## Failure Semantics

| 场景 | 表现 | 窗口 |
| :--- | :--- | :--- |
| 执行器进程 kill -9 | 无 `registryRemove`，靠 90s 超时剔除 | 最长 90s 内仍可能把请求发给死机器 |
| 执行器优雅停机 | 主动 `registryRemove`，但地址簿要等监控线程刷新 | 最长 30s 地址簿里仍有它 |
| 新执行器上线 | 注册落表，等监控线程聚合回写 | 最长 30s 参与路由 |
| 调度中心重启 | 注册表在 DB 里不丢，缓存重建 | 缓存重建是秒级 |
| 网络分区（执行器与 DB 通、与调度中心不通） | 无法注册 → 90s 后被剔除 | 任务在这台机器上"消失" |

这些窗口都不是精确值而是上界：剔除（90s）与聚合（30s）是两个独立周期，最坏情况叠加。

**被剔除后正在跑的任务不会受影响**——剔除只影响后续路由，已经在 `JobThread` 里的任务照常跑完并回调（回调失败会落盘重试）。

## Comparison

| 维度 | XXL-JOB（DB 心跳） | ZooKeeper / etcd（临时节点） |
| :--- | :--- | :--- |
| 依赖组件 | 无（复用 MySQL） | 需独立部署注册中心 |
| 死亡判定延迟 | 90s（3 × 心跳周期） | 秒级（session timeout） |
| 写压力 | 每机每 30s 一次 DB 写 | 依赖注册中心，无 DB 压力 |
| 规模上限 | 受 DB 写能力约束 | 万级节点无压力 |
| 一致性 | 各调度节点读同一张表，最终一致 | 注册中心保证 |

XXL-JOB 的选择与它"轻量、开箱即用"的定位一致：几百台执行器规模下，每 30s 一次 DB 写完全可以接受，换来的是运维上少一个组件。规模上到数千台时需要缩短 `BEAT_TIMEOUT` 或改走注册中心方案（此时更该考虑 PowerJob / ElasticJob）。

## Links

- [xxl-job](/docs/CS/Framework/Job/xxl-job.md)
- [Scheduler](/docs/CS/Framework/Job/xxl-job/Scheduler.md)
- [Trigger](/docs/CS/Framework/Job/xxl-job/Trigger.md)
- [Data Model](/docs/CS/Framework/Job/xxl-job/Data_Model.md)
- [OpenAPI](/docs/CS/Framework/Job/xxl-job/OpenAPI.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [XXL-JOB 官方文档](http://www.xuxueli.com/xxl-job/)
- [XXL-JOB GitHub](https://github.com/xuxueli/xxl-job)
