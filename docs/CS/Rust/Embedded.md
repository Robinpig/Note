## Introduction

嵌入式是 `#![no_std]` 最主流的落地场景，但「Rust 写单片机」这件事的知识密度不在语言里，而在一套**分层的 crate 栈**里：PAC 描述寄存器，HAL 用 trait 描述外设行为，BSP 把板级事实（时钟、引脚、链接脚本、契约槽）固化，驱动 crate 只依赖中间的 trait 层，于是「驱动 × 芯片」的组合数从乘积变成和。本篇讲的就是这四层各自在解决什么问题。

no_std 本身的机制（能力边界、panic_handler / eh_personality / global_allocator 四件套、双模 crate、panic 策略）归 [No_Std](/docs/CS/Rust/No_Std.md)，本篇只引用不重述；MMIO 的 volatile 语义与 unsafe 依据在 [Unsafe](/docs/CS/Rust/Unsafe.md)；异步执行器与 Future 的语义在 [异步](/docs/CS/Rust/Async.md) 与 [Async_Runtime](/docs/CS/Rust/Async_Runtime.md)。

> [!NOTE]
> 本篇 crate 版本号取自 crates.io sparse index 实测（2026-10-08），MSRV 取自索引 `rust_version` 字段。**裸机目标上的链接、烧录、芯片运行结果未在本机实测**（宿主是 `aarch64-apple-darwin`，未安装任何 nightly 与裸机 target）——凡涉及链接脚本、向量表、`-Z build-std` 的内容均标注「据文档」。

## The Four Layers

| 层 | 代表 crate | 回答什么问题 | 换芯片时要改吗 |
| :--- | :--- | :--- | :--- |
| 应用 | 你的 firmware | 业务逻辑 | 否（理想情况下） |
| 驱动 | `ssd1306`、`esp8266` 等 | 某个外设怎么驱动 | 否，这是分层的全部意义 |
| HAL | `stm32f4xx-hal`、`nrf52840-hal`、`rp2040-hal` | 这颗芯片的外设怎么操作 | 换芯片则换 |
| PAC | `stm32f4`、`nrf52840-pac` | 寄存器在哪个地址、什么位域 | 换芯片则换 |
| BSP | `stm32f4-discovery`、`pimoroni-pico-explorer` | 这块板子：引脚、时钟、入口、契约槽 | 换板则换 |

驱动 crate 只依赖 `embedded_hal` 的 trait，所以「一个 SSD1306 驱动 × 所有实现了 `I2c` 的芯片」成立。这是 C 裸机生态做不到的事 —— C 的 HAL 通常是宏与头文件，编译期没有 trait 解这个耦。

命名规律：芯片厂的 HAL 一般是 `stm32f4xx-hal` 形式，板级包一般是 `stm32f4-discovery`、`pimoroni-pico-explorer` 形式。**写固件几乎总是从 BSP 开始**，因为 BSP 正是把 [No_Std](/docs/CS/Rust/No_Std.md) 里那四件套（panic_handler、入口、全局分配器、critical-section 实现）加板级硬件事实打包好的那一层。

## PAC: Register Maps Generated from SVD

PAC（Peripheral Access Crate）通常由 `svd2rust` 从厂商的 SVD 文件（XML 格式的外设描述）生成。它把每个外设的寄存器块变成一个结构体，把每个位域变成一个 `Field` 枚举。三个设计要点：

1. **`Peripherals` 是单例**：`let p = pac::Peripherals::take().unwrap();`，第二次 `take()` 返回 `None` —— 用类型系统防止两个代码段同时操作同一个外设。要绕过就用 `Peripherals::steal()`（unsafe），代价是自己论证互斥。
2. **寄存器访问全部 volatile**：生成的 `write` / `modify` / `read` 都走 `read_volatile` / `write_volatile`（原因与实测见 [No_Std](/docs/CS/Rust/No_Std.md) 的 MMIO 节）。
3. **零成本**：一个 `GPIOA.odr.modify(|_, w| w.odr15().bit(true))` 编译后就是一条 read-modify-write 汇编，没有函数调用开销。这是 Rust 泛型 + trait 抽象在裸机上成立的前提。

## embedded-hal: Why a Trait Layer

