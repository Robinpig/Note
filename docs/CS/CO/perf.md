## Introduction

如果说[数据表示](/docs/CS/CO/datarep.md)、[指令系统](/docs/CS/CO/isa.md)回答"程序怎么变成指令"，那么性能评价回答的是另一个更根本的问题——**这台机器到底有多快，瓶颈在哪，改了会不会变快**。它是组成原理的度量衡：没有 CPU 时间公式与 Amdahl 定律，流水线、缓存、乱序执行的每一项设计都只是定性描述；没有功耗模型，就无法解释"频率多年不涨、核数一路暴涨"的产业拐点。本页把这把尺子造出来：时间模型、基准测试、功耗与能效，最后落到现代 CPU 的电源管理机制。

## 响应时间与吞吐率

两个经常被混为一谈的指标：

- **响应时间 / 延迟（latency）**：完成单个任务花的时间，交互式应用（桌面、数据库单条查询）的核心体验；
- **吞吐率（throughput）**：单位时间完成的任务数，服务器/批处理（Web 集群、渲染农场）的追求。

两者可能反向：提高频率改善延迟；增加核数主要改善吞吐，甚至因共享资源争用让单任务变慢。**说"性能提升 1.5×"时必须指明是哪个指标**，这是所有性能报告的第一条军规。

## CPU 时间公式

一个程序在 CPU 上花费的时间可以精确分解为三个因子的乘积：

$$\text{CPU time} = \text{IC} \times \text{CPI} \times T_{cc}$$

- **IC（Instruction Count）**：指令条数，由程序、编译器与 ISA 决定；
- **CPI（Cycles Per Instruction）**：平均每条指令占的时钟周期数，由微架构决定——[流水线](/docs/CS/CO/pipeline.md)停顿、[缓存](/docs/CS/CO/Cache.md)缺失、分支误预测全计入这里；
- $T_{cc}$：时钟周期，由工艺与电路决定。

三个因子分别对应软硬件栈的三层，也意味着三条独立的优化路线，而它们常常互相牵扯：

| 优化手段 | 动的因子 | 副作用 |
|----------|----------|--------|
| 换更好的编译器 / 算法 | IC ↓ | 可能引入更复杂的指令（CPI ↑） |
| 加缓存、深流水、宽发射 | CPI ↓ | 时钟频率可能下降（$T_{cc}$ ↑） |
| 先进制程、更高电压 | $T_{cc}$ ↓ | 功耗与成本飙升 |

单看主频（GHz）因此毫无意义：它只覆盖三项中的一项，其余两项翻车时主频再高也白搭。

### CPI 的分解

实际 CPI 是各停顿项的叠加：

$$\text{CPI} = \text{CPI}_{ideal} + \text{stall}_{cache} + \text{stall}_{branch} + \text{stall}_{depend}$$

教科书式的"完美流水 CPI = 1"只存在于[流水线](/docs/CS/CO/pipeline.md)的理想模型里。真实核心理想 CPI 早已小于 1（超标量，每周刊发射多条），但缓存缺失与依赖停顿把实际值又拉回去——这就是为什么现代 CPU 把[非阻塞缓存](/docs/CS/CO/Cache.md)、[乱序执行](/docs/CS/CO/datapath.md)当作头等大事：它们都是在跟 CPI 公式里的停顿项搏斗。

## Amdahl 定律

1967 年 Gene Amdahl 给出的一条冷酷算术：**系统中某部件所能带来的整体加速比，受限于它占总执行时间的比例**。若优化前总时间为 1，可被加速部分占比 $f$，该部分加速 $k$ 倍，则整体加速比

$$S = \frac{1}{(1-f) + f/k}$$

最著名的特例：$k \to \infty$（该部分快到不要钱）时 $S \le \dfrac{1}{1-f}$——**加速比的天花板由不可加速部分决定**。加速 10 倍只覆盖 50% 时间的优化，整体最多 2 倍；而"优化掉 90% 的时间"听起来不如"加速 10 倍"，实际却是 10 倍。

这一定律是计算机系统设计的"第一过滤器"：

- 多核化的价值：若程序并行部分只占 70%，核数从 1 加到 16 的整体加速上限也只有 $1/(0.3+0.7/16) \approx 3.1$ 倍——**并行化之前先算 Amdahl**；
- 与"局部性原理"并称：前者告诉你优化哪里最值，后者告诉你优化什么能命中。

## 基准测试：SPEC

个人判断快慢不可信，产业界靠标准化基准程序。**SPEC（Standard Performance Evaluation Corporation，1988 年成立）**是最权威的中立组织，其 CPU 套件是处理器采购的通用语言：

