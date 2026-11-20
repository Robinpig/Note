> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。Cordis 是 DSH 底层的 TypeScript 插件运行时（元框架）；设计论文：[*A Programming Paradigm for Spatiotemporal Composability*](https://arxiv.org/abs/2608.25512)。

## Introduction

Cordis 是 DSH 的**插件运行时**：它不提供模型、工具或 UI，只提供"组织能力的方式"——谁提供能力、谁使用、何时启动、如何退出、不同场景加载哪组能力。DSH 把它的源码 vendored 在 `vendor/`（重映射到 `@deepseek-ai`），本地改动包含 Fiber 重入卸载加固、配置更新事务、HMR 精确监听。

> 版本基线：v0.2.2-rc.3。

几个反直觉的点：

- **"一切皆插件"不递归到元层**：根 Context 构造函数里直接 `new Fiber/ReflectService/RegistryService/EventsService/LoggerService`，这些不是插件、不可被插件卸载。可替换的是产品能力，不是让插件得以存在的机制。
- **`provide` 返回的 disposer 不是"必须手动调用才清理"**：它本身已经是 fiber effect 的 wrapper，登记进 `_disposables`；不调用，fiber 卸载照样逆序回收，调用了也是幂等触发同一个 dispose。
- **waterfall 的 `next()` 是 Koa 式"包裹剩余链"**：不调用即否决内建行为（如服务解析、配置校验），调用两次直接抛错——把它当普通观察者漏掉 `next()`，会导致"服务读不到/配置没应用"这类难定位的现象。

## Context: A Proxy-Backed Service Boundary

`ctx` 不是装满单例的对象，而是**经 Proxy 包装的服务解析边界**。根 Context 构造时安装内建服务并把自己包成 Proxy（`vendor/cordis/src/context.ts`）：

```ts
  /** Create the root context and install the built-in services. */
  constructor() {
    this[symbols.isolate] = Object.create(null)
    this[symbols.intercept] = Object.create(null)
    const self = new Proxy<this>(this, ReflectService.handler)
    this.root = self
    this.baseUrl = undefined
    this.fiber = new Fiber(self, {}, Object.create(null), null, () => [])
    this.reflect = new ReflectService(self)
    this.registry = new RegistryService(self)
    this.events = new EventsService(self)
    this.logger = new LoggerService(self)
    this.fiber._disposables.clear()
    return self
  }
```

读取 `ctx.foo` 时，Proxy 的 `get` 陷阱沿 fiber 链上溯、按 isolate key 找实现（`vendor/cordis/src/reflect.ts`）：

```ts
      const def = target.reflect.props[prop]
      if (def?.type === 'accessor') {
        return def.get.call(ctx, ctx[symbols.receiver], error)
      }
      // a fiber-less def site cannot declare `inject` at all, so it keeps the unchecked root access.
      const defSite = (ctx[symbols.shadow] as Context | undefined) ?? ctx
      if (!defSite.fiber.runtime) return ctx.reflect.get(prop, false)
      return ctx.events.waterfall('internal/get', ctx, prop, error, () => {
        const key = defSite[symbols.isolate][prop]
        let fiber = defSite.fiber
        while (true) {
          let impl = fiber.committed?.[prop]
          for (const provision of fiber.provisions) {
            if (provision.name === prop && provision.ctx[symbols.isolate][prop] === key) impl = provision
          }
          if (impl) return getTraceable(ctx, impl.value)
          if (prop in fiber.inject) {
            error.message = `cannot get required service "${prop}" in inactive context`
            throw error
          }
          if (!fiber.runtime) throw error
          if (fiber.parent[symbols.isolate][prop] !== key) throw error
          fiber = fiber.parent.fiber
        }
      })
```

含义：未在 `inject` 声明就读 `ctx.foo` 会报错；`ctx.get("foo")` 是不受限的显式读取（接受服务可能不存在）。**依赖声明不是权限控制**——原生 JS 插件仍在宿主进程执行，未注入 `fs` 不代表 OS 层失去文件访问。

子 Context 通过原型继承父级（不新建容器），`isolate()` 只覆盖一个 name→label 映射：

```ts
  isolate(name: string, label?: symbol) {
    const shadow = Object.create(this[symbols.isolate])
    shadow[name] = label ?? Symbol(name)
    return this.extend({ [symbols.isolate]: shadow })
  }
```

配合 loader 层的 `Realm` 把 label 稳定映射成带后缀 symbol（`vendor/loader/src/config/isolate.ts`），同名服务可在不同 realm 各自存在——这是 agent preset 能给每个会话独立工具集/提示词的基础。

## Fiber: The Ownership Unit

Plugin 是定义，**Fiber 是挂载实例记录**：父 Context、原始配置、依赖实现快照、生命周期状态、disposables。状态枚举（`vendor/cordis/src/fiber.ts`）：

```ts
export const enum FiberState {
  PENDING,
  LOADING,
  ACTIVE,
  FAILED,
  DISPOSED,
  UNLOADING,
}
```

配置文件条目顺序不承担启动顺序，**依赖关系才承担**——依赖未就绪时 Fiber 停在 PENDING，就绪后 LOADING→ACTIVE。Provider 换实现时，Fiber 身份变化刷新依赖 epoch，触发旧 Consumer 卸载与新重载；Cordis 维护的是随 Provider 变化刷新的运行图，不是启动一次解析完的 DI 容器。

`plugin()` 把插件归一化为 callback/runtime 并创建 Fiber（`vendor/cordis/src/registry.ts`）：

```ts
  plugin(plugin: Plugin, config?: any, getOuterStack = buildOuterStack()) {
    const callback = this.resolve(plugin)
    if (!callback) throw new Error('invalid plugin, expect function or object with an "apply" method, received ' + typeof plugin)
    this.ctx.fiber.assertActive()
    let runtime = this._internal.get(callback)
    if (!runtime) {
      let name = plugin.name
      if (name === 'apply') name = undefined
      runtime = { name, callback, fibers: new DisposableList(), Config: plugin.Config }
      this._internal.set(callback, runtime)
    }
    const fiber = new Fiber(this.ctx, config, Inject.resolve(plugin.inject), runtime, getOuterStack)
    return Object.create(fiber) as Fiber & PromiseLike<Fiber>
  }
```

## Effect: Registration as Reversible

一切可撤销的注册都收敛到 `Fiber.effect()`。它把执行体返回的 disposer 经 `collect` 压入局部数组，并把包装后的 wrapper 登记进 fiber 的 `DisposableList`（`vendor/cordis/src/fiber.ts`）：

```ts
    const disposables: Disposable[] = []
    let disposing = false
    let disposalTask: void | Promise<void>
    const dispose = () => {
      if (disposing) return disposalTask
      disposing = true
      let task!: void | Promise<void>
      for (const disposable of disposables.splice(0).reverse()) {
        if (task) {
          task = task.then(() => runDisposable(disposable))
        } else {
          const result = runDisposable(disposable)
          if (isObject(result) && 'then' in result) task = result as any
        }
      }
      return disposalTask = task
    }
```

执行器把同步函数、promise、同步迭代、异步迭代统一成"收集 disposer"（同文件 `_execute`）：

```ts
      const effect: Effect = runner.execute.call(this)
      if (typeof effect === 'function') {
        return runner.collect(effect)
      } else if (isNullable(effect)) {
        // return
      } else if (!isObject(effect)) {
        throw new TypeError('Invalid effect')
      } else if ('then' in effect) {
        return effect.then(safeCollect)
      } else if (Symbol.iterator in effect) {
        info.error = new Error()
        const iter = effect[Symbol.iterator]()
        while (true) {
          const result = iter.next()
          safeCollect(result.value)
          if (result.done) return
        }
      } else if (Symbol.asyncIterator in effect) {
        // ... async iterator branch awaits each yield, honoring epoch
      }
```

Fiber 卸载走 `_unload()`：**先等所有 dependents 清空**（不让下游在自己清理时访问已撤销服务），再逆序 await 所有 disposer（`vendor/cordis/src/fiber.ts`）：

```ts
  private async _unload() {
    while ([...this.provisions].some(impl => impl.dependents.size)) {
      await new Promise<void>((resolve) => this._release = resolve)
    }
    this._release = undefined
    await Promise.all(this._disposables.clear().map(async (dispose) => {
      try {
        await composeError(async (info) => {
          await Promise.resolve()
          info.error = new Error()
          await runDisposable(dispose)
        }, this._runner.getOuterStack)
      } catch (reason) {
        this.ctx.logger.error(reason)
      }
    }))
  }
```

这就是"先问如何撤销，再问如何注册"的运行时兑现：插件作者只在 effect 里"注册"，无需手动配对注销；fiber 是唯一所有权边界，卸载 = 逆序执行其账号下所有 effect 的 disposer。**但可逆 ≠ 事务**——disposer 只能补偿，发过的网络消息、写过的共享文件不回滚。

## The Five Dispatch Modes

插件间除了服务调用，还提供类型化事件。五种模式在 `vendor/cordis/src/events.ts`：

```ts
  emit(...args: any[]) {
    const [thisArg, callbacks] = this._resolve('emit', args)
    for (const callback of callbacks) Reflect.apply(callback, thisArg, args)
  }

  async serial(...args: any[]) {
    const [thisArg, callbacks] = this._resolve('serial', args)
    for (const callback of callbacks) {
      const result = await Reflect.apply(callback, thisArg, args)
      if (isBailed(result)) return result
    }
  }

  waterfall(...args: any[]) {
    const [thisArg, callbacks] = this._resolve('waterfall', args)
    const inner = args.pop()
    const dispatch = () => {
      const callback = callbacks.shift()
      if (!callback) return inner()
      let called = false
      const next = () => {
        if (called) throw new Error('next() called multiple times')
        called = true
        return dispatch()
      }
      return Reflect.apply(callback, thisArg, [...args, next])
    }
    return dispatch()
  }
```

`parallel` 用 `Promise.allSettled` 并发、把 rejected 聚合成 `AggregateError`；`bail` 是 `serial` 的同步版。DSH 的分派：

| 模式 | 行为 | DSH 用例 |
| --- | --- | --- |
| `emit` | 同步通知，忽略返回值 | `tools/result`、`agent/status`、`session/event` |
| `parallel` | 并发等全部完成 | 广播型通知 |
| `serial` | 顺序、遇首有效结果停止 | `agent/turn-stopping`、`agent/created` |
| `bail` | `serial` 同步版 | 校验类拦截 |
| `waterfall` | 监听器拿 `next()` 包裹/改写/短路余下链 | `agent/pre-step`、`agent/request`、`llm/stream`、`tools/execute` |

**事件的持久性被刻意分层**：`agent/*`、`tools/*` 是活跃运行时的拦截（进程内、不落盘）；`turn/*`、`step/*`、`user/message`、`tool/*` 等会话事件追加日志承担恢复/fork/回放。一切皆插件 ≠ 一切皆事件。

## Loader and HMR: Failure Recovery

Loader 的 entry 导入模块后交给 registry 建 Fiber（`vendor/loader/src/config/entry.ts`）：

```ts
  private async _init() {
    let moduleNamespace: unknown
    try {
      moduleNamespace = await this.parent.tree.import(this.options.name, this.getOuterStack)
    } catch (error) {
      this.ctx.logger.error(error)
      return
    }
    const plugin = this.loader.unwrapExports(moduleNamespace)
    await this._patchContext([])
    this.fiber = this.ctx.registry.plugin(plugin, this.options.config, this.getOuterStack)
    this.moduleNamespace = moduleNamespace
  }
```

HMR 失败恢复靠"备份缓存 + 旧插件按原配置重建"（`vendor/hmr/src/index.ts`）：先备份 ESM loadCache 与 CJS require.cache 并清空，重导入或重挂载任一失败即 `rollback()` 恢复两份缓存，并 `registry.delete(attempts[filename])` + `reload(plugin, runtime)` 用旧实现按原 rawConfig 重新建 fiber。

配置持久化（include）则是"读成功才写 cache、坏文件只告警保留旧树"（`vendor/include/src/index.ts`）：

```ts
        } catch (error) {
          // Half-written files are routine while the user is editing, hence
          // only a warning. With the file in an unknown state there is nothing
          // safe to write: unless another read is due, stop here and leave
          // `dirtyWrite` set for the next trigger.
          this.persistenceError = error
          this.ctx.logger.warn(error)
          if (this.dirtyRead) continue
          return
        }
```

两者共同兑现"失败后保留最后一棵可用树"——接近配置事务，但外部副作用无法回滚，所以不等同于数据库事务。

## Comparison with Historical Precedents

- **Eclipse**：扩展点/扩展由宿主清单定义；DSH 连 agent loop 和 UI 都可替换，核心与第三方插件共享同一挂载机制。
- **OSGi**：动态服务注册表 + bundle 生命周期已有先例；Cordis 的新意是把动态依赖、作用域上下文、effect 所有权压进一个很小的进程内模型（执行单元是 Fiber——一个函数或 Service 子类即可）。
- **DI 容器**：新组合来自 **DI 与生命周期的绑定**——普通容器只构造对象，定时器/监听器/子进程仍由业务代码清理，Cordis 把注册动作收敛成 effect。

`declare module '@deepseek-ai/cordis' { interface Context { ... } }` 是声明合并：为已有接口添加 `ctx.greeter` 或事件名的类型，**不产生任何运行时接线**，插件须另行 `provide` 服务或发出事件。

## Common Misconceptions

1. **元层不是插件**：Proxy 陷阱、EffectRunner、Fiber 状态机、dispose 屏障属于 Cordis 自身，无法通过 `ctx.plugin()` 卸载或替换。
2. **失败 fiber 不会因依赖到位自动复活**：`_setEpoch` 里 `if (this._error) return` 明确阻断；失败 fiber 只能通过显式 `update()` 恢复。
3. **`FiberState` 的真相来源不是 `state` 字段**：ACTIVE/FAILED/PENDING 由 `_getState()` 依据 `uid/_error/runner.epoch` 派生，`state` 只是用于 `internal/status` 的缓存值。
4. **`emit` 并非普遍保证逐监听器隔离错误**：只有被特判的生命周期通知路径逐个 try/catch；公共 listener 抛错仍会中断同批后续 listener。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Plugin 开发](/docs/CS/AI/LLM/Agent/Product/DSH/Plugin.md)
- [DSH Boot & Frontends](/docs/CS/AI/LLM/Agent/Product/DSH/BootAndFrontends.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）vendor/cordis](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/vendor/cordis)
2. [Cordis 框架](https://github.com/cordiverse/cordis) / [时空可组合性论文](https://arxiv.org/abs/2608.25512)
3. [Cordis 框架教程](https://deepseek-harness.github.io/deepseek-harness/develop/cordis-tutorial/)
4. [DSH 的 Cordis 插件架构](https://mp.weixin.qq.com/s/XFWvHB8ke_LjcSZ06IajsA)
