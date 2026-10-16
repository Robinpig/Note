> 版本基线：核实于 2026-10-06。源码 `spawn.ts` 有 543 行，真正把进程拉起来的 spawn 调用只有 12 行，剩下五百多行在回答同一个问题：**怎么让这个进程死干净**。

## Introduction

起进程从来不难，难的是收。主线案例是 bash 执行器跑一条 `npm run build`：npm 自己是 node 进程，它再拉起构建器，构建器还自带进程池。从 Harness 视角看，这不是"一个子进程"，而是**一棵进程树**。围绕这棵树，六种死法各自长出一层机制。

| 死法 | 症状 | 机制 |
| --- | --- | --- |
| 孤儿进程 | 命令超时了机器却越来越烫 | `detached` 独立进程组 + 负 pid 组信号 |
| pid 复用 | 探活误判，SIGKILL 打死别人进程 | 首次确认树亡 = 永久停手边界 |
| leader 死、树没死 | 优雅退出宽限期被打断 | `graceTimer` 刻意不清、kill 前重探活 |
| 2GB 构建日志 | Node 先 OOM | 字节精确的尾部窗口 + 有上限的 spill 文件 |
| exit 来了 close 不来 | 工具调用挂死在 await 上 | 同一个 `graceMs` 兜底强制结算 |
| 宿主先死 | 活树留在系统里 | `prependListener('exit')` 队首同步 SIGKILL |

## Independent Process Group and Negative pid

`child_process` 的默认 spawn 治不了孤儿：信号发给 npm，到不了它 fork 的构建器。DSH 的解法写在一个参数里——POSIX 上 `detached: true` 让孩子拥有自己的进程组，组 id 等于它的 pid：

```ts
const child = spawn(program, args, {
  cwd: spec.cwd,
  env,
  stdio: [
    stdinMode === 'ignore' ? 'ignore' : 'pipe',
    outMode === 'inherit' ? 'inherit' : 'pipe',
    errMode === 'inherit' ? 'inherit' : 'pipe',
  ],
  // `detached` gives teardown a tree root on POSIX (its own process group);
  // Windows terminates by root pid through taskkill /T instead.
  detached: platform !== 'win32',
})
```

`process.kill(pid)` 杀一个，`process.kill(-pid)` 杀一组——**一个负号，就是"杀一个"和"杀一棵树"的全部区别**。后面所有终止逻辑都建立在这个负号上。

顺带看 `env`：`childEnv(spec.env)` 先取基类提供的 `scrubbedParentEnv()`，把父环境的凭据类变量剔干净再叠加调用方条目，所以 `aws.env` 里的 key 不会跟着构建命令泄进子进程。

Windows 没有进程组，换一种砍法，`/T` 砍整棵树、`/F` 强杀：

```ts
export function taskkillProcessTree(pid: number): void {
  if (pid <= 0) return
  // Outcome deliberately unchecked: an already-absent tree (status 128), exit
  // races, and a missing taskkill binary (spawnSync reports, never throws) are
  // as tolerable here as ESRCH is for a POSIX group signal.
  spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
}
```

注释里"结果故意不检查"是重点：**终止逻辑必须幂等**，第二次杀一棵死树不能抛异常，否则收尾代码会自己把自己绊倒。

## pid Reuse: First Confirmation Is a Permanent Boundary

发完 TERM 怎么知道树死了？POSIX 惯例是 `process.kill(-pid, 0)` 探活（0 号信号只做存在性检查），DSH 用 **15ms 一次的轮询**做这件事。

风险在于 pid 会回收：树全退 → 组 id 进回收池 → 系统把同一个数字发给不相干的新进程且它恰好成了组长 → 下一轮探活成功 → 升级梯到点，SIGKILL 打死别人的进程。DSH 立了一道**不可逆**的边界：

```ts
/**
 * Start or reuse the handle's single whole-tree exit observer. The first
 * confirmed absence is a permanent no-more-signals boundary: it cancels a
 * pending escalation before this process-group id can be reused.
 */
const observeTreeExit = (): Promise<void> => {
  treeExitObservation ??= (async () => {
    while (treeAlive()) await sleepTick()
    treeExitObserved = true
    if (graceTimer !== undefined) clearTimeout(graceTimer)
    graceTimer = undefined
  })()
  return treeExitObservation
}
```

`treeExitObserved` 一旦置 true 就永不回头，`treeAlive()` 第一行就是它：确认过树亡，此后一切探活直接返回死，待发的 SIGKILL 也被撤掉。两个配套细节：

- `sleepTick` 的 timer 保持 **ref'd**——被 await 的收尾必须保住事件循环直到树真退出，否则父进程一边宣称一切已安静一边退出，留下的正是它承诺要收割的孤儿。
- 只剩僵尸的组对 `kill(0)` 同样应答成功（僵尸占着进程表条目，杀不死，只能等父进程收尸）。因此 Linux 上还有一层精化：`linuxProcessGroupHasLiveMembers(pid)` 扫 `/proc` 判断组内成员是否全是 Z/X，但**只在直接孩子结算之后才扫**——活跃期的轮询保持一次 syscall 的成本，不拖家带口扫全表。

