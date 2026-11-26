# XA

## Introduction

XA 模式直接复用数据库原生的 **XA 协议**做两阶段提交：一阶段 `XA START/END/PREPARE`（预提交并持数据库锁），二阶段由 TC 下发 `XA COMMIT` / `XA ROLLBACK`。与 AT（一阶段本地提交 + undo_log）相反，XA 的资源锁持有到二阶段才释放，一致性最强但并发最差。XA 与 AT 共享同一套 TC/TM/RM 与 Netty 通道，差别只在 `BranchType` 与本地语义。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## DataSource Proxy

XA 数据源代理体系在 `rm-datasource/.../xa/`：

| 类 | 职责 |
| :--- | :--- |
| `DataSourceProxyXA` | 标准 XA 数据源代理，包装物理 `XADataSource` |
| `DataSourceProxyXANative` | 原生 XA 数据源代理（直连 `XADataSource`） |
| `AbstractDataSourceProxyXA` | 公共基类，继承 `BaseDataSourceResource<ConnectionProxyXA>` |
| `ConnectionProxyXA` | XA 连接代理，持有 `XAResource`，驱动 START/END/PREPARE/COMMIT/ROLLBACK |

代理入口与 AT 的 `DataSourceProxy` 平行，`DefaultResourceManager` 按 `BranchType` 选择对应资源管理器。

## Phase 1: Register First, Then XA START/END/PREPARE

**纠偏**：一阶段不是"先 prepare 后 register"。真实顺序是 `setAutoCommit(false)` 里**先向 TC branchRegister，再 XA START**；业务 SQL 执行后由连接 `close()` 完成 XA END + PREPARE。`ConnectionProxyXA.setAutoCommit` 的连续片段：

```java
// 1. register branch to TC then get the branch message
branchRegisterTime = System.currentTimeMillis();
branchId = DefaultResourceManager.get()
        .branchRegister(BranchType.XA, resource.getResourceId(), null, xid, null, null);
// 2. build XA-Xid with xid and branchId
this.xaBranchXid = XAXidBuilder.build(xid, branchId);
// Keep the Connection if necessary
keepIfNecessary();
try {
    start();
} catch (XAException e) {
    cleanXABranchContext();
    throw new SQLException("failed to start xa branch " + xid + " since " + e.getMessage(), e);
}
// 4. XA is active
this.xaActive = true;
```

`start()` 里根据库类型选事务标志（Oracle 用 `ORATRANSLOOSE`，其余 `TMNOFLAGS`）：

```java
if (JdbcConstants.ORACLE.equals(resource.getDbType())) {
    xaResource.start(this.xaBranchXid, SeataXAResource.ORATRANSLOOSE);
} else {
    xaResource.start(this.xaBranchXid, XAResource.TMNOFLAGS);
}
```

`close()` 里做 XA END(`TMSUCCESS`) → PREPARE；`XA_RDONLY` 时上报 `PhaseOne_RDONLY`，异常时 rollback 并上报 `PhaseOne_PrepareFailed`：

```java
if (xaActive && this.xaBranchXid != null) {
    // XA End: Success
    try {
        end(XAResource.TMSUCCESS);
    } catch (SQLException sqle) {
        throw new SQLException(
                "Branch " + xaBranchXid + " was rollbacked on committing since " + sqle.getMessage(),
                SQLSTATE_XA_NOT_END, sqle);
    }
    long now = System.currentTimeMillis();
    checkTimeout(now);
    setPrepareTime(now);
    int prepare = xaResource.prepare(xaBranchXid);
    if (prepare == XAResource.XA_RDONLY) {
        reportStatusToTC(BranchStatus.PhaseOne_RDONLY);
    }
}
```

注意：`ExecuteTemplateXA` 中注释写 "XA End & Prepare" 但调用的 `commit()` 只做 `xaActive` 校验，**真正的 end/prepare 在 `close()` 完成**——别被注释误导。

## Connection Hold Policy

