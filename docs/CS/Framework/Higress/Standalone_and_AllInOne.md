## Introduction

独立部署形态在文档里只有一段安装命令，但它其实是 Higress 最不寻常的一块工程：**在没有任何 Kubernetes 的机器上，自己实现一个 apiserver，让控制面以为自己还在监听 CRD**。基准是第二个仓 `higress-standalone`（`git describe` = **`aio-v2.2.5`**，HEAD `3688250`，2026-10-05），跨到主仓的结论标注主仓路径。关键源码直接抄在正文里，`路径:行号` 只用于回查，代码块里的 `// ...` 表示节选省略。

文档说"Standalone 用 5 个容器把 K8s 控制面重新演一遍（apiserver / controller / pilot / gateway / console）"——这五件套是对的，但省略了两个关键差异：**默认 profile 实际常驻约 10 个容器**，以及**持久层不是 etcd 而是 Nacos 配置项或本地文件**。

## The Fake apiserver

`src/apiserver` 是 **Kubernetes `sample-apiserver` 的直接 fork**：模块名 `github.com/alibaba/higress/api-server`（`src/apiserver/go.mod:1`），`k8s.io/{apiserver,apimachinery,client-go,component-base}` 全部 pin 在 **v0.31.2**，README 通篇是上游原文。它不是 k3s、不是 kine、不是 envtest，**没有 etcd、没有 kube-apiserver 二进制**。入口 `main.go` 把 RLIMIT_NOFILE 提到 65535，然后走 `server.NewCommandStartHigressServer`（`pkg/cmd/server/start.go`），并把 generic apiserver 的 `SkipOpenAPIInstallation` 设为 true。

对外它就是标准 REST + list/watch/discovery：compose 形态 TLS 端口 8443（`--secure-port 8443` + `--client-ca-file`，`compose/docker-compose.yml:65-72`）、健康检查 `https://127.0.0.1:8443/readyz`（`:96`）。controller / pilot / console 拿 precheck 生成的 **kubeconfig**（含 client 证书）连它——**这就是"控制面不改一行代码就能脱离 K8s"的机制**。认证只有一个 `--auth-enabled` 开关（默认 false），compose 形态根本没传，靠 TLS 客户端证书。

注册的资源约 21 类（`pkg/apiserver/apiserver.go`，generic server 名 `higress-apiserver:152`）：core/v1 的 configmaps / secrets / services / endpoints / pods / nodes / namespaces / endpointslices，apiextensions 的 customresourcedefinitions（`:182` 特判），admissionregistration 两个 webhook configuration，networking.k8s.io 的 ingresses（`:306`）与 ingressclasses（`:310`），Higress 三件套 **wasmplugins / mcpbridges / http2rpcs**，Gateway API 的 gatewayclasses / gateways / httproutes / referencegrants，以及 legacy istio group 的 `envoyfilters`（`:378-385`）。

**CRD 定义是静态内嵌、只读提供的**：`src/apiserver/pkg/storage/customresourcedefinition.go:22` 把 `src/apiserver/pkg/storage/crds/*.yaml`（相对本仓根的写法；前文简写的 `pkg/storage/crds/` 是 apiserver 模块内视角）解码成固定切片，Get 在 `:62`、List 在 `:83`，**不可增删改**。该目录实测恰好 **5 个 YAML**：`gateway.networking.k8s.io_gatewayclasses.yaml`、`gateway.networking.k8s.io_gateways.yaml`、`gateway.networking.k8s.io_httproutes.yaml`、`gateway.networking.k8s.io_referencegrants.yaml`、`networking.istio.io_envoyfilters.yaml`——**不含 wasmplugins 与 mcpbridges**，三件套的 storage 已注册但 schema 不在此处。

上面说的"只读、不可增删改 + watch 恒空"，在 `customresourcedefinition.go:86-124` 里就是这样：

```go
func (s *customResourceDefinitionStorage) Create(
	ctx context.Context,
	obj runtime.Object,
	createValidation rest.ValidateObjectFunc,
	options *metav1.CreateOptions,
) (runtime.Object, error) {
	return nil, apierrors.NewServiceUnavailable("create operation is not supported")
}

func (s *customResourceDefinitionStorage) Watch(ctx context.Context, options *metainternalversion.ListOptions) (watch.Interface, error) {
	return watch.NewFake(), nil
}
```

`Update` / `Delete` / `DeleteCollection` 与 `Create` 同形，只是错误文案不同（`:86-122`）。

Higress 三件套不走 CRD 形态：`apiserver.go:321-348` 用 `newLegacyAPIGroupInfo` 把 `extensions.higress.io/v1alpha1` 与 `networking.higress.io/v1` 注册成**内置 typed API group**，对象类型是 `go.mod:10` 的 `github.com/alibaba/higress/v2 v2.1.8` 里 `client/pkg/apis/{extensions/v1alpha1,networking/v1}` 的 Go struct（import 在 `:49-50`，`init():79` 于 `:95-96` 调 `AddToScheme`）。它们由 Scheme 直接编解码，**不需要 CRD schema**；那 5 个静态 YAML 只服务于 `customresourcedefinitions` 的 discovery——`:182-184` 特判后交给 `CreateCustomResourceDefinitionStorage`，其 `Create/Update/Delete/DeleteCollection` 一律返回 `NewServiceUnavailable`（`customresourcedefinition.go:86-122`），`Watch:124` 直接 `watch.NewFake()`，即 **CRD watch 恒不发事件**。Gateway API 四件套同理：`apiserver.go:351-375` 以 **v1beta1** 为存储版本，`:369-371` 让 v1beta1 / v1alpha2 / v1 **三个版本共享同一份 storages map**，靠 `converter.RegisterConverters(Scheme)`（`:200`）注册的 6 个 `RegisterUntypedConversionFunc`（`converter/gatewayapi.go:12-19`，三版本两两互转）完成版本适配；`go.mod:26` 声明 `sigs.k8s.io/gateway-api v1.0.0`、`:143` 却 replace 到 **v0.7.1**，正是这套"v1beta1 为中心 + 双向转换"结构的来源。

