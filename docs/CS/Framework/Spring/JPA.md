## Introduction

Spring Data JPA, part of the larger Spring Data family, makes it easy to easily implement JPA-based (Java Persistence API) repositories.

> [!NOTE]
> Boot 4 / Framework 7 的 Jakarta Persistence 基线是 **3.2**，默认搭配 **Hibernate ORM 7.1**。Hibernate 7 相比 6.x 是"平缓"的一次升级，但有几处**语义收紧**值得先记住，因为它们的共同点是不在编译期报错：
>
> | 变更 | 表现 |
> | :-- | :-- |
> | 不再允许把游离（detached）实体重新关联到持久化上下文 | `update()` / `saveOrUpdate()` / `lock()` 已移除；`refresh()` 游离实体抛 `IllegalArgumentException`；`hibernate.allow_refresh_detached_entity` 配置一并删除 |
> | `@Id` / `@MapsId` 不再隐式 `cascade=PERSIST` | 依赖旧行为的实体在保存时**子对象静默不落库**，必须显式补 `cascade = CascadeType.PERSIST` |
> | 原生查询的时间类型默认改为 `java.time` | 无 `@SqlResultSetMapping` 时返回 `LocalDateTime` 而非 `java.sql.Timestamp`，旧代码出现 `ClassCastException`；可用 `hibernate.query.native.prefer_jdbc_datetime_types=true` 回退 |
> | Criteria API 不再允许隐式 treat | 取子类型属性必须先 `cb.treat(root, SubType.class)` |
> | 实体扫描需要 `hibernate-scan-jandex` 模块 | 独立（非 Boot）应用缺少该模块时**不报错**，只是表映射整体消失 |
>
> 处理游离实体在 Hibernate 7 只剩两条路：JPA 标准的 `merge()`，或者 `StatelessSession`。

本文讲 **JPA 侧**的内容（实体映射、持久化上下文、抓取策略、缓存、锁、审计）；Repository 抽象、派生查询、分页排序等通用能力见 [Spring Data](/docs/CS/Framework/Spring/Data.md)。

## Entity Mapping

### Common Annotations

```java
@Entity                    // 声明为 JPA 实体（注意不是 @Entiry）
@Table(name = "t_order")   // 表名、schema、唯一约束
@MappedSuperclass          // 父类映射，自身不建表（基类放审计字段/id）
@Embeddable / @Embedded    // 值对象内联进同一张表
@Id                        // 主键
@GeneratedValue(strategy = ...)  // 主键生成策略
@SequenceGenerator / @TableGenerator
@Column(name, nullable, unique, length, precision)
@Enumerated(EnumType.ORDINAL | STRING)  // 枚举落库方式，生产建议 STRING
@Temporal                  // java.util.Date/Calendar 精度，java.time 不需要
@Transient                 // 非持久化字段
@Lob                       // 大对象
@Convert(converter = ...)  // AttributeConverter 自定义类型转换
```

`@MappedSuperclass` 与 `@Embeddable` 常被混淆：前者是**继承**（子类各自建表，字段合并进去），后者是**组合**（值对象内联，可复用、可嵌套）。

### Primary Key Generation Strategy

| 策略 | 机制 | 适用 | 代价 |
| :-- | :-- | :-- | :-- |
| `AUTO` | 由 provider 自选（Hibernate 7 通常选 `SEQUENCE`） | 快速起步 | 跨库迁移时行为会变 |
| `IDENTITY` | 依赖数据库自增列 | MySQL 常见 | **插入时必须立刻回读 ID，导致 JDBC batch 失效** |
| `SEQUENCE` | 数据库序列，Hibernate 可预分配 | PostgreSQL / Oracle | 需配 `allocationSize` |
| `TABLE` | 用一张表模拟序列 | 兼容老库 | 并发下是热点行，性能最差 |
| `UUID`（JPA 3.1+） | 生成 UUID 字符串 | 分布式 ID、不想依赖 DB | 索引与存储开销大 |

两个高频坑：

- **`allocationSize` 与数据库 `INCREMENT BY` 不一致** —— Hibernate 默认 `allocationSize=50`（走 pooled optimizer），若数据库序列 `INCREMENT BY 1`，每次重启应用都会出现"ID 跳跃"。要么两边对齐，要么显式 `allocationSize = 1`。
- **`IDENTITY` 与批量插入不可兼得** —— Hibernate 无法延迟执行 insert，这是 `hibernate.jdbc.batch_size` 配了却不见效的头号原因。

