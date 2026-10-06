## Introduction

systemd 不是单个进程，而是**一整套用户态设施**：PID 1 本身、启动管理、设备事件、服务激活、日志、用户会话管理、容器与服务运行器。它统一的设计前提是**一切皆 D-Bus 对象** —— 每个服务、每个设备、每个 slice 都是总线上的一个对象，可以被查询与控制。

它与内核的边界在 **cgroup**：`systemd` 负责"按需启动/停止谁、放进哪个 cgroup、限额多少"，内核负责"真的按 cgroup 记账执行"。这个分工在 [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md) 里有完整说明。

版本事实以 systemd **262~devel** 为准（man page 当前版本）。标注了 `Added in version` 的事实是核实过的，其余以官方 man page 为准。

## unit 类型

`systemd.unit(5)` 列出 **11 种** unit 后缀：

| 后缀 | 作用 |
| :-- | :-- |
| `.service` | **最常用** —— 管理一个长期运行的进程 |
| `.socket` | 监听 socket，按需激活服务（socket activation） |
| `.device` | 一个设备（udev 产生） |
| `.mount` / `.automount` | 挂载点 / 按需挂载 |
| `.swap` | swap 空间 |
| `.target` | 一组 unit 的聚合（启动目标） |
| `.path` | 监控路径变化触发 unit |
| `.timer` | 定时触发（替代 cron） |
| `.slice` | **cgroup 层的资源分组**（管理资源，非进程） |
| `.scope` | 外部创建的进程组（systemd 之外的进程） |

> [!NOTE]
>
> - **`.busname` 已彻底移除**（历史上 systemd 214 引入、219 前后废弃）。取代它的是 `.service` + `Type=dbus` + `BusName=`。
> - `.snapshot` 是**内部类型**（`systemctl snapshot` 产生），不该当普通 unit 文件类型写。

`.slice` 与 `.scope` 的区别是理解资源管理的关键：**`.slice` 由 systemd 管理（能改限额），`.scope` 是 systemd 之外创建的**（systemd 只能观察，不能改配置）。

`.timer` 与 `.path` 的作用经常被低估：前者替代 cron（`OnCalendar=` / `OnBootSec=`），后者在**目录变化时**触发（`PathChanged=` / `PathExists=`）—— 配合 `inotify` 实现"文件来了就处理"，比轮询省资源。

## Type=：服务怎么算"启动完成"

`systemd.service(5)`：

| 值 | 语义 | 适用 |
| :-- | :-- | :-- |
| **`simple`** | `fork()` 成功即算完成，**不等 `execve()`** | 有 `ExecStart=` 的常见默认 |
| **`exec`** | `fork()` **与** `execve()` 都成功才算完成 | **v240 引入**，想捕捉 exec 失败时用 |
| `forking` | 程序自行 fork，父进程退出即算完成 | ⚠️ **官方不推荐**，建议改 `notify`/`dbus` |
| `oneshot` | 等主进程跑完再启动后续单元 | 允许多个 `ExecStart=` |
| `dbus` | 等取得 `BusName=` 指定的总线名 | D-Bus 激活的服务 |
| **`notify`** | 等 `sd_notify(3)` 发 `READY=1` | **最可靠的现代做法** |
| `notify-reload` | notify + 用 `RELOADING=1`/`READY=1` 跟踪重载 | 默认重载向主进程发 `SIGHUP` |
| `idle` | 同 simple，但延后到当前活动作业分发完成后 | 效果最多持续 5 秒 |

**默认规则链**（按顺序判断）：

1. 设 `BusName=` → `Type=dbus`
2. 用了 credentials → 隐含 `exec`
3. 设了 `ExecStart=` 且未设 `Type=` → `simple`
4. 什么都没设 → `oneshot`

`Type=simple` 的陷阱是 **`ExecStart=` 里的命令拼错（命令不存在）时，systemd 认为启动成功了** —— 因为 `fork()` 本身成功，只有 `execve()` 失败，而 simple 不等它。日志里能看到"启动成功"但进程立刻消失。**这正是 `Type=exec` 要解决的问题**（v240 引入的动机就是"simple 下 Execve() 失败被发现得太晚，无法回传给 start job"）。

