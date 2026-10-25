## Introduction

视频跟踪回答**同一个目标在相邻帧里是哪一个**。单帧检测把每帧当独立图像，输出没有身份连续性；跟踪在帧间建立关联，给每个目标分配跨帧一致的 ID。这是安防轨迹分析、车辆计数、行为分析、体育赛事分析的直接底座。

主流范式是**「检测 + 关联」两段式**：先用检测器逐帧出框，再在帧间匹配同一目标。检测质量决定上限，关联策略决定身份稳定性。检测机制见 [Detection](/docs/CS/AI/CV/Detection.md)，分割基础模型对跟踪的改造见 [Segmentation](/docs/CS/AI/CV/Segmentation.md)。

## Detection-Based Tracking

**SORT**（2016）是极简基线：卡尔曼滤波预测目标下一帧位置，匈牙利算法做检测与预测的贪心匹配，代价只用运动信息。快而简单，但遮挡后 ID 易变。

**DeepSORT**（2017）加入**外观特征**：用 ReID 网络对每个框提特征向量，匹配时代价 = 马氏距离（运动）+ 余弦距离（外观），还引入级联匹配与存活管理。遮挡和交叉场景的 ID 稳定性显著改善，代价是每帧多跑一个 ReID 前向。

**ByteTrack**（2022）的关键观察是：**低分框也是真目标**——遮挡、模糊的目标检测分数低，直接丢掉等于主动放弃。ByteTrack 把检测分高低两档，先用高分框匹配，再用剩余低分框与未匹配轨迹二次关联。小目标、遮挡密集场景提升明显，且不改变检测器本身。

| 方法 | 关联信息 | 特点 |
| ------ | ------ | ------ |
| SORT | 运动（卡尔曼） | 极简，ID 抖动敏感 |
| DeepSORT | 运动 + 外观 ReID | 遮挡鲁棒，多一次前向 |
| ByteTrack | 运动 + 低分框二次关联 | 密集/遮挡场景强，不动检测器 |
| OC-SORT / StrongSORT | 运动补偿 + 外观 | 面向遮挡与匀速假设失效的修正 |

**遮挡补偿**是关联阶段的常见增强：目标被遮期间运动模型外推不可靠，用观测驱动的修正（OC-SORT）或外观特征补偿（StrongSORT 的 AFLink/GSI 后处理）补轨迹。

## End-to-End Tracking

Transformer 路线把「检测 + 关联」合进单模型：query 跨帧传播，检测与跟踪联合训练。**MOTR / MeMOTR** 用跨帧注意力直接输出带 ID 的轨迹，免去显式匹配，但在长视频与遮挡下仍不如两段式稳。

SAM 3 则从另一侧统一了任务：内建检测器 + 跟踪器 + 存在性头，提示词即可跟踪视频中某概念的全部实例；SAM 3.1 的单次前向多对象复用把吞吐提到 32 FPS（H100），实时视频分析开始不必自建跟踪链路。

## Association Math

两段式的关联是一个**二分图最优匹配**问题：一侧是已存在的轨迹，一侧是本帧检测，边权重由代价函数给出，用匈牙利算法求全局最优。代价通常两项加权：

$$
c_{ij}=\lambda\cdot d_{\text{motion}}(i,j)+(1-\lambda)\cdot d_{\text{appearance}}(i,j)
$$

运动项用卡尔曼预测位置与检测框的马氏距离，并用**门控（gating）**把不可能匹配的组合直接置为无穷大；外观项用 ReID 特征的余弦距离。级联匹配让新出现的轨迹优先匹配近期观测，缓解身份跳变。

## ReID

行人/车辆重识别（ReID）是外观特征的来源：度量学习把同一 ID 的图像映到相近向量、不同 ID 推远，常用三元组损失。Market-1501 等基准上已相当成熟，工业上更关心跨摄像头域差异（光照、视角、分辨率）。

## Metrics

跟踪指标比检测多一层身份维度：

- **MOTA / MOTP**：综合漏检、误检、ID 跳变的传统指标
- **IDF1**：身份保留率，匹配到的轨迹占真值/预测的比例
- **HOTA**：把指标拆成检测（DetA）× 关联（AssA）两项，位置误差单独报告——比 MOTA 更能定位问题出在检测还是关联

## Video Analytics Pipeline

工程链路不是逐帧独立识别，而是**抽帧 → 检测 → 跟踪 → 事件聚合**：跟踪输出稳定轨迹后才谈得上"车辆逆行""徘徊""跨线"这类事件；事件层做时序平滑与去抖，避免逐帧抖动直接触发告警。抽帧策略（关键帧 vs 均匀降采样，帧采样口径见 [Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md)）与延迟预算共同决定链路成本，部署细节见 [Deployment](/docs/CS/AI/CV/Deployment.md)。

## Links

- [CV](/docs/CS/AI/CV.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Segmentation](/docs/CS/AI/CV/Segmentation.md)
- [Metrics](/docs/CS/AI/CV/Metrics.md)
- [Deployment](/docs/CS/AI/CV/Deployment.md)

## References

1. [Simple Online and Realtime Tracking (SORT)](https://arxiv.org/abs/1602.00763)
2. [Simple Online and Realtime Tracking with a Deep Association Metric (DeepSORT)](https://arxiv.org/abs/1703.07402)
3. [ByteTrack: Multi-Object Tracking by Associating Every Detection Box](https://arxiv.org/abs/2110.06864)
4. [Observation-Centric SORT (OC-SORT)](https://arxiv.org/abs/2203.14360)
5. [MOTR: End-to-End Multi-Object Tracking with Transformer](https://arxiv.org/abs/2105.01947)
6. [SAM 3: Segment Anything with Concepts](https://arxiv.org/abs/2511.16719)
