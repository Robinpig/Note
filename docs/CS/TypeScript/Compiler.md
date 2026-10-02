## Introduction

TypeScript 编译器（`tsc`）不是一个传统意义上的"编译到机器码"的编译器，而是一个**静态类型检查器 + JS 转译器**。它的输入是一组文件，输出通常是另一组 JS 文件（外加可选的 `.d.ts` 声明），中间所有的类型信息在 emit 时被丢弃。理解这条管线，是判断"这个报错为什么会出现"、"这次为什么这么慢"、"能不能用 esbuild 替掉"的前提。

2026 年这块发生了十四年来最大的变化：编译器主体从自托管的 TypeScript 移植成了 **Go 原生二进制**（TypeScript 7.0）。本文同时覆盖经典管线与新实现。

## 两代实现

| 代号 | 实现 | 版本范围 | 运行环境 |
|------|------|----------|----------|
| **Strada** | TypeScript 写 TypeScript，编译成 JS | 0.8 ~ 6.x | Node.js / V8 |
| **Corsa** | Go 原生移植 | 7.0 起 | 原生机器码 |

Corsa 是一次**忠实移植（faithful port）**，不是重新设计。团队刻意逐文件复刻原结构，从而保证类型检查逻辑与 6.0 结构相同、语义一致：任何在 6.0 下能干净编译（且无弃用告警）的代码，在 7.0 下产出完全相同的结果。

## 编译管线

```
  ┌──────────────────────────────────────────────────────────────┐
  │  源文件 .ts / .tsx / .js / .d.ts                              │
  └───────────────────────────┬──────────────────────────────────┘
                              ▼
                    Scanner（词法）→ Token 序列
                              ▼
                    Parser（语法）→ AST           ← 容错解析，错了也产出 AST
                              ▼
                    Binder（符号）→ Symbol 表     ← 处理合并声明、作用域
                              ▼
                    Checker（语义）→ 类型与诊断    ← 最贵的一步，惰性求值
                              ▼
                    Transformer（降级）→ 新 AST
                              ▼
                    Emitter（打印）→ .js / .d.ts / .js.map
```

各阶段要点：

- **Program**：整个编译单元，等价于 `Map<Path, SourceFile>` 加上 `CompilerOptions`。`tsconfig.json` 的 `files`/`include`/`references` 决定这张表有多大——每多纳入一个文件，解析与检查的成本都要在里面摊一遍。
- **Scanner / Parser**：解析器是**容错的（error-tolerant）**。这是 IDE 场景的硬需求：你键入 `if (` 的那一瞬间代码不合法，编辑器依然要给出补全和悬浮提示，所以 AST 必须照样生成。
- **Binder**：把 AST 上的名字连到 `Symbol` 对象上，处理**声明合并**（同名 interface 合并、`namespace` 合并等）。
- **Checker**：类型检查的主力，占编译时间的绝大部分。它是**惰性**的——只有在被问到某处的类型时才计算该处的类型，这也是 language service 能局部响应交互的原因。
- **Transformer / Emitter**：按 `target` 做语法降级（箭头函数、class、`??`、可选链），并生成 sourcemap 与声明文件。

一个容易被忽视的事实：**AST 里充满了环**（子节点指回父节点、符号引用回 AST、类型指向声明又指回 AST）。这个性质直接决定了后面选择 Go 而不是 Rust。

## 为什么原先在 Node 上跑不动

Strada 时代三个无法用调参绕开的天花板：

| 天花板 | 说明 |
|--------|------|
| 单线程事件循环 | V8 的事件循环是单线程的，类型检查无法跨文件并行；Node 的 Worker Threads 是共享内存受限的有限并发 |
| JIT 预热 | V8 的 JIT 需要预热才能达到峰值性能，而一次构建往往在达到峰值前就结束了 |
| GC 不匹配 | V8 的 GC 不是为编译器这种"长生命周期、环状、树形"的数据结构设计的——AST + Symbol + Type 三者互指成一张大图 |

Go 一次搬掉三块石头：

- 编译成原生机器码，没有 JIT 预热与 JS 解释开销；
- goroutine 提供真正的**共享内存并行**，多个 worker 可以直接读同一份类型数据，而非 Node worker 那种需要序列化传递的模型；
- Go 的**并发 GC**与应用并行运行，不会长时间 Stop-The-World，天然适配递归、自引用的 AST 图。

