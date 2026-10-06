## Introduction

input 子系统解决一个具体问题：**把"物理设备产生的物理量"抽象成"内核与用户态都能理解的事件"**。硬件千差万别（键盘矩阵、触摸屏、力反馈手柄、加速度计），但对系统而言只该看到"EV_KEY 按下键码 30"、"EV_ABS X 轴移动了 5"这样的统一格式。

这套抽象由两侧组成，恰好对应设备驱动模型的两端：

| 侧 | 结构 | 谁来实现 | 例子 |
| :-- | :-- | :-- | :-- |
| 设备端 | `struct input_dev` | **驱动作者** | 键盘/触摸板驱动 |
| 处理端 | `struct input_handler` | **子系统/框架作者** | evdev、mousedev |

> [!NOTE]
>
> 本文所有函数名、字段名与文件路径在 **v7.2** 核实。v7.2 的 input 目录做过一轮改名，见文末"v7.2 变化清单"——**照抄旧教程会找不到文件**。

## 核心数据结构

### struct input_dev：设备端

`include/linux/input.h:137-212`。按功能分组：

| 组 | 字段 |
| :-- | :-- |
| 标识 | `name` / `phys` / `uniq` / `id` |
| **能力位图** | `propbit` / `evbit` / `keybit` / `relbit` / `absbit` / `mscbit` / `ledbit` / `sndbit` / `ffbit` / `swbit` |
| 键码表 | `keycodemax` / `keycodesize` / `keycode` / `setkeycode` / `getkeycode` |
| 设备方法 | `open` / `close` / `flush` / **`event`** |
| 锁与引用 | `event_lock`（自旋锁）/ `mutex` / `users` / `going_away` / `grab` |
| 子系统挂载 | `ff`（力反馈）/ `poller`（轮询）/ `mt`（多点触摸）/ `absinfo` |
| 缓冲 | `hint_events_per_packet` / `num_vals` / `max_vals` / `vals` |
| 时间戳 | `timestamp[INPUT_CLK_MAX]` |
| 驱动模型 | `dev`（用 `to_input_dev()` 转回） |

**能力位图是核心设计**：驱动声明"我支持哪些事件类型、哪些键码、哪些轴"，用户态通过 `EVIOCGBIT` ioctl 读它就知道这个设备能干什么。位图用 `BITS_TO_LONGS()` 宏分配，设备种类多时不会浪费。

`input_dev` 自己也挂进设备模型（`dev` 字段），所以 input 设备在 sysfs 里有 `/sys/class/input/` 树。

### struct input_handler：处理端

`include/linux/input.h:315-337`：

| 字段 | 作用 |
| :-- | :-- |
| **`events`** | **批量**事件回调（v7.2 的关键设计） |
| `event` | 单事件回调（老接口，由 `events` 的默认实现转调） |
| `filter` | 事件过滤器，返回 true 表示拦截 |
| `match` | 判断本 handler 是否处理该设备 |
| `connect` / `disconnect` | 建立/断开关联时调用 |
| `start` | 输入设备开始上报时调用 |
| `passive_observer` / `legacy_minors` / `minor` / `name` / `id_table` | 匹配与标识 |

> **v7.2 的关键变化是 `events()` 批量回调**。注释明确说同一结构也用于实现 input filter。批量接口的价值：一次鼠标移动会产生多个事件（X 位移、Y 位移、SYN_REPORT），批量传递省掉逐个函数调用的开销。

### struct input_value：值的抽象

```c
struct input_value {
	__u16 type;
	__u16 code;
	__s32 value;
};
```

只有三个字段 —— **type + code + value 就是事件的全部**。这个极简结构（配合 `dev->vals` 数组）是 v7.2 批量机制的基础。

> ⚠️ 旧的 `input_get_value()` 函数**不存在**，值抽象就是 `struct input_value` + `dev->vals` 数组。

配套时钟类型：

```c
enum input_clock_type {
	INPUT_CLK_REAL = 0,
	INPUT_CLK_MONO,
	INPUT_CLK_BOOT,
	INPUT_CLK_MAX
};
```

## 事件分发链

v7.2 的实际链路（比旧资料的"三段式"多一层批量值处理）：

