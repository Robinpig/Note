## Introduction

设计模式不是语法糖，而是**面向对象范式下反复出现的结构问题及其经过验证的解法**。GoF 的 23 个模式按目的分三族：创建型回答"对象怎么造"（把 new 的权利交给谁），结构型回答"对象怎么拼"（类与对象的组合关系），行为型回答"对象怎么协作"（职责在对象间如何分配）。

本页按这条主线组织：先讲设计原则（SOLID 是模式背后的判据），再按三族过一遍每个模式——每个条目给出意图、一个真实场景与一个使用边界。其中八篇有独立分册深入，正文中以链接标注。

学习模式最大的误区是把 23 个模式当目录背。真正有效的读法是**认坏味道**：看到 if-else 堆叠想到策略，看到构造器参数爆炸想到建造者，看到"类数量翻倍"的继承树想到组合——模式是症状的处方，先认症状再开处方。

## Design Principles

SOLID 是五个类设计原则，模式几乎都可以追溯到其中一条或几条的应用。它们不是规则清单，而是判断"这段设计是否健康"的标尺。

### SOLID

| 原则 | 一句话 | 对应模式 |
|------|--------|---------|
| SRP 单一职责 | 一个类只有一个引起它变化的原因 | 装饰器、代理（每个关注点一层） |
| OCP 开闭 | 对扩展开放，对修改关闭 | 策略、模板方法、工厂方法 |
| LSP 里氏替换 | 子类必须能替换父类 | 所有基于抽象的模式的前提 |
| ISP 接口隔离 | 不强迫客户端依赖它不用的方法 | 适配器、门面 |
| DIP 依赖倒置 | 依赖抽象而非具体 | 工厂方法、依赖注入 |

### Single Responsibility Principle

#### Intent

A class should have only one reason to change.

**Isolation**

变化的原因超过一个，就把职责拆开。实践中比"一个类只做一件事"更可操作的判据是：**描述这个类的职责时是否出现了"和"字**——"管理用户信息和发送邮件"就是两个职责。

### Open-Close Principle

#### Intent

Software entities like classes, modules and functions should be **open for extension** but **closed for modifications**.

行为要扩展时新增代码而非改动旧代码。这是策略、工厂方法、装饰器共同的理论基础：把可变部分抽象成接口，新增一种实现即完成扩展。

### Liskov's Substitution Principle

#### Intent

Derived types must be completely substitutable for their base types.

This principle is just an extension of the Open Close Principle and it means that we must make sure that new derived classes are extending the base classes without changing their behavior.

违反的典型信号：子类覆写方法抛"不支持"的异常（如 `Arrays.asList` 返回的列表 `add` 抛 `UnsupportedOperationException`，这正是 List 契约被子类削弱的后果），或子类加强前置条件、削弱后置条件。里氏替换是抽象能否被信任的底线，也是多态的前提。

Law of Demeter

#### Intent

A unit should only talk to its immediate friends; don't reach through objects.

最少知识原则：`a.getB().getC().doSomething()` 这种"跟陌生人说话"的链式调用会把调用方与深层结构耦合，改一层结构全线报错。Builder 的链式 API 是这条原则的合法例外——链上每一环返回的都是 this，不触及陌生人的内部。

### Interface Segregation Principle

#### Intent

Clients should not be forced to depend upon interfaces that they don't use.

胖接口迫使实现类给不需要的方法写空桩，调用方也被迫了解无关方法。拆成多个小接口，客户端只依赖自己真正用的那部分。接口是给**调用方**用的契约，不是给实现方贴的标签——这是它最常被误解的地方。

If the design is already done fat interfaces can be segregated using the Adapter pattern.

### Dependency Inversion Principle

#### Intent

- High-level modules should not depend on low-level modules. Both should depend on abstractions.
- Abstractions should not depend on details. Details should depend on abstractions.

高层策略（订单流程）不应依赖底层细节（MySQL 驱动），双方都依赖抽象（DAO 接口）。工厂方法、抽象工厂、原型都是实现倒置的手段；现代容器（[IoC](/docs/CS/Framework/Spring/IoC.md)）把倒置推到极致——类只声明依赖，装配由容器完成。

## Creational Patterns

