## Introduction

技能（Skills）是渐进式加载的专业流程——OpenCode 启动时只把技能名与描述摘要交给模型，判断相关后才通过原生 `skill` 工具拉取全文。这正是 Skill 相比「把规范全塞进系统提示词」节省 token 的地方。本文覆盖技能目录、frontmatter 契约与访问控制。

## Locations

- 项目级：`.opencode/skills/<name>/SKILL.md`，同时兼容 `.claude/skills/`、`.agents/skills/`
- 全局：`~/.config/opencode/skills/`、`~/.claude/skills/`、`~/.agents/skills/`
- 项目级查找会一直向上直到仓库边界 / git worktree 根

## Frontmatter

`SKILL.md` 的 frontmatter 中 `name` 与 `description` 必填，`license`、`compatibility`、`metadata` 可选，未知字段忽略。准确地写 `description` 很重要——模型只靠它决定是否加载该技能。

## Progressive Loading

启动时 Agent 只看到名称与描述的摘要，判断相关后才通过原生 `skill` 工具拉取全文。这与 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) 的 Skills 思路一致（均遵循 Agent Skills 开放标准），但与把整段规范常驻系统提示相比显著省 token。

## Access Control

技能可经 `permission.skill` 按 glob 模式控制加载：

```json
{
  "permission": {
    "skill": {
      "*": "allow",
      "chinese-*": "ask",
      "internal-*": "deny"
    }
  },
  "agent": {
    "reviewer": {
      "permission": { "skill": { "*": "deny", "chinese-code-review": "allow" } },
      "tools": { "skill": false }   // 也可以直接关掉某个 Agent 的 skill 工具
    }
  }
}
```

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md)
- [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [Skill (Theory)](/docs/CS/AI/LLM/Agent/Theory/Skill.md)

## References

- [OpenCode Skills 文档](https://opencode.ai/docs/skills)
- [Agent Skills 规范](https://agentskills.io/specification)