```java
@Id
@GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "order_seq")
@SequenceGenerator(name = "order_seq", sequenceName = "order_seq", allocationSize = 50)
private Long id;
```

## Repository Proxy Creation

Spring Data Repository 是**接口**，没有实现类。容器里真正注册的是一个动态代理，启动时由 `@EnableJpaRepositories`（Boot 下自动配置）触发扫描与注册。

### Annotation-Driven Wiring

```java
@Configuration
@EnableJpaRepositories
@EnableTransactionManagement
class ApplicationConfig {

  @Bean
  public DataSource dataSource() {

    EmbeddedDatabaseBuilder builder = new EmbeddedDatabaseBuilder();
    return builder.setType(EmbeddedDatabaseType.HSQL).build();
  }

  @Bean
  public LocalContainerEntityManagerFactoryBean entityManagerFactory() {

    HibernateJpaVendorAdapter vendorAdapter = new HibernateJpaVendorAdapter();
    vendorAdapter.setGenerateDdl(true);

    LocalContainerEntityManagerFactoryBean factory = new LocalContainerEntityManagerFactoryBean();
    factory.setJpaVendorAdapter(vendorAdapter);
    factory.setPackagesToScan("com.acme.domain");
    factory.setDataSource(dataSource());
    return factory;
  }

  @Bean
  public PlatformTransactionManager transactionManager(EntityManagerFactory entityManagerFactory) {

    JpaTransactionManager txManager = new JpaTransactionManager();
    txManager.setEntityManagerFactory(entityManagerFactory);
    return txManager;
  }
}
```

### JpaRepositoriesRegistrar

`@EnableJpaRepositories` 由 `ImportBeanDefinitionRegistrar` 实现，把"扫描哪些包"变成 `BeanDefinition` 批量注册：

```java
class JpaRepositoriesRegistrar extends RepositoryBeanDefinitionRegistrarSupport {

	@Override
	protected Class<? extends Annotation> getAnnotation() {
		return EnableJpaRepositories.class;
	}

	@Override
	protected RepositoryConfigurationExtension getExtension() {
		return new JpaRepositoryConfigExtension();
	}
}

public abstract class RepositoryBeanDefinitionRegistrarSupport
		implements ImportBeanDefinitionRegistrar, ResourceLoaderAware, EnvironmentAware {

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry,
                                        BeanNameGenerator generator) {

        AnnotationRepositoryConfigurationSource configurationSource = new AnnotationRepositoryConfigurationSource(metadata,
                getAnnotation(), resourceLoader, environment, registry, generator);

        RepositoryConfigurationExtension extension = getExtension();
        RepositoryConfigurationUtils.exposeRegistration(extension, registry, configurationSource);

        RepositoryConfigurationDelegate delegate = new RepositoryConfigurationDelegate(configurationSource, resourceLoader,
                environment);

        delegate.registerRepositoriesIn(registry, extension);
    }
}

public class JpaRepositoryConfigExtension extends RepositoryConfigurationExtensionSupport {

    @Override
    public String getRepositoryFactoryBeanClassName() {
        return JpaRepositoryFactoryBean.class.getName();
    }
}
```

### Lazy Initialization

注册进容器的是 `FactoryBean`，且目标对象是**惰性**创建的——非 `lazyInit` 时才在 `afterPropertiesSet` 里立即解析：

```java
public class JpaRepositoryFactoryBean<T extends Repository<S, ID>, S, ID>
		extends TransactionalRepositoryFactoryBeanSupport<T, S, ID> {

    public void afterPropertiesSet() {
        this.factory = createRepositoryFactory();
        // ...

        this.repository = Lazy.of(() -> this.factory.getRepository(repositoryInterface, repositoryFragmentsToUse));
        // ...
        if (!lazyInit) {
            this.repository.get();
        }
    }
}
```

### Create Proxy and Weave Interceptor