创建型的共同主题：**把"用哪个类、何时创建"的决定权从调用方转移出去**。直接 `new` 不是错，但当调用方需要知道实现细节才能构造时，变化就会沿调用链传染。

### Singleton

Ensure that only one instance of a class is created and provide a global point of access to it.

进程唯一资源的自然表达：线程池、连接池、配置客户端。五种写法的对比、双检锁为何必须 `volatile`、以及 Spring 的 singleton scope 与 GoF 单例的区别，见分册 [Singleton](/docs/CS/DesignPatterns/Singleton.md)。要记住的更重要的一条：**单例是可变全局状态**，能用容器托管就交给容器。

### Prototype

Specify the kinds of objects to create using a prototypical instance, and create new objects by copying this prototype.

创建成本高的对象（复杂配置、大图结构）用拷贝代替新建。Java 的坑在 `Cloneable`：它是个标记接口，`Object.clone()` 默认浅拷贝，引用字段不复制，忘记覆写就是隐蔽 bug；`clone` 方法还与构造器语义割裂。更安全的替代是拷贝构造器或静态工厂。protobuf 的 `Message.Builder` 把拷贝与修改合并成标准 API，是工程上的正确答案。

### Factory

Simple Factory 不在 GoF 23 之列，但它是工厂家族的起点：一个工厂类按参数返回不同产品，把 `if (type == A) new A()` 的决策集中到一处。产品种类继续增多、工厂本身开始频繁修改时，就该升级成工厂方法。

### Factory Method

Define an interface for creating an object, but let subclasses decide which class to instantiate.

工厂方法是创建型里最重要的一个，JDK 的 `Calendar.getInstance()`、JCA 的 `KeyFactory.getInstance()` 都是它的化身；Spring 的 `FactoryBean` 与依赖注入把"子类决定"翻转成"容器决定"。与抽象工厂的边界、以及注册表式工厂的现代写法，见分册 [Factory Method](/docs/CS/DesignPatterns/FactoryMethod.md)。

### Abstract Factory

Provide an interface for creating families of related or dependent objects without specifying their concrete classes.

工厂方法的"产品成组"升级版：一个工厂产出配套的一族产品（Windows 风格按钮+滚动条、MySQL 的 Connection+Statement 全家）。判据：产品之间必须**搭配使用**才有意义。现代用法常退化为"按配置选择一套实现"，此时一组 `@Configuration` 就是事实上的抽象工厂。

### Builder

Separate the construction of a complex object from its representation so that the same construction process can create different representations.

参数超过四五个、可选组合多、或对象必须不可变时，重叠构造器与 JavaBeans 设值都会失控：前者调用点不可读，后者允许非法中间态。Builder 把必填参数收进构造器、可选参数链式设值、`build()` 统一校验，产出 `final` 字段的不可变对象，详见分册 [Builder](/docs/CS/DesignPatterns/Builder.md)。

### Object Pool

Reuse expensive objects instead of creating and destroying them repeatedly.

连接、线程、大缓冲区这类"创建贵、销毁贵、可复用"的资源适合池化。核心难点全在**池的管理**而非获取：空闲回收、健康检查、借还峰值、池满策略（阻塞等待/快速失败/扩容）。Java 的答案见 [Druid](/docs/CS/Java/ConnectionPool/Druid.md) 与 [HiKariCP](/docs/CS/Java/ConnectionPool/HiKariCP.md)——连接池不是 Object Pool 的简单应用，而是它最复杂的工业形态。池与享元模式常被混淆：池借出后**独占**，享元**共享不可变**状态。

## Behavioral Patterns

行为型处理对象间的职责分配与通信，是日常代码里出现频率最高的一族——策略、观察者、责任链几乎在每个中层架构里都有投影。

### Memento

Without violating encapsulation, capture and externalize an object's internal state so that the object can be restored to this state later.

把对象状态存成快照以便回滚：编辑器撤销栈、事务回滚、游戏存档。成本在**快照体积**——全量拷贝大对象不可行，工业实现是增量快照（Git 的对象存储即是其思想化身）或命令日志反向重放（见 Command）。快照会破坏封装是常见误读：状态放在独立的 Memento 对象里，原对象只提供 create/restore 两个方法。

### Mediator

