## Introduction

Android 调度的基座是 Linux 内核（task_struct、CFS/EEVDF、实时策略都在），但它面对的是**电池供电、大小核异构、应用生命周期复杂**的手机环境，因此在内核调度之上叠加了一整套"按应用重要性分配 CPU 资源"的机制：cpuset 分组、uclamp 利用率钳制、EAS 能耗感知调度、Binder 优先级传递，以及用户态的后台任务框架。正如 [Linux 调度笔记](/docs/CS/OS/Linux/proc/sche.md)所说："Android 更多的是实时的任务"——音频、渲染、触摸响应都有硬延迟要求。

## Foreground/Background Split: cpuset + cgroup

Android 通过 cgroup v2 的 **cpuset** 控制器把线程限制到不同的 CPU 集合，典型拓扑（8 核大小核手机）：

| 分组 | 允许的 CPU | 典型成员 |
|------|-----------|---------|
| top-app | 全部核（含超大核），最高频率 | 当前前台应用、RenderThread |
| foreground | 大核为主 | 前台相关、短时交互服务 |
| background | 仅小核 | 后台应用 |
| system-background | 小核 | 系统后台任务 |
| restricted / daemon | 小核、低频 | 不活跃应用、低优守护 |

分组依据不是进程 nice 值，而是 AMS（ActivityManagerService）维护的**进程优先级（oom_score_adj/ad j 等级）**：前台 Activity、可见、服务、缓存进程逐级降低；LMKD（Low Memory Killer Daemon）也依据同一排序在内存紧张时杀最不重要的进程。这与桌面 Linux"任务平等竞争"的模型完全不同。

## EAS and uclamp

- **EAS（Energy Aware Scheduling）**：使用手机芯片的能耗模型（Energy Model，各频点/各核簇功耗），唤醒选核时预测"把任务放在哪个核最省电且满足需求"，而不是单纯追求最快核。EAS 最初在 Android/ARM 生态发展后回流主线。
- **uclamp（utilization clamping）**：任务可以声明自己的利用率上下限：
  - `uclamp.min` 保证任务至少被当作 N% 忙碌来选核/调频——UI 线程哪怕只忙 1ms，也要求跑在大核上避免掉帧；
  - `uclamp.max` 限制后台任务最高可用算力（限频省电）。
  - Android 通过 `SetSchedAttr`/API 把 top-app 组设高 uclamp.min，是"前台流畅、后台省电"的关键开关。
- **schedboost/Adpf**：游戏/渲染还可通过 ADPF（Android Performance Performance Hint Session）直接给系统提示"这帧还要多久"，让调度器临时提频（替代早期的 schedtune.boost/`sched_setattr` 野路子）。

## Realtime and Rendering Threads

- 音频回调（AAudio/OpenSL ES 的 callback 线程）使用 **SCHED_FIFO** 实时调度，避免被普通线程抢占导致 underrun（爆音）；系统对 RT 带宽有 cgroup 限额（`cpu.rt_runtime_us`）防止饿死普通线程。
- **RenderThread** 与 Choreographer：UI 绘制按 VSYNC 节拍驱动（16.6ms/帧），渲染线程与主线程（UI Thread）分离，Binder/SurfaceFlinger 合成；一帧超时就是 jank，用 Perfetto 的 frame timeline 分析。
- 触摸输入线程、SurfaceFlinger 主循环同样是高优先级/RT。

## Priority Inheritance in Binder Calls

Android 的跨进程调用走 [Binder](/docs/CS/OS/Android/Android.md)：前台进程调用后台进程的服务时，如果后台 Binder 线程以低优先级执行，前台关键路径会被"优先级反转"拖慢。Binder 驱动实现了**跨进程优先级继承**：事务期间把服务端处理线程临时提升到调用方的 nice/优先级（含 uclamp/cpuset 上下文传递），事务结束恢复。这是实时系统经典 PI（priority inheritance）在内核驱动中的分布式应用，对照内核 futex 的 PI 实现。

## Userspace Task Framework

后台任务不能想跑就跑（耗电、唤醒风暴），Android 用框架统一收口：

| 机制 | 适用 | 触发保证 |
|------|------|---------|
| WorkManager / JobScheduler | 可延迟的后台任务（同步、上传） | 满足约束（充电、WiFi、空闲）时批量调度，进程重启也不丢 |
| Foreground Service | 用户可感知的持续任务（音乐、导航） | 必须挂通知，优先级高 |
| AlarmManager | 定时唤醒 | 非精确 alarm 被批量对齐；Doze 模式延迟到维护窗口 |
| Doze / App Standby | 灭机闲置 | 后台网络/任务被整体推迟，维护窗口集中放行 |

应用侧常见误区：靠常驻线程/轮询保活——现代 Android 上会被分组限流、Doze 冻结甚至 LMKD 杀掉，正确做法是 WorkManager + 前台服务。

## Troubleshooting Tools

- `adb shell top -H -p <pid>` / `ps -A -T -p <pid>`：看线程优先级（PRI/nice 与 RT 标记）；
- `/dev/cpuset/` 下各分组的 `cgroup.procs`、`effective_cpus`：确认进程被放进哪个 CPU 集合；
- **Perfetto/Systrace**：内核调度事件（sched_switch/waking）、CPU 频率、帧时间线的官方工具；
- `dumpsys activity o`、`dumpsys gfxinfo`：进程 oom 等级、渲染帧统计。

## Links

- [Android](/docs/CS/OS/Android/Android.md)
- [Linux 调度（CFS/EEVDF）](/docs/CS/OS/Linux/proc/sche.md)
- [进程知识地图](/docs/CS/OS/Linux/proc/README.md)
- [并行调度 Work-Stealing](/docs/CS/OS/Parallel.md)

## References

1. [Android Device Performance: ADPF](https://developer.android.com/games/adpf)
2. [Energy Aware Scheduling (EAS) - Linux Documentation](https://docs.kernel.org/scheduler/sched-energy.html)