```java
public abstract class RepositoryFactorySupport implements BeanClassLoaderAware, BeanFactoryAware {
    public <T> T getRepository(Class<T> repositoryInterface, RepositoryFragments fragments) {
        ApplicationStartup applicationStartup = getStartup();
        StartupStep repositoryInit = onEvent(applicationStartup, "spring.data.repository.init", repositoryInterface);
        StartupStep repositoryMetadataStep = onEvent(applicationStartup, "spring.data.repository.metadata",
                repositoryInterface);
        StartupStep repositoryCompositionStep = onEvent(applicationStartup, "spring.data.repository.composition",
                repositoryInterface);

        StartupStep repositoryTargetStep = onEvent(applicationStartup, "spring.data.repository.target",
                repositoryInterface);
        // ...

        Object target = getTargetRepository(information);
        // Create proxy
        StartupStep repositoryProxyStep = onEvent(applicationStartup, "spring.data.repository.proxy", repositoryInterface);
        ProxyFactory result = new ProxyFactory();
        result.setTarget(target);
        result.setInterfaces(repositoryInterface, Repository.class, TransactionalProxy.class);

        if (MethodInvocationValidator.supports(repositoryInterface)) {
            result.addAdvice(new MethodInvocationValidator());
        }

        result.addAdvisor(ExposeInvocationInterceptor.ADVISOR);

        if (!postProcessors.isEmpty()) {
            StartupStep repositoryPostprocessorsStep = onEvent(applicationStartup, "spring.data.repository.postprocessors",
                    repositoryInterface);
            postProcessors.forEach(processor -> {

                StartupStep singlePostProcessor = onEvent(applicationStartup, "spring.data.repository.postprocessor",
                        repositoryInterface);
                singlePostProcessor.tag("type", processor.getClass().getName());
                processor.postProcess(result, information);
                singlePostProcessor.end();
            });
            repositoryPostprocessorsStep.end();
        }

        if (DefaultMethodInvokingMethodInterceptor.hasDefaultMethods(repositoryInterface)) {
            result.addAdvice(new DefaultMethodInvokingMethodInterceptor());
        }

        Optional<QueryLookupStrategy> queryLookupStrategy = getQueryLookupStrategy(queryLookupStrategyKey,
                evaluationContextProvider);
        result.addAdvice(new QueryExecutorMethodInterceptor(information, getProjectionFactory(), queryLookupStrategy,
                namedQueries, queryPostProcessors, methodInvocationListeners));

        result.addAdvice(
                new ImplementationMethodExecutionInterceptor(information, compositionToUse, methodInvocationListeners));

        T repository = (T) result.getProxy(classLoader);
        repositoryProxyStep.end();
        repositoryInit.end();

        return repository;
    }
}
```

注意代理实现了 `TransactionalProxy` —— 这就是为什么 Repository 上的 `@Transactional` 能被 `TransactionInterceptor` 识别并在**代理层而非目标类**上生效。

### Query Execution

派生方法、字符串查询最终都落到 `QueryExecutorMethodInterceptor` 上分发：

```java
class QueryExecutorMethodInterceptor implements MethodInterceptor {
    public QueryExecutorMethodInterceptor(RepositoryInformation repositoryInformation,
                                          ProjectionFactory projectionFactory, Optional<QueryLookupStrategy> queryLookupStrategy, NamedQueries namedQueries,
                                          List<QueryCreationListener<?>> queryPostProcessors,
                                          List<RepositoryMethodInvocationListener> methodInvocationListeners) {
        // ...
        this.resultHandler = new QueryExecutionResultHandler(RepositoryFactorySupport.CONVERSION_SERVICE);
        this.queries = queryLookupStrategy //
                .map(it -> mapMethodsToQuery(repositoryInformation, it, projectionFactory)) //
                .orElse(Collections.emptyMap());
    }

    @Override
    @Nullable
    public Object invoke(@SuppressWarnings("null") MethodInvocation invocation) throws Throwable {
        Method method = invocation.getMethod();
        QueryExecutionConverters.ExecutionAdapter executionAdapter = QueryExecutionConverters //
                .getExecutionAdapter(method.getReturnType());

        if (executionAdapter == null) {
            return resultHandler.postProcessInvocationResult(doInvoke(invocation), method);
        }
        return executionAdapter //
                .apply(() -> resultHandler.postProcessInvocationResult(doInvoke(invocation), method));
    }

    @Nullable
    private Object doInvoke(MethodInvocation invocation) throws Throwable {
        Method method = invocation.getMethod();
        if (hasQueryFor(method)) {
            // ...
            return invocationMetadata.invoke(repositoryInformation.getRepositoryInterface(), invocationMulticaster,
                    invocation.getArguments());
        }
        return invocation.proceed();
    }
}
```

