## Introduction

Spring Framework 为事务管理提供了一致的抽象，带来了以下好处：

- 跨不同事务 API（如 Java Transaction API (JTA)、JDBC、Hibernate、Java Persistence API (JPA) 和 Java Data Objects (JDO)）的一致编程模型。
- 支持声明式事务管理。
- 比复杂的事务 API（如 JTA）更简单的编程式事务管理 API。
- 与 Spring 的数据访问抽象出色集成。

让我们回忆一下在 application.yml 中声明 Spring Boot 数据源的样子：

```yaml
spring:
  datasource:
    url: ...
    username: ...
    password: ...
    driverClassname: ...
```

Spring 将这些设置映射到 org.springframework.boot.autoconfigure.jdbc.DataSourceProperties 的实例。
因此，要使用多个数据源，我们需要在 Spring 的应用上下文中声明具有不同映射的多个 bean。

DataSourceAutoConfiguration

DataSourceTransactionManagerAutoConfiguration

JdbcTemplateAutoConfiguration

将给定的 SQLException 转换为通用的 DataAccessException。

```java
public interface SQLExceptionTranslator {
	@Nullable
	DataAccessException translate(String task, @Nullable String sql, SQLException ex);
}
```
> JavaBean `SQLErrorCodes` define in `spring-jdbc/src/main/resources/org/springframework/jdbc/support/sql-error-codes.xml`.
> Can be overridden by definitions in a "`sql-error-codes.xml`" file in the root of the class path.

在 Spring Boot 2 和 Spring Boot 3 中，HikariCP 是默认的连接池，它会随 `spring-boot-starter-jdbc` 或 `spring-boot-starter-data-jpa` 启动依赖传递导入，因此你无需向项目添加任何额外依赖。
Spring Boot 会将 Hikari 特定的设置暴露给 `spring.datasource.hikari`。

事务策略由 org.springframework.transaction.PlatformTransactionManager 接口定义：
```java
public interface PlatformTransactionManager {

    TransactionStatus getTransaction(
            TransactionDefinition definition) throws TransactionException;

    void commit(TransactionStatus status) throws TransactionException;

    void rollback(TransactionStatus status) throws TransactionException;
}
```

TransactionDefinition 接口指定了：

- Isolation：此事务与其他事务的隔离程度。例如，此事务能否看到其他事务的未提交写入？
- Propagation：通常，在事务范围内执行的所有代码都将在该事务中运行。但是，你可以选择指定在已存在事务上下文的情况下执行事务方法时的行为。例如，代码可以在现有事务中继续运行（常见情况）；或者可以挂起现有事务并创建新事务。Spring 提供了 EJB CMT 中所有熟悉的事务传播选项。要阅读有关 Spring 中事务传播语义的信息，请参见第 16.5.7 节"事务传播"。
- Timeout：此事务在超时并被底层事务基础设施自动回滚之前的运行时间。
- Read-only status：当你的代码只读取但不修改数据时，可以使用只读事务。在某些情况下，只读事务可以作为有用的优化，例如使用 Hibernate 时。

## Programmatic transaction

核心方法是 execute，支持实现 TransactionCallback 接口的事务代码。
此模板处理事务生命周期和可能的异常，因此无论是 TransactionCallback 实现还是调用代码都不需要显式处理事务。

```java
public class TransactionTemplate extends DefaultTransactionDefinition
		implements TransactionOperations, InitializingBean {
		}
```

由 `TransactionTemplate.execute` 在事务上下文中调用。无需关心事务本身，但可以通过给定的状态对象获取和影响当前事务的状态，例如设置 rollback-only。
回调抛出的 RuntimeException 被视为强制回滚的应用异常。异常会传播给模板的调用者。

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

Spring Framework 的声明式事务管理是通过 Spring [面向切面编程](/docs/CS/Framework/Spring/AOP.md) (AOP) 实现的。
AOP 与事务元数据的结合产生了一个 AOP 代理，它使用 TransactionInterceptor 结合合适的 PlatformTransactionManager 实现来围绕方法调用驱动事务。

从概念上讲，在事务代理上调用方法看起来是这样的：

