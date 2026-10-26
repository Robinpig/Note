## Introduction

Svelte 是 Rich Harris 2016 年发布的**编译器优先**框架，立场最激进：别的框架把工作量留在运行时（虚拟 DOM diff），Svelte 在编译期就把组件变成直接操作 DOM 的命令式代码——没有虚拟 DOM、没有运行时框架本体，更新粒度由编译器静态算出。Svelte 5（2024-10-19 GA）用 **runes** 重写响应式模型，把依赖改为显式声明。版本基线（2026-10）：**Svelte 5.57.2**；配套全栈框架 **SvelteKit 3.0.0 已于 2026-10-01 GA**（当前 3.1.0）——注意 npm `next` tag 仍指向 3.0.0-next.32，别顺手装 `@next`；脚手架是 `npx sv create`，`npm create svelte` 已废弃且只会打印提示。

## Compiler-First Rendering

传统管线：状态变 → 重跑 render → 生成新 VNode 树 → 新旧 diff → patch DOM。Svelte 的编译器读模板时就知道每个动态表达式对应哪个 DOM 节点，直接生成「把某个文本节点的内容改成新值」这类点对点更新指令，中间四步全部省掉。

```
// 模板：<p>count: {count}</p>
// 编译产物大致相当于：把该文本节点登记为 count 的依赖，
// count 变化时直接 textContent = 新值（真实产物带编译期生成的变量与调度代码）
```

好处：没有 VNode 分配、没有树对比、没有运行时框架代码，包体与更新成本都低；代价是编译器承担全部复杂度，且依赖必须在编译期可分析。

## Runes: Explicit Reactivity

Svelte 4 的响应式是隐式的（`let` 赋值即响应、`$:` 标签声明派生 / 副作用），编译器要猜依赖。Svelte 5 改用编译器可见的 `$` 前缀符号：

| Rune | 用途 |
|------|------|
| `$state(v)` | 声明响应式状态（对象 / 数组走 Proxy） |
| `$derived(expr)` / `$derived.by(fn)` | 派生值 |
| `$effect(fn)` | DOM 更新后运行的副作用，可返回 cleanup（仅浏览器，SSR 不执行） |
| `$props()` | 声明组件入参（替代 `export let`） |
| `$bindable()` | 标记可双向绑定的 prop |
| `$inspect(v)` | 开发期调试日志，生产构建剔除 |
| `$host()` | custom element 宿主访问 |

要点：普通 `let` 不再有响应性——只跟踪显式标记的；runes 可在 `.svelte.js` / `.svelte.ts` 模块里复用（文件后缀必须精确，否则编译报错）；**snippets**（`{#snippet}` + `{@render}`）取代 slot，是带参数的函数式代码块。Svelte 4 组件以 legacy 模式继续工作，可增量迁移。

## SvelteKit

| 文件 | 作用 |
|------|------|
| `+page.svelte` / `+layout.svelte` | 页面与布局 |
| `+page.server.ts` | 服务端 load（取数、鉴权） |
| `+server.ts` | REST 端点 |
| form actions | 服务端表单处理，渐进增强——禁用 JS 也能提交 |

部署用 adapter 切换目标平台（静态站点 / Node 服务器 / 边缘运行时），不锁死运行时。

## Links

- [React](/docs/CS/front-end/React.md)
- [Vue](/docs/CS/front-end/Vue.md)
- [Angular](/docs/CS/front-end/Angular.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [Webpack](/docs/CS/front-end/Webpack.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)

## References

1. [Svelte 官方文档 - What are runes?](https://svelte.dev/docs/svelte/what-are-runes)
2. [SvelteKit 文档](https://svelte.dev/docs/kit/introduction)