推荐做法是**用 `Type=notify`，让服务自己确认准备好了**。这也是容器 healthcheck 的常见模式 —— 服务真正能服务才报 READY。

## 依赖指令

`systemd.unit(5)`。**关键区分：要求依赖与排序依赖互相独立**，要求依赖不自动决定顺序 —— 这解释了为什么实践中几乎总要同时写 `Requires=` + `After=`。

| 指令 | Added in | 语义 |
| :-- | :-- | :-- |
| `Requires=` | 201 | 强要求；配合 `After=` 时对方启动失败会阻自己 |
| `Wants=` | 201 | **弱**要求；对方失败通常不使本事务失败 |
| `BindsTo=` | 201 | 比 Requires 更强：**对方意外停止（含失败）也停/重启本单元**；官方建议配 `After=` |
| `PartOf=` | 201 | 只传播 stop/restart，**单向**；不因此拉起对方 |
| **`Upholds=`** | **249** | 类 Wants，但**持续保障**：只要本单元在，列出的单元不会处于 inactive/failed，且不为它们排 job |
| `Conflicts=` | 201 | 互斥；启动任一方停止另一方；**本身不提供顺序** |
| `Before=` / `After=` | 201 | 纯排序，不建立依赖 |

`Upholds=` 的场景很具体：**一个常驻的代理服务需要确保它依赖的若干服务一直运行**，但不想在启动时强拉起它们（那可能不必要）。这在 v249 之前只能用 `BindsTo` + `Restart` 绕。

`BindsTo=` 与 `Requires=` 的实际差异值得记：**`Requires=A` 只在启动阶段要求 A 成功；A 之后自己挂了，本单元照旧运行。`BindsTo=A` 则会连带停止或重启本单元。** 选错的常见后果是"服务莫名重启"。

`Conflicts=` 也有陷阱：**它本身不提供顺序**。两个互斥单元若没写 `Before=`/`After=`，停止与启动的先后是不确定的 —— 想保证"先停 A 再起 B"必须显式写排序。

## socket activation

这是 systemd 最有特色的设计：**服务不常驻，靠 socket 请求唤醒**。

```
客户端 connect() → 内核通知 systemd → systemd 启动 foo.service → 服务处理已建立的连接
```

`systemd.socket(5)` 的关键配置：

| 指令 | 语义 |
| :-- | :-- |
| **`Accept=`** | `no`（默认）：把监听 socket 交给一个服务实例，服务自己 accept；`yes`：**每连接启一个服务实例**，通常配 `foo@.service` 模板 |
| `Service=` | 默认 = 把 `.socket` 换成 `.service`。systemd 自动加 `Before=` 排序，但**不加** `WantedBy/RequiredBy` |
| `ListenStream=` | 多次指定按配置顺序传 fd；空串清除之前所有 `Listen*` |
| `SocketMode=` | 默认 **0666**，只作用于**有文件系统节点**的（AF_UNIX / FIFO / POSIX 消息队列） |
| `FileDescriptorName=` | Added in **227** |

**`Accept=yes` 只支持 SOCK_STREAM** —— 对数据报 socket 与 FIFO，`Accept=` 被忽略；且 `Service=` 只能配 `Accept=no`。

裸数字 `ListenStream=8080` 表示**经 IPv6 监听**（是否同时服务 IPv4 取决于 `BindIPv6Only=`）—— 这是 IPv6-only 主机上的常见坑。

`SocketMode=0666` 的默认值有个安全含义：**任何用户都能连这个 socket**（若有文件系统节点）。需要收紧就显式设 `SocketMode=0660` + `SocketGroup=`。

### fd 传递协议

服务侧用 `sd_listen_fds(1)` 接收：

| 环境变量 | 内容 |
| :-- | :-- |
| `LISTEN_PID` | 接收进程的 pid（不匹配当前 pid 则视为无有效 fd） |
| `LISTEN_FDS` | fd 数量 |
| `LISTEN_FDNAMES` | fd 名称，`:` 分隔 |

