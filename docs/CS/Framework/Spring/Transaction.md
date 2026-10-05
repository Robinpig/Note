## Introduction

Spring Framework 提供了一致的事务管理抽象，带来这些收益：

- **跨事务 API 的一致编程模型**：JTA、JDBC、Hibernate、JPA、JDO 等都能用同一套方式编写事务代码。
- **声明式事务支持**：用 `@Transactional` 等注解替代命令式样板。
- **比 JTA 等复杂 API 更简单的编程式事务**：`TransactionTemplate` 封装了生命周期与异常。
- **与 Spring 数据访问抽象的良好集成**。

先回顾一下 Spring Boot 里声明数据源在 `application.yml` 中的样子：


```yaml
spring:
  datasource:
    url: ...
    username: ...
    password: ...
    driver-class-name: ...
```

Spring 把这些配置映射到 `org.springframework.boot.autoconfigure.jdbc.DataSourceProperties` 的实例。
因此，若要使用多个数据源，就需要在 Spring 应用上下文里声明多个对应不同映射的 Bean。


DataSourceAutoConfiguration

DataSourceTransactionManagerAutoConfiguration

JdbcTemplateAutoConfiguration



将给定的 `SQLException` 翻译成统一的 `DataAccessException`。

```java
public interface SQLExceptionTranslator {
	@Nullable
	DataAccessException translate(String task, @Nullable String sql, SQLException ex);
}
```
> `SQLErrorCodes` 这个 JavaBean 定义在 `spring-jdbc/src/main/resources/org/springframework/jdbc/support/sql-error-codes.xml`。
> 也可以在 classpath 根目录放一份 `sql-error-codes.xml` 来覆盖默认定义。


从 Spring Boot 2 起直到当前的 Boot 4，HikariCP 一直是默认连接池，由 `spring-boot-starter-jdbc` 或 `spring-boot-starter-data-jpa` 传递引入，通常无需额外声明依赖。
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

The Spring Framework’s declarative transaction management is made possible with Spring [aspect-oriented programming](/docs/CS/Framework/Spring/AOP.md) (AOP).
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

**若未自定义回滚规则，事务只在遇到 RuntimeException 与 Error 时回滚，受检异常（checked exception）不会触发回滚。**

关于该注解各属性的语义细节，参见 `TransactionDefinition` 与 `org.springframework.transaction.interceptor.TransactionAttribute` 的 javadoc。

This annotation commonly works with thread-bound transactions managed by a `org.springframework.transaction.PlatformTransactionManager`, exposing a transaction to all data access operations within the current execution thread. 

**Note: This does NOT propagate to newly started threads within the method.**

Alternatively, this annotation may demarcate a reactive transaction managed by a org.springframework.transaction.ReactiveTransactionManager which uses the Reactor context instead of thread-local variables. 
As a consequence, all participating data access operations need to execute within the same Reactor context in the same reactive pipeline.


> [!NOTE]
>
> 使用代理模式时，`@Transactional` 应只标在 **public** 可见性的方法上。若标在 protected / private / 包级可见方法上，不会报错，但该方法**不会**表现出配置的事务行为。若确实需要给非 public 方法加事务，应考虑使用 AspectJ 织入（见下文）。


The @Transactional annotation is metadata that specifies that an interface, class, or method must have transactional semantics; 
for example, "start a brand new read-only transaction when this method is invoked, suspending any existing transaction". 
The default @Transactional settings are as follows:

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

早期 XML 风格的代理工厂 Bean，现在基本被 `@Transactional` + 自动代理取代，了解即可。

## TransactionManager

实现方包括 MyBatis、Hibernate、JTA。响应式场景下还有 `ReactiveTransactionManager`，它配合 Reactor 的 `Context` 而非 ThreadLocal 来传递事务状态（见下文「响应式事务」）。

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
        } else {
            // The TransactionInfo.hasTransaction() method will return false. We created it only
            // to preserve the integrity of the ThreadLocal stack maintained in this class.

            // We always bind the TransactionInfo to the thread, even if we didn't create
            // a new transaction here. This guarantees that the TransactionInfo stack
            // will be managed correctly even if no transaction was created by this aspect.
            txInfo.bindToThread();
            return txInfo;
        }
    }
