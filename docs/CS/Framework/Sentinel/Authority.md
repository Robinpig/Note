## Introduction

授权控制（Authority Control）按**调用来源（origin）**对资源做黑白名单限制，由链上的 `AuthoritySlot` 执行。它是五种防护能力里最轻量、最前置（位于 `StatisticSlot` 之后、`SystemSlot` 之前）的一个。来源 `origin` 由 `ContextUtil.enter(name, origin)` 在入口处指定，通常取服务消费方的应用名或来源 IP。

## AuthorityRule

`AuthorityRule` 关键字段：

| 字段 | 含义 |
| :--- | :--- |
| `resource` | 受控资源名 |
| `limitApp` | 来源标识（如调用方应用名） |
| `strategy` | `AUTHORITY_WHITE`（白名单）/ `AUTHORITY_BLACK`（黑名单） |

判定逻辑：

- **白名单（WHITE）**：仅当请求来源 `origin` **命中** `limitApp` 时才放行，其它来源一律拒绝（`AuthorityException`）。
- **黑名单（BLACK）**：当请求来源 `origin` **命中** `limitApp` 时拒绝，其它来源放行。

## 配置示例

```java
// 白名单：只允许来自 app-A 的调用访问 resourceX
AuthorityRule white = new AuthorityRule();
white.setResource("resourceX");
white.setLimitApp("app-A");
white.setStrategy(AuthorityRule.AUTHORITY_WHITE);

// 黑名单：拒绝来自 app-B 的调用访问 resourceY
AuthorityRule black = new AuthorityRule();
black.setResource("resourceY");
black.setLimitApp("app-B");
black.setStrategy(AuthorityRule.AUTHORITY_BLACK);

AuthorityRuleManager.loadRules(Arrays.asList(white, black));
```

> [!NOTE]
> `limitApp` 支持逗号分隔的多个来源（如 `"app-A,app-C"`），命中集合中任一即视为命中。若需要更灵活的匹配（如正则），可结合 [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md) 中按 `limitApp` 维度的流控，或自定义 Slot。

## 与流控「按调用方限流」的区别

[流控 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md) 也能用 `limitApp` 按来源设不同阈值，但那是「**限多少**」（QPS/线程数）；授权控制只回答「**允不允许**」（黑白名单）。二者可叠加：先用 `AuthoritySlot` 做准入，再用 `FlowSlot` 做额度控制。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Architecture.md)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)

## References

1. [Authority Control (官方文档)](https://sentinelguard.io/en-us/docs/authority-control.html)