HAL 的意义不是「省事」，而是**把「驱动」与「芯片」两件事解耦**：驱动 crate 只依赖 `embedded_hal::i2c::I2c` 这个 trait，不依赖 STM32 也不依赖 nRF。于是 `驱动 × 芯片` 的组合数从乘积变成和。

1.0.0 相对 0.2.x 的关键改动是**把错误类型拆成独立的 `ErrorType` trait**。给 `struct Pin` 直接 `impl OutputPin`（方法返回 `Result<(), core::convert::Infallible>`）而不写 `ErrorType`，实测得到：

```text
error[E0277]: the trait bound `Pin: embedded_hal::digital::ErrorType` is not satisfied
help: the trait `embedded_hal::digital::ErrorType` is not implemented for `Pin`
```

补上 `impl ErrorType for Pin { type Error = core::convert::Infallible; }` 后编译通过。0.2.x 用 `void::Void` 表达「不会失败」，1.0.0 换成 `core::convert::Infallible`——**这是 no_std 友好化的一部分**：不再需要外部 `void` crate。

async 侧的对应物是 `embedded-hal-async`：同样是 trait 定义，由 HAL crate 实现。这让 `embassy` 的异步驱动可以在任何实现了对应 trait 的芯片上跑。

## heapless: Collections Without a Heap

与 [集合类型](/docs/CS/Rust/Collections.md) 的对照点很直接：`heapless::Vec<T, N>` 的容量 `N` 是**类型参数**，存储内联在结构体里，因此 `size_of::<Vec<u8, 8>>()` 是编译期常量、无间接层、无重分配。代价是 `push` 可能返回 `Err`（容量满），而不是悄悄扩容。

实测：在 `#![no_std]` crate 里写 `let mut v: Vec<u8, 8> = Vec::new(); v.push(1).unwrap();`，`cargo build` 通过，依赖树只有 `heapless → byteorder / hash32 / stable_deref_trait`，**没有一个拉回 std**——这是「依赖树干净」的正面样本。

选型判据很简单：容量有编译期上界且不大（几十到几百字节）用 `heapless`；容量运行时才知道，或需要跨入无限增长，用 `alloc` 版 `Vec`（意味着要有全局分配器，见 [No_Std](/docs/CS/Rust/No_Std.md)）。

## embassy-executor: Async Without an OS

与 [异步](/docs/CS/Rust/Async.md) 的交叉点最容易写错：嵌入式 async **不需要 OS 线程，也不需要堆**。`async fn` 编译出的状态机是**存在栈上（或 `static` 里）的结构体**，`Waker` 由硬件中断触发（而不是线程池唤醒）。`embassy-executor` 做的是一个单栈、协作式的任务轮询器：任务 `await` 某个外设时让出，中断来了把对应 `Waker` 标为就绪，执行器再轮询。没有抢占、没有每任务独立栈、无 `Arc` 也能跑。

这是 Rust `async` 设计成「零分配状态机 + 外部 executor」而非「内置运行时」的直接收益——Go / JavaScript 那种带运行时 goroutine / 事件循环的模型在这里塞不进去。执行器模型本身（work-stealing、阻塞线程池、取消安全）归 [Async_Runtime](/docs/CS/Rust/Async_Runtime.md)。

## critical-section: A Slot for Critical Sections

单核 MCU 上「关中断」没有统一指令（Cortex-M 用 `PRIMASK`，RISC-V 用 `mie`），而 `alloc` / `embassy` 这类通用 crate 又需要它。`critical-section` 的做法与 `GlobalAlloc` 完全同构：**定义契约，由平台 crate 在链接期填一个实现**。用户代码写 `critical_section::with(|cs| { ... })`，具体是关中断还是别的手段由 `cortex-m` 或 `riscv` 的实现决定。

这是 no_std 生态里反复出现的设计模式——**用 lang-item 式的契约槽替代运行时多态**。四处同构：

| 契约槽 | 谁定义 | 谁填充 |
| :--- | :--- | :--- |
| `GlobalAlloc` | `core::alloc` | 你的 `#[global_allocator]`（通常在 BSP） |
| `panic_handler` | `core` | 你的 `#[panic_handler]`（通常在 BSP） |
| `critical_section` 实现 | `critical-section` | `cortex-m` / `riscv` 等平台 crate |
| `defmt::Logger` | `defmt` | 你的 `#[defmt::global_logger]` |

