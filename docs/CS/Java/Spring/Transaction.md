

## @Transactional

Describes a transaction attribute on an individual method or on a class.

When this annotation is declared at the class level, it applies as a default to all methods of the declaring class and its subclasses. Note that it does not apply to ancestor classes up the class hierarchy; inherited methods need to be locally redeclared in order to participate in a subclass-level annotation. For details on method visibility constraints, consult the Transaction Management  section of the reference manual.

This annotation type is generally directly comparable to Spring's org.springframework.transaction.interceptor.RuleBasedTransactionAttribute class, and in fact AnnotationTransactionAttributeSource will directly convert the data to the latter class, so that Spring's transaction support code does not have to know about annotations. If no custom rollback rules apply, the transaction will roll back on RuntimeException and Error but not on checked exceptions.

For specific information about the semantics of this annotation's attributes, consult the TransactionDefinition and org.springframework.transaction.interceptor.TransactionAttribute javadocs.

This annotation commonly works with thread-bound transactions managed by a org.springframework.transaction.PlatformTransactionManager, exposing a transaction to all data access operations within the current execution thread. 

**Note: This does NOT propagate to newly started threads within the method.**

Alternatively, this annotation may demarcate a reactive transaction managed by a org.springframework.transaction.ReactiveTransactionManager which uses the Reactor context instead of thread-local variables. As a consequence, all participating data access operations need to execute within the same Reactor context in the same reactive pipeline.


- only support public method

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

- 方法是final 代理类无法重写
- 调用了未被重写的方法
- 实体未被Spring管理 无法生成代理类
- Spring事务传播性质未设置好
- 数据库不支持事务 例如MySQL的myslam引擎
- 内部捕获异常未处理
- 抛出异常不为RuntimeException及其子类
- 多线程调用 数据库连接不相同
- 嵌套事务多回滚了





处理大事务的6种办法：

- 少用@Transactional注解
- 将查询(select)方法放到事务外
- 事务中避免远程调用
- 事务中避免一次性处理太多数据
- 非事务执行
- 异步处理



### Propagation

