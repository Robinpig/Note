## Introduction

设备插件框架（Device Plugin）让 K8s 把**非 CPU/内存的硬件资源**（GPU、FPGA、NIC、SSD、TPU）暴露给 Pod。它解决的是：调度器原生只认 cpu/memory，专用硬件需要一套标准机制来登记、调度、挂载。

机制：厂商提供实现了 `DevicePlugin` gRPC 接口的插件，以 DaemonSet 跑在每个节点；插件向 **kubelet** 注册设备，kubelet 把设备记作**扩展资源（Extended Resource）**（如 `nvidia.com/gpu`），上报到节点 `status.allocatable`。

## Flow

```
厂商 Device Plugin (DaemonSet, 每节点)
   │  Register → kubelet（Unix socket，/var/lib/kubelet/device-plugins/）
   ▼
kubelet 上报 Extended Resource 到 node.status.allocatable
   ▼
Pod 在 limits 里请求 nvidia.com/gpu: 1
   ▼
scheduler 按扩展资源选节点（节点有空闲 GPU 才调度）
   ▼
kubelet 调插件 Allocate → 设备挂载进容器（GPU 字符设备、驱动库）
```

Pod 侧：

```yaml
resources:
  limits:
    nvidia.com/gpu: 1     # 扩展资源，整数（整卡）
```

## GPU Example

- **NVIDIA**：`NVIDIA Device Plugin` 暴露 `nvidia.com/gpu`；配合 **NVIDIA Container Toolkit**（让容器能访问 GPU 驱动与字符设备）。支持整卡，或分数卡（MIG 切分、Time-Slicing 共享）。
- **AMD**：ROCm Device Plugin 暴露 `amd.com/gpu`。
- 容器内需装对应 GPU 驱动/运行库（CUDA 等），镜像自带或由节点提供。

## Limitations

- 扩展资源**不可压缩、不可超卖、只能整数**（默认按整卡请求）；分数靠厂商方案（MIG / Time-Slicing）实现，不是 K8s 原生。
- device 只能放 `limits` 不能放 `requests`（扩展资源无 QoS 概念，请求即上限）。
- 设备故障/隔离：插件可把设备标为不可用，kubelet 停止分配；已分配的 Pod 不受影响直到重启。
- 多卡拓扑：默认调度只看数量，不看 NVLink/PCIe 亲和；拓扑感知需调度器插件（如 Volcano）或节点标签 + `nodeSelector`/亲和。

## Beyond GPU

同一框架覆盖：Intel GPU、FPGA、SR-IOV 网卡（网络加速）、本地 NVMe（通过本地存储类）、TPU 等。核心都是"节点上发现硬件 → 注册扩展资源 → Pod 请求 → 分配时挂载"。

## Links

- [资源模型 requests/limits](/docs/CS/Container/k8s/Resource.md)
- [调度器](/docs/CS/Container/k8s/scheduler.md)
- [弹性扩缩容](/docs/CS/Container/k8s/Scaling.md)
- [容器运行时 CRI-O](/docs/CS/Container/k8s/CRI-O.md)

## References

1. [Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)
2. [NVIDIA Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)
3. [Schedule GPUs](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)
