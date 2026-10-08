## Introduction

数据类型决定一列数据占多少字节、能存哪些值、边界在哪里，也决定索引前缀能有多长、行大小还剩多少预算、
排序与临时表要付多少代价。这页按「存储事实 + 常见误解」记录每种类型，重点是那些**写进 DDL 之后很难再改**的决定。
字段选型的团队约定（禁 TEXT、禁 ENUM、金额必须 DECIMAL 等）见 Links 里的 Database_Standards，
本页只解释这些约定背后的类型事实。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

字节数与取值范围以官方手册为准；跨版本有差异的地方在小节内就地标注版本坐标，不写无坐标的断言。

## Integer Types

MySQL 除 SQL 标准的 `INT` / `SMALLINT` 外，还扩展了 `TINYINT`、`MEDIUMINT`、`BIGINT`。

| 类型 | 字节 | Signed 范围 | Unsigned 范围 |
| :--- | :--- | :--- | :--- |
| `TINYINT` | 1 | -128 ~ 127 | 0 ~ 255 |
| `SMALLINT` | 2 | -32768 ~ 32767 | 0 ~ 65535 |
| `MEDIUMINT` | 3 | -8388608 ~ 8388607 | 0 ~ 16777215 |
| `INT`（`INTEGER`） | 4 | -2147483648 ~ 2147483647 | 0 ~ 4294967295 |
| `BIGINT` | 8 | -9223372036854775808 ~ 9223372036854775807 | 0 ~ 18446744073709551615 |

三个容易搞错的点：

- **占用只由类型决定**，与值的大小、与 `UNSIGNED` 都无关。`INT` 存 5 和存 2000000000 都是 4 字节；
  `UNSIGNED` 不省空间，只是把负数区间挪给正数（上限翻倍）。
- **超出范围的行为取决于 SQL mode**：严格模式下报 `1264 Out of range value`，非严格模式截断到边界值再给 warning。
  老库里静默截断会把「99999 写成 255」这类脏数据留进表里。
- **自增列写满之后不会回到 0 重来**。`AUTO_INCREMENT` 到达该类型上限后无法再分配新值，
  后续插入会反复尝试用最大值而持续报主键冲突，表现为「某一天起突然写不进」。
  容量规划要按上限留告警水位：`INT` 42.9 亿、`BIGINT` 的 2^63 实际上用不完。

### Display Width Is Not Storage Width

`INT(11)`、`TINYINT(4)` 括号里的数字是**显示宽度**，不改变存储字节，也不改变取值范围：
`INT(1)` 与 `INT(20)` 都是 4 字节、同一个上限。它只在和 `ZEROFILL` 一起出现时影响结果集里数字的对齐方式，
而 `ZEROFILL` 本身同样已废弃。

- `TINYINT(1)` 常被当成布尔用，但它只是「显示宽度写成 1 的 TINYINT」，实际能存 -128 ~ 127；
  `BOOL` / `BOOLEAN` 是 `TINYINT(1)` 的同义词，这一点至今没变。
- **MySQL 8.0.17 起同时废弃 `ZEROFILL` 与整型显示宽度**（WL #13127）。9.7 手册里这两项仍标注为
  deprecated 并预告后续版本会移除，所以语法还能解析，但不要再用。
  唯一保留显示宽度的场景是带 `AUTO_INCREMENT` 的 `BIGINT` 列。
- 同一批废弃还包括 `FLOAT` / `DOUBLE` / `DECIMAL` 上的 `UNSIGNED` 属性——`UNSIGNED` 只对整型继续有意义。
- 实践结论：新表直接写 `INT`、`BIGINT`，不要写 `INT(11)`；从旧 dump 迁来的 DDL 里带宽度，忽略即可。
  要对齐输出用 `LPAD()` 或直接把格式化结果存进 `CHAR`，而不是靠 `ZEROFILL`。

## Floating Point and Fixed Point

`FLOAT` 4 字节、`DOUBLE` 8 字节，都是**近似值**：二进制小数无法精确表示 0.1，
所以 `0.1 + 0.2` 与 `0.3` 用 `=` 比较可能不相等。

- 比较浮点要么按范围（`ABS(a - b) < eps`），要么把小数放大成整数存（金额按分计），后者也避开了 DECIMAL 的开销。
- `FLOAT(M,D)` / `DOUBLE(M,D)` 这类精度写法是 MySQL 扩展，语义依赖实现，新表不要依赖。

`DECIMAL(M,D)` 是**定点数**，按十进制精确存储，`SUM` / `AVG` 不引入二进制误差，因此金额与账务字段必须用它。

- `M` 是有效数字总位数（最多 65），`D` 是小数位数（不超过 30，且 `D` 计入 `M`）。
- 存储上整数部分与小数部分各自**每 9 位十进制数字占 4 字节**，不足 9 位按位数查表给 0 ~ 4 字节
  （精确对照表见官方手册，别按「1 字节 1 位」估算）。
