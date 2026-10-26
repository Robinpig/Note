## Introduction

Angular 是 Google 的 TypeScript 优先**全功能框架**：2010 年的 AngularJS 开了前端框架化先河，2016 年 Angular 2 用 TypeScript 彻底重写，此后形成「路由、DI、表单、HTTP、测试、CLI 全家桶」的形态——立场强、上手重，但大团队长期维护的项目恰好需要这种强约束。版本基线（2026-10）：当前主版本 **Angular 22**（2026-06-03 发布，npm 22.2.3），v21 处于 LTS（支持至 2027-06）；自 v22 起发布节奏改为一年一个大版本，每个大版本约 24 个月支持（12 个月活跃 + 12 个月 LTS）。

## From Zone.js to Signals: How Angular Knows to Update

Angular 的变更检测历史上依赖 zone.js：它 monkey-patch 浏览器的 setTimeout / Promise / addEventListener / XHR / fetch，任何异步操作结束时通知 Angular 检查组件树。问题是 zone.js 无法判断回调是否真的改过状态——canvas 上的一次 mousemove 也可能触发全页绑定检查，于是 OnPush、`runOutsideAngular`、手动 `detectChanges` 成了性能优化三件套。

信号（signals）把根因解决掉：

| API | 语义 |
|-----|------|
| `signal(v)` | 可写信号，值变化时通知读取者 |
| `computed(fn)` | 派生信号，依赖脏了标记、读取时重算 |
| `effect(fn)` | 副作用 |

组件只登记「我读过哪些信号」，信号变化时只调度真正依赖它的视图。时间线：v17 信号稳定（signal inputs / outputs / queries 自 v19 稳定）→ v18 实验 zoneless → v20.2 zoneless stable → v21 新项目默认不打包 zone.js → v22 默认 OnPush。迁移顺序是先把状态搬进信号、再删 zone.js；真实风险是「信号外变化 + markForCheck 缺失」导致的静默不刷新，必须测试验证。

## Architecture

- **编译**：Ivy（v9 起默认渲染器）把模板 AOT 编译成指令代码，产物可 tree-shake、可做模板类型检查；
- **组件模型**：v17 起 standalone 成为 CLI 默认、v19 起全面默认，不再需要 NgModule 声明依赖；v22 起 selectorless 稳定，组件可直接 import 进模板；
- **模板控制流**：v17 起 `@if` / `@for` / `@defer` 内置块取代结构化指令；
- **DI**：分层注入器（根 / 平台 / 组件级），单例服务与请求级数据的标准机制，与 NestJS 同源设计——也因此是 TypeScript 传统装饰器的重度用户，迁移口径见[装饰器](/docs/CS/TypeScript/Decorators.md)；
- **表单**：Reactive Forms（RxJS 系）与 Signal Forms 双轨——后者 v21 实验、v22 稳定，纯信号驱动；
- **数据请求**：`HttpClient` 返回 Observable，`toSignal()` 转信号；v22 起 `httpResource` / `rxResource` 稳定，信号式取数替代常见 RxJS 样板。

## SSR and Hydration

v19 实验、v21 稳定的**增量水合**（incremental hydration）：SSR 的 HTML 先到，关键部分立即 hydrate，其余延迟到交互 / 视口 / 手动触发，模板里用 `@defer (hydrate on viewport)` 直接声明。v21 起支持**路由级渲染模式**（prerender / client / server 按路由配置），不必一个路由一个配置文件。

## Ecosystem and AI Direction

| 层 | 代表 |
|----|------|
| CLI 生态 | Angular CLI（esbuild / Vite 构建） |
| 测试 | Vitest（v21 起默认，取代 Karma） |
| UI | Angular Material、Angular ARIA（v22 起稳定，headless 无障碍原语） |
| 状态 | NgRx signalStore（v18+，zoneless 兼容） |
| 元框架 | Analog |

独特的一条：Angular CLI 内置 **MCP server**（v20.2 起稳定、v21 起默认包含），给 AI 编码 agent 提供权威工具（`find_examples` / `get_best_practices` / `search_documentation`）——框架团队直接下场约束 AI 生成代码的形态，四个框架里它做得最重。

## Links

- [React](/docs/CS/front-end/React.md)
- [Vue](/docs/CS/front-end/Vue.md)
- [Svelte](/docs/CS/front-end/Svelte.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [浏览器原理](/docs/CS/Browser/Browser.md)

## References

1. [Angular 官方文档](https://angular.dev/)
2. [Angular versioning and releases](https://angular.dev/reference/releases)
