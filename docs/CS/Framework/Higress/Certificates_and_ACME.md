## Introduction

自动签发证书是 Higress 的真实能力，且**默认就是开启的**（`automaticHttps: true`）。但 `pkg/cert/`（9 文件、非测试 1588 行）读完会发现：它的实现面比文档叙述窄、比运维直觉脆——challenge 只有 HTTP-01 一条路、续期参数其实是个比例、多副本之间**没有任何互斥**、而"不会覆盖手写 Secret""删掉域名会回收证书"这两条保护性预期在代码里根本不成立。基准 v2.2.5，行号可复核；本节所有涉及凭据的地方只写字段名与机制，不写任何密钥内容。

## Configuration Surface

配置载体是 ConfigMap `higress-https`（`pkg/cert/config.go:33`、`controller.go:35`），**data key 是 `cert`、内容是 YAML**（`config.go:34`）。顶层结构 `Config` 六个字段（`config.go:47-54`）：

| json tag | 类型 | 默认值 | 位置 |
| --- | --- | --- | --- |
| `automaticHttps` | bool | **`true`** | `config.go:48`，默认来自 `:297` |
| `fallbackForInvalidSecret` | bool | `false` | `:49`、`:298` |
| `renewBeforeDays` | int | 30（`DefaultRenewBeforeDays`，`:35`） | `:50` |
| `credentialConfig` | []CredentialEntry | 空 | `:51` |
| `acmeIssuer` | **[]ACMEIssuerEntry（数组）** | 单元素 letsencrypt | `:52`、`:289-294` |
| `version` | string | `time.Now().Format("20060102030405")` | `:53`、`:302` |

`CredentialEntry`（`:154-159`）是 `domains` / `tlsIssuer` / `tlsSecret` / `cacertSecret`；`ACMEIssuerEntry`（`:161-166`）是 `name` / `email` / `ak` / `sk`，其中 AK/SK 的行内注释逐字是 "Only applicable for certain issuers like 'aliyunssl'"。

issuer 枚举只有两个值（`:42-43`）：`letsencrypt` 与 `aliyunssl`。但 **`Validate()` 的 switch 只列了 letsencrypt，`default` 分支直接报错**（`:107-117`）⇒ `aliyunssl` 连同它的 AK/SK 是**未实现且会被拒绝**的死配置，`acmeIssuer` 有数组的形态却只有单值的语义。

三条校验行为值得记住：`renewBeforeDays` 的上限是**硬报错而不是 clamp**，且判定写的是 `>= RenewMaxDays`，所以 **90 本身也非法、合法区间是 1..89**（`:144-150`）；校验失败会让 `ParseConfigFromConfigmap` 整份返回 error（`:221-223`）、`syncConfigmap` 直接透传（`controller.go:130-133`）——**结果是内存里继续跑旧配置、日志一行 error、且不会重试**（见下一节），"改坏了会即时生效"这句话只对改对的情况成立。`ParseTLSSecret`（`:89-98`）按 `/` 切：一段 → `(空, name)`、两段 → `(ns, name)`、**三段以上返回两个空串**再被 Validate 判非法。域名匹配统一用 Istio 的 `host.Name.SubsetOf` + `strings.ToLower`（`MatchSecretNameByDomain:65-74`、`GetSecretNameByDomain:76-87`），**泛域名 `*.example.com` 能匹配 `a.example.com`，且 `credentialConfig` 按数组顺序先命中先返回**。`version` 字段在 `pkg/cert` 内只写不读，但因 informer 是整对象 `reflect.DeepEqual` 去重（`controller.go:70-72`），手改它等价于一次强制重跑。

## Challenge Path

库是 `certmagic` + `mholt/acmez`（`certmgr.go:23-24`）。**一个必须写进依赖说明的事实**：`go.mod:20` require 的是 `certmagic v0.21.3`，但 `go.mod:318` 有 `replace github.com/caddyserver/certmagic => github.com/2456868764/certmagic v1.0.2`——**实际编进二进制的是一个第三方 fork**，本机 module cache 里也没有它，因此 fork 内所有行为（续期轮询周期、锁语义、进程内去重）不可核对。

`pkg/cert` 自己没有一行 ACME 协议代码，它只做四步：`NewCache`（`certmgr.go:67-75`）→ `certmagic.New`（`:77`）→ `NewACMEIssuer`（`:86-93`）→ `ManageSync`（`:192-195`）。issuer 参数逐字（`certmgr.go:86-93`）：`CA: LetsEncryptProductionCA`（`:88`，**上一行的 Staging CA 是被注释掉的 ⇒ 不能用配置切到 staging**）、`Email`、`Agreed: true`（`:90`，代码里直接同意条款）、`DisableHTTPChallenge: false`（`:91`）、**`DisableTLSALPNChallenge: true`（`:92`）**、`Http01Solver = ingressSolver`（`:95-96`）。⇒ **只有 HTTP-01，没有 TLS-ALPN-01，本包零 DNS-01 代码。**

