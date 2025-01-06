## Introduction



client-go是一个调用kubernetes集群资源对象API的客户端，即通过client-go实现对kubernetes集群中资源对象（包括deployment、service、ingress、replicaSet、pod、namespace、node等）的增删改查等操作
大部分对kubernetes进行前置API封装的二次开发都通过client-go这个第三方包来实现

client-go` 支持四种客户端对象，分别是 `RESTClient`，`ClientSet`，`DynamicClient` 和 `DiscoveryClient
其中，`RESTClient` 是最基础的客户端对象，它封装了 `HTTP Request`，实现了 `RESTful` 风格的 `API`。
`ClientSet` 基于 `RESTClient`，封装了对于 `Resource` 和 `Version` 的请求方法。
`DynamicClient` 相比于 `ClientSet` 提供了全资源，包括自定义资源的请求方法
。`DiscoveryClient` 用于发现 `kube-apiserver` 支持的资源组，资源版本和资源信息。

每种客户端适用的场景不同，主要是对 `HTTP Request` 做了层层封装


kubeconfig用于管理访问kube-apiserver的配置信息
默认情况下 kubeconfig存放在`$HOME/.kube/config`文件中


```go
// veendor/k8s.io/client-go/tools/clientcmd/loader.go
// Load starts by running the MigrationRules and then
// takes the loading rules and returns a Config object based on following rules.
//   if the ExplicitPath, return the unmerged explicit file
//   Otherwise, return a merged config based on the Precedence slice
// A missing ExplicitPath file produces an error. Empty filenames or other missing files are ignored.
// Read errors or files with non-deserializable content produce errors.
// The first file to set a particular map key wins and map key's value is never changed.
// BUT, if you set a struct value that is NOT contained inside of map, the value WILL be changed.
// This results in some odd looking logic to merge in one direction, merge in the other, and then merge the two.
// It also means that if two files specify a "red-user", only values from the first file's red-user are used.  Even
// non-conflicting entries from the second file's "red-user" are discarded.
// Relative paths inside of the .kubeconfig files are resolved against the .kubeconfig file's parent folder
// and only absolute file paths are returned.
func (rules *ClientConfigLoadingRules) Load() (*clientcmdapi.Config, error) {
	if err := rules.Migrate(); err != nil {
		return nil, err
	}

	errlist := []error{}

	kubeConfigFiles := []string{}

	// Make sure a file we were explicitly told to use exists
	if len(rules.ExplicitPath) > 0 {
		if _, err := os.Stat(rules.ExplicitPath); os.IsNotExist(err) {
			return nil, err
		}
		kubeConfigFiles = append(kubeConfigFiles, rules.ExplicitPath)

	} else {
		kubeConfigFiles = append(kubeConfigFiles, rules.Precedence...)
	}

	kubeconfigs := []*clientcmdapi.Config{}
	// read and cache the config files so that we only look at them once
	for _, filename := range kubeConfigFiles {
		if len(filename) == 0 {
			// no work to do
			continue
		}

		config, err := LoadFromFile(filename)
		if os.IsNotExist(err) {
			// skip missing files
			continue
		}
		if err != nil {
			errlist = append(errlist, fmt.Errorf("Error loading config file \"%s\": %v", filename, err))
			continue
		}

		kubeconfigs = append(kubeconfigs, config)
	}

	// first merge all of our maps
	mapConfig := clientcmdapi.NewConfig()

	for _, kubeconfig := range kubeconfigs {
		mergo.Merge(mapConfig, kubeconfig)
	}

	// merge all of the struct values in the reverse order so that priority is given correctly
	// errors are not added to the list the second time
	nonMapConfig := clientcmdapi.NewConfig()
	for i := len(kubeconfigs) - 1; i >= 0; i-- {
		kubeconfig := kubeconfigs[i]
		mergo.Merge(nonMapConfig, kubeconfig)
	}

	// since values are overwritten, but maps values are not, we can merge the non-map config on top of the map config and
	// get the values we expect.
	config := clientcmdapi.NewConfig()
	mergo.Merge(config, mapConfig)
	mergo.Merge(config, nonMapConfig)

	if rules.ResolvePaths() {
		if err := ResolveLocalPaths(config); err != nil {
			errlist = append(errlist, err)
		}
	}
	return config, utilerrors.NewAggregate(errlist)
}
```

## Clients


### RESTClient