## defmt: Moving Formatting to the Host

`format!("x = {}", x)` 在固件里的代价是：格式化代码 + 格式字符串 + `Display` 实现全部进 flash，可能几十 KB。`defmt` 的做法是**固件侧只发一个「interned 字符串索引 + 参数字节流」**，真正的格式化由宿主上的 `defmt-decoder` 结合 ELF 里的符号表完成。

两个工程后果要知道：

1. **它要求链接脚本额外放一个 `.defmt` 段**，并需要 ELF 文件参与解码——与 [ELF](/docs/CS/Compiler/ELF.md) 的知识在这里接上。
2. **日志输出与调试通道绑定**：RTT（实时传输，SEGGER 协议）是默认搭档，probe-rs 直接解码；也可以配 semihosting。所以「有没有接探针」决定了 `defmt` 日志看不看得见。

它也解释了 [No_Std](/docs/CS/Rust/No_Std.md) 里那个「宏与格式化逻辑共用，运行时分离」的设计：`panic!` 与 `defmt::panic!` 是同一套机制的两个出口，格式化器可换。

## probe-rs: The Host-Side Toolchain

`probe-rs` 用 Rust 重写了调试探针协议（SWD / JTAG），替代 OpenOCD + GDB 的组合，并原生支持 `defmt` 的 RTT 解码与 `cargo embed` / `cargo flash` 工作流。

**它是宿主侧的 std 程序，不是固件的一部分**——这个区分很重要：no_std 只约束跑在芯片上的那一半。同一原则适用于 `cargo-binutils`、`svd2rust`、`probe-run` 等一切「生成代码 / 操作 ELF / 通信探针」的工具。

## Interrupts and Interrupt Safety

中断是嵌入式独有的「并发」形态，Rust 的类型系统在这里只能帮一半：

1. **数据竞争**仍被编译期挡住：中断处理函数与主循环共享可变状态时，`static mut` 取引用在 edition 2024 直接 deny，解法与 [Unsafe](/docs/CS/Rust/Unsafe.md) 的替代表一致（原子 / `Mutex` / `critical-section` + `RefCell`）。
2. **中断优先级与重入**编译器一无所知：同优先级中断不嵌套、`critical_section::with` 的粒度、ISR 里能不能分配内存（取决于分配器是否中断安全），这些全是契约，写错就偶发崩溃。
3. **外设中断的登记方式**是 HAL 层的：`embassy` 用 `interrupt::typelevel::X` 做编译期检查（两个任务绑定同一个中断 = 编译错误），`cortex-m-rt` 用 `#[interrupt]` 属性。前者把「中断号不重复」变成类型约束，是嵌入式里少见的能编译期证明的并发安全。

## DMA and Cache Coherence

DMA 是 volatile 之外第二个「编译器与硬件不一致」的来源，而且更难查：

- **缓存一致性**：CPU 写了缓冲区，DMA 读之前若数据还在 cache 里，DMA 看到的是旧值（或空）。需要 `clean` / `invalidate` 缓存操作，或把缓冲区放在 non-cacheable 内存区（链接脚本 + MPU 配置）。
- **编译器屏障 vs 硬件屏障**：`core::sync::atomic::compiler_fence` 只约束编译器重排，`atomic::fence` 才可能下发硬件屏障（平台相关）。DMA 完成的通知通常走「中断置标志 + 主循环读标志」，两边都要考虑可见性顺序（模型归 [Atomics](/docs/CS/Rust/Atomics.md)）。
- **借用与 DMA 重叠**：DMA 传输期间 CPU 若还能写那块缓冲区，就是数据竞争。常见解法是「DMA 期间把缓冲区所有权交给外设对象」（类型状态机模式，如 `stm32f4xx-hal-dma` 的 `Transfer` 类型持有 `&mut [u8]`），把「还在传」编码进类型。

## Panic Strategy and Memory Layout

裸机上 panic 策略不只是体积问题，还是可用性问题：

