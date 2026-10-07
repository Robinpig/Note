## Introduction

Dart 是 Google 设计的**面向对象、强类型、带 null safety 的编程语言**，主线定位是 [Flutter](/docs/CS/Flutter.md) 的专属语言——Flutter 用一套 Dart 代码自绘多端 UI。但 Dart 并不只活在 Flutter 里：它本身也能写 CLI 工具、轻量服务端和 Web 前端（编译到 JS / WASM）。

本页只收 Dart 语言本身（编译模型、类型系统、并发），UI 框架层面见 [Flutter](/docs/CS/Flutter.md)。语言入口的统一对照见 [编程语言横向对比](/docs/CS/Languages.md)。

## 双重编译模型

Dart 的"开发体验"和"发布性能"由同一套语言、两套编译器支撑，这也是 Flutter 的核心卖点：

- **JIT + 热重载（Hot Reload）**：开发期在 Dart VM 上运行，改代码秒级注入、保留组件状态——这是 Flutter 迭代快的根本。
- **AOT 编译**：发布期把 Dart 直接编译成原生机器码（ARM / x64），无解释、无 JS 桥接；Flutter 的 UI 就跑在 AOT 后的单线程事件循环里，目标 60 / 120fps。
- **Web 目标**：通过 dart2js 编译到 JavaScript，或走 dart2wasm 编译到 WASM。

## 语言特性

- **静态强类型 + 可选标注**：变量可省略类型（靠推断），但类型存在且参与检查；`sound null safety`（2.12 起）把"非空"写进类型系统，在编译期消除一类空指针错误。
- **单继承 + 接口 / mixin 组合**：类是唯一类型构造，能力复用靠 `implements` / `mixin` 而非多重继承。
- **异步基于 `async` / `await` + `Future` / `Stream`**：建立在线程内事件循环之上，与 JS 的 Promise 思路同源。

## 并发：Isolate

Dart 的并发单元是 **isolate**：每个 isolate 拥有**独立堆、彼此不共享内存**，通信靠 `SendPort` / `ReceivePort` 传递**消息**（可序列化对象，或通过 `TransferableTypedData` 零拷贝转移所有权）。这与 Go 的 goroutine（共享地址空间、靠 channel 通信）和 Java 的线程（共享堆、靠锁同步）都不同——Dart 从语言层就把"共享内存竞争"这条路堵死。

主 isolate 跑事件循环处理 UI；CPU 密集任务 spawn 新 isolate 卸载，避免阻塞渲染。

## 适用与不适用

- **适合**：Flutter 跨平台 UI（移动 / 桌面 / Web / 嵌入式）；希望一套语言打通前后端的轻量服务端或 CLI；对热重载开发体验敏感的团队。
- **不宜**：系统编程与裸机（没有 C / Rust 那种零成本控制）；对运行时体积 / 冷启动极敏感的 Serverless（VM / AOT runtime 有固有开销）；不在 Flutter 生态内的纯后端——库生态成熟度远不如 Java / Go / Node。

## Links

- [编程语言横向对比](/docs/CS/Languages.md)

## References

- [Dart 官方文档](https://dart.dev/)
- [Flutter 官方文档](https://docs.flutter.cn/)