```
驱动 driver
  └─ input_event(dev, type, code, value)          input.c:391
      guard(spinlock_irqsave)(&dev->event_lock)
      ├─ is_event_supported()                      input.c:65
      │     test_bit(code, bm) —— 能力位图里没有就直接丢弃
      └─ input_handle_event()                     input.c:358
          ├─ input_get_disposition()              返回 INPUT_* 位掩码
          ├─ add_input_randomness()               input.c:368  仅 type != EV_SYN
          └─ input_event_dispose()                input.c:318
              ├─ dev->event()                                → INPUT_PASS_TO_DEVICE
              ├─ 填 dev->vals[dev->num_vals++]                攒批
              └─ INPUT_FLUSH 或批量满 → input_pass_values()  input.c:342/353

input_pass_values()                                input.c:111  （持锁 + 关中断）
  ├─ dev->grab 存在 → 只给 grab 设备              input.c:120-124
  ├─ 遍历 dev->h_list（RCU）且 handle->open
  │     └─ handle->handle_events(handle, vals, count)      input.c:122/128
  │           ├─ input_handle_events_default()  → handler->event()
  │           ├─ input_handle_events_filter()   → filter() 拦截则终止
  │           └─ handler->events()              → evdev/mousedev 走这条
  └─ EV_REP 自动重复触发                          input.c:137-146
```

**"攒批"是这段代码的精髓**：`input_event()` 不断往 `dev->vals[]` 填，达到条件才一次性交给 handler。触发冲刷的条件是：

- 收到 `INPUT_FLUSH`（driver 显式要求）；
- 批量接近上限（`num_vals >= max_vals - 2`）—— **留 2 个槽位**避免边界溢出，此时内核自动插入 `SYN_REPORT` 同步事件再冲刷。

`handle_events` 这个函数指针由 core 在 `input_handle_setup_event_handler()` 里按 handler 的能力装配，注释强调它**在关中断且持 `event_lock` 的上下文执行，不可睡眠**。

反向注入（handler → device）走 `input_inject_event()`（`input.c:412`），在 RCU 下查 `dev->grab`，非 grab 设备收到的事件被丢弃。

### 三个 disposition 常量

```c
#define INPUT_IGNORE_EVENT	0
#define INPUT_PASS_TO_HANDLERS	1
#define INPUT_PASS_TO_DEVICE	2
```

`input_get_disposition()` 返回它们。`dev->event()` 回调可通过 `input_event_dispose()` 的返回值影响后续走向。`INPUT_SLOT` 与多点触摸的 slot 机制相关。

## 时间戳抽象

驱动上报事件时若不显式给时间，内核会补：

```c
int input_set_timestamp(struct input_dev *dev, ktime_t timestamp);   /* input.c:2053 */
ktime_t *input_get_timestamp(struct input_dev *dev);                   /* input.c:2068 */
```

`input_set_timestamp()` 要求传入 `CLOCK_MONOTONIC`，**一次写入派生三份**：

```c
	dev->timestamp[INPUT_CLK_MONO] = timestamp;
	dev->timestamp[INPUT_CLK_REAL] = ktime_mono_to_real(timestamp);
	dev->timestamp[INPUT_CLK_BOOT] = ktime_mono_to_any(timestamp, TK_OFFS_BOOT);
```

用户态读事件时选哪个时钟源由 `EVIOCSCLOCKID` 决定（存在 `client->clk_type`）。三种时钟的语义：**MONO 是单调的（适合计时）、REAL 是墙上时钟（适合时间戳）、BOOT 包含挂起时间**。

`input_get_timestamp()` 有个特殊行为：**若 MONO 为 0 则用 `ktime_get()` 合成**。这是"非零即有效"的约定 —— 所以冲刷批量后会重置 MONO 槽位（`input.c:350`），注释说明只重置单体时钟，因为它的存在与否正是"是否需要生成合成时间戳"的判据。

## evdev：把事件交给用户态

`drivers/input/evdev.c`。用户态通过 `/dev/input/eventN` 读事件，容器是 `struct input_event`（uapi 定义）。

`struct evdev_client`（`evdev.c:41-55`）的关键字段：

| 字段 | 作用 |
| :-- | :-- |
| `head` / `tail` | 环形缓冲读写指针 |
| `packet_head` | 记录上次 `SYN_REPORT` 时的 head，**用于丢弃空包** |
| `buffer_lock` | 自旋锁，保护缓冲 |
| `wait` | 阻塞读等待队列 |
| `fasync` | SIGIO 通知（`O_ASYNC`） |
| `evmasks[EV_CNT]` | **每类型事件掩码**，用户态 `EVIOCSMASK` 设置 |
| `bufsize` / `buffer[]` | 环形缓冲本体 |
| `clk_type` | 用户选的时钟源 |
| `revoked` | 客户端已断开则直接返回 |