## Leader Death Does Not Mean Tree Death

`terminate()` 是终止的全部：已观测退出或已有 `graceTimer` 就直接返回，否则先 `observeTreeExit()`，发 SIGTERM 给整组，再挂一个 `graceMs` 的定时器到点升级 SIGKILL。

```ts
const terminate = (): void => {
  if (treeExitObserved || graceTimer !== undefined) return
  void observeTreeExit()
  if (treeExitObserved) return
  kill('SIGTERM')
  // The escalation must survive direct-child settlement — the leader dying
  // does not mean the tree died — so settle does not clear this timer, and
  // kill() re-probes tree liveness before force-killing. …
  graceTimer = setTimeout(() => { kill('SIGKILL') }, spec.graceMs)
}
```

反直觉的地方在下一层：npm 收到 TERM 退出了，exit 事件来了，直觉是"孩子都死了，SIGKILL 定时器该清了"——**不清**。npm fork 的某个 helper 可能捕获了 TERM，正慢慢写临时文件，它还活着，还欠着一次可能的 SIGKILL。所以结算函数里刻意不清 `graceTimer`，且 `kill()` 每次执行前重新 `treeAlive()` 把关。

`graceMs` 自身也有硬上限：spawn 前校验它必须是正数且不超过 `2^31-1`（`MAX_TIMER_DELAY_MS`）——这是 Node 定时器能表示的最大延迟，更大的数塞进 `setTimeout` 会被立即触发，升级梯当场失效。

超时归谁管？**这个包自己不定超时**，只监听调用方传进来的 `AbortSignal`，abort 一到就 terminate。超时语义在消费侧，bash-local 里只有三行：

```ts
// One deadline combines timeout and upstream cancellation; disposal clears its timer.
using d = deadline(spec.signal, spec.timeoutMs, 'BASH_TIMEOUT')
const handle = this.ctx.subprocess.spawn(this.spawnSpec(spec, argv, spec.stdoutMaxBytes, d.signal))
```

`using` 在作用域结束时自动 dispose 定时器，超时与上游取消在上层合成一个信号，下层只管响应——两层各认各的账。

## Output: Byte-Precise Diagnostic Tail

构建挂掉时编译器把每个文件的错误全吐出来，stdout 两 GB，全量缓存进内存 Node 先 OOM。截断该截头部还是尾部？依据是**错误和最终结果聚在命令输出的末尾**（引自 pi / OpenCode 的实践），所以内存里只留尾部。

```ts
push(chunk: Buffer): void {
  this.total += chunk.length
  const overflows = this.bytes + chunk.length > this.maxBytes
  if (!this.spillDisabled && (overflows || this.spillFd !== undefined)) this.spillAll(chunk)
  this.chunks.push(chunk)
  this.bytes += chunk.length
  while (this.bytes > this.maxBytes) {
    const head = this.chunks[0] as Buffer
    const excess = this.bytes - this.maxBytes
    if (head.length <= excess) {
      // Drop the whole head chunk (length ≥ 1 is guaranteed while over cap).
      this.chunks.shift()
      this.bytes -= head.length
    } else {
      // Trim the head so the retained window is byte-exact at the cap — a
      // diagnostic tail (an LSP server's stderr) must hold the LAST
      // maxBytes regardless of how the stream was chunked.
      this.chunks[0] = head.subarray(excess)
      this.bytes -= excess
    }
    this.dropped = true
  }
}
```

两个分支的意义是**与流怎么分块无关**——诊断尾部永远精确装着最后 N 字节。头部丢之前先救一步：首次溢出时 `spillAll` 把已收集的块写入 spill 文件（`'wx'` 标志、`0o600` 权限、6 字节随机后缀，防的是共享 tmp 目录里的路径预测与 symlink 种植），此后追加；spill 也有总量上限，超限则关 fd、删文件并永久禁用，磁盘绝不无限增长。不配 spill 的 collect 模式就是纯粹的"诊断尾部"形态，比如 LSP server 的 stderr——只留内存尾部，不落文件。

## exit Arrives, close Does Not

孩子退出不等于输出齐了：Node 的 `close` 事件要等 stdio 流全部关闭，而 npm 退场时留下的后台子进程继承了 stdout 管道、攥着写端不放，于是 exit 触发了 close 永远不来，工具调用挂死在 `await` 上。兜底是两条路先到先得：

```ts
child.on('exit', (exitCode, signal) => {
  // A surviving descendant that inherited a pipe must not hold the
  // outcome open indefinitely: after exit, the same bounded grace that
  // governs kills also bounds the close wait.
  pipeDrainTimer = setTimeout(() => {
    settle(exitCode, signal)
  }, spec.graceMs)
})
child.on('close', settle)
```

