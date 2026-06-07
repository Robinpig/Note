## 简介

Undo Log 是逻辑日志。
**Undo Log 是逻辑日志，记录的是"在某个事务中做了什么修改操作的反向操作"**。

- Insert 操作的 Undo Log：记录主键信息。
- Delete 操作的 Undo Log：记录完整行的内容。
- Update 操作的 Undo Log：记录被修改列的旧值。

### MVCC 实现

Undo Log 通过版本链实现 MVCC，每条记录包含两个隐藏列：

- `DB_TRX_ID`：创建或最后修改该行的事务 ID。
- `DB_ROLL_PTR`：指向 Undo Log 的指针，形成版本链。

### ReadView

**ReadView** 是 MVCC 实现一致性读（consistent read）的核心：

- **m_ids**：生成 ReadView 时活跃的读写事务 ID 列表。
- **min_trx_id**：m_ids 中的最小事务 ID。
- **max_trx_id**：下一个要分配的事务 ID。
- **creator_trx_id**：创建该 ReadView 的事务 ID。

可见性判断：

1. 如果 `trx_id == creator_trx_id`，则本事务的修改可见。
2. 如果 `trx_id < min_trx_id`，则该版本在生成 ReadView 前已提交，可见。
3. 如果 `trx_id >= max_trx_id`，则该版本在生成 ReadView 后启动，不可见。
4. 如果 `min_trx_id <= trx_id < max_trx_id`，则检查 `trx_id` 是否在 m_ids 中：
   - 如果在 m_ids 中，则不可见（该事务在生成 ReadView 时仍活跃）。
   - 如果不在 m_ids 中，则可见（该事务在生成 ReadView 时已提交）。

### 隔离级别

| 隔离级别 | 实现方式 |
|---------|---------|
| READ UNCOMMITTED | 不检查 ReadView，直接读取最新版本 |
| READ COMMITTED | 每条语句生成新的 ReadView |
| REPEATABLE READ | 事务开始时生成 ReadView，事务结束前复用 |
| SERIALIZABLE | 使用锁实现 |

### Undo Log 类型

#### Insert Undo Log

在事务回滚中使用。

```c
struct trx_undo_insert_t {
    /* 表空间 ID */
    space_id_t space;
    /* 页面号 */
    page_no_t page_no;
    /* 偏移量 */
    ulint offset;
    /* 主键信息 */
    byte *primary_key;
    /* 主键长度 */
    ulint primary_key_len;
};
```

#### Update Undo Log

在事务回滚和 MVCC 中使用。

```c
struct trx_undo_update_t {
    /* 更新的列数 */
    ulint updated_columns;
    /* 主键信息 */
    byte *primary_key;
    /* 更新前每个列的值 */
    byte *old_values;
    /* 每个列的长度 */
    ulint *value_lengths;
    /* 事务 ID */
    trx_id_t trx_id;
    /* 回滚指针 */
    roll_ptr_t roll_ptr;
};
```

### Undo 表空间

Undo 表空间是 InnoDB 的存储区域，专门用于存储 Undo Log。

- 默认创建两个 Undo 表空间。
- 每个 Undo 表空间包含一个回滚段（Rollback Segment）。
- 每个回滚段包含多个 Undo Slot（默认为 1024 个）。
- 每个 Undo Slot 对应一个 Undo Segment。

### Undo 的物理结构

```c
struct trx_rseg_t {
    /* 回滚段 ID */
    ulint id;
    /* 回滚段所在表空间 ID */
    space_id_t space_id;
    /* 回滚段页面号 */
    page_no_t page_no;
    /* Undo Slot 数量 */
    ulint max_size;
    /* 当前使用的 Undo Slot */
    ulint curr_size;
    /* 最近的事务 ID */
    trx_id_t last_trx_id;
};
```

### Undo 生命周期

1. 事务开始时，分配 Undo Segment。
2. 事务执行过程中，将 Undo Log 写入 Undo Segment。
3. 事务提交后，Undo Log 可能被立即清理或保留（取决于是否有其他事务需要访问）。
4. 当所有需要该 Undo Log 的事务结束时，PURGE 线程将其清理。

#### Purge 线程

Purge 线程负责清理不再需要的 Undo Log：

1. 扫描 Undo Log。
2. 将 Undo Log 标记为可重用。
3. 回收 Undo Segment 空间。

## 配置

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `innodb_undo_tablespaces` | Undo 表空间数量 | 2 |
| `innodb_undo_log_truncate` | 是否启用 Undo 表空间截断 | OFF |
| `innodb_max_undo_log_size` | Undo 表空间最大大小 | 1GB |
| `innodb_purge_rseg_truncate_frequency` | Purge 线程截断频率 | 128 |

## 链接

- [MySQL InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [MySQL 事务](/docs/CS/DB/MySQL/Transaction.md)

## 参考

1. [MySQL 官方文档 - Undo Logs](https://dev.mysql.com/doc/refman/8.0/en/innodb-undo-logs.html)