Define an object that encapsulates how a set of objects interact. Mediator promotes loose coupling by keeping objects from referring to each other explicitly, and it lets you vary their interaction independently.

同事对象两两通信会变成 N² 条连线；引入中介者后每个对象只认识它。聊天室、机场塔台调度是经典比喻，分布式语境下**注册中心就是中介者**——服务提供者与消费者互不知晓，只与注册中心对话，见 [Consul](/docs/CS/Framework/Spring_Cloud/Consul.md)。与观察者的区别：中介者关心**谁转发、怎么协调**，观察者只做**一对多通知**。

### Observer

Define a one-to-many dependency between objects so that when one object changes state, all its dependents are notified and updated automatically.

事件发生后通知多方而不惊动发布方：缓存失效、消息推送、UI 刷新。进程内的标准形态是 Spring 的 `@EventListener`，跨进程则下沉到消息队列——两者的可靠性、事务、范围边界，见分册 [Observer](/docs/CS/DesignPatterns/Observer.md)。

### Null Object

Provide an object as a surrogate for the lack of an object, with the same interface, that does nothing.

用"什么都不做"的对象代替 `null`，消灭满屏的空值检查：空日志器、空权限策略、DAO 返回空集合而非 null。它让多态吞掉特例，客户端零分支；代价是空对象可能把"无数据"与"零数据"混为一谈，需要时可返回 `Optional` 显式表达缺失。

### Visitor

Represent an operation to be performed on the elements of an object structure. Visitor lets you define a new operation without changing the classes of the elements on which it operates.

对象结构稳定（AST、SQL 语法树、报表节点）但操作频繁新增时，把操作抽成 Visitor，避免每个节点类堆满方法。它依赖**双分派**——`node.accept(visitor)` 再由 `visitor.visit(node)`，运行时才能确定组合。现代观点：能用函数式遍历 + lambda 解决就别上 Visitor，双分派对不熟悉的人可读性很差。

### Interpreter

Given a language, define a representation for its grammar along with an interpreter that uses the representation to interpret sentences in the language.

每个语法规则一个类，组合成表达式树后递归求值：正则引擎、规则引擎、Spring 的 SpEL、配置中心的表达式过滤都属此类。只适合**语法简单且不常变**的场景——语法复杂时请直接使用 ANTLR 生成的解析器，手写解释器类会失控。

### Iterator

Provide a way to access the elements of an aggregate object sequentially without exposing its underlying representation.

遍历与容器实现解耦：客户端面向 `Iterator` 编程，背后可以是数组、链表、数据库游标、网络流。Java 的 for-each 即它的语法糖。经典事故是**并发修改**：遍历中直接改集合会触发 `ConcurrentModificationException`（fail-fast），正确做法是 `iterator.remove()` 或复制后遍历。

### Strategy

Define a family of algorithms, encapsulate each one, and make them interchangeable.

一族可互换算法 + 运行时按需选择：支付方式、折扣规则、负载均衡策略。Spring 的惯用法是注入 `Map<String, Strategy>` 按 bean 名路由，新增算法只加一个 `@Component`。与 if-else 的取舍、与状态模式/模板方法的边界，见分册 [Strategy](/docs/CS/DesignPatterns/StrategyPattern.md)。

### Command

Encapsulate a request as an object, thereby letting you parameterize clients with different requests, queue or log requests, and support undoable operations.

把一次操作封装成对象，于是它可以被**传递、排队、记录、撤销、重试**——线程池里的 `Runnable`、MQ 里的消息、前端弹窗的确认动作都是命令。它是可撤销操作（编辑器 undo/redo 栈）与事务脚本建模的标准答案，也是 [MQ](/docs/CS/MQ/MQ.md) "消息即命令"思想在单进程内的投影。与策略的区别：命令封装的是"要做的动作"，策略封装的是"做事的算法"。

### Template Method

Define the skeleton of an algorithm in an operation, deferring some steps to subclasses.

流程固定、个别步骤可变的场景：AQS 的 `acquire` 骨架 + 子类 `tryAcquire`、Servlet 的 `service` + `doGet`、`JdbcTemplate` 的异常翻译与资源管理。它是继承体系里复用代码的主力，也是"抽象类持有不变量、钩子方法收敛可变点"的范本，详见分册 [Template Method](/docs/CS/DesignPatterns/TemplateMethod.md)。