上面说的内置 typed API group 构造如下（`apiserver.go:321-327`、`:393-401`）。注意传给 `appendStorage` 的是 `&hiextensionsv1alpha1.WasmPlugin{}` 这样的 Go struct，而不是 CRD YAML：

```go
		hiextensionApiGroupInfo := newLegacyAPIGroupInfo(hiextensionsv1alpha1.SchemeGroupVersion.Group, Scheme, metav1.ParameterCodec)
		hiextensionv1alphaStorages := map[string]rest.Storage{}
		appendStorage(hiextensionv1alphaStorages, storageCreateFunc, hiextensionsv1alpha1.SchemeGroupVersion, true, "wasmplugin", "wasmplugins",
			func() runtime.Object { return &hiextensionsv1alpha1.WasmPlugin{} },
			func() runtime.Object { return &hiextensionsv1alpha1.WasmPluginList{} },
			nil, false)
```

```go
func newLegacyAPIGroupInfo(group string, scheme *runtime.Scheme, parameterCodec runtime.ParameterCodec) genericapiserver.APIGroupInfo {
	return genericapiserver.APIGroupInfo{
		PrioritizedVersions:          scheme.PrioritizedVersionsForGroup(group),
		VersionedResourcesStorageMap: map[string]map[string]rest.Storage{},
		// TODO unhardcode this.  It was hardcoded before, but we need to re-evaluate
		OptionsExternalVersion: &schema.GroupVersion{Version: "v1"},
		Scheme:                 scheme,
		ParameterCodec:         parameterCodec,
		NegotiatedSerializer:   LegacyNegotiatedSerializer,
	}
}
```

## Storage Factory

`completedConfig.New()`（`apiserver.go:151-391`）是整套形态的装配点，[Call Graph Internals](/docs/CS/Framework/Higress/Call_Graph_Internals.md) 的符号图里 `appendStorage` 被它调用 **21 次**、`newLegacyAPIGroupInfo` **4 次**，与逐行核对的资源表一一对应：

| API group | 资源 | 调用行 |
| --- | --- | --- |
| core/v1（legacy API group，`/api`） | configmaps / secrets / services / endpoints / pods / nodes / namespaces | `:205/:209/:224/:228/:232/:236/:240` |
| apiextensions.k8s.io/v1 | customresourcedefinitions | `:253` |
| admissionregistration.k8s.io/v1 | 两个 webhook configuration | `:266/:270` |
| authorization.k8s.io/v1 | subjectaccessreviews | **`:283` 直接赋值，不走 appendStorage** |
| discovery.k8s.io/v1 | endpointslices | `:293` |
| networking.k8s.io/v1 | ingresses / ingressclasses | `:306/:310` |
| extensions.higress.io/v1alpha1 | wasmplugins | `:323` |
| networking.higress.io/v1 | mcpbridges / http2rpcs | `:336/:340` |
| gateway.networking.k8s.io | gatewayclasses / gateways / httproutes / referencegrants | `:353/:357/:361/:365` |
| networking.istio.io/v1alpha3 | envoyfilters | `:380` |

准确口径是 11 个 APIGroupInfo、21 个经 `appendStorage` 注册的 storage，加 1 个直接挂载的 `subjectaccessreviews`。四个走 `newLegacyAPIGroupInfo` 的 group（`:321/:334/:351/:378`）都用 `codec.CreateLegacyNegotiatedSerializer(Scheme)` 作内容协商器（`apiserver.go:76`、`:401`），而不只是"legacy istio group"。`subjectaccessreviews` 是唯一绕过存储后端的资源（`&storage.SubjectAccessReviewStorage{}`），这也解释了 `--auth-enabled` 关掉后为何仍不报错。

所有资源共用一个工厂闭包 `storageCreateFunc`（`:172-198`），三条分支：① `groupResource == apiextensionsv1.Resource("customresourcedefinitions")` 时直接返回静态 storage，**完全绕开 file / nacos 后端**（`:182-184`）；② `Storage_File` 分支先把 codec 包成 `codec.NewFlatAwareCodec(groupResource, runtimeCodec)` 再交 `registry.NewFileREST`（`:187-188`）；③ `Storage_Nacos` 分支仅当 `sensitive=true` 时才把 `NacosOptions.EncryptionKey` 传进 `NewNacosREST`（`:190-194`），而 21 次 `appendStorage` 里只有 secrets 传了 true（`:223`）。非法 mode 走 `panic("invalid storage mode")`（`:196`），与 `options.go:84-91` 的校验是两道独立的门。

三条分支就写在 `apiserver.go:172-198` 的闭包里：

