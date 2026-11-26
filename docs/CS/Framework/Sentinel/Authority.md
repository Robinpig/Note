## Introduction

授权控制（Authority Control）按**调用来源（origin）**对资源做黑 / 白名单准入，由链上的 `AuthoritySlot` 执行。origin 由 `ContextUtil.enter(name, origin)` 在入口处指定，通常取消费方应用名或来源 IP。从 Slot 顺序（`ORDER_STATISTIC_SLOT=-7000` → `ORDER_AUTHORITY_SLOT=-6000` → `ORDER_SYSTEM_SLOT=-5000` → `ORDER_FLOW_SLOT=-2000`）看，它位于 `StatisticSlot` 之后、`SystemSlot` 之前：统计已开始、但额度判断还没做，正好适合做「先准入、再限流」的第一道门。

> 版本基线：Sentinel 1.8.10

## AuthoritySlot: A Thin Dispatch Layer

`AuthoritySlot` 的 `entry()` 只调 `checkBlackWhiteAuthority(resourceWrapper, context)` 再 `fireEntry`。后者从 `AuthorityRuleManager.getRules(resource.getName())` 取该资源的规则（为 `null` 直接返回），逐条交给 `AuthorityRuleChecker.passCheck`；只要有一条返回 `false`，就抛 `AuthorityException(context.getOrigin(), rule)` 阻断请求。

```java
@Override
public void entry(Context context, ResourceWrapper resourceWrapper, DefaultNode node, int count, boolean prioritized, Object... args)
    throws Throwable {
    checkBlackWhiteAuthority(resourceWrapper, context);
    fireEntry(context, resourceWrapper, node, count, prioritized, args);
}

@Override
public void exit(Context context, ResourceWrapper resourceWrapper, int count, Object... args) {
    fireExit(context, resourceWrapper, count, args);
}

void checkBlackWhiteAuthority(ResourceWrapper resource, Context context) throws AuthorityException {

    List<AuthorityRule> rules = AuthorityRuleManager.getRules(resource.getName());
    if (rules == null) {
        return;
    }

    for (AuthorityRule rule : rules) {
        if (!AuthorityRuleChecker.passCheck(rule, context)) {
            throw new AuthorityException(context.getOrigin(), rule);
        }
    }
}
```

注意 `AuthorityException` 的两个入参分别是**请求来源**和**触发的规则**；异常重写了 `fillInStackTrace()` 返回自身（不填栈以省开销），并可用 `getRule()` 取回规则（1.4.2+）。

源文件：`sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthoritySlot.java`

## passCheck: The Real Black / White Semantics

判定语义全在 `AuthorityRuleChecker.passCheck`，必须按源码逐行读——旧笔记「白名单命中才放行、黑名单命中就拒绝、limitApp 支持逗号分隔」的大方向没错，但漏掉了几个关键细节：

```java
static boolean passCheck(AuthorityRule rule, Context context) {
    String requester = context.getOrigin();

    // Empty origin or empty limitApp will pass.
    if (StringUtil.isEmpty(requester) || StringUtil.isEmpty(rule.getLimitApp())) {
        return true;
    }

    // Do exact match with origin name.
    int pos = rule.getLimitApp().indexOf(requester);
    boolean contain = pos > -1;

    if (contain) {
        boolean exactlyMatch = false;
        String[] appArray = rule.getLimitApp().split(",");
        for (String app : appArray) {
            if (requester.equals(app)) {
                exactlyMatch = true;
                break;
            }
        }

        contain = exactlyMatch;
    }

    int strategy = rule.getStrategy();
    if (strategy == RuleConstant.AUTHORITY_BLACK && contain) {
        return false;
    }

    if (strategy == RuleConstant.AUTHORITY_WHITE && !contain) {
        return false;
    }

    return true;
}
```

按源码得到的准确语义：