### Chain of Responsibility

Avoid coupling the sender of a request to its receiver by giving more than one object a chance to handle the request.

请求沿链传递直到某节点处理：日志 → 鉴权 → 限流 → 业务，顺序即语义。Servlet Filter、Spring Security、Netty Pipeline、Dubbo Filter、OkHttp Interceptor 的全部扩展点都是责任链，详见分册 [Chain of Responsibility](/docs/CS/DesignPatterns/ChainOfResponsibility.md)。

## Structural Patterns

结构型关注类与对象的组合方式，回答"已有零件怎么拼出更大的结构且不爆炸"。

### Adapter

Convert the interface of a class into another interface clients expect.

接口不兼容但都改不动时，在边界上包一层转接：`InputStreamReader`（字节→字符）、Spring MVC 的 `HandlerAdapter`（统一调度多种 handler）、Retrofit/Feign（接口声明 → HTTP 调用）。与门面的区别：适配器**改变**接口，门面**简化**接口，见分册 [Adapter](/docs/CS/DesignPatterns/Adapter.md)。

### Proxy

Provide a surrogate or placeholder for another object to control access to it.

客户端面向同一接口编程，请求先经过代理：远程代理（RPC stub）、虚拟代理（懒加载）、保护代理（权限）、智能引用（缓存/事务）。JDK 动态代理与 CGLIB 是 Spring AOP 的机制基础，同类自调用失效等陷阱见分册 [Proxy](/docs/CS/DesignPatterns/ProxyPattern.md)。

### Composite

Compose objects into tree structures to represent part-whole hierarchies. Composite lets clients treat individual objects and compositions uniformly.

树形部分-整体结构：文件系统、组织架构、AST、菜单。客户端对叶子与容器一视同仁——`File` 与 `Directory` 同接口，递归遍历天然统一。代价是设计过于一般化（"万物皆 Component"）时类型系统会变模糊，需要区分叶子能力时不如 Visitor 明确。

### Decorator

Attach additional responsibilities to an object dynamically.

组合代替继承来叠加功能：JDK IO 的 `new BufferedInputStream(new FileInputStream(f))`、`HttpServletRequestWrapper`、Netty 的 handler 分层。与代理同形同意不同：装饰器**层层叠加增强**，代理**控制访问**，判据是这层壳由谁组装、为何存在，见分册 [Decorator](/docs/CS/DesignPatterns/Decorator.md)。

### Flyweight

Use sharing to support large numbers of fine-grained objects efficiently.

大量细粒度对象的重复状态被抽成共享的不可变部分，各自只存上下文：`String` 常量池、`Integer` 缓存、棋盘棋子的颜色/形状共享、protobuf 对重复字段的内存优化。判据是对象数极大、状态可分类、且共享部分不可变。与对象池的区别：享元是**共享**（只读），池是**借还**（独占使用）。

### Bridge

Decouple an abstraction from its implementation so that the two can vary independently.

把抽象与实现拆成两条继承线，用组合连接，避免"抽象 × 实现"的类数乘法：JDBC 的 `DriverManager`（抽象）与各数据库 `Driver`（实现）、SLF4J 的 `Logger` 接口与 logback/log4j2 绑定、UI 的窗口抽象与平台渲染实现。它是"优先组合而非继承"原则的范本——当两个维度都在扩展时，单继承树必然爆炸。

## Links

- [Singleton](/docs/CS/DesignPatterns/Singleton.md)
- [Factory Method](/docs/CS/DesignPatterns/FactoryMethod.md)
- [Builder](/docs/CS/DesignPatterns/Builder.md)
- [Template Method](/docs/CS/DesignPatterns/TemplateMethod.md)
- [Chain of Responsibility](/docs/CS/DesignPatterns/ChainOfResponsibility.md)
- [Decorator](/docs/CS/DesignPatterns/Decorator.md)

## References

1. [OODesign - Design Patterns](https://www.oodesign.com)
2. [Refactoring.Guru - Design Patterns](https://refactoring.guru/design-patterns)
3. [Effective Java (3rd Edition)](https://www.informit.com/store/effective-java-9780134685991)