![](https://docs.spring.io/spring-framework/docs/4.2.x/spring-framework-reference/html/images/tx.png)

直接在 Java 源代码中声明事务语义使得声明更加接近受影响的代码。

### Transactional

描述单个方法或类上的事务属性。

当此注解在类级别声明时，它作为声明类及其子类的所有方法的默认值。
注意，它不适用于向上类层次结构的祖先类；继承的方法需要在子类级别重新声明才能参与子类级别的注解。
有关方法可见性约束的详细信息，请参阅参考手册的事务管理部分。

此注解类型通常与 Spring 的 org.springframework.transaction.interceptor.RuleBasedTransactionAttribute 类直接可比，
实际上 AnnotationTransactionAttributeSource 会直接将数据转换为后者，因此 Spring 的事务支持代码不必了解注解。

**如果没有自定义回滚规则，事务将在 RuntimeException 和 Error 上回滚，但不会在受检异常上回滚。**

有关此注解属性的语义的具体信息，请参阅 TransactionDefinition 和 `org.springframework.transaction.interceptor.TransactionAttribute` 的 javadocs。

此注解通常与由 `org.springframework.transaction.PlatformTransactionManager` 管理的线程绑定事务一起使用，将事务暴露给当前执行线程内的所有数据访问操作。

**注意：这不会传播到方法中启动的新线程。**

或者，此注解可以标记由 org.springframework.transaction.ReactiveTransactionManager 管理的响应式事务，后者使用 Reactor 上下文而不是线程局部变量。
因此，所有参与的数据访问操作需要在同一个响应式管道中的同一个 Reactor 上下文中执行。

> [!NOTE]
>
> When using proxies, you should apply the `@Transactional` annotation only to methods with public visibility.
> If you do annotate protected, private or package-visible methods with the `@Transactional` annotation, no error is raised, but the annotated method does not exhibit the configured transactional settings.
> Consider the use of AspectJ (see below) if you need to annotate non-public methods.

@Transactional 注解是元数据，指定接口、类或方法必须具有事务语义；
例如，"当调用此方法时，启动一个全新的只读事务，挂起任何现有事务"。
默认的 @Transactional 设置如下：

- Propagation 设置为 PROPAGATION_REQUIRED。
- Isolation 级别为 ISOLATION_DEFAULT。
- 事务为读/写。
- 事务超时默认为底层事务系统的默认超时，如果不支持超时则为无。
- 任何 RuntimeException 触发回滚，任何受检异常不会回滚。

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

表示用于 TransactionDefinition 接口的事务传播行为的枚举。

> [!NOTE]
>
> Note that isolation level and timeout settings will not get applied unless an actual new transaction gets started.
> As only `PROPAGATION_REQUIRED`, `PROPAGATION_REQUIRES_NEW` and `PROPAGATION_NESTED` can cause that, it usually doesn't make sense to specify those settings in other cases.

<!-- tabs:start -->
##### **PROPAGATION_REQUIRED**
`PROPAGATION_REQUIRED` 强制执行物理事务，如果当前范围尚无事务，则本地创建；如果已存在为更大范围定义的"外部"事务，则参与其中。在同一线程中的常见调用栈安排中，这是一个很好的默认设置（例如，服务外观委托给多个仓库方法，其中所有底层资源都必须参与服务级事务）。

当传播设置为 `PROPAGATION_REQUIRED` 时，每个应用此设置的方法都会创建一个逻辑事务范围。
每个这样的逻辑事务范围可以独立确定 rollback-only 状态，外部事务范围在逻辑上独立于内部事务范围。
在标准 `PROPAGATION_REQUIRED` 行为的情况下，所有这些范围都映射到同一个物理事务。
因此，在内部事务范围中设置的 rollback-only 标记确实会影响外部事务实际提交的机会。

然而，在内部事务范围设置 rollback-only 标记的情况下，外部事务尚未决定自己回滚，因此回滚（由内部事务范围静默触发）是意外的。
**此时会抛出相应的 `UnexpectedRollbackException`。**
这是预期的行为，这样事务的调用者永远不会被误导以为提交已执行而实际上并未执行。
因此，如果内部事务（外部调用者未察觉）静默地将事务标记为 rollback-only，外部调用者仍然调用 commit。
外部调用者需要收到 `UnexpectedRollbackException`，以明确指示已执行回滚。

##### **PROPAGATION_REQUIRES_NEW**

`PROPAGATION_REQUIRES_NEW` 与 PROPAGATION_REQUIRED 相反，总是为每个受影响的事务范围使用独立的物理事务，从不参与外部范围的现有事务。
在这种安排中，底层资源事务是不同的，因此可以独立提交或回滚，外部事务不受内部事务回滚状态的影响，内部事务的锁在其完成后立即释放。
这种独立的内部事务还可以声明自己的隔离级别、超时和只读设置，而不会继承外部事务的特性。

##### **PROPAGATION_NESTED**

`PROPAGATION_NESTED` 使用一个带有多个保存点的物理事务，它可以回滚到这些保存点。
**这种部分回滚允许内部事务范围触发其范围的回滚，而外部事务能够继续物理事务，尽管某些操作已被回滚。**
此设置通常映射到 JDBC 保存点，因此仅适用于 JDBC 资源事务。

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

由 MyBatis、Hibernate、JTA 实现。

```java
public interface PlatformTransactionManager extends TransactionManager {

    TransactionStatus getTransaction(TransactionDefinition definition) throws TransactionException;

    void commit(TransactionStatus status) throws TransactionException;

    void rollback(TransactionStatus status) throws TransactionException;
}
```

用于声明式事务管理的 AOP Alliance MethodInterceptor，使用通用的 Spring 事务基础设施（PlatformTransactionManager / org.springframework.transaction.ReactiveTransactionManager）。
派生自 TransactionAspectSupport 类，该类包含与 Spring 底层事务 API 的集成。
TransactionInterceptor 简单地按正确顺序调用相关的超类方法，例如 invokeWithinTransaction。
TransactionInterceptors 是线程安全的。
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

为当前线程注册一个新的事务同步。通常由资源管理代码调用。
注意，同步可以实现 `org.springframework.core.Ordered` 接口。它们将根据其顺序值（如果有）按顺序执行。

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

AbstractRoutingDataSource

### Rollback Rules

基于模式使用 `contains()`

## Tuning

### 事务失效

Spring 相关
- 未被 Spring 管理
- 多线程调用 数据库连接可能会不一样 事务不同, 例如使用 @Async 的函数是不支持事务 但函数内部调用的事务方法支持事务
- 事务传播特性设置不使用事务（较少）

声明式事务基于 [AOP](/docs/CS/Framework/Spring/AOP.md) 故导致函数无法被代理的情况
- 函数 access flag 非 public
- 函数是 final 或者 static
- 当前类里其它方法内部调用

异常相关
- catch 住异常后 Spring 无法感知异常做回滚处理
- 设置的回滚异常和实际抛出异常不对应
- 同个事务里子事务标记回滚 但是在外层 catch 住后 事务 commit `UnexpectedRollbackException`

其它情况
- 表不支持事务

### 长事务

长事务问题

长事务引发的常见危害有：

- 数据库连接池被占满，应用无法获取连接资源；
- 容易引发数据库死锁；
- 数据库回滚时间长；
- 在主从架构中会导致主从延时变大。

服务系统开始出现故障：数据库监控平台一直收到告警短信，数据库连接不足，出现大量死锁；日志显示调用流程引擎接口出现大量超时；同时一直提示 CannotGetJdbcConnectionException，数据库连接池连接占满。

Solution

长事务少用 `@Transactional` 使用编程式事务管理

拆分粒度
- select 放到事务外
- 减少 remote call, 发 MQ 消息, 其它 Redis MongoDB, 使用重试+补偿实现最终一致性
- 数据分批处理

可延时的行为 在事务外发送 MQ 消息 异步处理

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Transaction](/docs/CS/SE/Transaction.md)
- [Transaction - MySQL](/docs/CS/DB/MySQL/Transaction.md)

## References
1. [Transaction Management - Spring](https://docs.spring.io/spring-framework/docs/current/reference/html/data-access.html#transaction)
2. [Spring Boot项目业务代码中使用@Transactional事务失效踩坑点总结](https://mp.weixin.qq.com/s/S0-LUjC_f6ybYQi-dfK_sA)
