## Introduction

ReactiveX 结合了观察者模式、迭代器模式和函数式编程的最佳思想。

`java.util.Observable` 和 `java.util.Observer` 接口已被弃用。
Observer 和 Observable 支持的事件模型相当有限，Observable 传递通知的顺序未指定，状态变化与通知之间不是一一对应的。

- 对于更丰富的事件模型，请考虑使用 java.beans 包。
- 对于线程间可靠有序的消息传递，请考虑使用 java.util.concurrent 包中的并发数据结构。
- 对于响应式流风格编程，请参阅 java.util.concurrent.Flow API。

Flow

用于建立流控制组件的相关接口和静态方法，其中 Publisher 产生由 Subscription 管理的 Subscriber 消费的项目。

## References
1. [ReactiveX](http://reactivex.io/)