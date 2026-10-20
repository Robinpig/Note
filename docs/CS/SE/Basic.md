## Introduction

这一页记的是软件工程的**基本认知**——它们大多不是"技术"，而是关于技术选择的判断框架：为什么没有银弹、为什么要先想清楚问题、为什么抽象会反噬、为什么测试只能证伪。这些判断决定了后面所有具体手段（缓存、限流、事务、重构）什么时候该用、什么时候是过度设计。工程流程与度量见 [Engineering](/docs/CS/SE/Engineering.md)，具体代码手段见 [Clean Code](/docs/CS/SE/Clean_Code.md)。

## Essential and Accidental Complexity

- **没有银弹**：Brooks 区分本质复杂度（业务本身的复杂性，无法消除）与偶然复杂度（工具、语言、环境带来的，可以被压缩）。任何"用 X 之后就不用设计系统了"的承诺都是在试图消灭本质复杂度。
- **测试可以证明 bug 存在，但不能证明 bug 不存在**（Dijkstra）：测试是采样，不是证明。因此测试的作用是降低不确定性，而不是给出正确性保证；真正需要保证的部分要靠类型、不变式与形式化方法。
- **编程的难点在于确定要解决什么问题，而不是怎么解决问题**：需求理解错了，实现得再优雅也是负资产。这也是为什么"先把问题写清楚"比"先写代码"更省时间。

## Abstraction and Simplicity

> 设计软件有两种方式：一种是简单到明显没有缺陷，另一种是复杂到没有明显缺陷。前者要难得多。 —— C. A. R. Hoare

抽象的代价常被低估：**抽象层次越高，表达能力越低，越难理解**。这一条在组织层面同样成立——中台越往上抽象一层，前台业务要用它就越别扭，见 [中台](/docs/CS/SE/中台.md)。判断抽象是否过度的标准是：它在多少次真实变化里被复用过，而不是它看起来有多通用。

## Functional Programming

函数式风格的核心约束是**无副作用**：

- 不抛出异常（用返回值表达失败，如 `Optional` / `Either` / `Result`）；
- 相同参数必然得到相同结果（引用透明，可缓存、可重放、可并行）；
- 不修改外部可见状态，状态变化显式地发生在边界上。

这些约束换来的是**可推理性**：一段没有副作用的代码可以单独理解、单独测试、安全地并发执行。代价是需要额外的结构来承载状态变化，见 [Programming](/docs/CS/SE/Programming.md)。

## Improving Code

代码不是写完就定型的，随需求演进持续整理是常态，手法见 [Refactoring](/docs/CS/SE/Refactoring.md)。

## Links

- [Engineering](/docs/CS/SE/Engineering.md)
- [Programming](/docs/CS/SE/Programming.md)
- [Clean Code](/docs/CS/SE/Clean_Code.md)
- [Refactoring](/docs/CS/SE/Refactoring.md)
- [中台](/docs/CS/SE/中台.md)

## References

1. [No Silver Bullet: Essence and Accidents of Software Engineering (TR86-020) — Fred Brooks](https://www.cs.unc.edu/techreports/86-020.pdf)