- 超出 `M`/`D` 的能力范围同样是严格模式报错、非严格模式四舍五入或截断，行为与整型一致。

## String Types

`CHAR(M)` 与 `VARCHAR(M)` 的 M 都按**字符**计，但空间约束按**字节**结算，这是 utf8mb4 下最大的坑。

| 维度 | `CHAR(M)` | `VARCHAR(M)` |
| :--- | :--- | :--- |
| 长度 | 定长，最多 255 字符 | 变长，理论上限受行大小限制 |
| 额外开销 | 无长度前缀 | 1 字节长度前缀（实际字节数 < 256），否则 2 字节 |
| 存储上限 | M × 字符集最大字节数 | 见下方 65535 字节约束 |
| 尾部空格 | 检索时按排序规则的 PAD 属性处理 | 尾部空格保留 |

- **一行所有列共享 65535 字节上限**。`VARCHAR` 声明时按「M × 字符集最大字节数 + 长度前缀」折算：
  utf8mb4 每字符最多 4 字节，所以单列最大约 `VARCHAR(16383)`，再大就建不出来，只能转 `TEXT`。
- 尾部空格的行为还取决于排序规则是 `PAD SPACE` 还是 `NO PAD`。8.0 起的默认排序规则
  `utf8mb4_0900_ai_ci` 属于 `NO PAD`，尾部空格参与比较，这与旧的 `utf8_general_ci` / `utf8mb4_general_ci` 不同——
  升级排序规则时这是少数会改变查询结果的行为之一。
- `CHAR` 适合**长度基本固定**的短值（国家码、定长哈希前缀、状态码）；长度方差大时 `CHAR` 会为最长值付账。
- `BINARY(M)` / `VARBINARY(M)` 按**字节**计长，`BINARY` 右侧补 `0x00`；`binary` 排序规则属于
  `PAD SPACE`，比较时尾部补位不参与比较。适合存摘要、密文、UUID 的二进制形态。
- 字符集名 `utf8` 是 `utf8mb3` 的别名（每字符最多 3 字节，装不下 emoji 与部分生僻字）。
  新库直接写全 `utf8mb4`，不要写 `utf8`。索引前缀按字节算：InnoDB 16 KB 页在默认 `DYNAMIC` 行格式下
  单个索引键前缀上限 3072 字节，即 utf8mb4 下 768 个字符，长列要显式指定前缀长度。

## Text Types

`TEXT` 家族与对应的 `BLOB` 只差在「是否按字符集解释」，`BLOB` 是二进制字节串。

| 类型 | 最大长度（字节） | 典型用途 |
| :--- | :--- | :--- |
| `TINYTEXT` | 255 | 很少用，通常 `VARCHAR` 就够 |
| `TEXT` | 65535 | 正文、备注 |
| `MEDIUMTEXT` | 约 16 MB | 长文章、导出的 JSON |
| `LONGTEXT` | 约 4 GB | 极少该用，超限的交给对象存储 |

- 上限是**字节**而不是字符：utf8mb4 下 `TEXT` 最坏只能存约 16383 个字符。
- 索引 `TEXT` 列必须指定前缀长度（`KEY idx_col (col(64))`），无法整列建索引。
- InnoDB 的 `DYNAMIC` 行格式会把装不进数据页的大列**溢出到 off-page 页**，行内只留 20 字节指针，
  于是扫描该列要从 B-tree 页跳到溢出页，这是随机 IO 的主要来源之一（行格式细节见 InnoDB）。
- 自 MySQL 8.0.16 起，内部临时表的默认引擎从 `MEMORY` 换成 `TempTable`（`internal_tmp_mem_storage_engine`），
  含大字段的排序/分组落盘行为与 5.x 时代不同；跨版本对比慢查询时要把这一条算进变量。

## Date and Time Types

| 类型 | 字节 | 范围 / 语义 |
| :--- | :--- | :--- |
| `DATE` | 3 | 日期，无时间 |
| `TIME` | 3（含小数秒最多 6） | 时长或时刻，可负、可超过 24 小时 |
| `DATETIME` | 5（含小数秒最多 8） | 日期 + 时间，**不做时区转换** |
| `TIMESTAMP` | 4（含小数秒最多 7） | 日期 + 时间，**按会话时区转换** |
| `YEAR` | 1 | 只存年份，冷门，不建议用 |

`DATETIME` 与 `TIMESTAMP` 的区别是选型关键，不是「精度高低」：

- `TIMESTAMP` 内部存的是**自 1970-01-01 00:00:00 UTC 起的秒数**，写入时按会话 `time_zone` 转成 UTC，
  读出时再转回会话时区。因此它天然适合「同一份数据要给多个时区的客户端看」，
  但也意味着**改服务端时区或跨时区迁移会改变读出来的值**。
- `TIMESTAMP` 的范围是 `1970-01-01 00:00:01` UTC ~ `2038-01-19 03:14:07` UTC，
  即**躲不开 2038 问题**；超出范围（历史时间、很久以后）只能 `DATETIME`。
