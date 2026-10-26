## Introduction

TypeScript 没有官方全家桶，工具链按职责拆成几层各自选型：**类型检查**（`tsc`）、**转译产出**（esbuild / swc / Vite）、**lint**（typescript-eslint / Biome / Oxlint）、**测试**（vitest / jest）、**运行时直跑**（Node type stripping / Deno / Bun）。TS 7.0 把原生编译器做到 8~12 倍提速之后，"用 esbuild 换速度、再单独跑 tsc 补检查"这个流行数年的分工有了松动，但**插件生态的断层**（7.0 无稳定编程式 API）又让旧分工继续有效。本篇按层盘点 2026 年 10 月的实际格局。

## The Division of Labor

| 层 | 工具 | 是否检查类型 | 速度 | 角色 |
|----|------|-------------|------|------|
| 检查 | `tsc`（TS 7 原生） | **是** | 中~快 | 正确性权威 |
| 转译 | esbuild / swc | 否 | 极快 | dev server、产出 |
| 转译 | Vite | 否（dev 走 esbuild） | 极快 | 前端开发服务器与构建 |
| Lint | Biome / Oxlint | 否（有限规则） | 极快 | Rust 实现，毫秒级 |
| Lint | typescript-eslint | 部分（type-aware 规则） | 慢 | 需要类型信息的规则 |
| 直跑 | Node 22.18+ / Deno / Bun | 否 | 快 | 无构建步骤执行 |

TS 7 的意义不是取代 esbuild，而是**把检查变得足够便宜**，使"全量 tsc 进 CI"从奢侈变默认。esbuild 的不可替代性在转译吞吐（极速 watch）与语言覆盖（不止 TS）上，不在检查。

## Lint: Three Camps

**typescript-eslint** 是类型感知规则的事实标准，`no-floating-promises`、`no-misused-promises`、`await-thenable` 这类规则靠 `parserOptions.project` 把 tsconfig 喂给 parser 才能工作——代价是每个 lint 目标文件都要过一次类型检查，大仓库里它经常是最慢的 CI 作业。

TS 7.0 发布时它被卡住了：peer 依赖上限 `<6.1.0`，与 `typescript@7` 并存会直接 **ERESOLVE**；type-aware 规则与模板检查（Vue / Svelte / Astro / MDX / Angular）都等 **7.1 的稳定编程式 API**（Content Mapper / Emit / Language Service API，beta 已于 2026-10-20 发布，stable 计划 2026-11）。迁移期的标准姿势是 npm alias 双装：

```jsonc
{
  "devDependencies": {
    "typescript": "^7.0.0",                        // 原生 tsc，负责检查
    "@typescript/typescript6": "npm:typescript@^6.0.0"   // 6.0 API，喂给 ESLint 生态
  },
  "scripts": {
    "typecheck": "tsc --noEmit",                   // 快跑
    "lint": "eslint --max-warnings 0 ."            // 走 6.0 API
  }
}
```

**Biome** 用 Rust 把 linter + formatter 合成一个二进制，配置一张表，速度是数量级差距；但它**没有类型信息**，`no-floating-promises` 一类规则做不了或只能做保守近似。适合规则集与 prettier 兼容、且不强依赖 type-aware 规则的项目。

**Oxlint** 同样 Rust 出身、兼容 ESLint 配置迁移；它的 `tsgolint` 变体把类型感知检查接给了**原生编译器**，是目前唯一在 TS 7 语境下能做类型感知 lint 的路线——生态成熟度仍在快速演进，采用前建议在自己的仓库上实测规则覆盖面。

## Type Testing

类型是编译期构造，单元测试碰不到它。测试类型本身有三个层次的手段：