close 正常来就 settle，graceMs 内没来就强制 settle 并 destroy 掉服务自己 collect 的管道（`'pipe'` 模式的流属于调用方，不动）。注意这里**复用的又是 `graceMs`**——杀树的宽限和等管道的宽限是同一个数。settle 的产物是 `{ exitCode, signal }`：正常退出带 exitCode、被信号杀带 signal，terminal 那条线上再做一次归一（exit 带非零信号时 exitCode 记 null），两个入口吐同一种形状，上层不用分辨。

## Host Dies First

最坏的时序是 dsh 自己要退出：插件树开始 dispose，promise 链还在飞，而 Node 的 `exit` 事件是同步的，里面 promise 不会 resolve、await 全部失效。所以兜底挂在队列**最前面**：

```ts
constructor(ctx: Context) {
  super(ctx)
  ctx.effect(() => {
    const onHostExit = (): void => { this.terminateForHostExit() }
    process.prependListener('exit', onHostExit)
    return async () => {
      try {
        await this.disposeManagedProcesses()
      } finally {
        process.off('exit', onHostExit)
      }
    }
  }, 'local subprocess teardown')
}
```

用 `prependListener` 而非 `on`，是因为 exit 监听器按注册顺序同步执行，插到队首才能抢在其他清理逻辑前面拿到执行权。正常退出走 `disposeManagedProcesses`：对每棵活树 `terminate()`，然后等的不是直接孩子的 `done`，而是 `waitForExit()` 的**整树退出**；任何一次等待失败立刻降级为 `terminateForHostExit`——遍历全部句柄逐个同步 `kill('SIGKILL')`，单个失败不拦下一个（同步 exit 阶段能用的原语只剩这个）。

所有权释放条件也钉在同一根线上：**handle 从 live 集合删除要等整树退出之后**。trap 了 TERM 的 helper 必须保持"被服务拥有"，teardown 才来得及升级它。

## PTY Line: Why There Is No Config

包的另一半 `spawnTerminal` 起 node-pty 会话给终端面用，自成一套难题（shell 在自己的会话里，前台进程组归 tty 管，**负 pid 一刀切不适用**）。其中最深的是一个布尔值 `isStdinWaiting`——前台进程组是不是在等输入。Linux 实现扫 `/proc/<pid>/task/<tid>/syscall`，按体系结构查表：

```ts
const SYSCALLS: Partial<Record<NodeJS.Architecture, SyscallTable>> = {
  x64: { read: 0, select: 23, pselect: 270, poll: 7, ppoll: 271, epollWait: 232, epollPwait: 281 },
  arm64: { read: 63, pselect: 72, ppoll: 73, epollPwait: 22 },
}
```

`read` 看第一个参数是不是 fd 0；`poll` 更进一步，`readMemory` 直接读目标进程内存、把 pollfd 数组解析出来看有没有 stdin。Agent 靠这个区分"前台在等输入，该发 Ctrl-C"和"前台在跑长任务，该等"。

Windows 侧则用 koffi 绑 Toolhelp32 快照枚举 + `GetProcessTimes` 取创建时间，用**创建时间戳**实现 pid 复用防御——`ProcessIdentity` 这套契约三个平台各写一遍原语，把语义拉平。

还有一件值得记住的小事：**这个插件没有 Config**。文件头注释写明 every disposition and limit arrives on the spec——stdio 怎么处置、尾部留多少、宽限多长，全由调用方的 spec 逐次带来；部署相关选择留在 bash 执行器、LSP host 各自的配置里，进程管理本身无配置可言。

## Three Counter-Intuitive Points, All in the Comments

- **Windows 的树语义弱一档吗**：spawn 线确实弱（无组、无探活，`taskkill /F` 直接强杀，没有 TERM 宽限），但 terminal 线用 Windows inspector 补上了创建时间戳防御。
- **15ms 轮询浪费吗**：对比 `SIGCHLD`/`waitid` 方案——信号不排队、要配 `waitpid` 循环、跨平台语义碎。规模小（每棵活树一个 observer）时，轮询是白捡的简单。
- **改这个包的人要先信注释**：`graceTimer` 刻意不清、首次确认即永久停手、活跃轮询单 syscall，这三处行为都反直觉，也都把理由写在旁边了。动这几行之前先读注释，否则很容易"顺手优化"掉一道防线。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH 工具层（bash 执行器消费方）](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [DSH Permission（sandbox-local 内核边界）](/docs/CS/AI/LLM/Agent/Product/DSH/Permission.md)

## References

- [源码深读 04：起一个子进程只要十行，送走它用了五百行（subprocess-local）](https://mp.weixin.qq.com/s/mmprMkOaTMP2IBTeH6uQuw)
- 官方子系统文档：[shell](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/shell.md)