```go
	storageCreateFunc := func(
		groupResource schema.GroupResource,
		runtimeCodec runtime.Codec,
		isNamespaced bool,
		singularName string,
		newFunc func() runtime.Object,
		newListFunc func() runtime.Object,
		attrFunc genericstorage.AttrFunc,
		sensitive bool,
	) (rest.Storage, error) {
		if groupResource == apiextensionsv1.Resource("customresourcedefinitions") {
			return storage.CreateCustomResourceDefinitionStorage(runtimeCodec)
		}
		switch storageMode {
		case options.Storage_File:
			runtimeCodec = codec.NewFlatAwareCodec(groupResource, runtimeCodec)
			return registry.NewFileREST(groupResource, runtimeCodec, storageOptions.FileOptions.RootDir, extension, isNamespaced, singularName, newFunc, newListFunc, attrFunc)
		case options.Storage_Nacos:
			var encryptionKey []byte = nil
			if sensitive {
				encryptionKey = storageOptions.NacosOptions.EncryptionKey
			}
			return registry.NewNacosREST(groupResource, runtimeCodec, nacosConfigClient, isNamespaced, singularName, newFunc, newListFunc, attrFunc, encryptionKey), nil
		default:
			panic(fmt.Errorf("invalid storage mode: %s", storageMode))
		}
	}
```

## Storage Backends

CR 实例的持久层二选一（`pkg/apiserver/apiserver.go:188` NewFileREST / `:194` NewNacosREST；`pkg/options/options.go` 定义 `Storage_File="file"`、`Storage_Nacos="nacos"`，**默认 nacos**，填别的值直接报 "invalid storage mode"）：

- **file 后端**（`pkg/registry/file_rest.go`，704 行）：对象落盘成 `objRootPath/<resource小写>/<name>+extension`（`objectFileName:516-523`，**路径刻意忽略 namespace**，旁边还有被注释掉的分目录代码）；写盘是 `.tmp` + `os.Rename`（`:566`）；watch 靠 fsnotify（`startDirWatcher:122`、`notifyWatchers:225`）。根目录由 `--file-root-dir` 指定，默认 `./conf`。
- **Nacos 后端**（`pkg/registry/nacos_rest.go`，831 行）：用 nacos-sdk-go v2 的 config client，`dataId = <resource小写> + "." + names`（`:106`，分隔符常量在 `:42`），后台对"名单" dataId 做 `ListenConfig`（`watchNamesConfig:173`）再拉列表来模拟 watch；命名空间由 `--nacos-ns-id` 给定。相关默认：`NACOS_DISABLE_USE_SNAPSHOT=false`、`NACOS_LIST_REFRESH_INTERVAL_SECS=10`、`NACOS_CONFIG_SEARCH_PAGE_SIZE=50`。加密走 `--nacos-encryption-key-file`（compose 挂到 `/etc/api/nacos.key`，`docker-compose.yml:85-86`）配 `pkg/utils/encryption.go`。

⇒ 文档里"配置可以存独立 Nacos 或本地磁盘"这句话的真实含义是：**整个 K8s API 的对象存储被换成了 Nacos 配置项或一棵文件树**，Higress 主仓的 controller 只认 kubeconfig，不需要知道下面是什么。

## Codec Layer

`flat` 和 `legacy` 都不在 nacos 后端，也不是对象序列化格式。

- `legacy` 是 HTTP 内容协商器：`codec/legacy.go:14` 的 `CreateLegacyNegotiatedSerializer` 返回支持 `application/json`（含 pretty / strict 变体）与 `application/yaml`（含 strict 变体）的 `runtime.NegotiatedSerializer`，`EncoderForVersion` / `DecoderToVersion` 只包一层 `versioning.NewDefaultingCodecForScheme`（`:69-75`）。它赋给 `apiserver.go:76` 的包级变量 `LegacyNegotiatedSerializer`，只用在四个 `newLegacyAPIGroupInfo` 上（`:401`）。
- `flat` 是 file 后端专用、Ingress 专用的简写 codec：`codec/flat_codec.go:33-38` 的 `NewFlatAwareCodec` 仅在 `groupResource == networking.k8s.io/v1 ingresses` 时包一层 `flatIngressCodec`，其它资源原样返回 innerCodec；这个包装只出现在 `apiserver.go:187` 的 `Storage_File` 分支，**Nacos 分支完全不经过它**。

`flat` 包装器只有三个方法（`codec/flat_codec.go:29-71`，节选省去 `Identifier`），Encode 受开关控制、Decode 总是先试 flat：

```go
func init() {
	flatIngressEnabled, _ = strconv.ParseBool(os.Getenv("FLAT_INGRESS_ENABLED"))
}

func NewFlatAwareCodec(groupResource schema.GroupResource, innerCodec runtime.Codec) runtime.Codec {
	if v1IngressGvr.GroupResource() == groupResource {
		return &flatIngressCodec{groupResource: groupResource, innerCodec: innerCodec}
	}
	return innerCodec
}

func (c *flatIngressCodec) Encode(obj runtime.Object, w io.Writer) error {
	ingress, ok := obj.(*networkingv1.Ingress)
	if !ok || !flatIngressEnabled {
		return c.innerCodec.Encode(obj, w)
	}
	fIngress := toFlatIngress(ingress)
	return encodeFlatResource(fIngress, w)
}

func (c *flatIngressCodec) Decode(data []byte, defaults *schema.GroupVersionKind, into runtime.Object) (runtime.Object, *schema.GroupVersionKind, error) {
	fIngress := &flatIngress{}
	err := decodeFlatResource(data, fIngress)
	if err != nil {
		if errors.Is(err, nonFlatResourceError) {
			return c.innerCodec.Decode(data, defaults, into)
		}
		return nil, nil, err
	}
	ingress := fromFlatIngress(fIngress)
	ingress.APIVersion = v1IngressApiVersion
	ingress.Kind = v1IngressGvk.Kind
	return ingress, defaults, err
}
```

