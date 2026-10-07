## Introduction

Electron 是用 Web 技术（HTML/CSS/JavaScript）开发**跨平台桌面应用**的框架，由 GitHub 为 Atom 编辑器开发，VS Code、Slack、Discord、Postman 都基于它。核心做法是把 **Chromium 渲染进程**和 **Node.js 运行时**一起打包进应用：UI 用前端技术渲染，系统能力（文件、进程、原生菜单）由 Node.js 提供，开发者不必为 Windows/macOS/Linux 各写一套原生代码。

## Multi-process Architecture

Electron 沿用 Chromium 的多进程模型，并有明确的职责划分：

| 进程 | 技术能力 | 职责 |
|------|---------|------|
| 主进程（Main） | 完整 Node.js + 原生 API | 应用入口、创建 BrowserWindow、生命周期、系统菜单、文件系统 |
| 渲染进程（Renderer） | Chromium + 默认受限的 Node | 每个窗口一个，跑 Web 页面 UI |
| Preload 脚本 | 沙箱内运行，可访问部分 Node API | 桥接：通过 contextBridge 向页面暴露**白名单**方法 |

进程间通过 IPC 通信：`ipcMain.handle` / `ipcRenderer.invoke`（请求-响应，Promise 风格）或 `webContents.send`（事件推送）。这与浏览器内部的进程隔离原理一致，参见 [浏览器多进程模型](/docs/CS/Browser/Browser.md)。

## Security Model (Common Pitfalls)

Electron 早期允许渲染进程直接用 Node.js（`nodeIntegration: true`），相当于让网页拥有完整本机权限，XSS 即 RCE。现代安全基线：

- `nodeIntegration: false` + `contextIsolation: true`（默认）：页面 JS 碰不到 Node；
- 只在 preload 中通过 `contextBridge.exposeInMainWorld` 暴露最小 API，且对参数做校验；
- `sandbox: true` 进一步限制 preload；
- 加载远程内容时配置 CSP、禁止 `webSecurity: false`、`allowRunningInsecureContent: false`；
- 导航与新窗口用 `will-navigate`/`setWindowOpenHandler` 白名单管控，防钓鱼跳转。

## Engineering Issues

- **体积与内存**：每个应用自带整套 Chromium + Node，安装包 80MB 起步、每个窗口都是独立渲染进程，内存占用高。轻量化替代有 Tauri（系统 WebView + Rust 后端，安装包数 MB）、Wails（Go）。
- **自动更新**：electron-updater + 静态文件服务器/GitHub Release，差量更新与签名公证（macOS notarization、Windows 代码签名）是发布硬门槛。
- **原生模块**：含 C++ 的 npm 包要按 Electron 的 ABI 重新编译（electron-rebuild）。
- 打包：electron-builder/electron-forage 产出各平台安装包（dmg/nsis/AppImage）。

## Links

- [Nodejs](/docs/CS/front-end/Nodejs.md)
- [Webpack](/docs/CS/front-end/Webpack.md)
- [浏览器原理](/docs/CS/Browser/Browser.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md)

## References

1. [Electron 官方文档](https://www.electronjs.org/docs/latest/)
2. [Electron Security Checklist](https://www.electronjs.org/docs/latest/tutorial/security)