```

### TransactionInterceptor

```properties
logging.level.org.springframework.transaction.interceptor.TransactionAspectSupport=TRACE
```

```java
public class TransactionInterceptor extends TransactionAspectSupport implements MethodInterceptor, Serializable {
@Override
	@Nullable
	public Object invoke(MethodInvocation invocation) throws Throwable {
		// Work out the target class: may be {@code null}.
		// The TransactionAttributeSource should be passed the target class
		// as well as the method, which may be from an interface.
		Class<?> targetClass = (invocation.getThis() != null ? AopUtils.getTargetClass(invocation.getThis()) : null);

		// Adapt to TransactionAspectSupport's invokeWithinTransaction...
		return invokeWithinTransaction(invocation.getMethod(), targetClass, new CoroutinesInvocationCallback() {
			@Override
			@Nullable
			public Object proceedWithInvocation() throws Throwable {
				return invocation.proceed();
			}
			@Override
			public Object getTarget() {
				return invocation.getThis();
			}
			@Override
			public Object[] getArguments() {
				return invocation.getArguments();
			}
		});
	}
}

public abstract class TransactionAspectSupport implements BeanFactoryAware, InitializingBean {
@Nullable
	protected Object invokeWithinTransaction(Method method, @Nullable Class<?> targetClass,
			final InvocationCallback invocation) throws Throwable {

		// If the transaction attribute is null, the method is non-transactional.
		TransactionAttributeSource tas = getTransactionAttributeSource();
		final TransactionAttribute txAttr = (tas != null ? tas.getTransactionAttribute(method, targetClass) : null);
		final TransactionManager tm = determineTransactionManager(txAttr);

		if (this.reactiveAdapterRegistry != null && tm instanceof ReactiveTransactionManager rtm) {
			boolean isSuspendingFunction = KotlinDetector.isSuspendingFunction(method);
			boolean hasSuspendingFlowReturnType = isSuspendingFunction &&
					COROUTINES_FLOW_CLASS_NAME.equals(new MethodParameter(method, -1).getParameterType().getName());
			if (isSuspendingFunction && !(invocation instanceof CoroutinesInvocationCallback)) {
				throw new IllegalStateException("Coroutines invocation not supported: " + method);
			}
			CoroutinesInvocationCallback corInv = (isSuspendingFunction ? (CoroutinesInvocationCallback) invocation : null);

			ReactiveTransactionSupport txSupport = this.transactionSupportCache.computeIfAbsent(method, key -> {
				Class<?> reactiveType =
						(isSuspendingFunction ? (hasSuspendingFlowReturnType ? Flux.class : Mono.class) : method.getReturnType());
				ReactiveAdapter adapter = this.reactiveAdapterRegistry.getAdapter(reactiveType);
				if (adapter == null) {
					throw new IllegalStateException("Cannot apply reactive transaction to non-reactive return type [" +
							method.getReturnType() + "] with specified transaction manager: " + tm);
				}
				return new ReactiveTransactionSupport(adapter);
			});

			InvocationCallback callback = invocation;
			if (corInv != null) {
				callback = () -> KotlinDelegate.invokeSuspendingFunction(method, corInv);
			}
			return txSupport.invokeWithinTransaction(method, targetClass, callback, txAttr, rtm);
		}

		PlatformTransactionManager ptm = asPlatformTransactionManager(tm);
		final String joinpointIdentification = methodIdentification(method, targetClass, txAttr);

		if (txAttr == null || !(ptm instanceof CallbackPreferringPlatformTransactionManager cpptm)) {
			// Standard transaction demarcation with getTransaction and commit/rollback calls.
			TransactionInfo txInfo = createTransactionIfNecessary(ptm, txAttr, joinpointIdentification);

			Object retVal;
			try {
				// This is an around advice: Invoke the next interceptor in the chain.
				// This will normally result in a target object being invoked.
				retVal = invocation.proceedWithInvocation();
			}
			catch (Throwable ex) {
				// target invocation exception
				completeTransactionAfterThrowing(txInfo, ex);
				throw ex;
			}
			finally {
				cleanupTransactionInfo(txInfo);
			}

			if (retVal != null && txAttr != null) {
				TransactionStatus status = txInfo.getTransactionStatus();
				if (status != null) {
					if (retVal instanceof Future<?> future && future.isDone()) {
						try {
							future.get();
						}
						catch (ExecutionException ex) {
							if (txAttr.rollbackOn(ex.getCause())) {
								status.setRollbackOnly();
							}
						}
						catch (InterruptedException ex) {
							Thread.currentThread().interrupt();
						}
					}
					else if (vavrPresent && VavrDelegate.isVavrTry(retVal)) {
						// Set rollback-only in case of Vavr failure matching our rollback rules...
						retVal = VavrDelegate.evaluateTryFailure(retVal, txAttr, status);
					}
				}
			}

			commitTransactionAfterReturning(txInfo);
			return retVal;
		}

		else {
			Object result;
			final ThrowableHolder throwableHolder = new ThrowableHolder();

			// It's a CallbackPreferringPlatformTransactionManager: pass a TransactionCallback in.
			try {
				result = cpptm.execute(txAttr, status -> {
					TransactionInfo txInfo = prepareTransactionInfo(ptm, txAttr, joinpointIdentification, status);
					try {
						Object retVal = invocation.proceedWithInvocation();
						if (retVal != null && vavrPresent && VavrDelegate.isVavrTry(retVal)) {
							// Set rollback-only in case of Vavr failure matching our rollback rules...
							retVal = VavrDelegate.evaluateTryFailure(retVal, txAttr, status);
						}
						return retVal;
					}
					catch (Throwable ex) {
						if (txAttr.rollbackOn(ex)) {
							// A RuntimeException: will lead to a rollback.
							if (ex instanceof RuntimeException runtimeException) {
								throw runtimeException;
							}
							else {
								throw new ThrowableHolderException(ex);
							}
						}
						else {
							// A normal return value: will lead to a commit.
							throwableHolder.throwable = ex;
							return null;
						}
					}
					finally {
						cleanupTransactionInfo(txInfo);
					}
				});
			}
			catch (ThrowableHolderException ex) {
				throw ex.getCause();
			}
			catch (TransactionSystemException ex2) {
				if (throwableHolder.throwable != null) {
					logger.error("Application exception overridden by commit exception", throwableHolder.throwable);
					ex2.initApplicationException(throwableHolder.throwable);
				}
				throw ex2;
			}
			catch (Throwable ex2) {
				if (throwableHolder.throwable != null) {
					logger.error("Application exception overridden by commit exception", throwableHolder.throwable);
				}
				throw ex2;
			}

			// Check result state: It might indicate a Throwable to rethrow.
			if (throwableHolder.throwable != null) {
				throw throwableHolder.throwable;
			}
			return result;
		}
	}
}	
```

### TransactionSynchronizationManager

Register a new transaction synchronization for the current thread. Typically called by resource management code.
Note that synchronizations can implement the `org.springframework.core.Ordered` interface. They will be executed in an order according to their order value (if any).

```java
public abstract class TransactionSynchronizationManager {