开关是环境变量 `FLAT_INGRESS_ENABLED`（`flat_codec.go:29-31`，默认 false）。`Encode`（`:45-52`）只在开关打开且对象确为 `*networkingv1.Ingress` 时走 `toFlatIngress` → JSON → YAML（`:73-84`）；`Decode`（`:58-71`）则**总是先试 flat**：`decodeFlatResource` 发现数据含 `apiVersion` + `kind` 就返回 `nonFlatResourceError` 回退 innerCodec，否则按 flat 结构解，再由 `fromFlatIngress` 强制补回 `networking.k8s.io/v1` / `Ingress`。所以同一棵文件树能混放标准 K8s YAML 与 flat 简写。

`flat_resources.go:32-40` 的 `flatIngress` 只保留 `labels` / `annotations` 与 `defaultBackend` / `tls` / `rules` 三段 spec，**没有 `name` / `namespace` / `ingressClassName`**：前两者由文件名承载（`objectFileName:516-523` 刻意忽略 namespace），后者是真的丢了。这给独立部署的 `--ingressClass=`（空，监听全部 Ingress，`compose/docker-compose.yml:130`、`all-in-one/scripts/start-controller.sh:35`）提供了源码侧解释——flat 格式下按 class 过滤无从判定。另有一处实现缺陷：`flatIngress.DeepCopyObject()`（`:46-69`）构造完 `out` 后 `return nil`，没有返回对象。

> [!WARNING]
> `FLAT_INGRESS_ENABLED` 全仓只在 `flat_codec.go:30` 出现一次，compose / all-in-one 的脚本与 `.env` 都**没有设置它** ⇒ 默认部署走标准 K8s YAML，flat 只是一条兼容旧文件格式的读取分支；上段关于 `ingressClassName` 丢失的推论只在显式开启时成立。

## Watch Simulation

两种后端都要伪造 K8s 的 `resourceVersion` 与 watch 语义，做法完全不同。

file 后端（`pkg/registry/file_rest.go`）：`startDirWatcher:122` 先 `visitDir` 建 `fileContentCache`，再用 fsnotify 监听目录；Create / Write 只记进 `pendingFileChanges`（`:167-178`），由 `fileChangeProcessTickerFunc:198` 以 **`fileChangeProcessInterval = 100ms`**（`:36`）的时间窗去抖后才 `read` 并判 Added / Modified 发事件（`:204-220`）；Remove / Rename 则**立即**删缓存并发 Deleted，不进去抖（`:179-195`）。`notifyWatchers:225` 直接 `w.ch <- ev`，没有丢弃策略。写盘是 `.tmp` + `O_EXCL` + `os.Rename`，对残留 `.tmp` 有 TTL 清理与一次重试（`:526-584`）。

去抖本身是一个按时间筛 pending 的循环（`file_rest.go:36`、`:198-222`）：

```go
const fileChangeProcessInterval = 100 * time.Millisecond

func (f *fileREST) fileChangeProcessTickerFunc() {
	f.fileChangeMutex.Lock()
	defer f.fileChangeMutex.Unlock()

	now := time.Now()

	pendingChangesToKeep := make(map[string]time.Time)
	for path, t := range f.pendingFileChanges {
		if now.Sub(t) < fileChangeProcessInterval {
			pendingChangesToKeep[path] = t
			continue
		}
		if obj, err := f.read(f.codec, path, f.newFunc); err == nil {
			eventType := watch.Modified
			if f.fileContentCache[path] == nil {
				eventType = watch.Added
			}
			f.fileContentCache[path] = obj
			f.notifyWatchers(watch.Event{
				Type:   eventType,
				Object: obj,
			})
		}
	}
	f.pendingFileChanges = pendingChangesToKeep
}
```

nacos 后端（`pkg/registry/nacos_rest.go`）：对象是 `dataId = <prefix>.<name>`（`:475-477`、分隔符常量 `:42`），**resourceVersion 用内容 MD5 模拟**——`decodeConfig:591-607` 读完后 `SetResourceVersion(calculateMd5(config))`，`write:609-633` 写完重算，并把旧 md5 作为 `CasMd5` 传给 `PublishConfig`（`writeRaw:635-648`）做乐观锁；写之前还会把 resourceVersion 清空、不落库（`:614-616`）。加密是 **AES + base64 URL 编码 + 前缀 `enc|`**（`encryptConfig:744-754`、常量 `:44`），解密时见到前缀却没有 key 直接报错（`:756-772`）；结合 Storage Factory 的 `sensitive` 门，**只有 Secret 会加密**。

MD5 同时充当 resourceVersion 与乐观锁的 CAS 值（`nacos_rest.go:591-648`，节选省去两行错误日志）：

