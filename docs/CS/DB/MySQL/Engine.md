## Introduction



### MyISAM vs InnoDB

| Feature                      | MyISAM Support |   InnoDB Support            |
| :--------------------------- | :------------- |:------------- |
| **B-tree indexes**           | Yes            |      Yes         |
| **Cluster database support** | No             |         Yes      |
| **Clustered indexes**        | No             |      Yes         |
| **Data caches**              | No             |       Yes        |
| **Foreign key support**      | No             |       Yes        |
| **Full-text search indexes** | Yes            |       Yes        |
| **Hash indexes**             | No             |       No (InnoDB utilizes hash indexes internally for its Adaptive Hash Index feature.)        |
| **Index caches**             | Yes            |        Yes       |
| **Locking granularity**      | Table          |          Row     |
| **MVCC**                     | No             |        Yes       |
| **Storage limits**           | 256TB          |        64TB       |
| **Transactions**             | No             |      Yes         |


## References
