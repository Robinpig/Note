







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

\# 添加 MCP 服务器 claude mcp add filesystem – npx -y @anthropic-ai/mcp-server-filesystem /path/to/project # 查看已配置的服务器 claude mcp list