```go
func (n *nacosREST) decodeConfig(decoder runtime.Decoder, config string, newFunc func() runtime.Object) (runtime.Object, error) {
	decryptedConfig, err := n.decryptConfig(config)
	if err != nil {
		return nil, err
	}
	obj, _, err := decoder.Decode([]byte(decryptedConfig), nil, newFunc())
	if err != nil {
		return nil, err
	}
	accessor, err := meta.Accessor(obj)
	if err == nil {
		accessor.SetResourceVersion(calculateMd5(config))
	}
	return obj, nil
}

func (n *nacosREST) write(encoder runtime.Encoder, group, dataId, oldMd5 string, obj runtime.Object) error {
	accessor, err := meta.Accessor(obj)
	if err != nil {
		return err
	}
	oldResourceVersion := accessor.GetResourceVersion()
	// No resource version saved into nacos
	accessor.SetResourceVersion("")

	buf := new(bytes.Buffer)
	if err := encoder.Encode(obj, buf); err != nil {
		return err
	}
	content, err := n.encryptConfig(buf.String())
	if err != nil {
		return err
	}
	err = n.writeRaw(group, dataId, content, oldMd5)
	if err == nil {
		accessor.SetResourceVersion(calculateMd5(content))
	} else {
		accessor.SetResourceVersion(oldResourceVersion)
	}
	return err
}

func (n *nacosREST) writeRaw(group, dataId, content, oldMd5 string) error {
	published, err := n.configClient.PublishConfig(vo.ConfigParam{
		DataId:  dataId,
		Group:   group,
		Content: content,
		CasMd5:  oldMd5,
	})
	if err != nil {
		return err
	} else if !published {
		return fmt.Errorf("failed to publish config %s", dataId)
	}
	return nil
}
```

加密与解密（`encryptionMark` 即前缀 `enc|`，`:44`）：

```go
func (n *nacosREST) encryptConfig(config string) (string, error) {
	if n.encryptionKey == nil {
		return config, nil
	}
	encryptedKeyData, err := utils.AesEncrypt([]byte(config), n.encryptionKey)
	if err != nil {
		return "", err
	}
	return encryptionMark + base64.URLEncoding.EncodeToString(encryptedKeyData), nil
}

func (n *nacosREST) decryptConfig(config string) (string, error) {
	if !strings.HasPrefix(config, encryptionMark) {
		return config, nil
	}
	if n.encryptionKey == nil {
		return "", errors.New("config data is encrypted, but no data encryption key is provided")
	}
	encryptedData, err := base64.URLEncoding.DecodeString(strings.TrimPrefix(config, encryptionMark))
	if err != nil {
		return "", err
	}
	decryptedData, err := utils.AesDecrypt(encryptedData, n.encryptionKey)
	if err != nil {
		return "", err
	}
	return string(decryptedData), nil
}
```

watch 模拟是两层：`Watch:479-515` 先 `List` 并把现有对象以 `Added` 全量回放，符合 informer 语义；`refreshConfigList:650-742` 用 `SearchConfig(Search:"blur", DataId: prefix+"*")` 枚举全部配置项，把 `group/dataId` 列表写成换行分隔的**名单配置**（`namesGroup` = Nacos `DEFAULT_GROUP`，`namesDataId` = `<prefix>.names`），`watchNamesConfig:173` 对这份名单 `ListenConfig`；同时对每个新对象单独 `ListenConfig` 发 `Modified`（`:704-719`）、对消失的对象 `CancelListenConfig` + `Deleted`（`:724-740`）。所谓用 `ListenConfig` 模拟 watch，实际是名单轮询加逐对象订阅，一次订阅并没有覆盖全部。

> [!NOTE]
> 与控制面对照：主仓 controller 侧的三个 debounce 字段是死字段、informer resync 为 0，而这里的 **100ms 文件去抖**发生在 apiserver 侧，是另一层，不能混为一谈。

## Compose Topology

唯一的编排文件是 `compose/docker-compose.yml`（444 行，网络 `higress-net`），**15 个服务**。`src/runner` 不是 supervisor 而是一个无代码的工具箱镜像（`FROM ubuntu` + curl / wget / openssl / xxd / jq / yq，`ENTRYPOINT ["/bin/bash"]`），被 initializer / precheck / prepare / postcheck 四个一次性服务复用，脚本从宿主机 `./scripts:/workspace` 挂载。

| 服务 | 镜像 | 宿主端口 | profile |
| --- | --- | --- | --- |
| nacos | `higress/nacos-server` | 8888→8080 控制台、8848、9848 | `nacos` |
| initializer / precheck / prepare / postcheck | `higress/runner` | — | 一次性 |
| apiserver | `higress/api-server` | 不映射（容器内 8443） | — |
| controller | 主仓 controller 镜像 | 不映射（健康 `:8888/ready`） | — |
| pilot | 主仓 pilot 镜像 | 不映射（健康 `:8080/ready`，`--monitoringAddr=:15014`） | — |
| gateway | 主仓 gateway 镜像 | 80、443、15020 | — |
| plugin-server | wasm 插件静态分发 | 不映射 | `plugin-server` |
| console | `higress/console` | **8080**→8080 | — |
| prometheus / promtail / loki / grafana | 观测四件套 | 均未映射宿主端口（Prometheus retention 6h） | — |

默认 `COMPOSE_PROFILES='nacos,plugin-server'`、`CONFIG_STORAGE='nacos'`，即默认真正常驻 ≈ **10 个容器**。启动顺序完全由 `depends_on` 条件串起来：precheck(`service_completed_successfully`) → apiserver(`service_healthy`) → prepare(completed) → controller(healthy) → pilot(healthy) → gateway + plugin-server → console(healthy) → prometheus / loki → grafana，postcheck 再等全链 healthy。

