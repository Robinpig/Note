## Introduction

**数论**（number theory）是研究整数性质的分支。在算法域里它的地位特殊：它既是一切「离散数学味」问题的基础（整除、同余、质数），又因为**大量数论问题存在「暴力不可行、但存在精巧的筛法与分解法」**的结构，而成为算法竞赛与密码学中最密集的技巧来源之一。

它与本库其他部分的接口清晰：欧几里得算法见 [Algorithms](/docs/CS/Algorithms/Algorithms.md) 入口，$P \neq NP$ 的理论背景见 [NP](/docs/CS/Algorithms/NP.md)，模运算的密码学应用见 [Security](/docs/CS/Security/Security.md)，而「递归求解递推式」在 [Recursion](/docs/CS/Algorithms/Recursion.md) 的斐波那契一节有呼应。

本页聚焦算法视角的数论：**如何不枚举到 $n$ 就回答关于 $1 \sim n$ 的问题**。

## Divisibility and GCD
**欧几里得算法**（辗转相除法）是求 $\gcd(a,b)$ 的经典方法，也是史上第一个被记录的算法（见 [Algorithms](/docs/CS/Algorithms/Algorithms.md) 入口的历史一节）。其递推形式是 $\gcd(a,b) = \gcd(b, a \bmod b)$，直到 $b=0$ 为止，复杂度 $O(\log \min(a,b))$。

```java
long gcd(long a, long b) {
    while (b != 0) {
        long t = a % b;
        a = b;
        b = t;
    }
    return a;
}
```

**扩展欧几里得**在此基础上反解出贝祖系数 $x,y$ 使 $ax+by=\gcd(a,b)$，是解**线性同余方程** $ax \equiv c \pmod m$ 的基础（前提是 $\gcd(a,m) \mid c$）。

## Primes and Sieves
判断单个数 $n$ 是否为素数可以试除到 $\sqrt n$，复杂度 $O(\sqrt n)$。但若要回答「$1 \sim n$ 中每个数是不是素数」，逐个试除是 $O(n\sqrt n)$，而**筛法**能一次搞定。

### Sieve of Eratosthenes
从 2 开始，把所有未标记的数的倍数标记为合数；遇到已标记则跳过。关键优化是**从 $i^2$ 开始标记**（更小的倍数已被更小的质数筛过），复杂度 $O(n\log\log n)$，空间 $O(n)$。

```java
boolean[] sieve(int n) {
    boolean[] isPrime = new boolean[n + 1];
    Arrays.fill(isPrime, true);
    isPrime[0] = isPrime[1] = false;
    for (int i = 2; (long) i * i <= n; i++) {
        if (isPrime[i]) {
            for (long j = (long) i * i; j <= n; j += i)
                isPrime[(int) j] = false;
        }
    }
    return isPrime;
}
```

### Linear (Euler) Sieve
埃氏筛对每个合数会重复标记（如 6 被 2、3 各筛一次）。线性筛保证**每个合数只被它的最小质因子筛一次**，因此总复杂度是线性的 $O(n)$：按 $i$ 递增遍历，遍历其质因子 $p$，令 $i \cdot p$ 被 $p$ 筛去，并**当且仅当 $p$ 是 $i$ 的最小质因子时 break**。这个 break 正是线性复杂度的来源，也使它适合顺带求出每个数的最小质因子与欧拉函数值。

工程含义：$n$ 到 $10^7 \sim 10^8$ 量级时，线性筛明显快于埃氏筛，且只需保存一次结果，适合多次查询「某数是否为素数」。

## Binary Exponentiation
要计算 $a^n \bmod m$，逐次相乘是 $O(n)$，而用**二进制拆位**可降到 $O(\log n)$：维护结果 `res = 1`，循环中若 $n$ 的最低位为 1 则 `res = res * a`，然后 `a = a * a`、`n >>= 1`。

```java
long modPow(long a, long n, long m) {
    long res = 1 % m;
    a %= m;
    while (n > 0) {
        if (n & 1) res = res * a % m;
        a = a * a % m;
        n >>= 1;
    }
    return res;
}
```

**扩展快速幂**进一步支持「求 $a^x \bmod m$ 且 $x$ 极大（如 $10^{10^6}$）」：把指数 $x$ 的十进制表示按矩阵分解，或直接按数位递推 $a^{10} = (a^{x \bmod 9}\cdots)^{10} \cdot a^{\lfloor x/10\rfloor}$，复杂度降到 $O(\text{位数})$。这是大数取模题的核心技巧。

## Modular Arithmetic and Inverse
$(a + b) \bmod m = (a \bmod m + b \bmod m) \bmod m$ 与 $(a \times b) \bmod m$ 都可逐步取模，但**除法不能**。因此「模意义下的除法」需要**乘法逆元**：

