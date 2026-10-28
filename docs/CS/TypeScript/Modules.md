## Introduction

TypeScript 自己**不定义任何模块语义**——`import`/`export` 最终跑成什么行为，由三个世界分别决定：Node 的 ESM/CJS 双模块规则、打包器的宽松解析、以及 TS 在类型层对这两套规则的复刻。日常遇到的 "Vite 里好的、Node 里炸"、"打包产物在 ESM 宿主下报错"，几乎都是这三个世界的规则差异造成的。本篇把三者的边界讲清，模块相关的 tsconfig 选项（`module`、`moduleResolution`）本身在 [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)，这里讲它们背后的语义。

## Node's Dual Module World

Node 同时存在两套模块系统，一个文件属于哪套由下面三条规则机械判定：

| 文件 | 模块系统 |
|------|----------|
| `*.mjs` / `*.mts` | 永远 ESM |
| `*.cjs` / `*.cts` | 永远 CJS |
| `*.js` / `*.ts` | 看**最近祖先目录** `package.json` 的 `type` 字段：`"module"` → ESM，否则（含没有 `package.json`）→ CJS |

TypeScript 把这套规则原样搬到了 `.mts`/`.cts`/`.ts` 上。这就是为什么一个 `package.json` 没写 `type` 的仓库里，`.ts` 文件默认按 CJS 编译，而加上 `"type": "module"` 之后同样的代码会报 `require` 不存在——不是代码变了，是判定规则翻了。

两套系统的能力差异是硬边界：

| 能力 | ESM | CJS |
|------|-----|-----|
| `import` / `export` | 是 | 否 |
| `require` | 否（需 `createRequire`） | 是 |
| `__dirname` / `__filename` | 否（需自行构造） | 是 |
| top-level `await` | 是 | 否 |
| 静态分析友好度 | 高（导入导出在词法层） | 低（动态 `require`） |

## Conditional Exports

Node 按 `package.json` 的 `exports` 字段决定外部能 import 到什么，条件（conditions）**按数组顺序逐个匹配**，命中即停：

```jsonc
{
  "name": "mylib",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",     // 类型条件：必须排在前面
      "import": "./dist/index.mjs",     // ESM 消费者
      "require": "./dist/index.cjs"     // CJS 消费者
    }
  }
}
```

要点：

- **`types` 条件的排序至关重要**。TS 和编辑器解析类型时按同一套顺序匹配，`types` 不放在 `import`/`require` 之前，ESM 消费方会解析不到正确的声明文件；
- 运行时可用 `node --conditions=custom ./app.mjs` 注入自定义条件， monorepo 里指向 `development` 源码条件是常见手法；
- `imports` 字段（`#` 前缀）是包内自引用，可以配 `"#internal/*"` 替代深层相对路径，且**不需要 `paths` 那样的类型侧补配**；
- `exports` 一旦出现就是硬边界：未列出的子路径（哪怕文件真实存在）外部一律访问不到。给旧用户留后路通常要显式加一条 `"./legacy/*": "./legacy/*"`。

## Resolution Modes and Extension Rules

TS 用 `moduleResolution` 复刻不同宿主世界的查找规则。三者的差异集中在"要不要写扩展名"上：

| 模式 | 扩展名要求 | 目录导入 | 适用 |
|------|-----------|---------|------|
| `node16` / `nodenext` | **必须写全**（`./foo.js`，即使源码是 `foo.ts`） | 不认 `index` 省略 | 发布库、服务端 ESM |
| `bundler` | 允许省略（`./foo`） | 认 `./foo/index.ts` | 前端应用 |
| `node10` | 宽松 | 宽松 | **TS 7 已移除** |

`nodenext` 下写 `import { x } from "./foo.js"` 而磁盘上是 `foo.ts` 不是笔误：TS 规定**扩展名指向编译产物**，编译前把 `.js` 映射回 `.ts`/`.d.ts` 去找源。这个规则让源码可以直接被 Node 执行（Node 22.6+ 的 type stripping 同样按产物名查找），是 ESM 直连设计的一部分。

选型原则只有一条：**给别人消费的代码用 `nodenext`，自己的应用用 `bundler`**。前者严格是为了产出可被任何宿主正确解析的包，后者宽松是因为最终产物只有一个打包器说了算。

## Interop Traps

跨模块系统交互时踩坑最密集的区域，按出现频率排：

