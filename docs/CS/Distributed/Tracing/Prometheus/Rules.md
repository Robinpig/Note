## Introduction

[Rules](/docs/CS/Distributed/Tracing/Prometheus/Rules.md) 讲规则引擎的实现：recording rule 与 alerting rule 如何被调度评估、告警状态机（Inactive → Pending → Firing）如何迁移、过期序列如何打 stale 标记、告警如何送达 Alertmanager。它是 PromQL 引擎最重要的内嵌消费方。

> [!NOTE]
> 源码级笔记。代码事实基于 `prometheus/prometheus` **v3.16.0**（commit `e2e28adeee2c5883d000fc82aca6008cfbf7e96d`）。讲解直接贴真实源码，路径相对仓库根，不再标注行号。

## Manager 与 Group

`rules.Manager` 管理所有规则组；配置加载（`/-/reload`）时 `Update` 对比新旧组，组名/规则没变的组**保留运行时状态**继续跑（告警的 ActiveAt、recording 序列不丢），只有真正变化的组才重建。每个 `Group` 一个 goroutine：

```go
func (g *Group) run(ctx context.Context) {
	defer close(g.terminated)

	// Wait an initial amount to have consistently slotted intervals.
	evalTimestamp := g.EvalTimestamp(time.Now().UnixNano()).Add(g.interval)
	select {
	case <-time.After(time.Until(evalTimestamp)):
	case <-g.done:
		return
	}
	// ...
	// The assumption here is that since the ticker was started after having
	// waited for `evalTimestamp` to pass, the ticks will trigger soon
	// after each `evalTimestamp + N * g.interval` occurrence.
	tick := time.NewTicker(g.interval)
	defer tick.Stop()
	// ...
}
```

关键在第一行注释：组不是「启动即评估」，而是先等到下一个 `interval` 的整倍数时刻——**所有组的评估都对齐到全局时间槽**。这正是 `evaluation_interval` 文档行为的实现：15s 间隔意味着所有组都在 ：00/:15/:30/:45 边界附近评估，而不是各自随机漂移。

## Group.Eval：一次评估的事务

`Eval` 逐条规则求值、追加样本、统计错误类型；函数后半段做了一件容易忽略的事——**陈旧序列清理**：

```go
		for metric, lset := range g.seriesInPreviousEval[i] {
			if _, ok := seriesReturned[metric]; !ok {
				// Series no longer exposed, mark it stale.
				_, err = app.Append(0, lset, 0, timestamp.FromTime(ts.Add(-ruleQueryOffset)), math.Float64frombits(value.StaleNaN), nil, nil, g.appOpts)
				unwrappedErr := errors.Unwrap(err)
				if unwrappedErr == nil {
					unwrappedErr = err
				}
				switch {
				case unwrappedErr == nil:
				case errors.Is(unwrappedErr, storage.ErrOutOfOrderSample),
					errors.Is(unwrappedErr, storage.ErrTooOldSample),
					errors.Is(unwrappedErr, storage.ErrDuplicateSampleForTimestamp):
					// Do not count these in logging, as this is expected if series
					// is exposed from a different rule.
				default:
					logger.Warn("Adding stale sample failed", "sample", lset.String(), "err", err)
				}
			}
		}
```

`seriesInPreviousEval` 记住上次评估产出的全部序列；这次没再产出的序列立即补一条 StaleNaN——与抓取侧目标下线的处理完全同构。所以**修改 recording rule 的标签定义后，旧序列会优雅消失**而不是永远停在旧值上。规则组被删除/规则改名时还有一层兜底：`run` 的 defer 里把 `seriesInPreviousEval` 全部转为 stale，等 2 个 interval 给改名规则留出重建窗口。

## 告警状态机

`AlertingRule.Eval` 维护 `active map[uint64]*Alert`（键是标签集哈希）。状态迁移的完整逻辑在评估循环里：