SQL 解析实现在 commons 包里。

## Persistence Context and Entity State

### Four States and Corresponding Operations

| 状态 | 含义 | 进入方式 | 退出方式 |
| :-- | :-- | :-- | :-- |
| 瞬时 transient | 无 ID、未被上下文管理 | `new` | `persist()` |
| 托管 managed | 在持久化上下文中，变更会被脏检查捕捉 | `find()` / `persist()` / `merge()` 返回值 | `detach()` / `clear()` / 事务结束 |
| 游离 detached | 有 ID 但已脱离上下文 | 上下文关闭 | `merge()`（Hibernate 7 唯一合法回归路径） |
| 删除 removed | 已安排删除 | `remove()` | flush 后真正 `DELETE` |

最容易踩的两点：

- **`merge()` 的返回值才是托管对象**。继续改传入的那个引用，改动不会落库，且不报错。
- **`persist()` 传游离实体会抛 `PersistentObjectException`**（而不是静默忽略）。

### First-Level Cache and Dirty Checking

持久化上下文本身就是**一级缓存**：同一个 ID 在一次会话内只会得到一个 Java 对象（保证 `a == b`），并保存一份加载时的快照；flush 时逐字段比对快照，有差异才生成 `UPDATE`。

它无法关闭，因此批量处理大批量数据时，会话会在内存中无界增长——要么周期性 `clear()`，要么改用 `StatelessSession`（Hibernate 7 起其能力已与 `Session` 基本对等，且能读写二级缓存）。

### Hibernate 7 detached Tightening

旧代码里这些写法在 Hibernate 7 全部失效：

```java
// Hibernate 6（能跑但已废弃），Hibernate 7 已移除
session.update(detachedProduct);
session.saveOrUpdate(detachedProduct);
session.lock(detachedProduct, LockMode.PESSIMISTIC_WRITE);
session.refresh(detachedProduct);          // 现在抛 IllegalArgumentException

// Hibernate 7 的两种正解
Product managed = session.merge(detachedProduct);   // JPA 标准，注意用返回值
// 或 StatelessSession
```

把游离子实体挂到托管父实体上也会在 flush 时炸：

```java
parent.addChild(detachedChild);            // Hibernate 7：flush 时抛 EntityExistsException
parent.addChild(session.merge(child));     // 正确
```

## Eager Fetch and N+1

### Default Fetch Strategy

关联注解自带的默认值是问题的根源：`@OneToOne` / `@ManyToOne` 默认 **EAGER**，`@OneToMany` / `@ManyToMany` 默认 **LAZY**。EAGER 是"永远无法关闭的隐式 join"，一旦实体被任何查询加载，关联的额外 SQL 就必然发出。

经验是把所有关联显式声明为 `LAZY`，再按查询场景用 entity graph 逐个补加载。

### Lazy-Loading Proxy Trap

`@ManyToOne(fetch = LAZY)` 返回的是一个**代理对象**，字段要等首次访问时才去查库；如果此时持久化上下文已关闭，抛 `LazyInitializationException`。典型触发场景是"事务方法返回实体 → 序列化成 JSON 时访问懒字段"。

三种正解：

1. 查询时就加载（join fetch / entity graph），见下节；
2. 只取需要的字段：DTO 投影或 `interface` 投影，避免序列化整个实体；
3. 让上下文在视图渲染期间仍打开——`spring.jpa.open-in-view`，Boot **默认开启**并在启动日志打 WARN。它用一次长连接换"不报错"，代价是连接持有时间被拉长、并发下连接池更容易打满；生产建议显式关掉：

```properties
spring.jpa.open-in-view=false
```

> [!WARNING]
> `hibernate.enable_lazy_load_no_trans=true` 也能消除该异常，但它会在每次访问懒字段时临时开一个新会话，等于把 N+1 藏起来并让一致性失去保证，属反模式。

### Entity Graph and join fetch