关键常量：`EVDEV_MINOR_BASE 64`、`EVDEV_MINORS 32`（所以 event 编号从 64 起）、`EVDEV_MIN_BUFFER_SIZE 64U`、`EVDEV_BUF_PACKETS 8`。

### 事件过滤

`__evdev_is_filtered()`（`evdev.c:78`）：**`EV_SYN` 与 `type >= EV_CNT` 永不过滤**。所以用户态关掉某类事件不影响 `SYN_REPORT` 的同步语义。

`evdev_get_mask_cnt()`（`evdev.c:57`）有个历史坑，注释明确指出：

```c
	/* 陷阱：EV_SYN == 0 对应的长度是 EV_CNT 而不是 SYN_CNT
	   —— 与 EVIOCGBIT 的历史包袱有关 */
```

`__pass_event()` 的同步逻辑：`is_report = (EV_SYN && SYN_REPORT)`；缓冲满时插入 `SYN_DROPPED`（`evdev.c:155, 229`）告诉用户态"有事件丢了"。

`evdev_pass_values()`（`evdev.c:247`）会**丢弃空的 `SYN_REPORT`**（`272-275`）—— 一批事件里若只有同步标记，就不通知用户态（无意义地唤醒它）。只在真有内容时才 `wake_up_interruptible_poll()`。

### 常用 ioctl

| ioctl | 作用 |
| :-- | :-- |
| `EVIOCGBIT(ev,len)` | 读能力位图（ev 决定读哪张） |
| `EVIOCGID` | 设备 ID（`bustype` / `vendor` / `product` / `version`） |
| `EVIOCSMASK` | 设置事件掩码（只读某几类） |
| `EVIOCSCLOCKID` | 选择时钟源 |
| `EVIOCGPHYS` | 物理设备路径 |

`EVIOCGBIT` 的分派是 switch 每种 type 取对应位图：

```c
	case EV_ABS: bits = dev->absbit; len = ABS_MAX; break;
```

> ⚠️ `input_event_from_user()` 声明在 **`drivers/input/input-compat.h:69`**（不再是 `input.h`），配套 `input_event_to_user()`、`input_ff_effect_from_user()`。

## input-poller：轮询型设备

滑块、摇杆、加速度计这类**没有中断线**的设备需要内核主动轮询。`drivers/input/input-poller.c`（221 行）：

```c
struct input_dev_poller {
	int (*poll)(struct input_dev *dev, unsigned int cnt);   /* 驱动提供的读值回调 */
	unsigned int poll_interval;        /* msec */
	unsigned int poll_interval_max;
	unsigned int poll_interval_min;
	struct input_dev *input;
	struct delayed_work work;
};
```

`input_dev_poller_work()` 调完 `poll()` 后**再次排队**（`input.c:44`）—— 自续期循环，直到 `stop()`。

`input_dev_poller_finalize()`（`input.c:47`）里的**默认值很实用**：

```c
	if (!pdata->poll_interval)
		pdata->poll_interval = 500;              /* 500 ms */
	if (!pdata->poll_interval_max)
		pdata->poll_interval_max = pdata->poll_interval;
```

**`poll_interval` 不设就是 500 ms 一次**。工作队列用的是 **`system_freezable_wq`**（`input.c:35`）—— 轮询在系统冻结时自动停下，避免睡眠期间白耗电。

`input_start_polling()` 只在 `poll_interval > 0` 时首次同步调 `poll()`（`input.c:58-59`），所以"启用即调一次"。

## 其它 input 驱动

### mousedev：转成 PS/2 协议

`drivers/input/mousedev.c`（1125 行）把 input 事件**翻译成 PS/2 鼠标协议字节流**，供 X server / gpm 这类老式用户态消费。

混合设备（触摸板 + 物理按键同时存在）由 `mousedev_mix`（`mousedev.c:116`）聚合，`mixdev_*` 一族函数（454/484/935/959）负责把多个物理设备"融"成一个逻辑鼠标。

事件翻译函数：

