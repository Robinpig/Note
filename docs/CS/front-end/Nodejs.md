## Introduction

Node.js 是基于 V8 引擎的 JavaScript 服务端运行时（2009 年 Ryan Dahl），核心设计是**事件循环 + 非阻塞 I/O**：一个主线程配合 libuv 线程池处理文件/DNS 等阻塞操作，网络 I/O 直接走操作系统的 epoll/kqueue/IOCP 事件通知，用单线程模型扛住大量并发连接。它让 JS 从浏览器脚本变成服务端语言，并带来了 npm——曾经最大的包生态。

## Execution Model: Event Loop

```
   ┌───────────────────────────────────────────┐
   │            一个 JS 主线程                    │
   │  调用栈执行同步代码                          │
   │      │                                     │
   │      ▼                                     │
   │  异步 API（fs/net/timer…）注册回调          │
   │      │                                     │
   │      ▼                                     │
   │  libuv：epoll/kqueue/IOCP + 线程池          │
   │      │  I/O 完成                            │
   │      ▼                                     │
   │  任务队列 → 事件循环取出回调 → 回主线程执行   │
   └───────────────────────────────────────────┘
```

事件循环各阶段（libuv）：timers（setTimeout）→ pending callbacks → idle/prepare → **poll（取 I/O 事件）** → check（`setImmediate`）→ close callbacks。微任务（Promise.then、queueMicrotask、nextTick）在每个阶段切换之间全部清空，**微任务优先级高于宏任务**，`process.nextTick` 又高于 Promise 微任务。

关键推论：CPU 密集计算会阻塞整个循环（所有客户端一起卡），这类任务要用 worker_threads 或丢给子进程/外部服务。这与 [C10k 问题](/docs/CS/CN/C10k.md)的解决思路一脉相承，也与 [Nginx](/docs/CS/CN/nginx/nginx.md)、Redis 的事件驱动同构。

## Modularity

- **CommonJS**（Node 传统）：`require()` 同步加载、`module.exports`，首次加载后缓存于 `require.cache`，可以做条件加载；
- **ESM**（标准，Node 14+ 稳定）：`import/export`，静态分析、异步加载、支持 top-level await；`.mjs` 或 package.json `"type": "module"`；
- 二者互操作规则是工程上最常见的坑（default 导出在 CJS 互操作时挂在 `.default`）。

## Ecosystem and Toolchain

| 领域 | 代表 |
|------|------|
| Web 框架 | Express（中间件洋葱模型）、Koa（async/await 中间件）、Fastify（高性能、schema 校验）、NestJS（企业级，DI + 装饰器） |
| 包管理 | npm、yarn、pnpm（硬链接 + 内容寻址存储，省磁盘且严格依赖） |
| 构建/转译 | [Webpack](/docs/CS/front-end/Webpack.md)、esbuild（Go 写的极速 bundler）、Vite（dev 用原生 ESM、build 用 Rollup） |
| TypeScript | [TypeScript](/docs/CS/TypeScript/TypeScript.md) 是 JS 的静态类型超集，编译期擦除；TS 7 起编译器为 Go 原生实现 |
| 进程与部署 | cluster（多进程共享端口，老方案）、worker_threads（共享内存的线程）、PM2、容器化 |

## Boundary with Browser JS / Deno / Bun

- Node 有文件系统、进程、原生模块；浏览器 JS 有 DOM、受同源策略约束——宿主能力不同，语言本身相同（V8）；
- Deno：默认安全（权限显式授予）、原生 TS、内置工具链；Bun：JavaScriptCore + 系统级 bundler/test runner，主打性能；
- Node 仍是最稳的生产选择，二者蚕食的是工具链与边缘函数场景。

## Links

- [Electron](/docs/CS/front-end/Electron.md)
- [Webpack](/docs/CS/front-end/Webpack.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [浏览器原理](/docs/CS/Browser/Browser.md)
- [C10k](/docs/CS/CN/C10k.md)
- [IO 多路复用（epoll）](/docs/CS/OS/Linux/IO/epoll.md)

## References

1. [Node.js 官方文档](https://nodejs.org/docs/latest/api/)
2. [Node.js Event Loop 指南](https://nodejs.org/en/guides/event-loop-timers-and-nexttick)