### 为什么是 Go 而不是 Rust

这个问题在社区吵了很久。TypeScript 开发负责人 Ryan Cavanaugh 给的理由很具体：**Rust 的所有权模型不允许环形数据结构**，而 TypeScript 的 AST 到处是环。要用 Rust 就得先重新设计编译器的数据模型——那是数年级的工作量，且无法保证语义一致。相比之下 Go 换来的是约一年工期 + 严格等价的语义。

## TypeScript 7.0：性能与并行模型

官方公布的全量构建基准：

| 代码库 | TypeScript 6.0 | TypeScript 7.0 | 提速 |
|--------|---------------|---------------|------|
| VS Code | 125.7 s | 10.6 s | 11.9× |
| Sentry | 139.8 s | 15.7 s | 8.9× |
| Bluesky | 24.3 s | 2.8 s | 8.7× |
| Playwright | 12.8 s | 1.47 s | 8.7× |
| tldraw | 11.2 s | 1.46 s | 7.7× |

峰值内存同步下降：VS Code 5.2 GB → 4.2 GB（−18%）、Bluesky 1.8 GB → 1.3 GB（−26%）、Sentry 4.9 GB → 4.6 GB（−6%）。

编辑器的体感提升比构建更明显：在 VS Code 这份代码库里，打开文件到看到第一条红色波浪线，从约 17.5 s 降到 1.3 s（约 13×）；language server 的命令失败率下降约 80%，崩溃率下降约 60%。Slack 报告 CI 类型检查从约 7.5 分钟降到 1.25 分钟，合并队列时间减少 40%。

### 并行是怎么安排的

三个原本串行的环节被并行化：

- **解析（parsing）与输出（emitting）**：几乎完全可并行，随核数线性扩展；
- **类型检查（type checking）**：复杂得多，因为多个 worker 需要共享来自依赖的类型信息。TS 7 的做法是维护一个**固定大小的 checker worker 池**（默认 4 个），按确定性的方式切分文件集，从而保证输出稳定可复现。

```shell
# 用 8 个类型检查 worker（VS Code 代码库上可达 16.7× 提速）
tsc --checkers 8

# monorepo：并行构建多个 project reference
tsc --build --builders

# 关掉全部并行，用于排查问题或受限的 CI runner
tsc --singleThreaded
```

小项目调大 `--checkers` 通常没有收益——工作量不够分。

### watch 模式换了地基

7.0 的 `--watch` 建立在移植到 Go 的 **Parcel watcher** 之上。原先原生 watcher 依赖 C++ 工具链编译，难以随包分发；换成 Go 之后所有受支持平台都能获得真正的 OS 级文件监听，空闲 CPU 与内存占用低于 6.0 的轮询 + 回退方案。

### 一个真实的类型系统 bug 修复

Go 版遍历字符串按 Unicode code point，而非旧实现的 UTF-16 code unit，修掉了长期存在的代理对被切断的问题：

```typescript
type HeadTail = S extends `${infer Head}${infer Tail}` ? [Head, Tail] : never

// TypeScript 6.0：["\ud83d", "\ude00abc"] —— 半 broken emoji
// TypeScript 7.0：["😀", "abc"]
```

涉及非 BMP 字符（emoji、部分 CJK 扩展区、数学字母符号）的类型层字符串操作，从此行为符合直觉。详见 [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)。

## 升级 7.0 的破坏性变更

| 变更 | 影响 |
|------|------|
| `strict` 成为默认值 | 原本没开 strict 的项目会立刻冒出大量空值与隐式 any 报错 |
| 默认 target / module 变为 `esnext` | 需要显式指定才能维持旧产出形态 |
| 移除 ES5 target | 需要 ES5 兼容的链路暂时不能升 |
| 移除 AMD / UMD / SystemJS 模块格式 | 依赖这些格式的旧构建链要先改造 |
| 移除 `moduleResolution: node10` | 迁移到 `bundler` 或 `nodenext` |
| 6.0 的弃用项升级为硬错误 | 官方建议先在 6.0 下清干净告警 |
| `typescript` 主入口不再导出经典 compiler API | 见下 |

**最后这条是当前唯一的真正阻塞点。** 7.0 发布时**没有稳定的编程式 API**，而 `createProgram`、`ScriptTarget`、`ts` 命名空间这一整套 API，正是 linter、测试 runner、框架模板类型检查器接入 TS 的方式。受影响的工具：