有效 fd 从 **`SD_LISTEN_FDS_START + i`**（即通常从 3 起）—— **代码里不要硬编码 3**，用 `sd_listen_fds()` 返回的基址。传 1 表示"读完删除这三个环境变量"。

`Accept=yes` 时 `FileDescriptorName` 默认是 `connection`。

## 资源控制

`systemd.resource-control(5)`，全部映射到 cgroup v2 文件：

| 指令 | cgroup 文件 | Added in |
| :-- | :-- | :-- |
| `MemoryMax=` | `memory.max` | 231 |
| `CPUQuota=` | `cpu.max` | 213 |
| `TasksMax=` | `pids.max` | 227 |
| `IOWeight=` | `io.weight`（**默认 100**，范围 1–10000） | 230 |
| `IOReadBandwidthMax=` 等 | `io.max` | 230 |
| **`ManagedOOMMemoryPressure=`** / `ManagedOOMSwap=` | 基于 `memory.pressure` 监控 | **247** |

`CPUQuota=` 的周期由 `CPUQuotaPeriodSec=` 决定，对应 `cpu.max` 的第二个字段（默认 100 ms，见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)）。

### ManagedOOM：内核压力下的受害者选择

`ManagedOOMMemoryPressure=kill` 的语义：把该 cgroup 设为内存压力的**候选受害者集合**；超阈值时 `systemd-oomd.service` 选一个**后代 cgroup** 发 `SIGKILL`。

这与内核自己的 OOM killer 完全不同：内核按 `oom_badness` 打分选**进程**（见 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)），而 systemd-oomd 选**整个 cgroup**。适合"这个服务的所有 worker 一起重启比杀掉零散几个更好"的场景。

取值 `auto`（默认）表示本单元不主动监控，**但祖先为 `kill` 时仍可被连带杀**。启用时会自动加 `After=`/`Wants=` systemd-oomd.service（除 `DefaultDependencies=no` 的单元）。

### OOMPolicy=

`OOMPolicy=` 三值（**Added in 243**）：

| 值 | 行为 |
| :-- | :-- |
| `continue` | 仅记录，不动进程 |
| `stop` | 干净终止（走该服务的正常停止流程），事后进 `oom-kill` 失败态 |
| `kill` | 设 `memory.oom.group=1` 让内核杀光该组其余进程 |

默认值继承 `DefaultOOMPolicy=`，**但启用了 `Delegate=` 的单元默认 `continue`** —— 因为 `Delegate=` 意味着服务自己管 cgroup，systemd 不该替它决定。

## Delegate=

布尔，默认关。开启后 systemd 把该单元的 cgroup 子树控制权交给服务：可以建子 cgroup、用 cgroup/BPF 接口、部分资源控制自行管理。但**不脱离系统 cgroup 层级与其他内核限制**。

`Delegate=yes` **不是"systemd 不再管你"** —— `MemoryMax=` 这类指令仍生效（写在服务 cgroup 的根上）。它给的是"在该子树内继续往下配"的权限。

不写 `Delegate=yes` 但服务内自己 `mkdir` cgroup 目录会失败（`-EPERM`）—— 这是"我的服务在容器里建不了 cgroup"的根因。详见 [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md)。

## Restart= 与自动重启

七值：`no`（默认）/`on-success`/`on-failure`/`on-abnormal`/`on-watchdog`/`on-abort`/`always`。

限制：**`Type=oneshot` 不允许 `always` 或 `on-success`**。

`on-abort` 值得注意 —— **信号导致的非正常退出**（如收到 SIGABRT/SIGSEGV）才算，`SIGTERM` 之类算正常停止不算。

`WatchdogSec=` 让服务周期性发 `WATCHDOG=1` 心跳，超时则算 hang 触发 `on-watchdog` 重启。这是检测"进程还在但卡死"的机制。

`StartLimitIntervalSec=` / `StartLimitBurst=` 限制重启频率 —— **没有它，故障服务会无限重启刷屏**（systemd v230 起默认启用该限制）。

## 诊断工具