```c
	mousedev_abs_event()      /* 绝对坐标 → 相对位移 */   mousedev.c:167
	mousedev_rel_event()      /* 相对位移直接用 */        mousedev.c:204
	mousedev_key_event()      /* 按键 → 三字节包 */       mousedev.c:222
	mousedev_touchpad_touch() /* 触摸板起停 */            mousedev.c:319
```

### 键盘

> ⚠️ **v7.2 没有独立的 `kbd-core.c` —— 键盘核心状态机在 `input.c` 内**。`drivers/input/keyboard/` 子目录只放具体控制器驱动（`atkbd.c` / `gpio_keys.c` / `matrix_keypad.c` 等）。

键盘的核心逻辑在 `input.c`：

- `input_start_autorepeat()` / `input_stop_autorepeat()` —— 键长按重复（`EV_REP`），由 `input_pass_values()` 在 `input.c:137-146` 调用；
- `input_set_keycode()` 体系；
- `dev->rep[REP_CNT]`（`input.h:174`）存重复速率与延迟；
- `EV_REP` 周期值在 `input.c:1731-1732` 下发。

### touchscreen 与多点触摸

`drivers/input/touchscreen.c`（208 行）只放**共用的 slot 状态机与 `input_device_enabled()` 判定**（后者被 `input-poller.c:170` 调用），不针对具体硬件。

MT 核心在 `drivers/input/input-mt.c`：`input_mt_init_slot()` 系列管理 slot 分配。`ABS_MT_SLOT` 范围 `0 .. num_slots-1`，`TRACKING_ID` 范围 `0 .. TRKID_MAX`（`input-mt.c:59-60`）。

`touch-overlay.c` 提供**触摸框选/放大**这类叠加手势。

### misc：板级杂项

`drivers/input/misc/` 有 90+ 个驱动，全是**板级/SoC 杂项**，不按设备类型划分：

| 类别 | 例子 |
| :-- | :-- |
| 电源键 | `axp20x-pek.c` / `rk805-pwrkey.c` / `snvs_pwrkey.c` / `*_pwrbutton.c` |
| 振动 / haptic | `max77693-haptic.c` / `pwm-vibra.c` / `drv260x.c` / `gpio-vibra.c` / `regulator-haptic.c` |
| 旋转编码器 | `rotary_encoder.c` / `max7360-rotary.c` |
| 蜂鸣器 | `pcspkr.c` / `gpio-beeper.c` |
| **uinput** | `uinput.o`（`CONFIG_INPUT_UINPUT`）—— **用户态造设备** |
| 键阵列 | `soc_button_array.c` / `gpio_decoder.c` |

**`uinput` 值得注意**：它让用户态程序可以**创建** input 设备（写一个虚拟手柄、触摸事件），是屏幕录制、自动化测试、远程桌面这类场景的基础。

> ⚠️ **`misc/` 里没有 hid / serio / lirc / lm**：
> - `hid` → 独立目录 `drivers/hid/`
> - `serio` → `drivers/input/serio/`（独立 Makefile，含 `serio.c` 抽象 + `i8042.c` + `libps2.c` + `serport.c`）
> - `lirc` → **内核树中已无 lirc input 驱动**（历史上有 `drivers/input/lirc/`，已删除）
> - `lm` → 无（`CONFIG_INPUT_LM` 不存在，LM 键盘走 serio 或 hid）

### joystick

`drivers/input/joystick/` 有 34 个手柄驱动：`xpad.c`（Xbox 通用）、`n64joy.c`、`gamecon.c`、`sidewinder.c`、`analog.c`，以及 6DoF 设备 `spaceorb.c` / `spaceball.c`。新式设备有 `qwiic-joystick.c` / `adafruit-seesaw.c` 这类 I2C/SPI 手柄。

> ⚠️ **`drivers/input/gamepad.c` 不存在**。另有旧式字符设备 `joydev.c`（`CONFIG_JOYSTICK`）。

## 能力位图的一致性校验

一个容易忽略但很体现内核风格的做法：`include/linux/input.h:219-262` 用 `#error` 指令**在编译期校验** uapi 侧的枚举与内核侧宏一致：

```c
#if EV_MAX != INPUT_DEVICE_ID_EV_MAX
#error "Please do not use EV_ABS etc, use INPUT_DEVICE_ID_EV_ABS instead."
#endif
```

内核内部一律用 `INPUT_DEVICE_ID_EV_*` 前缀的宏，**不用 uapi 的 `EV_*`/`KEY_*`/`ABS_*`**。改动事件类型时，漏改一处就会编译失败 —— 这比运行期出问题好得多。