| 坑 | 现象 | 正解 |
|----|------|------|
| CJS 的 default import | `import express from "express"` 时有时无 | 靠 `esModuleInterop` 生成 `__importDefault` 辅助函数；CJS 模块若设了 `module.exports.default` 会拿到"默认里的默认"，要用 `import * as` 或库的双包导出 |
| ESM 里 `require` CJS 的命名导出 | 打包器好好的，Node 直跑报 "does not provide an export named" | Node 靠 **cjs-module-lexer** 静态分析 CJS 的命名导出，`module.exports = { ... }` 简单字面量能分析，条件拼接的分析不出；ESM 消费 CJS 优先用 default import |
| `__dirname` 不见了 | ESM 下 ReferenceError | `import.meta.url` + `fileURLToPath` 自行构造 |
| JSON 导入 | 写法在 Node 与打包器间不一致 | ESM 用 `with { type: "json" }` import attributes；CJS 保持 `require` |
| top-level `await` | 加到 CJS 文件里编译报错 | TLA 只属于 ESM；拆成 async main 或切模块系统 |
| 双包陷阱（dual package hazard） | 同一个库的 ESM/CJS 两份实例，`instanceof` 失效、单例 duplicated | 库发布时保证 ESM 是 CJS 的包装而非平行实现，或让状态外置 |

`__dirname` 的替换是标准三行：

```typescript
import { fileURLToPath } from "node:url"
import { dirname } from "node:path"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
```

## Type-Only Imports and Erasure Safety

类型在编译后被擦除，于是"这条 import 该不该删"必须让删除器（esbuild/swc/Node stripper）能机械判断：

```typescript
import type { User } from "./types"          // 纯类型，必须删
import { type Config, loadConfig } from "./config"  // 内联混写，删类型留值
```

两条 tsconfig 开关与它配套，语义见 [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)：

- **`verbatimModuleSyntax`**：强制类型导入必须显式 `import type`，输出保持写法原样。开了它，删除器不需要做任何推断；
- **`isolatedModules`**：限制只允许能单文件编译的写法——`export { SomeType }` 这种"值还是类型"跨文件才能断言的 re-export 会被要求改成 `export type { SomeType }`。

一个高频坑是**从类型文件 re-export**：

```typescript
// types.ts 里全是 interface / type
export { User, Order } from "./types"        // ✗ 删除器不知道这是类型
export type { User, Order } from "./types"   // ✓ 明确删除
```

## Bundlers Rewrite the Rules

打包器解析模块时**不严格遵守 Node 规则**：允许省略扩展名、允许目录导入、`package.json` 的 `type` 只作参考。差异本身就是坑：

| 维度 | Node（nodenext） | 打包器（bundler 模式） |
|------|------------------|------------------------|
| 扩展名 | 必须写全 | 可省略 |
| 目录 index | 不解析 | 解析 |
| `package.json` 条件 | 严格按顺序 | 按 targets 与自定义条件 |
| 条件导出的 types 位置 | 敏感 | 多数情况也敏感（编辑器走 TS 解析） |

tree shaking 则完全是打包器世界的规则：它依赖 ESM 的静态结构，`sideEffects: false` 是库作者的声明承诺，配错了会把有副作用的模块（CSS、polyfill、注册逻辑）整块摇掉。`"use strict"` 时代的 UMD 打包之所以被淘汰，也是因为静态分析不出它的导出。

对应用代码的实操结论：**`moduleDetection: "force"`**（每个非空文件都当模块）值得默认开启，避免"忘了写 export 的脚本文件被当成全局脚本"这类边界 bug。

## Aliases at Runtime

`tsconfig.json` 的 `paths` 只改**类型解析**，运行时一概不认。要让 `@/foo` 在 Node 或打包器里也成立，各有各的配法：打包器配 `resolve.alias`，Node 用 `imports` 字段（`#` 前缀）或 exports 子路径，测试 runner 又往往要单独配一份。三处漂移是 `paths` 最常见的故障形态——改动别名时只改 tsconfig，然后测试绿、构建红。

## Links

- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [Webpack](/docs/CS/front-end/Webpack.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)

## References

- [Node.js: Modules - CommonJS modules](https://nodejs.org/api/modules.html)
- [Node.js: ECMAScript modules](https://nodejs.org/api/esm.html)
- [Node.js: Package entry points (exports)](https://nodejs.org/api/packages.html#exports)
- [TypeScript Handbook: Modules - Reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html)
- [TypeScript: Module resolution reference](https://www.typescriptlang.org/docs/handbook/modules/theory.html)
- [Dual package hazard](https://nodejs.org/api/packages.html#dual-commonjses-module-packages)