```go
	numActivePending int
	// Check if any pending alerts should be removed or fire now. Write out alert timeseries.
	for fp, a := range r.active {
		if _, ok := resultFPs[fp]; !ok {
			// There is no firing alerts for this fingerprint. The alert is no
			// longer firing.

			// Use keepFiringFor value to determine if the alert should keep
			// firing.
			var keepFiring bool
			if a.State == StateFiring && r.keepFiringFor > 0 {
				if a.KeepFiringSince.IsZero() {
					a.KeepFiringSince = ts
				}
				if ts.Sub(a.KeepFiringSince) < r.keepFiringFor {
					keepFiring = true
				}
			}

			// If the alert is resolved (was firing but is now inactive) keep it for
			// at least the retention period. This is important for a number of reasons:
			//
			// 1. It allows for Prometheus to be more resilient to network issues that
			//    would otherwise prevent a resolved alert from being reported as resolved
			//    to Alertmanager.
			//
			// 2. It helps reduce the chance of resolved notifications being lost if
			//    Alertmanager crashes or restarts between receiving the resolved alert
			//    from Prometheus and sending the resolved notification. This tends to
			//    occur for routes with large Group intervals.
			if a.State == StatePending || (!a.ResolvedAt.IsZero() && ts.Sub(a.ResolvedAt) > resolvedRetention) {
				delete(r.active, fp)
			}
			if a.State != StateInactive && !keepFiring {
				a.State = StateInactive
				a.ResolvedAt = ts
			}
			if !keepFiring {
				continue
			}
		} else {
			// The alert is firing, reset keepFiringSince.
			a.KeepFiringSince = time.Time{}
		}
		numActivePending++

		if a.State == StatePending && ts.Sub(a.ActiveAt) >= r.holdDuration {
			a.State = StateFiring
			a.FiredAt = ts
		}

		// If the alert is firing and the active time is less than the new hold duration, set the state to pending.
		if a.State == StateFiring && ts.Sub(a.ActiveAt) < r.holdDuration {
			a.State = StatePending
			a.FiredAt = time.Time{}
			a.LastSentAt = time.Time{}
			a.KeepFiringSince = time.Time{}
		}
		// ...
	}
```

由此可读出状态机的全部规则：

| 迁移 | 条件 |
| --- | --- |
| Inactive → Pending | 表达式命中，新 Alert 以 `StatePending` 建档，记 `ActiveAt` |
| Pending → Firing | 持续命中 ≥ `for`（`holdDuration`） |
| Firing → Inactive | 条件消失且超过 `keep_firing_for` |
| Pending 直接删除 | 条件消失（还没来得及触发） |

两个易错点：① `keep_firing_for` 只是延迟转 Inactive，期间告警仍按 Firing 重复通知——它是「抖动抑制」不是「恢复延迟」；② 最后那个反向迁移（Firing → Pending）处理的是**配置热更新把 `for` 调大**的场景：已触发告警若发现 `ActiveAt` 距今不足新 holdDuration，会被降级回 Pending 并清空 FiredAt/LastSentAt，防止改配置瞬间把未满足新时长的告警当已触发。

## 送达 Alertmanager

`Group.Eval` 里每轮对告警规则调用：

```go
		if ar, ok := rule.(*AlertingRule); ok {
			ar.sendAlerts(ctx, ts, g.opts.ResendDelay, g.interval, g.opts.NotifyFunc)
		}
```

`NotifyFunc` 在 `main.go` 装配为 `rules.SendAlerts(notifierManager, externalURL)`，最终走 `notifier.Manager` 的 HTTP 客户端把 alert 批量 POST 给 Alertmanager。`ResendDelay` 控制 Firing 告警的重发频率（避免每轮 evaluation 都重发）；Pending/Firing 状态本身也会写成 `ALERTS{alertstate="pending|firing"}` 序列，可以用 PromQL 直接查告警历史。

## 并发评估与恢复

`ManagerOptions` 里的 `MaxConcurrentEvals` / `ConcurrentEvalsEnabled`（3.x 新特性）允许同组规则并发求值——此前组内是严格串行的，一条慢查询会拖住整组告警。Prometheus 重启时告警状态从 TSDB 恢复：评估前查回旧样本重建 `ActiveAt`，避免重启导致所有告警重新走 `for` 等待（这就是「重启后告警不抖」的机制）。

## Links

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [PromQL Engine](/docs/CS/Distributed/Tracing/Prometheus/Promql.md)
- [TSDB](/docs/CS/Distributed/Tracing/Prometheus/Tsdb.md)
- [Scrape](/docs/CS/Distributed/Tracing/Prometheus/Scrape.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)

## References

1. [prometheus/prometheus v3.16.0 source](https://github.com/prometheus/prometheus/tree/v3.16.0)
2. [Alerting rules documentation](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
3. [Keep firing for behavior](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/#keeping-alerts-firing-when-the-condition-becomes-untrue)
