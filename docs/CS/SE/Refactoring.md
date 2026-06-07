## Introduction

重构是一个在不创建新功能的前提下改进代码的系统性过程，可以将混乱转化为干净的代码和简单的设计。

复用的代码更难维护，改动的影响面更不易确定，对已有未知代码的改动更具不确定性。
重复代码的必要性。
请求参数和 DAO 的实体不会使用同一个对象，即使它们的内容基本一致。
过早优化是万恶之源。

编程的基本规则之一是，没有例程应该超过一页。
这是通过将程序分解为模块来实现的。每个模块是一个逻辑单元，完成特定工作。
通过调用其他模块来保持较小规模。模块化有几个优点：

- 首先，调试小程序比调试大程序容易得多。
- 其次，多人同时开发模块化程序更容易。
- 第三，编写良好的模块化程序将某些依赖项仅放在一个例程中，使更改更容易。

例如，如果需要以某种格式写入输出，有一个例程来完成这一点非常重要。
如果打印语句分散在整个程序中，修改将花费更长的时间。
全局变量和副作用不好的观念直接源于模块化好的观念。



## Bad Smells

- Mysterious Name
- Duplicated Code
- Long Function
- Long Parameter List
- Global Data
- Mutable Data
- Divergent Change
- Shotgun Surgery
- Feature Envy
- Data Clumps
- Primitive Obsession
- Repeated Switches
- Loops
- Lazy Element
- Speculative Generality
- Temporary Field
- Message Chains
- Middle Man
- Inside Trading
- Large Class
- Alternative Classes with Different Interfaces
- Data Classes
- Refused Bequest
- Comments



## References

1. [Refactoring Guru](https://refactoring.guru/refactoring)