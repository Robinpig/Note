## Introduction

React 是 Meta 2013 年开源的**声明式 UI 库**，核心立场是「UI 是状态的函数」：组件用纯函数描述界面应该长什么样，状态变化后由框架负责高效同步到 DOM。它只盯视图层，路由、状态管理、数据请求都交给生态——这种「小内核 + 大生态」的形态是它成为使用面最广的前端框架的直接原因。版本基线（2026-10）：**React 19.3**（npm latest 19.3.1，19.3 线发布于 2026-09-09），React Compiler 1.0 已稳定；治理上，React / React Native / JSX 已于 2026-02-24 捐赠给 Linux Foundation 托管的 **React Foundation**（八家白金创始成员：Amazon、Callstack、Expo、Huawei、Meta、Microsoft、Software Mansion、Vercel）。

## UI as a Function of State

组件是一个函数：输入 props 与 state，输出对该界面的描述。关键约束是**渲染必须纯粹**——同样的输入得到同样的输出，渲染期间不读写外部可变状态；props 与 state 是不可变快照，渲染中修改它们没有意义。

JSX 不是 JavaScript 语言特性，而是编译期变换：`<div>{x}</div>` 被编译为 `jsx("div", { children: x })` 调用，产出描述界面的普通 JS 对象（即 Virtual DOM 的节点）。因此 JSX 可用可不用，Babel / esbuild / SWC / TypeScript 都内置该变换。

数据流是单向的：父组件通过 props 向下传，子组件通过回调向上报。「谁拥有状态」因此成为一个显式决策，标准解法是把状态提升到最近的共同父级。

## Fiber: Interruptible Rendering

2017 年的 Fiber 重写把 reconciliation（新旧描述树的对比）从一次性递归改为**可中断的增量工作**：渲染被拆成 fiber 节点上的工作单元，每处理完一个单元就检查是否有更高优先级任务插入——没有则继续，有则让出主线程。这把长列表渲染从「卡死页面」变成「可能掉帧但不冻结」。

- **双缓存**：内存中同时存在 current（已提交）与 workInProgress（构建中）两棵树，commit 阶段一次性切换指针；
- **优先级（lanes）**：离散输入（点击）> 连续输入 > 默认 > 过渡（Transition）> 重试，高优先级可打断低优先级未完成的渲染；
- **commit 阶段不可中断**：DOM 变更必须原子完成，否则用户会看到半个界面。

调度器把渲染切片插到宏任务之间执行，对应的是[浏览器渲染管线](/docs/CS/Browser/Browser.md)里「JS 执行与渲染争用主线程」的问题在框架侧的解法。

## Hooks and the Compiler

Hooks 让函数组件拥有状态与副作用：`useState` / `useReducer` 持有状态，`useEffect` 在提交后同步外部系统，`useMemo` / `useCallback` 记忆化，`useRef` 持有可变引用，`useContext` 读取上下文。它们的实现依赖**调用顺序**——Hook 按首次渲染的顺序挂在组件的链表上，因此必须顶层调用、不可条件调用，顺序变了链表就对不上。

React Compiler 1.0（随 React 19 稳定）把最后一块手动优化也自动化了：构建期分析组件代码并自动插入记忆化，大部分 `useMemo` / `useCallback` 不再需要手写。它需在构建配置中显式启用；启用后仍应以性能剖析为准，而不是把 memo 当正确性依赖。

## Concurrent Features and Actions

- `useTransition` / `useDeferredValue`：把非紧急更新标记为过渡，期间界面保持可交互；
- `Suspense`：声明式表达「这部分还在加载」，配合流式 SSR 逐步填充；
- React 19 的 **Actions**：把表单提交等异步操作提升为一等概念——`useActionState` 自动管理 pending / 错误 / 结果，`useOptimistic` 先渲染乐观结果再与权威数据对齐，`useFormStatus` 读取外层表单状态；
- `use()`：在渲染中读取 promise 或 context，未 resolve 时挂起；
- 19.2 增加 `Activity`（隐藏子树但保留状态、清理副作用）与 `useEffectEvent`；19.3 稳定 `addTransitionType`、Fragment refs 与视图过渡集成。

## Server Rendering and Server Components

渲染可以发生在两个地方：服务端产出 HTML，客户端 hydrate 成交互应用。React 的服务端能力分两条线——**流式 SSR**（HTML 边算边发，Suspense 边界决定刷新次序）与 **Server Components**（RSC，组件只在服务端执行，产物是序列化流而非 HTML，代码与密钥不进浏览器包）。`"use client"` 标记的是模块依赖边界而不是「只在客户端运行」——客户端组件同样可以被服务端预渲染。

安全注记：2025 年 12 月 RSC 实现接连曝出两轮漏洞（拒绝服务、源码泄露），React 以补丁版本修复——用 RSC 的生产系统应保持小版本跟进。

## Ecosystem

| 层 | 代表 | 说明 |
|----|------|------|
| 元框架 | Next.js（App Router）、React Router（v7 起合并 Remix） | 路由 + RSC/SSR 数据方案的默认答案 |
| 原生 | React Native + Expo | 新架构以 JSI 取代旧桥，Fabric 重构渲染层 |
| 服务端状态 | TanStack Query | 把「请求 / 缓存 / 失效」从全局状态里分离出来 |
| 客户端状态 | Redux Toolkit、Zustand、Jotai | 按应用规模递减的三个档位 |
| 构建 | Vite、[Webpack](/docs/CS/front-end/Webpack.md)、Rspack | dev 走原生 ESM 已成主流 |

## Four Frameworks, Four Bets

| 维度 | React | Vue | Angular | Svelte |
|------|-------|-----|---------|--------|
| 定位 | UI 库 | 渐进式框架 | 全家桶 | 编译器优先 |
| 渲染 | VDOM + Fiber 可中断 | VDOM（3.6 起可选 Vapor 无 VDOM） | Ivy 编译模板 + 信号驱动 | 编译为命令式 DOM 操作 |
| 状态 | `useState` 显式快照 | `ref` / `reactive` 代理 | `signal()` 细粒度 | `$state` runes |
| 优化手段 | Compiler 自动 memo | 编译期静态分析 + 响应式依赖 | 信号依赖追踪 | 编译期已知依赖 |
| 生态策略 | 不自带路由/状态 | 官方 Router/Pinia/Vite | CLI + Material 全家桶 | SvelteKit |

四者共同的演进方向是**把「何时该更新」从运行时猜测变成编译期/依赖追踪的确定答案**：React 靠 Compiler，Vue 3.6 靠 alien-signals 内核与 Vapor，Angular 靠信号 + zoneless，Svelte 干脆编译成直接 DOM 指令。

## Links

- [Vue](/docs/CS/front-end/Vue.md)
- [Angular](/docs/CS/front-end/Angular.md)
- [Svelte](/docs/CS/front-end/Svelte.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)

## References

1. [React 官方文档](https://react.dev/)
2. [React Versions（版本线）](https://react.dev/versions)
3. [React v19 发布说明](https://react.dev/blog/2024/12/05/react-19)
