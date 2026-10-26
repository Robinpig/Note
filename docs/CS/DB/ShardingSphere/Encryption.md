## Introduction

数据安全在 ShardingSphere 里是两块独立规则：**加密（`!ENCRYPT`）**管存储——库里存密文、用时解密；**脱敏（`!MASK`）**管展示——查出来就是掩码，不可逆。两者都透明叠加在 SQL 链路上，业务不感知。本页讲内置算法清单、辅助查询机制与在线改造的真实复杂度。

## Two Rules, Two Semantics

| | 加密（encrypt） | 脱敏（mask） |
| :--- | :--- | :--- |
| 存储 | 密文 | 原值或掩码，按配置 |
| 可逆 | 可逆（配了密钥就能解） | 不可逆（MD5 等单向） |
| 用途 | 合规存储：手机号、身份证、卡号落库前加密 | 展示保护：日志、后台、导出场景 |
| 规则名 | `!ENCRYPT` | `!MASK` |

别把脱敏当加密用：脱敏算法不可逆，只能挡「看见」，挡不住「需要还原」的场景。

## Encryption Algorithms

`EncryptAlgorithm` SPI 的内置实现当前只有两条：

| type | 语义 |
| :--- | :--- |
| `AES` | AES 标准加密，配 `aes-key-value` 等属性 |
| `MD5` | **辅助查询**用的单向摘要加密算法 |

也就是说 5.5 的内置加密算法清单**只有 AES 与 MD5 两条实现**——4.x 时代文档里的 RC4 等算法不在当前清单中，迁移时别按旧文档配 `type: RC4`。

## Assisted Query

加密列做等值查询有个死结：密文是无序的，`WHERE phone = '138...'` 在密文上直接匹配不到。解法是**辅助查询列**：

- 表上加一个辅助列，保存明文的单向摘要（`MD5` assisted 算法）；
- 等值查询改路由到辅助列匹配，命中后再解密主列返回；
- 代价是额外一列存储与一次摘要计算——空间换可查性。

范围查询、模糊查询在加密列上不可用，这是加密方案的硬边界，不是配置问题。

## Masking Algorithms

`!MASK` 规则的内置算法：

| type | 语义 | 关键属性 |
| :--- | :--- | :--- |
| `MD5` | 哈希脱敏 | `salt`（可选） |
| `KEEP_FIRST_N_LAST_M` | 保留前 n 后 m | `first-n`、`last-m`、`replace-char` |
| `KEEP_FROM_X_TO_Y` | 保留 [x, y) 段 | `from-x`、`to-y`、`replace-char` |
| `MASK_FIRST_N_LAST_M` | 掩掉前 n 后 m | `first-n`、`last-m`、`replace-char` |
| `MASK_FROM_X_TO_Y` | 掩掉 [x, y) 段 | `from-x`、`to-y`、`replace-char` |
| `MASK_BEFORE_SPECIAL_CHARS` | 掩掉首个特殊字符前的部分 | `special-chars`、`replace-char` |
| `MASK_AFTER_SPECIAL_CHARS` | 掩掉首个特殊字符后的部分 | `special-chars`、`replace-char` |
| `GENERIC_TABLE_RANDOM_REPLACE` | 通用随机字符替换 | 大写/小写/数字/特殊字符码表 |

配置挂在列上，一张表不同列可用不同算法（`password` 用 MD5、`email` 用 `MASK_BEFORE_SPECIAL_CHARS` 掩掉 `@` 前、`telephone` 用 `KEEP_FIRST_N_LAST_M` 留前 3 后 4）。

## Application Scenarios

- **新业务合规加密**：安全部门要求敏感信息加密入库、用时解密——直接配 `!ENCRYPT`，业务零改造。
- **展示层脱敏**：管理后台、导出、日志里的手机号/邮箱掩码——`!MASK` 配列即生效。
- **在线系统加密改造**：官方直言这是最复杂的场景——不停机、不改业务 SQL、平滑切换需要前置加密数据、双写与回填的完整方案，不是改个规则就能上线。

## Facts Worth Pinning Down

1. **内置加密算法只有 AES 与 MD5 两条**；辅助查询列用 MD5 摘要，范围/模糊查询在加密列上不可用。
2. **脱敏不可逆**：`!MASK` 是展示保护，不是加密；要还原能力的场景必须 `!ENCRYPT`。
3. **加密改造最贵的不是规则**：是在线平滑切换的数据回填与双写，官方把它单列为挑战。
4. **加密/脱敏规则引用到的单表会被自动加载**——这是 ShardingSphere 自动加载单表的少数触发条件之一（见 [Sharding](/docs/CS/DB/ShardingSphere/Sharding.md)）。

## Links

- [SQL Pipeline](/docs/CS/DB/ShardingSphere/SQL_Pipeline.md)
- [Shadow](/docs/CS/DB/ShardingSphere/Shadow.md)
- [Architecture](/docs/CS/DB/ShardingSphere/Architecture.md)

## References

1. [Data Encryption :: ShardingSphere](https://shardingsphere.apache.org/document/current/en/features/encrypt/)
2. [Developer Guide: EncryptAlgorithm implementations](https://shardingsphere.apache.org/document/current/en/dev-manual/encrypt/)
3. [Data Masking Algorithm (built-in list)](https://shardingsphere.apache.org/document/current/en/user-manual/common-config/builtin-algorithm/mask)
4. [Encrypt YAML Configuration](https://shardingsphere.apache.org/document/current/en/user-manual/shardingsphere-jdbc/yaml-config/rules/encrypt/)