N+1 的标准形态：1 条查主表 + N 条查关联。三种手段按推荐度排列：

| 手段 | 写法 | 适用 |
| :-- | :-- | :-- |
| `@EntityGraph` | 注解在 Repository 方法上，声明式 | 最常用的定点优化 |
| `JOIN FETCH` | 写在 JPQL 里 | 需要配合其它查询条件时 |
| 批量抓取 | `@BatchSize` / `hibernate.default_batch_fetch_size` | 把 N 条 SQL 压成 N/batch 条，兜底方案 |

```java
@Entity
@NamedEntityGraph(name = "Order.withItems",
        attributeNodes = @NamedAttributeNode("items"))
public class Order { /* ... */ }

public interface OrderRepository extends JpaRepository<Order, Long> {

    @EntityGraph(value = "Order.withItems", type = EntityGraphType.LOAD)
    List<Order> findByStatus(OrderStatus status);
}
```

`type` 的语义差别容易记反：

- `LOAD`（`loadgraph`）—— 图中列出的属性按 EAGER 加载，**未列出的沿用注解声明**；
- `FETCH`（`fetchgraph`）—— 图中列出的按 EAGER 加载，**未列出的一律按 LAZY 处理**。

> [!TIP]
> `@EntityGraph` 本质是把关联变成 join，与分页（`Pageable`）联用时会出现"内存分页"警告：join 出多行后无法在 SQL 层 `LIMIT`，Hibernate 只能全部载入后再切页。分页场景要么改用 `@BatchSize`，要么拆成"先查 ID 页、再按 ID 批量取关联"两查。

## Cache

### Three-Level Cache Comparison

| 层级 | 作用域 | 是否默认开启 | 存什么 |
| :-- | :-- | :-- | :-- |
| 一级缓存（持久化上下文） | 一次会话 / 事务 | 必然开启，不可关 | 实体实例本身 |
| 二级缓存（L2C） | 整个 `SessionFactory`，跨会话共享 | 需显式开启 | 实体的**状态快照**（按 ID 查才命中） |
| 查询缓存 | 全局 | 需显式开启 | 查询结果对应的 **ID 集合**，必须与二级缓存配合 |

关键认知：二级缓存**只按主键命中**。JPQL / 派生查询不会自动走二级缓存，除非叠加查询缓存。

### Enable Second-Level Cache

Hibernate 6 起不再为各缓存厂商提供 `hibernate-ehcache` 这类适配模块，统一走 JSR-107（JCache）：

```properties
spring.jpa.properties.hibernate.cache.use_second_level_cache=true
spring.jpa.properties.hibernate.cache.region.factory_class=jcache
spring.jpa.properties.hibernate.javax.cache.provider=org.ehcache.jsr107.EhcacheCachingProvider
spring.jpa.properties.hibernate.javax.cache.uri=classpath:ehcache.xml
# 只对标了 @Cacheable 的实体生效，避免全表缓存
spring.jpa.properties.jakarta.persistence.sharedCache.mode=ENABLE_SELECTIVE
```

实体侧：

```java
@Entity
@Cacheable
@org.hibernate.annotations.Cache(usage = CacheConcurrencyStrategy.READ_WRITE)
public class Product {
    @Id private Long id;

    @Cache(usage = CacheConcurrencyStrategy.READ_WRITE)
    @OneToMany(mappedBy = "product", fetch = FetchType.LAZY)
    private List<Review> reviews;   // 集合缓存要单独标注
}
```

并发策略选型：`READ_ONLY`（字典类数据，最快）、`NONSTRICT_READ_WRITE`（很少改、容忍短暂不一致）、`READ_WRITE`（读多写少，用软锁保证）、`TRANSACTIONAL`（需 JTA，最慢）。

> [!NOTE]
> 二级缓存是**进程内**缓存，多实例部署时各节点互不知情，仍是可能读到旧数据。跨节点一致性要靠 Infinispan / Redis(Redisson) 这类分布式实现，或直接用 [Spring Cache](/docs/CS/Framework/Spring/Cache.md) 在业务层做——后者对失效时机的控制更直观。

## Lock and Concurrency

### Optimistic Lock

`@Version` 字段让 Hibernate 在 `UPDATE` 时带上版本条件，命中 0 行即判定冲突：