事件类型的实际定义位置：`include/uapi/linux/input-event-codes.h`（1016 行），uapi 的 `struct input_event` 在 `include/uapi/linux/input.h`（539 行）。

## v7.2 变化清单

| 旧（不存在） | v7.2 | 说明 |
| :-- | :-- | :-- |
| `drivers/input/core.c` | **`input.c`** | 目标名 `input-core.o`，故实现文件叫 input.c |
| `drivers/input/ff.c` | **`ff-core.c`** | 另有 `ff-memless.c`（`CONFIG_INPUT_FF_MEMLESS`） |
| `drivers/input/gamepad.c` | `joystick/` 目录 + `joydev.c` | |
| `drivers/input/mousedrv.c` | **`mousedev.c`** | |
| `drivers/input/kbd-core.c` | 并入 `input.c` | 控制器驱动留在 `keyboard/` |
| `misc/hid`、`misc/serio` | `drivers/hid/`、`drivers/input/serio/` | |
| `struct input_device` | （无） | 只有 `struct input_device_id`（`mod_devicetable.h`）与 `struct input_id`（uapi） |
| `input_register_event_handler()` | **`input_register_handle()`** | 分发方法由 `input_handle_setup_event_handler()` 装配 |
| `input_get_value()` | `struct input_value` + `dev->vals` | |
| `handler->event` 直连 | `handle->handle_events` 批量层 | 需经 `input_handle_events_default/filter/null` 之一 |
| `input_dev_get_*` 当 evdev API | 只在 `input-poller.c` 是 sysfs 属性读写 | 真正的引用计数接口是 `input_get_device()` / `input_put_device()` |

## 与其它子系统的接缝

- **设备模型**：`input_dev` 内嵌 `struct device`，走 probe/match 绑定，见 [设备模型 device](/docs/CS/OS/Linux/dev/device.md)。
- **字符设备**：evdev 走 `cdev` 暴露 `/dev/input/eventN`，见 [字符设备驱动 char](/docs/CS/OS/Linux/dev/char.md)。
- **中断**：键盘/鼠标的中断处理里调 `input_event()`，见 [Interrupt](/docs/CS/OS/Linux/Interrupt.md)。
- **总线**：i2c_hid / usbhid 等驱动通过总线注册 input 设备，见 [dev 总线族](/docs/CS/OS/Linux/dev/bus.md)。
- **用户态**：uinput 反向造设备、D-Bus 转发（`libinput`/`evdev`）都是用户态选择。

## 排障速查

```shell
# 列出所有 input 设备与能力
cat /proc/bus/input/devices          # 最全的汇总视图
ls /sys/class/input/                 # 按设备分目录
cat /sys/class/input/input0/name
cat /sys/class/input/input0/uevent   # 能力位图的十六进制形式
cat /sys/class/input/input0/capabilities/  # 分类型：ev / rel / abs / key / sw

# 实时抓事件（不写代码）
evtest /dev/input/event0             # libevtest
cat /dev/input/event0 | od -c        # 原始事件流
libinput debug-events                # libinput 的格式化输出

# 轮询设备
cat /sys/class/input/inputX/poll_interval     # 0 = 不轮询
cat /sys/class/input/inputX/poll_interval_max
echo 100 > /sys/class/input/inputX/poll_interval   # 改成 100ms

# 调试：内核侧 tracepoint
mount -t debugfs none /sys/kernel/debug
echo 1 > /sys/kernel/debug/tracing/events/input/input_event/enable
cat /sys/kernel/debug/tracing/trace_pipe

# 键盘布局与按键重映射
cat /sys/class/input/inputX/keyboard/...
xmodmap -pke                        # 当前 X 键位映射
```

## Links

- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [字符设备驱动 char](/docs/CS/OS/Linux/dev/char.md)
- [dev 总线族](/docs/CS/OS/Linux/dev/bus.md)
- [Interrupt](/docs/CS/OS/Linux/Interrupt.md)
- [dev/README（设备驱动总览）](/docs/CS/OS/Linux/dev/README.md)

## References

1. [Linux Kernel Documentation — Input event-codes](https://docs.kernel.org/input/event-codes.html)
2. [Linux Kernel Documentation — INPUT(4) / input drivers](https://docs.kernel.org/input/input.html)
3. [Linux input-tools (libevtest, evemu)](https://github.com/gregkh/input-tools)
