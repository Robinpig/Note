## Introduction

Refactoring is a systematic process of improving code without creating new functionality that can transform a mess into clean code and simple design.

复用的代码更难维护 改动的影响面更不易确定 对已有未知代码的改动更具不确定性
重复代码的必要性
请求参数和DAO的实体不会使用同一个对象 即使它们的内容基本一致
过早优化是万恶之源

One of the basic rules concerning programming is that no routine should ever exceed a page.
This is accomplished by breaking the program down into modules. Each module is a logical unit and does a specific job.
Its size is kept small by calling other modules. Modularity has several advantages.

- First, it is much easier to debug small routines than large routines.
- Second, it is easier for several people to work on a modular program simultaneously.
- Third, a well-written modular program places certain dependencies in only one routine, making changes easier.

For instance, if output needs to be written in a certain format, it is certainly important to have one routine to do this.
If printing statements are scattered throughout the program, it will take considerably longer to make modifications.
The idea that global variables and side effects are bad is directly attributable to the idea that modularity is good.



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