| 手段 | 写法 | 用途 |
|------|------|------|
| `expectTypeOf` / `assertType` | `expectTypeOf(fn).parameters.toEqualTypeOf<[string]>()`（vitest 内置） | 断言类型精确相等，写进测试文件 |
| `@ts-expect-error` | 标注"这行必须报错"，不报错反而编译失败 | 锁住库的拒绝行为 |
| `tsd` / `dtslint` | 独立的 `.test-d.ts` 文件 | 发布库的类型契约回归 |

原则与运行时测试一致：**断言公共 API 的类型形状，不要给内部实现写类型测试**——后者维护成本高、信息量低。

## CI Strategy: Dual-Track During the 7.x Transition

7.0 与 7.1 之间的窗口期，被验证过的组合是**双轨制**：

1. **权威轨**：`tsc6 --noEmit`（经 `@typescript/typescript6` alias）继续当门禁，ESLint / ts-jest / 框架模板检查都挂在这条线上；
2. **快速轨**：`tsc --noEmit`（TS 7 原生）以**非阻塞**作业并行跑，记录耗时与诊断差异；差异收敛后再把权威轨切过去。

配合 `--explainFiles`、`--extendedDiagnostics`（耗时分布）与 `npm ls typescript`（查谁在 import 编译器 API）三个排查入口。判断能否切轨的标准很直接：仓库里没有任何工具 `import ... from "typescript"`，且 7.1 stable 已发布、你的插件都在支持列表里。

## Running TypeScript Without a Build Step

Node 的类型擦除直跑时间线：

| 版本 | 事件 |
|------|------|
| 22.6.0 | `--experimental-strip-types`，只删类型 |
| 22.7.0 | `--experimental-transform-types`，可处理 enum / namespace 等需转换语法 |
| 23.6.0 | type stripping **默认开启**（unflag） |
| 22.18.0 | 默认开启**回移**到 22.x LTS 线 |

```bash
node app.ts                                # 22.18+ / 24 LTS 直接跑
node --no-experimental-strip-types app.ts  # 显式关掉
node --experimental-transform-types app.ts # enum/namespace 等仍需 flag
```

三个必须知道的事实：

- 底层是 **Amaro**（swc 的 WASM 封装）loader，**不读 `tsconfig.json`**——编辑器与 tsc 的行为要单独对齐；
- **不做任何类型检查**，它只是删类型；`tsc --noEmit` 该跑还得跑；
- 想让"可直跑"成为可机械校验的属性，tsconfig 开 **`erasableSyntaxOnly`**（TS 5.8），编译器会拒绝 enum / namespace / 参数属性这些擦不掉的语法。

Deno 与 Bun 各自内置转译器，同样只转译不检查，另需 `deno check` 补正确性。

## Version Pinning in the Transition

| 包 | 是什么 | 该不该进依赖 |
|----|--------|-------------|
| `typescript@7` | 稳定原生编译器（`tsc` 即原生二进制） | 是 |
| `typescript@next` | 7.1 开发线 nightly | 想跟踪 7.1 才装，接受漂移 |
| `@typescript/native-preview` | 预览期 nightly 包（`tsgo`），日期化 dev 版本 | **否**，随天变动，勿锁进生产依赖 |
| `@typescript/typescript6` | 6.0 兼容包，导出 `tsc6` 与 6.0 API | 插件生态就绪前的过渡依赖 |

结论：过渡期的 package.json 里，检查权威归 6（alias 安装），速度实验归 7，7.1 stable 落地且插件迁移完成后，删掉 alias 行。

## Links

- [TypeScript 编译器](/docs/CS/TypeScript/Compiler.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)
- [TypeScript 模块系统](/docs/CS/TypeScript/Modules.md)

## References

- [Node.js: Running TypeScript natively](https://nodejs.org/api/typescript.html)
- [Node.js 23.6.0 release (unflagging strip-types)](https://nodejs.org/en/blog/release/v23.6.0)
- [typescript-eslint](https://typescript-eslint.io/)
- [Biome](https://biomejs.dev/)
- [Oxc / Oxlint](https://oxc.rs/)
- [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
