## Introduction

MCP（模型上下文协议）是一个开源标准，用于将人工智能应用与外部系统连接起来。通过MCP，像Claude或ChatGPT这样的AI应用可以连接数据源（如本地文件、数据库）、工具（如搜索引擎、计算器）和工作流程（如专门提示）——使它们能够访问关键信息并执行任务。可以把MCP想象成AI应用的USB-C接口。正如USB-C提供了连接电子设备的标准化方式，MCP也提供了将AI应用与外部系统连接的标准化方式

**MCP能实现什么？**

- 客服可以访问您的Google日历和Notion，作为更个性化的AI助手。
- Claude Code 可以基于 Figma 设计生成整个网页应用。
- 企业聊天机器人可以连接组织内多个数据库，使用户能够通过聊天分析数据。
- AI模型可以在Blender上创建3D设计，并用3D打印机打印出来。



为什么需要MCP？





## Tools

MCP 让 Claude 连接外部工具和数据源。以下是 10 个必装：

**filesystem** - 文件系统读写，访问本地文件
**postgres/sqlite** - 数据库操作，查询和修改数据
**github** - GitHub API，管理 issues 和 PRs
**puppeteer** - 浏览器自动化，网页截图和爬虫
**fetch** - HTTP 请求，调用外部 API
**memory** - 持久化记忆，跨会话保存信息
**sequential-thinking** - 深度思考，复杂问题推理
**exa** - 搜索引擎，获取最新网络信息
**slack/discord** - 消息平台，发送通知
**notion** - 笔记管理，自动更新文档

```
# 添加 MCP 服务器 
claude mcp add filesystem – npx -y @anthropic-ai/mcp-server-filesystem /path/to/project 

# 查看已配置的服务器 
claude mcp list
```








## Links

- [Agent](/docs/CS/AI/LLM/Agent.md)