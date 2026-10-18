## Introduction

`security-guidance` 是官方最大的插件（14 文件 / 345KB），也是**唯一一个可读的、完整的官方 hook 实现**——它的 `hooks/` 目录是一套真实生产级的 Python 插件。对写过 hook 的人来说，比任何规范文档都更有参考价值：它同时示范了**分层架构**、**状态管理**、**LLM 调用**、**diff 处理**与**prompt injection 防御**。

本文的价值有两层：一是这套实现怎么组织（可照抄的范式），二是它的**三层安全模型**——后者与 [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md) 的 auto classifier 是两套并行机制，机理完全不同。

事实基线：据官方仓库 [`plugins/security-guidance/`](https://github.com/anthropics/claude-code/tree/main/plugins/security-guidance)（2026-10-18 抓取核实）。CLI ≥ v2.1.144、Python 3.8+。

## Three Layers

| 层 | 机制 | 触发时机 | 成本 |
| :--- | :--- | :--- | :--- |
| 1. **Pattern warnings** | ~26 条正则规则，命中即插入警告文本 | `Edit` / `Write` / `MultiEdit` / `NotebookEdit` | 本地正则，无网络 |
| 2. **LLM diff review** | 把 diff 发给快速 LLM 调用，高severity 发现回喂 Claude | `Stop`（turn 结束）、`git commit` / `git push` | 每次 review 一次 API |
| 3. **Agentic commit review** | **SDK 驱动**的 reviewer，用 `Read`/`Grep`/`Glob` 追数据流 | `git commit` | 多次工具调用 + 模型推理 |

第三层是三层的分水岭：它**能读仓库里的其他文件**，所以能抓到正则匹配不到的**跨文件漏洞**——IDOR、鉴权绕过、跨文件 SSRF。这不是「更长的正则」，是换了一个判定模型。

覆盖的漏洞类：注入、XSS、SSRF、硬编码密钥、IDOR、鉴权绕过、不安全反序列化、路径穿越等。

## The 26 Pattern Rules

规则定义在 `patterns.py`，是**纯数据 + 一个纯函数**——不读环境变量、不做I/O、不调 `debug_log`，刻意保持无副作用以便独立导入。文件按扩展名分三组（JS 系含 `.vue`/`.svelte`、Python 系含 `.ipynb`、文档系）。

| 类别 | ruleName |
| :--- | :--- |
| **反序列化** | `pickle_deserialization` `pickle_variants_load` `pickle_wrapper_load` `unsafe_yaml_load` `yaml_unsafe_load_variants` `torch_unsafe_load` `marshal_loads` `shelve_open` `xml_unsafe_parse` |
| **XSS** | `innerHTML_xss` `outerHTML_xss` `insertAdjacentHTML_xss` `document_write_xss` `react_dangerously_set_html` |
| **命令 / 代码注入** | `eval_injection` `new_function_injection` `os_system_injection` `python_subprocess_shell` `child_process_exec` `go_exec_shell_injection` |
| **密码学** | `aes_ecb_mode` `node_createcipher_no_iv` `tls_verification_disabled` |
| **供应链** | `github_actions_workflow` `script_src_without_sri` |

几个值得看它怎么写的细节：

- **`github_actions_workflow` 按路径而非内容匹配**（`.github/workflows/` 下的 `.yml`/`.yaml`），因为它的风险是结构性的——它给出的示例正是 `run: echo "${{ github.event.issue.title }}"`（不安全）与经 `env:` 传递（安全）的对比，并列出全部需警惕的 `github.event.*` 字段。
- **反序列化规则的文案不只说「危险」**：pickle 那条同时点名等价物（`cPickle` / `cloudpickle` / `dill` / `marshal` / `shelve` / `joblib` / `pandas.read_pickle` / `numpy` 的 `allow_pickle=True`），并给出替代方案（JSON / `msgspec`，或 `msgspec.Struct` / `pydantic` 这类 schema 校验的反序列化器）；`yaml.load` 那条点明危险来自 `!!python/object` 标签并要求 `yaml.safe_load` + schema 校验，且**明确禁止用能构造任意类型的自定义 Loader**。
- 每条提醒末尾统一一句**「若这确实是安全或明确需要的，请在继续前用注释简要说明」**——它要的是判断，不是禁令。
- 规则用 `RuleId(IntEnum)` + `_RULE_NAME_TO_ID` + `rule_names_to_mask()`（位掩码）组织，便于按名字批量开关。

## Hook Wiring

`hooks/hooks.json` 展示了官方推荐的完整接法：

| 事件 | matcher | 附加条件 | 说明 |
| :--- | :--- | :--- | :--- |
| `SessionStart` | — | `timeout: 180` | 先跑 `ensure_agent_sdk.py`——**检查 Agent SDK 是否可用**，三层里的第3 层依赖它 |
| `UserPromptSubmit` | — | — | 提示注入 |
| `PostToolUse` | `Edit\|Write\|MultiEdit\|NotebookEdit` | — | 第 1 层正则 |
| `PostToolUse` | `Bash` | `if: "Bash(git commit:*)"` | 第 3 层，commit 审查 |
| `PostToolUse` | `Bash` | `if: "Bash(git push:*)"` | 审查尚未审过的 commit |
| `Stop` | — | — | 第 2 层，diff 审查 |

⚠️ 这里出现了三个**我此前没有记录的新字段**（配套语义见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)）：

