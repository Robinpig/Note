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

## Functions and Comments

- **函数只做一件事**：判断标准是能否再拆出一个有意义的子函数；合理的结果是函数变短、调用层级变平，副作用被挤到边界上。
- **参数越少越好**：零参最好，单参次之；布尔标志参数往往说明这个函数其实同时做了两件事。
- **注释只写"代码讲不出来的那部分"**：为什么这么写、为什么不能那样写、外部约束来自哪里。复述代码的注释会先于代码失效，最终变成错误的说明；能用命名与类型表达的就别写注释。

## Error Handling and Boundaries

- 用异常表达非预期的失败路径，而不是返回魔法值（`null` / `-1`），并带上足以定位的上下文。
- **别返回 null，也别传 null**：集合用空集合而非 `null`，避免调用方层层判空。
- 错误处理与正常逻辑分离（`try` 块内尽量只有一行调用），否则主流程会被淹没。
- 第三方边界要用适配层隔离：包装掉不友好的 API，用少量冒烟测试把外部行为钉住，避免上游升级波及整个代码库。





## Links

- [Basic](/docs/CS/SE/Basic.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)
- [Programming](/docs/CS/SE/Programming.md)
- [Engineering](/docs/CS/SE/Engineering.md)
- [Bug](/docs/CS/SE/Bug.md)
- [Test](/docs/CS/SE/Test.md)

## References

1. 《Clean Code》— Robert C. Martin
2. 《Working Effectively with Legacy Code》— Michael Feathers