| 命令 | 用途 |
| :-- | :-- |
| `systemd-analyze blame` | 按耗时列出启动单元（**定位启动慢的首选**） |
| `systemd-analyze critical-chain` | 打印关键路径上的单元 |
| `systemd-analyze cat-config` | 看最终生效的合并配置（比翻文件准） |
| `systemd-analyze verify <unit>` | 检查 unit 文件语法与依赖问题 |
| `systemctl status` / `show` / `cat` | 状态 / 全部属性 / 配置 |
| `systemctl list-dependencies` | 依赖图 |
| `systemctl list-units --by-slice` | 按 slice 归类，看资源归属 |
| `systemctl is-system-running` | 整体状态（`degraded` = 有单元失败） |
| `journalctl -b` | 本次启动日志 |
| `journalctl -u <unit>` | 某单元日志 |
| `journalctl -k` | 仅内核日志 |
| `journalctl -p <prio>` | 按优先级 |
| `journalctl -f` | 跟随 |
| `systemd-cgtop` | 实时看 cgroup 资源占用 |

`systemctl show` 的价值常被低估：它输出**所有**配置属性（含默认值与最终生效值），比读 unit 文件准确 —— 配置文件可能被 drop-in 覆盖。

## 排障速查

```shell
# 全局状态
systemctl is-system-running          # degraded = 有单元失败
systemctl --failed                    # 失败的单元
systemd-analyze blame | head -20      # 启动最慢的 20 个单元
systemd-analyze critical-chain        # 关键路径

# 单元细节：show 比读文件准（drop-in 会覆盖）
systemctl cat nginx                   # 看配置文件（含 drop-in）
systemctl show nginx                  # 看最终生效的全部属性
systemctl show nginx -p Type -p Restart -p Delegate -p MemoryMax
systemctl list-dependencies nginx

# 日志
journalctl -u nginx -f
journalctl -b -1                      # 上次启动（对比为何启动失败）
journalctl -k | grep -i oom           # 内核 OOM 记录
journalctl _TRANSPORT=kernel -p err   # 只看错误级内核日志

# 资源
systemd-cgtop                         # 实时
systemctl show <unit> -p MemoryCurrent -p CPUUsageNSec
cat /sys/fs/cgroup/<path>/memory.events
systemd-oomd                         # ManagedOOM 的状态与下次触发预估

# 手改 drop-in（比改主文件安全，会被标记为可追溯）
systemctl edit nginx                  # 创建 /etc/systemd/system/nginx.service.d/override.conf
systemctl daemon-reload && systemctl restart nginx

# 验证 unit 文件
systemd-analyze verify /etc/systemd/system/nginx.service
```

## 与内核的接缝

- **cgroup**：资源控制、委派、冻结（`systemctl freeze`）的实际执行者，见 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md) 与 [委派实践](/docs/CS/OS/Linux/cgroup/delegation.md)。
- **namespace**：`Private*=` 系列指令使用 namespace 隔离，见 [namespace](/docs/CS/OS/Linux/namespace.md)。
- **设备模型**：`.device` unit 由 udev 产生，见 [udev](/docs/CS/OS/Linux/dev/udev.md)。
- **用户态设备**：`uinput` 让程序造 input 设备，见 [input](/docs/CS/OS/Linux/dev/input.md)。
- **OOM**：`OOMPolicy=` 与内核 OOM killer 的分工见 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。
- **定时器**：`.timer` 单元替代 cron，其实现与内核 timer 无关（用户态），但 `.timer` 触发的动作可能涉及内核设施（如重启、挂载）。

## Links

- [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)
- [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md)
- [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)
- [OOM killer](/docs/CS/OS/Linux/mm/oom.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [shell](/docs/CS/OS/Linux/Tools/shell.md)

## References

1. [systemd.unit(5)](https://man7.org/linux/man-pages/man5/systemd.unit.5.html)
2. [systemd.service(5)](https://man7.org/linux/man-pages/man5/systemd.service.5.html)
3. [systemd.socket(5)](https://man7.org/linux/man-pages/man5/systemd.socket.5.html)
4. [systemd.resource-control(5)](https://man7.org/linux/man-pages/man5/systemd.resource-control.5.html)
5. [systemd-analyze(1)](https://man7.org/linux/man-pages/man1/systemd-analyze.1.html)