    private static final ThreadLocal<Map<Object, Object>> resources =
            new NamedThreadLocal<>("Transactional resources");

    private static final ThreadLocal<Set<TransactionSynchronization>> synchronizations =
            new NamedThreadLocal<>("Transaction synchronizations");

    private static final ThreadLocal<String> currentTransactionName =
            new NamedThreadLocal<>("Current transaction name");

    private static final ThreadLocal<Boolean> currentTransactionReadOnly =
            new NamedThreadLocal<>("Current transaction read-only status");

    private static final ThreadLocal<Integer> currentTransactionIsolationLevel =
            new NamedThreadLocal<>("Current transaction isolation level");

    private static final ThreadLocal<Boolean> actualTransactionActive =
            new NamedThreadLocal<>("Actual transaction active");
    
    public static void registerSynchronization(TransactionSynchronization synchronization)
            throws IllegalStateException {
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

多数据源场景下，Spring 不替你做事务跨库协调。常见做法有两种：用 `AbstractRoutingDataSource` 做读写分离 / 分库路由（一个 `DataSource` 内部按 key 切换真实数据源，事务仍在同一库内）；跨库分布式事务则需引入 JTA / Seata 等外部协调器。

### Rollback Rules

Pattern-based use `contains()`

## 响应式事务

在 WebFlux / R2DBC 这类响应式栈里，没有"当前线程"承载事务，Spring 用 Reactor 的 `Context` 而不是 `ThreadLocal` 来传递事务状态。对应接口是 `ReactiveTransactionManager`：

- `@Transactional` 标注的响应式方法（返回 `Mono` / `Flux`，或 Kotlin `suspend` 函数）由响应式子栈处理；
- **所有参与的数据访问操作必须处在同一个 Reactor `Context` / 同一条响应式 pipeline 内**，否则 `Context` 丢失，事务不生效；
- 回滚规则、传播行为（`PROPAGATION_REQUIRED` 等）语义与命令式事务一致，但底层用 Reactor 算子实现，不能在响应式链里随意 `subscribe()` 到别的线程或切出新 `Context`。

声明式事务的 AOP 代理（见 [AOP](/docs/CS/Framework/Spring/AOP.md)）在响应式场景由 `TransactionalOperator` / `ReactiveTransactionInterceptor` 承载，而非 `TransactionInterceptor`。

## Tuning

### 事务失效


Spring相关
- 未被 Spring 管理
- 多线程调用 数据库连接可能会不一样 事务不同, 例如使用@Async的函数是不支持事务 但函数内部调用的事务方法支持事务
- 事务传播特性设置不使用事务(较少)


声明式事务基于[AOP](/docs/CS/Framework/Spring/AOP.md) 故导致函数无法被代理的情况
- 函数access flag非 public
- 函数是 final 或者 static
- 当前类里其它方法内部调用

异常相关
- catch 住异常后 Spring 无法感知异常做回滚处理
- 设置的回滚异常和实际抛出异常不对应
- 同个事务里子事务标记回滚 但是在外层 catch 住后 事务commit `UnexpectedRollbackException`

其它情况
- 表不支持事务


### 长事务

长事务问题

长事务引发的常见危害有：

- 数据库连接池被占满，应用无法获取连接资源；
- 容易引发数据库死锁；
- 数据库回滚时间长；
- 在主从架构中会导致主从延时变大。

服务系统开始出现故障：数据库监控平台一直收到告警短信，数据库连接不足，出现大量死锁；日志显示调用流程引擎接口出现大量超时；同时一直提示CannotGetJdbcConnectionException，数据库连接池连接占满。


Solution

长事务少用 `@Transactional` 使用编程式事务管理

拆分粒度 
- select放到事务外
- 减少remote call, 发 MQ 消息, 其它Redis MongoDB, 使用重试+补偿实现最终一致性
- 数据分批处理 

可延时的行为 在事务外发送 MQ 消息 异步处理

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Transaction](/docs/CS/SE/Transaction.md)
- [Transaction - MySQL](/docs/CS/DB/MySQL/Transaction.md)
- [Spring JPA](/docs/CS/Framework/Spring/JPA.md)
- [Spring 事件](/docs/CS/Framework/Spring/Event.md)
- [Spring 缓存抽象](/docs/CS/Framework/Spring/Cache.md)


## References
1. [Transaction Management - Spring](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#transaction)
2. [Spring Boot项目业务代码中使用@Transactional事务失效踩坑点总结](https://mp.weixin.qq.com/s/S0-LUjC_f6ybYQi-dfK_sA)