- **空 origin 或空 limitApp 直接放行**。第一道 `if` 明确 `return true`：入口没传 origin（`ContextUtil.enter(name)` 不填第二参），授权控制就完全不生效；`limitApp` 为空同样不生效。这是旧笔记没写、但生产上最容易踩的点。
- **「命中」是精确匹配，不是子串**。`indexOf(requester)` 只是先做一次子串预筛（性能优化）；真正判定是把 `limitApp` 按逗号 `split(",")`，再用 `requester.equals(app)` 逐项**精确比较**。所以 `"appA"` 不会命中 `"appA-extra"`，命中集合是逗号分隔的完整 token。注意代码**未 trim**：`"appA, appB"` 的第二个 token 是带前导空格的 `" appB"`。
- **黑白名单判定**：黑名单 `AUTHORITY_BLACK` 且命中 → `false`（拒绝）；白名单 `AUTHORITY_WHITE` 且未命中 → `false`（拒绝）；其余情况 `true`（放行）。即「白名单命中才放行、黑名单命中就拒绝」——但前提是 origin 与 limitApp 都非空。
- **所有规则都要通过**。`AuthoritySlot` 是逐条 `passCheck`，任一条返回 `false` 立即抛异常。

> [!NOTE]
> 规则加载侧还有两道处理（`AuthorityRuleManager.loadAuthorityConf`）：`limitApp` 为空会被填成 `RuleConstant.LIMIT_APP_DEFAULT`（即 `"default"`）；`isValidRule` 要求 `resource` 非空、`strategy >= 0`、`limitApp` 非空且资源名符合正则规则；**同一资源只保留第一条规则**，后续重复规则会被警告并忽略。所以实际进入 `passCheck` 的 `limitApp` 通常非空，但空 origin 仍会导致直接放行。

源文件：`sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthorityRuleChecker.java`

## AuthorityRule Fields

`AuthorityRule` 关键字段（`strategy` 默认 `AUTHORITY_WHITE`）：

| 字段 | 含义 |
| :--- | :--- |
| `resource` | 受控资源名 |
| `limitApp` | 来源标识，支持逗号分隔多个（精确 token 匹配） |
| `strategy` | `AUTHORITY_WHITE`（0，白名单）/ `AUTHORITY_BLACK`（1，黑名单） |

`strategy` 常量定义在 `RuleConstant`：`AUTHORITY_WHITE = 0`、`AUTHORITY_BLACK = 1`（注意它与流控的 `RuleConstant` 共用同一文件，别和 `LIMIT_APP_DEFAULT` 混淆）。

## Configuration Example

```java
// 白名单：只允许来自 app-A 的调用访问 resourceX
AuthorityRule white = new AuthorityRule();
white.setResource("resourceX");
white.setLimitApp("app-A");
white.setStrategy(RuleConstant.AUTHORITY_WHITE);

// 黑名单：拒绝来自 app-B、app-C 的调用访问 resourceY
AuthorityRule black = new AuthorityRule();
black.setResource("resourceY");
black.setLimitApp("app-B,app-C");
black.setStrategy(RuleConstant.AUTHORITY_BLACK);

AuthorityRuleManager.loadRules(Arrays.asList(white, black));
```

调用方必须在 `ContextUtil.enter("resourceX", "app-A")` 传入 origin，否则 `passCheck` 因空 origin 直接放行，规则形同虚设。

## Difference from FlowControl limitApp

[流控 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md) 也能用 `limitApp` 按来源设不同阈值，但那回答的是「**限多少**」（QPS / 线程数）；授权控制回答的是「**允不允许**」（黑 / 白名单准入）。二者可叠加：先用 `AuthoritySlot` 做准入，再用 `FlowSlot` 做额度控制。两者的 `limitApp` 是各自规则里的独立字段，语义与匹配方式并不共用。

## Links

- [Sentinel 枢纽](/docs/CS/Framework/Sentinel/Sentinel.md)
- [架构与工作原理](/docs/CS/Framework/Sentinel/Sentinel.md?id=architecture)
- [Slot 机制](/docs/CS/Framework/Sentinel/Slot.md)
- [流量控制 FlowControl](/docs/CS/Framework/Sentinel/FlowControl.md)
- [统计节点 Node](/docs/CS/Framework/Sentinel/Node.md)
- [系统自适应保护 SystemAdaptive](/docs/CS/Framework/Sentinel/SystemAdaptive.md)

## References

- <https://sentinelguard.io/en-us/docs/authority-control.html>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthoritySlot.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthorityRuleChecker.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthorityRuleManager.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthorityRule.java>
- <https://github.com/alibaba/Sentinel/blob/1.8.10/sentinel-core/src/main/java/com/alibaba/csp/sentinel/slots/block/authority/AuthorityException.java>