XA 连接**不一定全程保持**：`shouldBeHeld()` 按库类型决定（MySQL < 8.0.29、获取版本失败、MariaDB、OSCAR 为 true，其余 PREPARE 后关闭物理连接）：

```java
if (DBType.MYSQL.name().equalsIgnoreCase(dbType)) {
    // SELECT VERSION() ...
    if (currentVersion < version) {  // version = 8.0.29
        setShouldBeHeld(true);
    }
} else if (DBType.MARIADB.name().equalsIgnoreCase(dbType)) {
    setShouldBeHeld(true);
} else if (DBType.OSCAR.name().equalsIgnoreCase(dbType)) {
    setShouldBeHeld(true);
}
```

`close()` 末尾据此决定是否关连接；保留的连接由 `ResourceManagerXA.getConnectionForXAFinish(xaBranchXid)` 在二阶段取回，且有 10s 两阶段保持超时（`DEFAULT_XA_CONNECTION_TWO_PHASE_HOLD_TIMEOUT = 10000`）强制关闭。

## Phase 2: Commit / Rollback

`ResourceManagerXA.branchCommit/branchRollback` 都走 `finishBranch(true/false, ...)`，取回 XA 连接后调 `xaCommit` / `xaRollback`：

```java
private BranchStatus finishBranch(
        boolean committed, BranchType branchType, String xid, long branchId,
        String resourceId, String applicationData) throws TransactionException {
    XAXid xaBranchXid = XAXidBuilder.build(xid, branchId);
    Resource resource = dataSourceCache.get(resourceId);
    if (resource instanceof AbstractDataSourceProxyXA) {
        try (ConnectionProxyXA connectionProxyXA =
                ((AbstractDataSourceProxyXA) resource).getConnectionForXAFinish(xaBranchXid)) {
            if (committed) {
                connectionProxyXA.xaCommit(xid, branchId, applicationData);
                return BranchStatus.PhaseTwo_Committed;
            } else {
                connectionProxyXA.xaRollback(xid, branchId, applicationData);
                return BranchStatus.PhaseTwo_Rollbacked;
            }
```

`xaRollback` 会显式 `xaEnd(xaXid, XAResource.TMFAIL)` 再 `xaResource.rollback(xaXid)`；`xaCommit` 用 `xaResource.commit(xaXid, false)`。

## XA vs AT

| 维度 | AT | XA |
| :--- | :--- | :--- |
| 一阶段本地事务 | 直接 commit（业务数据 + `undo_log` 同事务） | `XA START/END/PREPARE`，不 commit，持数据库锁 |
| 二阶段提交 | 异步删 `undo_log` | `XA COMMIT` |
| 二阶段回滚 | `undo_log` 反向补偿 | `XA ROLLBACK` |
| 资源锁持有 | 一阶段 commit 后即释放，只持全局锁 | PREPARE 到 COMMIT/ROLLBACK 全程持数据库锁（除 RDONLY / 连接不保持的库） |
| 数据库要求 | 本地 ACID + `undo_log` 表 | 驱动支持 XA（`XADataSource`） |
| 性能 | 高 | 差（锁到二阶段才释放） |

## Corrections

- **一阶段顺序是 register → XA START → 业务 SQL → XA END/PREPARE**，不是"先 PREPARE 后 register"。
- **连接不总是全程保持**：由 `shouldBeHeld()` 按库类型决定，MySQL ≥ 8.0.29 时 PREPARE 后关闭物理连接，二阶段用新连接。
- **XA 不是"Seata 自己实现两阶段"**：真正的 prepare/commit/rollback 由 `XAResource` 交给数据库，Seata 只做全局协调与分支注册，RM 侧不保存补偿日志。
- **"XA 性能极差"的根因**：资源锁从 PREPARE 持有到二阶段，长事务长时间阻塞并发——这是 XA 协议固有代价。
- **XA 一阶段失败/超时**：TC 长期不决策时 PREPARE 的资源锁不释放，需数据库 `xa_recover` / 事务超时介入，Seata RM 不主动回滚已 PREPARE 分支。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TCC](/docs/CS/Framework/Seata/TCC.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
