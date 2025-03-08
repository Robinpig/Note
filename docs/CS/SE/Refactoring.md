## Introduction

Refactoring is a systematic process of improving code without creating new functionality that can transform a mess into clean code and simple design.

复用的代码更难维护 改动的影响面更不易确定 对已有未知代码的改动更具不确定性
重复代码的必要性
请求参数和DAO的实体不会使用同一个对象 即使它们的内容基本一致
过早优化是万恶之源



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