- `DATETIME` 存的就是字面值，与时区无关，范围大得多（到 `9999-12-31`），代价是它不携带任何时区信息，
  需要业务约定「这一列是 UTC 还是本地时间」并写进 `COMMENT`。
- 小数秒精度（`DATETIME(3)`）自 5.6.4 起支持，被占用的字节数随精度增加。
- 老资料里「第一个 TIMESTAMP 列自动带 `DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`」的隐式行为
  由 `explicit_defaults_for_timestamp` 控制：8.0 起它默认 `ON`（隐式默认不再成立），9.7 里已标记 Deprecated。
  需要自动更新时间就把子句显式写出来，不要依赖列的顺序。

## ENUM, SET, and Others

`ENUM` 按定义顺序存内部序号（1 起），存储 1 ~ 2 字节（成员数 ≤ 255 用 1 字节）。它的坑在于**序号参与语义**：

- `ORDER BY` 走的是定义顺序而不是字典序，`WHERE enum_col = 3` 会被解释成第 3 个成员，
  数字字面量与字符串字面量行为不一致。
- 调整成员顺序会改变已有数据的解释，新增成员通常只能追加在末尾，改定义要走 `ALTER TABLE`。
- 这也是规范建议用 `TINYINT` + 字典表或 `VARCHAR` 状态码替代 `ENUM` 的原因。

`SET` 是位图，最多 64 个成员（8 字节），判断包含要用 `FIND_IN_SET()` 或位运算，
`LIKE` 与 `=` 都不等于「包含」语义。成员顺序同样影响比较与排序。

其余不常展开的类型：

- `BIT(M)`：M ≤ 64，按位存储，读写要显式转成整数，可读性差，多数场景 `TINYINT UNSIGNED` 更好用。
- `JSON`：以二进制格式存储，读写可直接定位内部字段；不能直接建索引，
  要先把高频路径抽成生成列（`GENERATED ... STORED`）再索引。半结构化需求是否落到关系表，
  本质是「查询模式」问题而不是类型问题。
- 空间类型（`GEOMETRY` 及其子类）需要配套空间索引（`SPATIAL`），别混在通用业务表里当扩展字段用。

## Type Selection Summary

| 场景 | 建议 | 理由 |
| :--- | :--- | :--- |
| 主键 / 自增 ID | `BIGINT`（量小可 `INT`），`UNSIGNED` 视需要 | 上限决定写满时间，显示宽度无意义 |
| 金额、账务 | `DECIMAL(M,D)` | 二进制浮点无法精确表示十进制小数，`SUM` 误差不可对账 |
| 状态、开关 | `TINYINT UNSIGNED` + `COMMENT` 写字典 | 避开 `ENUM` 的序号语义与改定义的 `ALTER TABLE` |
| 事件发生时间 | `TIMESTAMP`（跨时区且不超过 2038）或 `DATETIME` | 区别在时区转换与范围，不在精度 |
| 定长短码（国家、币种） | `CHAR(n)` | 长度固定，省长度前缀，等值比较快 |
| 变长文本 | `VARCHAR(n)`，n 按真实上限给 | 行总长 65535 字节是共享预算，别习惯性写 1024 |
| 长文、附件 | `TEXT` / `BLOB`，或直接拆表、放对象存储 | 大列 off-page，扫描与临时表代价高 |
| 半结构化扩展 | `JSON` + 生成列索引，或扩展表 | 高频条件要能走索引，否则只剩全表扫描 |

## Links

- [MySQL Server](/docs/CS/DB/MySQL/MySQL.md)
- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Indexes](/docs/CS/DB/MySQL/Index.md)
- [SQL Execution](/docs/CS/DB/MySQL/SQL.md)
- [Database Standards](/docs/CS/DB/MySQL/Database_Standards.md)
- [Version Migration](/docs/CS/DB/MySQL/Version_Migration.md)

## References

- [Numeric Types](https://dev.mysql.com/doc/refman/9.7/en/numeric-types.html)
- [Numeric Type Attributes](https://dev.mysql.com/doc/refman/9.7/en/numeric-type-attributes.html)
- [The String Types CHAR, VARCHAR, BLOB, TEXT, ENUM, and SET](https://dev.mysql.com/doc/refman/9.7/en/string-types.html)
- [The BLOB and TEXT Types](https://dev.mysql.com/doc/refman/9.7/en/blob.html)
- [The ENUM and SET Types](https://dev.mysql.com/doc/refman/9.7/en/enum.html)
- [The Date and Time Types](https://dev.mysql.com/doc/refman/9.7/en/date-and-time-types.html)
- [Data Type Storage Requirements](https://dev.mysql.com/doc/refman/9.7/en/storage-requirements.html)
- [The Unicode Character Sets](https://dev.mysql.com/doc/refman/9.7/en/charset-unicode-utf8mb4.html)
- [Optimizing Data Types](https://dev.mysql.com/doc/refman/9.7/en/optimize-data-types.html)
