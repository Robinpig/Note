# Compatibility Guard

## Introduction

Silo 官方把设计原则写成一句话：*"the product and its delivery surfaces are renamed; the protocol and your data are not."* 这句话如果只是口号，半年后必然失守——因为"改名"这件事天然会侵蚀协议面：有人为了统一品牌把 `x-minio-*` 头改成 `x-silo-*`，有人把 `minio_*` 指标改名以至于 Prometheus 告警全断，有人把 `.minio.sys` 目录改名以至于旧数据盘读不出来。

所以 Silo 把这句话**编译成了三个 CI 守卫**。它们共同的特点是：不靠 review 靠人眼，而是靠程序比对基线快照，偏离即构建失败。这是整个 fork 里最有工程价值、也最值得抄的部分。

| 守卫 | 实现 | 守住什么 |
| :--- | :--- | :--- |
| `rebrand-guard` | Go 工具（AST + 正则）+ JSON 基线 | 协议标识符集合不得漂移 |
| `verify-rebrand.sh` | Shell + grep | 交付面不得残留旧品牌名 |
| `helm-migration-guard` | Go 工具 + YAML 解析 | 升级不得改变 K8s 资源身份 |

三者合起来形成一条完整的防线：**协议面不许变、交付面必须变、升级不许动资源身份**。

## Rebrand Guard: Protocol Identifiers Are Frozen

### How It Works

`buildscripts/rebrand-guard/main.go` 是一个 Go 程序，做法是"扫全仓 → 抽标识符 → 与基线比对"：

```go
const manifestVersion = 4

var (
	minioImportRE = regexp.MustCompile(`github\.com/minio/[A-Za-z0-9_./-]+`)
	envRE         = regexp.MustCompile(`\b_?MINIO_[A-Z0-9_]+\b`)
	metricRE      = regexp.MustCompile(`\bminio_[A-Za-z0-9_]+\b`)
	headerRE      = regexp.MustCompile(`(?i)\bx-minio-[a-z0-9_-]+\b`)
	routeRE       = regexp.MustCompile(`^/[A-Za-z0-9._~!$&'()*+,;=:@%/?{}=-]*`)
	storageRE     = regexp.MustCompile(`\.minio\.sys(?:/[A-Za-z0-9._${}-]+)*`)
	policyRE      = regexp.MustCompile(`(?:arn:minio|minio:s3)[A-Za-z0-9_:/.*${}-]*`)
	brandRE       = regexp.MustCompile(`(?i)(^|[^a-z0-9_])minio([^a-z0-9_]|$)`)
)
```

它遍历仓库所有受版本控制的文件，把标识符归入十类集合：

```go
	sets := map[string]map[string]struct{}{
		"imports": {}, "env": {}, "metrics": {}, "headers": {}, "routes": {},
		"roots": {}, "grid": {}, "storage": {}, "policy": {}, "brand": {},
	}