HTTP-01 的呈现方式不是本地监听，而是**动态创建一个 Ingress**（`pkg/cert/ingress.go:32-38` 的常量）：class `higress`、backend Service `higress-controller`、端口 **8889**、path 前缀 `/.well-known/acme-challenge/`、名字前缀 `higress-http-solver-`（源码里拼写为 `IngressNamePefix`）。`Present`（`:58-79`）Get 后 Create/Update，对象由 `constructIngress`（`:122-158`）拼，host 直接取 `challenge.Identifier.Value`（`:124`）；`Wait`（`:81-93`）**不检测 Ingress 是否真的生效，只是 `time.After(5s)`**（`ingressDelay:53`）⇒ 传播慢的集群会因这 5 秒不够而签发失败。`CleanUp`（`:95-106`）删掉它。与此同时控制器自己在 `:8889` 起 HTTP server 并用 `am.HTTPChallengeHandler(mux)` 包住 handler（`pkg/cert/server.go:99`；地址默认值 `CertHttpAddress: ":8889"` 在 `pkg/cmd/server.go:93`，可用 `--certHttpAddress` 覆盖）。

> [!WARNING]
> 完整通路是 `LE → 域名:80 → higress class 的 solver Ingress → Service higress-controller:8889 → HTTPChallengeHandler`。因此**域名必须公网 80 可达**：纯内网、无公网 DNS、或 80 不通的域名**不可能签发**，泛域名同理（challenge host 直接是 `*.x.com` 时 HTTP-01 无法呈现）。还有一条自指关系：solver 依赖 Ingress 资源通路，所以若集群只启用 Gateway API 而不走 Ingress，HTTP-01 在原理上就无法完成（未实测，见 Unverified）。

## Renewal Semantics

**`renewBeforeDays` 不是"提前多少天"，而是一个比例。** 初始化时算 `renewalWindowRatio = float64(RenewBeforeDays) / float64(RenewMaxDays)`（`certmgr.go:60`）并塞进 `certmagic.Config.RenewalWindowRatio`（`:63`），每次 reconcile 重算覆盖（`:164-165`）。`RenewMaxDays = 90` 这个常量同时充当**分母**与**校验上限**。默认 30 ⇒ ratio = 1/3，即"剩余生命周期不足总时长 1/3 时续期"；因为 LE 证书正好 90 天，才**碰巧**等于"提前 30 天"。换 CA 或证书时长不是 90 天时，字段名会骗人。

续期定时器不在本包：`cache.Start()`（`certmgr.go:167`）/ `cache.Stop()`（`:175`）由 `automaticHttps` 开关决定，**轮询周期常量在 fork 里**，本地读不到。事件驱动入口只有 `higress-https` 的 Add/Update（`controller.go:159-162`，且按 namespace + 名字双重过滤），**`DeleteFunc` 没注册 ⇒ 删掉 ConfigMap 不触发任何清理**。队列虽然是 RateLimiting 的（`:155`），`enqueue` 用的却是普通 `Add`（`:77`），worker 数 `workNum = 1`（`:33`），而 `ManageSync` 是同步阻塞的（`certmgr.go:171`、`:194`，`ctx` 是不带超时的 `context.Background()`）。

三条失败行为都可复核：签发 / 续期失败**不产生 K8s Event、不写状态**（`OnEvent` 只处理 `cert_obtained`，`certmgr.go:218`，其余走 `:266` 的 `return nil`）；**不重试**——`handleError` 里显式 `c.queue.Forget(key)`（`controller.go:139-143`），常量 `maxRetry = 2`（`:34`）只有声明处一次命中，是死常量；**写 Secret 失败连错误都不向上冒**（`certmgr.go:260-264` 判的是 `err2` 但结尾 `return err`，此时 `err` 是上面 `Load` 留下的 nil）。既有证书在失败路径上不受影响（Secret 只在成功事件里写），但这不是安全设计而是 `cleanSync` 是空实现的副产品——它逐字写着 `//TODO implement clean up domains`（`certmgr.go:197-201`），**所以从配置里删掉域名不会清理 Storage、Secret 或已签证书**。

## Where Certificates Land

