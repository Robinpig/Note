## Introduction

小程序（Mini Program）是一种**无需下载安装、由超级 App 宿主运行的轻量应用形态**，以微信小程序为代表（支付宝、抖音、百度等均有同类容器）。它在产品上追求「用完即走」，在技术上是一个**受限的混合运行环境**：既不是纯网页（没有完整 DOM、不能随意跳转），也不是原生 App（跑在宿主的 JavaScript 引擎与渲染容器中）。理解它的关键，是理解宿主为安全、性能和生态管控而设下的那层沙箱。

## 技术架构：双线程模型

微信小程序把逻辑与渲染拆到两个线程，这是它与普通网页最大的区别：

| 线程 | 运行内容 | 环境 |
| --- | --- | --- |
| 逻辑层 | JS 业务代码（App Service） | 各平台统一的 JavaScript 引擎（iOS 用 JSCore、安卓曾经用 V8/XWeb），**无 DOM/BOM** |
| 视图层 | 多个 WebView/渲染器，每个页面一个 | WXML + WXSS 渲染 |

两层通过 Native 中转通信（`setData` 序列化数据跨线程传递）。这带来一条核心性能纪律：**不要频繁、大批量 `setData`**——跨线程序列化是渲染开销的主要来源，长列表要配合分页、局部更新与虚拟列表。

这一双线程隔离与 [Browser](/docs/CS/Browser/Browser.md) 的多进程隔离、[Electron](/docs/CS/front-end/Electron.md) 的主/渲染进程分离目标一致：把不可信内容与敏感能力隔开。

## 组成

- **WXML**：类 HTML 的模板语言，数据绑定 `{{ }}`、列表 `wx:for`、条件 `wx:if`，组件化。
- **WXSS**：类 CSS，新增响应尺寸 `rpx`（按屏宽 750 等分，做屏适配）。
- **JS**：页面生命周期（`onLoad/onShow/onReady/onHide/onUnload`）、`Page()`/`Component()`、`setData`。
- **配置**：`app.json`（页面注册、tabBar、窗口）、页面 json、`app.js`（全局逻辑与 `getApp()`）。
- **能力 API**：`wx.*`，调起登录、支付、定位、相机、本地存储、扫码、网络等宿主能力。

## 网络与登录

- 网络请求只能用 `wx.request`（不是 XHR/fetch），且**后端域名必须在管理后台配置 HTTPS 白名单**（开发期可关闭校验）——这是平台管控，不是代码问题。
- 登录是宿主特有链路：`wx.login` 拿临时 `code` → 发到自家后端 → 后端用 code 换 `openid/session_key`（微信侧身份）→ 自家后端签发业务态 token（JWT 等）。**openid 是用户在该小程序下的唯一标识**，不要在前端直接用 `session_key`。这套机制与 [Security](/docs/CS/Security/Security.md) 中 OAuth「拿授权码换令牌」形似，但凭证体系是微信私有的。

## 生态与跨端

| 方案 | 思路 |
| --- | --- |
| 原生微信小程序 | WXML/WXSS + JS，能力最全、限制最直接 |
| 跨端框架（Taro、uni-app） | 用 React/Vue 写法，编译到微信/支付宝/抖音/H5/[RN 风格原生](/docs/CS/Flutter.md)，抹平多平台差异 |
| 小程序云开发（CloudBase） | 宿主提供 serverless 云函数 + 数据库，免自建后端 |

小程序与 [Flutter](/docs/CS/Flutter.md)、[Electron](/docs/CS/front-end/Electron.md) 同属「跨端」大家族，但形态不同：Flutter 自绘 UI、Electron 跑完整 Web 栈，小程序则是**寄生在超级 App 里的受限容器**，用能力受限换取零安装分发与社交裂变（分享、公众号挂载、扫码入口）。

## 适用边界

- 适用：低频/中频工具与服务、交易与营销闭环、强依赖社交分享与线下扫码的场景。
- 谨慎：重交互/重动画/长时间后台运行、需要大量本地计算或系统级能力、不愿受平台审核与规则约束的产品。

## WeChat

[微信小程序示例](https://github.com/wechat-miniprogram/miniprogram-demo)

## Links

- [Browser](/docs/CS/Browser/Browser.md) — Web 渲染、多进程隔离的对照
- [Electron](/docs/CS/front-end/Electron.md) — 另一种受限/进程分离容器
- [Flutter](/docs/CS/Flutter.md) — 自绘式跨端方案
- [Serverless](/docs/CS/SE/Serverless.md) — 小程序云开发的底座

## References

