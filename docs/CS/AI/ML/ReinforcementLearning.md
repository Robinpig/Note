## Introduction

强化学习（Reinforcement Learning，RL）研究**智能体（Agent）如何通过与环境反复交互、按奖励信号试错，学出长期收益最大的行动策略**。它不同于监督学习：没有"标准答案"标签，只有延迟、稀疏的奖励；也不同于无监督学习：有明确的优化目标（累积回报）。

它解决的问题是：决策是**序列**的、当前动作影响未来局面的任务——下棋、机器人控制、游戏 AI、推荐系统，以及大模型对齐训练（RLHF）。

## Framework

强化学习的基本循环是"观察 → 行动 → 获得奖励 → 进入新状态"：

- **智能体（Agent）**：做决策的学习者
- **环境（Environment）**：智能体交互的对象，反馈新状态与奖励
- **状态（State）**：$s$，对局面的描述
- **动作（Action）**：$a$，智能体的选择
- **奖励（Reward）**：$r$，每步的即时标量反馈，是唯一的"教学信号"

目标是最大化**长期累积奖励**，而不是每一步的即时奖励——为了将来赢棋，现在可以故意弃子。

## MDP

大多数强化学习问题被形式化为**马尔可夫决策过程（Markov Decision Process，MDP）**，五元组 $(S, A, P, R, \gamma)$：状态集、动作集、状态转移概率 $P(s'\mid s,a)$、奖励函数 $R$、折扣因子 $\gamma\in[0,1)$。

**马尔可夫性**：未来只依赖当前状态，与历史路径无关——"现在包含全部信息"。

折扣因子 $\gamma$ 衡量"未来的奖励今天值多少"：$\gamma=0$ 只顾眼前，$\gamma$ 越大越有远见。

## Core Concepts

### 回报 Return

从时刻 t 起的累积折扣奖励：

$$
G_t=r_{t+1}+\gamma r_{t+2}+\gamma^2 r_{t+3}+\dots=\sum_{k=0}^{\infty}\gamma^k r_{t+k+1}
$$

### 策略与价值函数

- **策略（Policy）** $\pi(a\mid s)$：在状态 s 下选动作 a 的规则，学习的最终目标
- **状态价值函数** $v_\pi(s)=\mathbb{E}_\pi[G_t\mid s_t=s]$：按策略 π 从状态 s 出发的期望回报
- **动作价值函数** $q_\pi(s,a)=\mathbb{E}_\pi[G_t\mid s_t=s,a_t=a]$：在 s 先执行 a、再按 π 行动的期望回报

两者通过策略加权联系：$v_\pi(s)=\sum_a \pi(a\mid s)\,q_\pi(s,a)$。

### 贝尔曼方程

对回报按首项拆开：$G_t=r_{t+1}+\gamma G_{t+1}$，取期望即得价值函数的递归——**贝尔曼方程**。一步推导：

$$
v_\pi(s)=\mathbb{E}_\pi\left[r_{t+1}+\gamma G_{t+1}\mid s_t=s\right]
=\sum_a \pi(a\mid s)\sum_{s',r}p(s',r\mid s,a)\left[r+\gamma v_\pi(s')\right]
$$

当前价值 = 即时奖励 + 折扣后的下一状态价值。几乎所有 RL 算法都是围绕"如何估计/优化这个递归"展开的。

### 贝尔曼最优方程

最优策略 $\pi^*$ 对应的价值函数 $v^*,q^*$ 满足带 max 的递归——**贝尔曼最优方程**：

$$
v^*(s)=\max_a\sum_{s',r}p(s',r\mid s,a)\left[r+\gamma v^*(s')\right],\qquad
q^*(s,a)=\sum_{s',r}p(s',r\mid s,a)\left[r+\gamma\max_{a'}q^*(s',a')\right]
$$

它刻画了"最优"的定义，也是值迭代等算法的收敛目标：一旦解出 $q^*$，对每个状态直接贪心取 $\arg\max_a q^*(s,a)$ 即得最优策略。

## Solving Paradigms

求价值函数/策略有三条技术路线，区别在于"要不要模型"与"用什么目标更新"：

### 动态规划 Dynamic Programming

已知模型 $p(s',r\mid s,a)$（model-based）时，直接迭代解贝尔曼（最优）方程：

- **策略迭代（Policy Iteration）**：交替执行"策略评估"（解线性方程组或迭代求 $v_\pi$）与"策略改进"（$\pi'(s)=\arg\max_a q_\pi(s,a)$）。由**策略改进定理**保证 $v_{\pi'}\ge v_\pi$，严格改进则继续，收敛到最优策略
- **值迭代（Value Iteration）**：把评估截断为一步、直接对 max 迭代：

$$
v_{k+1}(s)=\max_a\sum_{s',r}p(s',r\mid s,a)\left[r+\gamma v_k(s')\right]
$$

### 蒙特卡洛 Monte Carlo

无模型：跑完整条轨迹，用实际回报 $G_t$ 的均值估计 $v_\pi(s)$。

- 无偏，但方差大；必须等 episode 结束才能更新，不适合持续任务

### 时序差分 Temporal Difference

无模型 + **自举（bootstrapping）**：不等轨迹结束，用"即时奖励 + 折扣后的当前估计"当目标：

$$
V(s)\leftarrow V(s)+\alpha\left[r+\gamma V(s')-V(s)\right]
$$

方括号是 TD 误差。相比 MC：有偏但方差小、可在线单步更新——Q-Learning、SARSA 都是它的成员。

| | 需要模型 p | 自举 | 偏差/方差 | 更新时机 |
| ------ | ------ | ------ | ------ | ------ |
| 动态规划 | 是 | 是 | 无偏（已知模型） | 每步扫描 |
| 蒙特卡洛 | 否 | 否 | 无偏/高方差 | episode 结束 |
| 时序差分 | 否 | 是 | 有偏/低方差 | 每步在线 |

## Exploration and Exploitation

利用（Exploitation）选当前已知最优的动作，探索（Exploration）尝试新动作以发现更好的选择。只用最优会陷入局部最优，只探索则学不到东西。最简单的平衡策略是 **ε-greedy**：以概率 ε 随机探索，以 1-ε 贪心利用。更精细的做法有乐观初始化（把没试过的动作价值设得偏高）、UCB（按不确定性加成）等。

## Algorithms

| 思路 | 代表算法 | 核心思想 |
| ------ | ---------- | ---------- |
| 基于价值 | Q-Learning、SARSA、DQN | 学 q(s,a)，策略从价值表推导 |
| 基于策略 | REINFORCE、PPO | 直接参数化并优化策略 π(a\|s) |
| Actor-Critic | A2C、SAC | 价值网络当 critic、策略网络当 actor，两者结合 |

### Q-Learning and SARSA

经典的**Q-Learning**（off-policy 时序差分）每步用实际经验修正价值估计：

$$
Q(s,a)\leftarrow Q(s,a)+\alpha\left[r+\gamma\max_{a'}Q(s',a')-Q(s,a)\right]
$$

目标里的 max 让它学习"greedy 策略"的价值，而行为策略可以带探索——这就是 off-policy。**SARSA** 把 max 换成"实际执行的下一动作"的 $Q(s',a')$，评估的是"正在执行的（含探索的）策略"，因此是 on-policy。

> [!NOTE]
> 收敛性：当学习率满足 Robbins-Monro 条件（$\sum_t\alpha_t=\infty$、$\sum_t\alpha_t^2<\infty$）且每个 (s,a) 被无限次访问时，Q-Learning 以概率 1 收敛到 $q^*$（Watkins & Dayan, 1992）。实践中的 ε-greedy 探索大致满足"无限次访问"。

### Policy Gradient

基于策略的方法直接对策略参数 $\theta$ 做梯度上升。策略梯度定理（REINFORCE 的出发点）把期望回报的梯度写成对数概率的期望：

$$
\nabla_\theta J(\theta)=\mathbb{E}_{\pi_\theta}\left[\sum_t \nabla_\theta\log\pi_\theta(a_t\mid s_t)\,G_t\right]
$$

直觉：把"带来高回报的动作"的概率往上推，低回报的往下压；$G_t$ 充当加权。REINFORCE 用整条轨迹的实际回报估计该期望——无偏但方差大，常加 baseline（减去 $v(s)$）降方差，这就引出 Actor-Critic。

### DQN

状态太多、表格存不下时，用神经网络 $Q(s,a;\theta)$ 近似价值函数，最小化 TD 目标的均方误差：

$$
L(\theta)=\mathbb{E}\left[\left(r+\gamma\max_{a'}Q(s',a';\theta^-)-Q(s,a;\theta)\right)^2\right]
$$

两大稳定化技巧：**经验回放**（把转移存进缓冲区随机抽样，打破数据相关性）与**目标网络**（参数 $\theta^-$ 定期从 $\theta$ 复制、期间冻结，避免"追逐移动目标"）。

## Applications

- **游戏与博弈**：Atari（DQN）、围棋（AlphaGo = 蒙特卡洛树搜索 + RL + 深度网络）
- **机器人控制**：机械臂操作、四足行走
- **推荐系统**：把"推送→用户反馈"建模为序列决策
- **大模型对齐**：RLHF（基于人类反馈的强化学习）用奖励模型指导 [LLM](/docs/CS/AI/LLM/LLM.md) 输出对齐人类偏好

> [!WARNING]
> 强化学习的工程难点不在算法本身：奖励设计不当会被"钻空子"（reward hacking）、样本效率低、训练不稳定、模拟器与现实存在差距（sim-to-real），落地时要重点评估这几项。

## Practice

用 Gymnasium 的 FrozenLake 环境跑一个表格型 Q-Learning：

```python
import gymnasium as gym, numpy as np

env = gym.make("FrozenLake-v1", is_slippery=True)
Q = np.zeros((env.observation_space.n, env.action_space.n))
for ep in range(20000):
    s, _ = env.reset(); done = False
    while not done:
        a = env.action_space.sample() if np.random.rand() < 0.1 else Q[s].argmax()  # ε-greedy
        s2, r, term, trunc, _ = env.step(a)
        Q[s, a] += 0.1 * (r + 0.99 * Q[s2].max() - Q[s, a])   # Q-Learning 更新
        s, done = s2, term or trunc
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

1. [Reinforcement Learning: An Introduction (2nd Edition)-Sutton & Barto](http://incompleteideas.net/book/the-book-2nd.html)
2. [Spinning Up in Deep RL-OpenAI](https://spinningup.openai.com/en/latest/)
