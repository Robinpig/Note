## Introduction


### Transactional Properties
- The relational world
- Multi-user
- Distributed systems


## ACID
A transaction is a unit of work enjoying the following properties:
- Atomicity
- Consistency
- Isolation
- Durability


### Atomicity
A transaction is an atomic transformation from the initial state to the final state
Possible behaviors:
1. Commit work: SUCCESS
2. Rollback work or error prior to commit: UNDO
3. Fault after commit: REDO


### Consistency
The transaction satisfies the integrity constraints Consequence:
- If the initial state is consistent
- Then the final state is also consistent

### Isolation
A transaction is not affected by the behavior of other, concurrent transactions Consequence:
- Its intermediate states are not exposed
- The “domino effect” is avoided


### Durability
The effect of a transaction that has successfully committed will
last “forever”
- Independently of any system fault

### Transaction Properties and Mechanisms
- Atomicity
  - Abort-rollback-restart
  - Commit protocols
- Consistency
  - Integrity checking of the DBMS
- Isolation
  - Concurrency control
- Durability
  - Recovery management




| Isolation level  | Dirty Read               | Non-Repeatable Read | Phantom Read |
| ---------------- | ------------------------ | ------------------- | ------------ |
| READ-UNCOMMITTED | :white_check_mark:  | :white_check_mark: | :white_check_mark: |
| READ-COMMITTED   | :x:    | :white_check_mark: | :white_check_mark: |
| REPEATABLE-READ  | :x: | :x: | :white_check_mark: |
| SERIALIZABLE     | :x: | :x: | :x: |



mysql use Next-Key Lock algorithm avoid Phantom Read like SERIALIZABLE.


```mysql
mysql>SELECT @@tx_isolation;
REPEATABLE-READ
```



other dbs(Oracle,SQL Server) are `READ-COMMITTED `



Innodb in distribution-transaction is SERIALIZABLE.



## CAP Theorem (Brewer’s Theorem)
It is impossible for a distributed computer system to simultaneously provide all three of the following guarantees:
- **Consistency**: all nodes see the same data at the same time
- **Availability**: Node failures do not prevent other survivors from continuing to operate (a guarantee that every request receives a response about whether it succeeded or failed)
- **Partition tolerance**: the system continues to operate despite arbitrary partitioning due to network failures (e.g., message loss)
A distributed system can satisfy any two of these guarantees at the same time but not all three.

## BASE
(Basically Available, Soft-State, Eventually Consistent)
• Basic Availability: fulfill request, even in partial consistency.
• Soft State: abandon the consistency requirements of the ACID model pretty much completely
• Eventual Consistency: at some point in the future, data will converge to a consistent state; delayed consistency, as opposed to immediate consistency of the ACID properties.
• purely a liveness guarantee (reads eventually return the requested value); but
• does not make safety guarantees, i.e.,
• an eventually consistent system can return any value before it converges


### ACID vs. BASE trade-off
• No general answer to whether your application needs an ACID versus BASE
consistency model.
• Given BASE’s loose consistency, developers need to be more
knowledgeable and rigorous about consistent data if they choose a BASE
store for their application.
• Planning around BASE limitations can sometimes be a major disadvantage
when compared to the simplicity of ACID transactions.
• A fully ACID database is the perfect fit for use cases where data reliability
and consistency are essential.




## References
1. [ACID vs. BASE and SQL vs. NoSQL](https://marcobrambillapolimi.files.wordpress.com/2019/01/01-nosql-overview.pdf)