- **`asyncRewake: true`** —— hook 在后台跑，完成后**重新唤醒**会话把结果交给 Claude。这与 `async: true` 的区别是它不只是「不等它」，而是**跑完主动回来汇报**。
- **`rewakeMessage`** —— 唤醒时给 Claude 的完整提示词，官方措辞值得抄：「处理或确认下面的发现，然后继续用户的原始请求，或继续等待用户回复」。
- **`rewakeSummary`** —— 面向**用户**的一行摘要（如 "Commit security review found issues"）。

三者合起来构成一种新的 hook 模式：**不打断当前 turn、不阻塞，但保证结论一定回到对话里**。第 3 层要读多个文件、跑多次工具调用与模型推理，不可能同步等——这个模式正是为「重活异步、结论必达」设计的。

## Prompt Injection Defense

`_base.py` 里的一处设计值得单独记：**注入给 Claude 的每段文本都带 provenance 标签**：

```python
PROVENANCE_TAG = "[from security-guidance@claude-code-plugins plugin]"
```

注释解释了原因，且措辞诚实——**它明确承认这不是权威主张**：

> 「攻击者可以伪造完全相同的字符串；这个标签是一个路标，让 agent 可以带着具体依据去问运营者『这是来自你插件的吗？』，而不是把它当作未知来源的注入。」

原因是真实的：**某些自治 agent 部署会把「无来源标注的注入文本」当作 prompt injection 而停摆**。加横幅让来源显式化，避免误判。这条经验对任何写 hook 的人通用——注入内容必须有来源标注，否则可能被当成攻击而卡死。

## State And File Handling

`_base.py` 是所有 hook 模块共享的低层助手，文件头写明了它的存在理由：`patterns` / `session_state` / `gitutil` 都得用 `debug_log`，但**不能 import `security_reminder_hook`**（会循环依赖），所以它必须**不含任何其他插件内import**。

`debug_log` 的实现细节全是踩坑痕迹：

| 决定 | 理由 |
| :--- | :--- |
| 日志落`~/.claude/security/`（可由 `SECURITY_WARNINGS_STATE_DIR` 覆盖），**不落 `/tmp`** | `/tmp` 在多用户主机上全局可写——TOCTOU / 符号链接攻击面、跨用户日志泄漏 |
| 目录 `0700` 创建、文件 `0600` 创建 | 别的本地用户读不到审查输出 |
| 超过 1MB 时 `os.replace` 原子轮转到 `.1`（覆盖上一次轮转），总占用约 2× | 并行 worker 集群不把磁盘写满 |
| `os.replace` 在竞争下失败也无妨，后续 append 会重建文件 | 竞态安全的写法 |
| **整个 `debug_log` 包在try/except 里吞掉所有异常** | 日志失败绝不能影响主流程 |

## Configuration

全部经环境变量，**默认行为无需任何配置**：

| 变量 | 默认 | 作用 |
| :--- | :--- | :--- |
| `SECURITY_GUIDANCE_DISABLE=1` | unset | 整体 kill switch |
| `ENABLE_PATTERN_RULES=0` | on | 关第 1 层 |
| `ENABLE_CODE_SECURITY_REVIEW=0` | on | 关所有 LLM 审查 |
| `ENABLE_STOP_REVIEW=0` | on | **只**关Stop-hook diff 审查，保留 commit/push |
| `ENABLE_COMMIT_REVIEW=0` | on | 关第 3 层 |
| `SG_DUAL_OR=on` | off | 双路并行审查取并集 |

两处细节很见功力：

- **`ENABLE_STOP_REVIEW` 被单独拆出来**，注释给的场景是「多 agent / 共享 worktree 下另一个 agent 可能在 worker 的 turn 之间移动 HEAD」——即第 2 层的正确性依赖 `HEAD` 稳定，所以在这种场景下要能单独关掉它而保留 commit/push 审查。
- **`SG_DUAL_OR` 的取舍写明成本**：能多抓百分之几的漏洞，代价是**每次 review 约 2× API 成本**；结论是「多数用户不需要」。