`compose/scripts/` 四个脚本的分工很能说明这套形态的性质：`precheck.sh`（64 行）用 **openssl 现生成 CA / server / client 三张证书**并写 kubeconfig；`init.sh`（238 行）登录 Nacos 取 accessToken、建命名空间；`prepare.sh`（774 行）**用 curl 直写 apiserver 来初始化 CR**——McpBridge、`nacos-auth-default` Secret、ConfigMap `higress-config`、GatewayClass / Gateway、prometheus.yaml；`postcheck.sh` 全文两行，echo 一句 "All good!"。controller 的启动参数也在这里可见：`serve --kubeconfig=... --gatewaySelectorKey=higress --gatewaySelectorValue=higress-system-higress-gateway --ingressClass= --enableAutomaticHttps=true`（`:125-133`）——注意 `--enableAutomaticHttps=true` 与主仓的 flag 默认值 false 相反（见 [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)）。

## All-in-One

`all-in-one/Dockerfile` 是多阶段构建，把主仓 release 的四个镜像（controller / pilot / gateway / plugin-server）**按 sha256 digest 烘焙进同一个容器**，ARG 记录 `CORE_VERSION=2.2.5`、`CONSOLE_VERSION=2.2.5`、`ENVOY_VERSION=2.2.5`、`APISERVER_VERSION=0.1.0`；另外 COPY 进 apiserver 二进制、console 的 `/app`、JDK、wasm 插件与 **supercronic**，apt 装 supervisor / logrotate / cron / nginx，`EXPOSE 8080 8443 8001`，入口是 `supervisord -c .../supervisord.conf`。

`all-in-one/supervisord/supervisord.conf`（127 行，`nodaemon=true`）编排 **10 个 program，按 priority 依次拉起**：apiserver(0) → plugin-server(50) → controller(100) → pilot(200) → gateway(300) → console(900) → prometheus(2000) / promtail(2100) / loki(2200) / grafana(3000)。每个 program 的 stdout 落到 **`/var/log/higress/<name>.log`**——文档说的容器内日志目录属实。

**all-in-one 与 compose 的本质差别是存储：只有 file 后端、没有 Nacos。** `all-in-one/scripts/start-apiserver.sh` 把 `/opt/data/defaultConfig` 拷进 `/data`，可选手工跑 `config-template/{ai-gateway,ai-proxy}.sh`，从 ConfigMap 抽数据到 `/etc/istio/config`，最后起 `apiserver --bind-address 127.0.0.1 --secure-port 18443 --storage file --file-root-dir /data`；kubeconfig 是**烘焙进镜像的静态文件**（`all-in-one/apiserver/config`，server 指向 `https://localhost:18443`、`insecure-skip-tls-verify: true`）。端口也不同：`start-controller.sh` 里 `GATEWAY_HTTP_PORT` 默认 **8080**、`GATEWAY_HTTPS_PORT` 默认 **8443**（compose 形态是 80 / 443），`USE_PLUGIN_SERVER=on` 时 MCP 插件地址指向 `http://localhost:8002/plugins/mcp-server/2.0.3/plugin.wasm`（plugin-server 的 nginx 监听 8002）。

**三个暴露端口的角色已坐实**：`EXPOSE 8080 8443 8001`（`all-in-one/Dockerfile:88`）中 **8080 = 网关 HTTP、8443 = 网关 HTTPS、8001 = Console**——证据是 `all-in-one/scripts/start-console.sh:15` 的 `CONSOLE_PORT=8001`、`all-in-one/get-ai-gateway.sh:34` 的 `DEFAULT_CONSOLE_PORT=8001` 与 `:1622` 的 `--console-port PORT (default: 8001)`，`all-in-one/config/mcpbridges/default.yaml:10` 也把 console 域名写成 `127.0.0.1:8001`。插件服务的 nginx 是 **8002**，与 8001 无关；此前"未找到 8001 监听方"的疑问由此解决。

> [!WARNING]
> **不存在 `MODE=full|gateway|console` 这样的进程裁剪开关。** 全仓（`*.go` / `*.sh` / `Dockerfile*`）检索 `MODE=` 只有两种语义：`bin/configure.sh` 的 `MODE="wizard"` / `MODE="params"`（交互式向导 vs 纯参数两种**配置录入模式**），以及 `test/configure/configure-test-runner.sh:87` 给 Nacos 容器传的 `MODE=standalone`（那是 Nacos 自己的环境变量）。`all-in-one/scripts/base.sh` 内也没有任何 MODE 分支。⇒ all-in-one 跑哪些进程，实际由 **supervisord 的 10 个 program + priority** 与 `all-in-one/scripts/start-*.sh`（13 个脚本）决定，不是靠一个环境变量切换。

## Plugin Distribution

all-in-one 里的"插件服务"把 OCI 产物摊平成静态 HTTP 目录，插件体系仍是同一套。`all-in-one/Dockerfile:11,19,47` 从 `higress/plugin-server:2.2.5@sha256:ec63c6…` 中 `COPY --from=plugin-server /usr/share/nginx/html/plugins`；`all-in-one/plugin-server/nginx.conf` 让它监听 **8002**、root 为 `/usr/share/nginx/html`、只额外开 `/healthz`；`start-plugin-server.sh:8-11` 在 `USE_PLUGIN_SERVER != on` 时直接退出，而 `base.sh:68-77` 缺省即 **on**（`bin/configure.sh:25` 交互默认 `Y`），`supervisord.conf:21-31` 给它 priority 50。