```

关键在于**提取方式分两路**：

- 正则路：环境变量、指标名、HTTP 头、存储标记、策略值，全仓文本扫描。`metricRE` 只在 `cmd/` 与 `internal/` 下的 `.go` 文件中生效——因为指标只在代码里定义。
- AST 路：`.go` 文件用 `go/parser` 解析，拿到真实的 import 列表与字符串字面量。这比正则可靠得多：

```go
		if strings.HasSuffix(rel, ".go") {
			file, err := parser.ParseFile(fset, path, data, parser.SkipObjectResolution)
			...
			for _, spec := range file.Imports {
				value, err := strconv.Unquote(spec.Path.Value)
				if err == nil && strings.HasPrefix(value, "github.com/minio/") {
					sets["imports"][value] = struct{}{}
				}
			}
```

路由提取还带一条精细的排除规则：

```go
			if !strings.HasSuffix(rel, "_test.go") {
				// Test files hold request paths for fixtures, not served routes.
				collectStringMatches(sets["routes"], routeRE, file)
```

测试文件里的路径是 fixture，不是对外提供的路由，排除掉才不会产生假阳性。同理，grid 路由**只**从 `internal/grid/manager.go` 一个文件里收：

```go
			if rel == "internal/grid/manager.go" {
				collectStringMatches(sets["grid"], routeRE, file)
			}
```

还有两条"人为收窄"：一是跳过迁移说明与守卫自身目录（否则守卫的测试样例会污染基线）：

```go
		// Migration notes and guard fixtures contain archived identifiers.
		if rel == "SILO_REBRANDING_MIGRATION.md" ||
			strings.HasPrefix(rel, "buildscripts/rebrand-guard/") ||
			strings.HasPrefix(rel, "buildscripts/helm-migration-guard/") {
			continue
		}
```

二是显式剔除一个假环境变量：

```go
	// This was a shell-local PID variable in the generated inspect script,
	// never a supported environment setting.
	delete(sets["env"], "MINIO_SRVR_PID")
```

最后与 `compat-baseline.json` 比对；`--write` 参数可重新生成基线。CI 里跑的是比对模式，输出固定为 `"Silo rebrand compatibility baseline is unchanged"`。

### What the Baseline Locks

基线快照（`buildscripts/rebrand-guard/compat-baseline.json`，version 4）里的规模能说明这套守卫的覆盖面：

| 类别 | 条目数 | 样例 |
| :--- | :--- | :--- |
| `module_path` | 1 | `github.com/minio/minio` |
| `minio_imports` | 119 | `github.com/minio/minio-go/v7`、`github.com/minio/console/api` |
| `environment` | 428 | `MINIO_ACCESS_KEY`、`MINIO_API_CORS_ALLOW_ORIGIN` |
| `metrics` | 27 | `minio_bucket`、`minio_heal`、`minio_inter_node` |
| `headers` | 86 | `x-minio-deployment-id`、`x-minio-internal` |
| `routes` | 225 | `/admin`、`/add-canned-policy`、`/api/requests` |
| `route_roots` | 1 | `cmd/generic-handlers.go:minioReservedBucket=minio` |
| `grid_routes` | 3 | `/`、`/minio/grid/`、`/minio/grid/lock/` |
| `storage_markers` | 16 | `.minio.sys/format.json`、`.minio.sys/config/config.json` |
| `policy_values` | 59 | `arn:minio:iam:us-east-1::role/my-role` |
| `brand_allowlist` | 181 | 见下 |

428 个环境变量、225 条路由、119 个 import 被逐一冻结——任何一处改名都会让构建红。

### Brand Allowlist: Knowing the Difference

`brand_allowlist` 是这套设计里最见功力的部分。它规定"哪些位置的 `minio` 字样是接口名、不算品牌残留，必须豁免"：

```json
  "brand_allowlist": [
    "cmd/admin-handlers.go=\"MinIO admin API\"",
    "cmd/api-response.go=\"minio\"",
    "cmd/batch-handlers.go=\"minio.New\"",
    "cmd/bucket-handlers.go=\"x-minio-error-code\"",
    "cmd/admin-handlers.go=\"^(.*silo\\s+server\\s+|.*minio\\s+server\\s+)(--[^\\s]+\\s+[^\\s]+\\s+)*(.*)\""
  ]
```

最后一条尤其典型：命令行帮助文本里需要同时出现 `silo server` 与 `minio server` 两种写法，这是**用户可见的兼容入口**，不是品牌残留。没有 allowlist 机制的话，这种"故意保留"和"无意漏改"根本无法区分——守卫要么误报淹没在噪声里，要么被整体关掉。

## Verify Rebrand: Delivery Surface Must Change

反向的守卫是 `buildscripts/verify-rebrand.sh`：它不检查"协议有没有被改"，而是检查"**交付面有没有被忘记改**"。被检查的正是那些会出现在用户环境里的文件：

```bash
for file in \
	.github/goreleaser.yml \
	.github/nfpm.yml \
	buildscripts/package/lifecycle_test.sh \
	buildscripts/verify-helm-migration.sh \
	Dockerfile.goreleaser \
	Dockerfile.distroless \
	dockerscripts/build-static-curl.sh \
	dockerscripts/docker-entrypoint.sh \
	helm/silo/Chart.yaml \
	helm/silo/values.yaml \
	silo.service \
	...
```

它用 `require_text` / `reject_text` 两个原语：前者要求文件**必须**含某个新名字（如 `silo`），后者要求**不得**含某个旧名字（如 `minio/minio` 镜像名）。失败信息直接点出"still contains forbidden delivery text"。

这套脚本还处理了"扫描本身可能失败"的情况——BSD/Linux 的 `git grep` 返回 1 既可能表示无匹配也可能表示读取错误，所以先查 stderr：

```bash
	git --no-pager grep --no-index "${search_ignore}" --no-color -nIHE "$@" 2>"${search_errors}" || status=$?
	# Git can return 1 for both no matches and a file read error. Check stderr
	# as well, before callers filter matches through their allowlists.
	if [ "${status}" -gt 1 ] || [ -s "${search_errors}" ]; then
		cat "${search_errors}" >&2
		fail "could not scan source files")
	fi
```

这一点值得单独记一笔：**把"检查失败"和"检查没找到"混为一谈，是守卫型脚本最常见的失效方式**——工具自己报错，脚本却当成通过。

## Helm Migration Guard: Upgrades Must Not Change Identity

Helm 升级是 fork 最容易出事的地方：改个 chart 模板，用户原有的 PVC 选不上了、Service 端口变了、Secret 名字对不上。`buildscripts/helm-migration-guard/main.go` 的做法是**渲染两份 chart 再逐资源比对**：

```go
// helm-migration-guard compares a rendered legacy MinIO chart with the Silo
// upgrade candidate. Product labels, images, and commands may change; resource
// identity, selectors, PVCs, storage mounts, ports, secrets, and service-account
// references must not.
```

用法是 `helm-migration-guard OLD_RENDER NEW_RENDER`，输出形如：

```
Silo Helm migration identity is stable across N rendered resources
```

判定逻辑落在 `compare()` 上：允许变的是**产品标识、镜像、命令**；不允许变的是**资源身份与引用关系**（selector、PVC、storage mount、port、secret、serviceAccount）。这个划分与 `rebrand-guard` 完全同构——同一套"协议面/交付面"二分法，换了个应用场景。

## Service and Environment Compatibility

systemd 单元是交付面改名与协议面兼容最容易打架的地方，Silo 的解法是**两个环境文件都读**：

```ini
[Unit]
Description=Silo Object Storage Server
Documentation=https://silo.pigsty.com/docs/
Wants=network-online.target
After=network-online.target minio.service
Conflicts=minio.service
AssertFileIsExecutable=/usr/bin/silo

[Service]
Type=notify
User=silo
Group=silo
ProtectProc=invisible

EnvironmentFile=-/etc/default/minio
EnvironmentFile=-/etc/default/silo
ExecStart=/usr/bin/silo server $MINIO_OPTS $MINIO_VOLUMES
```

三个细节值得看：

- `EnvironmentFile=-/etc/default/minio` 的**前导减号**表示"文件不存在也不报错"，于是旧的 `/etc/default/minio` 可以原样继续用。
- `ExecStart` 里的变量名仍是 `$MINIO_OPTS` / `$MINIO_VOLUMES`——**协议面不动**。
- `After=network-online.target minio.service` + `Conflicts=minio.service`：两者互斥且有序，保证同一台机器上不会同时跑起 MinIO 与 Silo 争抢同一块盘。

配套的 `silo.env` 则是"故意为空"：

```sh
# Silo keeps the MINIO_* environment variable interface for compatibility.
# This packaged file intentionally contains no active assignments so values in
# the legacy /etc/default/minio continue to work until an administrator chooses
# to override them here.
#
# MINIO_VOLUMES="/data"
# MINIO_OPTS="--console-address :9001"
# MINIO_ROOT_USER="silo-admin"
# MINIO_ROOT_PASSWORD="replace-with-a-long-random-secret"
```

文件里**没有任何生效的赋值**，只有注释示例。逻辑是：默认继承旧配置，管理员想覆盖再解除注释。这样打包出来的 `silo.env` 不会因为"预置了某个值"而意外覆盖生产环境。

## What the Guard Does Not Cover

必须说清楚这套守卫的边界，否则容易高估它：

- **它锁标识符的存在性，不锁行为等价性**。把 `x-minio-deployment-id` 改成 `x-silo-deployment-id` 会被拦下，但把该头的**语义**改掉不会被发现——那属于协议行为变更，靠 release notes 与安全公告披露。
- **它只看仓库内**。运行时由外部系统发来的请求头、第三方客户端发送的自定义头不在扫描范围。
- **它不覆盖未纳入基线的新标识符**。新增一个 `MINIO_` 开头的环境变量必须同时更新基线（`--write`），这个"更新"动作本身需要 review 兜底——守卫能保证"改与不改"是显式的，不能保证"改得对"。

换句话说：**守卫把"意外的破坏"变成"显式的、可 review 的决定"**，这才是它真正的价值。

## Links

- [Silo（专题枢纽）](/docs/CS/Distributed/Silo.md)
- [Architecture（模块身份与 replace 机制）](/docs/CS/Distributed/Silo/Architecture.md)
- [Release Engineering（守卫在 CI 中的位置）](/docs/CS/Distributed/Silo/Release_Engineering.md)
- [Deployment and Migration（交付面改名的操作手册）](/docs/CS/Distributed/Silo/Deployment_and_Migration.md)
- [MinIO（上游与架构基准）](/docs/CS/Distributed/MinIO.md)

## References

1. [rebrand-guard 主程序（AST + 正则提取协议标识符）](https://github.com/pgsty/silo/blob/main/buildscripts/rebrand-guard/main.go)
2. [compat-baseline.json（协议标识符基线快照）](https://github.com/pgsty/silo/blob/main/buildscripts/rebrand-guard/compat-baseline.json)
3. [verify-rebrand.sh（交付面守卫）](https://github.com/pgsty/silo/blob/main/buildscripts/verify-rebrand.sh)
4. [helm-migration-guard（Helm 升级身份守卫）](https://github.com/pgsty/silo/blob/main/buildscripts/helm-migration-guard/main.go)
5. [silo.service（systemd 交付面）](https://github.com/pgsty/silo/blob/main/silo.service)
6. [silo.env（兼容优先的环境文件模板）](https://github.com/pgsty/silo/blob/main/silo.env)