| 工具 | 状态 |
|------|------|
| typescript-eslint | 发布当日尚未支持，支持上限暂止于 6.x |
| ts-jest、ts-morph | 等待 7.1 |
| Vue / Volar、Svelte、Astro、MDX、Angular 模板检查 | 等待 7.1 |
| 依赖 compiler API 的 webpack loader | 等待 7.1 |

过渡手段是官方的兼容包 `@typescript/typescript6`：它提供 `tsc6` 可执行文件并重新导出 6.0 的 API，可以 npm alias 方式与 TS 7 并存。团队给出的目标是在 **7.1（2026 年 11 月左右）**补齐稳定 API。

> [!TIP]
> 迁移路径推荐：先在 6.0 下清理告警（开启 `stableTypeOrdering`、去掉 `ignoreDeprecations`）→ 装 TS 7 只做 `--noEmit` 检查对比 → 确认上下游工具就绪后再切换 emit。

## tsc 与那些"只删类型"的工具

工程上最容易混淆的一组概念：

| 工具 | 是否做类型检查 | 速度 | 典型用处 |
|------|--------------|------|----------|
| `tsc` | **是**，全量 | 慢（6.0）/ 快（7.0） | 正确性把关、产出 `.d.ts` |
| esbuild / swc | 否，只 transform | 极快 | dev server、构建产出 |
| Vite | 否（dev 走 esbuild） | 极快 | 前端 dev/build |
| Biome / Oxlint | 否 | 极快 | lint / format |
| tsx / ts-node | 否（或不完整） | 快 | 直接执行 TS |

TS 7 出现前，社区的常规做法就是"**用 esbuild 换速度，丢掉检查，再单独跑 `tsc --noEmit`**"。TS 7 的意义在于：**保留完整类型检查的同时，把速度差距补上了**。这也是它区别于 esbuild 那类工具的核心——后者是帮你跳过检查，前者是让检查变得足够便宜。

为了让代码对"只删类型"的工具链友好，有两个 tsconfig 选项直接相关：

- `isolatedModules`：强制每个文件可以被**独立**编译——因为 esbuild/swc 是逐文件处理的，没有跨文件的类型信息，`.d.ts` 里写了但实际不存在的值会哑火；
- `verbatimModuleSyntax`：类型导入必须显式写 `import type`，让删除器能准确判断这条 import 该不该删（`importsNotUsedAsValues` 的继任者）。

## 增量化：tsbuildinfo 与 project references

即使有 TS 7 的原生速度，增量依然是大型仓库的必选项。

```jsonc
// 根 tsconfig.json，本身不参与编译，只负责编排
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
    "composite": true,        // 允许被 reference，并保证可被增量构建
    "declaration": true,
    "incremental": true       // 生成 .tsbuildinfo
  }
}
```

要点：

- **`composite`** 是 project reference 的准入开关，会连带要求 `declaration: true` 等一组选项；
- **`incremental`** 生成 `.tsbuildinfo`，记录上次的文件版本与诊断结果，供 `tsc --build` 复用；
- 引用方用一个 project 时，会读它的 `.d.ts` 而非源文件——这就是 "solution style tsconfig" 能让 IDE 与构建都变快的原因；
- TS 7 新增 `--builders` 让 project reference 的构建也并行起来。

诊断辅助：`tsc --explainFiles` 会把"为什么这个文件被纳入 program"讲清楚，`tsc --traceResolution` 跟踪模块解析路径，`--extendedDiagnostics` 给出各阶段耗时。配合配置见 [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)。

## Links

- [TypeScript](/docs/CS/TypeScript/TypeScript.md)
- [TypeScript 类型系统](/docs/CS/TypeScript/TypeSystem.md)
- [tsconfig 工程配置](/docs/CS/TypeScript/Tsconfig.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [Webpack](/docs/CS/front-end/Webpack.md)

## References

- [microsoft/typescript-go](https://github.com/microsoft/typescript-go)
- [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- [TypeScript 7.0 Release Notes](https://typescriptdocs.com/release-notes/TypeScript%207.0)
- [TypeScript Compiler Internals](https://github.com/microsoft/TypeScript/wiki/Architectural-Overview)
- [TypeScript: Project References](https://www.typescriptlang.org/docs/handbook/project-references.html)
- [Progress on TypeScript 7](https://devblogs.microsoft.com/typescript/)
