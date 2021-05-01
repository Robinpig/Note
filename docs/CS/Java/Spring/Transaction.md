# Transaction



## @Transactional

不支持事务情况

- 方法不是public不支持事务

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



Propagation

TransactionDefinition

TransactionSynchronizationManager