落地对象是 `kubernetes.io/tls` Secret，写点 `SecretMgr.Update`（`secret.go:43-73`），`Data` **只有 `tls.key` 与 `tls.crt` 两个键、没有 `ca.crt`**（`:88-99`）——即使 PEM bundle 里有中间证书，本包也只取 `certChain[0]` 算有效期（`certmgr.go:249-254`）。六个 annotation 用于溯源：`higress.io/cert-domain`、`cert-notAfter`、`cert-notBefore`、`cert-renew`、`cert-source`（固定 `letsencrypt`），续期时再加 `cert-renew-time`（`secret.go:76-84`）；写进 annotation 的时间做了 `Truncate(second).Add(1s)`，**与证书真实值差一秒**（`util.go:52-64`）。

Secret 名字**不是按规则生成的，而是用户配的 `credentialConfig[].tlsSecret`**（`certmgr.go:255` → `config.go:76-87`）；**查不到就打一条 error 并 `return nil`，签好的证书被直接丢弃**（`certmgr.go:256-259`）。namespace 默认取控制器自身所在 ns，`tlsSecret` 写成 `ns/name` 时前缀覆盖（`secret.go:47-51`）。

> [!WARNING]
> 三件与直觉相反的事。**① "不会覆盖手写同名 Secret"不成立**：`secret.go:63-66` 的守卫检查的是 `:53` 刚 `constructSecret` 出来的新对象，而构造函数无条件写入判据 annotation（`:77`）⇒ 条件永假、报错永不触发，**集群里已存在的手写同名 Secret 会被整体 Update 覆盖**。**② ACME 的中间态（含私钥）以 JSON 明文写在 ConfigMap 里而不是 Secret**：`ConfigmapStorage` 的产物是 `higress-cert-store-certificates-<fnv32a hash>` 与 `higress-cert-store-default`（`storage.go:35-37`、`:307-317`），data key 是 `fastHash`、value 是 `{"k":原 key,"v":bytes}`（`:48-51`），都带 annotation `higress.io/cert-https=true`，`List` 靠 annotation 的 FieldSelector 捞全量（`:160`）。ConfigMap 与 Secret 的 RBAC 面与加密面都不同，这属于凭据暴露面的实际差异，值得在部署评审里提一句。`Stat` 也不跟踪修改时间，`info.Modified = time.Now()`（`:249`，注释自认）。**③ 只有 `tlsIssuer: letsencrypt` 的条目才进签发队列**（`certmgr.go:133-142`）；**不填 `tlsIssuer` 的条目完全不碰 ACME**，`domains` 只是"域名 → 自备 Secret"的映射表，泛域名在这条路上合法且是主要用法。

## Concurrency

多副本（或 Standalone 与 K8s 混跑）同时签同一批域名时，代码里**没有任何互斥**：certmagic 要求的分布式锁被显式降级为 no-op——`Lock` / `Unlock` 直接 `return nil`（`storage.go:279-286`），而 `storage.go:40` 的接口断言说明这是**故意满足接口**而非漏实现；进程内只有 `sync.RWMutex`（`:45`）与 solver 的 `solversMu`（`ingress.go:43`），跨副本无效。全仓检索 `leaderelection` / `LeaderElection` / `leader-election` / `resourcelock` / `LeaseLock` **五个关键词零命中**。

副本数也没被约束：Helm 的 `controller.automaticHttps.enabled` 默认 **true**（`helm/core/values.yaml:669-672`），autoscaling 默认关但 `maxReplicas: 5`（`:664-667`），每个副本都会无条件跑一遍 `InitCertMgr` + `cache.Start` + `ManageSync`。具体的丢写面：`Store` / `Delete` 是"Get 整个 ConfigMap → 改 Data → Update 全量写回"（`storage.go:81-103`、`:344-352`），**没有 `RetryOnConflict`**，`ApplyConfigmap`（`config.go:262-275`）与 `SecretMgr.Update`（`secret.go:54-70`）同样没有。⇒ **"自动证书建议单副本"这个运维建议在代码侧是有支撑的**，虽然文档没写理由。Standalone / All-in-One 也被打开了：`higress-standalone` 的 `all-in-one/scripts/start-controller.sh:36` 传 `--enableAutomaticHttps=${GATEWAY_AUTO_HTTPS_ENABLED:-true}`、`compose/docker-compose.yml:131` 逐字 `--enableAutomaticHttps=true`（而主仓的 flag 默认值其实是 false，见 [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)）。