- **SPEC CPU**：整数（SPECint）与浮点（SPECfp）两大类，每类再分 **speed**（单任务延迟）与 **rate**（多拷贝吞吐）两种跑法；
- **SPECratio**：被测机运行时间取倒数再对参考机归一，最后以**几何平均**汇总——几何平均保证任何单项都不能绑架总分；
- **base / peak 两档**：base 强制统一编译选项防厂商特调，peak 允许调优，两者必须同时报告；
- 版本沿革：CPU 92 → 95 → 2000 → 2006 → **2017**（2017-06 发布，长期主流，含 ML 推理类负载）→ **SPEC CPU 2026**（2026 年发布的新一代套件，扩大负载覆盖并加强内存子系统考察）。RISC-V 平台自 CPU 2017 V1.1.9（2022-12）起获得有限支持。

基准测试的固有局限也要心里有数：SPECratio 是合成分，真实负载（数据库事务、AI 推理）的瓶颈结构与之不同；厂商总有办法在规则边缘试探。**基准分用来筛选项，不用来下结论**。

## 功耗：被遗忘的第四维度

1990 年代前，性能几乎只由频率代表。倒转发生在两个先后到来的物理事实：

### 动态功耗与 Dennold 缩放

 CMOS 电路开关一次的动态功耗

$$P_{dynamic} = \alpha C V^2 f$$

$\alpha$ 是翻转活动因子，$C$ 是电容，$V$ 电压，$f$ 频率。1974 年 Robert Dennard 提出的缩放定律指出：晶体管尺寸每代缩小，电压电流同步等比下降，**功耗密度保持不变**——芯片可以靠堆晶体管变强而不增加功耗预算。这个"免费午餐"延续了三十年，在 **2005 年前后失效**：漏电流不再随尺寸缩小而等比下降，电压已逼近阈值无法再降。

后果是直接的：**功耗墙（power wall）**。频率每提高一档，功耗按 $V^2 f$ 二次方增长，而散热（风冷约 100–200 W）和供电是硬上限。标志性事件是 Intel 在 2004 年取消 4 GHz 的 Pentium 4 后续项目——不是做不出来，是热散去不了。

### 静态功耗与暗硅

与开关无关，晶体管始终存在的漏电流功耗 $P_{static} = V \cdot I_{leak}$ 在先进制程里占比越来越高，关掉的晶体管也在耗电。其极端后果是**暗硅（dark silicon）**：晶体管的数量早已够多，但功耗预算不允许它们同时工作——芯片上相当一部分面积必须长期断电。暗硅直接催生了两个产业方向：**异构专用单元**（GPU、NPU、媒体编解码器平时休眠，需要时唤醒，见 [SIMD 与加速器](/docs/CS/CO/simd.md)）与**大小核**（大核冲高频、小核干杂活）。

### 能效：真正的货币

于是评价指标从"每秒能做多少事"变成**每瓦能做多少事**：

$$\text{Energy} = P \times t, \qquad \text{能效} = \frac{\text{performance}}{\text{power}}$$

一个微妙但重要的事实：**降低频率并不线性降低能耗**——电压随频率一起降（DVFS）才省电，且任务拖长后静态功耗照常计费；反之"快速跑完然后深度睡眠"（race to halt）常常反而更省。这也是数据中心 PUE、笔记本续航、手机温升共同的底层逻辑。

## 电源管理：DVFS 与 C/P 状态

现代 CPU 把功耗控制做成了硬件机制族，操作系统通过固件表（ACPI）驱动：

- **P-states（性能状态）**：不同的频率/电压组合点，即 **DVFS**（动态电压频率调整）——降频必须同步降压，否则违背 $CV^2f$ 的缩放逻辑；
- **C-states（空闲状态）**：核空闲时逐级关闭时钟、再清空流水、最后断电缓存，越深的 C 态退出延迟越长；
- **T-states**：节流占空比，作为过热时的最后手段；
- **uncore / 内存频率**也独立参与调节，内存带宽敏感型负载常出现"核在降频、内存在全速"的组合。

Linux 侧的对应实现（cpufreq/governor、intel_pstate、cpuidle）见 [Linux 电源管理](/docs/CS/OS/Linux/PM/cpufreq.md)。软件能干预的其实只有策略：交互式负载选 performance governor，批处理选 powersave，容器化环境则要小心邻居噪声。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [缓存层次](/docs/CS/CO/Cache.md)
- [SIMD / GPU / 领域专用架构](/docs/CS/CO/simd.md)
- [并行与伪共享](/docs/CS/OS/Parallel.md)
- [Linux 电源管理](/docs/CS/OS/Linux/PM/cpufreq.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Computer Organization and Design（Patterson & Hennessy）](https://www.elsevier.com/books/computer-organization-and-design/patterson/978-0-12-820331-6)
3. [SPEC — Standard Performance Evaluation Corporation](http://spec.org)
4. [Dark Silicon and the End of Multicore Scaling（Esmaeilzadeh et al., 2011）](https://dl.acm.org/doi/10.1145/2000367.2000798)
