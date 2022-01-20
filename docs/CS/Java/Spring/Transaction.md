## Introduction




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


- **only support public method**

```java
//class TransactionalRepositoryProxyPostProcessor
private TransactionAttribute computeTransactionAttribute(Method method, Class<?> targetClass) {
   // Don't allow no-public methods as required.
   if (allowPublicMethodsOnly() && !Modifier.isPublic(method.getModifiers())) {
      return null;
   }
  //
}
```







### Propagation
Enumeration that represents transaction propagation behaviors for use TransactionDefinition interface.

```java
public enum Propagation {

	REQUIRED(TransactionDefinition.PROPAGATION_REQUIRED),

	SUPPORTS(TransactionDefinition.PROPAGATION_SUPPORTS),

	MANDATORY(TransactionDefinition.PROPAGATION_MANDATORY),

	REQUIRES_NEW(TransactionDefinition.PROPAGATION_REQUIRES_NEW),

	NOT_SUPPORTED(TransactionDefinition.PROPAGATION_NOT_SUPPORTED),

	NEVER(TransactionDefinition.PROPAGATION_NEVER),

	NESTED(TransactionDefinition.PROPAGATION_NESTED);
}
```


### TransactionDefinition
```java

package org.springframework.transaction;

import org.springframework.lang.Nullable;

/**
 * Interface that defines Spring-compliant transaction properties.
 * Based on the propagation behavior definitions analogous to EJB CMT attributes.
 *
 * <p>Note that isolation level and timeout settings will not get applied unless
 * an actual new transaction gets started. As only {@link #PROPAGATION_REQUIRED},
 * {@link #PROPAGATION_REQUIRES_NEW} and {@link #PROPAGATION_NESTED} can cause
 * that, it usually doesn't make sense to specify those settings in other cases.
 * Furthermore, be aware that not all transaction managers will support those
 * advanced features and thus might throw corresponding exceptions when given
 * non-default values.
 *
 * <p>The {@link #isReadOnly() read-only flag} applies to any transaction context,
 * whether backed by an actual resource transaction or operating non-transactionally
 * at the resource level. In the latter case, the flag will only apply to managed
 * resources within the application, such as a Hibernate {@code Session}.
 *
 */
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


	/**
	 * Use the default timeout of the underlying transaction system,
	 * or none if timeouts are not supported.
	 */
	int TIMEOUT_DEFAULT = -1;

	default int getPropagationBehavior() {
		return PROPAGATION_REQUIRED;
	}

	default int getIsolationLevel() {
		return ISOLATION_DEFAULT;
	}

	default int getTimeout() {
		return TIMEOUT_DEFAULT;
	}

	default boolean isReadOnly() {
		return false;
	}

	@Nullable
	default String getName() {
		return null;
	}


	// Static builder methods
	static TransactionDefinition withDefaults() {
		return StaticTransactionDefinition.INSTANCE;
	}

}
```

### TransactionManager

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


TransactionSynchronizationManager


## Multi-DataSource

AbstractRoutingDataSource


## Links
- [Transaction](/docs/CS/Transaction.md)
- [Transaction - MySQL](/docs/CS/DB/MySQL/Transaction.md)


## References
1. [Transaction Management - Spring](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#transaction)