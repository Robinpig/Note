## Introduction

Vue 是 Evan You 2014 年发布的**渐进式框架**：可以只当视图库用在一个页面上，也可以配上官方路由、状态管理、构建工具长成完整应用。技术立场与 React 相反——React 用 JS 描述 UI，Vue 用**模板 + 编译器**把声明式模板变成渲染函数，再叠加一套基于 Proxy 的细粒度响应式系统。版本基线（2026-10）：稳定线 **3.5.x**（npm latest 3.5.44），**3.6 仍处 RC**（3.6.0-rc.13，未公布稳定日期）；Vue 4.0 开发已宣布启动，API 基本沿用 3.x，不会重演 2→3 的断崖式断裂。

## Reactivity: Proxy-based Dependency Tracking

Vue 3 重写响应式内核，对外只有三个原语：

| API | 语义 |
|-----|------|
| `ref(x)` | 包装任意值为响应式（对象走深层 `reactive` 代理） |
| `reactive(obj)` | 对象的深层 Proxy 代理 |
| `computed(fn)` | 惰性计算值，依赖变化才重算 |

原理是**依赖收集**：effect（渲染函数、watch、computed）执行时读取响应式属性，`track` 把「这个 effect 依赖这个属性」登记下来；属性被写时 `trigger` 通知相关 effect 入队，调度器去重后批量刷新。更新因此天然细粒度——只有真正读取了变化属性的视图会重渲染，不需要手写 memo 比较函数。

3.6 起内核换成 **alien-signals**（push-pull 算法）：状态变化时只把依赖的 computed 标记为脏，真正读取时才重算，避免「先全算一遍再决定用哪个」的浪费。不启用 Vapor 的普通组件升级即受益。

## Template Compiler

模板不是解释执行的，而是编译为渲染函数。编译期做三件事：**静态提升**（不变的节点提为常量）、**patchFlags**（标记哪些是动态绑定）、**block tree**（收集动态后代，把 diff 范围缩到最小）。运行时只需要对比「可能变的部分」——这是用编译期优化替代手工记忆化的路线，与 Svelte 同门，与 React Compiler 殊途同归。

单文件组件 `.vue` 把 template / script / style 收进一个文件，`<script setup>` 是组合式 API 的默认入口，`scoped` 样式自动加属性选择器。

## Vapor Mode: Compiling Away the VDOM

3.6 最重要的实验特性是 **Vapor Mode**——一种可选编译模式，跳过虚拟 DOM：编译期把每个动态表达式映射到对应 DOM 节点，生成点对点更新指令，运行时不分配 VNode、不树对比、不打补丁。

- 单组件启用：`<script setup vapor>`；全 VDOM 应用里混用靠 `vaporInteropPlugin`（props / events / slots 互通，官方建议两种模式各占树的独立区域，不要来回嵌套）；
- 全新应用用 `createVaporApp()` 引导，VDOM 运行时可被整体 tree-shake，官方给出的 Vapor 基线包在 10KB 以下；
- 当前边界：不支持 Options API，`getCurrentInstance()` 返回 null，部分 `$el` / `$refs` 不可用，**Suspense 尚未支持**（团队称除此以外 feature-complete）；Nuxt 4.6+ 可在 nuxt.config 开 `vue: { vapor: true }` 走 interop；
- 适用面：大列表、仪表盘、编辑器这类高频细粒度更新场景；表单和内容页收益有限，不要为改而改。

## Composition API vs Options API

| | Composition API | Options API |
|--|-----------------|-------------|
| 组织单位 | 功能（一个 setup 里聚合相关逻辑） | 选项（data / methods / computed 分散） |
| 类型推断 | 好（`<script setup>` 可直接推 refs） | 弱（this 上无类型） |
| 逻辑复用 | 组合函数（hook 式） | mixin（命名空间冲突、来源不清） |
| 适用 | 新代码默认 | 存量代码与简单页面 |

## Ecosystem

| 层 | 代表 |
|----|------|
| 路由 | Vue Router |
| 状态 | Pinia |
| 元框架 | Nuxt 4 |
| 构建 | Vite（Evan You 作品，dev 走原生 ESM） |
| 工具库 | VueUse、Volar（IDE 语言支持） |

## Links

- [React](/docs/CS/front-end/React.md)
- [Angular](/docs/CS/front-end/Angular.md)
- [Svelte](/docs/CS/front-end/Svelte.md)
- [Webpack](/docs/CS/front-end/Webpack.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)

## References

1. [Vue 官方文档](https://vuejs.org/guide/introduction.html)
2. [vuejs/core releases](https://github.com/vuejs/core/releases)