- `panic = "abort"` 让 panic 直接进死循环 / 触发复位，没有 unwind 表，flash 占用最小；配合 `panic-probe` 一类的 crate 可以往探针发一条日志再挂住。
- `panic = "unwind"` 在 no_std 下**不可用**（[No_Std](/docs/CS/Rust/No_Std.md) 有实测报错），所以裸机没有这个选项。
- 内存布局由 `memory.x` 声明 FLASH / RAM 的 Origin 与 Length，`flip-link` 把栈顶放到「越界即硬件 fault」的位置——溢出不再静默改写其他内存。这是 Rust 把「内存安全」延伸到裸机的又一例：溢出从 UB 变成可定位的 HardFault。

## RTIC versus Embassy

两个框架回答了同一个问题——「没有 OS 怎么组织并发任务」——但取向相反：

| | RTIC | Embassy |
| :--- | :--- | :--- |
| 并发模型 | 中断驱动的优先级任务，抢占语义明确 | 协作式 async，单栈轮询 |
| 硬件关系 | 任务直接绑定中断，优先级即任务优先级 | 中断只负责唤醒 `Waker`，调度在执行器里 |
| 实时性 | 有界延迟可推导（优先级 + 短 ISR） | 取决于任务是否及时让出 |
| 心智负担 | 要理解优先级与资源锁（`Mutex` 即 `critical-section`） | 要理解 async、`Pin` 与取消安全 |
| 与语言的关系 | 宏生成中断表 | 就是 `async fn` + executor |

选型判据：硬实时约束强、外设中断密集选 RTIC；任务逻辑复杂、IO 密集、想复用桌面端的 async 代码选 Embassy。两者都用 `critical-section` 做底层互斥。

## Embedded Pitfall Checklist

| # | 坑 | 现象 | 解法 |
| :--- | :--- | :--- | :--- |
| 1 | 手写寄存器赋值 | 死存储被消掉、读被合并 | `read_volatile` / `write_volatile`；用 PAC |
| 2 | `static mut` 在 ISR 与主循环间共享 | edition 2024 deny；偶发数据竞争 | 原子 / `Mutex` / `critical-section` |
| 3 | `alloc` 在中断里分配 | 分配器非中断安全时崩溃 | 分配器选中中断安全实现，或 ISR 内不分配 |
| 4 | DMA 期间 CPU 写缓冲区 | 偶发数据错乱，无规律 | 类型状态机移交所有权；缓存 clean/invalidate |
| 5 | 忘了 `memory.x` / 链接脚本 | 入口找不到、数据段错位 | BSP 提供；`flip-link` 兜底栈溢出 |
| 6 | 中断号被两个任务绑定 | 运行期行为随机 | `embassy::interrupt::typelevel` 编译期查重 |
| 7 | `defmt` 日志看不到 | 探针没连 / RTT 没配 | 确认 `.defmt` 段与 probe-rs RTT 通道 |
| 8 | 依赖树里混进 std-only crate | 裸机交叉编译才炸 | `cargo tree -f "{p} {f}"`；`default-features = false` |
| 9 | `critical-section` 版本填了 1.3.0 | 已 yank，解析失败 | 最新可用是 1.2.0 |
| 10 | soft-float / hard-float ABI 不匹配 | 链接到不存在的 FPU 指令 | 确认 target ABI（`eabi` vs `eabihf`） |

## Links

- [No_Std](/docs/CS/Rust/No_Std.md)
- [Unsafe](/docs/CS/Rust/Unsafe.md)
- [异步](/docs/CS/Rust/Async.md)
- [Async_Runtime](/docs/CS/Rust/Async_Runtime.md)
- [集合类型](/docs/CS/Rust/Collections.md)
- [Edition 与 MSRV](/docs/CS/Rust/Edition_MSRV.md)

## References

1. [The Embedded Rust Book](https://docs.rust-embedded.org/book/)
2. [The Embedonomicon](https://docs.rust-embedded.org/embedonomicon/)
3. [docs.rs — embedded-hal 1.0.0](https://docs.rs/embedded-hal/1.0.0/embedded_hal/)
4. [docs.rs — heapless 0.9.3](https://docs.rs/heapless/0.9.3/heapless/)
5. [docs.rs — embassy-executor 0.10.0](https://docs.rs/embassy-executor/0.10.0/embassy_executor/)
6. [Embassy Documentation](https://embassy.dev/)
