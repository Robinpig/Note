## Introduction

OpenCode 的「规则文件」是它长期记忆的载体，也是和 Claude Code（`CLAUDE.md`）互操作的关键。OpenCode 优先读 `AGENTS.md`，在缺失时回退 `CLAUDE.md`，因此从 Claude Code 迁过来的仓库可以双工具共享同一份规则。本文覆盖加载顺序、`instructions` 合并机制，以及与 Claude Code 的兼容策略。

## Load Order

OpenCode 规则（长期记忆）按以下顺序加载：

1. **项目规则**：从当前目录**向上**查找 `AGENTS.md`，找到后其约束覆盖该目录下的文件
2. **兼容兜底**：若项目内没有 `AGENTS.md`，则读取 `CLAUDE.md`（Claude Code 兼容）
3. **全局规则**：`~/.config/opencode/AGENTS.md`；若不存在，退回到 `~/.claude/CLAUDE.md`
4. **额外注入**：`opencode.json` 的 `instructions` 数组，支持本地路径、glob 通配甚至远程 URL（拉取超时 5s），与自动发现的规则**合并**而非替换

```json
{
  "instructions": ["./docs/rules/*.md", "https://example.com/style.md"]
}
```

`AGENTS.md` 与 `CLAUDE.md` 同时存在时只用前者。`/init` 会扫描项目并生成 `AGENTS.md`——所以若希望两套工具共享同一份规则，可让 `AGENTS.md` 通过 `instructions` 指回 `CLAUDE.md`，或由安装脚本维护带标记块的 `AGENTS.md`。

## Practical Layering

把规则分三层最有效：全局 `~/.config/opencode/AGENTS.md` 放个人偏好（语言、讲解顺序、范式倾向）；项目 `AGENTS.md` 放技术栈、目录结构、可执行的构建/测试命令与**负面约束**（「不要引入新的状态管理库」）；子目录再放模块级规则。保持精简——过长的提示词会稀释注意力。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md)
- [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Harness (Theory)](/docs/CS/AI/LLM/Agent/Theory/Harness.md)

## References

- [OpenCode Rules 文档](https://opencode.ai/docs/rules)
- [Claude Code Memory 文档](https://code.claude.com/docs/en/memory)