URL 改写发生在两个启动脚本：`start-console.sh:33-36` 把 `HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN` 设为 `http://localhost:8002/plugins/${name}/${version}/plugin.wasm`（仅当用户未自定义时）；`start-controller.sh:23-26` 把 `MCP_SERVER_WASM_IMAGE_URL` 设为 `http://localhost:8002/plugins/mcp-server/2.0.3/plugin.wasm`。Compose 形态同构但主机名与端口不同：`bin/configure.sh:652-666` 把 `plugin-server` 加进 `COMPOSE_PROFILES` 并写入 `http://plugin-server:8080/...` 模板，`compose/docker-compose.yml:237-247` 定义该服务（healthcheck 打 8080），`:206` 让 gateway 依赖它 healthy，`:136` / `:261` 把两个变量分别喂给 controller / console，`compose/.env:1,20-22` 默认就带这个 profile 与带 digest 的镜像。

内置插件的 CR 是启动时写出来的文件。`all-in-one/scripts/config-template/ai-gateway.sh:357-434` 往 `/data/wasmplugins/` 写三份 Higress `WasmPlugin` YAML：`ai-proxy.internal`（UNSPECIFIED / 100）、`ai-statistics-1.0.0`（UNSPECIFIED / 900）、`model-router.internal`（**AUTHN** / 900），均带 `resourceVersion: "1"`、`failStrategy: FAIL_OPEN` 与 localhost:8002 的 url。`start-apiserver.sh:41` 用 `--storage file --file-root-dir /data` ⇒ 它们就是 file 后端的 CR 对象，与 Watch Simulation 一节的 100ms fsnotify 去抖、controller 经 kubeconfig 读取衔接。`get-ai-gateway.sh:90-126` 的 `detectPluginRegistry()` 按时区选杭州 / 新加坡 / 美西 registry，只影响**关闭** plugin-server 时的 OCI 直拉。

主仓 Helm 默认 `enablePluginServer: false`，standalone 三种形态默认开启，差别只在"wasm 二进制从哪来"；`http[s]://` 是 `wasmplugin.proto:51-56` 原生支持的 scheme，控制面翻译代码一行没改。plugin-server 镜像由主仓 `plugins/release/snapshots/2.2.5.json` 按 digest 构建，完整链路见 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)。

## Configuration Tooling

`bin/base.sh` 探测 docker 并**明确拒绝 Compose v1**；`bin/startup.sh` 要求 `compose/.configured` 标记存在（由 configure 写入）后 `docker compose up -d`；`logs.sh` / `status.sh` / `shutdown.sh` / `restart.sh` / `reset.sh` 都是薄封装。核心是 `bin/configure.sh`（822 行），参数全集在 case 块 `:85-191`：

| 参数 | 存在性 | 默认 |
| --- | --- | --- |
| `--gateway-http-port` / `--gateway-https-port` / `--gateway-metrics-port` | 真实存在 | 80 / 443 / 15020（all-in-one 形态下 HTTP 默认改 8080） |
| `--console-port` | 真实存在 | 8080 |
| `-k, --data-enc-key` | 真实存在 | 未设则随机生成（记 `NACOS_USE_RANDOM_DATA_ENC_KEY`），**长度约束 32 字符**，集群部署必须显式设 |
| `-c, --config-url` | 真实存在 | 无默认；`nacos://host:8848` 或 `file:///opt/higress/conf` |
| `--use-builtin-nacos` | 真实存在（`:104`） | 关；置位则 profile 含 nacos（而 `.env` 默认就含） |
| `-r/--rerun`、`-a/--auto-start`、`-s/--storage`、`--nacos-ns`（默认 `higress-system`）、`--nacos-username/-password`、`--nacos-port/--nacos-console-port(8888)/--nacos-service-port(8848)`、`--use-plugin-server/--no-plugin-server` | 真实存在，**文档未列** | 见 `compose/.env` |

它的实际动作是：解析参数 → **整文件重写 `compose/.env`**（`:669` 起，含 COMPOSE_PROFILES / CONFIG_STORAGE / NACOS_* / 全部镜像 tag / `WASM_PLUGIN_URL_PATTERN` / `MCP_SERVER_WASM_URL` / 观测 tag / 四个端口）→ 跑 initializer 容器 → 写 `.configured` → `-a` 时调 `startup.sh`。开 plugin-server 时写入的是模板串 `http://plugin-server:8080/plugins/${name}/${version}/plugin.wasm`，与主仓侧的内置插件镜像地址替换是同一个占位符约定（见 [Plugin System](/docs/CS/Framework/Higress/Plugin.md)）。

一个容易混的点：本仓也有 `src/get-higress.sh`（279 行），但它与主仓的 `get-higress.sh` **同名不同物**——本仓的是安装器，只认 `-h` 与 `-u/--update`（`:38/:42`），VERSION 为空时去 GitHub releases 取最新 tag（`:179-185`）再下载 tar 包解包（`:193`），平台白名单 darwin / linux / windows × amd64 / arm64；**上面那串端口与凭据参数它全不吃**。文档若不区分两仓两个同名脚本，读者会把参数用到错的脚本上。

## Release Pinning