```go
// veendor/k8s.io/client-go/rest/config.go
// RESTClientFor returns a RESTClient that satisfies the requested attributes on a client Config
// object. Note that a RESTClient may require fields that are optional when initializing a Client.
// A RESTClient created by this method is generic - it expects to operate on an API that follows
// the Kubernetes conventions, but may not be the Kubernetes API.
func RESTClientFor(config *Config) (*RESTClient, error) {
	if config.GroupVersion == nil {
		return nil, fmt.Errorf("GroupVersion is required when initializing a RESTClient")
	}
	if config.NegotiatedSerializer == nil {
		return nil, fmt.Errorf("NegotiatedSerializer is required when initializing a RESTClient")
	}
	qps := config.QPS
	if config.QPS == 0.0 {
		qps = DefaultQPS
	}
	burst := config.Burst
	if config.Burst == 0 {
		burst = DefaultBurst
	}

	baseURL, versionedAPIPath, err := defaultServerUrlFor(config)
	if err != nil {
		return nil, err
	}

	transport, err := TransportFor(config)
	if err != nil {
		return nil, err
	}

	var httpClient *http.Client
	if transport != http.DefaultTransport {
		httpClient = &http.Client{Transport: transport}
		if config.Timeout > 0 {
			httpClient.Timeout = config.Timeout
		}
	}

	return NewRESTClient(baseURL, versionedAPIPath, config.ContentConfig, qps, burst, config.RateLimiter, httpClient)
}

```


```go

// Do formats and executes the request. Returns a Result object for easy response
// processing.
//
// Error type:
//  * If the request can't be constructed, or an error happened earlier while building its
//    arguments: *RequestConstructionError
//  * If the server responds with a status: *errors.StatusError or *errors.UnexpectedObjectError
//  * http.Client.Do errors are returned directly.
func (r *Request) Do() Result {
	r.tryThrottle()

	var result Result
	err := r.request(func(req *http.Request, resp *http.Response) {
		result = r.transformResponse(resp, req)
	})
	if err != nil {
		return Result{err: err}
	}
	return result
}
```

request

```go
// request connects to the server and invokes the provided function when a server response is
// received. It handles retry behavior and up front validation of requests. It will invoke
// fn at most once. It will return an error if a problem occurred prior to connecting to the
// server - the provided function is responsible for handling server errors.
func (r *Request) request(fn func(*http.Request, *http.Response)) error {
	//Metrics for total request latency
	start := time.Now()
	defer func() {
		metrics.RequestLatency.Observe(r.verb, r.finalURLTemplate(), time.Since(start))
	}()

	if r.err != nil {
		glog.V(4).Infof("Error in request: %v", r.err)
		return r.err
	}

	// TODO: added to catch programmer errors (invoking operations with an object with an empty namespace)
	if (r.verb == "GET" || r.verb == "PUT" || r.verb == "DELETE") && r.namespaceSet && len(r.resourceName) > 0 && len(r.namespace) == 0 {
		return fmt.Errorf("an empty namespace may not be set when a resource name is provided")
	}
	if (r.verb == "POST") && r.namespaceSet && len(r.namespace) == 0 {
		return fmt.Errorf("an empty namespace may not be set during creation")
	}

	client := r.client
	if client == nil {
		client = http.DefaultClient
	}

	// Right now we make about ten retry attempts if we get a Retry-After response.
	// TODO: Change to a timeout based approach.
	maxRetries := 10
	retries := 0
	for {
		url := r.URL().String()
		req, err := http.NewRequest(r.verb, url, r.body)
		if err != nil {
			return err
		}
		if r.ctx != nil {
			req = req.WithContext(r.ctx)
		}
		req.Header = r.headers

		r.backoffMgr.Sleep(r.backoffMgr.CalculateBackoff(r.URL()))
		if retries > 0 {
			// We are retrying the request that we already send to apiserver
			// at least once before.
			// This request should also be throttled with the client-internal throttler.
			r.tryThrottle()
		}
		resp, err := client.Do(req)
		updateURLMetrics(r, resp, err)
		if err != nil {
			r.backoffMgr.UpdateBackoff(r.URL(), err, 0)
		} else {
			r.backoffMgr.UpdateBackoff(r.URL(), err, resp.StatusCode)
		}
		if err != nil {
			// "Connection reset by peer" is usually a transient error.
			// Thus in case of "GET" operations, we simply retry it.
			// We are not automatically retrying "write" operations, as
			// they are not idempotent.
			if !net.IsConnectionReset(err) || r.verb != "GET" {
				return err
			}
			// For the purpose of retry, we set the artificial "retry-after" response.
			// TODO: Should we clean the original response if it exists?
			resp = &http.Response{
				StatusCode: http.StatusInternalServerError,
				Header:     http.Header{"Retry-After": []string{"1"}},
				Body:       ioutil.NopCloser(bytes.NewReader([]byte{})),
			}
		}

		done := func() bool {
			// Ensure the response body is fully read and closed
			// before we reconnect, so that we reuse the same TCP
			// connection.
			defer func() {
				const maxBodySlurpSize = 2 << 10
				if resp.ContentLength <= maxBodySlurpSize {
					io.Copy(ioutil.Discard, &io.LimitedReader{R: resp.Body, N: maxBodySlurpSize})
				}
				resp.Body.Close()
			}()

			retries++
			if seconds, wait := checkWait(resp); wait && retries < maxRetries {
				if seeker, ok := r.body.(io.Seeker); ok && r.body != nil {
					_, err := seeker.Seek(0, 0)
					if err != nil {
						glog.V(4).Infof("Could not retry request, can't Seek() back to beginning of body for %T", r.body)
						fn(req, resp)
						return true
					}
				}

				glog.V(4).Infof("Got a Retry-After %s response for attempt %d to %v", seconds, retries, url)
				r.backoffMgr.Sleep(time.Duration(seconds) * time.Second)
				return false
			}
			fn(req, resp)
			return true
		}()
		if done {
			return nil
		}
	}
}
```
### ClientSet

