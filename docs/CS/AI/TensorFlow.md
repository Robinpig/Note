## Introduction

TensorFlow（TF）是 Google Brain 2015 年开源的深度学习框架，名字来源于多维数组（tensor）在计算图上的流动。它最早以**静态计算图**（先 `tf.Graph` 构图、再在 Session 中喂数据执行）为核心，部署能力（Serving、Lite、TFLite、TF.js）覆盖云端到嵌入式，曾是工业界绝对主流；2.x 起默认 **Eager Execution**（逐行立即执行）并以 Keras 为高层 API，开发体验向 [PyTorch](/docs/CS/AI/PyTorch.md) 靠拢。当前研究社区以 PyTorch 为主，TF 更多见于存量工业部署、移动端/浏览器端和 TPU 生态。

## 核心抽象

- **Tensor**：同类型多维数组，对标 `np.ndarray`，但可驻留 GPU/TPU 且参与自动微分。
- **tf.Graph / tf.function**：`@tf.function` 装饰器把 Python 函数追踪（trace）成静态图，图模式去掉解释器开销、可做算子融合，并能导出 SavedModel 跨语言部署。这是"用 eager 调试、用图模式上线"的双模式设计。
- **Variable**：可被优化器更新的张量，模型权重都用它承载。
- **GradientTape**：eager 模式下记录前向运算、反向求梯度的上下文管理器。
- **Keras**：官方高层 API，`Model`/`Layer`/`Dense`/`Conv2D` 等积木，`model.fit()` 封装训练循环；也支持自定义 `train_step` 实现复杂损失。

```python
import tensorflow as tf

model = tf.keras.Sequential([
    tf.keras.layers.Dense(128, activation="relu"),
    tf.keras.layers.Dense(10),
])
model.compile(optimizer="adam",
              loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
              metrics=["accuracy"])
model.fit(x_train, y_train, epochs=5, batch_size=256,
          validation_data=(x_val, y_val))
```

## 数据管道：tf.data

`tf.data.Dataset` 是 TF 区别于早期 PyTorch 的强项：声明式描述数据变换，框架自动做并行预取：

```python
ds = (tf.data.Dataset.from_tensor_slices((x, y))
        .shuffle(10000).batch(256)
        .map(preprocess, num_parallel_calls=tf.data.AUTOTUNE)
        .prefetch(tf.data.AUTOTUNE))   # 训练 step n 时准备 step n+1
```

大数据场景配合 `tf.train.Example`（Protobuf）+ TFRecord 顺序文件格式，比大量小图文件的随机 IO 高效得多。

## 生态

| 组件 | 用途 |
|------|------|
| TensorBoard | 训练可视化（loss、计算图、直方图、embedding projector） |
| SavedModel / TF Serving | 模型序列化格式与生产级模型服务（版本管理、gRPC/REST、A/B） |
| TensorFlow Lite | 手机/嵌入式：量化（INT8）、FlatBuffer 格式、GPU/NPU delegate |
| TensorFlow.js | 浏览器/Node.js 中推理与再训练（WebGL/WebGPU 后端） |
| Keras 3 | 2024 起 Keras 成为多后端框架，可切 TF/Torch/JAX |
| XLA | 线性代数编译器，融合算子、生成 TPU/GPU 专用机器码 |
| TFX | 端到端生产流水线（ExampleGen→Transform→Trainer→Pusher） |

## TF 1.x 静态图 vs 2.x Eager

| 维度 | TF 1.x 静态图 | TF 2.x Eager |
|------|---------------|--------------|
| 执行方式 | 先构图后 Session.run | 定义即执行，可 print/断点 |
| 调试 | 难，需要 tfdbg | 接近普通 Python |
| 性能 | 图优化充分 | 靠 @tf.function 回退到图模式 |
| 控制流 | tf.cond/tf.while | 原生 Python 语法（AutoGraph 转换） |

## 与 PyTorch 的取舍

- PyTorch：动态图（define-by-run）、Pythonic、研究生态（论文实现、Hugging Face 首选）、分布式训练体验后来居上。
- TF：图/SavedModel 部署链路成熟、TFLite/JS 端侧全家桶、TPU 原生支持；代价是 API 历史包袱重（1.x/2.x 割裂、estimator 已废弃）。
- 新立项的经验法则：**研究复现/大模型选 PyTorch；已有 TF 基建、浏览器或极低端端侧推理可继续 TF；ONNX 是两边共用的交换格式**。

## Links

- [AI](/docs/CS/AI/AI.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [CNN](/docs/CS/AI/CNN.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)

## References

1. [TensorFlow 官方教程](https://www.tensorflow.org/tutorials)
2. [Keras 官方文档](https://keras.io/)