`release-provenance.json`（schemaVersion 1）是这套形态的可复现性凭据：`release{version: v2.2.5, commit: 4deae1dd…, releaseId: 403180124}`（**主仓 commit 就是 `Release v2.2.5` 的 HEAD**）、`snapshot{path: plugins/release/snapshots/2.2.5.json, sha256}`（各镜像共享同一 snapshot digest）、`mcpServerVersion: 2.0.3`、`standaloneBaseCommit`、`idempotencyKey`，以及 `images[]` 五组 digest（controller / gateway / pilot / plugin-server / console，各含 linux/amd64 + arm64，console 另有独立 commit 与 releaseId **403158311**）。

钉版机制是 `tools/render_release_pins.py`：`render()` 要求十个键（gatewayVersion / consoleVersion / pluginServerVersion / mcpServerVersion / snapshotSha256 / idempotencyKey / standaloneBaseCommit / gatewayImages / pluginServerRef / pluginServerDigest），**回写四个文件**——`all-in-one/Dockerfile`、`compose/.env`、`bin/configure.sh`、`all-in-one/scripts/start-controller.sh`——并生成本文说的 provenance 文件（配套 `tools/release_evidence.py` 与两个自测脚本）。本仓**不按 tag 去拉主仓的 crd.yaml**，CRD 是复制进 `src/apiserver/pkg/storage/crds/` 的快照。

顺带把版本线这件事收口：**console 有自己的 release 线**。本仓三处（Dockerfile 的 `CONSOLE_VERSION`、`compose/.env` 的 tag、provenance）一致是 **2.2.5**，而主仓 `DEP_VERSION` 写的是 `higress-console: v2.1.9`；`aio-v2.2.5` 这个 tag 也是本仓独立的前缀线。第三方组件只钉到 tag 不到 digest（nacos `v3.0.1`、prometheus `v2.40.7`、loki/promtail `2.9.4`、grafana `9.3.6`、runner `0.0.3`、api-server `0.1.0`），**只有主仓四件套 + console 钉到 digest**。

## Testing Reality

`test/` 只有 configure 一套：`configure-test.sh` 先 `bin/reset.sh` 再逐 case 跑 `configure-test-runner.sh`（对 external-nacos 类 case 会起一个真 Nacos 容器，pin `v2.2.3`，EXIT trap 清理），`cases/` 下 31 个 `.inc` 覆盖 `args-*`（builtin / external × full / console-port / data-enc-key / gateway-metrics-port / gateway-service-ports / nacos-ns / nacos-password / console-password）与 `input-*`（交互式输入等价类，含 Windows 路径用例）。**本质是"参数解析 → `.env` 产物"的冒烟与回归**，全仓没有任何打网关流量的 e2e。

至于 FAQ 说的"离线部署需要自行构建"：**仓内找不到这句 FAQ 文字**，能佐证的是每个组件都有可独立构建的 Makefile（`src/apiserver/`、`src/runner/`、`all-in-one/` 的 docker-build / docker-buildx-push），但镜像默认全量指向公网 ACR 且仓库不提供离线导入工具——方向成立，不构成文档承诺。

## Unverified

仍待核实：

- 本仓 5 个静态 CRD 与主仓 `helm/core/crds/`（三件套 + `istio-envoyfilter.yaml`）的字段级覆盖差异；console 客户端是否真的依赖 `customresourcedefinitions` 的 discovery 结果未跟踪。
- `bin/update.sh`（110 行，行数已核）的升级语义；`HIGRESS_CONSOLE_ACCESS_TOKEN` 的签发与校验机制（只记变量名，实现在独立的 console 仓）。
- `nacosREST` 的名单配置与逐对象订阅在并发写下的竞态、`NACOS_CACHE_SYNC_DELAY` 的实际默认值未实跑；`flatIngress.DeepCopyObject()` 返回 nil 在真实读写路径上是否被调用过未验证。
- `github.com/alibaba/higress/v2 v2.1.8` 与 standalone `aio-v2.2.5` 的版本差（CRD 类型来自更早的 minor）是否造成字段不一致，未做逐字段 diff。
- `plugin-server` 是独立仓库，本仓只烘焙它的产物镜像；`pull_plugins.py` 与 `unmanaged-plugins.lock.json` 的解包 / inventory 生成规则未读，主仓 workflow 只验证它们存在并跑单测。

已核并移入正文：`EXPOSE 8001` = Console（`start-console.sh:15`、`get-ai-gateway.sh:34`；插件 nginx 是 8002）；`MODE=full|gateway|console` 进程裁剪在全仓不存在，进程编排由 supervisord 的 10 个 program 与 13 个 `start-*.sh` 决定；21 次 `appendStorage` 加 4 个 legacy group 的精确资源表、CRD watch 恒空（`watch.NewFake()`）、只有 Secret 走 AES 加密、MD5 充当 resourceVersion 并配合 `CasMd5` 乐观锁；plugin-server 的 8002 / 8080 双形态、两处 URL 改写与三份内置插件 YAML 的生成路径已单列为 Plugin Distribution 节。

## Links

- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin.md)

## References

- [higress-standalone 仓库](https://github.com/higress-group/higress-standalone)
- [基于 Docker Compose 进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker-compose/)
- [基于 Docker 容器进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker/)
- [通过阿里云计算巢快速部署](https://higress.ai/docs/latest/ops/deploy-by-aliyun-computenest/)
- [查看日志](https://higress.ai/docs/latest/ops/how-tos/view-logs/)
