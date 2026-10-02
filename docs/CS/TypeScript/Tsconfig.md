## Introduction

`tsconfig.json` 不是一份普通的配置文件，它定义了**一个编译单元（program）的边界**：哪些文件属于这个世界、这些文件用哪套模块语义互相引用、产出的 JS 长什么样、以及哪些事情算错误。理解了它，`"include 多了"、"类型对不上"、"用 esbuild 构建后 behavior 变了"` 这类问题才有根子可寻。

TS 7 之后 `strict` 成了默认值，`moduleResolution` 的选项空间也重新洗牌，这份笔记按当前时间点的实际状态整理。细节审核请先翻 TS 对应版本的 release notes。

## 文件在哪里：program 的组成

```jsonc
{
  "include": ["src/**/*"],        // glob 纳入
  "exclude": ["src/**/*.test.ts"] // 排除（注意：被 import 的文件仍会被拉进来）
}
```

`excluding` 一个文件不等于它不参与编译——只要被任何纳入的文件 `import` 到，它照样会进 program。`exclude` 只影响 `include` 的 glob 命中范围。

排查手段：

```shell
tsc --explainFiles        # 逐文件说明"因为什么被纳入"
tsc --showConfig          # 打印继承、合并后的最终配置
```

`extends` 支持多级继承（相对路径会被相对于**宿主文件**解析）：

```jsonc
{ "extends": "../../tsconfig.base.json", "compilerOptions": { "rootDir": "./src" } }
```

注意 `"files"` 不参与继承合并，而 `include`/`exclude` 的路径基准是各自所在文件的目录。

## strict 家族：逐项在管什么

TS 7 起 `strict` 默认为开。逐条理解它的组成，才知道升级后满屏报错来自哪一项：

| 选项 | 归属 | 管什么 |
|------|------|--------|
| `strict` | 总开关 | 下面 `strict*` 的全包笔记本式归 Obervation。＝ 下列全部 |
| `noImplicitAny` | strict | 推断不出类型、也没写注解时报错，而不是悄悄退化成 `any` |
| `strictNullChecks` | strict | `null`/`undefined` 不自动并入其他类型——这是收益最大的一项 |
| `strictFunctionTypes` | strict | **函数类型**的参数按逆变检查（方法写法仍是双变） |
| `strictBindCallApply` | strict | `call`/`apply`/`bind` 也参与类型检查 |
| `strictPropertyInitialization` | strict | 构造函数必须为声明的属性赋初值（配合 `strictNullChecks`） |
| `noImplicitThis` | strict | `this` 推断不出来就报错 |
| `alwaysStrict` | strict | 产出 JS 带 `"use strict"` |
| `useUnknownInCatchVariables` | strict | `catch (e)` 里 `e` 是 `unknown` 而非 `any` |

建议另外手动开启的"额外严格项"，它们不在 `strict` 包里，但对 correctness 提升很大：

| 选项 | 管什么 | 为什么值得开 |
|------|--------|-------------|
| `noUncheckedIndexedAccess` | 索引访问的结果多带上 `undefined` | 修掉 `Record<string, T>` 和数组越界的谎言 |
| `exactOptionalPropertyTypes` | 区分"没有这个属性"与"属性值为 undefined" | 修掉 `{ x?: number }` 的歧义 |
| `noImplicitOverride` | 重写父类成员必须写 `override` | 防止改名 / 改签名时静默丢失 |
| `noFallthroughCasesInSwitch` | switch case 穿透到下一个 case 报错 | 兜住最常见的手滑 |
| `noPropertyAccessFromIndexSignature` | 索引签名的成员必须用 `[]` 访问 | 让"哪些 key 是真的"显式起来 |
| `erasableSyntaxOnly` | 禁止 enum / namespace / 参数属性等不可擦除语法 | 让代码能被 type-stripping 工具直接执行 |

最后一条值得多说一句：`erasableSyntaxOnly`（TS 5.8 引入）把"这份代码能否被 Node 直接跑"变成了**可被编译器机械校验**的属性。开了它，`node --experimental-strip-types app.ts` 就能直接执行源码，不需要 `ts-node`、`tsx` 或任何构建步骤。

## 模块：`module` 与 `moduleResolution`

这是实务中踩坑最多的一组。**`module` 决定产出的格式，`moduleResolution` 决定怎么找文件**，两者必须配套。

| `module` | 配套 `moduleResolution` | 场景 |
|----------|------------------------|------|
| `commonjs` | `node10`（旧默认，TS 7 已移除） | 传统 Node CJS |
| `node16`/`nodenext` | `node16`/`nodenext` | 严格遵循 Node 的 ESM/CJS 双模块规则，要求扩展名写全 |
| `esnext` | `bundler` | **前端打包场景推荐**：允许省略扩展名、支持 `import.meta`，不承认 Node 的 `.js` 查找规则 |
| `esnext` | `node16`/`nodenext` | 服务端 ESM |

TS 7 的变化：**`moduleResolution: node10` 已被移除**，`module` 默认变为 `esnext`。如果你之前依赖 node10 的宽松查找（可以省略 `index.js`、`.js` 后缀），升级时要么补全路径，要么切到 `bundler`。

相关开关：

- **`esModuleInterop`**：让 `import fs from "fs"` 在 CJS 互操作时可用（生成 `__importDefault` 辅助代码）。现代项目基本都开着；
- **`allowSyntheticDefaultImports`**：只修类型侧，不改 emit，适用于运行时由打包器负责的场景；
- **`verbatimModuleSyntax`**：类型导入必须写成 `import type`，让删除器能准确判断这条 import 是否该删；
- **`moduleDetection`**：设为 `force` 强制把每个非空文件当作模块（避免误判为全局脚本）；
- **`isolatedModules`**：限制只允许能被逐文件独立编译的写法，是 esbuild/swc 友好的前提。

