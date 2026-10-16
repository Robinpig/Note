> 版本基线：核实于 2026-10-06。参考：[第一个插件](https://deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/)（前置：完成[从源码运行](https://github.com/deepseek-ai/deepseek-harness#run-from-source)）

## Introduction

插件是 DeepSeek Harness 扩展的基本单元。它导出一个 `apply` 函数，框架加载时传入 `ctx`（上下文对象），插件通过 `ctx` 注册服务、事件监听器、工具等能力。**一切皆插件**的意思是：工具、LLM 适配器、文件访问乃至 Agent Loop 本身都是插件。

## What Is a Plugin

插件是一个**导出 `apply` 函数的 TypeScript 模块**。框架加载时调用 `apply`，传入 `ctx`（上下文对象），通过 `ctx` 注册能力——这就是完整的插件配置。

```ts
import type { Context } from '@deepseek-ai/cordis'

export const name = 'hello-plugin'

export function apply(ctx: Context) {
  console.log('[hello-plugin] plugin loaded!')
}
```

## Three Forms of Plugins

| 形态 | 适用场景 |
| --- | --- |
| 函数形式 `export function apply(ctx)` | 大多数情况，最简单直接 |
| 对象形式 `export default { name, inject, apply }` | 需要打包 name/inject 声明与 apply 在一起，便于工具链处理 |
| 类形式 `class MyService extends Service` | 需要向其他插件提供服务（见下文 Service 示例） |

```ts
// 对象形式
import type { Context } from '@deepseek-ai/cordis'

export default {
  name: 'my-plugin',
  inject: ['tools'],           // 声明依赖
  apply(ctx: Context) {
    // ctx.tools 已就绪
  }
}

// 类形式
import { Service, type Context } from '@deepseek-ai/cordis'

export default class MyService extends Service {
  static inject = ['tools']

  constructor(ctx: Context) {
    super(ctx, 'myService')
    // 构造函数中做同步初始化
  }
}
```

## Lifecycle and Automatic Cleanup

通过 `ctx` 注册的一切（事件监听、工具、定时器）在插件卸载时**自动清理**，无需手动 `removeListener` / `clearInterval`。需要手动清理的资源（如网络连接、文件句柄）用 `ctx.effect()`：

```ts
export function apply(ctx: Context) {
  ctx.effect(() => {
    const timer = setInterval(() => console.log('heartbeat'), 5000)
    return () => clearInterval(timer) // 插件卸载时执行
  })
}
```

### Real Example: Storage Backend Registration

真实例子——存储插件登记可撤销的 backend 注册：

```ts
export const inject = ["storage"]

export function apply(ctx, config) {
  const backend = new JsonStorageBackend(config.root)

  ctx.effect(() => {
    const unregister = ctx.storage.backend.register("json", backend)
    return async () => {
      unregister()
      await backend.close()
    }
  })

  ctx.provide("storageBackend:json", backend)
}
```

关键模式：`ctx.effect(() => { ...setup... ; return () => ...cleanup... })`——setup 和 cleanup 写在同一个 effect 里，框架保证卸载时调用返回的 disposer。

### Real Example: Tool Registration with Timeout

工具插件的 effect 模式：

```ts
export const name = 'my-tool-plugin'
export const inject = ['tools', 'shell']

export function apply(ctx: Context) {
  ctx.effect(() => {
    const registration = ctx.tools.register({
      name: 'run_my_command',
      description: 'Runs my custom build command',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: 'Build target name' }
        },
        required: ['target']
      },
      timeoutMs: 120000,
      execute: async (args) => {
        const result = await ctx.shell.bash(`my-build-tool ${args.target}`)
        return { success: result.exitCode === 0, output: result.stdout }
      }
    })
    return () => registration.unregister()
  })
}
```

## Declare Dependencies (inject)

需要其他服务（如 `tools`、`llm`、`fs`）时声明 `inject`，框架确保依赖服务就绪后才加载插件：

```ts
export const name = 'my-tool-plugin'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(/* ... */) // ctx.tools 已就绪
}
```

**依赖约束 ≠ 权限控制**：原生 JS 插件仍在宿主进程执行，未注入 `fs` 不代表 OS 层失去文件访问。`inject` 只是控制启动顺序和依赖解析时机。

## Register to Web UI via Patch YAML

创建 `scratch-plugin/cordis.yml` 作为本地插件的 Web 覆盖层（插件路径必须是**绝对路径**；patch 文件只贡献配置，不改变 loader 解析模块路径的 profile 目录）：

```yaml
- insert:
    - id: hello
      name: '/absolute/path/to/deepseek-harness/scratch-plugin/src/my-plugin.ts'
```

用覆盖层启动 Web UI：

```sh
pnpm dsh web --patch ./scratch-plugin/cordis.yml
```

打开 `http://127.0.0.1:3080`，启动时终端会打印 `[hello-plugin] plugin loaded!`。

## Configuration Is Assembly

三层配置概念决定了插件如何被装配：

- **Bundle**：分发一组 Cordis 配置和对应插件代码
- **Profile**：决定进程堆叠哪些 Bundle（内置 `web` 与 `headless`）
- **Patch**：替换或插入配置行，用于用户配置和命令行覆盖

Loader 加载顺序（后层按 id **整块替换**或插入）：

```
空 entry list
→ Profile 声明的 Bundle
→ Profile 自身 cordis.patch.yml
→ Harness home 下的 patch
→ 命令行 --patch
→ （关 telemetry 时）launcher 叠加 override
```

整块替换要求用户重述保留字段，略显笨重，却避免深度合并规则在数组、表达式和删除语义上制造歧义。配置热更新失败时，Loader 会恢复**最后一棵可用的插件树**（Group 并发启动收集全部结果，一项失败即删除新增项并重建旧配置）——接近配置事务，但不等同于数据库事务（外部副作用无法回滚）。

## Composition Example: minimal preset File System

`isolate` + `inject` + Provider/Consumer 三角色的真实组合（`agent.cordis.yml`）：

```yaml
- id: filesystem
  name: cordis:group
  group: true

  # 为这棵子树创建私有的 fs service realm
  isolate:
    fs: true

  config:
    # Consumer：tools 或当前 realm 的 fs 缺失时，Fiber 保持 PENDING
    - id: editor
      name: '@deepseek-ai/dsh-tool-str-replace-editor'
      inject: [tools, fs]
      config:
        maxOutputChars: 16000

    # Provider：在上面的私有 realm 中发布 ctx.fs
    - id: fs-provider
      name: '@deepseek-ai/dsh-fs-local'
      config:
        cwd: !!js process.env.DSH_CWD ?? process.cwd()
```

这个例子展示了 capability seam（能力接缝层）的三角色模式：**Service Definition**（`ctx.fs` 的稳定调用协议）→ **Provider**（`dsh-fs-local` 的具体实现）→ **Consumer**（`dsh-tool-str-replace-editor` 把能力变成模型可见工具）。底层从本机文件系统换成沙箱时，模型工具和 Agent Loop 都不用变化。

## Development Workflow Summary

完整开发一个 DSH 插件的步骤：

1. **克隆源码** + `pnpm install`（参见 [Installation](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md?id=installation)）
2. **创建插件模块**：TypeScript 文件，导出 `name`、可选的 `inject` 和 `apply`
3. **在 `apply` 中实现功能**：用 `ctx.effect()` 管理资源生命周期
4. **创建 patch YAML**：`- insert:` 条目引用插件路径（绝对路径）
5. **启动验证**：`pnpm dsh web --patch <your-patch.yml>`，看终端输出
6. **dump-config 排障**：`dsh --dump-config` 查看最终的插件配置树

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Cordis 微内核（effect / fiber / isolate 细节）](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)
- [DSH 工具层（插件注册的具体接口）](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [Cordis 教程（开发环境搭建）](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)
- [第一个插件（官方教程）](https://deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/)

## References

- [插件配置](https://deepseek-harness.github.io/deepseek-harness/develop/basic/config)
- [开发一个工具](https://deepseek-harness.github.io/deepseek-harness/develop/basic/tool)
- [DSH 的 Cordis 插件架构](https://mp.weixin.qq.com/s/XFWvHB8ke_LjcSZ06IajsA)
