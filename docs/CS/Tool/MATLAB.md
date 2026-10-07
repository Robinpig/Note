## Introduction

MATLAB（Matrix Laboratory）是 MathWorks 推出的**数值计算与科学工程语言/环境**，以「一切皆矩阵」为核心设计：标量是 1×1 矩阵，字符串是字符数组，连标量运算底层也走向量化路径。它在高校教学和工程界（信号处理、控制、通信、图像处理、仿真）长期占据主导地位，配套的 **Simulink** 提供基于框图的系统级建模仿真，是汽车/航空航天嵌入式开发的事实标准工具。

## Language Features

- **解释执行 + REPL**：命令行即时求值，适合探索式计算；`.m` 文件可写脚本与函数。
- **数组优先（向量化）**：用整段矩阵运算代替 `for` 循环——既更贴合数学表达，又把循环下沉到优化过的底层（历史上是 FORTRAN/C 库），性能远优于显式 M 代码循环。

```matlab
A = [1 2; 3 4];
b = [5; 6];
x = A \ b;          % 解线性方程组 Ax=b，反斜杠按矩阵类型自动选算法
[U,S,V] = svd(A);   % 奇异值分解，矩阵分解直接对应线代概念
```

- **索引从 1 开始**，支持强大的切片与逻辑索引：`A(A > 0)`、`A(:, 2)`。
- **动态类型**，变量无需声明；支持元胞数组 `{}`、结构体 `struct`、句柄类（OOP）。
- **绘图一等公民**：`plot`/`surf`/`imagesc` 快速出图，适合论文插图与可视化。

## Typical Toolbox

| 工具箱 | 领域 |
| --- | --- |
| Signal Processing / Communications | 滤波、FFT、调制解调 |
| Control System | 传递函数、状态空间、Bode 图、PID 整定 |
| Image / Computer Vision | 图像滤波、特征、深度学习 |
| Statistics & ML / Deep Learning | 统计、分类、网络训练 |
| Parallel Computing | parfor、GPU、集群 |
| Simulink + Embedded Coder | 框图仿真并自动生成 C 代码上硬件 |

## Comparison with Python Scientific Stack

| 维度 | MATLAB | Python（NumPy/SciPy） |
| --- | --- | --- |
| 成本 | 商业 License，昂贵 | 开源免费 |
| 数组运算 | 原生矩阵语义 | NumPy ndarray（默认逐元素，`@` 才是矩阵乘） |
| IDE/绘图 | 开箱即用、调试与 profiling 完善 | Jupyter / VS Code + Matplotlib |
| 工程生态 | Simulink、工具箱、代码生成、厂商支持强 | 生态更广（Web、工程化、深度学习框架） |
| 教学与论文 | 数学表达最直接 | 复现性与协作更友好 |

工程界趋势是原型/教学用 MATLAB，产品化、大规模与协作场景迁移到 Python；二者语法概念高度对应（矩阵、向量化、分解），迁移成本主要在索引习惯与函数命名。

## Links

- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md) — MATLAB 矩阵运算背后的数学
- [Calculus](/docs/Mathematics/Calculus.md) — 数值微分/积分、信号处理的数学基础
- [ffmpeg](/docs/CS/Tool/ffmpeg.md) — 同为工程信号/媒体处理工具
- [Vim](/docs/CS/Tool/Vim.md) / [gzip](/docs/CS/Tool/gzip.md) — 本目录其他通用工具

## References

- [MathWorks 官方文档](https://ww2.mathworks.cn/help/matlab/)
