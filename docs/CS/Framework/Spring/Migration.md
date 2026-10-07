## Introduction

应用代码有 Git 管版本，**数据库 schema 却常常没有**。团队里最常见的代偿做法是维护一个共享的 `schema.sql` 或一份变更邮件：谁改了表结构就在里面加一段，靠人手工对齐各个环境。这套做法必然出问题：

- 测试库与生产库的实际结构悄悄分叉，测试通过的功能上线就报错；
- 新人拉代码后不知道该跑哪些脚本才能还原到当前结构；
- 谁也不敢删掉历史脚本，文件越堆越乱；
- 回滚时没人说得清目标版本对应的表结构长什么样。

**数据库迁移（database migration）工具**把这件事治理起来：schema 变更写成**带版本号、按序执行、且带校验和**的脚本文件，纳入代码仓库，由应用在启动（或专门的流水线阶段）自动执行到最新状态，并把执行历史记录在目标库的系统表里。

生态里主流两款：**Flyway**（SQL 优先，简单直接）与 **Liquibase**（抽象层优先，支持多 DSL 与回滚）。Spring Boot 对两者都有自动配置。

## Flyway vs Liquibase

| 维度 | Flyway | Liquibase |
| ---- | ---- | ---- |
| 编写方式 | 原生 SQL（`V1__xxx.sql`） | XML / YAML / JSON / SQL changelog |
| 心智成本 | 低，DBA 熟悉 | 稍高，要理解 changeset 抽象 |
| 跨数据库 | 差：SQL 方言不同就得写多份脚本 | 好：抽象层可翻译到不同方言 |
| 回滚 | 社区版无自动回滚（靠 `undo` 需付费版） | 支持 `rollback`（部分 change 类型） |
| 变更检测 | 靠 checksum 检测已执行脚本被篡改 | 靠 changeset 唯一 ID 追踪 |
| 适合 | 单一数据库类型、团队熟悉 SQL | 需要多环境多方言、需要回滚能力强 |

大多数 Spring 应用选 Flyway——够用且心智负担最小。

## Flyway Core Mechanism

### Migration Script Naming

```text
src/main/resources/db/migration/
├── V1__create_order_table.sql
├── V2__seed_orders.sql
├── V3__add_order_genre.sql
└── R__create_order_summary_view.sql
```

- **`V<版本>__<描述>.sql`：版本化迁移**，只跑一次，按版本号升序执行，执行后**不允许再修改**（checksum 校验，改了就拒绝启动）。这是"历史的一部分"。
- **`R__<描述>.sql`：可重复迁移**，在所有版本化迁移之后执行，**每次文件内容变化就重新执行一遍**。

两者的心智模型区别很关键：**版本化是历史的一步；可重复是期望的终态**。视图、函数、触发器、存储过程这类声明式对象适合用 `R__`——一次 `CREATE OR REPLACE VIEW` 就能表达最终形态，比堆一堆 `V8__tweak_view`、`V9__tweak_view_again` 干净得多。

### Execution History Table

Flyway 在目标库建一张 `flyway_schema_history`，每条记录含版本号、描述、checksum、执行时间、耗时、成功与否。正因为有这张表，Flyway 才知道"从哪里继续执行"。

```sql
select version, description, installed_on, success
from flyway_schema_history order by installed_rank;
```

> [!WARNING]
> **不要手工改这张表**，也不要"先把脚本改了再跑"——checksum 不匹配会直接导致启动失败，而且这是有意为之的保护。要修正历史脚本的错误，应当**再写一个新版本迁移**，而不是回头篡改已执行过的脚本。

### Module Split with Flyway 10+

Flyway 从 10 起把各数据库的特化实现拆成了独立模块（如 `flyway-database-postgresql`）。现代版本只引 `flyway-core` 往往会缺类型支持：

```xml
<dependency>
    <groupId>org.flywaydb</groupId>
    <artifactId>flyway-core</artifactId>
</dependency>
<dependency>
    <groupId>org.flywaydb</groupId>
    <artifactId>flyway-database-postgresql</artifactId>
</dependency>
```

## Liquibase Concepts

Liquibase 用 **changeset** 而非文件作为最小单位，每个 changeset 由 `id` + `author` + `file` 三元组唯一标识（因此文件名本身不带版本号）：

```yaml
databaseChangeLog:
  - changeSet:
      id: create-order-table
      author: alice
      changes:
        - createTable:
            tableName: orders
            columns:
              - column: { name: id, type: bigint, constraints: { primaryKey: true } }
              - column: { name: customer_id, type: varchar(100) }
  - changeSet:
      id: add-order-genre
      author: bob
      changes:
        - addColumn:
            tableName: orders
            columns:
              - column: { name: genre, type: varchar(100) }
```

执行历史落在 `DATABASECHANGELOG` 表（外加 Liquibase 用来加锁的 `DATABASECHANGELOGLOCK`）。回滚、tag、diff、按上下文（context）选择性执行都是 Liquibase 的强项。

