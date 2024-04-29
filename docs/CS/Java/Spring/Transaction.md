## Introduction

The Spring Framework provides a consistent abstraction for transaction management that delivers the following benefits:

- Consistent programming model across different transaction APIs such as Java Transaction API (JTA), JDBC, Hibernate, Java Persistence API (JPA), and Java Data Objects (JDO).
Support for declarative transaction management.
- - Simpler API for programmatic transaction management than complex transaction APIs such as JTA.
- Excellent integration with Spring’s data access abstractions.

Let’s remember what declaring a data source in Spring Boot looks like in application.yml:


```yaml
spring:
  datasource:
    url: ...
    username: ...
    password: ...
    driverClassname: ...
```	

Spring maps these settings to an instance of org.springframework.boot.autoconfigure.jdbc.DataSourceProperties.
So, to use multiple data sources, we need to declare multiple beans with different mappings within Spring’s application context.


DataSourceAutoConfiguration

DataSourceTransactionManagerAutoConfiguration

JdbcTemplateAutoConfiguration



Translate the given SQLException into a generic DataAccessException.

```java
public interface SQLExceptionTranslator {
	@Nullable
	DataAccessException translate(String task, @Nullable String sql, SQLException ex);
}
```
> JavaBean `SQLErrorCodes` define in `spring-jdbc/src/main/resources/org/springframework/jdbc/support/sql-error-codes.xml`.
> Can be overridden by definitions in a "`sql-error-codes.xml`" file in the root of the class path.


With Spring Boot 2 and Spring Boot 3, HikariCP is the default connection pool and it is transitively imported with either `spring-boot-starter-jdbc` or `spring-boot-starter-data-jpa` starter dependency, so you don’t need to add any extra dependency to your project.
Spring Boot will expose Hikari-specific settings to `spring.datasource.hikari`. 



A transaction strategy is defined by the org.springframework.transaction.PlatformTransactionManager interface:
```java
public interface PlatformTransactionManager {

    TransactionStatus getTransaction(
            TransactionDefinition definition) throws TransactionException;

    void commit(TransactionStatus status) throws TransactionException;

    void rollback(TransactionStatus status) throws TransactionException;
}
```

The TransactionDefinition interface specifies:

- Isolation: The degree to which this transaction is isolated from the work of other transactions. For example, can this transaction see uncommitted writes from other transactions?
- Propagation: Typically, all code executed within a transaction scope will run in that transaction. However, you have the option of specifying the behavior in the event that a transactional method is executed when a transaction context already exists. For example, code can continue running in the existing transaction (the common case); or the existing transaction can be suspended and a new transaction created. Spring offers all of the transaction propagation options familiar from EJB CMT. To read about the semantics of transaction propagation in Spring, see Section 16.5.7, “Transaction propagation”.
- Timeout: How long this transaction runs before timing out and being rolled back automatically by the underlying transaction infrastructure.
- Read-only status: A read-only transaction can be used when your code reads but does not modify data. Read-only transactions can be a useful optimization in some cases, such as when you are using Hibernate.




## Programmatic transaction

The central method is execute, supporting transactional code that implements the TransactionCallback interface. 
This template handles the transaction lifecycle and possible exceptions such that neither the TransactionCallback implementation nor the calling code needs to explicitly handle transactions.


```java
public class TransactionTemplate extends DefaultTransactionDefinition
		implements TransactionOperations, InitializingBean {
		}
```

Gets called by `TransactionTemplate.execute` within a transactional context. Does not need to care about transactions itself, although it can retrieve and influence the status of the current transaction via the given status object, e.g. setting rollback-only.
A RuntimeException thrown by the callback is treated as application exception that enforces a rollback. An exception gets propagated to the caller of the template.


```java
@FunctionalInterface
public interface TransactionCallback<T> {

	@Nullable
	T doInTransaction(TransactionStatus status);

}

public abstract class TransactionCallbackWithoutResult implements TransactionCallback<Object> {

	@Override
	@Nullable
	public final Object doInTransaction(TransactionStatus status) {
		doInTransactionWithoutResult(status);
		return null;
	}

	protected abstract void doInTransactionWithoutResult(TransactionStatus status);

}
```


## Declarative transaction

The Spring Framework’s declarative transaction management is made possible with Spring aspect-oriented programming (AOP).
The combination of AOP with transactional metadata yields an AOP proxy that uses a TransactionInterceptor in conjunction with an appropriate PlatformTransactionManager implementation to drive transactions around method invocations.

Conceptually, calling a method on a transactional proxy looks like this:

