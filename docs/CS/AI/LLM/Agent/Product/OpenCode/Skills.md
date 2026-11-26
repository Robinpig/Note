> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。技能发现与加载有两套并存：`core/src/skill/`（V2，作为 SystemContext 的 `core/skill-guidance` source）与 `opencode/src/skill/` + `session/skill.ts`（V1，`skill` 工具链路）。本文覆盖目录约定、frontmatter、渐进式加载与访问控制。

## Introduction

技能（Skills）是**渐进式加载的专业流程**——OpenCode 启动时只把技能名与 `description` 摘要交给模型，判断相关后才通过原生 `skill` 工具拉取全文。这正是 Skill 相比"把规范全塞进系统提示词"节省 token 的地方。V1 与 V2 都遵循这个模式，只是摘要注入的位置不同（V1 在 system 的 `sys.skills`，V2 在 SystemContext source）。

## Discovery and Directory Convention

V2 的 `core/src/skill/` 发现逻辑扫描约定目录并解析 SKILL.md 的 frontmatter。目录约定：`.opencode/skills/`（项目）、`~/.config/opencode/skills/`（全局），同时兼容 `.claude/skills/` 与 `.agents/skills/`（便于从 Claude Code 迁移）。技能名来自目录名，`description` 来自 frontmatter。

frontmatter 契约核心字段：

```markdown
---
description: Use when the user asks about X; do not use for Y
license: MIT
allowed-tools: Read, Grep, Bash(git *)
---

# 技能正文（按需拉取的完整流程）
```

V2 的 `skillGuidance.load(agent)`（`core/src/skill/guidance.ts`）先按 agent 权限过滤，再把有 description 的技能渲染成摘要 source：

```typescript
load: Effect.fn("SkillGuidance.load")(function* (selection) {
  const agent = selection.info
  if (!agent) return SystemContext.empty
  const permitted = SkillV2.available(yield* skills.list(), agent)
  if (permitted.length === 0 && PermissionV2.evaluate("skill", "*", agent.permissions).effect === "deny")
    return SystemContext.empty
  const available = permitted
    .flatMap((skill) => skill.description === undefined ? [] : [{ name: skill.name, description: skill.description }])
    .toSorted((a, b) => a.name.localeCompare(b.name))
  return SystemContext.make({
    key: SystemContext.Key.make("core/skill-guidance"),
    baseline: render,
    update: (_previous, current) => [
      "The available skills have changed. This list supersedes the previous available skills list.",
      render(current),
    ].join("\n"),
    removed: () => "Skill guidance is no longer available. Do not use any previously listed skill.",
  })
})
```

注意：只有带 `description` 的技能才进摘要；`update`/`removed` 文本明确"取代此前列表"——这是渐进式加载在 V2 的落点。详见 [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md)。

## Progressive Loading via the skill Tool

模型看到摘要后，用原生 `skill` 工具（`packages/core/src/tool/skill.ts` 与 `opencode/src/tool/skill.ts`）按名字拉取全文。这个工具也走 `ctx.ask({permission: "skill", patterns: [name]})` 鉴权——权限键 `skill` 是 Rule 类型，可按技能名 glob 控制。执行链与内置工具一致（hook + permission），见 [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)。

V1 的 system 拼装（`session/prompt.ts`）把 `sys.skills` 摘要和 `sys.environment`、`instruction.system()`、`sys.mcp` 一起注入；provider 专属人设 prompt 由 `system.ts` 按 model id 选（anthropic/gpt/gemini/kimi/codex/trinity 等）。

## Access Control

`permission.skill` 既控制工具调用，也控制摘要是否出现在上下文里：V2 的 `SkillV2.available(skills, agent)` 按 agent 权限过滤，且当完全无可用技能且 `skill: "*"` 为 deny 时返回空 source（连摘要都不给）。这比"调用了才拦"更省——被禁的技能模型根本不知道其存在。

## Links

- [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md) / [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) / [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [core/src/skill/guidance.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/skill/guidance.ts)
2. [core/src/tool/skill.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/tool/skill.ts)
3. [opencode/src/tool/skill.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/tool/skill.ts)
4. [OpenCode Skills 文档](https://opencode.ai/docs/skills/)
