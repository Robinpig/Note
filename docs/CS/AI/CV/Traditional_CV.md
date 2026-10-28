## Introduction

深度学习之前，视觉的主流范式是**手工设计特征 + 传统分类器**：人先把图像中的边缘、角点、纹理抽象成数值描述子，再交给 [SVM](/docs/CS/AI/ML/SVM.md) 之类的分类器。这套方法在 2012 年后整体退出主战场，但远未消亡——SLAM 的视觉里程计前端、图像拼接、文档矫正、工业规则质检仍在用它，理由是可解释、无需训练数据、CPU 上跑得动。

理解传统 CV 还有一层认知价值：今天深度网络里的卷积核、多尺度、特征匹配，思想源头都在这里。

## Image Filtering

- **线性滤波**：高斯模糊（可分离卷积，先横向再纵向，复杂度从 $O(r^2)$ 降到 $O(r)$），用于去噪与构建尺度空间
- **非线性滤波**：中值滤波对椒盐噪声远好于高斯，且保边缘
- **形态学**：腐蚀/膨胀（取邻域极值），开运算（先腐后胀，去小白点）闭运算（先胀后腐，补小黑洞），是二值掩码后处理的标准操作
- **图像金字塔**：高斯金字塔逐层降采样，拉普拉斯金字塔存残差可无损重建——多尺度分析的经典结构，FPN 的思想祖先

## Edge Detection

梯度算子的局限是方向相关且噪敏。**Canny**（1986）给出完整方案，四步走：

1. 高斯平滑去噪
2. Sobel 求梯度幅值与方向
3. 非极大值抑制：沿梯度方向只保留局部极大，把粗边压成细边
4. 双阈值 + 滞后连接：高于高阈值的强边直接保留，介于两阈值间的弱边仅在与强边连通时保留

**LoG/DoG**（高斯差分）先用高斯模糊不同尺度相减再找零交叉点，天然带尺度选择，是 SIFT 的构建块。

## Corner Detection

**Harris 角点**用结构张量的两个特征值判断局部是平坦、边缘还是角点：角点处两个方向梯度都大。响应函数：

$$
R=\det(M)-k\cdot(\mathrm{tr}(M))^2,\quad M=\sum w\begin{bmatrix}I_x^2 & I_xI_y\\ I_xI_y & I_y^2\end{bmatrix}
$$

FAST 用圆周上 16 像素的亮度比较，速度快一个量级，是 ORB 的检测器。

## Local Features

**SIFT**（1999，专利 2020 年到期）是尺度不变特征的集大成者：DoG 构建尺度空间找极值点 → 精确定位与边缘抑制 → 主方向赋值保证旋转不变 → 128 维描述子。SURF 用积分图近似加速。**ORB** 换用 oFAST + 旋转感知的 rBRIEF 二值描述子，免专利、快一个量级，是长期开源默认。

| 特征 | 描述子 | 专利 | 速度 | 现状 |
| ------ | ------ | ------ | ------ | ------ |
| SIFT | 128 维浮点 | 已到期 | 慢 | 拼接/重建精度基准 |
| SURF | 64/128 维浮点 | 有 | 中 | 逐步被替代 |
| ORB | 256 位二值 | 无 | 快 | 开源默认，实时 SLAM 常用 |

**HOG**（2005）不走"关键点 + 描述子"路线，而是密采样的方向梯度直方图：细胞归一化 + 块级对比度归一化，连 SVM 做行人检测，是深度学习之前最成功的检测器。

**霍夫变换**用参数空间投票检测直线/圆：边缘点在各参数组合上累加，局部极大即对应形状，对遮挡与断裂鲁棒，是车道线检测的经典手段。

## Still in Service

- **图像拼接/全景**：SIFT/ORB 提特征 → 描述子匹配 → RANSAC 估单应矩阵 → 加权融合，仍是主流离线流程
- **SLAM 视觉前端**：ORB-SLAM 系列用 ORB 做跟踪与建图，惯性/视觉里程计在机器人上仍大量服役
- **文档处理**：透视矫正、表格线检测、二值化
- **工业质检**：模板匹配、Blob 分析、缺陷规则判定——训练数据稀缺时的性价比之王

## Bridge to the Deep Era

边界正在模糊。**学习式特征**（SuperPoint、DISK、ALIKED）直接回归关键点与描述子；**稠密匹配**（LoFTR）用 Transformer 跨图注意力免去"先检测再匹配"；LightGlue 做快速匹配后处理。OpenCV 5（2026-06 发布）的新 Features 模块把这些神经特征与 SIFT/ORB 并列收纳——传统与深度从此共存于同一 API，见 [Deployment](/docs/CS/AI/CV/Deployment.md)。

## Links

- [CV](/docs/CS/AI/CV/CV.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Representation Learning](/docs/CS/AI/CV/Representation_Learning.md)
- [Deployment](/docs/CS/AI/CV/Deployment.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [Distinctive Image Features from Scale-Invariant Keypoints (SIFT)](https://www.cs.ubc.ca/~lowe/papers/ijcv04.pdf)
2. [ORB: An efficient alternative to SIFT or SURF](https://arxiv.org/abs/1911.05703)
3. [OpenCV 5 发布说明](https://opencv.org/opencv-5/)