> $a$ 在模 $m$ 意义下可逆 $\iff \gcd(a,m)=1$。此时存在 $a^{-1}$ 使 $a \cdot a^{-1} \equiv 1 \pmod m$，于是 $a/b \bmod m = a \cdot b^{-1} \bmod m$。

求法有两种：当 $m$ 为质数时用**费马小定理** $a^{-1} \equiv a^{m-2} \pmod m$（配合快速幂）；任意 $m$ 时用**扩展欧几里得**。

这条性质是许多「除法」型计数题的关键——例如「求方案数模 $10^9+7$」时，组合数里的除法必须换成逆元，否则结果错误。**前提是模数是质数**，这是最常见的踩坑点。

## Euler's Totient Function and Theorem
**欧拉函数** $\varphi(n)$ 是 $1 \sim n$ 中与 $n$ 互质的整数个数，计算式为 $\varphi(n) = n \prod_{p \mid n} (1 - \tfrac{1}{p})$，其中乘积遍历 $n$ 的所有不同质因子。它与线性筛配合可 $O(n)$ 求出 $1 \sim n$ 全部 $\varphi$ 值。

**欧拉定理**：$\gcd(a,m)=1$ 时 $a^{\varphi(m)} \equiv 1 \pmod m$。它把「求 $a^k \bmod m$」的指数从 $k$ 缩小到 $k \bmod \varphi(m)$，在大指数问题里与扩展快速幂互补。

## Binomial Coefficients
从 $n$ 个元素中选 $k$ 个：$C(n,k) = \binom{n}{k}$，递推 $C(n,k) = C(n-1,k) + C(n-1,k-1)$ 即帕斯卡三角（本身也是一道经典 DP）。

当 $n$ 很大、$k$ 很小时，逐个算会超时，需**预处理阶乘与逆阶乘**：$C(n,k) = \text{fac}[n] \cdot \text{ifac}[k] \cdot \text{ifac}[n-k] \bmod m$，预处理 $O(n)$、每次查询 $O(1)$。这是所有组合计数题目的通用基础设施。

相关恒等式在竞赛中高频出现：$C(n,k) \cdot k = n \cdot C(n-1,k-1)$（选人再选代表）、$C(n,k) = \sum_i C(k,i)C(n-k,k-i)$（按子集大小分拆）等。

## Integer Factorization
试除法分解 $n$ 是 $O(\sqrt n)$，对 $10^{18}$ 量级完全失效。

**Pollard–Rho** 是解决大数分解的实用算法：随机选取递推式 $f(x) = x^2 + c \pmod n$，像 Floyd 判环那样用「快慢指针」找循环节，再对每个因子 $d = \gcd(|x-y|, n)$ 尝试提取因子；失败就换随机参数重试。它**没有确定性复杂度保证**，但实践上对 64 位整数分解非常快（通常在 $O(n^{1/4})$ 量级），是竞赛与 CTF 分解 64 位整数的标准解法。

## Chinese Remainder Theorem
当若干模数**两两互质**时，同余方程组 $x \equiv a_i \pmod{m_i}$ 有解，且解在 $\prod m_i$ 意义下唯一：

$$
x = \sum_i a_i \cdot M_i \cdot (M_i^{-1} \bmod m_i), \qquad M_i = \prod_{j \ne i} m_j
$$

存在性与唯一性由 $\gcd$ 条件保证。「两两互质」是前提——模数不互质时需先用**扩展 CRT** 逐个合并（求解 $x \equiv a \pmod m$ 与 $x \equiv b \pmod n$ 的推广）。

现实对应是「时间/日期的模运算周期」：比如「一个数被 3、5、7 同时整除的最小值」正是求 $\text{lcm}(3,5,7)$，可用 CRT 思想理解为解 $x \equiv 0 \pmod{105}$。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [NP](/docs/CS/Algorithms/NP.md)
- [Recursion](/docs/CS/Algorithms/Recursion.md)
- [bit operations](/docs/CS/Algorithms/Bits.md)

## References

1. [快速幂 - OI Wiki](https://oi-wiki.org/math/number-theory/quick-pow/)
2. [素数 - OI Wiki](https://oi-wiki.org/math/number-theory/prime/)
3. [欧拉函数 - OI Wiki](https://oi-wiki.org/math/number-theory/euler-totient/)
4. [组合数学 - OI Wiki](https://oi-wiki.org/math/combinatorics/basic/)
5. [Pollard's rho algorithm - Wikipedia](https://en.wikipedia.org/wiki/Pollard%27s_rho_algorithm)
6. [Chinese remainder theorem - Wikipedia](https://en.wikipedia.org/wiki/Chinese_remainder_theorem)