> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。指令文件有两套并存实现：V1（`packages/opencode/src/session/instruction.ts`，主会话 `prompt.ts` 用这套）与 V2（`packages/core/src/instruction-context.ts`，作为 SystemContext 的 `core/instructions` source）。本文分别标注，结论不同处以各自链路为准。

## Introduction

OpenCode 的"规则文件"是它长期记忆的载体，也是和 Claude Code（`CLAUDE.md`）互操作的关键。它们不通过某个 `read` 调用获取，而是在会话启动时被发现、拼进 system 上下文；修改规则文件会被 epoch 机制检测为 system context 变化并增量更新。

几个反直觉点：

- **V1 的"第一个匹配文件名整组胜出"**：项目级按 `["AGENTS.md","CLAUDE.md","CONTEXT.md"]` 顺序 findUp，**第一个有命中的文件名**就加载其全部祖先并 break——即使 `CLAUDE.md` 在更近目录，只要任意祖先有 `AGENTS.md`，也不会加载 CLAUDE.md。
- **V2 只读 `AGENTS.md`**，完全没有 CLAUDE.md 兼容；两套实现目前并存，主会话走 V1。
- **已发现的指令文件读取失败会返回 `unavailable`**，V2 里这会**阻塞**整批 context 初始化/替换，而不是静默跳过。

## V1: Discovery and Precedence

`session/instruction.ts` 的全局数组：

```typescript
const globalFiles = [
  path.join(global.config, "AGENTS.md"),
  ...(!flags.disableClaudeCodePrompt ? [path.join(global.home, ".claude", "CLAUDE.md")] : []),
]
const instructionFiles = [
  "AGENTS.md",
  ...(!flags.disableClaudeCodePrompt ? ["CLAUDE.md"] : []),
  "CONTEXT.md", // deprecated
]
```

`systemPaths()` 的逻辑：全局数组里取第一个存在者；项目级对每个文件名做 findUp，**命中即整组加入并 break**（"第一个项目级匹配胜出，不堆叠祖先的 AGENTS.md/CLAUDE.md"）；再叠加 `config.instructions` 的本地路径（`~/` 展开、glob/globUp）。`system()` 并发读取（concurrency 8）并对 http(s) URL 单独 fetch（5 秒超时，concurrency 4）：

```typescript
for (const file of instructionFiles) {
  const matches = yield* fs.findUp(file, ctx.directory, ctx.worktree).pipe(Effect.catch(() => Effect.succeed([])))
  if (matches.length > 0) {
    matches.forEach((item) => paths.add(path.resolve(item)))
    break
  }
}
```

渲染格式是 `Instructions from: ${path}\n${content}`。V1 还有 `resolve()`：读文件时按目录向上挂就近指令文件，每条 assistant message 只挂一次；`loaded()` 从 read 工具 part 的 `metadata.loaded` 提取已加载路径，供 compaction 时保留已读规则。`Flag.OPENCODE_DISABLE_PROJECT_CONFIG` 可完全关闭项目级发现。

## V2: The Instruction Context Source

`core/instruction-context.ts` 把指令注册成 SystemContext 的一个 source（key `core/instructions`）：

```typescript
const discovered = new Set(
  yield* Effect.forEach(
    Flag.OPENCODE_DISABLE_PROJECT_CONFIG || !insideProject
      ? []
      : yield* fs.up({ targets: ["AGENTS.md"], start, stop }),
    fs.resolve,
  ),
)
const paths = Array.dedupe([yield* fs.resolve(join(global.config, "AGENTS.md")), ...discovered])
// ...
if (files.some((file, index) => file === undefined && discovered.has(paths[index])))
  return SystemContext.unavailable
```

发现范围受两重约束：`Flag.OPENCODE_DISABLE_PROJECT_CONFIG` 与"cwd 是否在项目内"（`insideProject` 由 start 相对 project.directory 的相对路径判定）。V2 的 source 定义了 `update`（"These instructions replace all previously loaded ambient instructions."）与 `removed`（"Previously loaded instructions no longer apply."），所以指令文件变化会在下一轮以增量文本告知模型，而非重发整份 baseline。详见 [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md)。

## Practical Layering

基于发现规则，实用的分层写法：

- 全局 `~/.config/opencode/AGENTS.md` 放个人偏好（语言、讲解顺序、范式倾向）。
- 项目根 `AGENTS.md` 放技术栈、目录结构、可执行的构建/测试命令与**负面约束**（"不要引入新的状态管理库"）。
- 子目录可放模块级 AGENTS.md（V1 findUp 会一并加载祖先链；V2 的 `fs.up` 同样向上发现到 project root 为止）。

保持精简：过长提示词会稀释注意力，且每次 epoch reconcile 都要比较这些 source。从 Claude Code 迁移的仓库若两个文件都有，注意 V1 会优先 AGENTS.md 而忽略更近的 CLAUDE.md——建议合并为单一 AGENTS.md 避免歧义。

## Links

- [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md) / [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md) / [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [session/instruction.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/instruction.ts)
2. [core/src/instruction-context.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/instruction-context.ts)
3. [system-context/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/system-context/index.ts)
4. [OpenCode Rules 文档](https://opencode.ai/docs/rules/)