## `target` 与 `lib`：两件不同的事

初学者最容易混：`target` 管**语法降级**，`lib` 管**可用 API 的类型声明**。

```jsonc
{
  "compilerOptions": {
    "target": "es2020",        // 语法：可选链/?? 是否降级，class 是否降级成 function
    "lib": ["es2020", "dom"],  // 类型：这篇文章允许用 Object.fromEntries、HTMLElement 等
    "downlevelIteration": true // 降级 for..of 遍历迭代器（target < es2015 时需要）
  }
}
```

两个典型坑：

1. `target` 设得很新但运行环境很老 → 语法不兼容运行时直炸，`tsc` 不会提醒；
2. 用了 `Promise.allSettled` 却没把 `es2020` 放进 `lib` → 报"属性不存在"，即使 polyfill 已经进了 bundle。

TS 7 已**移除 ES5 target**；需要 ES5 的链路请保留 6.x 产物。

### 类字段的语义差异：`useDefineForClassFields`

这一项决定了 `class { x = 1 }` 走 `[[Define]]` 还是 `[[Set]]`：

```typescript
class Base { declare x: number }
class Derived extends Base {
  x = 1   // [[Define]]：在子类实例上新定义一份，忽略父级 setter
          // [[Set]]：   走原型链上的 setter
}
```

`target: es2022` 或更高时默认为 `true`（按标准语义用 `[[Define]]`），否则为 `false`。涉及到继承 + 属性装饰器的老代码在这两个模式下行为不同，升级时要格外留意。

## 声明文件：`.d.ts` 这块

| 选项 | 作用 |
|------|------|
| `declaration` | 产出 `.d.ts`；`composite: true` 强制要求开 |
| `declarationMap` | 让编辑器能跳转到 `.ts` 源而非 `.d.ts` |
| `emitDeclarationOnly` | 只产声明、不产 JS，常见于打包器负责 JS 的项目 |
| `skipLibCheck` | 跳过对 `.d.ts` 的检查——**几乎必备的性能开关**，代价是第三方库声明里的问题不会被揪出来 |
| `types` / `typeRoots` | 限制自动引入哪些 `@types` 包 |

第三方没有自带类型时，从社区仓库 DefinitelyTyped 安装：`npm i -D @types/node`。这些包靠 `node_modules/@types` 下的隐式查找被自动纳入；一旦显式写了 `types` 数组，未列出的包就不再自动生效——这是很多人遇到"为什么 @types/node 突然找不到了"的原因。

## 这些选项不影响 emit

理解"只有类型、不留痕迹"的部分，可以避免为了消除报错而误改源码：

`strict*` 家族、`noUncheckedIndexedAccess`、`exactOptionalPropertyTypes`、`skipLibCheck`、`noEmit`、`paths`。

其中 **`paths` 需要 runtime 侧配合**——它只改变类型解析，打包器/Node 并不认：

```jsonc
{
  "compilerOptions": {
    "paths": { "@/*": ["./src/*"] }   // 只影响类型；Vite/webpack/Node 各需配一份 alias
  }
}
```

## monorepo：solution style tsconfig

根配置只做编排，本身不参与编译：

```jsonc
// tsconfig.json
{
  "files": [],
  "references": [
    { "path": "./packages/core" },
    { "path": "./packages/app" }
  ]
}
```

```jsonc
// packages/core/tsconfig.json
{
  "compilerOptions": {
    "composite": true,      // 允许被 reference
    "incremental": true,    // 产出 .tsbuildinfo
    "declaration": true,
    "rootDir": "./src",
    "outDir": "./dist"
  }
}
```

构建用 `tsc --build`（TS 7 下再用 `--builders` 让它并行）。引用方读的是被引用方的 `.d.ts`，因此 IDE 不必为了补全去重新解析整棵依赖树。详见 [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)。

## 性能与排障

| 手段 | 命令 | 用途 |
|------|------|------|
| 阶段耗时统计 | `tsc --extendedDiagnostics` | 判断时间花在 parse / bind / check / emit 哪一步 |
| 精简版诊断 | `tsc --diagnostics` | 同上，输出更短 |
| 文件纳入原因 | `tsc --explainFiles` | 揪出被意外纳入的巨大目录 |
| 模块解析路径 | `tsc --traceResolution` | 排查"为什么找不到这个模块" |
| 跳过库检查 | `skipLibCheck: true` | 通常立竿见影地省下 30~50% 时间 |
| 增量 | `incremental: true` | 复用上次结果（`.tsbuildinfo`） |
| 并行（TS 7） | `tsc --checkers 8` | 大仓库提升到 16× 级 |

一份面向新项目的推荐基线：

```jsonc
{
  "compilerOptions": {
    "target": "es2022",
    "lib": ["es2022"],
    "module": "esnext",
    "moduleResolution": "bundler",
    "moduleDetection": "force",
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "erasableSyntaxOnly": true,

    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,

    "declaration": true,
    "incremental": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src/**/*"]
}
```

服务端 Node 项目把 `module`/`moduleResolution` 换成 `nodenext`，并去掉 `erasableSyntaxOnly`（除非确实要在 Node 22+ 下直接跑源码）。

## Links

- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)
- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [Webpack](/docs/CS/front-end/Webpack.md)

## References

- [TSConfig 参考（逐选项）](https://www.typescriptlang.org/tsconfig)
- [What is a tsconfig.json](https://www.typescriptlang.org/docs/handbook/tsconfig-json.html)
- [TypeScript: Project References](https://www.typescriptlang.org/docs/handbook/project-references.html)
- [TypeScript: Modules - Reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html)
- [TypeScript Handbook: Classes](https://www.typescriptlang.org/docs/handbook/2/classes.html)
