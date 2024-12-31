

## Introduction



```go
func (o *Options) Run() error {
	if len(o.WriteConfigTo) > 0 {
		return o.writeConfigFile()
	}

	proxyServer, err := NewProxyServer(o)
	if err != nil {
		return err
	}

	return proxyServer.Run()
}
```








## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)

