## Introduction

训练出的模型只是半成品。上线要过四关：**导出**（训练框架 → 部署格式）、**加速**（图优化 + 量化 + 剪枝）、**运行时**（TensorRT/OpenVINO/NCNN 按硬件选）、**服务化**（批处理、流水线、多路视频）。每一关都能把延迟砍一个量级，也每一关都能引入"训练时没有"的精度损失。

本篇讲通用部署链路；YOLO/SAM 的具体导出命令见 [Detection](/docs/CS/AI/CV/Detection.md) 与 [Segmentation](/docs/CS/AI/CV/Segmentation.md)。

## Export

标准链路是 **PyTorch → ONNX → 厂商运行时**：

```python
model.eval()
torch.onnx.export(model, dummy_input, "net.onnx",
                  opset_version=17, input_names=["images"],
                  dynamic_axes={"images": {0: "batch"}})   # 动态 batch
```

- **opset**：定 ONNX 算子集版本，越高支持的算子越多；部署端老运行时可能不认识新算子，取双方交集
- **动态轴**：batch 动态最常用；检测的变长输出（框数不定）要小心，NMS 放图内还是图外直接影响能否直接导出
- **onnxsim**：导出后跑一遍简化（常量折叠、冗余消除），经常白赚 10–20% 延迟

训练时的预处理（resize、归一化）要么写进 ONNX 图，要么在部署端用同一套参数复刻（口径见 [Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md)）——两边不一致是经典事故源。

## Quantization

量化把 FP32 权重/激活降到 INT8，收益：模型体积 1/4、整数指令吞吐数倍、功耗降。两档做法：

- **PTQ（训练后量化）**：校准集跑前向统计每层激活范围（min-max / 熵 / 百分位），直接定 scale。零成本，但对激活分布敏感的层（Transformer 的 attention、检测头）掉点明显
- **QAT（量化感知训练）**：前向插入 fake-quant 节点、反向用 STE（直通估计器）传梯度，让模型学会适应量化误差。掉点可控在 1% 内，代价是训练周期与调参

粒度上 per-channel 逐通道 scale 远好于 per-tensor；**混合精度**（只量化骨干、检测头保 FP16）是精度崩坏时的标准退路。FP16 是另一条更安全的加速路：几乎无损、几乎所有 GPU/NPU 原生支持，通常作为第一步。

## Pruning and Distillation

- **剪枝**：非结构化剪枝产出稀疏权重，需硬件/运行时支持稀疏计算才有时延收益，否则只是模型变小；**结构化剪枝**（整通道裁掉）通用性好，配合微调恢复精度
- **蒸馏**：用大模型（教师）的输出或中间特征监督小模型（学生），是无损压缩的主力。视觉领域的标杆用法：**RT-DETRv4**（2025-11，ECCV 2026）用 DINOv3 ViT-B/16-LVD-1689M 当教师蒸馏轻量检测器（自监督表示学习路线见 [Representation Learning](/docs/CS/AI/CV/Representation_Learning.md)），S 档在 T4 上 49.8 AP/3.66 ms——不增推理延迟把视觉基础模型的能力搬进实时检测器，详见 [Detection](/docs/CS/AI/CV/Detection.md)

## Runtimes

| 运行时 | 适用硬件 | 特点 |
| ------ | ------ | ------ |
| TensorRT | NVIDIA GPU | 图优化 + 内核自动选择，延迟下限；需为卡型构建 engine |
| OpenVINO | Intel CPU/GPU/NPU | 异步流水线，CPU 上优化深 |
| ONNX Runtime | 跨平台 | 通用兜底，Execution Provider 接各硬件后端 |
| NCNN / MNN | 手机 ARM | 移动端事实标准，内存占用敏感场景 |
| OpenCV 5 DNN | CPU 通用 | 新引擎 ONNX 覆盖率从 4.x 的约两成提到六成以上，能直接跑 ViT/VLM |

OpenCV 5（2026-06 发布）的新 DNN 引擎值得注意：重写为类型化操作图，支持 If/Loop 子图、动态形状、QDQ 量化图，Attention 与 MatMul 融合；官方基准下 CPU 上比 ONNX Runtime 快约 25–37%（OWLv2、DINOv2、BiRefNet 等），还能直接跑 Qwen、Gemma、PaliGemma 一类 VLM——省掉一套推理框架，见 [Traditional CV](/docs/CS/AI/CV/Traditional_CV.md)。

## Latency Engineering

量化与选型之外，延迟工程是纯软件手段：

- **图融合**：Conv+BN 折叠、常量折叠、算子融合（element-wise 链合成一个 kernel）——onnxsim 与各运行时会做大部分
- **NMS 外移**：把 NMS 放在部署端而非图内，图内只留原始输出，避免动态形状拖慢整个图；端到端模型（YOLO26 一对一模式、RT-DETR）则相反——图内自带匹配，无 NMS 最干净
- **切片推理**：高分辨率大图切 patch 分别推理再合并（RT-DETR 官方支持 sliced inference），小目标场景比缩图强得多
- **batch 与流**：视频场景用多路摄像头共享 batch；GPU 上动态 shape 触发重编译，尽量固定输入档位

## Serving

单机推理之外，服务化关注三件事：**吞吐**（动态批处理把零散请求攒成 batch）、**流水线**（检测 → 跟踪 → 事件聚合分段解耦，任一段可独立扩缩，见 [Tracking](/docs/CS/AI/CV/Tracking.md)）、**版本**（模型灰度、回滚、AB）。Triton 一类推理服务器提供模型仓库 + 并发批处理 + 指标，是多模型生产的常见选择。

> [!WARNING]
>
> Ultralytics 系模型（YOLOv5/v8/v11/v26）是 **AGPL-3.0**：SaaS 与内部网络服务同样触发开源义务，商用需采购 Enterprise 许可。选型时把许可证当一等公民评估。

## Links

- [CV](/docs/CS/AI/CV/CV.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Tracking](/docs/CS/AI/CV/Tracking.md)
- [Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md)
- [Traditional CV](/docs/CS/AI/CV/Traditional_CV.md)

## References

1. [ONNX 官方文档](https://onnx.ai/)
2. [TensorRT 官方文档](https://docs.nvidia.com/tensorrt/)
3. [OpenCV 5 发布说明](https://opencv.org/opencv-5/)
4. [RT-DETRv4 仓库](https://github.com/RT-DETRs/RT-DETRv4)
5. [Ultralytics 导出文档](https://docs.ultralytics.com/modes/export/)