```java

package org.springframework.transaction.annotation;

import org.springframework.transaction.TransactionDefinition;

/**
 * Enumeration that represents transaction propagation behaviors for use
 * with the {@link Transactional} annotation, corresponding to the
 * {@link TransactionDefinition} interface.
 */
public enum Propagation {

	/**
	 * Support a current transaction, create a new one if none exists.
	 * Analogous to EJB transaction attribute of the same name.
	 * <p>This is the default setting of a transaction annotation.
	 */
	REQUIRED(TransactionDefinition.PROPAGATION_REQUIRED),

	/**
	 * Support a current transaction, execute non-transactionally if none exists.
	 * Analogous to EJB transaction attribute of the same name.
	 * <p>Note: For transaction managers with transaction synchronization,
	 * {@code SUPPORTS} is slightly different from no transaction at all,
	 * as it defines a transaction scope that synchronization will apply for.
	 * As a consequence, the same resources (JDBC Connection, Hibernate Session, etc)
	 * will be shared for the entire specified scope. Note that this depends on
	 * the actual synchronization configuration of the transaction manager.
	 * @see org.springframework.transaction.support.AbstractPlatformTransactionManager#setTransactionSynchronization
	 */
	SUPPORTS(TransactionDefinition.PROPAGATION_SUPPORTS),

	/**
	 * Support a current transaction, throw an exception if none exists.
	 * Analogous to EJB transaction attribute of the same name.
	 */
	MANDATORY(TransactionDefinition.PROPAGATION_MANDATORY),

	/**
	 * Create a new transaction, and suspend the current transaction if one exists.
	 * Analogous to the EJB transaction attribute of the same name.
	 * <p><b>NOTE:</b> Actual transaction suspension will not work out-of-the-box
	 * on all transaction managers. This in particular applies to
	 * {@link org.springframework.transaction.jta.JtaTransactionManager},
	 * which requires the {@code javax.transaction.TransactionManager} to be
	 * made available to it (which is server-specific in standard Java EE).
	 * @see org.springframework.transaction.jta.JtaTransactionManager#setTransactionManager
	 */
	REQUIRES_NEW(TransactionDefinition.PROPAGATION_REQUIRES_NEW),

	/**
	 * Execute non-transactionally, suspend the current transaction if one exists.
	 * Analogous to EJB transaction attribute of the same name.
	 * <p><b>NOTE:</b> Actual transaction suspension will not work out-of-the-box
	 * on all transaction managers. This in particular applies to
	 * {@link org.springframework.transaction.jta.JtaTransactionManager},
	 * which requires the {@code javax.transaction.TransactionManager} to be
	 * made available to it (which is server-specific in standard Java EE).
	 * @see org.springframework.transaction.jta.JtaTransactionManager#setTransactionManager
	 */
	NOT_SUPPORTED(TransactionDefinition.PROPAGATION_NOT_SUPPORTED),

	/**
	 * Execute non-transactionally, throw an exception if a transaction exists.
	 * Analogous to EJB transaction attribute of the same name.
	 */
	NEVER(TransactionDefinition.PROPAGATION_NEVER),

	/**
	 * Execute within a nested transaction if a current transaction exists,
	 * behave like {@code REQUIRED} otherwise. There is no analogous feature in EJB.
	 * <p>Note: Actual creation of a nested transaction will only work on specific
	 * transaction managers. Out of the box, this only applies to the JDBC
	 * DataSourceTransactionManager. Some JTA providers might support nested
	 * transactions as well.
	 * @see org.springframework.jdbc.datasource.DataSourceTransactionManager
	 */
	NESTED(TransactionDefinition.PROPAGATION_NESTED);


	private final int value;


	Propagation(int value) {
		this.value = value;
	}

	public int value() {
		return this.value;
	}

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
 * @author Juergen Hoeller
 * @since 08.05.2003
 * @see PlatformTransactionManager#getTransaction(TransactionDefinition)
 * @see org.springframework.transaction.support.DefaultTransactionDefinition
 * @see org.springframework.transaction.interceptor.TransactionAttribute
 */
public interface TransactionDefinition {

	/**
	 * Support a current transaction; create a new one if none exists.
	 * Analogous to the EJB transaction attribute of the same name.
	 * <p>This is typically the default setting of a transaction definition,
	 * and typically defines a transaction synchronization scope.
	 */
	int PROPAGATION_REQUIRED = 0;

	/**
	 * Support a current transaction; execute non-transactionally if none exists.
	 * Analogous to the EJB transaction attribute of the same name.
	 * <p><b>NOTE:</b> For transaction managers with transaction synchronization,
	 * {@code PROPAGATION_SUPPORTS} is slightly different from no transaction
	 * at all, as it defines a transaction scope that synchronization might apply to.
	 * As a consequence, the same resources (a JDBC {@code Connection}, a
	 * Hibernate {@code Session}, etc) will be shared for the entire specified
	 * scope. Note that the exact behavior depends on the actual synchronization
	 * configuration of the transaction manager!
	 * <p>In general, use {@code PROPAGATION_SUPPORTS} with care! In particular, do
	 * not rely on {@code PROPAGATION_REQUIRED} or {@code PROPAGATION_REQUIRES_NEW}
	 * <i>within</i> a {@code PROPAGATION_SUPPORTS} scope (which may lead to
	 * synchronization conflicts at runtime). If such nesting is unavoidable, make sure
	 * to configure your transaction manager appropriately (typically switching to
	 * "synchronization on actual transaction").
	 * @see org.springframework.transaction.support.AbstractPlatformTransactionManager#setTransactionSynchronization
	 * @see org.springframework.transaction.support.AbstractPlatformTransactionManager#SYNCHRONIZATION_ON_ACTUAL_TRANSACTION
	 */
	int PROPAGATION_SUPPORTS = 1;

	/**
	 * Support a current transaction; throw an exception if no current transaction
	 * exists. Analogous to the EJB transaction attribute of the same name.
	 * <p>Note that transaction synchronization within a {@code PROPAGATION_MANDATORY}
	 * scope will always be driven by the surrounding transaction.
	 */
	int PROPAGATION_MANDATORY = 2;

	/**
	 * Create a new transaction, suspending the current transaction if one exists.
	 * Analogous to the EJB transaction attribute of the same name.
	 * <p><b>NOTE:</b> Actual transaction suspension will not work out-of-the-box
	 * on all transaction managers. This in particular applies to
	 * {@link org.springframework.transaction.jta.JtaTransactionManager},
	 * which requires the {@code javax.transaction.TransactionManager} to be
	 * made available it to it (which is server-specific in standard Java EE).
	 * <p>A {@code PROPAGATION_REQUIRES_NEW} scope always defines its own
	 * transaction synchronizations. Existing synchronizations will be suspended
	 * and resumed appropriately.
	 * @see org.springframework.transaction.jta.JtaTransactionManager#setTransactionManager
	 */
	int PROPAGATION_REQUIRES_NEW = 3;

	/**
	 * Do not support a current transaction; rather always execute non-transactionally.
	 * Analogous to the EJB transaction attribute of the same name.
	 * <p><b>NOTE:</b> Actual transaction suspension will not work out-of-the-box
	 * on all transaction managers. This in particular applies to
	 * {@link org.springframework.transaction.jta.JtaTransactionManager},
	 * which requires the {@code javax.transaction.TransactionManager} to be
	 * made available it to it (which is server-specific in standard Java EE).
	 * <p>Note that transaction synchronization is <i>not</i> available within a
	 * {@code PROPAGATION_NOT_SUPPORTED} scope. Existing synchronizations
	 * will be suspended and resumed appropriately.
	 * @see org.springframework.transaction.jta.JtaTransactionManager#setTransactionManager
	 */
	int PROPAGATION_NOT_SUPPORTED = 4;

	/**
	 * Do not support a current transaction; throw an exception if a current transaction
	 * exists. Analogous to the EJB transaction attribute of the same name.
	 * <p>Note that transaction synchronization is <i>not</i> available within a
	 * {@code PROPAGATION_NEVER} scope.
	 */
	int PROPAGATION_NEVER = 5;

	/**
	 * Execute within a nested transaction if a current transaction exists,
	 * behave like {@link #PROPAGATION_REQUIRED} otherwise. There is no
	 * analogous feature in EJB.
	 * <p><b>NOTE:</b> Actual creation of a nested transaction will only work on
	 * specific transaction managers. Out of the box, this only applies to the JDBC
	 * {@link org.springframework.jdbc.datasource.DataSourceTransactionManager}
	 * when working on a JDBC 3.0 driver. Some JTA providers might support
	 * nested transactions as well.
	 * @see org.springframework.jdbc.datasource.DataSourceTransactionManager
	 */
	int PROPAGATION_NESTED = 6;


	/**
	 * Use the default isolation level of the underlying datastore.
	 * All other levels correspond to the JDBC isolation levels.
	 * @see java.sql.Connection
	 */
	int ISOLATION_DEFAULT = -1;

	/**
	 * Indicates that dirty reads, non-repeatable reads and phantom reads
	 * can occur.
	 * <p>This level allows a row changed by one transaction to be read by another
	 * transaction before any changes in that row have been committed (a "dirty read").
	 * If any of the changes are rolled back, the second transaction will have
	 * retrieved an invalid row.
	 * @see java.sql.Connection#TRANSACTION_READ_UNCOMMITTED
	 */
	int ISOLATION_READ_UNCOMMITTED = 1;  // same as java.sql.Connection.TRANSACTION_READ_UNCOMMITTED;

	/**
	 * Indicates that dirty reads are prevented; non-repeatable reads and
	 * phantom reads can occur.
	 * <p>This level only prohibits a transaction from reading a row
	 * with uncommitted changes in it.
	 * @see java.sql.Connection#TRANSACTION_READ_COMMITTED
	 */
	int ISOLATION_READ_COMMITTED = 2;  // same as java.sql.Connection.TRANSACTION_READ_COMMITTED;

	/**
	 * Indicates that dirty reads and non-repeatable reads are prevented;
	 * phantom reads can occur.
	 * <p>This level prohibits a transaction from reading a row with uncommitted changes
	 * in it, and it also prohibits the situation where one transaction reads a row,
	 * a second transaction alters the row, and the first transaction re-reads the row,
	 * getting different values the second time (a "non-repeatable read").
	 * @see java.sql.Connection#TRANSACTION_REPEATABLE_READ
	 */
	int ISOLATION_REPEATABLE_READ = 4;  // same as java.sql.Connection.TRANSACTION_REPEATABLE_READ;

	/**
	 * Indicates that dirty reads, non-repeatable reads and phantom reads
	 * are prevented.
	 * <p>This level includes the prohibitions in {@link #ISOLATION_REPEATABLE_READ}
	 * and further prohibits the situation where one transaction reads all rows that
	 * satisfy a {@code WHERE} condition, a second transaction inserts a row
	 * that satisfies that {@code WHERE} condition, and the first transaction
	 * re-reads for the same condition, retrieving the additional "phantom" row
	 * in the second read.
	 * @see java.sql.Connection#TRANSACTION_SERIALIZABLE
	 */
	int ISOLATION_SERIALIZABLE = 8;  // same as java.sql.Connection.TRANSACTION_SERIALIZABLE;


	/**
	 * Use the default timeout of the underlying transaction system,
	 * or none if timeouts are not supported.
	 */
	int TIMEOUT_DEFAULT = -1;


	/**
	 * Return the propagation behavior.
	 * <p>Must return one of the {@code PROPAGATION_XXX} constants
	 * defined on {@link TransactionDefinition this interface}.
	 * <p>The default is {@link #PROPAGATION_REQUIRED}.
	 * @return the propagation behavior
	 * @see #PROPAGATION_REQUIRED
	 * @see org.springframework.transaction.support.TransactionSynchronizationManager#isActualTransactionActive()
	 */
	default int getPropagationBehavior() {
		return PROPAGATION_REQUIRED;
	}

	/**
	 * Return the isolation level.
	 * <p>Must return one of the {@code ISOLATION_XXX} constants defined on
	 * {@link TransactionDefinition this interface}. Those constants are designed
	 * to match the values of the same constants on {@link java.sql.Connection}.
	 * <p>Exclusively designed for use with {@link #PROPAGATION_REQUIRED} or
	 * {@link #PROPAGATION_REQUIRES_NEW} since it only applies to newly started
	 * transactions. Consider switching the "validateExistingTransactions" flag to
	 * "true" on your transaction manager if you'd like isolation level declarations
	 * to get rejected when participating in an existing transaction with a different
	 * isolation level.
	 * <p>The default is {@link #ISOLATION_DEFAULT}. Note that a transaction manager
	 * that does not support custom isolation levels will throw an exception when
	 * given any other level than {@link #ISOLATION_DEFAULT}.
	 * @return the isolation level
	 * @see #ISOLATION_DEFAULT
	 * @see org.springframework.transaction.support.AbstractPlatformTransactionManager#setValidateExistingTransaction
	 */
	default int getIsolationLevel() {
		return ISOLATION_DEFAULT;
	}

	/**
	 * Return the transaction timeout.
	 * <p>Must return a number of seconds, or {@link #TIMEOUT_DEFAULT}.
	 * <p>Exclusively designed for use with {@link #PROPAGATION_REQUIRED} or
	 * {@link #PROPAGATION_REQUIRES_NEW} since it only applies to newly started
	 * transactions.
	 * <p>Note that a transaction manager that does not support timeouts will throw
	 * an exception when given any other timeout than {@link #TIMEOUT_DEFAULT}.
	 * <p>The default is {@link #TIMEOUT_DEFAULT}.
	 * @return the transaction timeout
	 */
	default int getTimeout() {
		return TIMEOUT_DEFAULT;
	}

	/**
	 * Return whether to optimize as a read-only transaction.
	 * <p>The read-only flag applies to any transaction context, whether backed
	 * by an actual resource transaction ({@link #PROPAGATION_REQUIRED}/
	 * {@link #PROPAGATION_REQUIRES_NEW}) or operating non-transactionally at
	 * the resource level ({@link #PROPAGATION_SUPPORTS}). In the latter case,
	 * the flag will only apply to managed resources within the application,
	 * such as a Hibernate {@code Session}.
	 * <p>This just serves as a hint for the actual transaction subsystem;
	 * it will <i>not necessarily</i> cause failure of write access attempts.
	 * A transaction manager which cannot interpret the read-only hint will
	 * <i>not</i> throw an exception when asked for a read-only transaction.
	 * @return {@code true} if the transaction is to be optimized as read-only
	 * ({@code false} by default)
	 * @see org.springframework.transaction.support.TransactionSynchronization#beforeCommit(boolean)
	 * @see org.springframework.transaction.support.TransactionSynchronizationManager#isCurrentTransactionReadOnly()
	 */
	default boolean isReadOnly() {
		return false;
	}

	/**
	 * Return the name of this transaction. Can be {@code null}.
	 * <p>This will be used as the transaction name to be shown in a
	 * transaction monitor, if applicable (for example, WebLogic's).
	 * <p>In case of Spring's declarative transactions, the exposed name will be
	 * the {@code fully-qualified class name + "." + method name} (by default).
	 * @return the name of this transaction ({@code null} by default}
	 * @see org.springframework.transaction.interceptor.TransactionAspectSupport
	 * @see org.springframework.transaction.support.TransactionSynchronizationManager#getCurrentTransactionName()
	 */
	@Nullable
	default String getName() {
		return null;
	}


	// Static builder methods

	/**
	 * Return an unmodifiable {@code TransactionDefinition} with defaults.
	 * <p>For customization purposes, use the modifiable
	 * {@link org.springframework.transaction.support.DefaultTransactionDefinition}
	 * instead.
	 * @since 5.2
	 */
	static TransactionDefinition withDefaults() {
		return StaticTransactionDefinition.INSTANCE;
	}

}
```


```java
public interface PlatformTransactionManager extends TransactionManager {

    TransactionStatus getTransaction(TransactionDefinition definition) throws TransactionException;

    void commit(TransactionStatus status) throws TransactionException;

    void rollback(TransactionStatus status) throws TransactionException;
}
```

AOP Alliance MethodInterceptor for declarative transaction management using the common Spring transaction infrastructure (PlatformTransactionManager/ org.springframework.transaction.ReactiveTransactionManager).
Derives from the TransactionAspectSupport class which contains the integration with Spring's underlying transaction API. TransactionInterceptor simply calls the relevant superclass methods such as invokeWithinTransaction in the correct order.
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

## References
1. [Transaction Management - Spring](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#transaction)