模型选择 `SECURITY_REVIEW_MODEL`（默认 `claude-opus-4-7`）与 `SG_AGENTIC_MODEL`，且**不同 provider 的 id 语法不同**：Bedrock 用推理 profile id（`us.anthropic.claude-opus-4-7`）、Vertex 用日期标签形态（`claude-opus-4-7@20260218`）。README 的排障条目明确指出「审不出东西」最常见的原因就是**在 3P provider 上没设 provider 专用 id**。

## Privacy And Data Flow

README 把外发数据讲得很明确，值得作为写插件的参照：

- 每次 Stop-hook diff 审查外传**改动文件路径、diff hunk、以及diff 里相关的文件内容**。
- agentic commit 审查**额外外传它为追数据流而读到的任何文件**。
- `claude-security-guidance.md` 的内容（user / project / local 三处）**每次审查都追加到 prompt**——所以别把密钥写进去。
- 数据去向取决于配置：默认到 `api.anthropic.com`（适用 Anthropic 商业条款）；设了 `ANTHROPIC_BASE_URL` 则到你的 gateway（**运营方条款适用**）；Bedrock / Vertex / Foundry / Mantle 则到对应 provider（**其数据处理条款适用**）。
- 自己的 debug 日志只含 diffstate 元数据与发现类别，**不含完整文件内容与模型 prompt**，1MB 轮转，**不上传**。

## Two Rules Against Noise

官方给的降噪手段比机制本身更实用：

- **要静音某一条发现**：在该行加注释说明为什么安全——**LLM reviewer 会把行内解释当作排除项**。
- **系统性排除**：写进 `claude-security-guidance.md`（可放 `~/.claude/`、`<project>/.claude/` 或local）。
- **误报太多**：把 `SECURITY_REVIEW_MODEL` 降到 `claude-sonnet-4-6`；**若优先精确率，就留在 Opus 4.7**。

## How This Differs From The Auto Classifier

这是两套并行且互补的机制——同一个插件仓库里同时能读到它们：

| | security-guidance 三层 | auto 模式 classifier |
| :--- | :--- | :--- |
| 判定对象 | **代码内容** | **动作意图**（要跑什么命令、改什么） |
| 判定方式 | 正则 + LLM 读 diff + agent 追数据流 | 独立 classifier 模型读用户消息与工具调用 |
| 时机 | 编辑时、turn 结束时、commit/push 时 | 动作执行前 |
| 覆盖 | 具体漏洞类（注入、XSS、反序列化…） | 越权、瞄准不认识的基础设施、被敌意内容驱动的动作 |
| 能否跨文件 | 第 3 层能（`Read`/`Grep`/`Glob`） | 不能——**工具结果被剥掉**，它看不到工具返回的内容 |

最关键的一条互补关系：**classifier 的审查范围里工具结果被剥掉**，所以它天然无法发现「代码里有漏洞」这类问题；而 security-guidance 读的是 diff 与文件内容。反过来 security-guidance 不判断意图，无法拦住「把密钥 POST 到攻击者地址」这种合法工具调用。**两者都必须有**——这也是为什么官方同时提供这两个机制。

## It Is A Best-Effort Tool

README 的免责声明写得很直接，值得原样记住其态度：

> 这是尽力而为的辅助工具，**不是保证**。把发现当作建议，而不是人类代码评审、SAST/DAST、依赖扫描或渗透测试的替代品。reviewer 可能漏报、可能误报、也可能在不同代码库、语言与模型版本上表现不同。**不提供任何保证。**

对一个官方出品的自动安全检查器来说，明说「不提供保证」而不是暗示自己可靠，这是值得记的态度。

## Links

- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)

## References

- [`plugins/security-guidance/` 官方实现](https://github.com/anthropics/claude-code/tree/main/plugins/security-guidance)
- [插件 README（三层架构与配置）](https://github.com/anthropics/claude-code/blob/main/plugins/security-guidance/README.md)
- [`hooks/patterns.py` 26 条规则定义](https://github.com/anthropics/claude-code/blob/main/plugins/security-guidance/hooks/patterns.py)
- [`hooks/hooks.json` 接法](https://github.com/anthropics/claude-code/blob/main/plugins/security-guidance/hooks/hooks.json)
- [`hooks/_base.py` 共享基类与注入防御](https://github.com/anthropics/claude-code/blob/main/plugins/security-guidance/hooks/_base.py)