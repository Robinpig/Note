# Index

有序的数据结构

主键索引

普通索引

唯一索引

full text

组合索引



Hash Index精确单个查询 Innodb



覆盖索引

select的列都是索引项

索引失效

不满足最左前缀匹配

范围索引未放到最后:联合索引里的范围列

使用select *

索引列上有计算

索引列上有函数

字符类型没加引号

字段允许为空情况下 使用对 null判断不走索引

like查询左边%

or对不同索引字段使用比单独select后union差

