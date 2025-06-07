## Introduction

软件质量，不但依赖于架构及项目管理，而且与代码质量紧密相关
代码质量与其整洁度成正比。干净的代码，既在质量上较为可靠，也为后期维护、升级奠定了良好基础

我们常用 优雅 形容一个好的代码

好的代码应该具备哪些特质

- 干脆利落的抽象 代码应尽量专注做一件事
- 有意义的命名
- 易于阅读 在字面上能表达其含义
-
- 几乎没有改进的余地

实现好的代码的代价

- 需要时刻维护 每次修改时都需要保持比之前更整洁 而不是破窗效应 最后陷入泥沼
-

## Implementation

如何实现

命名

变量、函数或类的名称应该已经答复了所有的大问题。它该告诉你，它为什么会存在，它做什么事，应该怎么用。如果名称需要注释来补充，那就不算是名副其实。

类名和对象名应该是名词或名词短语，如Customer、WikiPage、Account和AddressParser。
避免使用Manager、Processor、Data或Info这样的类名。类名不应当是动词

但在实际的编码中 很多情况下不得不将一些行为和抽象放到Processor 和 Manager中 如 Netty的Processor 业务编码中service层和Manager层

方法名应当是动词或动词短语





## Links

- [SE](/docs/CS/SE/Basic.md)

## References

1. [Clean Code]()
2. [Working Effectively with Legacy Code]()