```java
@Entity
public class Account {
    @Id private Long id;
    private BigDecimal balance;

    @Version
    private Long version;
}
```

```sql
UPDATE account SET balance = ?, version = version + 1 WHERE id = ? AND version = ?
```

冲突时 Hibernate 抛 `OptimisticLockException`，Spring 的异常转换把它译为 `OptimisticLockingFailureException` 家族（如 `ObjectOptimisticLockingFailureException`）。

适用：冲突概率低、重试成本低的场景。高频争抢（如秒杀库存）用乐观锁会导致大量重试失败，应改悲观锁或把扣减下沉到数据库原子操作（`UPDATE ... SET stock = stock - 1 WHERE stock > 0`）。

### Pessimistic Lock

在 Repository 方法上声明锁模式，Hibernate 会生成 `SELECT ... FOR UPDATE`：

```java
public interface AccountRepository extends JpaRepository<Account, Long> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from Account a where a.id = :id")
    Optional<Account> findByIdForUpdate(@Param("id") Long id);
}
```

配合超时 hint 控制等待行为（`0` 表示不等待，`-1` 表示无限等待）：

```java
@Lock(LockModeType.PESSIMISTIC_WRITE)
@QueryHints(@QueryHint(name = "jakarta.persistence.lock.timeout", value = "3000"))
Optional<Account> findByIdForUpdate(@Param("id") Long id);
```

悲观锁必须包在真实事务里才有效——脱离事务执行的 `@Lock` 不会开启数据库锁。

### Failure Retry

乐观锁冲突重试要**重新读一遍数据**再重算，不能拿旧对象直接再 `save`，否则只是重复提交同一个版本。可靠做法是用 Spring Retry 在新事务里整体重放：

```java
@Retryable(retryFor = OptimisticLockingFailureException.class, maxAttempts = 3,
           backoff = @Backoff(delay = 50, multiplier = 2))
@Transactional
public void transfer(...) { /* 重新读取 → 重新计算 → 更新 */ }
```

## Auditing

审计字段（创建/修改时间与操作人）不必手写，交给 `AuditingEntityListener`：

```java
@Configuration
@EnableJpaAuditing(auditorAwareRef = "auditorProvider")
class JpaAuditConfig {

    @Bean
    AuditorAware<String> auditorProvider() {
        return () -> Optional.ofNullable(SecurityContextHolder.getContext().getAuthentication())
                .map(Authentication::getName);
    }
}

@MappedSuperclass
@EntityListeners(AuditingEntityListener.class)
public abstract class Auditable {

    @CreatedDate
    private Instant createdAt;

    @LastModifiedDate
    private Instant updatedAt;

    @CreatedBy
    private String createdBy;

    @LastModifiedBy
    private String updatedBy;
}
```

`AuditorAware` 的返回类型必须与 `@CreatedBy` 字段类型一致；测试环境没有登录上下文时返回 `Optional.empty()` 即可，否则审计会连带失败。

## Log

```properties
logging.level.org.springframework.orm.jpa=DEBUG
logging.level.org.hibernate.SQL=DEBUG
logging.level.org.hibernate.orm.jdbc.bind=TRACE   # 打印绑定参数（Hibernate 6+ 的新 logger）
```

## Links

- [Spring](/docs/CS/Framework/Spring/Spring.md)
- [Spring Transaction](/docs/CS/Framework/Spring/Transaction.md)
- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)
- [Spring Boot](/docs/CS/Framework/Spring_Boot/Spring_Boot.md)
- [Spring Validation](/docs/CS/Framework/Spring/Validation.md)

## References

- [Spring Data JPA - Reference Documentation](https://docs.spring.io/spring-data/jpa/reference/jpa.html)
- [Hibernate ORM 7.0 Migration Guide](https://docs.hibernate.org/orm/7.0/migration-guide)
- [Hibernate 7 (and Hibernate Validator 9) - Hibernate Blog](http://blog.hibernate.org/2025/05/20/hibernate-orm-seven/)
- [Jakarta Persistence 3.2 Specification](https://jakarta.ee/specifications/persistence/3.2/)
- [Spring Framework - Data Access: JPA](https://docs.spring.io/spring-framework/reference/data-access/orm/jpa.html)
