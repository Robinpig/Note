## Introduction

`interface` 与 `type` 在运行时不存在，那编辑器怎么知道 `express` 有哪些方法、`process.env` 是什么类型？答案是**声明文件（`.d.ts`）**——一层纯编译期的描述，把 JS 世界的形状写给类型检查器听。`.d.ts` 是 TS 与整个 JS 生态之间的接口层：库自带一份，没有的从 DefinitelyTyped 装 `@types/*`，都没有就自己写。理解这一层的来源、查找规则与生成方式，"这个类型从哪来的"和"怎么给老库补类型"两个问题才有答案。

## Ambient Declarations

`declare` 关键字声明一个"编译期存在、运行时不碰"的实体：

```typescript
declare const VERSION: string          // 构建时注入的全局常量
declare function ga(...args: unknown[]): void   // 页面里第三方脚本挂的全局函数
declare class LegacyWidget {           // 无类型的第三方 UMD 库
  render(el: HTMLElement): void
}
```

一条容易忽视的规则：**文件里有任何一个顶层 `import`/`export`，它就是模块**，其中的 `declare` 只在本模块可见；要往全局作用域注入，必须显式写 `declare global`：

```typescript
export {}                        // 把文件标记为模块
declare global {
  interface Window { __APP_VERSION__: string }
}
```

跨文件共享声明用**三斜线指令**，它是编译期的文件包含关系，与运行时的 import 无关：

```typescript
/// <reference types="node" />        // 引入 @types/node 的全局声明
/// <reference path="./legacy.d.ts" />
```

三斜线只在"没有模块系统的全局脚本"场景必要，模块代码里应该用 `import`。

## Declaration Merging

同名声明会被编译器**合并**而不是覆盖，这是 TS 独有的扩展机制：

| 组合 | 效果 | 典型用途 |
|------|------|----------|
| interface + interface | 成员联合，同名成员类型必须兼容 | 给第三方接口补字段 |
| namespace + function | 函数挂上静态命名空间 | `declare function jQuery(...)` + `declare namespace jQuery { ... }` |
| namespace + class | 类挂静态成员与类型 | 库的实例侧/静态侧分离 |
| namespace + enum | 枚举挂辅助函数 | 给枚举加命名空间工具 |
| class + interface | 接口声明实例侧额外成员 | 声明文件的惯用拆分 |

实际最常见的是**模块增强（module augmentation）**——给已安装的类型包补字段而不 fork 它：

```typescript
// 给 Express 的 Request 加一个自定义字段
import "express"

declare module "express" {
  interface Request {
    requestId?: string
  }
}
```

注意 augmentation 必须写在**模块文件**里（有 import/export），且 `declare module "express"` 的路径要与解析到的声明一致；写错了不会有任何报错，只是静默不生效——这是它最隐蔽的地方。

## @types and DefinitelyTyped

没有自带类型的库，类型从 `node_modules/@types` 下的**社区包**来：

- `@types/node`、`@types/react` 这些包的大版本**跟随对应库的版本行**，装错大版本是"莫名缺类型/多错误"的高频原因；
- 包的类型**自动全局引入**（任何文件不 import 就能用 `process`、`console`）；一旦 tsconfig 显式写了 `types: ["node"]` 白名单，未列出的 `@types/*` 全部失效——"升级后全局类型全丢"类问题的标准嫌疑人；
- 库**自带类型优先于** `@types` 同名包：`package.json` 的 `types`/`typings` 字段或 `exports` 的 `types` 条件指向的声明胜出，`@types` 同名包会被忽略。同时装两者是经典困惑源；
- 类型与实现版本错配时，先核 `npm ls <lib> @types/<lib>` 两条线，再考虑 `skipLibCheck` 掩盖（见下，那是性能开关不是修复）。

## The lib Family

`lib` 决定**全局 API 的类型面**（`Promise`、`Map`、`fetch`、`HTMLElement`……），与管语法降级的 `target` 是两件事，细节见 [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)。两个实务点：

- **服务端项目要显式排除 `dom`**。默认 `lib` 由 target 推导时会把 DOM 拉进来，`window`、`document` 在类型层可用，运行时（Node）却没有——这类错误只有部署后才炸。库与 CLI 工具建议 `lib: ["es2022"]` 写死；
- **`skipLibCheck` 几乎必备**：跳过对 `node_modules` 里所有 `.d.ts` 的检查，通常省 30~50% 编译时间。代价是第三方声明文件自身的错误不再被揪出——对应用项目这是划算交易，对**要发布声明文件的库**则应该关掉，保证自己的声明是干净的。

## Writing d.ts for an Untyped Library

给没有类型的老库补声明，按代价从低到高三条路：

1. **`declare module` 兜底**——先用 `any` 形状让它过编译，留 TODO 编号跟踪：

```typescript
declare module "legacy-tracker" {
  const tracker: {
    track(event: string, payload?: Record<string, unknown>): void
  }
  export default tracker
}
```

2. **wildcard 模块声明**——给非代码资源（打包器负责转换的 CSS/SVG/图片）统一补类型：

```typescript
declare module "*.css" {
  const css: string
  export default css
}
```

3. **精确手写**——只对核心依赖值得。写好之后优先 upstream 提 PR 给库仓库，其次 DefinitelyTyped，最后留在自己仓库。

判断标准：这个库的 API 会不会经常变？变得频繁就值得精确写；一次性脚本 `declare module` 兜底足够。

## isolatedDeclarations and Emit at Scale

TS 5.5 引入 **`isolatedDeclarations`**：要求每个导出的函数/方法有**显式返回类型**等一组约束，使 `.d.ts` 可以被**单文件独立生成**。它的动机与 TS 7 直接相关——原生编译器的并行 emit 与多语言 emit 工具（esbuild/swc 的 d.ts 插件）都需要"不读别的文件就能产出声明"。

对使用者的实际影响：开启后 `export const x = 1` 不够，要写 `export const x: number = 1`；函数必须显式标注返回类型。对纯内部代码是噪音，对**发布库**是让下游工具链兼容的保险。

产出侧的常见组合：`emitDeclarationOnly` + `declarationMap`（库把 JS 交给打包器，把 `.d.ts` 交给 tsc），以及用 **api-extractor** / **rollup-plugin-dts** / **tsdown** 把散落的 `.d.ts` 收拢成单文件入口。

发布前的最后一道关是 **publint** 与 **@arethetypeswrong**（attw）：它们静态检查一个包的 `exports` 条件、`types` 位置、ESM/CJS 解析结果是否正确，能在"本地好好的、用户装上报类型错"之前发现问题。

## Links

- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [TypeScript 模块系统](/docs/CS/TypeScript/Modules.md)

## References

- [TypeScript Handbook: Declaration Files](https://www.typescriptlang.org/docs/handbook/declaration-files/introduction.html)
- [TypeScript Handbook: Declaration Merging](https://www.typescriptlang.org/docs/handbook/declaration-merging.html)
- [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped)
- [Announcing TypeScript 5.5](https://devblogs.microsoft.com/typescript/announcing-typescript-5-5/)
- [Are the types wrong? (attw)](https://arethetypeswrong.github.io/)
- [Node.js: Modules - Packages](https://nodejs.org/api/packages.html)
