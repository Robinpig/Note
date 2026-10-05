## Introduction

Linux 的电源管理是一个**倒金字塔**：越往底层，节能越彻底，但对系统行为的要求越苛刻。本目录按"能省多少"从低到高组织：

| 层次 | 手段 | 省电程度 | 副作用 |
| :-- | :-- | :-- | :-- |
| 空闲挂起 | [cpuidle](/docs/CS/OS/Linux/PM/cpuidle.md) — C-state | 小 | 唤醒延迟 |
| 频率调节 | [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md) — P-state | 中 | 需要重新调频 |
| 设备省电 | [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md) | 中 | 引用计数管理 |
| 温控 | thermal — 降频/降速 | 中 | 性能下降 |
| 整机睡眠 | [suspend](/docs/CS/OS/Linux/PM/suspend.md) — S3/S2idle | 大 | 上下文保存恢复 |
| 热插拔电源 | [devfreq](/docs/CS/OS/Linux/PM/devfreq.md) | 视设备 | 设备特有 |

三个概念要分清，这是理解整个子系统的前提：

- **C-state**（cpuidle）：CPU 什么都不干时的省电档位，**与"谁在用 CPU"无关**，只关心"没事做的时候停多久"。
- **P-state**（cpufreq）：CPU 有活干时跑多快，**与性能直接挂钩**。
- **睡眠状态**（suspend）：整机（包括内存）一起断电，是完全不同的一层。

cpuidle 选 C-state 时会参考下一个定时器到期时间，cpufreq 选 P-state 时会参考当前 util —— 两者共享"预测还有多久空闲"这个信息，但决策目标相反。

## 一个贯穿全栈的机制：PM QoS

PM 性能服务质量（PM QoS）是内核里唯一一处"由用户态声明需求、影响内核决策"的机制。它的作用是给电源管理各层提供一个**统一的延迟/频率约束出口**：

```
用户态: 进程设为实时/设 CPU 亲和/写 cgroup 带宽
   ↓
PM QoS: 全局 cpu_latency_qos / 各设备 latency QoS
   ↓
消费者: cpuidle governor 不会进太深的 C-state
        cpufreq governor 会提频
        thermal 会在延迟约束前先降频
```

最典型的效果是：**实时任务存在时，cpuidle 只能进浅 C-state**（否则唤醒延迟不可接受），功耗上升但响应性有保证。这是"跑实时任务为什么更费电"的技术原因。

> ⚠️ **v7.2 的一个重要变化**：旧资料里控制 cpuidle 选深度的 `cpuidle_latency_limit` / `cpuidle_latency_requirement` 两个 sysfs 节点**已不存在**。同样的语义改由 PM QoS 提供。

## 跨层接缝

- **timer / tick**：cpuidle 进入深度空闲前要停 tick，用 hrtimer 模拟 —— 完整机制见 [timer 时间子系统](/docs/CS/OS/Linux/timer.md) 的 NO_HZ 一节。
- **调度器**：cpufreq 的 schedutil governor **直接与调度器对话**取 util，不经过别的中间层，见 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md)。
- **cgroup**：cgroup 的 `cpu.max` 限流会导致 throttle，而 throttle 与调频的相互作用见 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md)。
- **中断**：runtime PM 与中断唤醒的交互（能否在中断上下文里 get/put）见 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md)。
- **崩溃转储**：睡眠失败时的错误处理与 `pm_test_level` 调试开关见 [suspend](/docs/CS/OS/Linux/PM/suspend.md)。

## 排障速查

```shell
# cpuidle：当前有哪些 C-state、用了哪个
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/disable
cat /sys/devices/system/cpu/cpuidle/current_driver
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/latency      # 退出延迟
cat /sys/devices/system/cpu/cpu0/cpuidle/state*/residency    # 目标驻留

# cpufreq：当前频率与 governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
cat /sys/devices/system/cpu/cpufreq/boost            # 剩余 P-state 比例

# 睡眠：可用状态与测试
cat /sys/power/state
cat /sys/power/mem_sleep
cat /sys/power/disk                       # 关机时磁盘策略

# runtime PM：设备的电源状态与 autosuspend 延时
cat /sys/devices/platform/.../power/runtime_status
cat /sys/devices/platform/.../power/autosuspend_delay_ms
cat /sys/devices/platform/.../power/control            # auto|on

# 全局统计
grep -E "^(nr_|state_)" /sys/devices/system/cpu/cpuidle/stats
cat /proc/cmdline | tr ' ' '\n' | grep -E "cpuidle|pm=|nohz"
```

## Links

- [cpuidle 空闲挂起](/docs/CS/OS/Linux/PM/cpuidle.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [runtime PM 设备省电](/docs/CS/OS/Linux/PM/runtimepm.md)
- [suspend 整机睡眠](/docs/CS/OS/Linux/PM/suspend.md)
- [devfreq 设备动态频率](/docs/CS/OS/Linux/PM/devfreq.md)
- [timer 时间子系统](/docs/CS/OS/Linux/timer.md)
- [进程调度 fair](/docs/CS/OS/Linux/proc/fair.md)
- [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)

## References

1. [Linux Kernel Documentation — CPU Idle](https://docs.kernel.org/admin-guide/pm/cpuidle.html)
2. [Linux Kernel Documentation — CPU Frequency Scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
3. [Linux Kernel Documentation — Runtime PM](https://docs.kernel.org/power/runtime_pm.html)
4. [Linux Kernel Documentation — System Suspend](https://docs.kernel.org/power/suspend-and-hibernate.html)
5. [Linux Kernel Documentation — PM Quality of Service](https://docs.kernel.org/power/pm_qos_interface.html)