## Boot 4 Pitfall: Must Use a Starter

> [!WARNING]
> Boot 4 把自动配置从单一的 `spring-boot-autoconfigure` 拆成了 70+ 个按技术划分的模块。这意味着：**仅仅把第三方 jar 放进 classpath 已经不足以触发自动配置**。
> Boot 3 时代，只要 `flyway-core` 在依赖里，Flyway 就会被自动装配；Boot 4 里 `FlywayAutoConfiguration` 已经搬到独立的 `spring-boot-flyway` 模块，**必须显式引入 starter** 才会把它拉进来。

失效的症状是彻底沉默的：应用正常启动、没有报错、没有 WARN，只是迁移一次都没跑，然后某张表不存在导致业务报错——排查方向很容易跑偏。

```xml
<!-- Boot 4 正确写法 -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-flyway</artifactId>
</dependency>
<!-- 或 -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-liquibase</artifactId>
</dependency>
```

测试环境同样按模块化规则配 `-test` 伴生包（`spring-boot-starter-flyway-test`），否则切片测试里会缺自动配置。

> [!TIP]
> 这条规律适用于 Boot 4 的所有"此前没有专属 starter"的技术。**行业级教训**：如果一个 Spring 集成"既没生效也没报错"，先检查 `spring-boot-starter-*` 是否到位，而不是只检查底层 jar。同类问题在 [Spring Batch 6](/docs/CS/Framework/Spring/Batch.md) 上也出现过——默认换成了内存 JobRepository，一样是静默失效。

## Relationship with JPA schema Generation

这条几乎是必踩：

```yaml
spring:
  jpa:
    hibernate:
      ddl-auto: none     # 生产必须 none / validate
  flyway:
    enabled: true
```

`ddl-auto` 的几个取值里，`update` 在开发期很方便，但它只做"加法"——加列、加表可以，**删列、改列类型、加约束都不会做**，而且既然它产出的结构与 Flyway 脚本未必一致，两边会慢慢分叉。

推荐分工：

| 环境 | schema 由谁负责 | `ddl-auto` |
| ---- | ---- | ---- |
| 本地开发 | Flyway/Liquibase（也可以临时 `create-drop` 图快） | `create-drop` 或 `none` |
| 测试 | Flyway/Liquibase | `none` |
| **生产** | **Flyway/Liquibase，且禁用 JPA 生成** | `none`（或 `validate` 做校对） |

`validate` 是个不错的中间选择：它让 Hibernate 启动时核对实体与表结构是否匹配，不匹配就启动失败——相当于给"迁移脚本忘了写"加了一道保险。

## Engineering Practice

| 主题 | 建议 |
| ---- | ---- |
| 脚本不可变 | 已执行过的版本化脚本禁止修改，修正靠新增迁移 |
| 多人并行 | 两个分支都加了 `V5__` 会冲突；约定版本用时间戳（`V202610031200__`）或合并时重编号 |
| 数据回填放哪 | 放在同一个迁移里：环境与代码保持一致，避免"C 改了表、漏了回填" |
| 破坏性变更 | 拆成多步发布：先加新列 → 双写 → 切读 → 删除旧列，不要一次迁移里 drop column |
| 大表 DDL | 了解目标库的 online DDL 能力（MySQL `ALGORITHM=INPLACE`、PG `CREATE INDEX CONCURRENTLY`），避免锁全表 |
| baseline | 存量库接入时用 `baseline-on-migrate: true` 先把当前状态标记为基线，避免首个迁移反复失败 |
| 谁来执行 | 生产建议由流水线/DBA 执行而非应用启动时自动跑，可控性更好 |

最后一点值得展开：自动迁移在启动时执行，意味着**部署即改表**。CI 环境下很方便，但生产里有几个隐患——多实例并发启动时谁来执行（需要锁，工具自带）、执行失败时是否允许应用继续启动、权限是否够。稳妥做法是让迁移成为流水线的独立阶段，应用启动只做 `validate`。

## Migration of Modular Projects

如果应用采用模块化组织（见 [Spring Modulith](/docs/CS/Framework/Spring/Modulith.md)），可以为**每个模块配独立的迁移脚本目录**——模块自己维护它的表结构，避免所有人往一个全局 `db/migration` 里挤。这是 Modulith 2.0 支持的能力。

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Data](/docs/CS/Framework/Spring/Data.md)
- [Spring Modulith](/docs/CS/Framework/Spring/Modulith.md)
- [Spring Testing](/docs/CS/Framework/Spring/Test.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)

## References

1. [Modularizing Spring Boot（Boot 4 模块化官方说明）](https://spring.io/blog/2025/10/28/modularizing-spring-boot)
2. [Spring Boot 4.0 Migration Guide](https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide)
3. [Flyway Documentation](https://documentation.red-gate.com/flyway)
4. [Liquibase Documentation](https://docs.liquibase.com/)
