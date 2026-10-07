## Introduction

Flutter 是 Google 推出的**跨平台 UI 工具包**：一套 Dart 代码同时编译到 iOS、Android、Web、Windows、macOS、Linux 与嵌入式设备。与依赖原生控件的跨端方案不同，Flutter **自己绘制每一个像素**——框架自带渲染引擎（Skia/Impeller）和完整的 Widget 库，不借道平台原生组件，从而保证多端视觉与行为高度一致。

## 技术架构

| 层 | 内容 |
| --- | --- |
| Framework（Dart） | Material / Cupertino Widget、渲染（RenderObject）、动画、手势、基础库 |
| Engine（C/C++） | Skia/Impeller 图形、Dart VM、文字排版、平台通道 |
| Embedder（平台原生） | 各平台的壳：创建 surface、事件循环、打包成 .apk/.app |

Dart 的双重编译模式是 Flutter 性能的关键：

- **JIT + 热重载（Hot Reload）**：开发期在 VM 上运行，改动代码秒级注入、保留状态，这是 Flutter 开发体验的核心卖点。
- **AOT 机器码**：发布期编译成原生 ARM 指令，无 JS 桥接、无解释执行，UI 跑在 60/120fps 的单线程事件循环里。

## Widget 与渲染

- **一切皆 Widget**：不仅按钮、文本是 Widget，布局（Row/Column/Stack）、padding、居中也是 Widget，组合成声明式的 Widget 树。
- **三棵树**：Widget（不可变配置）→ Element（实例/生命周期）→ RenderObject（布局与绘制）。Widget 频繁重建很廉价，真正昂贵的布局绘制由 RenderObject 层 diff 后最小化更新。
- **布局约束向下、尺寸向上**：父节点给约束，子节点在约束内决定尺寸，父节点定位——理解这条协议是排查布局问题的基础。
- 声明式 UI + diff 重建的思想与 React 同源，可与前端笔记 [Browser 渲染管线](/docs/CS/Browser/Browser.md)对照。

## 与原生及其他跨端方案对比

| 方案 | UI 来源 | 语言 | 特点 |
| --- | --- | --- | --- |
| 原生（Swift/Kotlin） | 平台控件 | Swift / Kotlin | 体验上限最高，双端两套代码 |
| Flutter | **自绘控件** | Dart | 多端一致性最好、UI 流畅；包体积较大、原生能力靠插件 |
| React Native | 映射为原生控件 | JS/TS | 生态贴近前端，桥接有历史性能坑（新架构已改 JSI） |
| Web 容器 / 小程序 | WebView/自绘 | JS | 见 [Mini Program](/docs/CS/SE/MiniProgram/Mini_Program.md)，适合轻量分发 |
| 桌面跨端 | Web 渲染 | JS | [Electron](/docs/CS/front-end/Electron.md) 用 Chromium 自绘，思路与 Flutter 类似但技术栈不同 |

与原生能力交互走 **Platform Channels**（消息编解码，异步传递）；系统级行为（如 Android 的线程调度、cpuset 分组）仍由平台决定，可参考 [Android schedule](/docs/CS/OS/Android/schedule.md)。

## 适用与不适用

- 适用：UI 为主、追求多端一致、团队希望一套代码快速迭代的应用；早期产品验证、品牌化强的界面。
- 谨慎：重度依赖平台最新原生特性、对包体积极度敏感、需要大量系统级底层调用的场景——插件质量与桥接成本会成为风险。

## Links

- [Dart](/docs/CS/Dart/Dart.md) — Flutter 的编程语言（语言特性与编译模型）
- [Mini Program](/docs/CS/SE/MiniProgram/Mini_Program.md) — 另一种轻量跨端形态
- [Electron](/docs/CS/front-end/Electron.md) — 桌面端自绘式跨端（Chromium + Node）
- [Nodejs](/docs/CS/front-end/Nodejs.md) / [Webpack](/docs/CS/front-end/Webpack.md) — 前端技术栈
- [Android schedule](/docs/CS/OS/Android/schedule.md) — 底层 Android 平台调度机制

## References

- [Flutter 官方文档](https://docs.flutter.cn/)