![](https://docs.spring.io/spring-framework/docs/4.2.x/spring-framework-reference/html/images/tx.png)

 Declaring transaction semantics directly in the Java source code puts the declarations much closer to the affected code.



### Transactional

Describes a transaction attribute on an individual method or on a class.

When this annotation is declared at the class level, it applies as a default to all methods of the declaring class and its subclasses. 
Note that it does not apply to ancestor classes up the class hierarchy; inherited methods need to be locally redeclared in order to participate in a subclass-level annotation. 
For details on method visibility constraints, consult the Transaction Management  section of the reference manual.

This annotation type is generally directly comparable to Spring's org.springframework.transaction.interceptor.RuleBasedTransactionAttribute class, 
and in fact AnnotationTransactionAttributeSource will directly convert the data to the latter class, so that Spring's transaction support code does not have to know about annotations. 

**If no custom rollback rules apply, the transaction will roll back on RuntimeException and Error but not on checked exceptions.**

For specific information about the semantics of this annotation's attributes, consult the TransactionDefinition and `org.springframework.transaction.interceptor.TransactionAttribute` javadocs.

This annotation commonly works with thread-bound transactions managed by a `org.springframework.transaction.PlatformTransactionManager`, exposing a transaction to all data access operations within the current execution thread. 

**Note: This does NOT propagate to newly started threads within the method.**

Alternatively, this annotation may demarcate a reactive transaction managed by a org.springframework.transaction.ReactiveTransactionManager which uses the Reactor context instead of thread-local variables. 
As a consequence, all participating data access operations need to execute within the same Reactor context in the same reactive pipeline.


> [!NOTE]
> 
> When using proxies, you should apply the @Transactional annotation only to methods with public visibility. If you do annotate protected, private or package-visible methods with the @Transactional annotation, no error is raised, but the annotated method does not exhibit the configured transactional settings. Consider the use of AspectJ (see below) if you need to annotate non-public methods.


The @Transactional annotation is metadata that specifies that an interface, class, or method must have transactional semantics; for example, "start a brand new read-only transaction when this method is invoked, suspending any existing transaction". The default @Transactional settings are as follows:

- Propagation setting is PROPAGATION_REQUIRED.
- Isolation level is ISOLATION_DEFAULT.
- Transaction is read/write.
- Transaction timeout defaults to the default timeout of the underlying transaction system, or to none if timeouts are not supported.
- Any RuntimeException triggers rollback, and any checked Exception does not.

```java
//class TransactionalRepositoryProxyPostProcessor
private TransactionAttribute computeTransactionAttribute(Method method, Class<?> targetClass) {
   // Don't allow no-public methods as required.
   if (allowPublicMethodsOnly() && !Modifier.isPublic(method.getModifiers())) {
      return null;
   } 
}
```







### Propagation

Enumeration that represents transaction propagation behaviors for use TransactionDefinition interface.
 


> [!NOTE]
> 
> Note that isolation level and timeout settings will not get applied unless an actual new transaction gets started. 
As only `PROPAGATION_REQUIRED`, `PROPAGATION_REQUIRES_NEW` and `PROPAGATION_NESTED` can cause that, it usually doesn't make sense to specify those settings in other cases.

<!-- tabs:start -->
##### **PROPAGATION_REQUIRED**
`PROPAGATION_REQUIRED` enforces a physical transaction, either locally for the current scope if no transaction exists yet or participating in an existing 'outer' transaction defined for a larger scope. This is a fine default in common call stack arrangements within the same thread (for example, a service facade that delegates to several repository methods where all the underlying resources have to participate in the service-level transaction).

When the propagation setting is `PROPAGATION_REQUIRED`, a logical transaction scope is created for each method upon which the setting is applied. 
Each such logical transaction scope can determine rollback-only status individually, with an outer transaction scope being logically independent from the inner transaction scope. 
In the case of standard `PROPAGATION_REQUIRED` behavior, all these scopes are mapped to the same physical transaction. 
So a rollback-only marker set in the inner transaction scope does affect the outer transaction’s chance to actually commit.

However, in the case where an inner transaction scope sets the rollback-only marker, the outer transaction has not decided on the rollback itself, so the rollback (silently triggered by the inner transaction scope) is unexpected. 
**A corresponding `UnexpectedRollbackException` is thrown at that point.**
This is expected behavior so that the caller of a transaction can never be misled to assume that a commit was performed when it really was not. 
So, if an inner transaction (of which the outer caller is not aware) silently marks a transaction as rollback-only, the outer caller still calls commit. 
The outer caller needs to receive an `UnexpectedRollbackException` to indicate clearly that a rollback was performed instead.


##### **PROPAGATION_REQUIRES_NEW**

`PROPAGATION_REQUIRES_NEW`, in contrast to PROPAGATION_REQUIRED, always uses an independent physical transaction for each affected transaction scope, never participating in an existing transaction for an outer scope. In such an arrangement, the underlying resource transactions are different and, hence, can commit or roll back independently, with an outer transaction not affected by an inner transaction’s rollback status and with an inner transaction’s locks released immediately after its completion. Such an independent inner transaction can also declare its own isolation level, timeout, and read-only settings and not inherit an outer transaction’s characteristics.


##### **PROPAGATION_NESTED**

`PROPAGATION_NESTED` uses a single physical transaction with multiple savepoints that it can roll back to. 
**Such partial rollbacks let an inner transaction scope trigger a rollback for its scope, with the outer transaction being able to continue the physical transaction despite some operations having been rolled back.** 
This setting is typically mapped onto JDBC savepoints, so it works only with JDBC resource transactions.

<!-- tabs:end -->

```java
public interface TransactionDefinition {

	int PROPAGATION_REQUIRED = 0;

	int PROPAGATION_SUPPORTS = 1;

	int PROPAGATION_MANDATORY = 2;

	int PROPAGATION_REQUIRES_NEW = 3;

	int PROPAGATION_NOT_SUPPORTED = 4;

	int PROPAGATION_NEVER = 5;

	int PROPAGATION_NESTED = 6;

	int ISOLATION_DEFAULT = -1;

	int ISOLATION_READ_UNCOMMITTED = 1;  // same as java.sql.Connection.TRANSACTION_READ_UNCOMMITTED;

	int ISOLATION_READ_COMMITTED = 2;  // same as java.sql.Connection.TRANSACTION_READ_COMMITTED;

	int ISOLATION_REPEATABLE_READ = 4;  // same as java.sql.Connection.TRANSACTION_REPEATABLE_READ;

	int ISOLATION_SERIALIZABLE = 8;  // same as java.sql.Connection.TRANSACTION_SERIALIZABLE;

	int TIMEOUT_DEFAULT = -1;
 
}
```

## TransactionProxyFactoryBean

## TransactionManager

Implementation by MyBatis, Hibernate, JTA.

```java
public interface PlatformTransactionManager extends TransactionManager {

    TransactionStatus getTransaction(TransactionDefinition definition) throws TransactionException;

    void commit(TransactionStatus status) throws TransactionException;

    void rollback(TransactionStatus status) throws TransactionException;
}
```

AOP Alliance MethodInterceptor for declarative transaction management using the common Spring transaction infrastructure (PlatformTransactionManager/ org.springframework.transaction.ReactiveTransactionManager).
Derives from the TransactionAspectSupport class which contains the integration with Spring's underlying transaction API. 
TransactionInterceptor simply calls the relevant superclass methods such as invokeWithinTransaction in the correct order.
TransactionInterceptors are thread-safe.
```java
public class TransactionInterceptor extends TransactionAspectSupport implements MethodInterceptor, Serializable {
}
```

```java
// TransactionAspectSupport
	/** Prepare a TransactionInfo for the given attribute and status object. */
	protected TransactionInfo prepareTransactionInfo(@Nullable PlatformTransactionManager tm,
			@Nullable TransactionAttribute txAttr, String joinpointIdentification,
			@Nullable TransactionStatus status) {

		TransactionInfo txInfo = new TransactionInfo(tm, txAttr, joinpointIdentification);
		if (txAttr != null) {
			// We need a transaction for this method...
			if (logger.isTraceEnabled()) {
				logger.trace("Getting transaction for [" + txInfo.getJoinpointIdentification() + "]");
			}
			// The transaction manager will flag an error if an incompatible tx already exists.
			txInfo.newTransactionStatus(status);
		}
		else {
			// The TransactionInfo.hasTransaction() method will return false. We created it only
			// to preserve the integrity of the ThreadLocal stack maintained in this class.
			if (logger.isTraceEnabled()) {
				logger.trace("No need to create transaction for [" + joinpointIdentification +
						"]: This method is not transactional.");
			}
		}

		// We always bind the TransactionInfo to the thread, even if we didn't create
		// a new transaction here. This guarantees that the TransactionInfo stack
		// will be managed correctly even if no transaction was created by this aspect.
		txInfo.bindToThread();
		return txInfo;
	}
```


### TransactionSynchronizationManager

Register a new transaction synchronization for the current thread. Typically called by resource management code.
Note that synchronizations can implement the `org.springframework.core.Ordered` interface. They will be executed in an order according to their order value (if any).

```java
public abstract class TransactionSynchronizationManager {
    public static void registerSynchronization(TransactionSynchronization synchronization)
            throws IllegalStateException {

        Assert.notNull(synchronization, "TransactionSynchronization must not be null");
        Set<TransactionSynchronization> synchs = synchronizations.get();
        if (synchs == null) {
            throw new IllegalStateException("Transaction synchronization is not active");
        }
        synchs.add(synchronization);
    }
}
```

#### TransactionSynchronization

```java

public interface TransactionSynchronization extends Flushable {
    int STATUS_COMMITTED = 0;
    int STATUS_ROLLED_BACK = 1;
    int STATUS_UNKNOWN = 2;

    default void suspend() {
    }

    default void resume() {
    }

    default void flush() {
    }

    default void beforeCommit(boolean readOnly) {
    }

    default void beforeCompletion() {
    }

    default void afterCommit() {
    }

    default void afterCompletion(int status) {
    }
}
```

## Multi-DataSource

AbstractRoutingDataSource


### Rollback Rules

Pattern-based use `contains()`



## Links

- [Spring](/docs/CS/Java/Spring/Spring.md)
- [Transaction](/docs/CS/Transaction.md)
- [Transaction - MySQL](/docs/CS/DB/MySQL/Transaction.md)


## References
1. [Transaction Management - Spring](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#transaction)