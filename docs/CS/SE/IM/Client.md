## Introduction

这一页讲的是 IM 客户端最现实的一个工程问题：**保活**。服务端消息要到达 App，前提是 App 那条长连接还活着、进程还没被系统回收；而对操作系统来说，一个长期驻留后台、周期性收发数据的进程，恰恰是最该被节制的那一类。所以保活不是技巧问题，而是在厂商省电策略与应用实时性之间找一块还站得住的地方。协议侧的设计见 [MQTT](/docs/CS/SE/IM/MQTT.md)，服务端架构见 [IM](/docs/CS/SE/IM/IM.md)。

## Why Keep Alive Is Hard

Android进程和Service的保活，是困扰Android开发人员的一大顽疾。
因涉及到省电和内存管理策略，各厂商基于自家的理解，在自家 ROM 发布时都对标准 Android 发行版做出或多或少的改动，
使得应用层程序在处理进程和Service保活问题上变的异常复杂，且很难兼容，因为说不定哪款手机或者哪个版本的省电策略发生改变，
那么随之而来的就是进程和Service保活的差异。

在应用场景上，由于即时通讯应用（包括IM聊天应用、消息推送服务等）为了保证消息的全时、实时送达能力，必须要实现进程或Service的保活。
而就这一看似不起眼的问题，实际处理起来，因为众多Android手机和Android系统版本的差异，让问题的处理充满了不确定性

## What the System Actually Allows

原生 Android 的限制是逐年收紧的，理解这条时间线才不会去做无用功：

| 版本 | 限制 |
|------|------|
| Android 6.0（API 23） | **Doze**：熄屏、未充电、静止一段时间后进入，挂起网络访问、忽略 wake lock、推迟 AlarmManager 标准闹钟与 JobScheduler，仅在周期性维护窗口（maintenance window）放行 |
| Android 7.0（API 24） | Doze-on-the-Go（熄屏即缓步进入，不要求静止）、限制隐式广播 |
| Android 8.0（API 26） | **后台执行限制**：后台应用无法再随意启动后台服务，退后台后服务会在短时间内被停止 |
| Android 9（API 28） | **App Standby Buckets**：按使用频次把 App 分入 Active / Working Set / Frequent / Rare 等桶，据此限制 job 与 alarm 配额 |

Doze 期间仍保留的几个口子（且它们的配额本身就说明了系统态度）：

- `setAndAllowWhileIdle()` / `setExactAndAllowWhileIdle()`：可在 Doze 中触发，但**每个 App 每 9 分钟最多一次**；
- `setAlarmClock()`：闹钟类闹钟照常触发，系统会为此提前退出 Doze；
- **高优先级 FCM 消息**：可以立即唤醒设备下发通知——这是官方给出的推荐做法，也是滥用会被限流的地方。

## Vendor ROMs Take It Further

上述原生限制之外，厂商 ROM 往往更激进。以小米 MIUI 为例：

以小米手机为例，MIUI的神隐模式让很多IM和推送开发同行纠结不已：在MIUI深度休眠之后,默认会彻底断开后台应用的socket
但微信、QQ这样的应用，MIUI官方的帖子说了:给这2个应用特殊照顾

情况是这样的： 在MIUI深度休眠之后,默认会彻底断开后台应用的socket,关于微信,和QQ,miui官方的帖子说了,给这2个应用特殊照顾。

问题怎么解决：
咱们自己的app应用就没有这些特殊待遇了,所以就必须需要用户自己来手动设置后台app在深度休眠之后依然要使用网络连接。
位置就在: 设置->其他高级设置->电量和性能 ->"神隐模式"。
没事就是这个神隐模式,默认就是开启的,不注意根本不知道MIUI加了这个坑爹的功能,只要把这个神隐模式关闭之后,推送心跳、IM心跳这些就可以正常的工作了。

关于用户手动设置关闭神隐模式的体验问题：
上面也说了，qq和微信这样的大牌是被MIUI特殊照顾的，其它app就没那么好待遇了，只能自已在UI和功能体验上下功夫了：比如像ios一样，推送通知这样的权限申请时给一个提示框，友好一点，引导用户去解决它（对于你的app一说，首次安装运行时如果是运行在MIUI下，就引导用户去解决这个神隐模式问题了）

## What Actually Works

把结论说白：**不要试图在系统限制之下硬保活**。与 Doze、App Standby、厂商省电策略逐项对抗的方案，短期能跑,长期一定会随某个 ROM 版本失效，而且会把耗电代价转嫁给用户（进而招来一星和卸载）。业界收敛下来的做法是：

1. **把实时性外包给系统通道**：国内用厂商推送（小米、华为、OPPO、vivo 等各自的系统推送），海外用 FCM，在 App 内做一层统一抽象；App 活着时走自己的长连接，被杀死时降级到系统通道唤醒。
2. **消息到达路径做成多级**：优先长连接推送，超时则由短信 / 电话这类带外手段兜底——这与服务端 [掉单机制](/docs/CS/SE/掉单机制.md) 的思路一致，都是先承认"一定会丢"，再设计兜底。
3. **只在确有必要时用前台服务**：前台服务伴随常驻通知，用户看得见，也就不算"偷偷活着"；滥用会被系统和应用商店双重针对。
4. **把选择权交还给用户**：检测到 ROM 有深度省电策略时给出引导（如 MIUI 神隐模式），并说清代价，而不是静默地加一堆白名单请求。

## Links

- [IM](/docs/CS/SE/IM/IM.md)
- [DTIM](/docs/CS/SE/IM/DTIM.md)
- [MQTT](/docs/CS/SE/IM/MQTT.md)
- [闲鱼 IM](/docs/CS/SE/IM/闲鱼IM.md)
- [掉单机制](/docs/CS/SE/掉单机制.md)

## References

1. [Optimize for Doze and App Standby — Android Developers](https://developer.android.google.cn/training/monitoring-device-state/doze-standby)