ClientSet 对比RESTClient使用更加便捷
 
```go
func NewForConfig(c *rest.Config) (*CoreV1Client, error) {
	config := *c
	if err := setConfigDefaults(&config); err != nil {
		return nil, err
	}
	client, err := rest.RESTClientFor(&config)
	if err != nil {
		return nil, err
	}
	return &CoreV1Client{client}, nil
}
```


```go
type Clientset struct {
	*discovery.DiscoveryClient
	admissionregistration *admissionregistrationinternalversion.AdmissionregistrationClient
	core                  *coreinternalversion.CoreClient
	apps                  *appsinternalversion.AppsClient
	authentication        *authenticationinternalversion.AuthenticationClient
	authorization         *authorizationinternalversion.AuthorizationClient
	autoscaling           *autoscalinginternalversion.AutoscalingClient
	batch                 *batchinternalversion.BatchClient
	certificates          *certificatesinternalversion.CertificatesClient
	events                *eventsinternalversion.EventsClient
	extensions            *extensionsinternalversion.ExtensionsClient
	networking            *networkinginternalversion.NetworkingClient
	policy                *policyinternalversion.PolicyClient
	rbac                  *rbacinternalversion.RbacClient
	scheduling            *schedulinginternalversion.SchedulingClient
	settings              *settingsinternalversion.SettingsClient
	
```


CoreV1Client
```go
// CoreV1Client is used to interact with features provided by the  group.
type CoreV1Client struct {
	restClient rest.Interface
}
```
CoreV1Interface中包含了各种kubernetes对象的调用接口，例如PodsGetter是对kubernetes中pod对象增删改查操作的接口。ServicesGetter是对service对象的操作的接口

```go
type CoreV1Interface interface {
	RESTClient() rest.Interface
	ComponentStatusesGetter
	ConfigMapsGetter
	EndpointsGetter
	EventsGetter
	LimitRangesGetter
	NamespacesGetter
	NodesGetter
	PersistentVolumesGetter
	PersistentVolumeClaimsGetter
	PodsGetter
	PodTemplatesGetter
	ReplicationControllersGetter
	ResourceQuotasGetter
	SecretsGetter
	ServicesGetter
	ServiceAccountsGetter
}



### DynamicClient



## informer



`informer` 机制的核心组件包括：

```
  Reflector
```

  : 主要负责两类任务：

  1. 通过 `client-go` 客户端对象 list `kube-apiserver` 资源，并且 watch `kube-apiserver` 资源变更。
  2. 作为生产者，将获取的资源放入 `Delta FIFO` 队列。

```


## Informer


主要负责三类任务：

1. 作为消费者，将 `Reflector` 放入队列的资源拿出来。
2. 将资源交给 `indexer` 组件。
3. 交给 `indexer` 组件之后触发回调函数，处理回调事件。

`Indexer`: `indexer` 组件负责将资源信息存入到本地内存数据库（实际是 `map` 对象），该数据库作为缓存存在，
其资源信息和 `ETCD` 中的资源信息完全一致（得益于 `watch` 机制）。
因此，`client-go` 可以从本地 `indexer` 中读取相应的资源，而不用每次都从 `kube-apiserver` 中获取资源信息
这也实现了 `client-go` 对于实时性的要求。







## Links

- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

