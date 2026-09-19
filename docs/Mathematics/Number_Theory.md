## Introduction

数论研究**整数及其性质**——整除、素数、同余。它曾被视为最「纯粹」、最无用的数学，直到公钥密码学把素数分解与离散对数变成国家安全的基石。

本笔记给出数论的 CS 视角；代数结构见 [代数](/docs/Mathematics/Algebra.md)，离散基础见 [离散数学](/docs/Mathematics/Discrete_Math.md)。趣味例题见 [斐波那契数列](/docs/Mathematics/Fibonacii.md) 与 [考拉兹猜想](/docs/Mathematics/Callatz%20conjecture.md)。

## 整除与同余

- **整除**：`a | b` 表示存在整数 k 使 b=ak。
- **同余**：$a\equiv b\pmod n$ 当 $n\mid(a-b)$。同余把整数按余数分组，构成**剩余类环**，是模运算的语言。
- **欧几里得算法**：辗转相除求最大公约数 $\gcd(a,b)$，是 RSA 密钥生成的底层操作。

## 素数与定理

- **素数**：恰有两个正因子的整数；算术基本定理说每个整数唯一分解为素数之积。
- **费马小定理**：$a^{p-1}\equiv1\pmod p$（p 为素数），用于素性测试与求逆。
- **欧拉定理**：$a^{\varphi(n)}\equiv1\pmod n$，费马是其特例，是 RSA 正确性的核心。

## 在 CS 中的落点

| 应用 | 用到的数论 |
| --- | --- |
| RSA | 大整数分解困难、欧拉定理 |
| Diffie-Hellman | 离散对数困难 |
| 椭圆曲线密码 ECC | 有限域上的椭圆曲线群 |
| 哈希与校验 | 模运算、素数 |
| 随机数 | 素数、原根 |

数论提供了「正向易、反向难」的单向函数——这正是密码学安全的数学来源，详见 [安全](/docs/CS/Security/Security.md)。

## 趣味例题

- [斐波那契数列](/docs/Mathematics/Fibonacii.md)：矩阵快速幂求 $F_n$ 与黄金比，是线性递推与 [线性代数](/docs/Mathematics/Linear_Algebra.md) 的漂亮接合。
- [考拉兹猜想](/docs/Mathematics/Callatz%20conjecture.md)：3n+1 迭代，至今未证，属迭代动力系统的未解之谜。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Algebra](/docs/Mathematics/Algebra.md)
- [Discrete Math](/docs/Mathematics/Discrete_Math.md)
- [Fibonacii](/docs/Mathematics/Fibonacii.md)
- [Callatz conjecture](/docs/Mathematics/Callatz%20conjecture.md)

## References

1. [Number Theory (Wikipedia)](https://en.wikipedia.org/wiki/Number_theory)
