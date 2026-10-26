# Parsing

## Introduction

语法分析（解析）接收词法分析产生的 token 流，按语言的上下文无关文法（CFG）验证其结构，并产出分析树/语法树。
它决定"一段字符序列是不是合法程序"，以及程序的语法形状——后续的语义分析完全依赖这棵树的形状。

本页的主线是两条互斥的技术路线：**自顶向下**（从开始符号推导出输入）与**自底向上**（从输入归约出开始符号），以及它们各自的适用边界。

## Context-Free Grammars

CFG 由四元组定义：终结符集合、非终结符集合、开始符号、产生式集合。
文法不仅是描述工具，还直接决定分析器的形态：

```
stmt   → if expr then stmt else stmt
       | if expr then stmt
       | while expr do stmt
       | id = expr
expr   → expr + term | term
term   → term * factor | factor
factor → ( expr ) | id | num
```

三个核心概念：

- **推导**：从开始符号反复替换非终结符，最左推导对应自顶向下分析顺序；
- **分析树 vs 语法树**：分析树记录完整推导（每个内部节点是一个非终结符）；语法树是压缩后的形式，内部节点是操作，叶子是操作数；
- **二义性**：一个句子存在两棵不同分析树。
  `if expr then stmt else stmt` 的悬挂 else 是经典二义，用"else 匹配最近的 if"的约定消解，等价于改写文法强制就近绑定。

二义性不可能一般性地判定，所以不存在"自动去二义"工具；二义文法只能靠人改写（如引入优先级/结合性产生式分层）。

## Top-Down Parsing

从开始符号出发，尝试推导出输入串。天然适合手写递归下降，但有两个硬约束。

### Backtracking and Predictive Parsing

朴素回溯（试探性展开产生式，失败就回退）指数级最坏。
预测分析器通过固定前瞻 token 决定用哪条产生式，免回溯——要求文法满足 **LL(1)**：对每个非终结符，各产生式的 **FIRST** 集合不相交；当产生式可能推出 ε 时，还需 **FOLLOW** 不相交。

FIRST/FOLLOW 的定义：

- `FIRST(α)`：α 能推导出的第一个终结符集合；
- `FOLLOW(A)`：可能紧跟在 A 后面的终结符集合。

预测分析表用 `(非终结符, 前瞻 token)` 二维索引直接给出动作，驱动栈与输入流同步消耗。
实际编译器（GCC 的 C 前端、Clang 的表达式解析）大量使用带回溯的递归下降，但只在歧义确实存在的局部小范围回溯。

### Recursive Descent

每个非终结符一个函数，产生式的每个符号对应一行代码：

```c
void expr(void) {
    term();
    while (tok == PLUS || tok == MINUS) {
        next();
        term();
    }
}
```

优点：错误信息质量高、可嵌入语义动作、可手动处理例外。
缺点：左递归文法（`expr → expr + term`）会无限递归，必须改写为右递归或迭代形式；改写要保留运算符优先级与结合性。

### LL(k) 的边界

LL(1) 表达力弱：不含左递归、FIRST/FOLLOW 不相交，把很多自然文法挡在门外。
LL(k)（任意 k）理论上更强但表格爆炸，实践中工具链极少使用。

## Bottom-Up Parsing

从输入串出发，反复把"与某产生式右侧匹配的符号串"归约为左侧非终结符，直到归约出开始符号。
每一步的决策对象是 **handle**（最左简单短语的子串）——找到正确的 handle 序列就等价于找到正确的分析树。

### Shift-Reduce

移进-归约框架：栈 + 输入，动作只有两种：

| 动作 | 含义 |
| :--- | :--- |
| shift | 输入前端 token 压栈 |
| reduce | 栈顶符号串匹配某产生式右侧，替换为左侧非终结符 |
| accept | 归约到开始符号且输入耗尽 |
| error | 无合法动作 |

冲突有两类：

- **移进-归约冲突**：如 `if expr then stmt` 后遇 `else`，该继续移进还是先归约内层 if——用"移进优先"消歧（就近匹配 else）；
- **归约-归约冲突**：栈顶可按多条产生式归约，通常意味着文法有真正的歧义。

### LR Family

LR 分析器用**有穷自动机 + 前瞻**同时描述"已扫描部分"与"可做的归约"：

| 变体 | 构造 | 状态数 | 冲突 |
| :--- | :--- | :--- | :--- |
| LR(0) | 仅项目集 | 最少 | 多 |
| SLR(1) | LR(0) + FOLLOW 集近似 | 少 | 中 |
| LALR(1) | 合并同心 LR(1) 状态 | 与 SLR 同级 | 少 |
| LR(1) | 完整前瞻一项 | 最多 | 最少 |

yacc / bison 默认产出 LALR(1)：状态数与 SLR 相当，能力接近 LR(1)，是工程最优平衡点。
LR(1) 的全尺寸表在实践中状态爆炸，仅在对冲突零容忍的语言（如 Ada）中值得。

### Error Recovery

语法错误的处理直接影响编译器可用性：

- **Panic mode**：跳过 token 直到遇到同步 token（`;`、`}`），简单但恢复粗糙；
- **Phrase-level recovery**：对剩余输入局部替换/插入/删除，易级联误报；
- **Error productions**：为常见错误写专门文法规则，错误信息质量最高；
- **异常机制**：GCC/Clang 解析器对模板等复杂结构回溯并重试。

错误恢复的真正目标不是"恢复解析"，而是**抑制级联报错**——一次错误产生一条信息，而不是几百条。

## Links

- [Compiler](/docs/CS/Compiler/Compiler.md)
- [Lexical Analysis](/docs/CS/Compiler/Lexical_Analysis.md)
- [Semantic Analysis](/docs/CS/Compiler/Semantic_Analysis.md)
- [Intermediate Representation](/docs/CS/Compiler/Intermediate_Representation.md)

## References

1. [GNU Bison Manual — Parsing](https://www.gnu.org/software/bison/manual/)
2. [LLVM Kaleidoscope Tutorial — Implementing a Parser and AST](https://llvm.org/docs/tutorial/MyFirstLanguageFrontend/LangImpl02.html)