关于"留空则随机生成邮箱"：只发生在 `higress-https` 不存在、需要新建默认配置那一次（`config.go:192-194` → `getRandEmail:307-311`），生成的是**不存在的假域名** `your%d@yours%d.com`（域名段少一个字母、疑似 typo）⇒ 收不到任何到期通知；而**已存在的 ConfigMap 里把 email 改成空是硬报错**（`:109-111`），不会重新生成。email 的输入链是 `--automaticHttpsEmail`（`pkg/cmd/server.go:137`，默认 `""`）→ Helm `controller.automaticHttps.email` → `--automaticHttpsEmail=`（`controller-deployment.yaml:62`）。另有一处启动瑕疵：`InitConfig` 在"首次创建成功"的路径上仍然 `return nil, err`（`config.go:201`），而这个 error 会经 `server.go:66-69` → `bootstrap/server.go:451` 冒到构造期（`InitDefaultConfig()` 的返回值在 `:446` 被丢弃，所以第一次建 CM 本身不打日志）。

## Ingress Wiring

自动签发的证书**只有一条消费链**，就在 Ingress → Gateway 的翻译里。`IngressConfig` 无条件持有 `httpsConfigMgr`（`pkg/ingress/config/ingress_config.go:158`、`:236-237`），`convertGateways`（`:502`）**每次转换都现读 ConfigMap**（`:508`），读失败只打 error 并把 nil 传下去（`:509-11`），随后逐 Ingress 调 `ConvertGateway(..., httpsCredentialConfig)`（`:522`）。

`ingressv1/controller.go:444-490` 是落点：`spec.tls` 为空就 `continue`（`:444-447`，**证书只从 Ingress 的 TLS 段起算**）；`extractTLSSecretName` 取到名字后分两支——**分支 A**：名字有值但集群里不存在且 `fallbackForInvalidSecret` 为真，则按域名反查（`:452-470`）；**分支 B**：`spec.tls` 里根本没匹配该 host 的 secret，则直接 `MatchSecretNameByDomain(rule.Host)`（`:471-482`）——**这才是"自动证书被用上"的机制：按域名反查 `higress-https` 的 `credentialConfig`，与 Ingress 自己写没写 secretName 无关**。匹配到就 `domainBuilder.SecretName = path.Join(clusterId, ns, secretName)`（`:489-490`），最终由 Gateway 的 TLS credential 消费、Envoy 侧经 SDS 取（`pkg/cert` 不参与数据面下发）。

> [!NOTE]
> "仅 Ingress 模式生效、Gateway API 不支持"这条文档限制在代码里是**有正面证据的**：对 `pkg/ingress/kube/gateway/`（含 `gateway/istio/` 子树）、`registry/`、`hgctl/` 三个目录检索 `pkg/cert` 与 `higress-https` **零命中**，`cert.Config` 的非测试消费方只有上述四处。Gateway API 的 `certificateRefs` 完全不查这个 ConfigMap。另外 XDS 联动面很窄：只有 `fallbackForInvalidSecret` 或 `credentialConfig` 变化才触发 full push，且要求 `oldConfig != nil`（`certmgr.go:179-187`）⇒ **`automaticHttps` / `renewBeforeDays` / `acmeIssuer.email` 的变化不会推 xDS**，首次启动也不推。

## Unverified

certmagic fork（`github.com/2456868764/certmagic v1.0.2`）本机 module cache 不存在 ⇒ 续期轮询间隔常量、`ManageSync` 的重试策略、per-domain 的进程内去重全部未核。首次冷启动那次 `InitConfig` 返回 NotFound 的真实后果（pod 崩溃重启？被 console 预建的 `higress-https` 掩盖？）未验证，且要看 console 仓（版本线 2.2.5 与主仓 `DEP_VERSION` 的 v2.1.9 不一致）。`cacertSecret`（`config.go:158`）在 `pkg/cert` 外是否有消费点未检索；只有 Gateway API、没有 Ingress 通路时 HTTP-01 是否确实失败未实测；多副本并发的具体失败形态（重复签发 / 互相覆盖 / LE 速率限制）未观测；`List` 依赖的 annotation FieldSelector（`storage.go:160`）在真实 apiserver 上是否被支持未验证；Standalone 无 kube-apiserver 时整个子系统的行为（依赖 `kubernetes.Interface`）未跟踪；`util.go:69-75` 的 `hostOnly` 与 `certmgr.go:42` 的 `mux` 已确认无使用点，但用途属推测。

## Links

- [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)
- [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)
- [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md)
- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [全局配置说明](https://higress.ai/docs/latest/user/configmap/)
- [配置路由指向 HTTPS 服务](https://higress.ai/docs/latest/ops/how-tos/https-upstream/)
- [caddyserver/certmagic](https://github.com/caddyserver/certmagic)
- [mholt/acmez](https://github.com/mholt/acmez)
- [Let's Encrypt RFC8555 Profiles](https://letsencrypt.org/docs/)
