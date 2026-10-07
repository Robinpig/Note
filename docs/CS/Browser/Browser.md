## Introduction

浏览器是一个把 URL 变成可交互页面的**大型应用运行时**：它同时是 HTTP 客户端、HTML/CSS 解析器、JavaScript 解释器与 JIT、图形合成器、安全沙箱和多进程操作系统。理解浏览器的内部管线（导航→解析→布局→绘制→合成）是前端性能优化（LCP/INP/CLS）、网络协议演进（HTTP/2、HTTP/3）和安全策略（同源策略、沙箱）的共同基础。

## Process Model

现代浏览器（Chrome/Edge/Firefox）采用多进程架构：

- **Browser 进程（主进程）**：地址栏、导航、Cookie/权限、网络栈（早期各页面共享，部分浏览器如此）；
- **Renderer 进程**：每个站点（site isolation 下按 site 隔离）一个，跑 Blink 渲染引擎 + V8 JS 引擎，处于沙箱中，崩溃不影响其他标签；
- **GPU 进程**：统一调度 GPU 命令做合成与加速；
- 网络服务、音频、存储等可拆为 utility 进程。

Site Isolation 让不同站点的渲染进程完全隔离，是防御 Spectre 类侧信道的关键；进程间通过 Mojo IPC（Chrome）通信，跨进程开销也是 iframe 性能成本的来源。

## Navigation and Rendering Pipeline

```
输入 URL
 → DNS 解析 + TCP/TLS 建连（[TLS](/docs/CS/CN/TLS.md)，缓存与预连接）
 → 请求/响应（[HTTP](/docs/CS/CN/HTTP/HTTP.md)；协商/强缓存、H2 多路复用、H3/QUIC）
 → HTML 解析成 DOM，CSS 解析成 CSSOM（遇到 <script> 默认阻塞，可 defer/async/module）
 → 合并为 Render Tree（只含可见节点，display:none 不进渲染树）
 → Layout/Reflow：计算每个节点几何位置
 → Paint：按层光栅化为位图
 → Composite：GPU 线程合成各层上屏
```

关键优化常识：

- 改动布局属性（width/top）触发 reflow（重排）→repaint→composite，最贵；只改颜色触发 repaint；只改 transform/opacity 可只走合成（提升为合成层），最省——这是动画性能的核心；
- 帧预算约 16.6ms（60Hz），长任务超过 50ms 就会影响 INP 指标；
- JS 是单线程事件循环（宏任务/微任务），与渲染共享主线程；长任务用 Web Worker 或拆分；
- 关键渲染路径优化：CSS 尽早、JS 加 defer、preload/prefetch、代码分割。

## JS Engine and V8

V8 的管线：解析器生成 AST → Ignition 解释器生成字节码直接执行 → 热点函数被 TurboFan 优化为机器码（去优化时可回退）。隐藏类（hidden class/shape）与内联缓存让动态类型也能高性能；对象频繁增删属性会退化隐藏类，创建对象保持构造顺序一致是经典建议。垃圾回收采用分代（新生代 Scavenge / 老生代 Mark-Sweep-Compact）。

## Storage and Caching

| 机制 | 生命周期/特点 |
|------|--------------|
| HTTP Cache | 强缓存（Cache-Control/max-age）与协商缓存（ETag/Last-Modified） |
| Cookie | 每次请求自动携带，容量小，有 Domain/Path/Secure/HttpOnly/SameSite |
| localStorage / sessionStorage | 同步键值，约 5MB，前者持久后者会话级 |
| IndexedDB | 异步事务型对象库，容量大，PWA 离线数据主力 |
| Cache API + Service Worker | 可编程的请求缓存，支撑离线与弱网 |

## Security Model

- **同源策略（SOP）**：协议+域名+端口三者相同才允许直接读 DOM/发请求；跨域用 CORS（响应头授权）、postMessage（窗口间）、[WebSocket](/docs/CS/CN/WebSocket.md)（不受 CORS 限制但有 Origin 校验）；
- **沙箱**：渲染进程在最小权限沙箱中运行，配合 site isolation；
- **安全头**：CSP（限制脚本来源防 XSS）、HSTS（强制 HTTPS）、X-Frame-Options/frame-ancestors（防点击劫持）；
- 证书与传输安全见 [TLS](/docs/CS/CN/TLS.md)，网络层攻击见 [Attack](/docs/CS/CN/Attack.md)。

## Developer Tools and Ecosystem

DevTools 的 Network（瀑布图/排队/TTFB/协议版本）、Performance（火焰图、布局抖动）、Memory（heap snapshot 排查泄漏）是核心排障入口；Lighthouse 给出性能/可访问性/最佳实践评分。桌面化方案 [Electron](/docs/CS/front-end/Electron.md) 就是把 Chromium + Node.js 打包；服务端渲染/边缘渲染则是把同一套渲染逻辑搬到服务器。

## Links

- [HTTP](/docs/CS/CN/HTTP/HTTP.md)
- [TLS](/docs/CS/CN/TLS.md)
- [WebSocket](/docs/CS/CN/WebSocket.md)
- [Attack](/docs/CS/CN/Attack.md)
- [Electron](/docs/CS/front-end/Electron.md)
- [Firefox](/docs/CS/Browser/Firefox.md)

## References

1. [How browsers work](https://web.dev/howbrowserswork/)
2. [Chrome 内部架构：进程模型](https://developer.chrome.com/blog/inside-browser-part1/)
